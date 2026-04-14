"""Script: check_aws.py

Verify AWS credentials and access to pre-provisioned services.

Tests:
  1. AWS credentials (STS GetCallerIdentity)
  2. S3 bucket access (HeadBucket on vqms-data-store)
  3. S3 prefix listing (list objects in each prefix)
  4. SQS queue access (list queues with vqms- prefix)
  5. EventBridge bus access (describe event bus)

Does NOT create or delete any AWS resources — read-only checks only.

Usage:
    uv run python scripts/check_aws.py
"""

from __future__ import annotations

import sys

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


def check_aws() -> None:
    """Run all AWS access checks."""
    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS — AWS Service Access Check")
    print(f"  Region: {settings.aws_region}")
    print()

    # --- Check 1: AWS Credentials (STS) ---
    try:
        sts = boto3.client("sts", region_name=settings.aws_region)
        identity = sts.get_caller_identity()
        account = identity.get("Account", "unknown")
        arn = identity.get("Arn", "unknown")
        print_check("AWS Credentials (STS)", True, f"Account={account}")
        print(f"          ARN: {arn}")
    except NoCredentialsError:
        print_check("AWS Credentials (STS)", False, "No credentials found — check .env or AWS config")
        print("\n  Remaining checks skipped (no credentials).")
        return
    except ClientError as e:
        print_check("AWS Credentials (STS)", False, e.response["Error"]["Message"])
        return

    # --- Check 2: S3 Bucket ---
    bucket_name = settings.s3_bucket_data_store
    try:
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.head_bucket(Bucket=bucket_name)
        print_check(f"S3 Bucket ({bucket_name})", True, "Exists and accessible")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "404":
            print_check(f"S3 Bucket ({bucket_name})", False, "Bucket does not exist")
        elif code == "403":
            print_check(f"S3 Bucket ({bucket_name})", False, "Access denied")
        else:
            print_check(f"S3 Bucket ({bucket_name})", False, str(e))

    # --- Check 3: S3 Prefix Listing ---
    expected_prefixes = [
        "inbound-emails/",
        "attachments/",
        "processed/",
        "templates/",
        "archive/",
    ]
    try:
        for prefix in expected_prefixes:
            response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix, MaxKeys=1)
            count = response.get("KeyCount", 0)
            label = f"  S3 prefix: {prefix}"
            if count > 0:
                print_check(label, True, f"{count}+ object(s)")
            else:
                print_check(label, True, "Empty (no objects yet)")
    except ClientError as e:
        print_check("S3 Prefix Listing", False, str(e))

    # --- Check 4: SQS Queues ---
    try:
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        response = sqs.list_queues(QueueNamePrefix=settings.sqs_queue_prefix)
        queue_urls = response.get("QueueUrls", [])
        if queue_urls:
            print_check(
                f"SQS Queues (prefix={settings.sqs_queue_prefix})",
                True,
                f"{len(queue_urls)} queue(s) found",
            )
            for url in queue_urls:
                # Extract queue name from URL
                queue_name = url.rsplit("/", 1)[-1]
                print(f"          - {queue_name}")
        else:
            print_check(
                f"SQS Queues (prefix={settings.sqs_queue_prefix})",
                False,
                "No queues found",
            )
    except ClientError as e:
        print_check("SQS Queues", False, str(e))

    # --- Check 5: EventBridge Bus ---
    bus_name = settings.eventbridge_bus_name
    try:
        eb = boto3.client("events", region_name=settings.aws_region)
        response = eb.describe_event_bus(Name=bus_name)
        bus_arn = response.get("Arn", "unknown")
        print_check(f"EventBridge Bus ({bus_name})", True, "Exists")
        print(f"          ARN: {bus_arn}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "ResourceNotFoundException":
            print_check(f"EventBridge Bus ({bus_name})", False, "Bus does not exist")
        else:
            print_check(f"EventBridge Bus ({bus_name})", False, str(e))

    print(f"\n{'=' * 60}\n")


def main() -> None:
    """Run the check."""
    check_aws()


if __name__ == "__main__":
    main()
