"""SQLite 历史库。

每个统计日期保留一份最新快照；同日重跑会覆盖该日记录。
历史库只保存分析结果，不保存客户个人信息。
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from ecom_ops.analysis.rule_advice import directions_for_types
from ecom_ops.config import Settings
from ecom_ops.exceptions import HistoryError
from ecom_ops.utils.dates import now
from ecom_ops.utils.files import ensure_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    stat_date TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_file TEXT,
    report_path TEXT,
    status TEXT,
    product_count INTEGER,
    anomaly_count INTEGER,
    total_pv REAL,
    total_orders REAL,
    total_sales REAL,
    overall_cr REAL,
    overall_pv_change_rate REAL,
    ai_status TEXT,
    data_note TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS product_metrics (
    stat_date TEXT NOT NULL,
    product_id TEXT NOT NULL,
    product_name TEXT,
    shop TEXT,
    category TEXT,
    pv REAL,
    uv REAL,
    orders REAL,
    sales_amount REAL,
    cr REAL,
    pv_change_rate REAL,
    pv_baseline REAL,
    orders_baseline REAL,
    anomaly_types TEXT,
    severity_score REAL,
    severity_level TEXT,
    low_confidence INTEGER,
    PRIMARY KEY (stat_date, product_id)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stat_date TEXT NOT NULL,
    product_id TEXT NOT NULL,
    source TEXT NOT NULL,
    action TEXT NOT NULL,
    rationale TEXT,
    risk TEXT,
    needs_human INTEGER,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_metrics_product
    ON product_metrics (product_id, stat_date);
CREATE INDEX IF NOT EXISTS idx_recs_product
    ON recommendations (product_id, stat_date);
CREATE INDEX IF NOT EXISTS idx_recs_date
    ON recommendations (stat_date);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    ensure_dir(path.parent)
    try:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        return connection
    except sqlite3.Error as exc:
        raise HistoryError(f"历史库打开失败: {path}\n{exc}") from exc


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _int(value: Any) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def record_result(
    settings: Settings,
    result: dict[str, Any],
    source_file: str | None = None,
    data_note: str | None = None,
) -> int:
    """把一次工作流结果写入历史库；同日覆盖。"""
    if not settings.history.enabled:
        return 0

    stat_date = _text(result.get("stat_date"))
    metrics = result.get("metrics")
    if not stat_date:
        raise HistoryError("历史写入缺少统计日期")
    if not isinstance(metrics, pd.DataFrame) or metrics.empty:
        raise HistoryError("历史写入缺少商品指标")

    summary = result.get("global_summary", {}) or {}
    anomalies = result.get("anomalies", []) or []
    anomaly_by_product = {
        str(item.get("product_id")): item for item in anomalies if item.get("product_id")
    }
    ai_result = result.get("ai_result", {}) or {}
    ai_products = ai_result.get("products", {}) or {}
    data_quality = result.get("data_quality", {}) or {}
    quality_summary = data_quality.get("summary", {}) or {}
    created_at = now().isoformat(timespec="seconds")
    source = source_file or _text(result.get("source_path")) or _text(
        settings.app.data_file
    )
    note = data_note if data_note is not None else _text(result.get("data_note"))

    connection = connect(settings.history.db_path)
    try:
        with connection:
            connection.execute("DELETE FROM recommendations WHERE stat_date = ?", (stat_date,))
            connection.execute("DELETE FROM product_metrics WHERE stat_date = ?", (stat_date,))
            connection.execute("DELETE FROM runs WHERE stat_date = ?", (stat_date,))
            connection.execute(
                """
                INSERT INTO runs (
                    stat_date, run_id, source_file, report_path, status,
                    product_count, anomaly_count, total_pv, total_orders,
                    total_sales, overall_cr, overall_pv_change_rate, ai_status,
                    data_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stat_date,
                    _text(result.get("run_id")),
                    source,
                    _text(result.get("report_path")),
                    _text(result.get("status")),
                    int(summary.get("product_count", len(metrics)) or len(metrics)),
                    len(anomalies),
                    _number(summary.get("total_pv")),
                    _number(summary.get("total_orders")),
                    _number(summary.get("total_sales")),
                    _number(summary.get("overall_cr")),
                    _number(summary.get("overall_pv_change_rate")),
                    _text(ai_result.get("status")),
                    note,
                    created_at,
                ),
            )

            metric_rows = []
            for row in metrics.to_dict("records"):
                product_id = _text(row.get("product_id"))
                anomaly = anomaly_by_product.get(product_id, {})
                types = anomaly.get("anomaly_types", []) or []
                metric_rows.append(
                    (
                        stat_date,
                        product_id,
                        _text(row.get("product_name")),
                        _text(row.get("shop")),
                        _text(row.get("category")),
                        _number(row.get("pv")),
                        _number(row.get("uv")),
                        _number(row.get("orders")),
                        _number(row.get("sales_amount")),
                        _number(row.get("cr_today")),
                        _number(row.get("pv_change_rate")),
                        _number(anomaly.get("pv_baseline")),
                        _number(anomaly.get("orders_baseline")),
                        "、".join(str(item) for item in types),
                        _number(anomaly.get("severity_score")),
                        _text(anomaly.get("severity_level")),
                        1 if anomaly.get("low_confidence") else 0,
                    )
                )
            connection.executemany(
                """
                INSERT INTO product_metrics (
                    stat_date, product_id, product_name, shop, category,
                    pv, uv, orders, sales_amount, cr, pv_change_rate,
                    pv_baseline, orders_baseline, anomaly_types,
                    severity_score, severity_level, low_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                metric_rows,
            )

            recommendation_rows = []
            for anomaly in anomalies:
                product_id = _text(anomaly.get("product_id"))
                ai_product = ai_products.get(product_id, {}) or {}
                ai_recommendations = ai_product.get("recommendations", []) or []
                if ai_recommendations:
                    for item in ai_recommendations:
                        action = _text(item.get("action"))
                        if not action:
                            continue
                        recommendation_rows.append(
                            (
                                stat_date,
                                product_id,
                                "ai",
                                action,
                                _text(item.get("rationale")),
                                _text(item.get("risk")),
                                1 if item.get("needs_human", True) else 0,
                                created_at,
                            )
                        )
                else:
                    for direction in directions_for_types(
                        list(anomaly.get("anomaly_types", []) or [])
                    )[:3]:
                        recommendation_rows.append(
                            (
                                stat_date,
                                product_id,
                                "rule",
                                direction,
                                "规则型核查方向",
                                "需人工判断",
                                1,
                                created_at,
                            )
                        )
            if recommendation_rows:
                connection.executemany(
                    """
                    INSERT INTO recommendations (
                        stat_date, product_id, source, action, rationale,
                        risk, needs_human, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    recommendation_rows,
                )
        return len(metric_rows)
    except sqlite3.Error as exc:
        raise HistoryError(f"历史记录写入失败: {exc}") from exc
    finally:
        connection.close()
