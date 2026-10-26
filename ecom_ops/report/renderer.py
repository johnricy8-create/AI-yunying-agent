"""Markdown 报告渲染。

报告只负责展示，不重新计算任何指标；
所有数字都来自 analyze_data 的输出。
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ecom_ops.context import RunContext
from ecom_ops.exceptions import ReportError
from ecom_ops.graph.state import AgentState
from ecom_ops.utils.dates import format_datetime
from ecom_ops.utils.files import ensure_dir, write_text_atomic


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_RULE_DIRECTIONS: dict[str, list[str]] = {
    "zero_conversion": [
        "核对商品详情页、价格与库存是否正常可见",
        "检查下单与支付链路是否存在故障",
        "核对流量来源是否精准，排除无效流量或统计异常",
    ],
    "pv_drop": [
        "核对平台搜索排名、活动结束时间与商品是否下架",
        "检查竞品动作、站外流量与投放变化",
        "确认数据采集是否漏数或日期错位",
    ],
    "order_drop": [
        "检查价格、优惠、评价与售后变化",
        "核对库存、支付故障与下单链路",
        "复盘流量结构是否发生明显变化",
    ],
    "high_pv_low_cr": [
        "优化详情页首屏卖点与信息完整度",
        "检查价格竞争力、评价与信任信息",
        "核对流量关键词与商品匹配度",
    ],
    "stock_out": [
        "确认补货计划与到货时间",
        "评估是否暂停投放或临时下架",
    ],
    "overstock": [
        "评估促销、组合销售或清仓方案",
        "控制后续采购与投放节奏",
    ],
}

_STATUS_LABELS = {
    "started": "开始",
    "data_loaded": "数据已加载",
    "analyzed": "分析完成",
    "ai_skipped": "AI 未接入",
    "completed": "成功",
    "failed": "失败",
}


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return True
    try:
        return bool(value != value)  # NaN
    except Exception:
        return False


def _fmt_int(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_float(value: Any, digits: int = 1) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_money(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"¥{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "—"


def _fmt_change(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):+.2%}"
    except (TypeError, ValueError):
        return "—"


def _md_escape(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _truncate(value: Any, length: int = 200) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) <= length:
        return text
    return text[:length] + "…"


def _confidence_label(value: Any) -> str:
    return {
        "normal": "正常",
        "low": "低",
        "unavailable": "不可用",
    }.get(str(value), str(value) if value is not None else "—")


def _suggestion_groups(anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for anomaly in anomalies:
        for hit in anomaly.get("hits", []):
            code = str(hit.get("code", ""))
            if code not in groups:
                groups[code] = {
                    "label": hit.get("label", code),
                    "products": [],
                    "directions": _RULE_DIRECTIONS.get(code, ["结合业务实际进一步核查"]),
                }
            if anomaly.get("product_name") not in groups[code]["products"]:
                groups[code]["products"].append(anomaly.get("product_name", ""))
    return list(groups.values())


def _manual_confirmations(
    anomalies: list[dict[str, Any]],
    data_quality: dict[str, Any],
) -> list[str]:
    items: list[str] = []
    summary = data_quality.get("summary", {})
    invalid_rows = int(summary.get("invalid_rows", 0) or 0)
    if invalid_rows:
        items.append(
            f"有 {invalid_rows} 行数据未通过校验并被隔离，请核对原始数据与报告末尾的数据质量摘要。"
        )

    low_confidence = [
        str(item.get("product_name", ""))
        for item in anomalies
        if item.get("low_confidence")
    ]
    if low_confidence:
        items.append(
            "以下商品基线置信度低，异常结论需人工复核："
            + "、".join(low_confidence[:10])
            + (" 等" if len(low_confidence) > 10 else "")
        )

    high_risk = [
        str(item.get("product_name", ""))
        for item in anomalies
        if item.get("severity_level") == "高危"
    ]
    if high_risk:
        items.append(
            "高危异常建议优先处理："
            + "、".join(high_risk[:10])
            + (" 等" if len(high_risk) > 10 else "")
        )

    zero_conversion = [
        str(item.get("product_name", ""))
        for item in anomalies
        if "零转化" in item.get("anomaly_types", [])
    ]
    if zero_conversion:
        items.append(
            "零转化商品需确认详情页、价格、库存与支付链路："
            + "、".join(zero_conversion[:10])
            + (" 等" if len(zero_conversion) > 10 else "")
        )

    stock_low = [
        str(item.get("product_name", ""))
        for item in anomalies
        if "断货风险" in item.get("anomaly_types", [])
    ]
    if stock_low:
        items.append("断货风险商品请确认补货计划：" + "、".join(stock_low[:10]))

    if not items:
        items.append("本报告未发现必须人工确认的阻断项，但仍建议抽查 Top 异常商品。")
    return items


def render_report(context: RunContext, state: AgentState) -> Path:
    settings = context.settings
    stat_date = str(state.get("stat_date", ""))
    if not stat_date:
        raise ReportError("报告渲染缺少统计日期")

    report_dir = ensure_dir(settings.app.report_dir)
    filename = settings.report.filename_pattern.format(date=stat_date)
    report_path = report_dir / filename

    anomalies = list(state.get("anomalies", []) or [])
    top_n = settings.report.top_n
    top_anomalies = anomalies[:top_n]
    other_anomalies = anomalies[top_n:]

    other_type_counts: dict[str, int] = {}
    for anomaly in other_anomalies:
        for label in anomaly.get("anomaly_types", []):
            other_type_counts[label] = other_type_counts.get(label, 0) + 1

    data_quality = dict(state.get("data_quality", {}) or {})
    summary = dict(data_quality.get("summary", {}) or {})
    metrics = state.get("metrics")
    missing_yesterday = 0
    if metrics is not None and "has_yesterday" in metrics.columns:
        missing_yesterday = int((~metrics["has_yesterday"].astype(bool)).sum())

    global_summary = dict(state.get("global_summary", {}) or {})
    ai_result = dict(state.get("ai_result", {}) or {})
    report_time = format_datetime()
    status = str(state.get("status", ""))
    pipeline_status = _STATUS_LABELS.get(status, status or "—")
    # 报告能渲染到这里，说明本次报告生成已经成功；流水线状态单独展示。
    status_label = "成功（报告已生成）"

    data_limitations: list[str] = [
        "阶段一未接入大模型；AI 原因分析章节为占位，不构成模型结论。",
        "统计日期默认为运行日的前一天（D-1）；如需补跑，可在命令行显式指定日期。",
        "基线采用 3/5/7 日均值，按近期波动自适应选择；无法处理周内规律与季节性，开学季等正常波动可能被误判。",
        "缺失日期不插值；基线只使用有效历史数据。",
        "昨日浏览量为 0 或缺失时，浏览量变化率显示为“—”，不参与异常判定。",
        "销售额为已扣除退款、不含税的净额；退款金额仅用于校验，不再二次扣减。",
        "库存仅作展示与数据校验，阶段一不参与异常判定（库存规则默认关闭）。",
    ]
    if int(summary.get("invalid_rows", 0) or 0) > 0:
        data_limitations.append(
            f"本次有 {summary.get('invalid_rows')} 行数据未通过校验，已从指标计算中排除。"
        )
    if int(summary.get("warning_rows", 0) or 0) > 0:
        data_limitations.append(
            f"本次有 {summary.get('warning_rows')} 行数据带警告（如简介缺失），仍参与计算。"
        )
    low_confidence_count = sum(1 for item in anomalies if item.get("low_confidence"))
    if low_confidence_count:
        data_limitations.append(
            f"共有 {low_confidence_count} 个异常商品的基线置信度低，相关结论需谨慎使用。"
        )
    if missing_yesterday:
        data_limitations.append(
            f"共有 {missing_yesterday} 个商品缺少昨日数据，无法计算昨日对比与变化率。"
        )
    if global_summary.get("warning"):
        data_limitations.append(str(global_summary["warning"]))

    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters.update(
        {
            "fmt_int": _fmt_int,
            "fmt_float": _fmt_float,
            "fmt_money": _fmt_money,
            "fmt_pct": _fmt_pct,
            "fmt_change": _fmt_change,
            "md": _md_escape,
            "truncate_desc": _truncate,
            "conf": _confidence_label,
        }
    )

    try:
        template = environment.get_template("daily_report.md.j2")
        content = template.render(
            report_time=report_time,
            stat_date=stat_date,
            run_id=state.get("run_id", "—"),
            status_label=status_label,
            pipeline_status=pipeline_status,
            report_path=str(report_path),
            global_summary=global_summary,
            data_quality=data_quality,
            summary=summary,
            top_anomalies=top_anomalies,
            other_anomalies=other_anomalies,
            other_type_counts=other_type_counts,
            top_n=top_n,
            ai_result=ai_result,
            suggestion_groups=_suggestion_groups(top_anomalies),
            manual_confirmations=_manual_confirmations(anomalies, data_quality),
            data_limitations=data_limitations,
            description_max_chars=settings.report.description_max_chars,
            anomaly_config=settings.anomaly,
            baseline_config=settings.baseline,
            conversion_mode=global_summary.get("conversion_mode", "pv"),
            source_file=data_quality.get("source_file", ""),
            available_dates=data_quality.get("available_dates", []),
        )
    except Exception as exc:
        raise ReportError(f"报告模板渲染失败: {exc}") from exc

    try:
        write_text_atomic(report_path, content, encoding="utf-8")
    except Exception as exc:
        raise ReportError(f"报告写入失败: {report_path}\n{exc}") from exc
    return report_path
