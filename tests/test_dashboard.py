from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from ecom_ops.dashboard.builder import build_dashboard_data
from ecom_ops.dashboard.renderer import render_dashboard
from ecom_ops.history.store import record_result
from ecom_ops.utils.files import read_text


def _result() -> dict:
    metrics = pd.DataFrame(
        [
            {
                "product_id": "P1",
                "product_name": "测试商品A",
                "shop": "店铺A",
                "category": "Excel模板",
                "pv": 120.0,
                "uv": 100.0,
                "orders": 0.0,
                "sales_amount": 0.0,
                "cr_today": 0.0,
                "pv_change_rate": 0.1,
            }
        ]
    )
    return {
        "run_id": "dash-run",
        "stat_date": "2026-07-31",
        "source_path": "test.csv",
        "report_path": "reports/test.md",
        "status": "completed",
        "metrics": metrics,
        "anomalies": [
            {
                "product_id": "P1",
                "anomaly_types": ["零转化"],
                "severity_score": 100.0,
                "severity_level": "高危",
                "low_confidence": False,
                "pv_baseline": 100.0,
                "orders_baseline": 3.0,
            }
        ],
        "global_summary": {
            "product_count": 1,
            "total_pv": 120,
            "total_orders": 0,
            "total_sales": 0,
            "overall_cr": 0.0,
            "overall_pv_change_rate": 0.1,
        },
        "ai_result": {
            "status": "ok",
            "products": {
                "P1": {
                    "recommendations": [
                        {
                            "action": "检查详情页",
                            "rationale": "零转化",
                            "risk": "无",
                            "needs_human": True,
                        }
                    ]
                }
            },
        },
        "data_quality": {"summary": {"valid_rows": 1}},
        "data_note": "看板测试数据",
    }


def test_dashboard_build_and_render(settings, tmp_path):
    history_settings = replace(
        settings,
        history=replace(
            settings.history,
            enabled=True,
            db_path=tmp_path / "history.db",
            lookahead_days=3,
            recurring_min_count=2,
        ),
    )
    record_result(history_settings, _result())

    data = build_dashboard_data(
        history_settings,
        db_path=history_settings.history.db_path,
        days=7,
    )
    output = render_dashboard(data, tmp_path / "dashboard" / "index.html")
    content = read_text(output)

    assert "运营总览" in content
    assert "最新浏览量" in content
    assert "测试商品A" in content
    assert "建议后续观察" in content
    assert "看板测试数据" in content
    assert "http://" not in content
    assert "https://" not in content


def test_dashboard_empty_history(settings, tmp_path):
    history_settings = replace(
        settings,
        history=replace(
            settings.history,
            enabled=True,
            db_path=tmp_path / "empty.db",
        ),
    )
    data = build_dashboard_data(history_settings, db_path=history_settings.history.db_path)
    output = render_dashboard(data, tmp_path / "empty.html")
    content = read_text(output)
    assert "暂无历史数据" in content
