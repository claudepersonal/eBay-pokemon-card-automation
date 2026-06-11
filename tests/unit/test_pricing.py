"""Comp aggregation: median vs trimmed mean, cleaning, and empty input."""

from __future__ import annotations

from decimal import Decimal

from cardlister.domain.pricing import summarize_prices


def _d(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


def test_returns_none_for_no_prices() -> None:
    assert summarize_prices([]) is None
    assert summarize_prices(_d("0", "0")) is None  # non-positive dropped


def test_small_sample_uses_median() -> None:
    result = summarize_prices(_d("10", "20", "30"))
    assert result is not None
    assert result.method == "median"
    assert result.median == Decimal("20.00")
    assert result.suggested == Decimal("20.00")
    assert result.low == Decimal("10")
    assert result.high == Decimal("30")
    assert result.sample_size == 3


def test_even_sample_median_averages_middle() -> None:
    result = summarize_prices(_d("10", "20", "30", "40"))
    assert result is not None
    assert result.median == Decimal("25.00")


def test_large_sample_uses_trimmed_mean() -> None:
    # 1 is an outlier low, 100 an outlier high; trimming removes both.
    result = summarize_prices(_d("1", "20", "22", "24", "100"))
    assert result is not None
    assert result.method == "trimmed_mean"
    assert result.suggested == Decimal("22.00")  # mean of 20, 22, 24
    assert result.low == Decimal("1")
    assert result.high == Decimal("100")


def test_suggested_is_rounded_to_cents() -> None:
    result = summarize_prices(_d("10", "11", "13", "14", "17"))
    assert result is not None
    assert result.suggested == Decimal("12.67")  # mean(11,13,14)=12.666...
