"""用 Shopify 商品目录生成模拟销售演示数据。

用法：
    .venv\\Scripts\\python.exe tools\\build_shopify_sales_demo.py ^
      --catalog "D:\\olist电商数据\\shopify-products-dataset-sample\\data\\catalog_sample_500.csv"

真实字段：商品ID、商品名称、店铺、类目、单价、可用状态。
模拟字段：日期、订单量、PV、UV、销售额、退款、成本、库存。
仅用于演示，不可用于真实业务校准。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.demo.shopify_sales import build_shopify_sales_demo
from ecom_ops.exceptions import CatalogError
from ecom_ops.utils.files import ensure_dir


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="用 Shopify 目录生成模拟销售演示数据")
    parser.add_argument("--catalog", required=True, help="catalog CSV 路径")
    parser.add_argument(
        "--output",
        default="data/derived/shopify_catalog_sales_demo.csv",
        help="输出 CSV 路径",
    )
    parser.add_argument("--days", type=int, default=60, help="天数，默认 60")
    parser.add_argument("--end-date", default="2026-07-31", help="结束日期，默认 2026-07-31")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    try:
        catalog = pd.read_csv(
            args.catalog,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
        result = build_shopify_sales_demo(
            catalog,
            days=args.days,
            end_date=args.end_date,
            seed=args.seed,
        )
    except (CatalogError, ValueError, OSError) as exc:
        print(f"生成演示数据失败: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output)
    ensure_dir(output.parent)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    manifest = {
        "source_catalog": str(Path(args.catalog)),
        "output": str(output),
        "rows": len(result),
        "products": int(result["product_id"].nunique()),
        "days": int(result["stat_date"].nunique()),
        "date_min": result["stat_date"].min(),
        "date_max": result["stat_date"].max(),
        "seed": args.seed,
        "real_fields": ["product_id", "product_name", "shop", "category", "price"],
        "synthetic_fields": ["stat_date", "orders", "pv", "uv", "sales_amount", "refund_amount", "cost", "stock"],
        "note": "订单、PV/UV、销售额、退款、成本、库存均为演示模拟值，不可用于真实业务校准。",
        "license_note": "商品目录来自 CC BY-NC 4.0 样本；商用前需确认完整数据集的商业许可。",
    }
    (output.parent / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"演示数据已生成: {output}")
    print(f"行数: {len(result):,}，商品: {result['product_id'].nunique():,}，天数: {result['stat_date'].nunique()}")
    print(f"日期范围: {result['stat_date'].min()} ~ {result['stat_date'].max()}")
    print("注意: 订单、PV/UV、销售额、退款、成本、库存为模拟值，不可用于真实业务校准。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
