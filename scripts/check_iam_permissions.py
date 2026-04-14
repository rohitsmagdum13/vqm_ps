# ruff: noqa: E402
"""Script: check_iam_permissions.py

Inspect IAM policies for the current AWS credentials (vqms-dev) and
verify access to Bedrock, Textract, and embedding models.

What this script does:
  1. Identifies the current IAM identity (user or role)
  2. Lists all attached policies (managed + inline)
  3. Shows policy document details (allowed actions/resources)
  4. Tests real access to Bedrock (ListFoundationModels, InvokeModel)
  5. Tests real access to Textract (DetectDocumentText)
  6. Tests real access to Bedrock embeddings (InvokeModel with Titan)

Usage:
    uv run python scripts/check_iam_permissions.py
"""

from __future__ import annotations

import json
import sys
import time

# ---------------------------------------------------------------------------
# Bootstrap -- must happen before project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

import os

import boto3
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    NoCredentialsError,
)

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
HEADER = "\033[1m"
RESET = "\033[0m"
DIM = "\033[90m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"


def print_header(title: str) -> None:
    print(f"\n{HEADER}{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}{RESET}")


def print_subheader(title: str) -> None:
    print(f"\n  {HEADER}{'-' * 55}")
    print(f"  {title}")
    print(f"  {'-' * 55}{RESET}")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    suffix = f" — {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


def print_warn(name: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  {WARN} {name}{suffix}")


def print_info(text: str) -> None:
    print(f"  {INFO} {text}")


# ---------------------------------------------------------------------------
# Step 1: Identify current IAM identity
# ---------------------------------------------------------------------------

def identify_caller(region: str) -> dict | None:
    """Get the current IAM identity via STS GetCallerIdentity.

    Returns dict with Account, Arn, UserId, or None if auth fails.
    """
    print_header("Step 1: IAM Identity (Who Am I?)")

    try:
        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        arn = identity["Arn"]
        account = identity["Account"]
        user_id = identity["UserId"]

        print_check("STS GetCallerIdentity", True)
        print(f"         ARN:      {arn}")
        print(f"         Account:  {account}")
        print(f"         UserId:   {user_id}")

        # Determine if it's a user, role, or assumed-role
        if ":user/" in arn:
            entity_type = "IAM User"
            entity_name = arn.split(":user/")[-1]
        elif ":assumed-role/" in arn:
            entity_type = "Assumed Role"
            entity_name = arn.split(":assumed-role/")[-1].split("/")[0]
        elif ":role/" in arn:
            entity_type = "IAM Role"
            entity_name = arn.split(":role/")[-1]
        else:
            entity_type = "Unknown"
            entity_name = arn

        print(f"         Type:     {entity_type}")
        print(f"         Name:     {entity_name}")

        return {
            "arn": arn,
            "account": account,
            "user_id": user_id,
            "entity_type": entity_type,
            "entity_name": entity_name,
        }

    except NoCredentialsError:
        print_check("STS GetCallerIdentity", False, "No credentials found")
        print("         Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
        return None
    except ClientError as e:
        print_check("STS GetCallerIdentity", False, e.response["Error"]["Message"])
        return None


# ---------------------------------------------------------------------------
# Step 2: List IAM policies attached to the identity
# ---------------------------------------------------------------------------

def list_user_policies(iam_client, username: str) -> None:
    """List all policies (managed + inline) attached to an IAM user."""
    print_subheader(f"Managed Policies for User: {username}")

    try:
        response = iam_client.list_attached_user_policies(UserName=username)
        policies = response.get("AttachedPolicies", [])

        if policies:
            for i, policy in enumerate(policies, 1):
                print(f"\n    {i}. {policy['PolicyName']}")
                print(f"       ARN: {policy['PolicyArn']}")

                # Fetch the policy document to see actual permissions
                _show_policy_document(iam_client, policy["PolicyArn"])
        else:
            print("    No managed policies attached.")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "AccessDeniedException"):
            print_warn("ListAttachedUserPolicies", "Access denied — cannot list managed policies")
        elif code == "NoSuchEntity":
            print_warn("ListAttachedUserPolicies", f"User '{username}' not found")
        else:
            print_warn("ListAttachedUserPolicies", f"{code}: {e.response['Error']['Message']}")

    # Inline policies
    print_subheader(f"Inline Policies for User: {username}")

    try:
        response = iam_client.list_user_policies(UserName=username)
        policy_names = response.get("PolicyNames", [])

        if policy_names:
            for name in policy_names:
                print(f"\n    Policy: {name}")
                try:
                    doc_response = iam_client.get_user_policy(
                        UserName=username, PolicyName=name
                    )
                    doc = doc_response.get("PolicyDocument", {})
                    _print_policy_statements(doc)
                except ClientError:
                    print(f"       {DIM}(Could not read policy document){RESET}")
        else:
            print("    No inline policies.")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "AccessDeniedException"):
            print_warn("ListUserPolicies", "Access denied — cannot list inline policies")
        else:
            print_warn("ListUserPolicies", f"{code}: {e.response['Error']['Message']}")

    # Group memberships
    print_subheader(f"Group Memberships for User: {username}")

    try:
        response = iam_client.list_groups_for_user(UserName=username)
        groups = response.get("Groups", [])

        if groups:
            for group in groups:
                group_name = group["GroupName"]
                print(f"\n    Group: {group_name}")

                # List group's managed policies
                try:
                    gp_response = iam_client.list_attached_group_policies(GroupName=group_name)
                    group_policies = gp_response.get("AttachedPolicies", [])
                    if group_policies:
                        for gp in group_policies:
                            print(f"       Managed: {gp['PolicyName']}")
                            _show_policy_document(iam_client, gp["PolicyArn"], indent=10)
                    else:
                        print(f"       {DIM}No managed policies on this group{RESET}")
                except ClientError:
                    print(f"       {DIM}(Could not list group policies){RESET}")

                # List group's inline policies
                try:
                    gi_response = iam_client.list_group_policies(GroupName=group_name)
                    inline_names = gi_response.get("PolicyNames", [])
                    for ip_name in inline_names:
                        print(f"       Inline: {ip_name}")
                        try:
                            ip_doc = iam_client.get_group_policy(
                                GroupName=group_name, PolicyName=ip_name
                            )
                            _print_policy_statements(
                                ip_doc.get("PolicyDocument", {}), indent=10
                            )
                        except ClientError:
                            pass
                except ClientError:
                    pass
        else:
            print("    Not a member of any groups.")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "AccessDeniedException"):
            print_warn("ListGroupsForUser", "Access denied — cannot list group memberships")
        else:
            print_warn("ListGroupsForUser", f"{code}: {e.response['Error']['Message']}")


def list_role_policies(iam_client, role_name: str) -> None:
    """List all policies (managed + inline) attached to an IAM role."""
    print_subheader(f"Managed Policies for Role: {role_name}")

    try:
        response = iam_client.list_attached_role_policies(RoleName=role_name)
        policies = response.get("AttachedPolicies", [])

        if policies:
            for i, policy in enumerate(policies, 1):
                print(f"\n    {i}. {policy['PolicyName']}")
                print(f"       ARN: {policy['PolicyArn']}")
                _show_policy_document(iam_client, policy["PolicyArn"])
        else:
            print("    No managed policies attached.")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "AccessDeniedException"):
            print_warn("ListAttachedRolePolicies", "Access denied")
        else:
            print_warn("ListAttachedRolePolicies", f"{code}: {e.response['Error']['Message']}")

    # Inline policies
    print_subheader(f"Inline Policies for Role: {role_name}")

    try:
        response = iam_client.list_role_policies(RoleName=role_name)
        policy_names = response.get("PolicyNames", [])

        if policy_names:
            for name in policy_names:
                print(f"\n    Policy: {name}")
                try:
                    doc_response = iam_client.get_role_policy(
                        RoleName=role_name, PolicyName=name
                    )
                    doc = doc_response.get("PolicyDocument", {})
                    _print_policy_statements(doc)
                except ClientError:
                    print(f"       {DIM}(Could not read policy document){RESET}")
        else:
            print("    No inline policies.")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "AccessDeniedException"):
            print_warn("ListRolePolicies", "Access denied")
        else:
            print_warn("ListRolePolicies", f"{code}: {e.response['Error']['Message']}")


def _show_policy_document(iam_client, policy_arn: str, indent: int = 7) -> None:
    """Fetch and display the default version of a managed policy."""
    prefix = " " * indent
    try:
        policy_info = iam_client.get_policy(PolicyArn=policy_arn)
        version_id = policy_info["Policy"]["DefaultVersionId"]

        version = iam_client.get_policy_version(
            PolicyArn=policy_arn, VersionId=version_id
        )
        document = version["PolicyVersion"]["Document"]
        _print_policy_statements(document, indent=indent)

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "AccessDeniedException"):
            print(f"{prefix}{DIM}(Cannot read policy document — access denied){RESET}")
        else:
            print(f"{prefix}{DIM}(Error reading policy: {code}){RESET}")


def _print_policy_statements(document: dict, indent: int = 7) -> None:
    """Pretty-print the statements from an IAM policy document."""
    prefix = " " * indent
    statements = document.get("Statement", [])

    for stmt in statements:
        effect = stmt.get("Effect", "?")
        actions = stmt.get("Action", [])
        resources = stmt.get("Resource", [])
        conditions = stmt.get("Condition", {})

        # Normalize to lists
        if isinstance(actions, str):
            actions = [actions]
        if isinstance(resources, str):
            resources = [resources]

        # Color the effect
        effect_colored = f"{GREEN}{effect}{RESET}" if effect == "Allow" else f"{RED}{effect}{RESET}"

        print(f"{prefix}Effect: {effect_colored}")

        # Show actions (truncate if too many)
        if len(actions) <= 15:
            for action in actions:
                print(f"{prefix}  Action: {action}")
        else:
            for action in actions[:10]:
                print(f"{prefix}  Action: {action}")
            print(f"{prefix}  ... +{len(actions) - 10} more actions")

        # Show resources (truncate if too many)
        if len(resources) <= 5:
            for resource in resources:
                print(f"{prefix}  Resource: {resource}")
        else:
            for resource in resources[:3]:
                print(f"{prefix}  Resource: {resource}")
            print(f"{prefix}  ... +{len(resources) - 3} more resources")

        # Show conditions if present
        if conditions:
            print(f"{prefix}  Condition: {json.dumps(conditions, indent=2)[:200]}")

        print()


# ---------------------------------------------------------------------------
# Step 3: Search for vqms-dev user/role specifically
# ---------------------------------------------------------------------------

def search_for_vqms_dev(iam_client, region: str) -> str | None:
    """Search for 'vqms-dev' as an IAM user or role.

    Returns the entity name if found, None otherwise.
    """
    print_header("Step 2: Search for 'vqms-dev' Entity")

    # Try as IAM user
    try:
        response = iam_client.get_user(UserName="vqms-dev")
        user = response["User"]
        print_check("IAM User 'vqms-dev'", True, "Found")
        print(f"         ARN:     {user['Arn']}")
        print(f"         Created: {user['CreateDate']}")
        return "user:vqms-dev"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchEntity":
            print_info("IAM User 'vqms-dev' — does not exist")
        elif code in ("AccessDenied", "AccessDeniedException"):
            print_warn("IAM GetUser('vqms-dev')", "Access denied — cannot check")
        else:
            print_warn("IAM GetUser('vqms-dev')", f"{code}")

    # Try as IAM role
    try:
        response = iam_client.get_role(RoleName="vqms-dev")
        role = response["Role"]
        print_check("IAM Role 'vqms-dev'", True, "Found")
        print(f"         ARN:     {role['Arn']}")
        print(f"         Created: {role['CreateDate']}")
        return "role:vqms-dev"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchEntity":
            print_info("IAM Role 'vqms-dev' — does not exist")
        elif code in ("AccessDenied", "AccessDeniedException"):
            print_warn("IAM GetRole('vqms-dev')", "Access denied — cannot check")
        else:
            print_warn("IAM GetRole('vqms-dev')", f"{code}")

    # Search through users list for partial match
    print_info("Searching for users/roles containing 'vqms'...")
    found_entities: list[str] = []

    try:
        paginator = iam_client.get_paginator("list_users")
        for page in paginator.paginate():
            for user in page.get("Users", []):
                if "vqms" in user["UserName"].lower():
                    found_entities.append(f"User: {user['UserName']} ({user['Arn']})")
    except ClientError:
        print_warn("ListUsers", "Cannot search users — access denied")

    try:
        paginator = iam_client.get_paginator("list_roles")
        for page in paginator.paginate():
            for role in page.get("Roles", []):
                if "vqms" in role["RoleName"].lower():
                    found_entities.append(f"Role: {role['RoleName']} ({role['Arn']})")
    except ClientError:
        print_warn("ListRoles", "Cannot search roles — access denied")

    if found_entities:
        print(f"\n    Found {len(found_entities)} entity(ies) matching 'vqms':")
        for entity in found_entities:
            print(f"      - {entity}")
    else:
        print_info("No IAM users or roles found matching 'vqms'")

    return None


# ---------------------------------------------------------------------------
# Step 4: Test actual access to VQMS-critical services
# ---------------------------------------------------------------------------

def test_bedrock_access(region: str) -> None:
    """Test access to Amazon Bedrock (management + runtime APIs)."""
    print_header("Step 4: Bedrock Access (LLM + Embeddings)")

    # 4a. List foundation models (management API)
    print_subheader("4a. Bedrock Management API")
    try:
        bedrock = boto3.client("bedrock", region_name=region)
        response = bedrock.list_foundation_models()
        models = response.get("modelSummaries", [])
        print_check("ListFoundationModels", True, f"{len(models)} models available")

        # Check for specific models we need
        claude_models = [
            m for m in models
            if "claude" in m.get("modelId", "").lower()
        ]
        titan_embed_models = [
            m for m in models
            if "titan" in m.get("modelId", "").lower()
            and "embed" in m.get("modelId", "").lower()
        ]

        if claude_models:
            print(f"\n    Claude models available ({len(claude_models)}):")
            for m in claude_models[:15]:
                model_id = m["modelId"]
                status = m.get("modelLifecycle", {}).get("status", "?")
                status_indicator = GREEN + status + RESET if status == "ACTIVE" else RED + status + RESET
                print(f"      - {model_id}  [{status_indicator}]")
            if len(claude_models) > 15:
                print(f"      ... +{len(claude_models) - 15} more")
        else:
            print_warn("No Claude models found", "Check model access in Bedrock console")

        if titan_embed_models:
            print(f"\n    Titan Embed models available ({len(titan_embed_models)}):")
            for m in titan_embed_models:
                model_id = m["modelId"]
                status = m.get("modelLifecycle", {}).get("status", "?")
                status_indicator = GREEN + status + RESET if status == "ACTIVE" else RED + status + RESET
                print(f"      - {model_id}  [{status_indicator}]")
        else:
            print_warn("No Titan Embed models found", "Check model access in Bedrock console")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "AccessDeniedException"):
            print_check("ListFoundationModels", False, "Access denied to Bedrock management API")
        else:
            print_check("ListFoundationModels", False, f"{code}: {e.response['Error']['Message']}")

    # 4b. Test InvokeModel with Claude (runtime API)
    print_subheader("4b. Bedrock Runtime — Claude LLM Invoke")

    # Try the model ID from .env, or fall back to common ones.
    # Newer Claude models (4+) require cross-region inference profile
    # ARNs (us.anthropic.*) instead of direct model IDs (anthropic.*).
    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
    fallback_id = os.environ.get("BEDROCK_FALLBACK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

    for test_model_id in [model_id, fallback_id]:
        try:
            bedrock_runtime = boto3.client("bedrock-runtime", region_name=region)
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Say hi"}],
            })
            response = bedrock_runtime.invoke_model(
                modelId=test_model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            tokens_in = result.get("usage", {}).get("input_tokens", "?")
            tokens_out = result.get("usage", {}).get("output_tokens", "?")
            print_check(
                f"InvokeModel ({test_model_id})",
                True,
                f"OK — {tokens_in} tokens in, {tokens_out} tokens out",
            )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            if code in ("AccessDeniedException", "AccessDenied"):
                print_check(f"InvokeModel ({test_model_id})", False, "Access denied")
            elif code == "ResourceNotFoundException":
                print_check(
                    f"InvokeModel ({test_model_id})",
                    False,
                    "Model not found or EOL — request access in Bedrock console",
                )
            elif code == "ValidationException":
                # Model exists and we're authorized, just bad request format
                print_check(f"InvokeModel ({test_model_id})", True, f"Authorized (validation: {msg[:80]})")
            else:
                print_warn(f"InvokeModel ({test_model_id})", f"{code}: {msg[:100]}")

    # 4c. Test InvokeModel with Titan Embed (runtime API)
    print_subheader("4c. Bedrock Runtime — Titan Embed v2")

    embed_model_id = os.environ.get("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
    try:
        bedrock_runtime = boto3.client("bedrock-runtime", region_name=region)
        body = json.dumps({
            "inputText": "test embedding",
            "dimensions": 1024,
            "normalize": True,
        })
        response = bedrock_runtime.invoke_model(
            modelId=embed_model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        embedding = result.get("embedding", [])
        print_check(
            f"InvokeModel ({embed_model_id})",
            True,
            f"OK — returned {len(embedding)}-dim embedding",
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        if code in ("AccessDeniedException", "AccessDenied"):
            print_check(f"InvokeModel ({embed_model_id})", False, "Access denied")
        elif code == "ResourceNotFoundException":
            print_check(f"InvokeModel ({embed_model_id})", False, "Model not found — request access")
        else:
            print_warn(f"InvokeModel ({embed_model_id})", f"{code}: {msg[:100]}")


def test_textract_access(region: str) -> None:
    """Test access to Amazon Textract."""
    print_header("Step 5: Textract Access")

    try:
        textract = boto3.client("textract", region_name=region)
        # Send a minimal 1x1 white PNG to test authorization
        # This is a valid 1x1 PNG file (67 bytes)
        minimal_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        response = textract.detect_document_text(
            Document={"Bytes": minimal_png}
        )
        blocks = response.get("Blocks", [])
        print_check("DetectDocumentText", True, f"Authorized — {len(blocks)} blocks returned")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]
        if code in ("AccessDeniedException", "AccessDenied"):
            print_check("DetectDocumentText", False, "Access denied to Textract")
        elif code in ("InvalidParameterException", "UnsupportedDocumentException"):
            # The API call was authorized — just the test document wasn't ideal
            print_check("DetectDocumentText", True, f"Authorized (doc issue: {code})")
        elif code == "BadDocumentException":
            print_check("DetectDocumentText", True, "Authorized (test doc rejected, but API accessible)")
        else:
            print_warn("DetectDocumentText", f"{code}: {msg[:100]}")

    # Test async API access (AnalyzeDocument)
    try:
        response = textract.analyze_document(
            Document={"Bytes": minimal_png},
            FeatureTypes=["TABLES", "FORMS"],
        )
        print_check("AnalyzeDocument", True, "Authorized — TABLES + FORMS features available")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDeniedException", "AccessDenied"):
            print_check("AnalyzeDocument", False, "Access denied")
        elif code in ("InvalidParameterException", "UnsupportedDocumentException", "BadDocumentException"):
            print_check("AnalyzeDocument", True, f"Authorized ({code} — test doc issue)")
        else:
            print_warn("AnalyzeDocument", f"{code}: {e.response['Error']['Message'][:80]}")


def test_comprehend_access(region: str) -> None:
    """Test access to Amazon Comprehend (PII detection)."""
    print_header("Step 6: Comprehend Access (PII Detection)")

    try:
        comprehend = boto3.client("comprehend", region_name=region)
        response = comprehend.detect_pii_entities(
            Text="My name is John and my email is john@example.com",
            LanguageCode="en",
        )
        entities = response.get("Entities", [])
        print_check(
            "DetectPiiEntities",
            True,
            f"Authorized — detected {len(entities)} PII entities in test text",
        )
        for entity in entities:
            print(f"         PII: {entity['Type']} (confidence: {entity['Score']:.2f})")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDeniedException", "AccessDenied"):
            print_check("DetectPiiEntities", False, "Access denied to Comprehend")
        else:
            print_warn("DetectPiiEntities", f"{code}: {e.response['Error']['Message'][:100]}")
    except (ConnectionClosedError, ConnectionError, OSError) as e:
        # Corporate firewall/proxy may block comprehend.us-east-1.amazonaws.com
        print_check("DetectPiiEntities", False, "Connection blocked by network/firewall")
        print(f"         {DIM}Error: {type(e).__name__}: {str(e)[:120]}{RESET}")
        print(f"         {DIM}This is a NETWORK issue, not a permissions issue.{RESET}")
        print(f"         {DIM}Ask your network admin to whitelist: comprehend.{region}.amazonaws.com{RESET}")
        return  # Skip DetectEntities — same endpoint will fail

    # Also test DetectEntities (general NER)
    try:
        response = comprehend.detect_entities(
            Text="Invoice INV-2024-001 from Tata Consultancy for $50,000 due on Jan 15 2025",
            LanguageCode="en",
        )
        entities = response.get("Entities", [])
        print_check(
            "DetectEntities",
            True,
            f"Authorized — detected {len(entities)} entities",
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDeniedException", "AccessDenied"):
            print_check("DetectEntities", False, "Access denied")
        else:
            print_warn("DetectEntities", f"{code}")
    except (ConnectionClosedError, ConnectionError, OSError):
        print_check("DetectEntities", False, "Connection blocked by network/firewall")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_final_summary(identity: dict | None) -> None:
    """Print a VQMS-focused summary of what matters."""
    print_header("VQMS Service Access Summary")

    print(f"""
    This script checked IAM permissions for the credentials in your .env file.

    For VQMS Phase 3 (AI Pipeline), you need:

      Service              Needed For                       How to Check
      ─────────────────────────────────────────────────────────────────────
      Bedrock (LLM)        Query Analysis (Step 8)          See Step 4b above
      Bedrock (Embed)      KB Search (Step 9B)              See Step 4c above
      Textract             Attachment OCR (email intake)    See Step 5 above
      Comprehend           PII detection (Quality Gate)     See Step 6 above
      S3                   Raw email + KB storage           Run: scripts/check_aws.py
      SQS                  Pipeline message queues          Run: scripts/check_aws.py
      EventBridge          Audit events                     Run: scripts/check_aws.py

    If any service shows [FAIL], request access from your AWS admin:
      1. Open the AWS Console → IAM → Users → {identity['entity_name'] if identity else 'your-user'}
      2. Attach the required managed policy or add inline permissions
      3. For Bedrock models: Console → Bedrock → Model access → Request access
    """)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the full IAM permission audit for VQMS."""
    region = os.environ.get("AWS_REGION", os.environ.get("BEDROCK_REGION", "us-east-1"))

    print(f"\n{HEADER}  VQMS IAM Permission Audit{RESET}")
    print(f"  Region: {region}")
    print("  Purpose: Check vqms-dev IAM policies and verify Bedrock/Textract/Comprehend access")
    print("  Safety:  All calls are read-only except a tiny Bedrock test invoke (costs < $0.001)\n")

    start = time.time()

    # Step 1: Who am I?
    identity = identify_caller(region)
    if not identity:
        print("\n  Cannot continue without valid AWS credentials.")
        return

    # Step 2: Search for vqms-dev
    iam = boto3.client("iam", region_name=region)
    vqms_entity = search_for_vqms_dev(iam, region)

    # Step 3: List policies for the current identity (or vqms-dev if found)
    print_header("Step 3: IAM Policies & Permissions")

    # Always show policies for the current identity
    if identity["entity_type"] == "IAM User":
        list_user_policies(iam, identity["entity_name"])
    elif identity["entity_type"] in ("IAM Role", "Assumed Role"):
        list_role_policies(iam, identity["entity_name"])

    # If vqms-dev is different from current identity, also show its policies
    if vqms_entity:
        entity_type, entity_name = vqms_entity.split(":", 1)
        if entity_name != identity["entity_name"]:
            print(f"\n  {INFO} Also showing policies for vqms-dev (different from current identity):")
            if entity_type == "user":
                list_user_policies(iam, entity_name)
            else:
                list_role_policies(iam, entity_name)

    # Step 4-6: Test actual service access
    test_bedrock_access(region)
    test_textract_access(region)
    test_comprehend_access(region)

    elapsed = time.time() - start
    print_final_summary(identity)
    print(f"  {DIM}Completed in {elapsed:.1f}s{RESET}\n")


if __name__ == "__main__":
    main()
