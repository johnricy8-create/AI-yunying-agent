"""导出历史数据 Excel。

用法：
    .venv\\Scripts\\python.exe tools\\export_history_excel.py
    .venv\\Scripts\\python.exe tools\\export_history_excel.py --days 30 --output reports/exports/history.xlsx
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.config import load_settings
from ecom_ops.exceptions import HistoryError
from ecom_ops.history.excel import export_history_excel
from ecom_ops.utils.dates import now


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="导出历史运营数据 Excel")
    parser.add_argument("--db", default=None, help="历史库路径")
    parser.add_argument("--days", type=int, default=30, help="导出最近 N 天")
    parser.add_argument("--output", default=None, help="输出 xlsx 路径")
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    args = parser.parse_args()

    if args.days < 1:
        print("--days 必须 >= 1", file=sys.stderr)
        return 2

    try:
        settings = load_settings(args.config)
        if args.db:
            settings = replace(
                settings,
                history=replace(settings.history, db_path=Path(args.db)),
            )
        if not settings.history.db_path.exists():
            print(
                f"历史库不存在: {settings.history.db_path}\n"
                "请先运行 run.py 或 scheduler.py 生成日报。",
                file=sys.stderr,
            )
            return 1
        output = (
            Path(args.output)
            if args.output
            else Path("reports/exports")
            / f"ops_history_{now().strftime('%Y%m%d-%H%M%S')}.xlsx"
        )
        path = export_history_excel(settings, output, days=args.days)
    except (HistoryError, OSError) as exc:
        print(f"导出失败: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"未预期错误: {exc}", file=sys.stderr)
        return 1

    print(f"Excel 已导出: {path}")
    print(f"历史库: {settings.history.db_path}，导出天数: {args.days}")
    print("工作表: 说明 / 每日概览 / 商品指标 / 异常明细 / 建议清单 / 建议追踪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
