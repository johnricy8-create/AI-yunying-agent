from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from ecom_ops.analysis.metrics import build_global_summary, build_metrics
from ecom_ops.exceptions import AnalysisError


def _row(
    stat_date: str,
    product_id: str = "P1",
    pv: int = 100,
    orders: int = 5,
    sales: float = 50.0,
    refund: float = 0.0,
    uv: int | None = None,
) -> dict:
    return {
        "stat_date": stat_date,
        "product_id": product_id,
        "product_name": f"商品{product_id}",
        "product_desc": "测试商品",
        "shop": "测试店",
        "platform": "淘宝",
        "category": "Excel模板",
        "price": 10.0,
        "cost": 5.0,
        "stock": 100,
        "pv": pv,
        "uv": uv,
        "orders": orders,
        "sales_amount": sales,
        "refund_amount": refund,
    }


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "uv" not in df.columns:
        df["uv"] = None
    return df


def test_basic_metrics_and_change_rate():
    df = _frame(
        [
            _row("2026-10-24", pv=100, orders=5, sales=50),
            _row("2026-10-25", pv=120, orders=6, sales=60),
        ]
    )
    metrics = build_metrics(df, date(2026, 10, 25))
    assert len(metrics) == 1
    row = metrics.iloc[0]
    assert row["pv"] == 120
    assert row["pv_yesterday"] == 100
    assert row["orders_yesterday"] == 5
    assert row["cr_today"] == pytest.approx(6 / 120)
    assert row["cr_yesterday"] == pytest.approx(5 / 100)
    assert row["pv_change_rate"] == pytest.approx(0.2)
    assert bool(row["has_yesterday"]) is True
    assert row["conversion_denominator"] == "pv"


def test_missing_yesterday_leaves_change_rate_empty():
    df = _frame([_row("2026-10-25", pv=120, orders=6)])
    metrics = build_metrics(df, date(2026, 10, 25))
    row = metrics.iloc[0]
    assert pd.isna(row["pv_yesterday"])
    assert pd.isna(row["pv_change_rate"])
    assert bool(row["has_yesterday"]) is False


def test_zero_yesterday_pv_does_not_record_change_rate():
    df = _frame(
        [
            _row("2026-10-24", pv=0, orders=0, sales=0),
            _row("2026-10-25", pv=120, orders=6, sales=60),
        ]
    )
    metrics = build_metrics(df, date(2026, 10, 25))
    row = metrics.iloc[0]
    assert row["pv_yesterday"] == 0
    assert pd.isna(row["pv_change_rate"])
    assert bool(row["has_yesterday"]) is True


def test_uv_is_preferred_as_conversion_denominator():
    df = _frame(
        [
            _row("2026-10-24", pv=150, orders=5, uv=100),
            _row("2026-10-25", pv=120, orders=4, uv=80),
        ]
    )
    metrics = build_metrics(df, date(2026, 10, 25))
    row = metrics.iloc[0]
    assert row["conversion_denominator"] == "uv"
    assert row["traffic_today"] == 80
    assert row["cr_today"] == pytest.approx(4 / 80)
    assert row["cr_yesterday"] == pytest.approx(5 / 100)


def test_global_summary_uses_comparable_products_for_change_rate():
    df = _frame(
        [
            _row("2026-10-24", product_id="P1", pv=100, orders=5, sales=50),
            _row("2026-10-25", product_id="P1", pv=120, orders=6, sales=60),
            _row("2026-10-25", product_id="P2", pv=80, orders=4, sales=40),
        ]
    )
    metrics = build_metrics(df, date(2026, 10, 25))
    summary = build_global_summary(metrics, date(2026, 10, 25))
    assert summary["product_count"] == 2
    assert summary["total_pv"] == 200
    assert summary["total_orders"] == 10
    assert summary["total_sales"] == pytest.approx(100.0)
    assert summary["overall_cr"] == pytest.approx(10 / 200)
    assert summary["overall_pv_change_rate"] == pytest.approx(0.2)
    assert summary["zero_order_products"] == 0
    assert summary["conversion_mode"] == "pv"


def test_empty_target_date_raises():
    df = _frame([_row("2026-10-24")])
    with pytest.raises(AnalysisError):
        build_metrics(df, date(2026, 10, 25))
