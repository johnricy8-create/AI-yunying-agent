"""定时任务执行器。

- APScheduler 每天北京时间 09:00 触发；
- 文件锁防止手动运行/定时任务并发；
- 失败按配置有限重试；
- 每次执行都走完整 LangGraph 工作流并记录日志。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from ecom_ops.config import Settings
from ecom_ops.context import RunContext
from ecom_ops.graph.workflow import run_workflow
from ecom_ops.history.store import record_result
from ecom_ops.logging_setup import get_run_logger
from ecom_ops.utils.dates import now
from ecom_ops.utils.files import ensure_dir


def parse_hhmm(value: str) -> tuple[int, int]:
    """解析 HH:MM，用于临时调整测试时间。"""
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"时间格式错误，应为 HH:MM: {value!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"时间超出范围: {value!r}")
    return hour, minute


def acquire_lock(lock_file: Path, stale_seconds: int, logger: logging.Logger) -> bool:
    """用 O_EXCL 创建锁文件；过期的旧锁自动清理。"""
    ensure_dir(lock_file.parent)
    if lock_file.exists():
        try:
            age = time.time() - lock_file.stat().st_mtime
        except OSError:
            age = 0
        if age > stale_seconds:
            logger.warning("发现过期调度锁（%.0f 秒），自动清理: %s", age, lock_file)
            lock_file.unlink(missing_ok=True)
        else:
            logger.warning("已有任务在运行，跳过本次调度（锁: %s）", lock_file)
            return False

    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        logger.warning("调度锁竞争失败，跳过本次调度: %s", lock_file)
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {"pid": os.getpid(), "started_at": now().isoformat()},
            handle,
            ensure_ascii=False,
        )
    return True


def release_lock(lock_file: Path) -> None:
    lock_file.unlink(missing_ok=True)


def run_job(
    settings: Settings,
    data_path: str | Path | None = None,
    stat_date: str | None = None,
    ai_enabled: bool = True,
    data_note: str | None = None,
    sheet_name: str | None = None,
) -> dict:
    """执行一次定时任务，返回工作流结果或失败/跳过状态。"""
    lock_file = settings.scheduler.lock_file
    base_logger = logging.getLogger("ecom_ops.scheduler")
    if not acquire_lock(lock_file, settings.scheduler.stale_lock_seconds, base_logger):
        return {"status": "skipped", "reason": "lock", "report_path": ""}

    run_id = (
        f"scheduled-{now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    logger = get_run_logger(run_id)
    source = Path(data_path) if data_path else settings.app.data_file
    app = replace(settings.app, data_file=source)
    llm = settings.llm if ai_enabled else replace(settings.llm, enabled=False)
    job_settings = replace(settings, app=app, llm=llm)
    context = RunContext(settings=job_settings, logger=logger)

    attempts = max(1, settings.scheduler.max_retries + 1)
    last_error: Exception | None = None
    try:
        for attempt in range(1, attempts + 1):
            try:
                logger.info(
                    "[scheduler] 开始执行（第 %d/%d 次），数据文件=%s，统计日期=%s",
                    attempt,
                    attempts,
                    source,
                    stat_date or "默认 D-1",
                )
                result = run_workflow(
                    context,
                    run_id=run_id,
                    source_path=source,
                    stat_date=stat_date,
                    data_note=data_note,
                    sheet_name=sheet_name,
                )
                if result.get("status") == "completed":
                    try:
                        record_result(
                            job_settings,
                            result,
                            source_file=str(source),
                            data_note=data_note,
                        )
                    except Exception as history_exc:
                        logger.warning(
                            "[scheduler] 历史记录写入失败（不影响报告）: %s",
                            history_exc,
                        )
                logger.info(
                    "[scheduler] 执行完成：状态=%s，报告=%s",
                    result.get("status"),
                    result.get("report_path"),
                )
                return result
            except Exception as exc:  # 记录完整堆栈并有限重试
                last_error = exc
                logger.exception(
                    "[scheduler] 第 %d/%d 次执行失败: %s",
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts:
                    delay = settings.scheduler.retry_delay_seconds
                    logger.warning("等待 %s 秒后重试", delay)
                    time.sleep(delay)
        return {
            "status": "failed",
            "error": f"{type(last_error).__name__}: {last_error}",
            "report_path": "",
        }
    finally:
        release_lock(lock_file)


def build_scheduler(
    settings: Settings,
    job,
    hour: int | None = None,
    minute: int | None = None,
) -> BlockingScheduler:
    """构建每天固定时间执行的 BlockingScheduler。"""
    timezone = ZoneInfo(settings.app.timezone)
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        job,
        "cron",
        hour=settings.scheduler.hour if hour is None else hour,
        minute=settings.scheduler.minute if minute is None else minute,
        id="daily_ops",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.scheduler.misfire_grace_seconds,
    )
    return scheduler
