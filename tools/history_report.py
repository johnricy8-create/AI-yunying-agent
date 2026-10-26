"""生成运营历史复盘报告。

用法：
    .venv\\Scripts\\python.exe tools\\history_report.py
    .venv\\Scripts\\python.exe tools\\history_report.py --days 30 --limit 15
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.config import load_settings
from ecom_ops.history.query import build_history_analysis
from ecom_ops.history.renderer import render_history_report
from ecom_ops.exceptions import HistoryError


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="运营历史复盘报告")
    parser.add_argument("--db", default=None, help="历史库路径；默认使用 settings.yaml")
    parser.add_argument("--days", type=int, default=14, help="商品历史对比天数")
    parser.add_argument("--limit", type=int, default=10, help="重复异常商品数量")
    parser.add_argument(
        "--output",
        default="reports/history_review/ops_history_report.md",
        help="报告输出路径",
    )
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    parser.add_argument("--fields", default=None, help="fields.yaml 路径")
    args = parser.parse_args()

    try:
        settings = load_settings(args.config, args.fields)
        db_path = Path(args.db) if args.db else settings.history.db_path
        if not db_path.exists():
            print(
                f"历史库不存在: {db_path}\n请先运行 run.py 或 scheduler.py 生成日报。",
                file=sys.stderr,
            )
            return 1
        analysis = build_history_analysis(
            db_path,
            days=args.days,
            limit=args.limit,
            lookahead_days=settings.history.lookahead_days,
            recurring_min_count=settings.history.recurring_min_count,
        )
        report_path = render_history_report(analysis, args.output)
    except HistoryError as exc:
        print(f"生成历史报告失败: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"未预期错误: {exc}", file=sys.stderr)
        return 1

    overview = analysis["overview"]
    print(f"历史复盘报告已生成: {report_path}")
    print(
        f"历史天数: {overview['runs']}，商品: {overview['products']}，"
        f"异常: {overview['anomalies']}，建议: {overview['recommendations']}"
    )
    print(f"重复异常商品: {len(analysis['recurring'])}，建议追踪: {len(analysis['advice']['details'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
