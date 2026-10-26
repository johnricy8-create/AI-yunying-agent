"""生成阶段一模拟销售数据。

用法示例：
    python tools/generate_mock_data.py
    python tools/generate_mock_data.py --products 200 --days 14 --seed 42
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# 允许直接执行 python tools/generate_mock_data.py，而不必先安装本项目。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.data.mock import generate_mock_data, write_mock_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="生成电商运营 Agent 模拟销售数据")
    parser.add_argument(
        "--output",
        default="data/mock/sales_mock.csv",
        help="输出 CSV 路径，默认 data/mock/sales_mock.csv",
    )
    parser.add_argument("--products", type=int, default=200, help="商品数量，默认 200")
    parser.add_argument("--days", type=int, default=14, help="天数，默认 14")
    parser.add_argument("--seed", type=int, default=42, help="随机种子，默认 42")
    parser.add_argument(
        "--end-date",
        default=None,
        help="数据最后一天，格式 YYYY-MM-DD；默认昨天（北京时间）",
    )
    args = parser.parse_args()

    end_date = None
    if args.end_date:
        end_date = date.fromisoformat(args.end_date)

    df = generate_mock_data(
        products=args.products,
        days=args.days,
        seed=args.seed,
        end_date=end_date,
    )
    output = write_mock_csv(df, args.output)
    print(f"已生成模拟数据: {output}")
    print(f"行数: {len(df)}，商品数: {df['product_id'].nunique()}，日期数: {df['stat_date'].nunique()}")
    print(f"日期范围: {df['stat_date'].min()} ~ {df['stat_date'].max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
