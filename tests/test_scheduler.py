from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ecom_ops.scheduler.runner import (
    acquire_lock,
    build_scheduler,
    parse_hhmm,
    release_lock,
    run_job,
)
from ecom_ops.utils.files import read_text


def test_parse_hhmm():
    assert parse_hhmm("09:00") == (9, 0)
    assert parse_hhmm("23:59") == (23, 59)
    with pytest.raises(ValueError):
        parse_hhmm("24:00")


def test_lock_prevents_concurrent_run(tmp_path, test_logger):
    lock = tmp_path / "scheduler.lock"
    lock.write_text("busy", encoding="utf-8")
    assert acquire_lock(lock, stale_seconds=3600, logger=test_logger) is False
    release_lock(lock)
    assert not lock.exists()
    assert acquire_lock(lock, stale_seconds=3600, logger=test_logger) is True
    release_lock(lock)


def test_run_job_completes_and_releases_lock(settings, mock_csv, tmp_path):
    schedule = replace(
        settings.scheduler,
        lock_file=tmp_path / "scheduler.lock",
        max_retries=0,
        retry_delay_seconds=0,
    )
    job_settings = replace(
        settings,
        scheduler=schedule,
        llm=replace(settings.llm, enabled=False),
    )
    result = run_job(
        job_settings,
        data_path=mock_csv,
        stat_date="2026-10-25",
        ai_enabled=False,
        data_note="定时任务测试",
    )
    assert result["status"] == "completed"
    assert Path(result["report_path"]).exists()
    assert not schedule.lock_file.exists()
    assert "定时任务测试" in read_text(Path(result["report_path"]))


def test_build_scheduler_registers_daily_job(settings):
    scheduler = build_scheduler(settings, lambda: None, hour=9, minute=5)
    job = scheduler.get_job("daily_ops")
    assert job is not None
    assert job.id == "daily_ops"
