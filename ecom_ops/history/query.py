"""历史库查询与建议效果追踪。

所有“改善/恶化”都是后续观测到的指标变化，不代表因果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ecom_ops.history.store import connect


def overview(db_path: str | Path) -> dict[str, Any]:
    connection = connect(db_path)
    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS runs,
                   MIN(stat_date) AS first_date,
                   MAX(stat_date) AS last_date,
                   SUM(anomaly_count) AS anomalies,
                   SUM(product_count) AS product_rows
            FROM runs
            """
        ).fetchone()
        products = connection.execute(
            "SELECT COUNT(DISTINCT product_id) AS products FROM product_metrics"
        ).fetchone()
        recommendations = connection.execute(
            "SELECT COUNT(*) AS recs FROM recommendations"
        ).fetchone()
        ai_runs = connection.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE ai_status = 'ok'"
        ).fetchone()
        return {
            "runs": int(row["runs"] or 0),
            "first_date": row["first_date"] or "",
            "last_date": row["last_date"] or "",
            "anomalies": int(row["anomalies"] or 0),
            "products": int(products["products"] or 0),
            "recommendations": int(recommendations["recs"] or 0),
            "ai_runs": int(ai_runs["n"] or 0),
        }
    finally:
        connection.close()


def recurring_products(
    db_path: str | Path,
    min_count: int = 2,
    limit: int = 10,
) -> list[dict[str, Any]]:
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT product_id,
                   MAX(product_name) AS product_name,
                   MAX(shop) AS shop,
                   MAX(category) AS category,
                   COUNT(*) AS days,
                   MAX(stat_date) AS last_date,
                   GROUP_CONCAT(anomaly_types, '|') AS all_types,
                   MAX(severity_score) AS max_score
            FROM product_metrics
            WHERE anomaly_types != ''
            GROUP BY product_id
            HAVING days >= ?
            ORDER BY days DESC, max_score DESC
            LIMIT ?
            """,
            (min_count, limit),
        ).fetchall()
    finally:
        connection.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        type_counts: dict[str, int] = {}
        for chunk in str(row["all_types"] or "").replace("|", "、").split("、"):
            label = chunk.strip()
            if not label:
                continue
            type_counts[label] = type_counts.get(label, 0) + 1
        result.append(
            {
                "product_id": str(row["product_id"]),
                "product_name": str(row["product_name"] or ""),
                "shop": str(row["shop"] or ""),
                "category": str(row["category"] or ""),
                "days": int(row["days"]),
                "last_date": str(row["last_date"] or ""),
                "types": "、".join(sorted(type_counts, key=lambda key: type_counts[key], reverse=True)),
                "type_counts": type_counts,
                "max_score": float(row["max_score"] or 0),
            }
        )
    return result


def product_history(
    db_path: str | Path,
    product_id: str,
    days: int = 14,
) -> list[dict[str, Any]]:
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT stat_date, pv, uv, orders, sales_amount, cr, pv_change_rate,
                   anomaly_types, severity_level, low_confidence
            FROM product_metrics
            WHERE product_id = ?
            ORDER BY stat_date DESC
            LIMIT ?
            """,
            (str(product_id), days),
        ).fetchall()
    finally:
        connection.close()
    data = [dict(row) for row in rows]
    data.reverse()
    return data


def advice_effectiveness(
    db_path: str | Path,
    lookahead_days: int = 3,
    limit: int = 30,
) -> dict[str, Any]:
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT r.id, r.stat_date, r.product_id, r.source, r.action,
                   r.rationale, r.risk, r.needs_human,
                   m.product_name, m.pv AS base_pv, m.orders AS base_orders,
                   m.cr AS base_cr
            FROM recommendations r
            LEFT JOIN product_metrics m
              ON r.stat_date = m.stat_date AND r.product_id = m.product_id
            WHERE EXISTS (
                SELECT 1 FROM product_metrics f
                WHERE f.product_id = r.product_id AND f.stat_date > r.stat_date
            )
            ORDER BY r.stat_date DESC, r.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        details: list[dict[str, Any]] = []
        for row in rows:
            followups = connection.execute(
                """
                SELECT stat_date, pv, orders, cr
                FROM product_metrics
                WHERE product_id = ? AND stat_date > ?
                ORDER BY stat_date ASC
                LIMIT ?
                """,
                (str(row["product_id"]), str(row["stat_date"]), lookahead_days),
            ).fetchall()
            base_orders = row["base_orders"]
            base_cr = row["base_cr"]
            followup = followups[-1] if followups else None
            order_change = None
            cr_change = None
            if followup is not None and base_orders not in (None, 0):
                order_change = (float(followup["orders"] or 0) - float(base_orders)) / float(
                    base_orders
                )
            if followup is not None and base_cr not in (None, 0):
                cr_change = (float(followup["cr"] or 0) - float(base_cr)) / float(base_cr)

            if followup is None:
                classification = "无后续数据"
            else:
                signal = order_change if order_change is not None else cr_change
                if signal is None:
                    classification = "无后续数据"
                elif signal >= 0.10:
                    classification = "改善"
                elif signal <= -0.10:
                    classification = "恶化"
                else:
                    classification = "持平"

            details.append(
                {
                    "stat_date": str(row["stat_date"]),
                    "product_id": str(row["product_id"]),
                    "product_name": str(row["product_name"] or ""),
                    "source": str(row["source"]),
                    "action": str(row["action"]),
                    "rationale": str(row["rationale"] or ""),
                    "risk": str(row["risk"] or ""),
                    "needs_human": bool(row["needs_human"]),
                    "base_orders": base_orders,
                    "base_cr": base_cr,
                    "followup_date": str(followup["stat_date"]) if followup else "",
                    "followup_orders": followup["orders"] if followup else None,
                    "followup_cr": followup["cr"] if followup else None,
                    "order_change": order_change,
                    "cr_change": cr_change,
                    "classification": classification,
                }
            )
    finally:
        connection.close()

    summary: dict[str, int] = {}
    for item in details:
        key = item["classification"]
        summary[key] = summary.get(key, 0) + 1
    return {"details": details, "summary": summary}


def build_history_analysis(
    db_path: str | Path,
    days: int = 14,
    limit: int = 10,
    lookahead_days: int = 3,
    recurring_min_count: int = 2,
) -> dict[str, Any]:
    info = overview(db_path)
    recurring = recurring_products(db_path, recurring_min_count, limit)
    comparisons = [
        {"product": item, "history": product_history(db_path, item["product_id"], days)}
        for item in recurring
    ]
    advice = advice_effectiveness(db_path, lookahead_days, limit=30)
    return {
        "db_path": str(db_path),
        "overview": info,
        "recurring": recurring,
        "comparisons": comparisons,
        "advice": advice,
        "days": days,
        "limit": limit,
        "lookahead_days": lookahead_days,
        "recurring_min_count": recurring_min_count,
    }
