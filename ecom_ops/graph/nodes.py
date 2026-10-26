"""LangGraph 节点实现。

节点顺序：load_data → analyze_data → ai_recommend → generate_report。
阶段一 ai_recommend 是显式占位节点，不调用任何模型，也不伪造结论。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ecom_ops.analysis.anomalies import detect_anomalies
from ecom_ops.analysis.baseline import baselines_to_dict, compute_baselines
from ecom_ops.analysis.metrics import build_global_summary, build_metrics
from ecom_ops.context import RunContext
from ecom_ops.data.loader import load_sales_data
from ecom_ops.data.validator import validate_sales_data
from ecom_ops.exceptions import (
    AnalysisError,
    DataLoadError,
    DataValidationError,
    EcomOpsError,
    WorkflowError,
)
from ecom_ops.graph.state import AgentState
from ecom_ops.report.renderer import render_report
from ecom_ops.utils.dates import default_stat_date, parse_date, today as today_fn


def load_data_node(state: AgentState, context: RunContext) -> dict[str, Any]:
    context.logger.info("[load_data] 开始读取数据: %s", state.get("source_path"))
    try:
        source_path = Path(str(state.get("source_path", "")))
        raw = load_sales_data(source_path, context.settings.fields)
        validation = validate_sales_data(
            raw,
            context.settings.fields,
            current_date=today_fn(),
        )

        if validation.valid_df.empty:
            raise DataValidationError(
                "数据校验后没有可用行，任务终止。"
                f"总行数 {validation.summary.get('total_rows')}，"
                f"无效行 {validation.summary.get('invalid_rows')}。"
            )

        available_dates = sorted(
            str(value) for value in validation.valid_df["stat_date"].dropna().unique()
        )
        requested = str(state.get("stat_date", "") or "").strip()
        if requested:
            if requested not in available_dates:
                raise DataLoadError(
                    f"统计日期 {requested} 没有可用数据；"
                    f"可用范围: {available_dates[0]} ~ {available_dates[-1]}"
                )
            resolved = requested
        else:
            default_date = default_stat_date(today_fn()).isoformat()
            if default_date in available_dates:
                resolved = default_date
            else:
                resolved = available_dates[-1]
                context.logger.warning(
                    "[load_data] 默认统计日期 %s 不在数据中，回退到最新可用日期 %s",
                    default_date,
                    resolved,
                )

        issues = [issue.to_dict() for issue in validation.issues]
        invalid_sample = validation.invalid_df.head(10).to_dict("records") if not validation.invalid_df.empty else []
        data_quality = {
            "summary": validation.summary,
            "issues": issues[:200],
            "issues_truncated": len(issues) > 200,
            "invalid_sample": invalid_sample,
            "available_dates": available_dates,
            "source_file": str(source_path),
        }

        context.logger.info(
            "[load_data] 完成：总行数 %d，有效 %d，无效 %d，统计日期 %s",
            validation.summary.get("total_rows", 0),
            validation.summary.get("valid_rows", 0),
            validation.summary.get("invalid_rows", 0),
            resolved,
        )
        return {
            "data": validation.valid_df,
            "data_quality": data_quality,
            "stat_date": resolved,
            "status": "data_loaded",
        }
    except EcomOpsError as exc:
        context.logger.error("[load_data] 失败: %s", exc)
        raise
    except Exception:
        context.logger.exception("[load_data] 未预期错误")
        raise


def analyze_data_node(state: AgentState, context: RunContext) -> dict[str, Any]:
    context.logger.info("[analyze_data] 开始计算指标、基线与异常")
    try:
        data = state.get("data")
        if data is None or data.empty:
            raise WorkflowError("analyze_data 没有收到可用数据")
        stat_date = parse_date(state.get("stat_date"))
        metrics = build_metrics(data, stat_date)
        if metrics.empty:
            raise AnalysisError(f"统计日期 {stat_date.isoformat()} 没有可分析商品")

        baselines = compute_baselines(data, stat_date, context.settings.baseline)
        anomalies = detect_anomalies(metrics, baselines, context.settings.anomaly)
        global_summary = build_global_summary(metrics, stat_date)

        context.logger.info(
            "[analyze_data] 完成：商品 %d，异常 %d，全局浏览量 %d，订单 %d",
            len(metrics),
            len(anomalies),
            global_summary.get("total_pv", 0),
            global_summary.get("total_orders", 0),
        )
        return {
            "metrics": metrics,
            "baselines": baselines_to_dict(baselines),
            "anomalies": [anomaly.to_dict() for anomaly in anomalies],
            "global_summary": global_summary,
            "status": "analyzed",
        }
    except EcomOpsError as exc:
        context.logger.error("[analyze_data] 失败: %s", exc)
        raise
    except Exception:
        context.logger.exception("[analyze_data] 未预期错误")
        raise


def ai_recommend_node(state: AgentState, context: RunContext) -> dict[str, Any]:
    """阶段一占位：不调用模型，不生成伪 AI 结论。"""
    context.logger.info("[ai_recommend] 阶段一未接入大模型，跳过模型调用")
    return {
        "ai_result": {
            "status": "not_configured",
            "provider": None,
            "message": "阶段一未接入大模型；本报告仅包含规则型核查方向，不代表模型结论。",
            "suggestions": [],
        },
        "status": "ai_skipped",
    }


def generate_report_node(state: AgentState, context: RunContext) -> dict[str, Any]:
    context.logger.info("[generate_report] 开始渲染 Markdown 报告")
    try:
        report_path = render_report(context, state)
        context.logger.info("[generate_report] 完成：%s", report_path)
        return {
            "report_path": str(report_path),
            "status": "completed",
        }
    except EcomOpsError as exc:
        context.logger.error("[generate_report] 失败: %s", exc)
        raise
    except Exception:
        context.logger.exception("[generate_report] 未预期错误")
        raise
