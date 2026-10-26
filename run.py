"""阶段一手动运行入口。

用法：
    python run.py
    python run.py --date 2026-10-25
    python run.py --data data/mock/sales_mock.csv --date 2026-10-25
    python run.py --top-n 5

阶段一只读取模拟 CSV、生成 Markdown 报告，不调用任何大模型。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import replace
from datetime import date, datetime

from ecom_ops.config import load_settings
from ecom_ops.context import RunContext
from ecom_ops.exceptions import EcomOpsError
from ecom_ops.graph.workflow import run_workflow
from ecom_ops.logging_setup import get_run_logger, setup_logging
from ecom_ops.utils.dates import APP_TZ
from ecom_ops.utils.files import resolve_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="电商运营 Agent - 阶段一手动运行")
    parser.add_argument("--date", default=None, help="统计日期，格式 YYYY-MM-DD；默认 D-1")
    parser.add_argument("--data", default=None, help="数据 CSV 路径；默认使用 settings.yaml")
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    parser.add_argument("--fields", default=None, help="fields.yaml 路径")
    parser.add_argument("--report-dir", default=None, help="报告输出目录")
    parser.add_argument("--log-dir", default=None, help="日志输出目录")
    parser.add_argument("--top-n", type=int, default=None, help="报告展示的异常数量")
    return parser


def _parse_date_arg(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"--date 格式错误，应为 YYYY-MM-DD: {value!r}") from exc


def main(argv: list[str] | None = None) -> int:
    # 尽早切到 UTF-8，保证配置/参数错误在 Windows 控制台也能正常显示中文。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    logger = None
    try:
        settings = load_settings(args.config, args.fields)
        stat_date = _parse_date_arg(args.date)

        app = replace(
            settings.app,
            data_file=(
                resolve_path(args.data, settings.root)
                if args.data
                else settings.app.data_file
            ),
            report_dir=(
                resolve_path(args.report_dir, settings.root)
                if args.report_dir
                else settings.app.report_dir
            ),
            log_dir=(
                resolve_path(args.log_dir, settings.root)
                if args.log_dir
                else settings.app.log_dir
            ),
        )
        report = settings.report
        if args.top_n is not None:
            if args.top_n < 1:
                raise ValueError("--top-n 必须 >= 1")
            report = replace(report, top_n=args.top_n)
        settings = replace(settings, app=app, report=report)

        setup_logging(
            settings.app.log_dir,
            level=settings.logging.level,
            filename=settings.logging.filename,
            retention_days=settings.logging.retention_days,
        )
        run_id = (
            f"{stat_date or 'auto'}-"
            f"{datetime.now(APP_TZ).strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:6]}"
        )
        logger = get_run_logger(run_id)
        context = RunContext(settings=settings, logger=logger)

        result = run_workflow(
            context,
            run_id=run_id,
            source_path=settings.app.data_file,
            stat_date=stat_date,
        )

        summary = result.get("global_summary", {}) or {}
        quality = (result.get("data_quality", {}) or {}).get("summary", {}) or {}
        print()
        print("=" * 60)
        print("阶段一运行完成")
        print(f"run_id       : {run_id}")
        print(f"统计日期     : {result.get('stat_date', '—')}")
        print(f"参与商品数   : {summary.get('product_count', 0)}")
        print(f"异常商品数   : {len(result.get('anomalies', []) or [])}")
        print(f"有效/隔离行  : {quality.get('valid_rows', 0)} / {quality.get('invalid_rows', 0)}")
        print(f"报告路径     : {result.get('report_path', '—')}")
        print("=" * 60)
        return 0
    except EcomOpsError as exc:
        if logger:
            logger.error("任务失败: %s", exc)
        else:
            print(f"任务失败: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        if logger:
            logger.error("参数错误: %s", exc)
        else:
            print(f"参数错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if logger:
            logger.warning("用户中断任务")
        else:
            print("用户中断任务", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - 兜底
        if logger:
            logger.exception("未预期错误")
        else:
            print(f"未预期错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
