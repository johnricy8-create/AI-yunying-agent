"""异常识别与严重度排序。

阶段一核心规则（与文档一致）：
- 零转化；
- 浏览量骤降；
- 订单量骤降；
- 高浏览低转化。
库存规则默认关闭，仅保留配置入口。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ecom_ops.analysis.baseline import BaselineResult
from ecom_ops.analysis.severity import (
    drop_factor,
    high_pv_low_cr_factor,
    level_of,
    rule_score,
    total_score,
    zero_conversion_factor,
)
from ecom_ops.config import AnomalyConfig
from ecom_ops.utils.dates import parse_date


@dataclass(frozen=True)
class RuleHit:
    code: str
    label: str
    base_score: float
    factor: float
    score: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "base_score": self.base_score,
            "factor": round(self.factor, 3),
            "score": self.score,
            "detail": self.detail,
        }


@dataclass
class Anomaly:
    product_id: str
    product_name: str
    product_desc: str
    shop: str
    platform: str
    category: str
    pv_today: float
    pv_yesterday: float | None
    pv_baseline: float | None
    pv_change_rate: float | None
    pv_baseline_window: int
    pv_baseline_days: int
    pv_baseline_confidence: str
    orders_today: float
    orders_yesterday: float | None
    orders_baseline: float | None
    orders_baseline_window: int
    orders_baseline_days: int
    orders_baseline_confidence: str
    sales_today: float
    refund_today: float
    cr_today: float | None
    cr_baseline: float | None
    stock: float
    conversion_denominator: str
    hits: list[RuleHit]
    score: float
    level: str
    low_confidence: bool
    first_seen: str | None
    product_age_days: int
    is_first_day: bool

    @property
    def anomaly_types(self) -> list[str]:
        return [hit.label for hit in self.hits]

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "product_desc": self.product_desc,
            "shop": self.shop,
            "platform": self.platform,
            "category": self.category,
            "pv_today": self.pv_today,
            "pv_yesterday": self.pv_yesterday,
            "pv_baseline": self.pv_baseline,
            "pv_change_rate": self.pv_change_rate,
            "pv_baseline_window": self.pv_baseline_window,
            "pv_baseline_days": self.pv_baseline_days,
            "pv_baseline_confidence": self.pv_baseline_confidence,
            "orders_today": self.orders_today,
            "orders_yesterday": self.orders_yesterday,
            "orders_baseline": self.orders_baseline,
            "orders_baseline_window": self.orders_baseline_window,
            "orders_baseline_days": self.orders_baseline_days,
            "orders_baseline_confidence": self.orders_baseline_confidence,
            "sales_today": self.sales_today,
            "refund_today": self.refund_today,
            "cr_today": self.cr_today,
            "cr_baseline": self.cr_baseline,
            "stock": self.stock,
            "conversion_denominator": self.conversion_denominator,
            "anomaly_types": self.anomaly_types,
            "hits": [hit.to_dict() for hit in self.hits],
            "severity_score": self.score,
            "severity_level": self.level,
            "low_confidence": self.low_confidence,
            "first_seen": self.first_seen,
            "product_age_days": self.product_age_days,
            "is_first_day": self.is_first_day,
        }


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


def _confidence_label(value: str) -> str:
    return {"normal": "正常", "low": "低", "unavailable": "不可用"}.get(value, value)


def _baseline_or_unavailable(metric: str) -> BaselineResult:
    return BaselineResult(
        metric=metric,
        mean=None,
        window=0,
        valid_days=0,
        cv=None,
        confidence="unavailable",
        available=False,
        reason="no_history",
        first_seen=None,
    )


def _hit(
    code: str,
    label: str,
    base_score: float,
    factor: float,
    detail: str,
) -> RuleHit:
    return RuleHit(
        code=code,
        label=label,
        base_score=base_score,
        factor=factor,
        score=rule_score(base_score, factor),
        detail=detail,
    )


def detect_anomalies(
    metrics: pd.DataFrame,
    baselines: dict[str, dict[str, BaselineResult]],
    config: AnomalyConfig,
) -> list[Anomaly]:
    """识别异常商品并按严重度降序返回。"""
    if metrics.empty:
        return []

    anomalies: list[Anomaly] = []

    for _, row in metrics.iterrows():
        product_id = str(row["product_id"])
        product_baselines = baselines.get(product_id, {})
        pv_baseline = product_baselines.get("pv") or _baseline_or_unavailable("pv")
        orders_baseline = product_baselines.get("orders") or _baseline_or_unavailable("orders")

        # 新品首日完全豁免，不进入异常列表。
        if pv_baseline.reason == "new_product_exempt":
            continue

        pv_today = _number(row.get("pv")) or 0.0
        orders_today = _number(row.get("orders")) or 0.0
        cr_today = _number(row.get("cr_today"))
        pv_change_rate = _number(row.get("pv_change_rate"))
        sales_today = _number(row.get("sales_amount")) or 0.0
        refund_today = _number(row.get("refund_amount")) or 0.0
        stock = _number(row.get("stock")) or 0.0
        conversion_denominator = str(row.get("conversion_denominator", "pv"))

        pv_base_mean = pv_baseline.mean if pv_baseline.available else None
        orders_base_mean = orders_baseline.mean if orders_baseline.available else None
        cr_baseline = (
            orders_base_mean / pv_base_mean
            if pv_base_mean and pv_base_mean > 0 and orders_base_mean is not None
            else None
        )

        hits: list[RuleHit] = []

        # 1) 零转化
        if pv_today >= config.min_pv_for_zero_conversion and orders_today == 0:
            factor = zero_conversion_factor(pv_today, config.min_pv_for_zero_conversion)
            hits.append(
                _hit(
                    "zero_conversion",
                    "零转化",
                    config.severity.zero_conversion,
                    factor,
                    f"浏览量 {pv_today:.0f}，订单量 0",
                )
            )

        # 2) 浏览量骤降
        if (
            pv_base_mean is not None
            and pv_base_mean >= config.min_pv_for_ratio
            and pv_today <= config.pv_drop_ratio * pv_base_mean
        ):
            factor = drop_factor(pv_today, pv_base_mean, config.pv_drop_ratio)
            hits.append(
                _hit(
                    "pv_drop",
                    "浏览量骤降",
                    config.severity.pv_drop,
                    factor,
                    (
                        f"今日 {pv_today:.0f}，基线 {pv_base_mean:.1f}"
                        f"（{pv_baseline.window} 日均值，置信度 {_confidence_label(pv_baseline.confidence)}）"
                    ),
                )
            )

        # 3) 订单量骤降
        if (
            orders_base_mean is not None
            and orders_base_mean >= config.min_orders_for_drop
            and orders_today <= config.order_drop_ratio * orders_base_mean
        ):
            factor = drop_factor(orders_today, orders_base_mean, config.order_drop_ratio)
            hits.append(
                _hit(
                    "order_drop",
                    "订单量骤降",
                    config.severity.order_drop,
                    factor,
                    (
                        f"今日 {orders_today:.0f}，基线 {orders_base_mean:.1f}"
                        f"（{orders_baseline.window} 日均值，置信度 {_confidence_label(orders_baseline.confidence)}）"
                    ),
                )
            )

        # 4) 高浏览低转化
        if (
            pv_base_mean is not None
            and pv_base_mean > 0
            and cr_today is not None
            and cr_baseline is not None
            and cr_baseline > 0
            and pv_today >= config.high_pv_ratio * pv_base_mean
            and cr_today <= config.low_cr_ratio * cr_baseline
            and pv_today >= config.min_pv_for_high_pv
        ):
            factor = high_pv_low_cr_factor(cr_today, cr_baseline, config.low_cr_ratio)
            hits.append(
                _hit(
                    "high_pv_low_cr",
                    "高浏览低转化",
                    config.severity.high_pv_low_cr,
                    factor,
                    (
                        f"浏览量 {pv_today:.0f}（基线 {pv_base_mean:.1f}），"
                        f"转化率 {cr_today:.2%}（基线 {cr_baseline:.2%}）"
                    ),
                )
            )

        # 可选库存规则，默认关闭。
        if config.inventory.enabled:
            if stock <= 0 and pv_today >= config.min_pv_for_ratio:
                hits.append(
                    _hit(
                        "stock_out",
                        "断货风险",
                        40.0,
                        1.0,
                        f"库存 {stock:.0f}，今日浏览量 {pv_today:.0f}",
                    )
                )
            if (
                orders_base_mean is not None
                and orders_base_mean > 0
                and stock / orders_base_mean > config.inventory.overstock_days
            ):
                hits.append(
                    _hit(
                        "overstock",
                        "库存积压",
                        20.0,
                        1.0,
                        f"库存 {stock:.0f}，按基线订单可售 {stock / orders_base_mean:.1f} 天",
                    )
                )

        if not hits:
            continue

        score = total_score([hit.score for hit in hits])
        low_confidence = (
            pv_baseline.confidence == "low" or orders_baseline.confidence == "low"
        )
        first_seen_value = pv_baseline.first_seen or orders_baseline.first_seen
        product_age_days = 0
        if first_seen_value:
            try:
                product_age_days = max(
                    0,
                    (parse_date(str(row.get("stat_date"))) - parse_date(first_seen_value)).days
                    + 1,
                )
            except ValueError:
                product_age_days = 0
        is_first_day = product_age_days == 1

        anomalies.append(
            Anomaly(
                product_id=product_id,
                product_name=str(row.get("product_name", "")),
                product_desc=str(row.get("product_desc", "")),
                shop=str(row.get("shop", "")),
                platform=str(row.get("platform", "")),
                category=str(row.get("category", "")),
                pv_today=pv_today,
                pv_yesterday=_number(row.get("pv_yesterday")),
                pv_baseline=pv_base_mean,
                pv_change_rate=pv_change_rate,
                pv_baseline_window=pv_baseline.window,
                pv_baseline_days=pv_baseline.valid_days,
                pv_baseline_confidence=pv_baseline.confidence,
                orders_today=orders_today,
                orders_yesterday=_number(row.get("orders_yesterday")),
                orders_baseline=orders_base_mean,
                orders_baseline_window=orders_baseline.window,
                orders_baseline_days=orders_baseline.valid_days,
                orders_baseline_confidence=orders_baseline.confidence,
                sales_today=sales_today,
                refund_today=refund_today,
                cr_today=cr_today,
                cr_baseline=cr_baseline,
                stock=stock,
                conversion_denominator=conversion_denominator,
                hits=hits,
                score=score,
                level=level_of(score, config.levels),
                low_confidence=low_confidence,
                first_seen=first_seen_value,
                product_age_days=product_age_days,
                is_first_day=is_first_day,
            )
        )

    anomalies.sort(key=lambda item: (-item.score, -item.pv_today, item.product_id))
    return anomalies
