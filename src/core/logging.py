from __future__ import annotations

import re
from typing import Any

import structlog

ETH_KEY_PATTERN = re.compile(r"^0x[0-9a-fA-F]{64}$")
SENSITIVE_KEYS = ("key", "secret", "signature", "private")


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if any(marker in key.lower() for marker in SENSITIVE_KEYS):
                continue
            sanitized[key] = _scrub(item)
        return sanitized

    if isinstance(value, list):
        return [_scrub(item) for item in value]

    if isinstance(value, str) and ETH_KEY_PATTERN.match(value):
        return "[REDACTED_ETH_KEY]"

    return value


def redact_processor(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    return _scrub(event_dict)


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
