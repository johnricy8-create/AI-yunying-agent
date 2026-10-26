"""生成历史日报，作为 RAG 的可选语料。

不会调用大模型：历史报告只包含规则型分析，用于后续检索“相似历史案例”。
输出目录：reports/history/YYYY-MM-DD_daily_report.md

用法：
    .venv\\Scripts\\python.exe tools\\build_history.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.config import load_settings
from ecom_ops.context import RunContext
from ecom_ops.data.loader import load_sales_data
from ecom_ops.data.validator import validate_sales_data
from ecom_ops.graph.workflow import run_workflow
from ecom_ops.logging_setup import get_run_logger, setup_logging


def main() -> int:
    settings = load_settings()
    history_dir = settings.root / "reports" / "history"
    history_settings = replace(
        settings,
        app=replace(settings.app, report_dir=history_dir),
        llm=replace(settings.llm, enabled=False),
        rag=replace(settings.rag, enabled=False),
    )

    setup_logging(
        settings.app.log_dir,
        level=settings.logging.level,
        filename="history_build.log",
        retention_days=settings.logging.retention_days,
    )
    logger = get_run_logger("build-history")
    context = RunContext(settings=history_settings, logger=logger)

    raw = load_sales_data(settings.app.data_file, settings.fields)
    validation = validate_sales_data(raw, settings.fields)
    dates = sorted(str(item) for item in validation.valid_df["stat_date"].unique())
    if len(dates) < 5:
        print(f"可用日期不足，无法生成历史日报: {dates}")
        return 1

    # 至少保留 3 天基线；排除最新一天，避免把当前分析日写入历史语料。
    candidates = dates[3:-1]
    if not candidates:
        print("没有适合生成历史日报的日期。")
        return 1

    print(f"可用日期: {dates[0]} ~ {dates[-1]}")
    print(f"将生成 {len(candidates)} 份历史日报 -> {history_dir}")
    failures = 0
    for date_str in candidates:
        try:
            result = run_workflow(
                context,
                run_id=f"history-{date_str}",
                source_path=settings.app.data_file,
                stat_date=date_str,
            )
            print(f"  {date_str}: {result.get('report_path')}")
        except Exception as exc:
            failures += 1
            print(f"  {date_str}: 失败 - {exc}")
    print(f"完成：成功 {len(candidates) - failures}，失败 {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
