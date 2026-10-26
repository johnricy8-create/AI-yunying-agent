"""运营指标计算。

所有数值都由 Python/Pandas 计算，后续大模型只解释结果，不参与计算。
统计日期为字符串 YYYY-MM-DD，便于 CSV、报告与状态之间传递。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from ecom_ops.exceptions import AnalysisError


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = pd.Series(float("nan"), index=numerator.index, dtype="float64")
    mask = denominator > 0
    result.loc[mask] = numerator.loc[mask].astype(float) / denominator.loc[mask].astype(float)
    return result


def _traffic_series(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """转化率分母：优先 uv（>0），否则回退 pv。

    返回 (traffic, uses_uv)。
    """
    pv = pd.to_numeric(df["pv"], errors="coerce").fillna(0).astype(float)
    if "uv" in df.columns:
        uv = pd.to_numeric(df["uv"], errors="coerce")
    else:
        uv = pd.Series(float("nan"), index=df.index, dtype="float64")
    uses_uv = uv.notna() & (uv > 0)
    traffic = pv.copy()
    traffic.loc[uses_uv] = uv.loc[uses_uv]
    return traffic, uses_uv


def build_metrics(df: pd.DataFrame, stat_date: date) -> pd.DataFrame:
    """计算指定统计日的商品级指标，并带上昨日对比。"""
    target = stat_date.isoformat()
    yesterday = (stat_date - timedelta(days=1)).isoformat()

    today = df[df["stat_date"] == target].copy()
    if today.empty:
        raise AnalysisError(f"统计日期 {target} 没有可用数据")

    previous_columns = [
        column
        for column in ["product_id", "pv", "uv", "orders", "sales_amount", "refund_amount"]
        if column in df.columns
    ]
    previous = df[df["stat_date"] == yesterday][previous_columns].copy()
    previous = previous.rename(
        columns={
            "pv": "pv_yesterday",
            "uv": "uv_yesterday",
            "orders": "orders_yesterday",
            "sales_amount": "sales_yesterday",
            "refund_amount": "refund_yesterday",
        }
    )

    metrics = today.merge(previous, on="product_id", how="left", validate="one_to_one")

    traffic_today, uses_uv_today = _traffic_series(metrics)

    # 昨日分母单独构造，避免把今天的 pv 列改名后与 _traffic_series 冲突。
    pv_y = pd.to_numeric(metrics["pv_yesterday"], errors="coerce").fillna(0).astype(float)
    if "uv_yesterday" in metrics.columns:
        uv_y = pd.to_numeric(metrics["uv_yesterday"], errors="coerce")
    else:
        uv_y = pd.Series(float("nan"), index=metrics.index, dtype="float64")
    use_uv_y = uv_y.notna() & (uv_y > 0)
    traffic_yesterday = pv_y.copy()
    traffic_yesterday.loc[use_uv_y] = uv_y.loc[use_uv_y]
    uses_uv_yesterday = use_uv_y

    metrics["traffic_today"] = traffic_today
    metrics["traffic_yesterday"] = traffic_yesterday
    metrics["uses_uv"] = uses_uv_today
    metrics["uses_uv_yesterday"] = uses_uv_yesterday
    metrics["cr_today"] = _safe_ratio(metrics["orders"], traffic_today)
    metrics["cr_yesterday"] = _safe_ratio(metrics["orders_yesterday"], traffic_yesterday)

    pv_today = pd.to_numeric(metrics["pv"], errors="coerce").fillna(0).astype(float)
    pv_prev = pd.to_numeric(metrics["pv_yesterday"], errors="coerce")
    metrics["pv_change_rate"] = _safe_ratio(pv_today - pv_prev.fillna(0), pv_prev.fillna(0))
    # 昨日缺失或为 0 时不记录变化率，避免把“无对比”误写成 0%。
    metrics.loc[pv_prev.isna() | (pv_prev <= 0), "pv_change_rate"] = float("nan")

    metrics["has_yesterday"] = pv_prev.notna()
    metrics["conversion_denominator"] = "pv"
    metrics.loc[metrics["uses_uv"], "conversion_denominator"] = "uv"

    # 展示顺序：先异常候选商品，再按浏览量降序，便于阅读。
    metrics = metrics.sort_values(["pv", "orders", "product_id"], ascending=[False, False, True])
    return metrics.reset_index(drop=True)


def build_global_summary(metrics: pd.DataFrame, stat_date: date) -> dict[str, Any]:
    """生成全局指标摘要。"""
    total_pv = int(pd.to_numeric(metrics["pv"], errors="coerce").fillna(0).sum())
    total_orders = int(pd.to_numeric(metrics["orders"], errors="coerce").fillna(0).sum())
    total_sales = float(pd.to_numeric(metrics["sales_amount"], errors="coerce").fillna(0).sum())
    refund_series = (
        pd.to_numeric(metrics["refund_amount"], errors="coerce").fillna(0)
        if "refund_amount" in metrics.columns
        else pd.Series(0.0, index=metrics.index)
    )
    total_refund = float(refund_series.sum())
    total_traffic = float(pd.to_numeric(metrics["traffic_today"], errors="coerce").fillna(0).sum())
    overall_cr = total_orders / total_traffic if total_traffic > 0 else None

    pv_prev = pd.to_numeric(metrics["pv_yesterday"], errors="coerce")
    comparable = pv_prev.notna() & (pv_prev > 0)
    if comparable.any():
        pv_today_comparable = float(
            pd.to_numeric(metrics.loc[comparable, "pv"], errors="coerce").fillna(0).sum()
        )
        pv_yesterday_comparable = float(pv_prev.loc[comparable].sum())
        overall_pv_change = (
            (pv_today_comparable - pv_yesterday_comparable) / pv_yesterday_comparable
            if pv_yesterday_comparable > 0
            else None
        )
    else:
        pv_today_comparable = None
        pv_yesterday_comparable = None
        overall_pv_change = None

    zero_order_products = int((pd.to_numeric(metrics["orders"], errors="coerce").fillna(0) == 0).sum())
    uv_rows = int(metrics["uses_uv"].fillna(False).sum()) if "uses_uv" in metrics.columns else 0

    return {
        "stat_date": stat_date.isoformat(),
        "product_count": int(len(metrics)),
        "total_pv": total_pv,
        "total_orders": total_orders,
        "total_sales": round(total_sales, 2),
        "total_refund": round(total_refund, 2),
        "total_traffic": round(total_traffic, 2),
        "overall_cr": overall_cr,
        "overall_pv_change_rate": overall_pv_change,
        "pv_today_comparable": pv_today_comparable,
        "pv_yesterday_comparable": pv_yesterday_comparable,
        "zero_order_products": zero_order_products,
        "uv_used_rows": uv_rows,
        "conversion_mode": "uv" if uv_rows == len(metrics) and len(metrics) > 0 else "pv",
        "warning": (
            "部分商品使用 UV、部分回退 PV，整体转化率为混合口径，解读时需注意。"
            if 0 < uv_rows < len(metrics)
            else None
        ),
    }
