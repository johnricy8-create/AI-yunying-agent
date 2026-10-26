"""自适应基线。

对每个商品的浏览量、订单量分别计算：
- 取统计日之前最近 7 个自然日内的有效数据；
- 用变异系数 CV 判断近期波动，选择 3/5/7 日均值；
- 历史不足 3 天时使用可用天数，并标注低置信；
- 新品首日豁免，第 2 天起参与判定。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ecom_ops.config import BaselineConfig
from ecom_ops.utils.dates import parse_date


@dataclass(frozen=True)
class BaselineResult:
    metric: str
    mean: float | None
    window: int
    valid_days: int
    cv: float | None
    confidence: str  # normal / low / unavailable
    available: bool
    reason: str
    first_seen: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "mean": self.mean,
            "window": self.window,
            "valid_days": self.valid_days,
            "cv": self.cv,
            "confidence": self.confidence,
            "available": self.available,
            "reason": self.reason,
            "first_seen": self.first_seen,
        }


def _unavailable(metric: str, reason: str, first_seen: str | None) -> BaselineResult:
    return BaselineResult(
        metric=metric,
        mean=None,
        window=0,
        valid_days=0,
        cv=None,
        confidence="unavailable",
        available=False,
        reason=reason,
        first_seen=first_seen,
    )


def compute_baseline(
    history: pd.DataFrame,
    metric: str,
    target_date: date,
    config: BaselineConfig,
    first_seen: date,
) -> BaselineResult:
    """计算单个商品单个指标在 target_date 的基线。"""
    first_seen_iso = first_seen.isoformat()
    if (target_date - first_seen).days < config.new_product_exempt_days:
        return _unavailable(metric, "new_product_exempt", first_seen_iso)

    prior = history[history["stat_date"] < target_date.isoformat()].copy()
    if prior.empty:
        return _unavailable(metric, "no_history", first_seen_iso)

    lookback_start = target_date - timedelta(days=config.lookback_days)
    recent = prior[prior["stat_date"] >= lookback_start.isoformat()].copy()
    used_fallback = False
    if recent.empty:
        # 最近窗口完全缺数据时，退回最近的有效记录，但标记低置信。
        recent = prior.tail(config.lookback_days).copy()
        used_fallback = True

    values = pd.to_numeric(recent[metric], errors="coerce").dropna()
    values = values[values >= 0]
    if values.empty:
        return _unavailable(metric, "no_history", first_seen_iso)

    valid_days = int(len(values))
    mean_all = float(values.mean())
    if mean_all <= 0:
        return BaselineResult(
            metric=metric,
            mean=0.0,
            window=valid_days,
            valid_days=valid_days,
            cv=None,
            confidence="unavailable",
            available=False,
            reason="mean_zero",
            first_seen=first_seen_iso,
        )

    cv = float(values.std(ddof=0) / mean_all)

    windows = sorted(config.windows)
    if cv < config.cv_low:
        selected_window = windows[-1]
    elif cv < config.cv_high:
        selected_window = windows[len(windows) // 2]
    else:
        selected_window = windows[0]

    window = min(selected_window, valid_days)
    mean = float(values.tail(window).mean())

    confidence = "normal"
    reason = "ok"
    if valid_days < config.min_valid_days or used_fallback:
        confidence = "low"
        reason = "insufficient_history"
    elif window != selected_window:
        confidence = "low"
        reason = "window_shortened"

    return BaselineResult(
        metric=metric,
        mean=mean,
        window=int(window),
        valid_days=valid_days,
        cv=cv,
        confidence=confidence,
        available=True,
        reason=reason,
        first_seen=first_seen_iso,
    )


def compute_baselines(
    df: pd.DataFrame,
    target_date: date,
    config: BaselineConfig,
) -> dict[str, dict[str, BaselineResult]]:
    """为所有商品计算 pv / orders 基线。"""
    result: dict[str, dict[str, BaselineResult]] = {}
    if df.empty:
        return result

    for product_id, group in df.groupby("product_id", sort=False):
        group = group.sort_values("stat_date", kind="stable")
        first_seen = parse_date(group["stat_date"].min())
        result[str(product_id)] = {
            "pv": compute_baseline(group, "pv", target_date, config, first_seen),
            "orders": compute_baseline(group, "orders", target_date, config, first_seen),
        }
    return result


def baselines_to_dict(
    baselines: dict[str, dict[str, BaselineResult]]
) -> dict[str, dict[str, dict[str, Any]]]:
    """转换为可放入状态、报告与测试断言的普通字典。"""
    return {
        product_id: {metric: baseline.to_dict() for metric, baseline in metrics.items()}
        for product_id, metrics in baselines.items()
    }
