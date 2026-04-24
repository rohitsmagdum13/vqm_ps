"""Module: connectors/eventbridge.py

AWS EventBridge connector for VQMS.

Publishes events to the VQMS event bus for audit trail and
event-driven processing. Validates event types against the
20 allowed event types before publishing.

All boto3 calls are wrapped in asyncio.to_thread because
boto3 is synchronous.

Usage:
    from connectors.eventbridge import EventBridgeConnector
    from config.settings import get_settings

    eb = EventBridgeConnector(get_settings())
    event_id = await eb.publish_event(
        "EmailParsed",
        {"query_id": "VQ-2026-0001", "sender": "vendor@example.com"},
        correlation_id="abc-123",
    )
"""

from __future__ import annotations

import asyncio

import boto3
import orjson
import structlog
from botocore.exceptions import ClientError

from config.settings import Settings
from utils.decorators import log_service_call
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# All 20 valid VQMS event types — frozen set for O(1) lookup
VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "EmailReceived",
        "EmailParsed",
        "QueryReceived",
        "AnalysisCompleted",
        "VendorResolved",
        "TicketCreated",
        "TicketUpdated",
        "DraftPrepared",
        "ValidationPassed",
        "ValidationFailed",
        "EmailSent",
        "SLAWarning70",
        "SLAEscalation85",
        "SLAEscalation95",
        "VendorReplyReceived",
        "ResolutionPrepared",
        "TicketClosed",
        "TicketReopened",
        "HumanReviewRequired",
        "HumanReviewCompleted",
    }
)


class EventBridgeConnector:
    """AWS EventBridge connector for event publishing.

    Publishes structured events to the VQMS event bus. Each event
    is enriched with a correlation_id and timestamp before publishing.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Creates the boto3 EventBridge client immediately.
        """
        self._client = boto3.client(
            "events",
            region_name=settings.aws_region,
            **settings.aws_credentials_kwargs(),
        )
        self._bus_name = settings.eventbridge_bus_name
        self._source = settings.eventbridge_source

    @log_service_call
    async def publish_event(
        self,
        event_type: str,
        detail: dict,
        *,
        correlation_id: str = "",
    ) -> str:
        """Publish an event to the VQMS EventBridge bus.

        Validates the event_type against the 20 allowed types,
        enriches the detail with correlation_id and timestamp,
        then publishes to EventBridge.

        Args:
            event_type: One of the 20 VALID_EVENT_TYPES (e.g., "EmailParsed").
            detail: Event payload dict — will be JSON-serialized.
            correlation_id: Tracing ID added to the detail automatically.

        Returns:
            The EventBridge EventId from the response.

        Raises:
            ValueError: If event_type is not in VALID_EVENT_TYPES.
            ClientError: If the publish fails.
        """
        # Validate event type before making the API call
        if event_type not in VALID_EVENT_TYPES:
            msg = f"Invalid event type: '{event_type}'. Must be one of {sorted(VALID_EVENT_TYPES)}"
            raise ValueError(msg)

        # Enrich detail with tracing fields — create a new dict
        # to avoid mutating the caller's dict (immutability principle)
        enriched_detail = {
            **detail,
            "correlation_id": correlation_id,
            "timestamp": TimeHelper.ist_now().isoformat(),
        }

        entry = {
            "Source": self._source,
            "DetailType": event_type,
            "Detail": orjson.dumps(enriched_detail).decode("utf-8"),
            "EventBusName": self._bus_name,
        }

        try:
            response = await asyncio.to_thread(
                self._client.put_events,
                Entries=[entry],
            )
        except ClientError as exc:
            logger.error(
                "EventBridge publish failed",
                tool="eventbridge",
                event_type=event_type,
                error_code=exc.response["Error"]["Code"],
                correlation_id=correlation_id,
            )
            raise

        # Check for partial failures — EventBridge can accept the API
        # call but fail to process individual entries
        failed_count = response.get("FailedEntryCount", 0)
        if failed_count > 0:
            entries = response.get("Entries", [])
            error_msg = entries[0].get("ErrorMessage", "unknown") if entries else "unknown"
            logger.error(
                "EventBridge entry failed",
                tool="eventbridge",
                event_type=event_type,
                error_message=error_msg,
                correlation_id=correlation_id,
            )

        # Return the EventId from the first (only) entry
        event_id = response["Entries"][0].get("EventId", "")
        logger.info(
            "EventBridge event published",
            tool="eventbridge",
            event_type=event_type,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        return event_id
