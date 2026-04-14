"""Script: check_bedrock.py

Verify Amazon Bedrock model access for LLM inference.

Tests:
  1. Bedrock runtime client creation
  2. Model access — invoke Claude Sonnet 3.5 with a simple prompt
  3. Response parsing (validate JSON structure)
  4. Token count extraction

Does NOT test embeddings — see check_embedding.py for that.

Usage:
    uv run python scripts/check_bedrock.py
"""

from __future__ import annotations

import json
import sys
import time

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

import boto3  # noqa: E402
from botocore.exceptions import ClientError, NoCredentialsError  # noqa: E402

from config.settings import get_settings  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    """Print a check result."""
    status = "[PASS]" if passed else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


def check_bedrock() -> None:
    """Run all Bedrock LLM access checks."""
    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS — Amazon Bedrock LLM Check")
    print(f"  Region:          {settings.bedrock_region}")
    print(f"  Primary Model:   {settings.bedrock_model_id}")
    print(f"  Fallback Model:  {settings.bedrock_fallback_model_id}")
    print(f"  Max Tokens:      {settings.bedrock_max_tokens}")
    print(f"  Temperature:     {settings.bedrock_temperature}")
    print()

    # --- Check 1: Create Bedrock runtime client ---
    try:
        client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
        print_check("Bedrock runtime client", True)
    except NoCredentialsError:
        print_check("Bedrock runtime client", False, "No AWS credentials found")
        return
    except Exception as e:
        print_check("Bedrock runtime client", False, str(e))
        return

    # --- Check 2: List available foundation models ---
    try:
        bedrock_mgmt = boto3.client("bedrock", region_name=settings.bedrock_region)
        response = bedrock_mgmt.list_foundation_models(
            byProvider="Anthropic",
            byOutputModality="TEXT",
        )
        models = response.get("modelSummaries", [])
        model_ids = [m["modelId"] for m in models]
        print_check(
            "Anthropic models available",
            True,
            f"{len(model_ids)} model(s)",
        )
        for mid in model_ids[:5]:
            print(f"          - {mid}")
        if len(model_ids) > 5:
            print(f"          ... and {len(model_ids) - 5} more")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "AccessDeniedException":
            print_check("List foundation models", False, "Access denied — check IAM permissions")
        else:
            print_check("List foundation models", False, str(e))

    # --- Check 3: Invoke primary model (Claude Sonnet) ---
    test_prompt = "Reply with exactly: VQMS_HEALTH_CHECK_OK"
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 50,
            "temperature": 0.0,
            "messages": [
                {"role": "user", "content": test_prompt},
            ],
        })

        start = time.perf_counter()
        response = client.invoke_model(
            modelId=settings.bedrock_model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        elapsed = (time.perf_counter() - start) * 1000

        result = json.loads(response["body"].read())
        response_text = result.get("content", [{}])[0].get("text", "").strip()
        input_tokens = result.get("usage", {}).get("input_tokens", 0)
        output_tokens = result.get("usage", {}).get("output_tokens", 0)

        print_check(
            f"Invoke {settings.bedrock_model_id}",
            True,
            f"{elapsed:.0f}ms",
        )
        print(f"          Response:      \"{response_text[:80]}\"")
        print(f"          Input tokens:  {input_tokens}")
        print(f"          Output tokens: {output_tokens}")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "AccessDeniedException":
            print_check(
                f"Invoke {settings.bedrock_model_id}",
                False,
                "Access denied — model not enabled in Bedrock console",
            )
        elif code == "ValidationException":
            print_check(
                f"Invoke {settings.bedrock_model_id}",
                False,
                f"Validation error — {e.response['Error']['Message']}",
            )
        else:
            print_check(f"Invoke {settings.bedrock_model_id}", False, str(e))
    except Exception as e:
        print_check(f"Invoke {settings.bedrock_model_id}", False, str(e))

    # --- Check 4: Invoke fallback model (Claude Haiku) ---
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 50,
            "temperature": 0.0,
            "messages": [
                {"role": "user", "content": test_prompt},
            ],
        })

        start = time.perf_counter()
        response = client.invoke_model(
            modelId=settings.bedrock_fallback_model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        elapsed = (time.perf_counter() - start) * 1000

        result = json.loads(response["body"].read())
        response_text = result.get("content", [{}])[0].get("text", "").strip()

        print_check(
            f"Invoke {settings.bedrock_fallback_model_id}",
            True,
            f"{elapsed:.0f}ms",
        )
        print(f"          Response: \"{response_text[:80]}\"")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "AccessDeniedException":
            print_check(
                f"Invoke {settings.bedrock_fallback_model_id}",
                False,
                "Access denied — fallback model not enabled",
            )
        else:
            print_check(f"Invoke {settings.bedrock_fallback_model_id}", False, str(e))
    except Exception as e:
        print_check(f"Invoke {settings.bedrock_fallback_model_id}", False, str(e))

    print(f"\n{'=' * 60}\n")


def main() -> None:
    """Run the check."""
    check_bedrock()


if __name__ == "__main__":
    main()
