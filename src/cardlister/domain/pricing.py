"""Comp aggregation: turn a set of comparable prices into a suggested price.

Pure and side-effect-free so the pricing logic is unit-testable on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from cardlister.domain.states import CompKind

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class CompData:
    """One comparable listing/sale, normalized from an eBay API response."""

    kind: CompKind
    title: str | None
    price: Decimal
    currency: str
    condition: str | None
    url: str | None


@dataclass(frozen=True)
class PriceSuggestion:
    suggested: Decimal
    method: str
    sample_size: int
    low: Decimal
    high: Decimal
    median: Decimal


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _median(sorted_values: Sequence[Decimal]) -> Decimal:
    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2


def summarize_prices(prices: Sequence[Decimal]) -> PriceSuggestion | None:
    """Suggest a price from comp prices.

    Uses a trimmed mean (dropping the extreme high/low) once there are enough
    samples to make trimming meaningful, otherwise the median. Returns ``None`` if
    there are no usable (positive) prices.
    """
    cleaned = sorted(p for p in prices if p > 0)
    if not cleaned:
        return None

    median = _median(cleaned)
    if len(cleaned) >= 5:
        trimmed = cleaned[1:-1]
        suggested = sum(trimmed, Decimal(0)) / len(trimmed)
        method = "trimmed_mean"
    else:
        suggested = median
        method = "median"

    return PriceSuggestion(
        suggested=_quantize(suggested),
        method=method,
        sample_size=len(cleaned),
        low=cleaned[0],
        high=cleaned[-1],
        median=_quantize(median),
    )
