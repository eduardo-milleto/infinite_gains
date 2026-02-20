from __future__ import annotations

from decimal import Decimal


def bullish_crossover(k_prev: Decimal, d_prev: Decimal, k_curr: Decimal, d_curr: Decimal) -> bool:
    return k_prev <= d_prev and k_curr > d_curr


def bearish_crossover(k_prev: Decimal, d_prev: Decimal, k_curr: Decimal, d_curr: Decimal) -> bool:
    return k_prev >= d_prev and k_curr < d_curr
