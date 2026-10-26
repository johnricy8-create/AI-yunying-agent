"""用 Shopify 商品目录生成模拟销售/流量面板。

真实字段：商品ID、商品名称、店铺、类目、单价、上架/可用状态（来自目录快照）。
模拟字段：日期、订单量、PV、UV、销售额、退款、成本、库存。

用途：让用户用现有目录数据看到完整日报效果；
**不能用于真实业务校准，也不能把模拟销售当成真实销售。**
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ecom_ops.exceptions import CatalogError

REQUIRED_CATALOG = ["store_domain", "product_id", "variant_id", "title", "price", "available"]


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def build_shopify_sales_demo(
    catalog: pd.DataFrame,
    days: int = 60,
    end_date: str = "2026-07-31",
    seed: int = 42,
) -> pd.DataFrame:
    if catalog.empty:
        raise CatalogError("目录为空，无法生成演示销售数据")
    missing = [name for name in REQUIRED_CATALOG if name not in catalog.columns]
    if missing:
        raise CatalogError(f"目录缺少字段: {', '.join(missing)}")
    if days < 8:
        raise ValueError("演示数据至少需要 8 天，以覆盖 7 日基线窗口")

    work = catalog.copy()
    work["price"] = pd.to_numeric(work["price"], errors="coerce")
    positive_prices = work.loc[work["price"] > 0, "price"]
    fallback_price = float(positive_prices.median()) if not positive_prices.empty else 10.0
    work["price"] = work["price"].where(work["price"] > 0, fallback_price)
    work["available_flag"] = work["available"].map(_bool)
    for column, default in (
        ("store_name", ""),
        ("product_type", ""),
        ("vendor", ""),
        ("tags", ""),
        ("niche", ""),
        ("variant_title", ""),
    ):
        if column not in work.columns:
            work[column] = default
        work[column] = work[column].map(_text)

    end = date.fromisoformat(end_date)
    dates = [end - timedelta(days=days - 1 - index) for index in range(days)]
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []

    for row_index, (_, product) in enumerate(work.iterrows()):
        price = round(float(product["price"]), 2)
        available = bool(product["available_flag"])
        store = _text(product["store_domain"]) or "unknown-store"
        title = _text(product["title"]) or "未命名商品"
        variant = _text(product["variant_title"]).replace("Default Title", "").strip()
        display_name = f"{title} / {variant}" if variant else title
        display_name = display_name[:120]
        category = _text(product["niche"]) or _text(product["product_type"]) or "未分类"
        tags = _text(product["tags"])
        vendor = _text(product["vendor"])
        desc_parts = [part for part in (category, vendor, tags) if part]
        description = " | ".join(desc_parts)[:200]

        popularity = float(rng.uniform(0.3, 6.0))
        price_factor = (30.0 / max(5.0, price)) ** 0.25
        base_orders = max(0.05, popularity * price_factor)
        if not available:
            base_orders *= 0.15
        base_cr = float(rng.uniform(0.015, 0.05))
        base_pv = max(40.0, base_orders / max(0.001, base_cr * 0.8))
        base_stock = max(8, int(round(base_orders * 22)))
        stock = base_stock if available else 0
        cost = round(price * (0.55 + 0.15 * float(rng.random())), 2)

        for day_index, current in enumerate(dates):
            weekday_factor = 0.85 if current.weekday() >= 5 else 1.0
            noise = float(rng.uniform(0.7, 1.3))
            orders = int(rng.poisson(max(0.01, base_orders * weekday_factor)))
            pv = max(orders + 1, int(round(base_pv * weekday_factor * noise)))

            # 构造可验证的边界样本：只影响最后一天，便于测试异常规则。
            is_last = day_index == len(dates) - 1
            if is_last:
                if row_index % 37 == 0:
                    orders = 0
                    pv = max(150, pv)
                elif row_index % 53 == 0:
                    pv = max(5, int(round(pv * 0.15)))
                    orders = min(orders, max(0, pv - 1))
                elif row_index % 71 == 0:
                    orders = 0
                elif row_index % 89 == 0:
                    pv = max(pv + 1, int(round(pv * 1.6)))
                    orders = max(1, int(round(orders * 0.3))) if orders else 1

            uv = max(orders + 1, int(round(pv * float(rng.uniform(0.72, 0.88)))))
            uv = min(pv, uv)
            if uv < orders + 1:
                uv = min(pv, orders + 1)

            refund_rate = float(rng.uniform(0.0, 0.06))
            refund = round(price * orders * refund_rate, 2)
            sales = round(price * orders - refund, 2)
            if sales < 0:
                sales = 0.0

            stock = max(0, stock - orders)
            if stock < max(3, int(base_stock * 0.2)):
                stock = base_stock + int(rng.integers(0, max(1, base_stock // 3)))
            if not available and stock > 0 and day_index == 0:
                stock = 0

            rows.append(
                {
                    "stat_date": current.isoformat(),
                    "product_id": _text(product["variant_id"]) or _text(product["product_id"]),
                    "product_name": display_name,
                    "product_desc": description,
                    "shop": store,
                    "platform": "Shopify",
                    "category": category,
                    "price": price,
                    "cost": cost,
                    "stock": int(stock),
                    "pv": int(pv),
                    "uv": int(uv),
                    "orders": int(orders),
                    "sales_amount": sales,
                    "refund_amount": refund,
                }
            )

    result = pd.DataFrame(rows)
    result = result.sort_values(["stat_date", "product_id"], kind="stable").reset_index(drop=True)
    return result
