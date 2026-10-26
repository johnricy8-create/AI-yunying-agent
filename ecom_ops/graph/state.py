"""工作流状态定义。

阶段一没有检查点/持久化需求，因此状态直接携带 DataFrame 与明细结果，
实现简单；阶段五引入历史与断点续跑时，再迁移为“状态只放引用”。
"""

from __future__ import annotations

from typing import Any, TypedDict

import pandas as pd


class AgentState(TypedDict, total=False):
    run_id: str
    stat_date: str
    source_path: str

    data: pd.DataFrame
    data_quality: dict[str, Any]

    metrics: pd.DataFrame
    baselines: dict[str, dict[str, dict[str, Any]]]
    anomalies: list[dict[str, Any]]
    global_summary: dict[str, Any]

    ai_result: dict[str, Any]
    force_refresh_ai: bool
    report_path: str
    status: str
    errors: list[str]
