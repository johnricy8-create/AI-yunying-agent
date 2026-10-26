from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from ecom_ops.exceptions import AISchemaError
from ecom_ops.llm.schema import parse_ai_json
from ecom_ops.llm.service import AIService
from ecom_ops.graph.workflow import run_workflow
from ecom_ops.utils.files import read_text


class FakeRetriever:
    available = True
    info = {
        "enabled": True,
        "available": True,
        "embedding_model": "fake-embedding",
        "chunk_count": 1,
        "error": None,
    }

    def retrieve_many(self, queries, date_before=None):
        return [
            [
                {
                    "id": "c1",
                    "source": "knowledge/test.md",
                    "title": "测试知识",
                    "date": None,
                    "section": "高浏览低转化",
                    "text": "高浏览低转化时优先检查详情页和价格。",
                    "score": 0.8,
                }
            ]
            for _ in queries
        ]


class FakeChat:
    def __init__(self, content: str | None = None, exc: Exception | None = None):
        self.content = content
        self.exc = exc
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.exc:
            raise self.exc
        return AIMessage(content=self.content or "")


class FakeRateLimitError(Exception):
    status_code = 429


class RetryChat:
    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            raise FakeRateLimitError("1305 overloaded")
        return AIMessage(content=self.content)


def _anomaly() -> dict:
    return {
        "product_id": "P0001",
        "product_name": "高浏览零订单-销售报表",
        "product_desc": "Excel模板",
        "shop": "旗舰店",
        "platform": "抖音",
        "category": "Excel模板",
        "pv_today": 650,
        "pv_yesterday": 738,
        "pv_baseline": 697.4,
        "pv_change_rate": -0.1192,
        "orders_today": 0,
        "orders_yesterday": 20,
        "orders_baseline": 22.7,
        "sales_today": 0.0,
        "refund_today": 0.0,
        "cr_today": 0.0,
        "cr_baseline": 0.0326,
        "stock": 0,
        "anomaly_types": ["零转化", "订单量骤降"],
        "severity_level": "高危",
        "severity_score": 100.0,
        "low_confidence": False,
        "hits": [{"label": "零转化", "detail": "浏览量 650，订单量 0", "score": 100.0}],
    }


def _payload() -> str:
    return json.dumps(
        {
            "products": [
                {
                    "product_id": "P0001",
                    "summary": "高浏览但零订单，先核对下单链路。",
                    "fact_analysis": ["浏览量 650，订单量 0。"],
                    "possible_causes": [
                        {
                            "cause": "详情页或支付链路异常",
                            "confidence": "中",
                            "evidence": ["零订单且浏览量较高"],
                        }
                    ],
                    "recommendations": [
                        {
                            "action": "检查商品是否可正常下单",
                            "rationale": "先排除链路问题",
                            "expected_effect": "确认是否为可修复的转化阻断",
                            "risk": "无直接业务风险",
                            "needs_human": True,
                        }
                    ],
                    "manual_checks": ["确认库存与支付配置"],
                    "sources": ["K1", "K9"],
                }
            ],
            "global_notes": "仅基于当前数据与检索资料。",
        },
        ensure_ascii=False,
    )


def _ai_settings(settings, tmp_path: Path, max_attempts: int = 1, cache: bool = False):
    return replace(
        settings,
        llm=replace(
            settings.llm,
            enabled=True,
            max_attempts=max_attempts,
            retry_backoff_seconds=(0, 0),
            cache_enabled=cache,
            cache_dir=tmp_path / "cache",
        ),
        rag=replace(settings.rag, enabled=True),
    )


def test_parse_ai_json_handles_code_fence_and_source_filtering(settings, test_logger, tmp_path):
    parsed = parse_ai_json("```json\n" + _payload() + "\n```")
    assert len(parsed.products) == 1
    assert parsed.products[0].product_id == "P0001"
    assert parsed.products[0].possible_causes[0].confidence == "中"


def test_parse_ai_json_supports_products_dict_and_strings():
    payload = json.dumps(
        {
            "products": {
                "P0002": {
                    "summary": "测试",
                    "possible_causes": ["可能原因A"],
                    "recommendations": ["动作A"],
                }
            }
        },
        ensure_ascii=False,
    )
    parsed = parse_ai_json(payload)
    assert parsed.products[0].product_id == "P0002"
    assert parsed.products[0].possible_causes[0].confidence == "低"
    assert parsed.products[0].recommendations[0].needs_human is True


def test_parse_ai_json_rejects_invalid_output():
    with pytest.raises(AISchemaError):
        parse_ai_json("这不是 JSON")


def test_ai_service_ok_and_filters_unknown_sources(settings, test_logger, tmp_path):
    ai_settings = _ai_settings(settings, tmp_path)
    service = AIService(
        ai_settings,
        test_logger,
        chat_model=FakeChat(_payload()),
        retriever=FakeRetriever(),
    )
    result = service.recommend([_anomaly()], "2026-10-25")
    assert result["status"] == "ok"
    assert result["products"]["P0001"]["sources"] == ["K1"]
    assert result["retrieval"]["selected_count"] == 1
    assert result["retrieval"]["chunks"][0]["id"] == "K1"


def test_ai_service_retries_rate_limit(settings, test_logger, tmp_path):
    ai_settings = _ai_settings(settings, tmp_path, max_attempts=2)
    chat = RetryChat(_payload())
    service = AIService(
        ai_settings,
        test_logger,
        chat_model=chat,
        retriever=FakeRetriever(),
    )
    result = service.recommend([_anomaly()], "2026-10-25")
    assert result["status"] == "ok"
    assert chat.calls == 2


def test_ai_service_failure_returns_fallback(settings, test_logger, tmp_path):
    ai_settings = _ai_settings(settings, tmp_path, max_attempts=1)
    service = AIService(
        ai_settings,
        test_logger,
        chat_model=FakeChat(exc=RuntimeError("boom")),
        retriever=FakeRetriever(),
    )
    result = service.recommend([_anomaly()], "2026-10-25")
    assert result["status"] == "failed"
    assert "boom" in result["error"]
    assert result["products"] == {}


def test_ai_service_uses_cache(settings, test_logger, tmp_path):
    ai_settings = _ai_settings(settings, tmp_path, max_attempts=1, cache=True)
    first = AIService(
        ai_settings,
        test_logger,
        chat_model=FakeChat(_payload()),
        retriever=FakeRetriever(),
    )
    first_result = first.recommend([_anomaly()], "2026-10-25")
    assert first_result["status"] == "ok"

    failing_chat = FakeChat(exc=RuntimeError("should not be called"))
    second = AIService(
        ai_settings,
        test_logger,
        chat_model=failing_chat,
        retriever=FakeRetriever(),
    )
    second_result = second.recommend([_anomaly()], "2026-10-25")
    assert second_result["status"] == "ok"
    assert second_result["cached"] is True
    assert failing_chat.calls == 0


def test_ai_service_disabled(settings, test_logger, tmp_path):
    disabled = replace(settings, llm=replace(settings.llm, enabled=False))
    service = AIService(
        disabled,
        test_logger,
        chat_model=FakeChat(_payload()),
        retriever=FakeRetriever(),
    )
    result = service.recommend([_anomaly()], "2026-10-25")
    assert result["status"] == "disabled"


def test_ai_service_not_configured(settings, test_logger, tmp_path, monkeypatch):
    ai_settings = _ai_settings(settings, tmp_path)
    monkeypatch.setattr("ecom_ops.llm.service.build_chat_model", lambda _settings: None)
    service = AIService(
        ai_settings,
        test_logger,
        chat_model=None,
        retriever=FakeRetriever(),
    )
    result = service.recommend([_anomaly()], "2026-10-25")
    assert result["status"] == "not_configured"


def test_ai_consistency_warnings(settings, test_logger, tmp_path):
    ai_settings = _ai_settings(settings, tmp_path)
    service = AIService(
        ai_settings,
        test_logger,
        chat_model=FakeChat(_payload()),
        retriever=FakeRetriever(),
    )
    warnings = service._consistency_warnings(
        {
            "summary": "库存售罄，浏览量下降，新品首日波动，pv_direction: down",
            "possible_causes": [],
        },
        {
            "stock_status": "in_stock",
            "pv_direction": "up",
            "orders_direction": "flat",
            "product_age_days": 2,
        },
    )
    assert any("售罄" in item for item in warnings)
    assert any("浏览量" in item for item in warnings)
    assert any("首日" in item for item in warnings)
    assert any("pv_direction" in item for item in warnings)


def test_workflow_renders_ai_sections(context, mock_csv):
    class FakeAIService:
        def recommend(self, anomalies, stat_date, force_refresh=False):
            return {
                "status": "ok",
                "provider": "zhipu",
                "model": "glm-4.7-flash",
                "prompt_version": "v1",
                "generated_at": "2026-10-26 18:00:00",
                "latency_seconds": 1.2,
                "cached": False,
                "products": {
                    "P0001": {
                        "product_id": "P0001",
                        "summary": "高浏览零订单，先核对下单链路。",
                        "fact_analysis": ["浏览量 650，订单量 0。"],
                        "possible_causes": [
                            {"cause": "链路异常", "confidence": "中", "evidence": ["零订单"]}
                        ],
                        "recommendations": [
                            {
                                "action": "检查支付链路",
                                "rationale": "先排除阻断",
                                "expected_effect": "确认是否可恢复",
                                "risk": "无",
                                "needs_human": True,
                            }
                        ],
                        "manual_checks": ["确认库存"],
                        "sources": ["K1"],
                    }
                },
                "global_notes": "测试",
                "message": "AI 分析完成",
                "retrieval": {
                    "enabled": True,
                    "available": True,
                    "chunk_count": 1,
                    "selected_count": 1,
                    "chunks": [
                        {
                            "id": "K1",
                            "source": "knowledge/test.md",
                            "title": "测试知识",
                            "date": None,
                            "score": 0.8,
                            "preview": "高浏览低转化时优先检查详情页。",
                        }
                    ],
                    "error": None,
                },
                "error": None,
            }

    context.ai_service = FakeAIService()
    result = run_workflow(
        context,
        run_id="test-ai-run",
        source_path=str(mock_csv),
        stat_date="2026-10-25",
    )
    content = read_text(Path(result["report_path"]))
    assert "AI 摘要" in content
    assert "AI 建议" in content
    assert "高浏览零订单" in content
    assert "K1" in content
    assert result["ai_result"]["status"] == "ok"
