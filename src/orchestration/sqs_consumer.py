"""Module: orchestration/sqs_consumer.py

SQS Consumer for the VQMS AI pipeline.

Pulls messages from the email-intake and query-intake SQS queues,
deserializes the unified payload, builds the initial PipelineState,
runs the LangGraph graph, and deletes the message on success.

On failure, the message stays in the queue and will be retried
(up to 3 times, then moved to DLQ by SQS configuration).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from config.settings import Settings
from db.connection import PostgresConnector
from queues.sqs import SQSConnector
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)


def _to_jsonb_str(value: Any) -> str | None:
    """Serialize a dict to a JSON string for ::jsonb cast, or return None."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return None


class PipelineConsumer:
    """Consumes SQS messages and feeds them into the LangGraph pipeline.

    Pulls from both email-intake and query-intake queues,
    builds an initial PipelineState, invokes the compiled graph,
    and deletes the message on success.
    """

    def __init__(
        self,
        sqs: SQSConnector,
        compiled_graph: Any,
        postgres: PostgresConnector,
        settings: Settings,
    ) -> None:
        """Initialize with SQS connector and compiled graph.

        Args:
            sqs: SQS connector for message operations.
            compiled_graph: Compiled LangGraph StateGraph.
            postgres: PostgreSQL connector for status updates.
            settings: Application settings.
        """
        self._sqs = sqs
        self._graph = compiled_graph
        self._postgres = postgres
        self._settings = settings
        self._running = False

    async def process_message(self, message: dict) -> dict:
        """Process a single SQS message through the pipeline.

        Deserializes the message body, builds the initial
        PipelineState, and runs the graph.

        Args:
            message: Parsed SQS message with 'body' dict.

        Returns:
            Final PipelineState after graph execution.

        Raises:
            Exception: If graph execution fails (message stays
                in queue for retry).
        """
        body = message["body"]
        correlation_id = body.get("correlation_id", IdGenerator.generate_correlation_id())
        query_id = body.get("query_id", "UNKNOWN")
        source = body.get("source", "unknown")

        logger.info(
            "Processing pipeline message",
            step="consumer",
            query_id=query_id,
            source=source,
            correlation_id=correlation_id,
        )

        now = TimeHelper.ist_now().isoformat()

        # Build initial PipelineState from message body
        initial_state = {
            "query_id": query_id,
            "correlation_id": correlation_id,
            "execution_id": body.get("execution_id", IdGenerator.generate_execution_id()),
            "source": source,
            "unified_payload": body.get("unified_payload", body),
            "status": "RECEIVED",
            "created_at": now,
            "updated_at": now,
        }

        # Phase 6 — resume_context signals the graph to skip normal intake
        # and jump to a special entry (e.g. resolution-from-notes on
        # "prepare_resolution"). The entry-switch in graph.py reads this.
        resume_context = body.get("resume_context")
        if isinstance(resume_context, dict):
            initial_state["resume_context"] = resume_context

            # Surface prior pipeline output so the resolution-from-notes
            # branch has the vendor_context and analysis_result it needs.
            analysis_result = resume_context.get("analysis_result")
            if isinstance(analysis_result, dict):
                initial_state["analysis_result"] = analysis_result

            if resume_context.get("action") == "prepare_resolution":
                initial_state["resolution_mode"] = True
                ticket_id = resume_context.get("ticket_id")
                if ticket_id:
                    initial_state["ticket_info"] = {
                        "ticket_id": ticket_id,
                        "ticket_number": ticket_id,
                    }

        # Run the LangGraph pipeline
        result = await self._graph.ainvoke(initial_state)

        logger.info(
            "Pipeline execution complete",
            step="consumer",
            query_id=query_id,
            status=result.get("status", "UNKNOWN"),
            processing_path=result.get("processing_path"),
            correlation_id=correlation_id,
        )

        # Persist final pipeline state back to workflow.case_execution.
        # Until this happens, the row is stuck at status='RECEIVED' with
        # null analysis/draft, and the admin draft-approval queue stays
        # empty even after Path A halts. Best-effort — failure here is
        # logged but does not re-queue the SQS message because the email
        # may already have gone out (Path B) or the ticket is created.
        await self._persist_final_state(
            query_id=query_id,
            correlation_id=correlation_id,
            result=result,
        )

        return result

    async def _persist_final_state(
        self,
        *,
        query_id: str,
        correlation_id: str,
        result: dict,
    ) -> None:
        """Write the pipeline's final state into workflow.case_execution.

        Each LangGraph node returns a slice of state — analysis, routing,
        draft, ticket, status. The graph merges them into ``result`` but
        nobody persists them back to PG. This method does that single
        UPDATE so the admin UI / draft-approval queue / query detail
        page see the actual outcome of the run.

        Columns updated:
          - status              : final pipeline status (PENDING_APPROVAL,
                                  AWAITING_RESOLUTION, RESOLVED, etc.)
          - processing_path     : 'A', 'B', or 'C'
          - analysis_result     : JSONB from QueryAnalysisNode
          - routing_decision    : JSONB from RoutingNode
          - draft_response      : JSONB stash from DeliveryNode
                                  (subject + body + recipient)
          - quality_gate_result : JSONB from QualityGateNode
          - updated_at          : NOW()
        """
        if not query_id:
            return

        try:
            await self._postgres.execute(
                """
                UPDATE workflow.case_execution
                SET status              = COALESCE($1, status),
                    processing_path     = COALESCE($2, processing_path),
                    analysis_result     = COALESCE($3::jsonb, analysis_result),
                    routing_decision    = COALESCE($4::jsonb, routing_decision),
                    draft_response      = COALESCE($5::jsonb, draft_response),
                    quality_gate_result = COALESCE($6::jsonb, quality_gate_result),
                    updated_at          = $7
                WHERE query_id = $8
                """,
                result.get("status"),
                result.get("processing_path"),
                _to_jsonb_str(result.get("analysis_result")),
                _to_jsonb_str(result.get("routing_decision")),
                _to_jsonb_str(result.get("draft_response")),
                _to_jsonb_str(result.get("quality_gate_result")),
                TimeHelper.ist_now(),
                query_id,
            )
            logger.info(
                "case_execution persisted",
                step="consumer",
                query_id=query_id,
                status=result.get("status"),
                processing_path=result.get("processing_path"),
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "Failed to persist final case_execution state — query "
                "timeline still shows progress via audit.action_log, but "
                "draft / status columns will be stale",
                step="consumer",
                query_id=query_id,
                correlation_id=correlation_id,
            )

    async def start_consumer(self, queue_url: str) -> None:
        """Start long-polling loop for a single SQS queue.

        Continuously polls the queue, processes messages, and
        deletes them on success. On failure, the message remains
        in the queue for SQS retry (up to 3 times, then DLQ).

        Args:
            queue_url: Full URL of the SQS queue to consume.
        """
        self._running = True
        logger.info(
            "Consumer started",
            step="consumer",
            queue_url=queue_url,
        )

        while self._running:
            try:
                messages = await self._sqs.receive_messages(
                    queue_url,
                    max_messages=1,
                    wait_time_seconds=20,
                )

                if not messages:
                    continue

                for msg in messages:
                    try:
                        await self.process_message(msg)

                        # Success — delete the message
                        await self._sqs.delete_message(
                            queue_url,
                            msg["receipt_handle"],
                            correlation_id=msg["body"].get("correlation_id", ""),
                        )
                    except Exception:
                        # Failure — message stays in queue for retry
                        logger.exception(
                            "Failed to process message — will retry",
                            step="consumer",
                            message_id=msg["message_id"],
                            query_id=msg["body"].get("query_id", "UNKNOWN"),
                        )

            except Exception:
                # SQS receive itself failed — wait before retrying
                logger.exception(
                    "SQS receive error — waiting before retry",
                    step="consumer",
                    queue_url=queue_url,
                )
                await asyncio.sleep(5)

    def stop(self) -> None:
        """Signal the consumer to stop polling."""
        self._running = False
        logger.info("Consumer stop requested", step="consumer")

    async def consume_both_queues(self) -> None:
        """Start consumers for both email and query intake queues.

        Runs two long-polling loops concurrently via asyncio.gather.
        """
        logger.info(
            "Starting dual-queue consumer",
            step="consumer",
            email_queue=self._settings.sqs_email_intake_queue_url,
            query_queue=self._settings.sqs_query_intake_queue_url,
        )

        await asyncio.gather(
            self.start_consumer(self._settings.sqs_email_intake_queue_url),
            self.start_consumer(self._settings.sqs_query_intake_queue_url),
        )
