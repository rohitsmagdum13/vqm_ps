# ruff: noqa: E402
"""Audit AWS access: discover which services and actions are available.

Probes ~30 AWS services with read-only API calls to determine what
your IAM credentials can and cannot do. No resources are created,
modified, or deleted — every call is a safe read/list/describe.

Usage:
  uv run python scripts/check_aws_access.py
"""

from __future__ import annotations

import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap -- must happen before project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

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


def print_header(title: str) -> None:
    print(f"\n{HEADER}{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}{RESET}")


def print_result(service: str, action: str, passed: bool, detail: str) -> None:
    status = PASS if passed else FAIL
    print(f"  {status} {service}: {action}")
    if detail:
        print(f"         {DIM}{detail}{RESET}")


def print_warn_result(service: str, action: str, detail: str) -> None:
    print(f"  {WARN} {service}: {action}")
    if detail:
        print(f"         {DIM}{detail}{RESET}")


# ---------------------------------------------------------------------------
# Probe helper — calls an AWS API and reports success/failure
# ---------------------------------------------------------------------------

def probe(
    service_name: str,
    action_name: str,
    callable_fn: Any,
    *args: Any,
    **kwargs: Any,
) -> dict:
    """Call an AWS API and return a result dict.

    Returns:
        {service, action, status: "pass"|"fail"|"warn", detail, error_code}
    """
    try:
        result = callable_fn(*args, **kwargs)

        # Extract a useful detail from the response
        detail = _extract_detail(service_name, action_name, result)

        return {
            "service": service_name,
            "action": action_name,
            "status": "pass",
            "detail": detail,
            "error_code": None,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        # AccessDenied means the service exists but we lack permission
        if error_code in (
            "AccessDenied",
            "AccessDeniedException",
            "UnauthorizedAccess",
            "UnauthorizedOperation",
            "AuthorizationError",
            "AuthorizationErrorException",
            "ForbiddenException",
        ):
            return {
                "service": service_name,
                "action": action_name,
                "status": "fail",
                "detail": f"Access denied ({error_code})",
                "error_code": error_code,
            }

        # Some errors are "soft" — like resource not found, which still
        # means the API call itself was authorized
        if error_code in (
            "ResourceNotFoundException",
            "NotFoundException",
            "NoSuchBucket",
            "AWS.SimpleQueueService.NonExistentQueue",
            "NoSuchEntity",
            "DBInstanceNotFound",
            "CacheClusterNotFound",
            "ClusterNotFoundException",
            "FunctionNotFound",
            "RepositoryNotFoundException",
            "InvalidParameterValue",
        ):
            return {
                "service": service_name,
                "action": action_name,
                "status": "pass",
                "detail": f"Authorized (resource not found: {error_code})",
                "error_code": error_code,
            }

        return {
            "service": service_name,
            "action": action_name,
            "status": "warn",
            "detail": f"{error_code}: {error_msg}",
            "error_code": error_code,
        }

    except EndpointConnectionError:
        return {
            "service": service_name,
            "action": action_name,
            "status": "warn",
            "detail": "Service endpoint not reachable in this region",
            "error_code": "EndpointConnectionError",
        }

    except Exception as e:
        return {
            "service": service_name,
            "action": action_name,
            "status": "warn",
            "detail": f"Unexpected: {type(e).__name__}: {e}",
            "error_code": "Unknown",
        }


def _extract_detail(service: str, action: str, response: dict) -> str:
    """Pull a useful summary from a successful API response."""
    # Remove ResponseMetadata to keep things clean
    if isinstance(response, dict):
        response.pop("ResponseMetadata", None)

    # Service-specific summaries
    if service == "S3" and action == "ListBuckets":
        buckets = response.get("Buckets", [])
        names = [b["Name"] for b in buckets[:10]]
        suffix = f" ... +{len(buckets) - 10} more" if len(buckets) > 10 else ""
        return f"{len(buckets)} buckets: {', '.join(names)}{suffix}"

    if service == "SQS" and action == "ListQueues":
        urls = response.get("QueueUrls", [])
        names = [u.split("/")[-1] for u in urls[:10]]
        suffix = f" ... +{len(urls) - 10} more" if len(urls) > 10 else ""
        return f"{len(urls)} queues: {', '.join(names)}{suffix}"

    if service == "Lambda" and action == "ListFunctions":
        fns = response.get("Functions", [])
        names = [f["FunctionName"] for f in fns[:10]]
        suffix = f" ... +{len(fns) - 10} more" if len(fns) > 10 else ""
        return f"{len(fns)} functions: {', '.join(names)}{suffix}"

    if service == "IAM" and action == "ListUsers":
        users = response.get("Users", [])
        return f"{len(users)} IAM users found"

    if service == "IAM" and action == "ListRoles":
        roles = response.get("Roles", [])
        return f"{len(roles)} IAM roles found"

    if service == "IAM" and action == "ListPolicies":
        policies = response.get("Policies", [])
        return f"{len(policies)} IAM policies found"

    if service == "EC2" and action == "DescribeInstances":
        reservations = response.get("Reservations", [])
        count = sum(len(r.get("Instances", [])) for r in reservations)
        return f"{count} EC2 instances found"

    if service == "EC2" and action == "DescribeVpcs":
        vpcs = response.get("Vpcs", [])
        return f"{len(vpcs)} VPCs found"

    if service == "EC2" and action == "DescribeSecurityGroups":
        sgs = response.get("SecurityGroups", [])
        return f"{len(sgs)} security groups found"

    if service == "RDS" and action == "DescribeDBInstances":
        dbs = response.get("DBInstances", [])
        names = [d["DBInstanceIdentifier"] for d in dbs[:5]]
        return f"{len(dbs)} DB instances: {', '.join(names)}" if names else "0 DB instances"

    if service == "DynamoDB" and action == "ListTables":
        tables = response.get("TableNames", [])
        return f"{len(tables)} tables: {', '.join(tables[:10])}" if tables else "0 tables"

    if service == "CloudWatch" and action == "ListDashboards":
        entries = response.get("DashboardEntries", [])
        return f"{len(entries)} dashboards found"

    if service == "CloudWatch Logs" and action == "DescribeLogGroups":
        groups = response.get("logGroups", [])
        names = [g["logGroupName"] for g in groups[:5]]
        suffix = f" ... +{len(groups) - 5} more" if len(groups) > 5 else ""
        return f"{len(groups)} log groups: {', '.join(names)}{suffix}"

    if service == "SNS" and action == "ListTopics":
        topics = response.get("Topics", [])
        return f"{len(topics)} topics found"

    if service == "Secrets Manager" and action == "ListSecrets":
        secrets = response.get("SecretList", [])
        names = [s["Name"] for s in secrets[:5]]
        return f"{len(secrets)} secrets: {', '.join(names)}" if names else "0 secrets"

    if service == "ECR" and action == "DescribeRepositories":
        repos = response.get("repositories", [])
        names = [r["repositoryName"] for r in repos[:5]]
        return f"{len(repos)} repos: {', '.join(names)}" if names else "0 repositories"

    if service == "ECS" and action == "ListClusters":
        arns = response.get("clusterArns", [])
        return f"{len(arns)} clusters found"

    if service == "Cognito" and action == "ListUserPools":
        pools = response.get("UserPools", [])
        names = [p["Name"] for p in pools[:5]]
        return f"{len(pools)} user pools: {', '.join(names)}" if names else "0 user pools"

    if service == "KMS" and action == "ListKeys":
        keys = response.get("Keys", [])
        return f"{len(keys)} KMS keys found"

    if service == "CloudFormation" and action == "ListStacks":
        stacks = response.get("StackSummaries", [])
        active = [s for s in stacks if s["StackStatus"] != "DELETE_COMPLETE"]
        return f"{len(active)} active stacks"

    if service == "Bedrock" and action == "ListFoundationModels":
        models = response.get("modelSummaries", [])
        return f"{len(models)} foundation models available"

    if service == "Textract" and action == "GetDocumentAnalysis":
        return "API authorized (call succeeded or expected error)"

    if service == "Comprehend" and action == "ListEntitiesDetectionJobs":
        jobs = response.get("EntitiesDetectionJobPropertiesList", [])
        return f"{len(jobs)} entity detection jobs"

    if service == "Step Functions" and action == "ListStateMachines":
        machines = response.get("stateMachines", [])
        return f"{len(machines)} state machines found"

    if service == "EventBridge" and action == "ListEventBuses":
        buses = response.get("EventBuses", [])
        names = [b["Name"] for b in buses[:5]]
        return f"{len(buses)} buses: {', '.join(names)}" if names else "0 event buses"

    if service == "SSM" and action == "DescribeParameters":
        params = response.get("Parameters", [])
        return f"{len(params)} parameters found"

    if service == "Glue" and action == "GetDatabases":
        dbs = response.get("DatabaseList", [])
        return f"{len(dbs)} Glue databases found"

    if service == "Athena" and action == "ListWorkGroups":
        groups = response.get("WorkGroups", [])
        return f"{len(groups)} work groups found"

    if service == "API Gateway" and action == "GetRestApis":
        apis = response.get("items", [])
        names = [a["name"] for a in apis[:5]]
        return f"{len(apis)} REST APIs: {', '.join(names)}" if names else "0 REST APIs"

    return "OK"


# ---------------------------------------------------------------------------
# Service probes — grouped by category
# ---------------------------------------------------------------------------

def _probe_s3_permissions(s3_client: Any, bucket_names: list[str]) -> list[dict]:
    """Probe per-bucket S3 permissions: list, head, read, write, delete, ACL, versioning.

    Uses safe test calls — writes a tiny temp object then cleans it up.
    No permanent changes are made to any bucket.
    """
    test_key = "_vqms_access_audit_test.txt"
    test_body = b"VQMS access audit probe"
    results: list[dict] = []

    for bucket in bucket_names:
        permissions: list[str] = []
        denied: list[str] = []

        # 1. HeadBucket — basic bucket access
        try:
            s3_client.head_bucket(Bucket=bucket)
            permissions.append("HeadBucket")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("403", "AccessDenied"):
                denied.append("HeadBucket")
            else:
                denied.append(f"HeadBucket({code})")

        # 2. ListObjectsV2 — read/list permission
        try:
            s3_client.list_objects_v2(Bucket=bucket, MaxKeys=1)
            permissions.append("ListObjects")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("403", "AccessDenied"):
                denied.append("ListObjects")
            else:
                denied.append(f"ListObjects({code})")

        # 3. GetObject — read a specific object (use a key that won't exist)
        try:
            s3_client.get_object(Bucket=bucket, Key="_vqms_nonexistent_probe_key")
            permissions.append("GetObject")  # unlikely to reach here
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NoSuchKey":
                # Key doesn't exist, but we were AUTHORIZED to try
                permissions.append("GetObject")
            elif code in ("403", "AccessDenied"):
                denied.append("GetObject")
            else:
                denied.append(f"GetObject({code})")

        # 4. PutObject — write permission (upload tiny test file)
        write_ok = False
        try:
            s3_client.put_object(Bucket=bucket, Key=test_key, Body=test_body)
            permissions.append("PutObject")
            write_ok = True
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("403", "AccessDenied"):
                denied.append("PutObject")
            else:
                denied.append(f"PutObject({code})")

        # 5. DeleteObject — delete permission (clean up test file)
        if write_ok:
            try:
                s3_client.delete_object(Bucket=bucket, Key=test_key)
                permissions.append("DeleteObject")
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("403", "AccessDenied"):
                    denied.append("DeleteObject")
                else:
                    denied.append(f"DeleteObject({code})")

        # 6. GetBucketAcl — ACL read permission
        try:
            s3_client.get_bucket_acl(Bucket=bucket)
            permissions.append("GetBucketAcl")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("403", "AccessDenied"):
                denied.append("GetBucketAcl")
            else:
                denied.append(f"GetBucketAcl({code})")

        # 7. GetBucketVersioning — versioning status
        try:
            s3_client.get_bucket_versioning(Bucket=bucket)
            permissions.append("GetBucketVersioning")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("403", "AccessDenied"):
                denied.append("GetBucketVersioning")
            else:
                denied.append(f"GetBucketVersioning({code})")

        # 8. GetBucketPolicy — bucket policy read
        try:
            s3_client.get_bucket_policy(Bucket=bucket)
            permissions.append("GetBucketPolicy")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("NoSuchBucketPolicy",):
                # No policy set, but we were authorized to check
                permissions.append("GetBucketPolicy")
            elif code in ("403", "AccessDenied"):
                denied.append("GetBucketPolicy")
            else:
                denied.append(f"GetBucketPolicy({code})")

        # Build summary
        allowed_str = ", ".join(permissions) if permissions else "NONE"
        denied_str = ", ".join(denied) if denied else "NONE"
        all_passed = len(denied) == 0

        results.append({
            "service": f"S3 ({bucket})",
            "action": "PerBucketAudit",
            "status": "pass" if all_passed else ("fail" if not permissions else "warn"),
            "detail": f"ALLOWED: {allowed_str}  |  DENIED: {denied_str}",
            "error_code": None,
        })

    return results


def probe_all(region: str) -> list[dict]:
    """Probe all AWS services and return results."""
    results: list[dict] = []

    # ── Identity ──────────────────────────────────────────────────────────
    print_header("Identity & Access (IAM / STS)")

    sts = boto3.client("sts", region_name=region)
    results.append(probe("STS", "GetCallerIdentity", sts.get_caller_identity))

    iam = boto3.client("iam", region_name=region)
    results.append(probe("IAM", "ListUsers", iam.list_users, MaxItems=10))
    results.append(probe("IAM", "ListRoles", iam.list_roles, MaxItems=10))
    results.append(probe("IAM", "ListPolicies", iam.list_policies, Scope="Local", MaxItems=10))
    results.append(probe("IAM", "GetAccountSummary", iam.get_account_summary))

    # ── Storage ───────────────────────────────────────────────────────────
    print_header("Storage (S3)")

    s3 = boto3.client("s3", region_name=region)
    results.append(probe("S3", "ListBuckets", s3.list_buckets))

    # Discover all buckets, then probe per-bucket permissions
    buckets_to_check: list[str] = []
    try:
        bucket_resp = s3.list_buckets()
        buckets_to_check = [b["Name"] for b in bucket_resp.get("Buckets", [])]
    except Exception:
        pass  # ListBuckets denied — already captured above

    results.extend(_probe_s3_permissions(s3, buckets_to_check))

    # ── Compute ───────────────────────────────────────────────────────────
    print_header("Compute (EC2 / Lambda / ECS)")

    ec2 = boto3.client("ec2", region_name=region)
    results.append(probe("EC2", "DescribeInstances", ec2.describe_instances, MaxResults=10))
    results.append(probe("EC2", "DescribeVpcs", ec2.describe_vpcs))
    results.append(probe("EC2", "DescribeSecurityGroups", ec2.describe_security_groups, MaxResults=10))
    results.append(probe("EC2", "DescribeSubnets", ec2.describe_subnets))
    results.append(probe("EC2", "DescribeKeyPairs", ec2.describe_key_pairs))

    lam = boto3.client("lambda", region_name=region)
    results.append(probe("Lambda", "ListFunctions", lam.list_functions, MaxItems=10))
    results.append(probe("Lambda", "ListLayers", lam.list_layers))

    ecs = boto3.client("ecs", region_name=region)
    results.append(probe("ECS", "ListClusters", ecs.list_clusters, maxResults=10))

    # ── Database ──────────────────────────────────────────────────────────
    print_header("Database (RDS / DynamoDB)")

    rds = boto3.client("rds", region_name=region)
    results.append(probe("RDS", "DescribeDBInstances", rds.describe_db_instances, MaxRecords=20))
    results.append(probe("RDS", "DescribeDBClusters", rds.describe_db_clusters, MaxRecords=20))

    ddb = boto3.client("dynamodb", region_name=region)
    results.append(probe("DynamoDB", "ListTables", ddb.list_tables, Limit=10))

    # ── Messaging ─────────────────────────────────────────────────────────
    print_header("Messaging (SQS / SNS / EventBridge)")

    sqs = boto3.client("sqs", region_name=region)
    results.append(probe("SQS", "ListQueues", sqs.list_queues))

    sns = boto3.client("sns", region_name=region)
    results.append(probe("SNS", "ListTopics", sns.list_topics))

    eb = boto3.client("events", region_name=region)
    results.append(probe("EventBridge", "ListEventBuses", eb.list_event_buses))
    results.append(probe("EventBridge", "ListRules", eb.list_rules))

    # ── AI / ML ───────────────────────────────────────────────────────────
    print_header("AI / ML (Bedrock / Comprehend / Textract)")

    bedrock = boto3.client("bedrock", region_name=region)
    results.append(probe("Bedrock", "ListFoundationModels", bedrock.list_foundation_models))

    # bedrock-runtime requires a payload to invoke, so we only test
    # the management API (ListFoundationModels) above.
    # Separately probe bedrock-agent if available.
    try:
        bedrock_agent = boto3.client("bedrock-agent", region_name=region)
        results.append(probe("Bedrock Agent", "ListAgents", bedrock_agent.list_agents, maxResults=5))
    except Exception:
        pass

    comprehend = boto3.client("comprehend", region_name=region)
    results.append(probe("Comprehend", "ListEntitiesDetectionJobs", comprehend.list_entities_detection_jobs))

    textract = boto3.client("textract", region_name=region)
    # Textract has no list call, so we try a benign call that will give us auth info
    results.append(probe(
        "Textract", "DetectDocumentText",
        textract.detect_document_text,
        Document={"Bytes": b"test"},
    ))

    # ── Security & Secrets ────────────────────────────────────────────────
    print_header("Security (Secrets Manager / KMS / Cognito)")

    sm = boto3.client("secretsmanager", region_name=region)
    results.append(probe("Secrets Manager", "ListSecrets", sm.list_secrets, MaxResults=10))

    kms = boto3.client("kms", region_name=region)
    results.append(probe("KMS", "ListKeys", kms.list_keys, Limit=10))

    cognito = boto3.client("cognito-idp", region_name=region)
    results.append(probe("Cognito", "ListUserPools", cognito.list_user_pools, MaxResults=10))

    # ── Monitoring ────────────────────────────────────────────────────────
    print_header("Monitoring (CloudWatch / CloudWatch Logs)")

    cw = boto3.client("cloudwatch", region_name=region)
    results.append(probe("CloudWatch", "ListDashboards", cw.list_dashboards))
    results.append(probe("CloudWatch", "ListMetrics", cw.list_metrics, Namespace="AWS/EC2"))

    logs = boto3.client("logs", region_name=region)
    results.append(probe("CloudWatch Logs", "DescribeLogGroups", logs.describe_log_groups, limit=10))

    # ── DevOps / Infra ────────────────────────────────────────────────────
    print_header("DevOps (CloudFormation / SSM / ECR / Step Functions)")

    cfn = boto3.client("cloudformation", region_name=region)
    results.append(probe("CloudFormation", "ListStacks", cfn.list_stacks))

    ssm = boto3.client("ssm", region_name=region)
    results.append(probe("SSM", "DescribeParameters", ssm.describe_parameters, MaxResults=10))

    ecr = boto3.client("ecr", region_name=region)
    results.append(probe("ECR", "DescribeRepositories", ecr.describe_repositories, maxResults=10))

    sfn = boto3.client("stepfunctions", region_name=region)
    results.append(probe("Step Functions", "ListStateMachines", sfn.list_state_machines, maxResults=10))

    # ── API Gateway ───────────────────────────────────────────────────────
    print_header("API Gateway")

    apigw = boto3.client("apigateway", region_name=region)
    results.append(probe("API Gateway", "GetRestApis", apigw.get_rest_apis, limit=10))

    apigw2 = boto3.client("apigatewayv2", region_name=region)
    results.append(probe("API Gateway V2", "GetApis", apigw2.get_apis, MaxResults="10"))

    # ── Analytics ─────────────────────────────────────────────────────────
    print_header("Analytics (Glue / Athena)")

    glue = boto3.client("glue", region_name=region)
    results.append(probe("Glue", "GetDatabases", glue.get_databases))

    athena = boto3.client("athena", region_name=region)
    results.append(probe("Athena", "ListWorkGroups", athena.list_work_groups))

    # Print results as we collect them
    for r in results:
        if r["status"] == "pass":
            print_result(r["service"], r["action"], True, r["detail"])
        elif r["status"] == "fail":
            print_result(r["service"], r["action"], False, r["detail"])
        else:
            print_warn_result(r["service"], r["action"], r["detail"])

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: list[dict], elapsed: float) -> None:
    """Print a categorized summary of all probes."""
    passed = [r for r in results if r["status"] == "pass"]
    failed = [r for r in results if r["status"] == "fail"]
    warned = [r for r in results if r["status"] == "warn"]

    print_header("ACCESS SUMMARY")

    # Group passed results by service
    accessible_services: dict[str, list[str]] = {}
    for r in passed:
        accessible_services.setdefault(r["service"], []).append(r["action"])

    denied_services: dict[str, list[str]] = {}
    for r in failed:
        denied_services.setdefault(r["service"], []).append(r["action"])

    unknown_services: dict[str, list[str]] = {}
    for r in warned:
        unknown_services.setdefault(r["service"], []).append(r["action"])

    # --- Accessible services ---
    print(f"\n  {PASS} ACCESSIBLE SERVICES ({len(accessible_services)}):")
    for svc, actions in sorted(accessible_services.items()):
        print(f"      {svc}: {', '.join(actions)}")

    # --- Denied services ---
    if denied_services:
        print(f"\n  {FAIL} ACCESS DENIED ({len(denied_services)}):")
        for svc, actions in sorted(denied_services.items()):
            print(f"      {svc}: {', '.join(actions)}")

    # --- Unknown / warnings ---
    if unknown_services:
        print(f"\n  {WARN} UNKNOWN / ERRORS ({len(unknown_services)}):")
        for svc, actions in sorted(unknown_services.items()):
            print(f"      {svc}: {', '.join(actions)}")

    # --- Totals ---
    total = len(results)
    print(f"\n  {'-' * 50}")
    print(f"  Total API calls probed: {total}")
    print(f"  {PASS} Authorized:    {len(passed)}")
    print(f"  {FAIL} Denied:        {len(failed)}")
    print(f"  {WARN} Unknown/Error: {len(warned)}")
    print(f"\n  Time: {elapsed:.2f}s\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Audit AWS access across all major services."""
    # Default to us-east-1 or read from env
    import os
    region = os.environ.get("AWS_REGION", "us-east-1")

    print(f"\n{HEADER}  AWS Access Audit{RESET}")
    print(f"  Region: {region}")
    print("  Purpose: Discover which AWS services your credentials can access")
    print("  Safety:  ALL calls are read-only (list/describe/get). Nothing is created or modified.\n")

    start = time.time()

    # First verify credentials work at all
    try:
        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        print(f"  {PASS} Identity: {identity['Arn']}")
        print(f"  {INFO} Account:  {identity['Account']}")
    except Exception as e:
        print(f"  {FAIL} Cannot authenticate: {e}")
        print("  Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
        return

    results = probe_all(region)
    elapsed = time.time() - start
    print_summary(results, elapsed)


if __name__ == "__main__":
    main()
