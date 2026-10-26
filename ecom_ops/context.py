"""一次运行所需的上下文对象。

配置与 logger 不放进 LangGraph 状态，避免状态臃肿；
节点通过闭包持有 RunContext。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ecom_ops.config import Settings


@dataclass
class RunContext:
    settings: Settings
    logger: logging.LoggerAdapter
