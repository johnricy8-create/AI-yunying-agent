"""用 UCI Online Retail 公开数据构建参考样本。

源数据：UCI Machine Learning Repository, Online Retail
https://archive.ics.uci.edu/dataset/352/online+retail
原始文件：data/reference/raw/Online Retail.xlsx（不提交）

处理方式：
- 取指定 180 天窗口内销售额最高的 N 个商品；
- 按 商品 × 日期 聚合真实的正向订单/销售额/退款；
- 补齐完整日期面板（没有销售的日期补 0）；
- 对源数据没有的 PV/UV、成本、库存、店铺/平台/类目做确定性模拟，
  并在 data/reference/README.md 中明确标注为派生字段。

用法：
    .venv\\Scripts\\python.exe tools\\build_reference_sample.py
    .venv\\Scripts\\python.exe tools\\build_reference_sample.py --products 300 --days 180
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.utils.files import ensure_dir

CATEGORY_RULES = [
    ("CHRISTMAS", "节日装饰"),
    ("XMAS", "节日装饰"),
    ("BUNTING", "派对装饰"),
    ("PARTY", "派对装饰"),
    ("BALLOON", "派对装饰"),
    ("BAG", "包袋"),
    ("LUNCH", "包袋"),
    ("MUG", "餐厨"),
    ("CUP", "餐厨"),
    ("BOWL", "餐厨"),
    ("PLATE", "餐厨"),
    ("TEAPOT", "餐厨"),
    ("CAKE", "餐厨"),
    ("TIN", "餐厨"),
    ("LIGHT", "灯饰"),
    ("LAMP", "灯饰"),
    ("CANDLE", "灯饰"),
    ("HOLDER", "灯饰"),
    ("FRAME", "相框"),
    ("PHOTO", "相框"),
    ("TOY", "玩具"),
    ("GAME", "玩具"),
    ("PLAYHOUSE", "玩具"),
    ("CARD", "文具礼品"),
    ("WRAP", "文具礼品"),
    ("RIBBON", "文具礼品"),
    ("PAPER", "文具礼品"),
    ("DOORMAT", "家居"),
    ("HOT WATER", "家居"),
    ("BASKET", "家居"),
    ("ORNAMENT", "家居"),
    ("BOTTLE", "家居"),
    ("JAR", "家居"),
]


def _category(description: str) -> str:
    text = (description or "").upper()
    for keyword, category in CATEGORY_RULES:
        if keyword in text:
            return category
    return "家居礼品"


def _title(description: str) -> str:
    text = " ".join(str(description or "").split())
    return text.title()[:80] if text else "Unknown Product"


def build_reference(
    raw_path: Path,
    output_path: Path,
    products: int = 300,
    days: int = 180,
    end_date: str = "2011-11-27",
    seed: int = 42,
) -> pd.DataFrame:
    end = pd.Timestamp(end_date)
    start = end - pd.Timedelta(days=days - 1)

    raw = pd.read_excel(
        raw_path,
        engine="openpyxl",
        usecols=["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice"],
    )
    raw["StockCode"] = raw["StockCode"].astype(str).str.strip().str.upper()
    raw["Description"] = raw["Description"].fillna("Unknown Product").astype(str).str.strip()
    raw["InvoiceDate"] = pd.to_datetime(raw["InvoiceDate"], errors="coerce")
    raw = raw.dropna(subset=["InvoiceDate"])
    raw = raw[(raw["InvoiceDate"] >= start) & (raw["InvoiceDate"] <= end + pd.Timedelta(days=1))]
    raw = raw[(raw["UnitPrice"] > 0) & (raw["Quantity"] != 0)]
    raw["date"] = raw["InvoiceDate"].dt.normalize()

    # 只保留真实商品编码（5 位数字，可带一个字母），排除 POSTAGE/MANUAL 等非商品行。
    raw = raw[raw["StockCode"].str.match(r"^\d{5}[A-Z]?$", na=False)]
    if raw.empty:
        raise RuntimeError("筛选后没有数据，请检查日期范围与原始文件")

    positive = raw[raw["Quantity"] > 0].copy()
    positive["gross"] = positive["Quantity"] * positive["UnitPrice"]
    agg_pos = (
        positive.groupby(["StockCode", "date"])
        .agg(orders=("InvoiceNo", "nunique"), gross=("gross", "sum"), units=("Quantity", "sum"))
        .reset_index()
    )
    agg_pos["price"] = agg_pos["gross"] / agg_pos["units"].replace(0, pd.NA)

    negative = raw[raw["Quantity"] < 0].copy()
    negative["refund"] = -(negative["Quantity"] * negative["UnitPrice"])
    agg_neg = negative.groupby(["StockCode", "date"])["refund"].sum().reset_index()

    product_gross = agg_pos.groupby("StockCode")["gross"].sum().sort_values(ascending=False)
    top_ids = list(product_gross.head(products).index)
    if not top_ids:
        raise RuntimeError("没有可用商品")

    meta = (
        raw[raw["StockCode"].isin(top_ids)]
        .groupby("StockCode")["Description"]
        .agg(lambda values: values.mode().iloc[0] if not values.mode().empty else "Unknown Product")
        .to_dict()
    )
    product_price = (
        agg_pos[agg_pos["StockCode"].isin(top_ids)]
        .groupby("StockCode")
        .apply(lambda group: group["gross"].sum() / max(1, group["units"].sum()))
        .to_dict()
    )

    dates = pd.date_range(start=start, end=end, freq="D")
    rng = random.Random(seed)
    rows: list[dict] = []

    for product_id in top_ids:
        name = meta.get(product_id, "Unknown Product")
        description = str(name)
        price = float(product_price.get(product_id, 10.0) or 10.0)
        price = max(0.5, round(price, 2))
        cost = round(price * (0.55 + 0.15 * rng.random()), 2)
        category = _category(description)
        product_pos = agg_pos[agg_pos["StockCode"] == product_id].set_index("date")
        product_neg = agg_neg[agg_neg["StockCode"] == product_id].set_index("date")
        avg_orders = max(0.1, product_pos["orders"].mean() if not product_pos.empty else 0.1)
        base_cr = rng.uniform(0.015, 0.045)
        base_pv = max(60.0, avg_orders / max(0.001, base_cr * 0.8))
        base_stock = max(20, int(round(avg_orders * 30)))
        stock = base_stock

        for current in dates:
            pos_row = product_pos.loc[current] if current in product_pos.index else None
            neg_row = product_neg.loc[current] if current in product_neg.index else None
            orders = int(pos_row["orders"]) if pos_row is not None else 0
            gross = float(pos_row["gross"]) if pos_row is not None else 0.0
            refund_raw = float(neg_row["refund"]) if neg_row is not None else 0.0
            refund = min(refund_raw, gross)
            sales = round(max(0.0, gross - refund), 2)
            day_price = (
                float(pos_row["price"])
                if pos_row is not None and pd.notna(pos_row["price"])
                else price
            )

            month_factor = 1.3 if current.month in {11, 12} else (0.9 if current.month in {6, 7, 8} else 1.0)
            weekday_factor = 0.8 if current.weekday() >= 5 else 1.0
            noise = rng.uniform(0.7, 1.3)
            pv = max(int(round(orders * 1.1)), int(round(base_pv * month_factor * weekday_factor * noise)))
            uv = max(int(round(orders * 2)), int(round(pv * rng.uniform(0.72, 0.85))))
            uv = min(pv, max(uv, int(round(orders * 1.05)) + 1))
            if uv <= 0:
                uv = max(1, pv)

            stock = max(0, stock - orders)
            if stock < max(5, int(base_stock * 0.2)):
                stock = base_stock + rng.randint(0, max(1, base_stock // 3))

            rows.append(
                {
                    "stat_date": current.strftime("%Y-%m-%d"),
                    "product_id": product_id,
                    "product_name": _title(description),
                    "product_desc": description[:200],
                    "shop": "UCI Online Retail",
                    "platform": "UK Online Retail",
                    "category": category,
                    "price": round(day_price, 2),
                    "cost": cost,
                    "stock": int(stock),
                    "pv": int(pv),
                    "uv": int(uv),
                    "orders": int(orders),
                    "sales_amount": sales,
                    "refund_amount": round(refund, 2),
                }
            )

    result = pd.DataFrame(rows).sort_values(["stat_date", "product_id"]).reset_index(drop=True)
    ensure_dir(output_path.parent)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    manifest = {
        "source": "UCI Machine Learning Repository - Online Retail",
        "source_url": "https://archive.ics.uci.edu/dataset/352/online+retail",
        "window_start": start.strftime("%Y-%m-%d"),
        "window_end": end.strftime("%Y-%m-%d"),
        "products": len(top_ids),
        "days": len(dates),
        "rows": len(result),
        "seed": seed,
        "real_fields": ["stat_date", "product_id", "product_name", "product_desc", "orders", "sales_amount", "refund_amount"],
        "derived_fields": ["price (weighted avg)", "cost", "stock", "pv", "uv", "shop", "platform", "category"],
        "note": "PV/UV、成本、库存、店铺/平台/类目为参考样本派生字段，不是源数据真实值。",
    }
    (output_path.parent / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="构建 UCI Online Retail 参考样本")
    parser.add_argument(
        "--raw",
        default="data/reference/raw/Online Retail.xlsx",
        help="UCI 原始 xlsx 路径",
    )
    parser.add_argument(
        "--output",
        default="data/reference/online_retail_reference.csv",
        help="输出 CSV 路径",
    )
    parser.add_argument("--products", type=int, default=300, help="商品数，默认 300")
    parser.add_argument("--days", type=int, default=180, help="天数，默认 180")
    parser.add_argument("--end-date", default="2011-11-27", help="窗口结束日期")
    parser.add_argument("--seed", type=int, default=42, help="派生字段随机种子")
    args = parser.parse_args()

    try:
        result = build_reference(
            Path(args.raw),
            Path(args.output),
            products=args.products,
            days=args.days,
            end_date=args.end_date,
            seed=args.seed,
        )
    except Exception as exc:
        print(f"构建参考样本失败: {exc}", file=sys.stderr)
        return 1

    print(f"参考样本已生成: {args.output}")
    print(f"行数: {len(result):,}")
    print(f"商品数: {result['product_id'].nunique():,}")
    print(f"日期范围: {result['stat_date'].min()} ~ {result['stat_date'].max()}")
    print(f"总销售额: {result['sales_amount'].sum():,.2f}")
    print(f"总订单量: {result['orders'].sum():,}")
    print("注意: PV/UV、成本、库存、店铺/平台/类目为派生字段，详见 data/reference/README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
