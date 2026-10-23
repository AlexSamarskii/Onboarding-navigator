"""
Structured logging setup for production-ready JSON logs.

Supports both JSON (production) and text (development) formats.
"""

import logging

logger = logging.getLogger(__name__)


def setup_structured_logging(
    log_format: str = "text", level: int = logging.INFO
) -> None:
    """
    Setup structured logging with JSON or text format.

    Args:
        log_format: Log format - "json" for production (ELK/Loki), "text" for development
        level: Logging level (logging.INFO, logging.WARNING, logging.ERROR)

    Example:
        >>> setup_structured_logging(log_format="json", level=logging.INFO)
        >>> logger.info("Test message", extra={"user_id": 123})
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setLevel(level)

    if log_format == "json":
        # JSON format for production (ELK/Loki integration)
        try:
            from pythonjsonlogger import jsonlogger

            formatter = jsonlogger.JsonFormatter(
                "%(timestamp)s %(level)s %(name)s %(message)s",
                rename_fields={"levelname": "level", "asctime": "timestamp"},
                static_fields={"service": "telegram-bot"},
            )
        except ImportError:
            # Fallback to text if python-json-logger not installed
            logger.warning(
                "python-json-logger not installed, falling back to text format"
            )
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
            )
    else:
        # Text format for development (human-readable)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    logger.info(
        f"✅ Structured logging initialized (format: {log_format}, level: {logging.getLevelName(level)})"
    )
