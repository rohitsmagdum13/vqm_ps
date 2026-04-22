"""Module: services/email_intake/relevance_filter.py

Pre-pipeline filter that drops obviously-not-a-query emails before
they reach Bedrock.

Without this filter, a vendor emailing only "hello" or an Outlook
auto-reply will propagate through the whole ingestion pipeline and
end up calling Claude Sonnet in the Query Analysis node — wasting
tokens for a confidence score that was always going to be low.

Tiered filter (cheap -> expensive):
    Layer 2: Sender allowlist     — unknown senders rejected
    Layer 3: Content sanity       — length, noise words, auto-reply headers
    Layer 4: Optional LLM gate    — Claude Haiku binary classifier

(Layer 1 — the Graph API `$filter` — lives in adapters/graph_api/email_fetch.py.)
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import structlog

from config.settings import Settings
from models.email import RelevanceDecision
from utils.decorators import log_service_call
from utils.exceptions import BedrockTimeoutError

if TYPE_CHECKING:
    from adapters.bedrock import BedrockConnector

logger = structlog.get_logger(__name__)

# Headers that identify auto-generated mail. Presence of any one marks
# the email as machine-sent — never a real vendor query.
_AUTO_SUBMITTED_HEADERS = frozenset({
    "auto-submitted",
    "x-auto-response-suppress",
    "x-autoreply",
    "x-autorespond",
    "list-unsubscribe",
    "list-id",
})

# Precedence header values that indicate bulk/auto mail.
_BULK_PRECEDENCE_VALUES = frozenset({"bulk", "list", "junk", "auto_reply"})

# Subject prefixes typical of auto-replies. Layer 1 already catches
# most of these at Graph API fetch time, but polling in environments
# without the $filter (older Exchange servers) might still surface them.
_AUTO_REPLY_SUBJECT_PREFIXES = (
    "automatic reply",
    "auto: ",
    "out of office",
    "undeliverable",
    "delivery status notification",
    "mail delivery failure",
)

# LLM classifier — tiny prompt, temperature 0, just "is this a query?".
# Uses the fallback (Haiku) model so cost stays well under 1¢ per call.
_CLASSIFIER_SYSTEM_PROMPT = (
    "You are a lightweight email classifier for VQMS, a vendor query "
    "management system. Decide whether an email is a substantive vendor "
    "question that needs investigation. Reply with ONLY a JSON object: "
    '{"is_query": true|false, "reason": "<short reason>"}.'
)


class EmailRelevanceFilter:
    """Decides whether an email should enter the AI pipeline.

    Each filter layer is independent and returns a reject decision
    as soon as a rule matches. The LLM classifier only runs when
    the deterministic layers are inconclusive AND the setting
    ``email_filter_use_llm_classifier`` is true.
    """

    def __init__(
        self,
        settings: Settings,
        bedrock: "BedrockConnector | None" = None,
    ) -> None:
        """Initialize with config and an optional Bedrock adapter.

        Args:
            settings: Application settings (thresholds, noise patterns).
            bedrock: BedrockConnector for Layer 4. Can be None when
                the LLM classifier is disabled.
        """
        self._settings = settings
        self._bedrock = bedrock

        # Pre-compile a case-insensitive regex matching any noise
        # pattern at the whole-string level so we don't rebuild it
        # on every email.
        escaped = [re.escape(p) for p in settings.email_filter_noise_patterns]
        self._noise_regex = re.compile(
            r"^\s*(?:" + "|".join(escaped) + r")\s*[.!?]*\s*$",
            re.IGNORECASE,
        ) if escaped else None

        self._allowed_domains = {
            d.lower().lstrip("@") for d in settings.email_filter_allowed_sender_domains
        }

    @log_service_call
    async def evaluate(
        self,
        *,
        parsed: dict,
        raw_email: dict,
        vendor_id: str | None,
        vendor_match_method: str | None,
        correlation_id: str,
    ) -> RelevanceDecision:
        """Run the filter layers in order and return the first rejection.

        Args:
            parsed: Output of EmailParser.parse_email_fields.
            raw_email: The raw Graph API message dict (for headers).
            vendor_id: Resolved vendor ID, or None if unresolved.
            vendor_match_method: How vendor was matched, or "unresolved".
            correlation_id: Tracing ID.

        Returns:
            RelevanceDecision. If ``accept`` is True the caller should
            continue the pipeline; otherwise use ``action`` to decide
            whether to drop, auto-reply, or run thread-only handling.
        """
        subject = (parsed.get("subject") or "").strip()
        body_text = (parsed.get("body_text") or "").strip()
        sender = parsed.get("sender_email", "")

        # Layer 2 — Sender allowlist
        sender_decision = self._check_sender(
            sender=sender,
            vendor_id=vendor_id,
            vendor_match_method=vendor_match_method,
        )
        if sender_decision is not None:
            self._log_rejection(sender_decision, sender, correlation_id)
            return sender_decision

        # Layer 3 — Deterministic content sanity
        content_decision = self._check_content(
            subject=subject,
            body_text=body_text,
            raw_email=raw_email,
        )
        if content_decision is not None:
            self._log_rejection(content_decision, sender, correlation_id)
            return content_decision

        # Layer 4 — LLM classifier (only for borderline content)
        if (
            self._settings.email_filter_use_llm_classifier
            and self._bedrock is not None
            and self._is_borderline(subject, body_text)
        ):
            llm_decision = await self._classify_with_llm(
                subject=subject,
                body_text=body_text,
                correlation_id=correlation_id,
            )
            if llm_decision is not None:
                self._log_rejection(llm_decision, sender, correlation_id)
                return llm_decision

        return RelevanceDecision(
            accept=True,
            reason="passed_all_filters",
            action="drop",  # unused when accept=True; placeholder
            layer="passed",
        )

    # ------------------------------------------------------------------
    # Layer 2 — Sender allowlist
    # ------------------------------------------------------------------

    def _check_sender(
        self,
        *,
        sender: str,
        vendor_id: str | None,
        vendor_match_method: str | None,
    ) -> RelevanceDecision | None:
        """Reject mail from senders we can't tie to a vendor.

        We allow the email through if Salesforce found the vendor OR the
        sender's domain is on the ops-managed allowlist (for onboarding).
        """
        if vendor_id is not None and vendor_match_method != "unresolved":
            return None

        domain = sender.rsplit("@", 1)[-1].lower() if "@" in sender else ""
        if domain and domain in self._allowed_domains:
            return None

        return RelevanceDecision(
            accept=False,
            reason=f"unknown_sender:{sender or 'missing'}",
            action="auto_reply_ask_details",
            layer="sender_allowlist",
        )

    # ------------------------------------------------------------------
    # Layer 3 — Content sanity
    # ------------------------------------------------------------------

    def _check_content(
        self,
        *,
        subject: str,
        body_text: str,
        raw_email: dict,
    ) -> RelevanceDecision | None:
        """Reject emails that are clearly not a real query.

        Order matters: check auto-reply headers first (they're the
        cheapest and most decisive), then subject prefix, then length,
        then noise-word match.
        """
        headers = _normalize_headers(raw_email)

        if _has_auto_submitted_header(headers):
            return RelevanceDecision(
                accept=False,
                reason="auto_submitted_header",
                action="drop",
                layer="content_sanity",
            )

        precedence = headers.get("precedence", "").strip().lower()
        if precedence in _BULK_PRECEDENCE_VALUES:
            return RelevanceDecision(
                accept=False,
                reason=f"bulk_precedence:{precedence}",
                action="drop",
                layer="content_sanity",
            )

        lowered_subject = subject.lower()
        for prefix in _AUTO_REPLY_SUBJECT_PREFIXES:
            if lowered_subject.startswith(prefix):
                return RelevanceDecision(
                    accept=False,
                    reason=f"auto_reply_subject:{prefix}",
                    action="drop",
                    layer="content_sanity",
                )

        stripped_body = _strip_quoted_reply(body_text)

        # An empty reply to an existing thread is still useful signal
        # for closure / reopen detection — flag it as thread_only so
        # the caller can skip analysis but keep that side path.
        if lowered_subject.startswith("re:") and not stripped_body.strip():
            return RelevanceDecision(
                accept=False,
                reason="empty_reply",
                action="thread_only",
                layer="content_sanity",
            )

        meaningful_chars = len(_meaningful_chars(subject, stripped_body))
        if meaningful_chars < self._settings.email_filter_min_chars:
            return RelevanceDecision(
                accept=False,
                reason=f"too_short:{meaningful_chars}",
                action="auto_reply_ask_details",
                layer="content_sanity",
            )

        if self._noise_regex is not None:
            combined = f"{subject} {stripped_body}".strip()
            if self._noise_regex.match(combined):
                return RelevanceDecision(
                    accept=False,
                    reason="noise_word_only",
                    action="auto_reply_ask_details",
                    layer="content_sanity",
                )

        return None

    # ------------------------------------------------------------------
    # Layer 4 — LLM classifier
    # ------------------------------------------------------------------

    @staticmethod
    def _is_borderline(subject: str, body_text: str) -> bool:
        """Only send the LLM emails that look short-ish but not empty.

        Long, substantive emails are almost certainly real queries —
        no need to spend a Haiku call. Very short ones were already
        caught by Layer 3.
        """
        combined_len = len(subject) + len(body_text)
        return 50 <= combined_len <= 300

    async def _classify_with_llm(
        self,
        *,
        subject: str,
        body_text: str,
        correlation_id: str,
    ) -> RelevanceDecision | None:
        """Ask Claude Haiku a yes/no question about the email.

        Returns a rejection decision when the classifier says "no",
        None when it says "yes" (meaning: keep going through the
        pipeline), and None on any error — failing open is safer
        than dropping a real query because the classifier hiccuped.
        """
        assert self._bedrock is not None  # guarded by caller

        prompt = (
            "Subject: "
            + (subject or "(no subject)")
            + "\n\nBody:\n"
            + (body_text[:1500] if body_text else "(empty body)")
        )

        try:
            result = await self._bedrock.llm_complete(
                prompt=prompt,
                system_prompt=_CLASSIFIER_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=80,
                correlation_id=correlation_id,
            )
        except BedrockTimeoutError:
            logger.warning(
                "Relevance LLM classifier timed out — failing open",
                tool="email_intake",
                layer="llm_classifier",
                correlation_id=correlation_id,
            )
            return None
        except Exception as exc:
            logger.warning(
                "Relevance LLM classifier errored — failing open",
                tool="email_intake",
                layer="llm_classifier",
                error=str(exc),
                correlation_id=correlation_id,
            )
            return None

        parsed_json = _try_parse_json(result.get("response_text", ""))
        if parsed_json is None:
            logger.warning(
                "Relevance LLM returned non-JSON — failing open",
                tool="email_intake",
                layer="llm_classifier",
                raw=result.get("response_text", "")[:200],
                correlation_id=correlation_id,
            )
            return None

        is_query = bool(parsed_json.get("is_query", True))
        if is_query:
            return None

        reason = str(parsed_json.get("reason", "not_a_query"))[:120]
        return RelevanceDecision(
            accept=False,
            reason=f"llm:{reason}",
            action="auto_reply_ask_details",
            layer="llm_classifier",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_rejection(
        decision: RelevanceDecision, sender: str, correlation_id: str
    ) -> None:
        """Single place for the rejection log line — keeps shape consistent."""
        logger.info(
            "Email rejected by relevance filter",
            tool="email_intake",
            layer=decision.layer,
            reason=decision.reason,
            action=decision.action,
            sender=sender,
            correlation_id=correlation_id,
        )


# ---------------------------------------------------------------------
# Module-level helpers (pure functions — easy to unit-test in isolation)
# ---------------------------------------------------------------------


def _normalize_headers(raw_email: dict) -> dict[str, str]:
    """Flatten Graph API's internetMessageHeaders list into a dict.

    Graph returns a list of {name, value} pairs with case-preserved
    names. We lowercase the name so callers can look up any header
    without worrying about capitalization.
    """
    headers: dict[str, str] = {}
    for header in raw_email.get("internetMessageHeaders", []) or []:
        name = (header.get("name") or "").strip().lower()
        value = header.get("value") or ""
        if name:
            headers[name] = value
    return headers


def _has_auto_submitted_header(headers: dict[str, str]) -> bool:
    """Return True when any auto-reply / bulk-list header is present."""
    for name, value in headers.items():
        if name not in _AUTO_SUBMITTED_HEADERS:
            continue
        # Auto-Submitted can legitimately be "no" — treat only the
        # affirmative values as auto-reply markers.
        if name == "auto-submitted":
            if value.strip().lower() not in {"", "no"}:
                return True
            continue
        return True
    return False


_QUOTED_REPLY_SPLITTERS = (
    "\n-----Original Message-----",
    "\nOn ",  # "On Tue, Jan 1..." — common Gmail-style quoting
    "\nFrom: ",
    "\n> ",
)


def _strip_quoted_reply(body_text: str) -> str:
    """Remove the quoted portion of a reply so we measure only new content.

    This is intentionally conservative — we only cut at well-known
    quote markers so we don't accidentally drop legitimate body text.
    """
    if not body_text:
        return ""
    earliest = len(body_text)
    for marker in _QUOTED_REPLY_SPLITTERS:
        idx = body_text.find(marker)
        if 0 <= idx < earliest:
            earliest = idx
    return body_text[:earliest].strip()


_NON_MEANINGFUL = re.compile(r"[\s\W_]+")


def _meaningful_chars(subject: str, body_text: str) -> str:
    """Return subject+body with whitespace/punctuation stripped.

    Used to measure whether the email has enough substance to be a
    real query. "hello!!!" collapses to "hello" (5 chars) which is
    well below the default 30-char threshold.
    """
    combined = f"{subject} {body_text}"
    return _NON_MEANINGFUL.sub("", combined)


def _try_parse_json(text: str) -> dict | None:
    """Best-effort JSON parse for the LLM classifier response.

    Handles both clean JSON and responses wrapped in ```json fences.
    Returns None on any parse failure — callers should fail open.
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop opening fence (``` or ```json) and closing fence
        stripped = stripped.split("\n", 1)[-1]
        if stripped.endswith("```"):
            stripped = stripped[: -3]
        stripped = stripped.strip()
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None
