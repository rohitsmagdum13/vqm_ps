"""Script: check_embedding.py

Verify Amazon Bedrock Titan Embed v2 for vector embeddings.

Tests:
  1. Bedrock runtime client creation
  2. Generate embedding for a test sentence
  3. Validate embedding dimensions (1536 for Titan Embed v2)
  4. Verify vector values are normalized (L2 norm ≈ 1.0)

This is separate from check_bedrock.py because embedding uses
a different model (Titan) and different API payload format.

Usage:
    uv run python scripts/check_embedding.py
"""

from __future__ import annotations

import json
import math
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


def check_embedding() -> None:
    """Run all Bedrock embedding checks."""
    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS — Amazon Bedrock Embedding Check")
    print(f"  Region:     {settings.bedrock_region}")
    print(f"  Model:      {settings.bedrock_embedding_model_id}")
    print(f"  Dimensions: {settings.bedrock_embedding_dimensions}")
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

    # --- Check 2: Generate embedding for test text ---
    test_text = "What is the status of my invoice INV-2026-0042 from last month?"
    try:
        body = json.dumps({
            "inputText": test_text,
            "dimensions": settings.bedrock_embedding_dimensions,
        })

        start = time.perf_counter()
        response = client.invoke_model(
            modelId=settings.bedrock_embedding_model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        elapsed = (time.perf_counter() - start) * 1000

        result = json.loads(response["body"].read())
        embedding = result.get("embedding", [])
        input_tokens = result.get("inputTextTokenCount", 0)

        print_check(
            f"Invoke {settings.bedrock_embedding_model_id}",
            True,
            f"{elapsed:.0f}ms",
        )
        print(f"          Input tokens: {input_tokens}")
        print(f"          Test text:    \"{test_text[:60]}...\"")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "AccessDeniedException":
            print_check(
                f"Invoke {settings.bedrock_embedding_model_id}",
                False,
                "Access denied — model not enabled in Bedrock console",
            )
        else:
            print_check(f"Invoke {settings.bedrock_embedding_model_id}", False, str(e))
        return
    except Exception as e:
        print_check(f"Invoke {settings.bedrock_embedding_model_id}", False, str(e))
        return

    # --- Check 3: Validate dimensions ---
    expected_dims = settings.bedrock_embedding_dimensions
    actual_dims = len(embedding)
    dims_ok = actual_dims == expected_dims
    print_check(
        "Embedding dimensions",
        dims_ok,
        f"Expected {expected_dims}, got {actual_dims}",
    )

    # --- Check 4: Validate values are normalized ---
    if embedding:
        l2_norm = math.sqrt(sum(v * v for v in embedding))
        normalized = abs(l2_norm - 1.0) < 0.01
        print_check(
            "Vector normalization (L2 norm ≈ 1.0)",
            normalized,
            f"L2 norm = {l2_norm:.6f}",
        )

        # Show first 5 values as a sanity check
        preview = [f"{v:.6f}" for v in embedding[:5]]
        print(f"          First 5 values: [{', '.join(preview)}, ...]")

    # --- Check 5: Generate a second embedding and compute similarity ---
    similar_text = "Can you check on invoice INV-2026-0042 payment status?"
    try:
        body2 = json.dumps({
            "inputText": similar_text,
            "dimensions": settings.bedrock_embedding_dimensions,
        })
        response2 = client.invoke_model(
            modelId=settings.bedrock_embedding_model_id,
            body=body2,
            contentType="application/json",
            accept="application/json",
        )
        result2 = json.loads(response2["body"].read())
        embedding2 = result2.get("embedding", [])

        # Cosine similarity
        dot = sum(a * b for a, b in zip(embedding, embedding2))
        norm1 = math.sqrt(sum(v * v for v in embedding))
        norm2 = math.sqrt(sum(v * v for v in embedding2))
        similarity = dot / (norm1 * norm2) if norm1 > 0 and norm2 > 0 else 0.0

        # Similar texts should have high similarity (> 0.7)
        sim_ok = similarity > 0.7
        print_check(
            "Cosine similarity (similar texts)",
            sim_ok,
            f"{similarity:.4f}",
        )
        print(f"          Text A: \"{test_text[:50]}...\"")
        print(f"          Text B: \"{similar_text[:50]}...\"")

    except Exception as e:
        print_check("Cosine similarity test", False, str(e))

    print(f"\n{'=' * 60}\n")


def main() -> None:
    """Run the check."""
    check_embedding()


if __name__ == "__main__":
    main()
