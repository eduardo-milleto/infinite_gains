from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")


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
