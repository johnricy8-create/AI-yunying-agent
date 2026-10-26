"""日志初始化。

标准库 logging：控制台 + 按天轮转文件，UTF-8，默认保留 30 天。
每条日志通过 RunIdFilter 注入 run_id，未注入时显示短横线。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from ecom_ops.utils.files import ensure_dir


_current_run_id = "-"


class RunIdFilter(logging.Filter):
    """保证所有日志记录都有 run_id 字段，避免格式化时报错。

    节点通过 LoggerAdapter 注入 run_id；直接使用模块 logger 的组件
    （例如 loader）则回退到最近一次 get_run_logger 设置的当前 run_id。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id") or not getattr(record, "run_id"):
            record.run_id = _current_run_id
        return True


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    filename: str = "ecom_ops.log",
    retention_days: int = 30,
) -> logging.Logger:
    """创建项目根 logger，重复调用时先清理旧 handler。"""
    ensure_dir(log_dir)

    # Windows 控制台可能是 GBK；尽可能切到 UTF-8，避免中文日志报编码错误。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    logger = logging.getLogger("ecom_ops")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(run_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = TimedRotatingFileHandler(
        filename=log_dir / filename,
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RunIdFilter())

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RunIdFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def get_run_logger(run_id: str) -> logging.LoggerAdapter:
    """返回带 run_id 的 logger 适配器，并更新模块级默认 run_id。"""
    global _current_run_id
    _current_run_id = run_id
    return logging.LoggerAdapter(logging.getLogger("ecom_ops"), {"run_id": run_id})
