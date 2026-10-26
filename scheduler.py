"""阶段四定时任务入口。

默认每天北京时间 09:00 执行完整工作流。
可用 --run-now 立即执行一次，--time HH:MM 临时调整时间用于测试。

Windows 长期运行：用任务计划程序在登录/开机时启动本脚本，
本进程会常驻并按 APScheduler 的 cron 触发。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from ecom_ops.config import load_settings
from ecom_ops.logging_setup import setup_logging
from ecom_ops.scheduler.runner import build_scheduler, parse_hhmm, run_job
from ecom_ops.utils.files import resolve_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="电商运营 Agent 定时任务")
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    parser.add_argument("--fields", default=None, help="fields.yaml 路径")
    parser.add_argument("--data", default=None, help="数据 CSV/Excel 路径")
    parser.add_argument("--sheet", default=None, help="Excel 工作表")
    parser.add_argument("--date", default=None, help="统计日期 YYYY-MM-DD；默认 D-1")
    parser.add_argument("--time", default=None, help="临时调整执行时间，格式 HH:MM")
    parser.add_argument("--run-now", action="store_true", help="立即执行一次后退出")
    parser.add_argument("--no-ai", action="store_true", help="本次不调用大模型")
    parser.add_argument("--data-note", default=None, help="写入报告的数据来源说明")
    parser.add_argument("--log-dir", default=None, help="日志目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config, args.fields)
    except Exception as exc:
        print(f"配置加载失败: {exc}", file=sys.stderr)
        return 2

    if args.log_dir:
        settings = replace(
            settings,
            app=replace(
                settings.app,
                log_dir=resolve_path(args.log_dir, settings.root),
            ),
        )

    setup_logging(
        settings.app.log_dir,
        level=settings.logging.level,
        filename=settings.logging.filename,
        retention_days=settings.logging.retention_days,
    )

    data_path = (
        resolve_path(args.data, settings.root) if args.data else settings.app.data_file
    )
    try:
        hour, minute = (
            parse_hhmm(args.time)
            if args.time
            else (settings.scheduler.hour, settings.scheduler.minute)
        )
    except ValueError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 2

    def job() -> dict:
        return run_job(
            settings,
            data_path=data_path,
            stat_date=args.date,
            ai_enabled=not args.no_ai,
            data_note=args.data_note,
            sheet_name=args.sheet,
        )

    if args.run_now:
        result = job()
        print(f"执行状态: {result.get('status')}")
        print(f"报告路径: {result.get('report_path') or '—'}")
        if result.get("error"):
            print(f"错误: {result['error']}")
        return 0 if result.get("status") == "completed" else 1

    scheduler = build_scheduler(settings, job, hour=hour, minute=minute)
    print(
        f"定时任务已启动：每天 {hour:02d}:{minute:02d} "
        f"（{settings.app.timezone}），数据文件：{data_path}"
    )
    print("按 Ctrl+C 退出。Windows 长期运行请用任务计划程序启动本脚本。")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\n正在停止定时任务...")
        scheduler.shutdown(wait=False)
    except Exception as exc:
        print(f"定时任务异常退出: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
