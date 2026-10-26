"""阶段二手动运行入口。

用法：
    python run.py
    python run.py --date 2026-10-25
    python run.py --data data/mock/sales_mock.csv --date 2026-10-25
    python run.py --data data/raw/sales.xlsx --sheet 销售数据 --date 2026-10-25
    python run.py --top-n 5
    python run.py --no-ai
    python run.py --refresh-ai

读取 CSV、计算指标与异常，调用 RAG + GLM 生成建议，并生成 Markdown 报告。
没有 API Key 或模型失败时自动回退到规则型报告。
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
from ecom_ops.history.store import record_result
from ecom_ops.logging_setup import get_run_logger, setup_logging
from ecom_ops.utils.dates import APP_TZ
from ecom_ops.utils.files import resolve_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="电商运营 Agent - 阶段一手动运行")
    parser.add_argument("--date", default=None, help="统计日期，格式 YYYY-MM-DD；默认 D-1")
    parser.add_argument("--data", default=None, help="数据 CSV/Excel 路径；默认使用 settings.yaml")
    parser.add_argument("--sheet", default=None, help="Excel 工作表名称；默认第一个工作表")
    parser.add_argument(
        "--data-note",
        default=None,
        help="写入报告的数据来源说明，例如“销售字段为模拟数据”",
    )
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    parser.add_argument("--fields", default=None, help="fields.yaml 路径")
    parser.add_argument("--report-dir", default=None, help="报告输出目录")
    parser.add_argument("--log-dir", default=None, help="日志输出目录")
    parser.add_argument("--top-n", type=int, default=None, help="报告展示的异常数量")
    parser.add_argument("--no-ai", action="store_true", help="本次运行不调用大模型")
    parser.add_argument("--no-rag", action="store_true", help="本次运行不启用 RAG 检索")
    parser.add_argument("--refresh-ai", action="store_true", help="忽略 AI 结果缓存")
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
        llm = replace(settings.llm, enabled=False) if args.no_ai else settings.llm
        rag = replace(settings.rag, enabled=False) if args.no_rag else settings.rag
        settings = replace(settings, app=app, report=report, llm=llm, rag=rag)

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
            force_refresh_ai=args.refresh_ai,
            sheet_name=args.sheet,
            data_note=args.data_note,
        )

        if result.get("status") == "completed":
            try:
                record_result(
                    settings,
                    result,
                    source_file=str(settings.app.data_file),
                    data_note=args.data_note,
                )
            except Exception as exc:
                logger.warning("历史记录写入失败（不影响本次报告）: %s", exc)

        summary = result.get("global_summary", {}) or {}
        quality = (result.get("data_quality", {}) or {}).get("summary", {}) or {}
        ai_result = result.get("ai_result", {}) or {}
        retrieval = ai_result.get("retrieval", {}) or {}
        print()
        print("=" * 60)
        print("运营分析运行完成")
        print(f"run_id       : {run_id}")
        print(f"统计日期     : {result.get('stat_date', '—')}")
        print(f"参与商品数   : {summary.get('product_count', 0)}")
        print(f"异常商品数   : {len(result.get('anomalies', []) or [])}")
        print(f"有效/隔离行  : {quality.get('valid_rows', 0)} / {quality.get('invalid_rows', 0)}")
        print(f"AI 状态      : {ai_result.get('status', '—')}")
        print(f"RAG 检索块   : {retrieval.get('selected_count', 0)} / 索引 {retrieval.get('chunk_count', 0)}")
        print(f"报告路径     : {result.get('report_path', '—')}")
        if ai_result.get("status") == "failed":
            print(f"AI 错误      : {str(ai_result.get('error', ''))[:160]}")
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
