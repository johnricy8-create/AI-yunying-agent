from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ecom_ops.analysis.baseline import compute_baseline


TARGET = date(2026, 10, 25)


def _history(values: list[int], metric: str = "pv") -> pd.DataFrame:
    dates = [TARGET - timedelta(days=len(values) - index) for index in range(len(values))]
    return pd.DataFrame(
        {
            "stat_date": [item.isoformat() for item in dates],
            "product_id": "P1",
            metric: values,
            "orders": [1] * len(values),
        }
    )


def test_stable_history_uses_seven_day_window(settings):
    history = _history([100] * 7)
    result = compute_baseline(history, "pv", TARGET, settings.baseline, date(2026, 10, 18))
    assert result.available is True
    assert result.window == 7
    assert result.mean == 100
    assert result.confidence == "normal"


def test_high_volatility_uses_three_day_window(settings):
    history = _history([100, 300, 50, 400, 20, 350, 80])
    result = compute_baseline(history, "pv", TARGET, settings.baseline, date(2026, 10, 18))
    assert result.window == 3
    assert result.mean == 150
    assert result.confidence == "normal"


def test_moderate_volatility_uses_five_day_window(settings):
    history = _history([100, 110, 120, 130, 140, 150, 160])
    result = compute_baseline(history, "pv", TARGET, settings.baseline, date(2026, 10, 18))
    assert result.window == 5
    assert result.mean == 140
    assert result.confidence == "normal"


def test_insufficient_history_is_low_confidence(settings):
    history = _history([100, 120])
    result = compute_baseline(history, "pv", TARGET, settings.baseline, date(2026, 10, 23))
    assert result.available is True
    assert result.window == 2
    assert result.confidence == "low"
    assert result.reason == "insufficient_history"


def test_new_product_first_day_is_exempt(settings):
    history = pd.DataFrame(
        {
            "stat_date": [TARGET.isoformat()],
            "product_id": ["P1"],
            "pv": [260],
            "orders": [8],
        }
    )
    result = compute_baseline(history, "pv", TARGET, settings.baseline, TARGET)
    assert result.available is False
    assert result.reason == "new_product_exempt"


def test_new_product_second_day_uses_available_history(settings):
    history = _history([500])
    result = compute_baseline(history, "pv", TARGET, settings.baseline, date(2026, 10, 24))
    assert result.available is True
    assert result.window == 1
    assert result.mean == 500
    assert result.confidence == "low"


def test_zero_mean_baseline_is_unavailable(settings):
    history = _history([0, 0, 0])
    result = compute_baseline(history, "pv", TARGET, settings.baseline, date(2026, 10, 21))
    assert result.available is False
    assert result.reason == "mean_zero"


def test_no_history_is_unavailable(settings):
    history = pd.DataFrame(columns=["stat_date", "product_id", "pv", "orders"])
    result = compute_baseline(history, "pv", TARGET, settings.baseline, date(2026, 10, 18))
    assert result.available is False
    assert result.reason == "no_history"
