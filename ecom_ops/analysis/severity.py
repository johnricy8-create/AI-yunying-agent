"""严重度评分。

规则基础分 × 幅度系数，幅度系数封顶 2.0；
多条规则累加后封顶 100。
分级：>= high 高危，>= medium 中危，其余低危。
"""

from __future__ import annotations

from ecom_ops.config import LevelsConfig


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def drop_factor(actual: float, baseline: float, threshold: float) -> float:
    """下降类规则：实际值越低于阈值，幅度系数越大。"""
    if baseline <= 0:
        return 1.0
    ratio = actual / baseline
    deviation = (threshold - ratio) / threshold
    return 1.0 + _clamp(deviation, 0.0, 1.0)


def zero_conversion_factor(pv: float, min_pv: float) -> float:
    """零转化：浏览量越大，问题越值得优先看。"""
    if min_pv <= 0:
        return 1.0
    extra = (pv - min_pv) / min_pv
    return 1.0 + _clamp(extra, 0.0, 1.0)


def high_pv_low_cr_factor(cr_today: float, cr_baseline: float, low_cr_ratio: float) -> float:
    """高浏览低转化：转化率相对基线低得越多，幅度系数越大。"""
    if cr_baseline <= 0:
        return 1.0
    ratio = cr_today / cr_baseline
    deviation = (low_cr_ratio - ratio) / low_cr_ratio
    return 1.0 + _clamp(deviation, 0.0, 1.0)


def rule_score(base: float, factor: float) -> float:
    return round(base * min(2.0, max(1.0, factor)), 2)


def total_score(scores: list[float]) -> float:
    return round(min(100.0, sum(scores)), 2)


def level_of(score: float, levels: LevelsConfig) -> str:
    if score >= levels.high:
        return "高危"
    if score >= levels.medium:
        return "中危"
    return "低危"
