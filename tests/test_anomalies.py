from __future__ import annotations

import pandas as pd

from ecom_ops.analysis.anomalies import detect_anomalies
from ecom_ops.analysis.baseline import BaselineResult


def _baseline(
    metric: str,
    mean: float | None,
    confidence: str = "normal",
    available: bool = True,
    reason: str = "ok",
    window: int = 7,
    days: int = 7,
) -> BaselineResult:
    return BaselineResult(
        metric=metric,
        mean=mean,
        window=window,
        valid_days=days,
        cv=0.1,
        confidence=confidence,
        available=available,
        reason=reason,
        first_seen="2026-10-01",
    )


def _metrics(**overrides) -> pd.DataFrame:
    row = {
        "product_id": "P1",
        "product_name": "测试商品",
        "product_desc": "测试简介",
        "shop": "测试店",
        "platform": "淘宝",
        "category": "Excel模板",
        "pv": 500,
        "orders": 10,
        "sales_amount": 100.0,
        "refund_amount": 0.0,
        "stock": 10,
        "pv_yesterday": 500,
        "orders_yesterday": 10,
        "pv_change_rate": 0.0,
        "cr_today": 10 / 500,
        "conversion_denominator": "pv",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _detect(metrics: pd.DataFrame, pv_baseline: BaselineResult, orders_baseline: BaselineResult, settings):
    return detect_anomalies(
        metrics,
        {"P1": {"pv": pv_baseline, "orders": orders_baseline}},
        settings.anomaly,
    )


def _codes(anomaly) -> set[str]:
    return {hit.code for hit in anomaly.hits}


def test_zero_conversion_triggers_and_scores_high(settings):
    metrics = _metrics(pv=500, orders=0, cr_today=0.0)
    anomalies = _detect(metrics, _baseline("pv", 500), _baseline("orders", 20), settings)
    assert len(anomalies) == 1
    assert "zero_conversion" in _codes(anomalies[0])
    assert anomalies[0].score == 100
    assert anomalies[0].level == "高危"


def test_pv_drop_boundary_at_seventy_percent(settings):
    baseline_pv = _baseline("pv", 100)
    baseline_orders = _baseline("orders", 10)

    at_threshold = _metrics(pv=70, orders=10, cr_today=10 / 70)
    hit = _detect(at_threshold, baseline_pv, baseline_orders, settings)
    assert hit and "pv_drop" in _codes(hit[0])

    just_above = _metrics(pv=71, orders=10, cr_today=10 / 71)
    assert _detect(just_above, baseline_pv, baseline_orders, settings) == []


def test_order_drop_requires_minimum_baseline_orders(settings):
    baseline_pv = _baseline("pv", 100)
    baseline_orders = _baseline("orders", 2.9)
    metrics = _metrics(pv=100, orders=2, cr_today=0.02)
    assert _detect(metrics, baseline_pv, baseline_orders, settings) == []


def test_high_pv_low_conversion_triggers(settings):
    metrics = _metrics(pv=130, orders=2, cr_today=2 / 130)
    anomalies = _detect(
        metrics,
        _baseline("pv", 100),
        _baseline("orders", 5),
        settings,
    )
    assert len(anomalies) == 1
    assert "high_pv_low_cr" in _codes(anomalies[0])


def test_new_product_first_day_is_fully_exempt(settings):
    metrics = _metrics(pv=500, orders=0, cr_today=0.0)
    anomalies = _detect(
        metrics,
        _baseline("pv", None, available=False, reason="new_product_exempt", window=0, days=0),
        _baseline("orders", None, available=False, reason="new_product_exempt", window=0, days=0),
        settings,
    )
    assert anomalies == []


def test_low_confidence_baseline_is_flagged(settings):
    metrics = _metrics(pv=70, orders=10, cr_today=10 / 70)
    anomalies = _detect(
        metrics,
        _baseline("pv", 100, confidence="low", days=1, window=1),
        _baseline("orders", 10, confidence="low", days=1, window=1),
        settings,
    )
    assert len(anomalies) == 1
    assert anomalies[0].low_confidence is True


def test_inventory_rules_are_disabled_by_default(settings):
    metrics = _metrics(pv=500, orders=10, cr_today=0.02, stock=0)
    anomalies = _detect(metrics, _baseline("pv", 500), _baseline("orders", 10), settings)
    assert anomalies == []


def test_zero_conversion_still_works_without_baseline(settings):
    metrics = _metrics(pv=500, orders=0, cr_today=0.0)
    anomalies = _detect(
        metrics,
        _baseline("pv", None, available=False, reason="no_history", window=0, days=0),
        _baseline("orders", None, available=False, reason="no_history", window=0, days=0),
        settings,
    )
    assert len(anomalies) == 1
    assert "zero_conversion" in _codes(anomalies[0])
    assert "pv_drop" not in _codes(anomalies[0])
