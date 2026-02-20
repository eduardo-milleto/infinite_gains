from __future__ import annotations

from decimal import Decimal


def crossed_above(level: Decimal, prev: Decimal, curr: Decimal) -> bool:
    return prev <= level and curr > level


def crossed_below(level: Decimal, prev: Decimal, curr: Decimal) -> bool:
    return prev >= level and curr < level
