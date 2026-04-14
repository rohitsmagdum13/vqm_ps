"""Module: utils/logging_setup.py

Structured logging configuration for VQMS.

All application code uses structlog.get_logger() with keyword arguments.
Under the hood, structlog routes through stdlib LoggerFactory so that
both console output and the rotating file handler receive all logs.

Key design decisions:
- IST timestamps (per CLAUDE.md — Indian Standard Time, not UTC)
- stdlib.LoggerFactory so logs hit both console and file handlers
- ConsoleRenderer in dev, JSONRenderer in prod
- contextvars support for automatic correlation_id propagation
- Rotating file handler captures ALL logs (app + third-party)

Usage:
    from utils.logging_setup import LoggingSetup

    LoggingSetup.configure()  # Call once at app startup

    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("Email processed", tool="s3", query_id="VQ-2026-0001")
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from dataclasses import dataclass
from pathlib import Path

import structlog

from utils.helpers import TimeHelper


@dataclass
class LogContext:
    """Structured context passed through the VQMS pipeline.

    Every log entry in the pipeline should include at minimum
    the correlation_id and step_name. Other fields are optional
    and added as the query progresses through the pipeline.
    """

    correlation_id: str = ""
    step_name: str = ""
    query_id: str | None = None
    vendor_id: str | None = None

    def as_dict(self) -> dict:
        """Convert to a dict, excluding None values."""
        result = {
            "correlation_id": self.correlation_id,
            "step_name": self.step_name,
        }
        if self.query_id is not None:
            result["query_id"] = self.query_id
        if self.vendor_id is not None:
            result["vendor_id"] = self.vendor_id
        return result


def _add_ist_timestamp(
    logger: object, method_name: str, event_dict: dict
) -> dict:
    """Add an IST timestamp to every log entry.

    CLAUDE.md mandates IST (Indian Standard Time) for all timestamps.
    """
    event_dict["timestamp"] = TimeHelper.ist_now().isoformat()
    return event_dict


class LoggingSetup:
    """Configures structured logging for the VQMS application.

    Uses structlog.stdlib.LoggerFactory so that all application logs
    route through stdlib handlers. This means both the console handler
    and the rotating file handler receive every log line — application
    AND third-party.

    Application code still uses structlog.get_logger() with kwargs.
    The factory choice only controls WHERE output goes, not HOW
    application code calls the logger.
    """

    _configured: bool = False

    @staticmethod
    def configure(log_level: str = "DEBUG") -> None:
        """Configure structlog and stdlib logging.

        Safe to call multiple times — only the first call takes effect.

        Args:
            log_level: The minimum log level (DEBUG, INFO, WARNING, ERROR).
                       Defaults to DEBUG for development.
        """
        if LoggingSetup._configured:
            return

        is_debug = os.environ.get("APP_DEBUG", "true").lower() == "true"

        # --- stdlib handlers: console + rotating file ---
        # Both application (via structlog) and third-party logs go
        # through stdlib handlers so everything reaches the file.
        log_dir = Path("data/logs")
        log_dir.mkdir(parents=True, exist_ok=True)

        # Shared pre-chain for structlog events coming through stdlib
        shared_processors: list = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_ist_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]

        # Console handler — colorized in dev, JSON in prod
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer()
            if is_debug
            else structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                _add_ist_timestamp,
                structlog.processors.format_exc_info,
            ],
        )
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)

        # File handler — always JSON for CloudWatch parsing
        file_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                _add_ist_timestamp,
                structlog.processors.format_exc_info,
            ],
        )
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_dir / "vqms.log"),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)

        # Root logger gets both handlers — all logs go to both
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.DEBUG))

        # --- structlog: routes through stdlib via LoggerFactory ---
        # Application code uses structlog.get_logger() with kwargs.
        # LoggerFactory routes output through stdlib, which hits both
        # the console and file handlers configured above.
        structlog.configure(
            processors=[
                *shared_processors,
                # PrepareEvent formats the event for stdlib's ProcessorFormatter
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # Suppress noisy third-party loggers
        for noisy_logger in [
            "uvicorn",
            "uvicorn.access",
            "uvicorn.error",
            "httpx",
            "httpcore",
            "boto3",
            "botocore",
            "urllib3",
            "asyncio",
            "paramiko",
            "sshtunnel",
        ]:
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)

        LoggingSetup._configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Convenience function to get a structlog logger.

    Args:
        name: Logger name (typically __name__).

    Returns:
        A structlog BoundLogger instance.
    """
    return structlog.get_logger(name)
