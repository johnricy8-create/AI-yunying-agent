"""一次运行所需的上下文对象。

配置与 logger 不放进 LangGraph 状态，避免状态臃肿；
节点通过闭包持有 RunContext。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ecom_ops.config import Settings


@dataclass
class RunContext:
    settings: Settings
    logger: logging.LoggerAdapter
    # 测试可注入假的 AI 服务；生产环境由 ai_recommend 节点按配置构造。
    ai_service: Any | None = None
