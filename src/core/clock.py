from __future__ import annotations

from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")
INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([mhd])\s*$", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def et_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ET_TZ)
    else:
        value = value.astimezone(ET_TZ)
    return value.astimezone(timezone.utc)


def utc_floor_hour(value: datetime) -> datetime:
    utc_value = value.astimezone(timezone.utc)
    return utc_value.replace(minute=0, second=0, microsecond=0)


def interval_to_seconds(interval: str, *, default_seconds: int = 3600) -> int:
    match = INTERVAL_RE.match(interval)
    if not match:
        return default_seconds

    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 3600
    if unit == "d":
        return amount * 86400
    return default_seconds


def utc_floor_interval(value: datetime, *, interval: str) -> datetime:
    interval_seconds = max(60, interval_to_seconds(interval))
    utc_value = value.astimezone(timezone.utc)
    floored_unix = int(utc_value.timestamp()) // interval_seconds * interval_seconds
    return datetime.fromtimestamp(floored_unix, tz=timezone.utc)
