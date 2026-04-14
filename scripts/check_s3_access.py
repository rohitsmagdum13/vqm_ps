# ruff: noqa: E402
"""Check detailed S3 access permissions for all VQMS buckets.

Tests every S3 action your IAM credentials can perform on each bucket:
  - Bucket-level: HeadBucket, ListObjects, GetBucketAcl, GetBucketPolicy,
                  GetBucketVersioning, GetBucketEncryption, GetBucketTagging,
                  GetBucketLocation, GetBucketCORS, GetBucketLifecycle
  - Object-level: GetObject (read), PutObject (write), DeleteObject (delete),
                  CopyObject (copy), HeadObject (metadata)
  - Advanced:     GeneratePresignedUrl, Multipart upload

All checks are safe and read-only where possible. Write/delete tests
use a tiny temp object and clean up immediately after.

Usage:
  uv run python scripts/check_s3_access.py
"""

from __future__ import annotations

import sys
import time

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import boto3
from botocore.exceptions import ClientError

from config.settings import get_settings

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
    print(f"\n{HEADER}{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}{RESET}")


def print_sub_header(title: str) -> None:
    print(f"\n  {HEADER}--- {title} ---{RESET}")


# ---------------------------------------------------------------------------
# S3 permission checker
# ---------------------------------------------------------------------------

TEST_KEY = "_vqms_s3_access_audit_test.txt"
TEST_BODY = b"VQMS S3 access audit probe - safe to delete"
COPY_KEY = "_vqms_s3_access_audit_copy.txt"


def check_action(
    s3_client,
    bucket: str,
    action_name: str,
    callable_fn,
    *args,
    **kwargs,
) -> dict:
    """Try a single S3 action and return the result.

    Returns: {action, status: pass|fail|warn, detail}
    """
    try:
        result = callable_fn(*args, **kwargs)
        detail = _summarize(action_name, result)
        return {"action": action_name, "status": "pass", "detail": detail}

    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"]["Message"]

        # These mean "authorized but resource/config doesn't exist"
        authorized_errors = (
            "NoSuchKey",
            "NoSuchBucketPolicy",
            "NoSuchCORSConfiguration",
            "NoSuchLifecycleConfiguration",
            "NoSuchTagSet",
            "ServerSideEncryptionConfigurationNotFoundError",
            "NoSuchWebsiteConfiguration",
            "ReplicationConfigurationNotFoundError",
        )

        if code in authorized_errors:
            return {
                "action": action_name,
                "status": "pass",
                "detail": f"Authorized (not configured: {code})",
            }

        if code in ("403", "AccessDenied"):
            return {
                "action": action_name,
                "status": "fail",
                "detail": "Access Denied",
            }

        return {
            "action": action_name,
            "status": "warn",
            "detail": f"{code}: {msg}",
        }

    except Exception as e:
        return {
            "action": action_name,
            "status": "warn",
            "detail": f"{type(e).__name__}: {e}",
        }


def _summarize(action: str, response: dict) -> str:
    """Extract a useful one-liner from the response."""
    if not isinstance(response, dict):
        return "OK"

    if action == "ListObjectsV2":
        count = response.get("KeyCount", 0)
        return f"{count} object(s) returned"

    if action == "GetBucketLocation":
        loc = response.get("LocationConstraint") or "us-east-1 (default)"
        return f"Region: {loc}"

    if action == "GetBucketVersioning":
        status = response.get("Status", "Not enabled")
        mfa = response.get("MFADelete", "Disabled")
        return f"Versioning: {status}, MFA Delete: {mfa}"

    if action == "GetBucketEncryption":
        rules = response.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
        if rules:
            algo = rules[0].get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm", "?")
            return f"Encryption: {algo}"
        return "Encryption config found"

    if action == "GetBucketAcl":
        owner = response.get("Owner", {}).get("DisplayName", "?")
        grants = response.get("Grants", [])
        return f"Owner: {owner}, {len(grants)} grant(s)"

    if action == "GetBucketPolicy":
        policy = response.get("Policy", "")
        return f"Policy: {len(policy)} chars"

    if action == "GetBucketTagging":
        tags = response.get("TagSet", [])
        tag_str = ", ".join(f"{t['Key']}={t['Value']}" for t in tags[:5])
        suffix = f" ... +{len(tags) - 5} more" if len(tags) > 5 else ""
        return f"{len(tags)} tags: {tag_str}{suffix}" if tags else "No tags"

    if action == "GetBucketCORS":
        rules = response.get("CORSRules", [])
        return f"{len(rules)} CORS rule(s)"

    if action == "GetBucketLifecycle":
        rules = response.get("Rules", [])
        return f"{len(rules)} lifecycle rule(s)"

    if action == "HeadObject":
        size = response.get("ContentLength", "?")
        ctype = response.get("ContentType", "?")
        return f"Size: {size} bytes, Type: {ctype}"

    if action == "PutObject":
        etag = response.get("ETag", "?")
        return f"Written OK (ETag: {etag})"

    if action == "CopyObject":
        return "Copy OK"

    if action == "DeleteObject":
        return "Deleted OK"

    if action == "CreateMultipartUpload":
        upload_id = response.get("UploadId", "?")
        return f"Multipart initiated (UploadId: {upload_id[:20]}...)"

    if action == "AbortMultipartUpload":
        return "Multipart aborted OK"

    return "OK"


def audit_bucket(s3_client, bucket: str) -> list[dict]:
    """Run all permission checks on a single bucket."""
    results: list[dict] = []

    # ── Bucket-level read permissions ─────────────────────────────────

    results.append(check_action(
        s3_client, bucket, "HeadBucket",
        s3_client.head_bucket, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "ListObjectsV2",
        s3_client.list_objects_v2, Bucket=bucket, MaxKeys=5,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketLocation",
        s3_client.get_bucket_location, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketVersioning",
        s3_client.get_bucket_versioning, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketEncryption",
        s3_client.get_bucket_encryption, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketAcl",
        s3_client.get_bucket_acl, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketPolicy",
        s3_client.get_bucket_policy, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketTagging",
        s3_client.get_bucket_tagging, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketCORS",
        s3_client.get_bucket_cors, Bucket=bucket,
    ))

    results.append(check_action(
        s3_client, bucket, "GetBucketLifecycle",
        s3_client.get_bucket_lifecycle_configuration, Bucket=bucket,
    ))

    # ── Object-level write permissions ────────────────────────────────
    # Upload a tiny test object, then check read/copy/delete on it

    write_result = check_action(
        s3_client, bucket, "PutObject",
        s3_client.put_object, Bucket=bucket, Key=TEST_KEY, Body=TEST_BODY,
    )
    results.append(write_result)
    write_ok = write_result["status"] == "pass"

    # HeadObject — object metadata read
    if write_ok:
        results.append(check_action(
            s3_client, bucket, "HeadObject",
            s3_client.head_object, Bucket=bucket, Key=TEST_KEY,
        ))
    else:
        # Try HeadObject on a non-existent key to check auth
        results.append(check_action(
            s3_client, bucket, "HeadObject",
            s3_client.head_object, Bucket=bucket, Key="_vqms_nonexistent_key",
        ))

    # GetObject — read the object back
    if write_ok:
        results.append(check_action(
            s3_client, bucket, "GetObject",
            s3_client.get_object, Bucket=bucket, Key=TEST_KEY,
        ))
    else:
        results.append(check_action(
            s3_client, bucket, "GetObject",
            s3_client.get_object, Bucket=bucket, Key="_vqms_nonexistent_key",
        ))

    # CopyObject — copy within the same bucket
    if write_ok:
        copy_result = check_action(
            s3_client, bucket, "CopyObject",
            s3_client.copy_object,
            Bucket=bucket,
            Key=COPY_KEY,
            CopySource={"Bucket": bucket, "Key": TEST_KEY},
        )
        results.append(copy_result)

        # Clean up copy
        if copy_result["status"] == "pass":
            try:
                s3_client.delete_object(Bucket=bucket, Key=COPY_KEY)
            except Exception:
                pass
    else:
        results.append({
            "action": "CopyObject",
            "status": "warn",
            "detail": "Skipped (PutObject denied, cannot test copy)",
        })

    # DeleteObject — delete the test object
    if write_ok:
        results.append(check_action(
            s3_client, bucket, "DeleteObject",
            s3_client.delete_object, Bucket=bucket, Key=TEST_KEY,
        ))
    else:
        results.append({
            "action": "DeleteObject",
            "status": "warn",
            "detail": "Skipped (no test object to delete)",
        })

    # ── Multipart upload ──────────────────────────────────────────────
    multipart_key = "_vqms_multipart_test.txt"
    mp_result = check_action(
        s3_client, bucket, "CreateMultipartUpload",
        s3_client.create_multipart_upload,
        Bucket=bucket, Key=multipart_key,
    )
    results.append(mp_result)

    # Abort the multipart upload immediately (cleanup)
    if mp_result["status"] == "pass":
        upload_id = None
        try:
            # Re-extract upload ID from a fresh call since check_action
            # doesn't return the raw response
            resp = s3_client.create_multipart_upload(
                Bucket=bucket, Key=multipart_key,
            )
            upload_id = resp["UploadId"]
        except Exception:
            pass

        if upload_id:
            abort_result = check_action(
                s3_client, bucket, "AbortMultipartUpload",
                s3_client.abort_multipart_upload,
                Bucket=bucket, Key=multipart_key, UploadId=upload_id,
            )
            results.append(abort_result)

            # Also abort the first one we created
            try:
                # List and abort any remaining
                list_resp = s3_client.list_multipart_uploads(Bucket=bucket, Prefix="_vqms_multipart")
                for upload in list_resp.get("Uploads", []):
                    s3_client.abort_multipart_upload(
                        Bucket=bucket,
                        Key=upload["Key"],
                        UploadId=upload["UploadId"],
                    )
            except Exception:
                pass

    # ── Presigned URL generation (client-side, always works) ──────────
    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": "test.txt"},
            ExpiresIn=60,
        )
        results.append({
            "action": "GeneratePresignedUrl",
            "status": "pass",
            "detail": f"URL generated ({len(url)} chars)",
        })
    except Exception as e:
        results.append({
            "action": "GeneratePresignedUrl",
            "status": "warn",
            "detail": str(e),
        })

    return results


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_bucket_results(bucket: str, results: list[dict]) -> None:
    """Print results for a single bucket in a clear table format."""
    print_sub_header(bucket)

    passed = [r for r in results if r["status"] == "pass"]
    failed = [r for r in results if r["status"] == "fail"]
    warned = [r for r in results if r["status"] == "warn"]

    for r in results:
        if r["status"] == "pass":
            icon = PASS
        elif r["status"] == "fail":
            icon = FAIL
        else:
            icon = WARN
        print(f"    {icon} {r['action']:<30} {DIM}{r['detail']}{RESET}")

    # Quick summary line
    print()
    summary_parts = []
    if passed:
        summary_parts.append(f"{GREEN}{len(passed)} allowed{RESET}")
    if failed:
        summary_parts.append(f"{RED}{len(failed)} denied{RESET}")
    if warned:
        summary_parts.append(f"{YELLOW}{len(warned)} unknown{RESET}")
    print(f"    Summary: {' | '.join(summary_parts)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Check S3 access permissions for buckets configured in .env."""
    settings = get_settings()
    region = settings.aws_region

    print(f"\n{HEADER}  S3 Access Audit (from .env){RESET}")
    print(f"  Region: {region}")
    print("  Checks per-bucket: read, write, delete, copy, ACL, policy,")
    print("  encryption, versioning, tagging, CORS, lifecycle, multipart")
    print("  All write tests use a temp object and clean up immediately.")
    print(f"  Source: .env (S3_BUCKET_DATA_STORE={settings.s3_bucket_data_store})\n")

    start = time.time()

    # Verify credentials
    try:
        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        print(f"  {PASS} Identity: {identity['Arn']}")
        print(f"  {INFO} Account:  {identity['Account']}")
    except Exception as e:
        print(f"  {FAIL} Cannot authenticate: {e}")
        return

    s3 = boto3.client("s3", region_name=region)

    # Only check the bucket from .env
    bucket_name = settings.s3_bucket_data_store
    buckets = [bucket_name]

    print(f"\n  {INFO} Checking bucket from .env: {bucket_name}")

    # Audit each bucket
    all_results: dict[str, list[dict]] = {}

    for bucket in buckets:
        bucket_results = audit_bucket(s3, bucket)
        all_results[bucket] = bucket_results
        print_bucket_results(bucket, bucket_results)

    # ── Final summary ─────────────────────────────────────────────────
    elapsed = time.time() - start

    print_header("OVERALL S3 ACCESS MATRIX")

    # Collect all unique actions
    all_actions: list[str] = []
    for bucket_results in all_results.values():
        for r in bucket_results:
            if r["action"] not in all_actions:
                all_actions.append(r["action"])

    # Print compact matrix
    max_action_len = max(len(a) for a in all_actions)
    short_names = [b.replace("vqms-", "") for b in buckets]
    col_width = max(len(n) for n in short_names) + 2

    # Header row
    print(f"\n    {'Action':<{max_action_len}}  ", end="")
    for name in short_names:
        print(f"{name:<{col_width}}", end="")
    print()
    print(f"    {'-' * max_action_len}  ", end="")
    for name in short_names:
        print(f"{'-' * (col_width)}", end="")
    print()

    # Data rows
    for action in all_actions:
        print(f"    {action:<{max_action_len}}  ", end="")
        for bucket in buckets:
            bucket_results = all_results[bucket]
            match = next((r for r in bucket_results if r["action"] == action), None)
            if match is None:
                symbol = f"{DIM}--{RESET}"
            elif match["status"] == "pass":
                symbol = f"{GREEN}YES{RESET}"
            elif match["status"] == "fail":
                symbol = f"{RED}NO{RESET}"
            else:
                symbol = f"{YELLOW}?{RESET}"
            # Pad accounting for ANSI codes (add extra spaces)
            print(f"{symbol}{' ' * (col_width - 3)}", end="")
        print()

    # Totals
    total_checks = sum(len(r) for r in all_results.values())
    total_pass = sum(1 for r in all_results.values() for x in r if x["status"] == "pass")
    total_fail = sum(1 for r in all_results.values() for x in r if x["status"] == "fail")
    total_warn = sum(1 for r in all_results.values() for x in r if x["status"] == "warn")

    print(f"\n  {'-' * 50}")
    print(f"  Buckets checked:  {len(buckets)}")
    print(f"  Total API probes: {total_checks}")
    print(f"  {PASS} Allowed:  {total_pass}")
    print(f"  {FAIL} Denied:   {total_fail}")
    print(f"  {WARN} Unknown:  {total_warn}")
    print(f"  Time: {elapsed:.2f}s\n")


if __name__ == "__main__":
    main()
