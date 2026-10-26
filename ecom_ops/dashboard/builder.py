"""看板数据组装。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ecom_ops.catalog.analyzer import analyze_catalog
from ecom_ops.config import Settings
from ecom_ops.history.query import (
    advice_effectiveness,
    latest_anomalies,
    latest_run,
    overview,
    recent_runs,
    recurring_products,
)
from ecom_ops.utils.dates import format_datetime


def build_dashboard_data(
    settings: Settings,
    db_path: str | Path | None = None,
    days: int = 14,
    catalog_path: str | Path | None = None,
    changes_path: str | Path | None = None,
) -> dict[str, Any]:
    db = Path(db_path) if db_path else settings.history.db_path
    info = overview(db)
    runs = recent_runs(db, limit=days)
    latest = latest_run(db)
    anomalies = (
        latest_anomalies(db, latest["stat_date"], limit=10) if latest else []
    )
    recurring = recurring_products(
        db,
        min_count=settings.history.recurring_min_count,
        limit=10,
    )
    advice = advice_effectiveness(
        db,
        lookahead_days=settings.history.lookahead_days,
        limit=30,
    )

    catalog: dict[str, Any] | None = None
    catalog_error: str | None = None
    if catalog_path and Path(catalog_path).exists():
        try:
            catalog = analyze_catalog(catalog_path, changes_path, top=10)
        except Exception as exc:
            catalog_error = str(exc)

    return {
        "generated_at": format_datetime(),
        "db_path": str(db),
        "days": days,
        "settings_lookahead": settings.history.lookahead_days,
        "overview": info,
        "runs": runs,
        "latest": latest,
        "anomalies": anomalies,
        "recurring": recurring,
        "advice": advice,
        "catalog": catalog,
        "catalog_error": catalog_error,
    }
