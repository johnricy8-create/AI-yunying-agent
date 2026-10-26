"""测试公共 fixture。"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from ecom_ops.config import load_settings
from ecom_ops.context import RunContext
from ecom_ops.data.mock import generate_mock_data, write_mock_csv


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def base_settings():
    return load_settings()


@pytest.fixture()
def settings(tmp_path: Path, base_settings):
    app = replace(
        base_settings.app,
        report_dir=tmp_path / "reports",
        log_dir=tmp_path / "logs",
    )
    # 单元测试默认不调用真实 API；需要联网的用例单独注入假服务或显式开启。
    return replace(
        base_settings,
        app=app,
        llm=replace(base_settings.llm, enabled=False),
        rag=replace(base_settings.rag, enabled=False),
    )


@pytest.fixture()
def fields(settings):
    return settings.fields


@pytest.fixture()
def test_logger():
    logger = logging.getLogger("ecom_ops.test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logging.LoggerAdapter(logger, {"run_id": "test"})


@pytest.fixture()
def context(settings, test_logger):
    return RunContext(settings=settings, logger=test_logger)


@pytest.fixture()
def mock_csv(tmp_path: Path) -> Path:
    df = generate_mock_data(
        products=30,
        days=14,
        seed=7,
        end_date=date(2026, 10, 25),
    )
    path = tmp_path / "sales_mock.csv"
    write_mock_csv(df, path)
    return path
