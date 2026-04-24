"""Module: connectors/sqs.py

AWS SQS connector for VQMS.

Handles sending, receiving, and deleting messages on all VQMS
SQS queues. Messages are serialized as JSON using orjson for
performance. All boto3 calls are wrapped in asyncio.to_thread
because boto3 is synchronous.

Usage:
    from connectors.sqs import SQSConnector
    from config.settings import get_settings

    sqs = SQSConnector(get_settings())
    msg_id = await sqs.send_message(queue_url, {"query_id": "VQ-2026-0001"})
    messages = await sqs.receive_messages(queue_url)
    await sqs.delete_message(queue_url, messages[0]["receipt_handle"])
"""

from __future__ import annotations

import asyncio

import boto3
import orjson
import structlog
from botocore.exceptions import ClientError

from config.settings import Settings
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class SQSConnector:
    """AWS SQS connector for message queue operations.

    All methods are async. Boto3 sync calls are executed in a
    thread pool via asyncio.to_thread to avoid blocking the
    event loop.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Creates the boto3 SQS client immediately.
        """
        self._client = boto3.client(
            "sqs",
            region_name=settings.aws_region,
            **settings.aws_credentials_kwargs(),
        )
        self._settings = settings

    @log_service_call
    async def send_message(
        self,
        queue_url: str,
        message_body: dict,
        *,
        correlation_id: str = "",
        delay_seconds: int = 0,
    ) -> str:
        """Send a message to an SQS queue.

        Args:
            queue_url: Full URL of the SQS queue.
            message_body: Dict to serialize as JSON message body.
            correlation_id: Tracing ID for structured logging.
            delay_seconds: Delay before message becomes visible (0-900).

        Returns:
            The SQS MessageId of the sent message.

        Raises:
            ClientError: If the send fails (e.g., queue not found, AccessDenied).
        """
        # orjson.dumps returns bytes, SQS needs a string
        body_json = orjson.dumps(message_body).decode("utf-8")

        try:
            response = await asyncio.to_thread(
                self._client.send_message,
                QueueUrl=queue_url,
                MessageBody=body_json,
                DelaySeconds=delay_seconds,
            )
            message_id = response["MessageId"]
            logger.info(
                "SQS message sent",
                tool="sqs",
                queue_url=queue_url,
                message_id=message_id,
                correlation_id=correlation_id,
            )
            return message_id
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            logger.error(
                "SQS send failed",
                tool="sqs",
                queue_url=queue_url,
                error_code=error_code,
                correlation_id=correlation_id,
            )
            raise

    @log_service_call
    async def receive_messages(
        self,
        queue_url: str,
        max_messages: int = 1,
        wait_time_seconds: int = 20,
        *,
        correlation_id: str = "",
    ) -> list[dict]:
        """Receive messages from an SQS queue.

        Uses long polling (WaitTimeSeconds) to reduce empty responses.
        Each returned message includes message_id, receipt_handle,
        and the parsed body dict.

        Args:
            queue_url: Full URL of the SQS queue.
            max_messages: Maximum messages to receive (1-10).
            wait_time_seconds: Long polling duration (0-20 seconds).
            correlation_id: Tracing ID for structured logging.

        Returns:
            List of dicts with keys: message_id, receipt_handle, body.
            Empty list if no messages available.
        """
        try:
            response = await asyncio.to_thread(
                self._client.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time_seconds,
            )
        except ClientError as exc:
            logger.error(
                "SQS receive failed",
                tool="sqs",
                queue_url=queue_url,
                error_code=exc.response["Error"]["Code"],
                correlation_id=correlation_id,
            )
            raise

        raw_messages = response.get("Messages", [])
        if not raw_messages:
            return []

        parsed_messages = []
        for msg in raw_messages:
            parsed_body = orjson.loads(msg["Body"])
            parsed_messages.append(
                {
                    "message_id": msg["MessageId"],
                    "receipt_handle": msg["ReceiptHandle"],
                    "body": parsed_body,
                }
            )

        logger.info(
            "SQS messages received",
            tool="sqs",
            queue_url=queue_url,
            count=len(parsed_messages),
            correlation_id=correlation_id,
        )
        return parsed_messages

    @log_service_call
    async def delete_message(
        self,
        queue_url: str,
        receipt_handle: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """Delete a message from an SQS queue after processing.

        Must be called after successful processing to prevent
        the message from becoming visible again after the
        visibility timeout expires.

        Args:
            queue_url: Full URL of the SQS queue.
            receipt_handle: Receipt handle from receive_messages.
            correlation_id: Tracing ID for structured logging.

        Raises:
            ClientError: If the delete fails.
        """
        try:
            await asyncio.to_thread(
                self._client.delete_message,
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.info(
                "SQS message deleted",
                tool="sqs",
                queue_url=queue_url,
                correlation_id=correlation_id,
            )
        except ClientError as exc:
            logger.error(
                "SQS delete failed",
                tool="sqs",
                queue_url=queue_url,
                error_code=exc.response["Error"]["Code"],
                correlation_id=correlation_id,
            )
            raise
