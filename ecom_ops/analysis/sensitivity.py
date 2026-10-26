"""阈值敏感度分析。

只用于工程评估：在固定数据上改变异常阈值，观察异常数量、异常率、
类型分布和高危数量。不修改线上配置，也不代表业务定案。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Iterable

import pandas as pd

from ecom_ops.analysis.anomalies import detect_anomalies
from ecom_ops.analysis.baseline import compute_baselines
from ecom_ops.analysis.metrics import build_metrics
from ecom_ops.config import AnomalyConfig, BaselineConfig
from ecom_ops.utils.dates import parse_date


@dataclass
class SensitivityRow:
    label: str
    parameter: str
    value: str
    days: int
    product_days: int
    total_anomalies: int
    avg_per_day: float
    anomaly_rate: float
    high_risk_avg: float
    type_counts: dict[str, int]
    unique_products: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "parameter": self.parameter,
            "value": self.value,
            "days": self.days,
            "product_days": self.product_days,
            "total_anomalies": self.total_anomalies,
            "avg_per_day": self.avg_per_day,
            "anomaly_rate": self.anomaly_rate,
            "high_risk_avg": self.high_risk_avg,
            "unique_products": self.unique_products,
            **{f"type_{key}": value for key, value in self.type_counts.items()},
        }


def select_dates(df: pd.DataFrame, days: int) -> list[date]:
    values = sorted(str(item) for item in df["stat_date"].dropna().unique())
    return [parse_date(item) for item in values[-days:]]


def prepare_frames(
    df: pd.DataFrame,
    dates: Iterable[date],
    baseline_config: BaselineConfig,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    metrics_by_date: dict[str, pd.DataFrame] = {}
    baselines_by_date: dict[str, dict] = {}
    for current in dates:
        key = current.isoformat()
        metrics = build_metrics(df, current)
        metrics_by_date[key] = metrics
        baselines_by_date[key] = compute_baselines(df, current, baseline_config)
    return metrics_by_date, baselines_by_date


def evaluate_config(
    metrics_by_date: dict[str, pd.DataFrame],
    baselines_by_date: dict[str, dict],
    config: AnomalyConfig,
    label: str,
    parameter: str = "baseline",
    value: str = "v0.1",
) -> SensitivityRow:
    total_anomalies = 0
    product_days = 0
    high_risk = 0
    type_counts: dict[str, int] = {}
    unique_products: set[str] = set()

    for key, metrics in metrics_by_date.items():
        anomalies = detect_anomalies(metrics, baselines_by_date[key], config)
        total_anomalies += len(anomalies)
        product_days += len(metrics)
        for anomaly in anomalies:
            unique_products.add(anomaly.product_id)
            if anomaly.level == "高危":
                high_risk += 1
            for label_text in anomaly.anomaly_types:
                type_counts[label_text] = type_counts.get(label_text, 0) + 1

    days = max(1, len(metrics_by_date))
    return SensitivityRow(
        label=label,
        parameter=parameter,
        value=value,
        days=len(metrics_by_date),
        product_days=product_days,
        total_anomalies=total_anomalies,
        avg_per_day=round(total_anomalies / days, 2),
        anomaly_rate=round(total_anomalies / product_days, 4) if product_days else 0.0,
        high_risk_avg=round(high_risk / days, 2),
        type_counts=dict(sorted(type_counts.items())),
        unique_products=len(unique_products),
    )


def run_ofat(
    base_config: AnomalyConfig,
    specs: dict[str, list[Any]],
    metrics_by_date: dict[str, pd.DataFrame],
    baselines_by_date: dict[str, dict],
) -> list[SensitivityRow]:
    rows = [
        evaluate_config(
            metrics_by_date,
            baselines_by_date,
            base_config,
            label="v0.1 基线",
            parameter="baseline",
            value="v0.1",
        )
    ]
    for parameter, values in specs.items():
        for value in values:
            config = replace(base_config, **{parameter: value})
            rows.append(
                evaluate_config(
                    metrics_by_date,
                    baselines_by_date,
                    config,
                    label=f"{parameter}={value}",
                    parameter=parameter,
                    value=str(value),
                )
            )
    return rows


def run_grid(
    base_config: AnomalyConfig,
    x_parameter: str,
    x_values: list[Any],
    y_parameter: str,
    y_values: list[Any],
    metrics_by_date: dict[str, pd.DataFrame],
    baselines_by_date: dict[str, dict],
) -> list[SensitivityRow]:
    rows: list[SensitivityRow] = []
    for x_value in x_values:
        for y_value in y_values:
            config = replace(
                base_config,
                **{x_parameter: x_value, y_parameter: y_value},
            )
            rows.append(
                evaluate_config(
                    metrics_by_date,
                    baselines_by_date,
                    config,
                    label=f"{x_parameter}={x_value}, {y_parameter}={y_value}",
                    parameter=f"{x_parameter} × {y_parameter}",
                    value=f"{x_value} / {y_value}",
                )
            )
    return rows


def run_profiles(
    base_config: AnomalyConfig,
    profiles: dict[str, dict[str, Any]],
    metrics_by_date: dict[str, pd.DataFrame],
    baselines_by_date: dict[str, dict],
) -> list[SensitivityRow]:
    rows: list[SensitivityRow] = []
    for name, overrides in profiles.items():
        config = replace(base_config, **overrides) if overrides else base_config
        rows.append(
            evaluate_config(
                metrics_by_date,
                baselines_by_date,
                config,
                label=name,
                parameter="profile",
                value=name,
            )
        )
    return rows
