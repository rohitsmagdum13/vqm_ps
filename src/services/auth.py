"""Authentication Service for VQMS.

Handles user login, logout, JWT token management, and session
control. Replaces the local_vqm auth logic with VQMS-standard
patterns: async DB via PostgresConnector, PostgreSQL-based token
blacklist, structured logging, and correlation IDs.

Database: Queries public.tbl_users and public.tbl_user_roles
via raw SQL (asyncpg with $1 positional params).

Password hashing: Uses werkzeug.security.check_password_hash
to verify passwords — compatible with existing hashed passwords
in tbl_users created by the local_vqm backend.

Token blacklist: Uses PostgreSQL cache table (cache.kv_store).
Key pattern: vqms:auth:blacklist:<jti> with TTL matching JWT lifetime.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import structlog
from jose import JWTError, jwt
from werkzeug.security import check_password_hash

from cache.cache_client import auth_blacklist_key, exists_key, set_with_ttl
from config.settings import get_settings
from utils.log_types import LOG_TYPE_SECURITY
from db.connection import PostgresConnector
from models.auth import LoginResponse, TokenPayload
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)

# Module-level reference to the PostgresConnector, set at startup
# by init_auth_service(). This avoids passing the connector through
# every function call while keeping the dependency explicit.
_pg: PostgresConnector | None = None
# Optional SalesforceConnector — when set, the login flow verifies the
# user's vendor_id is registered in Salesforce before issuing a JWT.
# Tests that don't exercise Salesforce can omit it.
_sf: object | None = None  # SalesforceConnector

# Dev-mode mapping from seeded username to vendor_id. tbl_users does not
# store a vendor_id column yet — this dict is the bridge so the portal
# can filter GET /queries by the caller's vendor. Replace with a DB
# column or a Salesforce contact lookup in production.
#
# IDs match scripts/seed_admin_user.py and the Salesforce sf_accounts
# CSV (V-001 through V-025). All non-admin users authenticate with
# password 'vendor_user123' (admin uses 'admin123').
USER_TO_VENDOR_ID: dict[str, str] = {
    "sneha.singh": "V-001",
    "dinesh.chauhan": "V-002",
    "deepak.reddy": "V-003",
    "vendor_user": "V-001",
    "priya.menon": "V-004",
    "arjun.iyer": "V-005",
    "kavya.patel": "V-006",
    "manish.sharma": "V-007",
    "ananya.gupta": "V-008",
    "vikram.rao": "V-009",
    "ritu.kapoor": "V-010",
    "rahul.verma": "V-011",
    "meera.nair": "V-012",
    "siddharth.joshi": "V-013",
    "neha.bhatt": "V-014",
    "arvind.krishnan": "V-015",
    "divya.desai": "V-016",
    "karthik.subramanian": "V-017",
    "pooja.malhotra": "V-018",
    "rajesh.shah": "V-019",
    "swati.dixit": "V-020",
    "amit.bose": "V-021",
    "shreya.pillai": "V-022",
    "naveen.menon": "V-023",
    "simran.kaur": "V-024",
    "varun.choudhary": "V-025",
}


def resolve_vendor_id(user_name: str, role: str) -> str | None:
    """Return the vendor_id for a user, or None if role is not VENDOR."""
    if role != "VENDOR":
        return None
    return USER_TO_VENDOR_ID.get(user_name)


def init_auth_service(
    pg: PostgresConnector,
    salesforce: object | None = None,  # SalesforceConnector
) -> None:
    """Initialize the auth service with the connectors it needs.

    The SalesforceConnector is optional — when provided, the login
    flow verifies a vendor user's vendor_id is registered in Salesforce
    before issuing a JWT. When omitted, the gate degrades to a
    cache.vendor_cache lookup only (used by tests that don't exercise
    Salesforce).

    Called once during app startup (in app.lifespan).
    """
    global _pg, _sf
    _pg = pg
    _sf = salesforce


def _get_pg() -> PostgresConnector:
    """Return the module-level PostgresConnector, raising if not initialized."""
    if _pg is None:
        msg = "Auth service not initialized. Call init_auth_service() first."
        raise RuntimeError(msg)
    return _pg


class AuthenticationError(Exception):
    """Raised when authentication fails.

    Covers: invalid credentials, inactive account, missing role,
    JWT decode failure, blacklisted token. The message is safe
    to return to the client (no internal details leaked).
    """


@log_service_call
async def authenticate_user(
    username_or_email: str,
    password: str,
    *,
    correlation_id: str | None = None,
) -> LoginResponse:
    """Authenticate a user by username/email and password.

    Queries public.tbl_users to find the user, verifies the
    password hash with werkzeug, then queries public.tbl_user_roles
    for the user's role. Creates a JWT.

    Args:
        username_or_email: The username or email to log in with.
        password: Plain-text password to verify against the hash.
        correlation_id: Tracing ID for log correlation.

    Returns:
        LoginResponse with JWT token and user profile.

    Raises:
        AuthenticationError: If credentials are invalid, account
            is inactive, or no role is assigned.
    """
    pg = _get_pg()

    # Look up user by username or email
    user_row = await pg.fetchrow(
        "SELECT id, user_name, email_id, tenant, password, status, "
        "security_q1, security_a1, security_q2, security_a2, "
        "security_q3, security_a3 "
        "FROM public.tbl_users "
        "WHERE user_name = $1 OR email_id = $1 "
        "LIMIT 1",
        username_or_email,
    )

    if user_row is None:
        logger.warning(
            "Login failed — user not found",
            log_type=LOG_TYPE_SECURITY,
            event_name="login_failed",
            reason="user_not_found",
            username_or_email=username_or_email,
            correlation_id=correlation_id,
        )
        raise AuthenticationError("Invalid credentials")

    if user_row["status"] != "ACTIVE":
        logger.warning(
            "Login failed — account inactive",
            log_type=LOG_TYPE_SECURITY,
            event_name="login_failed",
            reason="inactive_account",
            user_name=user_row["user_name"],
            status=user_row["status"],
            correlation_id=correlation_id,
        )
        raise AuthenticationError("Account is inactive")

    # Verify password in a thread to avoid blocking the event loop
    # (werkzeug hashing is CPU-bound)
    password_valid = await asyncio.to_thread(
        check_password_hash, user_row["password"], password
    )
    if not password_valid:
        logger.warning(
            "Login failed — invalid password",
            log_type=LOG_TYPE_SECURITY,
            event_name="login_failed",
            reason="bad_password",
            user_name=user_row["user_name"],
            correlation_id=correlation_id,
        )
        raise AuthenticationError("Invalid credentials")

    # Look up user role
    role_row = await pg.fetchrow(
        "SELECT slno, first_name, last_name, email_id, "
        "user_name, tenant, role "
        "FROM public.tbl_user_roles "
        "WHERE user_name = $1 "
        "LIMIT 1",
        user_row["user_name"],
    )

    if role_row is None:
        logger.warning(
            "Login failed — no role assigned",
            log_type=LOG_TYPE_SECURITY,
            event_name="login_failed",
            reason="no_role",
            user_name=user_row["user_name"],
            correlation_id=correlation_id,
        )
        raise AuthenticationError("No role assigned to this user")

    role = role_row["role"]
    tenant = role_row["tenant"] or user_row["tenant"]

    # Vendor registration gate — VENDOR users must map to a known
    # vendor_id AND that vendor must exist in our system of record
    # (Salesforce, with cache.vendor_cache as a fallback when SF is
    # unreachable). Admins / reviewers bypass this gate because they
    # don't have a vendor identity.
    vendor_id = resolve_vendor_id(user_row["user_name"], role)
    if role == "VENDOR":
        await _ensure_vendor_registered(
            user_name=user_row["user_name"],
            vendor_id=vendor_id,
            correlation_id=correlation_id,
        )

    # Compose full_name from role row. Either part may be NULL in the
    # DB for legacy rows, so strip whitespace to avoid leading/trailing
    # spaces. If both parts are empty, fall back to None (Pydantic default).
    first_name = (role_row["first_name"] or "").strip()
    last_name = (role_row["last_name"] or "").strip()
    full_name = f"{first_name} {last_name}".strip() or None
    token = create_access_token(
        user_name=user_row["user_name"],
        role=role,
        tenant=tenant,
        vendor_id=vendor_id,
    )

    logger.info(
        "Login successful",
        log_type=LOG_TYPE_SECURITY,
        event_name="login_success",
        user_name=user_row["user_name"],
        role=role,
        tenant=tenant,
        correlation_id=correlation_id,
    )

    return LoginResponse(
        token=token,
        user_name=user_row["user_name"],
        full_name=full_name,
        email=user_row["email_id"],
        role=role,
        tenant=tenant,
        vendor_id=vendor_id,
    )


async def _ensure_vendor_registered(
    *,
    user_name: str,
    vendor_id: str | None,
    correlation_id: str | None,
) -> None:
    """Reject login if the user has no vendor mapping or the vendor
    cannot be found in Salesforce or the local vendor cache.

    Order of checks:
        1. vendor_id resolved? — else reject ("User has no vendor mapping")
        2. SalesforceConnector wired? — query find_vendor_by_id
            * found  → warm cache.vendor_cache and return
            * not found → reject ("Vendor account not registered")
        3. Salesforce errored or wasn't wired → fall back to
           cache.vendor_cache (last-known-good)
            * cached entry present → return (degraded mode, logged)
            * else → reject

    Raises:
        AuthenticationError: When the vendor cannot be confirmed.
    """
    if vendor_id is None:
        logger.warning(
            "Login rejected — user has no vendor mapping",
            log_type=LOG_TYPE_SECURITY,
            event_name="login_failed",
            reason="no_vendor_mapping",
            user_name=user_name,
            correlation_id=correlation_id,
        )
        raise AuthenticationError("User has no vendor mapping")

    pg = _get_pg()

    # 1. Try Salesforce when wired.
    sf_lookup_failed = False
    if _sf is not None:
        try:
            sf_record = await _sf.find_vendor_by_id(  # type: ignore[attr-defined]
                vendor_id, correlation_id=correlation_id or ""
            )
        except Exception:
            logger.warning(
                "Salesforce lookup raised during login — falling back to cache",
                tool="salesforce",
                vendor_id=vendor_id,
                correlation_id=correlation_id,
            )
            sf_record = None
            sf_lookup_failed = True

        if sf_record is not None:
            await _warm_vendor_cache(pg, vendor_id, sf_record, correlation_id)
            return

        if not sf_lookup_failed:
            # SF returned cleanly with no record — vendor is genuinely
            # not registered. Don't fall back to a stale cache entry.
            logger.warning(
                "Login rejected — vendor not registered in Salesforce",
                log_type=LOG_TYPE_SECURITY,
                event_name="login_failed",
                reason="vendor_not_registered",
                user_name=user_name,
                vendor_id=vendor_id,
                correlation_id=correlation_id,
            )
            raise AuthenticationError("Vendor account not registered")

    # 2. Salesforce unavailable (no connector or it errored) — degraded
    # mode: trust cache.vendor_cache if it has the row.
    try:
        cached = await pg.cache_read("cache.vendor_cache", "vendor_id", vendor_id)
    except Exception:
        cached = None

    if cached:
        logger.warning(
            "Login allowed via cache fallback (Salesforce unreachable)",
            tool="postgresql",
            vendor_id=vendor_id,
            user_name=user_name,
            correlation_id=correlation_id,
        )
        return

    logger.warning(
        "Login rejected — vendor not registered (no SF, no cache)",
        log_type=LOG_TYPE_SECURITY,
        event_name="login_failed",
        reason="vendor_not_registered",
        user_name=user_name,
        vendor_id=vendor_id,
        correlation_id=correlation_id,
    )
    raise AuthenticationError("Vendor account not registered")


async def _warm_vendor_cache(
    pg: PostgresConnector,
    vendor_id: str,
    sf_record: dict,
    correlation_id: str | None,
) -> None:
    """Best-effort write of the SF record into cache.vendor_cache.

    Lets the AI pipeline's context_loading skip the Salesforce hit on
    the next query for this vendor. Failure here must not break login.
    """
    import json
    from datetime import timedelta

    from utils.helpers import TimeHelper

    payload = {
        "vendor_id": vendor_id,
        "vendor_name": sf_record.get("Name", "Unknown"),
        "tier": {
            "tier_name": sf_record.get("Vendor_Tier__c") or "BRONZE",
            "sla_hours": 24,
            "priority_multiplier": 1.0,
        },
        "primary_contact_email": sf_record.get("Email") or "",
        "is_active": True,
    }
    expires_at = TimeHelper.ist_now() + timedelta(hours=1)

    try:
        await pg.execute(
            """
            INSERT INTO cache.vendor_cache (vendor_id, cache_data, expires_at)
            VALUES ($1, $2::jsonb, $3)
            ON CONFLICT (vendor_id) DO UPDATE SET
                cache_data = EXCLUDED.cache_data,
                cached_at = NOW(),
                expires_at = EXCLUDED.expires_at
            """,
            vendor_id,
            json.dumps(payload),
            expires_at,
        )
    except Exception:
        logger.debug(
            "Vendor cache warm failed — non-critical",
            vendor_id=vendor_id,
            correlation_id=correlation_id,
        )


def create_access_token(
    user_name: str,
    role: str,
    tenant: str,
    vendor_id: str | None = None,
) -> str:
    """Create a signed JWT with user claims.

    `vendor_id` is baked into the token for VENDOR users so request
    handlers can rely on it from the JWT instead of trusting any
    client-controlled header. None for ADMIN/REVIEWER.
    """
    settings = get_settings()
    now = time.time()

    claims = {
        "sub": user_name,
        "role": role,
        "tenant": tenant,
        "vendor_id": vendor_id,
        "exp": now + settings.session_timeout_seconds,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(
        claims,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


async def validate_token(token: str) -> TokenPayload | None:
    """Decode and validate a JWT token.

    Checks: valid signature, not expired, not blacklisted.
    Returns None if any check fails (invalid token).
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None

    required_claims = {"sub", "role", "tenant", "exp", "iat", "jti"}
    if not required_claims.issubset(payload.keys()):
        return None

    # Check if token has been blacklisted (logout)
    try:
        pg = _get_pg()
        blacklist_key, _ttl = auth_blacklist_key(payload["jti"])
        is_blacklisted = await exists_key(pg, blacklist_key)
        if is_blacklisted:
            return None
    except Exception:
        # Cache unavailable — allow the token rather than
        # blocking all authenticated requests
        logger.warning(
            "Cache unavailable for blacklist check — allowing token",
            jti=payload["jti"],
        )

    return TokenPayload(
        sub=payload["sub"],
        role=payload["role"],
        tenant=payload["tenant"],
        # vendor_id was added later — old tokens without it stay valid
        # by defaulting to None.
        vendor_id=payload.get("vendor_id"),
        exp=payload["exp"],
        iat=payload["iat"],
        jti=payload["jti"],
    )


@log_service_call
async def blacklist_token(
    token: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Add a token to the cache blacklist (logout)."""
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
    except JWTError as exc:
        raise AuthenticationError(f"Cannot decode token for blacklisting: {exc}") from exc

    jti = payload.get("jti")
    if not jti:
        raise AuthenticationError("Token has no JTI claim")

    try:
        pg = _get_pg()
        key, ttl = auth_blacklist_key(jti)
        await set_with_ttl(pg, key, "blacklisted", ttl)
        logger.info(
            "Token blacklisted",
            log_type=LOG_TYPE_SECURITY,
            event_name="token_blacklisted",
            jti=jti,
            user_name=payload.get("sub"),
            correlation_id=correlation_id,
        )
    except Exception:
        logger.warning(
            "Cache unavailable — token blacklist skipped",
            jti=jti,
            correlation_id=correlation_id,
        )


async def refresh_token_if_expiring(
    payload: TokenPayload,
) -> str | None:
    """Create a new token if the current one is about to expire.

    Returns a new JWT string if the current token is within
    the refresh threshold, or None if no refresh needed.
    """
    settings = get_settings()
    remaining = payload.exp - time.time()

    if remaining > settings.token_refresh_threshold_seconds:
        return None

    new_token = create_access_token(
        user_name=payload.sub,
        role=payload.role,
        tenant=payload.tenant,
    )

    # Blacklist the old token so it can't be reused
    try:
        pg = _get_pg()
        key, ttl = auth_blacklist_key(payload.jti)
        await set_with_ttl(pg, key, "refreshed", ttl)
    except Exception:
        logger.warning(
            "Cache unavailable — old token JTI not blacklisted after refresh",
            jti=payload.jti,
        )

    logger.info(
        "Token refreshed",
        log_type=LOG_TYPE_SECURITY,
        event_name="token_refreshed",
        user_name=payload.sub,
        old_jti=payload.jti,
        remaining_seconds=remaining,
    )

    return new_token
