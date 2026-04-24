"""Module: adapters/servicenow/client.py

ServiceNow client initialization and authentication.

Manages the httpx async client with lazy initialization and
provides shared helper methods and constants used across all
ServiceNow operation classes.
"""

from __future__ import annotations

import httpx
import structlog

from config.settings import Settings

logger = structlog.get_logger(__name__)

# ServiceNow priority mapping: VQMS priority string -> ServiceNow numeric value
# ServiceNow uses 1=Critical, 2=High, 3=Moderate, 4=Low
PRIORITY_MAP = {
    "CRITICAL": "1",
    "HIGH": "2",
    "MEDIUM": "3",
    "LOW": "4",
}

# VQMS priority -> ServiceNow (impact, urgency) pair. ServiceNow derives
# Priority from an Impact × Urgency matrix by default. Sending both alongside
# the explicit priority keeps Priority correct while also populating the
# impact/urgency columns that dashboards, SLA widgets, and filters rely on.
# ServiceNow values: 1=High, 2=Medium, 3=Low.
IMPACT_URGENCY_MAP = {
    "CRITICAL": ("1", "1"),
    "HIGH": ("2", "1"),
    "MEDIUM": ("2", "2"),
    "LOW": ("3", "2"),
}

# ServiceNow expects datetimes in "YYYY-MM-DD HH:mm:ss" format on the
# Table API. We hold IST times in Python; ServiceNow will display them
# in the user's session timezone.
SERVICENOW_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ServiceNowConnectorError(Exception):
    """Raised when a ServiceNow API call fails."""


class ServiceNowClient:
    """Base ServiceNow client with connection management.

    Uses lazy initialization for the httpx client — it's only
    created on the first API call. This avoids connection errors
    during startup if ServiceNow credentials aren't configured yet.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Does NOT connect to ServiceNow yet. The httpx client is
        created lazily on first use via _get_client().

        Args:
            settings: Application settings with ServiceNow config.
        """
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._base_url: str = ""
        # Per-process cache for sys_user_group name lookups. Maps the
        # queried name to the same name when it exists in ServiceNow, or
        # to "" when no such group exists. We cache both hits and misses
        # so we don't re-query ServiceNow on every ticket creation.
        self._group_name_cache: dict[str, str] = {}
        # Per-process cache for sys_user display-name lookups. Keys are
        # `user_name` values (e.g. "admin"), values are the user's `name`
        # field (e.g. "System Administrator"), or "" when the user cannot
        # be resolved.
        self._user_display_name_cache: dict[str, str] = {}
        # Per-process cache for sys_user sys_id lookups. Same key shape as
        # the display-name cache above. Exists because corporate ServiceNow
        # orgs often have multiple users with the same ``name`` (display)
        # field — e.g. two people both called "Arun" with a trailing-space
        # variant — which makes display-value resolution unreliable. POSTing
        # caller_id as a sys_id skips the ambiguity entirely.
        self._user_sys_id_cache: dict[str, str] = {}

    def _resolve_base_url(self) -> str:
        """Work out the ServiceNow base URL from settings.

        Two ways to configure:
          1. servicenow_instance_url — full URL like
             https://dev123456.service-now.com (trailing slash tolerated)
          2. servicenow_instance_name — short name like dev123456, which
             gets expanded to https://dev123456.service-now.com

        Option 1 wins if both are set. Raises if neither is configured.
        """
        full_url = (self._settings.servicenow_instance_url or "").strip()
        if full_url:
            return full_url.rstrip("/")

        instance_name = (self._settings.servicenow_instance_name or "").strip()
        if instance_name:
            # Guard against someone pasting a full URL here by mistake —
            # strip scheme/domain leftovers so we always end up with just
            # the short instance identifier before building the URL.
            short_name = instance_name
            if "://" in short_name:
                short_name = short_name.split("://", 1)[1]
            short_name = short_name.split("/", 1)[0]
            short_name = short_name.split(".", 1)[0]
            short_name = short_name.rstrip("/")
            if not short_name:
                raise ServiceNowConnectorError(
                    "SERVICENOW_INSTANCE_NAME is set but appears empty after "
                    "normalization"
                )
            return f"https://{short_name}.service-now.com"

        raise ServiceNowConnectorError(
            "ServiceNow is not configured: set either SERVICENOW_INSTANCE_URL "
            "(full URL) or SERVICENOW_INSTANCE_NAME (short name, e.g. "
            "'dev123456')"
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client.

        Lazy initialization — the client is created on first call
        and cached for subsequent calls.

        Returns:
            Configured httpx.AsyncClient with basic auth.

        Raises:
            ServiceNowConnectorError: If required credentials are missing.
        """
        if self._client is not None:
            return self._client

        self._base_url = self._resolve_base_url()

        username = self._settings.servicenow_username
        password = self._settings.servicenow_password

        if not username or not password:
            raise ServiceNowConnectorError(
                "SERVICENOW_USERNAME and SERVICENOW_PASSWORD are required"
            )

        logger.info(
            "ServiceNow client initialized",
            tool="servicenow",
            base_url=self._base_url,
        )

        self._client = httpx.AsyncClient(
            auth=(username, password),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        return self._client

    async def close(self) -> None:
        """Close the httpx client. Call during app shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def resolve_group_name(self, name: str) -> str:
        """Return `name` if a sys_user_group with that exact name exists.

        ServiceNow reference fields (assignment_group, caller_id, etc.)
        silently drop unresolvable values — the incident is created with
        an empty reference, which means it never shows up under any
        group-scoped view in the UI. We avoid that by pre-checking that
        the group name resolves before POSTing the ticket.

        Args:
            name: The group name to check (e.g. "VQMS Support").

        Returns:
            The input `name` if a matching group exists, else "".
            Both hits and misses are cached per process.
        """
        lookup = (name or "").strip()
        if not lookup:
            return ""

        cached = self._group_name_cache.get(lookup)
        if cached is not None:
            return cached

        try:
            client = self._get_client()
            url = f"{self._base_url}/api/now/table/sys_user_group"
            response = await client.get(
                url,
                params={
                    "sysparm_query": f"name={lookup}",
                    "sysparm_fields": "sys_id,name",
                    "sysparm_limit": 1,
                },
            )
            response.raise_for_status()
            results = response.json().get("result", []) or []
            resolved = lookup if results else ""
        except Exception:  # noqa: BLE001 - lookup failure is non-critical
            # Don't let a group lookup failure block ticket creation —
            # treat it as "unresolved" and let the caller decide what
            # to do. A warning is enough; the ticket will still post.
            logger.warning(
                "ServiceNow group lookup failed — treating as unresolved",
                tool="servicenow",
                group=lookup,
            )
            resolved = ""

        self._group_name_cache[lookup] = resolved
        return resolved

    async def resolve_user_display_name(self, user_name: str) -> str:
        """Return the `name` (display value) of a sys_user given `user_name`.

        Needed because we POST tickets with sysparm_input_display_value=true,
        which means reference fields must be sent as their human-readable
        display value. For sys_user records the display value is the
        `name` field (e.g. "System Administrator"), not the `user_name`
        ("admin"). Sending the wrong one leaves the reference unresolved
        and the ticket becomes invisible to "Self Service" / "Caller = me"
        style views in the ServiceNow UI.

        Args:
            user_name: The sys_user.user_name to look up (e.g. "admin").

        Returns:
            The user's `name` field when found, else "". Results (hit or
            miss) are cached per process.
        """
        lookup = (user_name or "").strip()
        if not lookup:
            return ""

        cached = self._user_display_name_cache.get(lookup)
        if cached is not None:
            return cached

        try:
            client = self._get_client()
            url = f"{self._base_url}/api/now/table/sys_user"
            response = await client.get(
                url,
                params={
                    "sysparm_query": f"user_name={lookup}",
                    "sysparm_fields": "sys_id,user_name,name",
                    "sysparm_limit": 1,
                },
            )
            response.raise_for_status()
            results = response.json().get("result", []) or []
            resolved = ""
            if results:
                # Fall back to user_name itself if `name` is blank, which
                # can happen on lightly-configured PDI users.
                resolved = (results[0].get("name") or "").strip() or lookup
        except Exception:  # noqa: BLE001 - lookup failure is non-critical
            logger.warning(
                "ServiceNow user lookup failed — caller_id will be blank",
                tool="servicenow",
                user_name=lookup,
            )
            resolved = ""

        self._user_display_name_cache[lookup] = resolved
        return resolved

    async def resolve_user_sys_id(self, user_name: str) -> str:
        """Return the sys_user.sys_id for a given `user_name`.

        Why this exists instead of just using the display name:
        ServiceNow's ``sysparm_input_display_value=true`` resolves
        reference fields by matching the *display* field. For sys_user
        that's ``name``, and in real-world orgs multiple users can
        share a ``name`` (classic homonyms like two "Arun" entries,
        or a subtle variant with a trailing space). When resolution is
        ambiguous, ServiceNow picks an arbitrary match — the ticket
        ends up linked to the wrong user, and UI filters like
        ``Affected User = <me>`` don't show it.

        POSTing the sys_id directly avoids the ambiguity entirely.
        ServiceNow accepts a sys_id in any reference field regardless
        of the display-value flag.

        Args:
            user_name: The sys_user.user_name to look up (the login,
                e.g. ``"admin"`` or ``"ArunkumarV@hexaware.com"``).

        Returns:
            The user's sys_id, or "" when the lookup fails. Results
            (hit or miss) are cached per process.
        """
        lookup = (user_name or "").strip()
        if not lookup:
            return ""

        cached = self._user_sys_id_cache.get(lookup)
        if cached is not None:
            return cached

        try:
            client = self._get_client()
            url = f"{self._base_url}/api/now/table/sys_user"
            response = await client.get(
                url,
                params={
                    "sysparm_query": f"user_name={lookup}",
                    "sysparm_fields": "sys_id,user_name,name",
                    "sysparm_limit": 1,
                },
            )
            response.raise_for_status()
            results = response.json().get("result", []) or []
            resolved = (results[0].get("sys_id") or "").strip() if results else ""
        except Exception:  # noqa: BLE001 - lookup failure is non-critical
            logger.warning(
                "ServiceNow user sys_id lookup failed — caller_id will "
                "fall back to display name and may resolve to the wrong user",
                tool="servicenow",
                user_name=lookup,
            )
            resolved = ""

        self._user_sys_id_cache[lookup] = resolved
        return resolved

    @staticmethod
    def status_to_state(status: str) -> str:
        """Map a human-readable status to ServiceNow state integer.

        ServiceNow uses integer state codes internally:
        1=New, 2=In Progress, 3=On Hold, 6=Resolved, 7=Closed.
        """
        mapping = {
            "New": "1",
            "In Progress": "2",
            "On Hold": "3",
            "Resolved": "6",
            "Closed": "7",
        }
        return mapping.get(status, "1")

    @staticmethod
    def state_to_status(state: str) -> str:
        """Map a ServiceNow state integer to human-readable status."""
        mapping = {
            "1": "New",
            "2": "In Progress",
            "3": "On Hold",
            "6": "Resolved",
            "7": "Closed",
        }
        return mapping.get(str(state), "New")
