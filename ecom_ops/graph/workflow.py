"""LangGraph StateGraph 组装。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from ecom_ops.context import RunContext
from ecom_ops.graph.nodes import (
    ai_recommend_node,
    analyze_data_node,
    generate_report_node,
    load_data_node,
)
from ecom_ops.graph.state import AgentState


def build_workflow(context: RunContext):
    """构建阶段一固定工作流。"""
    graph = StateGraph(AgentState)
    graph.add_node("load_data", lambda state: load_data_node(state, context))
    graph.add_node("analyze_data", lambda state: analyze_data_node(state, context))
    graph.add_node("ai_recommend", lambda state: ai_recommend_node(state, context))
    graph.add_node("generate_report", lambda state: generate_report_node(state, context))

    graph.add_edge(START, "load_data")
    graph.add_edge("load_data", "analyze_data")
    graph.add_edge("analyze_data", "ai_recommend")
    graph.add_edge("ai_recommend", "generate_report")
    graph.add_edge("generate_report", END)
    return graph.compile()


def run_workflow(
    context: RunContext,
    run_id: str,
    source_path: str | Path,
    stat_date: str | None = None,
    force_refresh_ai: bool = False,
) -> dict[str, Any]:
    """执行一次完整工作流，返回最终状态。"""
    compiled = build_workflow(context)
    initial: AgentState = {
        "run_id": run_id,
        "source_path": str(source_path),
        "stat_date": stat_date or "",
        "force_refresh_ai": force_refresh_ai,
        "status": "started",
        "errors": [],
    }
    context.logger.info(
        "[workflow] 开始运行 run_id=%s，数据文件=%s，请求统计日期=%s",
        run_id,
        source_path,
        stat_date or "默认",
    )
    result = compiled.invoke(initial)
    context.logger.info(
        "[workflow] 运行结束 run_id=%s，状态=%s，报告=%s",
        run_id,
        result.get("status"),
        result.get("report_path"),
    )
    return dict(result)
