from __future__ import annotations

from pathlib import Path

import pytest

from ecom_ops.context import RunContext
from ecom_ops.exceptions import DataLoadError
from ecom_ops.graph.nodes import load_data_node
from ecom_ops.graph.workflow import run_workflow
from ecom_ops.logging_setup import get_run_logger, setup_logging
from ecom_ops.utils.files import read_text


REQUIRED_SECTIONS = [
    "## 1. 数据概览",
    "## 2. 全局指标",
    "## 3. 异常商品 Top",
    "## 4. 异常详情",
    "## 5. 未进入 Top-",
    "## 6. AI 原因分析",
    "## 7. 运营优化建议",
    "## 8. 待人工确认事项",
    "## 9. 数据限制",
    "## 10. 执行状态",
    "## 11. 统计口径",
    "## 12. 附录",
]


def test_end_to_end_generates_report(context, mock_csv):
    result = run_workflow(
        context,
        run_id="test-run-001",
        source_path=str(mock_csv),
        stat_date="2026-10-25",
    )
    assert result["status"] == "completed"
    assert result["stat_date"] == "2026-10-25"
    assert result["anomalies"]
    assert result["data_quality"]["summary"]["invalid_rows"] >= 1

    report_path = Path(result["report_path"])
    assert report_path.exists()
    content = read_text(report_path)
    for section in REQUIRED_SECTIONS:
        assert section in content, f"报告缺少章节: {section}"
    assert "大模型未启用" in content
    assert "成功（报告已生成）" in content
    assert "高浏览零订单" in content
    assert "规则型核查方向" in content


def test_rerun_same_date_overwrites_report(context, mock_csv, settings):
    first = run_workflow(
        context,
        run_id="test-run-001",
        source_path=str(mock_csv),
        stat_date="2026-10-25",
    )
    second = run_workflow(
        context,
        run_id="test-run-002",
        source_path=str(mock_csv),
        stat_date="2026-10-25",
    )
    assert first["report_path"] == second["report_path"]
    files = list(settings.app.report_dir.glob("*.md"))
    assert len(files) == 1
    content = read_text(Path(second["report_path"]))
    assert "test-run-002" in content
    assert "test-run-001" not in content


def test_data_note_is_written_to_report(context, mock_csv):
    result = run_workflow(
        context,
        run_id="test-note",
        source_path=str(mock_csv),
        stat_date="2026-10-25",
        data_note="演示数据说明：销售字段为模拟值",
    )
    content = read_text(Path(result["report_path"]))
    assert "数据说明" in content
    assert "销售字段为模拟值" in content


def test_missing_data_file_fails_fast(context, tmp_path):
    with pytest.raises(DataLoadError):
        load_data_node(
            {
                "source_path": str(tmp_path / "missing.csv"),
                "stat_date": "2026-10-25",
            },
            context,
        )


def test_logging_writes_run_id(settings, mock_csv, tmp_path):
    setup_logging(
        tmp_path / "logs",
        level="INFO",
        filename="ecom_ops.log",
        retention_days=30,
    )
    logger = get_run_logger("log-test-run")
    context = RunContext(settings=settings, logger=logger)
    result = run_workflow(
        context,
        run_id="log-test-run",
        source_path=str(mock_csv),
        stat_date="2026-10-25",
    )
    assert result["status"] == "completed"
    log_file = tmp_path / "logs" / "ecom_ops.log"
    assert log_file.exists()
    log_content = read_text(log_file)
    assert "log-test-run" in log_content
    assert "[workflow]" in log_content
