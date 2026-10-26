"""模拟销售数据生成。

阶段一固定 200 个商品 × 14 天，使用固定随机种子，保证可复现。
内置新品、昨日零浏览、缺日、重复行、逻辑冲突等边界样本，
用于验证规则和报告，而不是追求真实业务分布。
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ecom_ops.utils.dates import today as today_fn
from ecom_ops.utils.files import ensure_dir


CATEGORIES = ["Excel模板", "PPT模板", "办公资料", "电子资料", "简历模板"]
SHOPS = ["旗舰店", "办公小店", "模板工坊", "效率工具铺"]
PLATFORMS = ["淘宝", "拼多多", "抖音", "京东"]
NAME_PREFIXES = ["销售报表", "进销存", "项目计划", "年度总结", "简历套装", "合同范本", "财务测算", "运营看板"]

SPECIAL_PRODUCTS: dict[str, dict[str, object]] = {
    "P0001": {"name": "高浏览零订单-销售报表", "category": "Excel模板", "pv": 650, "cr": 0.030},
    "P0002": {"name": "高浏览低转化-项目计划", "category": "PPT模板", "pv": 420, "cr": 0.050},
    "P0003": {"name": "浏览量骤降-年度总结", "category": "PPT模板", "pv": 520, "cr": 0.035},
    "P0004": {"name": "订单骤降-简历套装", "category": "简历模板", "pv": 380, "cr": 0.045},
    "P0005": {"name": "新品首日-合同范本", "category": "办公资料", "pv": 260, "cr": 0.040},
    "P0006": {"name": "新品第二天-财务测算", "category": "Excel模板", "pv": 300, "cr": 0.040},
    "P0007": {"name": "昨日零浏览-运营看板", "category": "Excel模板", "pv": 340, "cr": 0.035},
    "P0008": {"name": "昨日缺数据-进销存", "category": "Excel模板", "pv": 360, "cr": 0.032},
    "P0009": {"name": "重复行样本-项目计划", "category": "PPT模板", "pv": 280, "cr": 0.030},
    "P0010": {"name": "负库存样本-办公资料", "category": "办公资料", "pv": 220, "cr": 0.030},
    "P0011": {"name": "订单大于浏览-电子资料", "category": "电子资料", "pv": 180, "cr": 0.030},
    "P0012": {"name": "退款大于销售-简历模板", "category": "简历模板", "pv": 240, "cr": 0.030},
    "P0013": {"name": "零库存样本-合同范本", "category": "办公资料", "pv": 320, "cr": 0.035},
    "P0014": {"name": "高库存样本-效率工具", "category": "电子资料", "pv": 150, "cr": 0.025},
    "P0015": {"name": "简介缺失样本-销售报表", "category": "Excel模板", "pv": 260, "cr": 0.032},
    "P0016": {"name": "未来日期样本-项目计划", "category": "PPT模板", "pv": 200, "cr": 0.030},
    "P0017": {"name": "商品名缺失样本-办公资料", "category": "办公资料", "pv": 210, "cr": 0.030},
}


def _make_description(name: str, category: str, rng: random.Random) -> str:
    features = [
        "可编辑源文件，含使用说明",
        "适配 Windows 与 Office，开箱即用",
        "含公式与示例数据，适合中小团队",
        "结构化模板，节省重复整理时间",
        "支持自定义配色与字段",
    ]
    return f"{name}｜{category}｜{rng.choice(features)}"


def _build_products(count: int, rng: random.Random) -> list[dict[str, object]]:
    if count < len(SPECIAL_PRODUCTS):
        raise ValueError(f"商品数量至少为 {len(SPECIAL_PRODUCTS)}，当前: {count}")

    products: list[dict[str, object]] = []
    for product_id, spec in SPECIAL_PRODUCTS.items():
        price = round(rng.uniform(19.9, 99.9), 2)
        products.append(
            {
                "product_id": product_id,
                "product_name": spec["name"],
                "category": spec["category"],
                "shop": rng.choice(SHOPS),
                "platform": rng.choice(PLATFORMS),
                "price": price,
                "cost": round(price * rng.uniform(0.2, 0.45), 2),
                "base_pv": spec["pv"],
                "base_cr": spec["cr"],
                "base_stock": rng.randint(20, 300),
            }
        )

    remaining = count - len(products)
    for index in range(remaining):
        product_id = f"P{100 + index:04d}"
        category = rng.choice(CATEGORIES)
        name = f"{rng.choice(NAME_PREFIXES)}-{category}-{index + 1:03d}"
        price = round(rng.uniform(9.9, 199.0), 2)
        products.append(
            {
                "product_id": product_id,
                "product_name": name,
                "category": category,
                "shop": rng.choice(SHOPS),
                "platform": rng.choice(PLATFORMS),
                "price": price,
                "cost": round(price * rng.uniform(0.2, 0.45), 2),
                "base_pv": rng.randint(60, 700),
                "base_cr": rng.uniform(0.008, 0.045),
                "base_stock": rng.randint(20, 600),
            }
        )
    return products


def generate_mock_data(
    products: int = 200,
    days: int = 14,
    seed: int = 42,
    end_date: date | None = None,
) -> pd.DataFrame:
    """生成模拟销售数据。

    end_date 默认为北京时间昨天，使默认统计日期 D-1 恰好是数据最后一天。
    """
    if days < 8:
        raise ValueError("至少需要 8 天数据，才能覆盖 7 日基线窗口")
    if products < len(SPECIAL_PRODUCTS):
        raise ValueError(f"商品数量至少为 {len(SPECIAL_PRODUCTS)}")

    rng = random.Random(seed)
    end = end_date or (today_fn() - timedelta(days=1))
    dates = [end - timedelta(days=days - 1 - i) for i in range(days)]
    target = dates[-1]
    previous = dates[-2]

    rows: list[dict[str, object]] = []
    product_specs = _build_products(products, rng)

    for product in product_specs:
        product_id = str(product["product_id"])
        price = float(product["price"])
        base_pv = int(product["base_pv"])
        base_cr = float(product["base_cr"])
        base_stock = int(product["base_stock"])
        cumulative_orders = 0

        for day in dates:
            # 新品首日只生成统计日；新品第二天只生成昨天与统计日。
            if product_id == "P0005" and day != target:
                continue
            if product_id == "P0006" and day not in {previous, target}:
                continue
            if product_id == "P0008" and day == previous:
                continue

            weekday_factor = 1.12 if day.weekday() >= 5 else 1.0
            noise = rng.uniform(0.78, 1.24)
            pv = max(0, int(round(base_pv * weekday_factor * noise)))

            expected_orders = pv * base_cr
            orders = max(0, int(round(rng.gauss(expected_orders, max(1.0, expected_orders * 0.25)))))
            orders = min(orders, pv)

            refund_rate = rng.uniform(0.0, 0.08)
            refund = round(price * orders * refund_rate, 2) if orders else 0.0
            sales = round(price * orders - refund, 2) if orders else 0.0
            if sales < 0:
                sales = 0.0

            stock = max(0, base_stock + rng.randint(-15, 15) - cumulative_orders)
            cumulative_orders += orders

            rows.append(
                {
                    "stat_date": day.isoformat(),
                    "product_id": product_id,
                    "product_name": str(product["product_name"]),
                    "product_desc": _make_description(
                        str(product["product_name"]), str(product["category"]), rng
                    ),
                    "shop": str(product["shop"]),
                    "platform": str(product["platform"]),
                    "category": str(product["category"]),
                    "price": price,
                    "cost": float(product["cost"]),
                    "stock": stock,
                    "pv": pv,
                    "orders": orders,
                    "sales_amount": sales,
                    "refund_amount": refund,
                }
            )

    def find(product_id: str, day: date) -> dict[str, object] | None:
        key = (product_id, day.isoformat())
        for row in rows:
            if (row["product_id"], row["stat_date"]) == key:
                return row
        return None

    # 1) 高浏览零订单
    row = find("P0001", target)
    if row:
        row.update(pv=650, orders=0, sales_amount=0.0, refund_amount=0.0)

    # 2) 高浏览低转化
    row = find("P0002", target)
    if row:
        row.update(
            pv=620,
            orders=2,
            sales_amount=round(float(row["price"]) * 2, 2),
            refund_amount=0.0,
        )

    # 3) 浏览量骤降：订单按同等比例收缩，避免出现“订单大于浏览量”的逻辑冲突
    row = find("P0003", target)
    if row:
        original_pv = float(row["pv"])
        row["pv"] = max(1, int(round(original_pv * 0.18)))
        row["orders"] = max(0, int(round(float(row["orders"]) * 0.18)))
        row["sales_amount"] = round(float(row["price"]) * int(row["orders"]), 2)
        row["refund_amount"] = 0.0

    # 4) 订单骤降
    row = find("P0004", target)
    if row:
        row.update(orders=0, sales_amount=0.0, refund_amount=0.0)

    # 6) 新品第二天：昨日高、今日低，触发低置信基线下的 PV 骤降
    for day, pv, orders in ((previous, 500, 20), (target, 100, 4)):
        row = find("P0006", day)
        if row:
            row.update(
                pv=pv,
                orders=orders,
                sales_amount=round(float(row["price"]) * orders, 2),
                refund_amount=0.0,
            )

    # 7) 昨日零浏览
    row = find("P0007", previous)
    if row:
        row.update(pv=0, orders=0, sales_amount=0.0, refund_amount=0.0)

    # 9) 重复行：追加一条统计日数据
    row = find("P0009", target)
    if row:
        rows.append(dict(row))

    # 10) 负库存
    row = find("P0010", target)
    if row:
        row["stock"] = -5

    # 11) 订单大于浏览
    row = find("P0011", target)
    if row:
        row.update(pv=10, orders=20, sales_amount=round(float(row["price"]) * 20, 2))

    # 12) 退款大于销售
    row = find("P0012", target)
    if row:
        row.update(sales_amount=10.0, refund_amount=20.0)

    # 13/14) 零库存与高库存
    row = find("P0013", target)
    if row:
        row["stock"] = 0
    row = find("P0014", target)
    if row:
        row["stock"] = 9999

    # 15) 简介缺失（警告，保留）
    row = find("P0015", target)
    if row:
        row["product_desc"] = ""

    # 16) 未来日期（错误，隔离）。使用固定远期日期，保证无论哪天运行都是未来数据。
    row = find("P0016", target)
    if row:
        future = dict(row)
        future["stat_date"] = date(2099, 1, 1).isoformat()
        rows.append(future)

    # 17) 商品名缺失（错误，隔离）
    row = find("P0017", target)
    if row:
        row["product_name"] = ""

    df = pd.DataFrame(rows)
    df = df.sort_values(["stat_date", "product_id"], kind="stable").reset_index(drop=True)
    expected_columns = [
        "stat_date",
        "product_id",
        "product_name",
        "product_desc",
        "shop",
        "platform",
        "category",
        "price",
        "cost",
        "stock",
        "pv",
        "orders",
        "sales_amount",
        "refund_amount",
    ]
    return df[expected_columns]


def write_mock_csv(df: pd.DataFrame, output: str | Path) -> Path:
    path = Path(output)
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
