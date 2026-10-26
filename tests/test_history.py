from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from ecom_ops.history.query import (
    advice_effectiveness,
    build_history_analysis,
    overview,
    product_history,
    recurring_products,
)
from ecom_ops.history.renderer import render_history_report
from ecom_ops.history.store import record_result
from ecom_ops.utils.files import read_text


def _result(
    stat_date: str,
    orders: float,
    cr: float,
    with_ai: bool = True,
) -> dict:
    metrics = pd.DataFrame(
        [
            {
                "product_id": "P1",
                "product_name": "测试商品A",
                "shop": "店铺A",
                "category": "Excel模板",
                "pv": 100.0,
                "uv": 80.0,
                "orders": orders,
                "sales_amount": orders * 10,
                "cr_today": cr,
                "pv_change_rate": 0.05,
            },
            {
                "product_id": "P2",
                "product_name": "测试商品B",
                "shop": "店铺B",
                "category": "PPT模板",
                "pv": 50.0,
                "uv": 40.0,
                "orders": 0.0,
                "sales_amount": 0.0,
                "cr_today": 0.0,
                "pv_change_rate": -0.2,
            },
        ]
    )
    anomalies = [
        {
            "product_id": "P1",
            "anomaly_types": ["订单量骤降"],
            "severity_score": 60.0,
            "severity_level": "中危",
            "low_confidence": False,
            "pv_baseline": 110.0,
            "orders_baseline": 4.0,
        },
        {
            "product_id": "P2",
            "anomaly_types": ["零转化"],
            "severity_score": 80.0,
            "severity_level": "高危",
            "low_confidence": False,
            "pv_baseline": 55.0,
            "orders_baseline": 1.0,
        },
    ]
    ai_result = {
        "status": "ok" if with_ai else "failed",
        "products": {
            "P1": {
                "recommendations": [
                    {
                        "action": "检查详情页与价格",
                        "rationale": "订单下降",
                        "risk": "无",
                        "needs_human": True,
                    }
                ]
            }
        },
    }
    return {
        "run_id": f"run-{stat_date}",
        "stat_date": stat_date,
        "source_path": "test.csv",
        "report_path": f"reports/{stat_date}.md",
        "status": "completed",
        "metrics": metrics,
        "anomalies": anomalies,
        "global_summary": {
            "product_count": 2,
            "total_pv": 150,
            "total_orders": orders,
            "total_sales": orders * 10,
            "overall_cr": cr,
            "overall_pv_change_rate": 0.0,
        },
        "ai_result": ai_result,
        "data_quality": {"summary": {"valid_rows": 2}},
        "data_note": "测试历史",
    }


def _history_settings(settings, tmp_path):
    return replace(
        settings,
        history=replace(
            settings.history,
            enabled=True,
            db_path=tmp_path / "history.db",
            lookahead_days=3,
            recurring_min_count=2,
        ),
    )


def test_history_record_query_and_report(settings, tmp_path):
    history_settings = _history_settings(settings, tmp_path)
    record_result(history_settings, _result("2026-07-30", orders=2, cr=0.02))
    record_result(history_settings, _result("2026-07-31", orders=4, cr=0.04))

    info = overview(history_settings.history.db_path)
    assert info["runs"] == 2
    assert info["first_date"] == "2026-07-30"
    assert info["last_date"] == "2026-07-31"
    assert info["products"] == 2

    recurring = recurring_products(history_settings.history.db_path, min_count=2)
    assert len(recurring) == 2
    recurring_ids = {item["product_id"] for item in recurring}
    assert "P1" in recurring_ids
    assert all(item["days"] == 2 for item in recurring)

    history = product_history(history_settings.history.db_path, "P1", days=14)
    assert [row["stat_date"] for row in history] == ["2026-07-30", "2026-07-31"]

    advice = advice_effectiveness(history_settings.history.db_path, lookahead_days=3)
    first_day = [item for item in advice["details"] if item["stat_date"] == "2026-07-30"]
    assert first_day
    p1_rows = [item for item in first_day if item["product_id"] == "P1"]
    assert p1_rows
    assert p1_rows[0]["classification"] == "改善"
    assert "无后续数据" in advice["summary"] or "改善" in advice["summary"]

    analysis = build_history_analysis(
        history_settings.history.db_path,
        days=14,
        limit=5,
        lookahead_days=3,
        recurring_min_count=2,
    )
    report_path = render_history_report(analysis, tmp_path / "history_report.md")
    content = read_text(report_path)
    assert "运营历史复盘报告" in content
    assert "重复异常商品" in content
    assert "商品历史对比" in content
    assert "建议追踪" in content
    assert "改善" in content
    assert "2026-07-30" in content


def test_history_rule_recommendations_when_ai_missing(settings, tmp_path):
    history_settings = _history_settings(settings, tmp_path)
    record_result(history_settings, _result("2026-07-30", orders=2, cr=0.02, with_ai=False))
    info = overview(history_settings.history.db_path)
    assert info["recommendations"] > 0
