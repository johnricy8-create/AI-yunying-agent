"""大模型输出的结构化契约。

模型必须只输出 JSON；这里做解析、容错和 Pydantic 校验。
解析失败由上层降级为规则型报告，不影响整次任务。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from ecom_ops.exceptions import AISchemaError


class PossibleCause(BaseModel):
    cause: str
    confidence: str = "低"
    evidence: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> str:
        mapping = {
            "high": "高",
            "medium": "中",
            "mid": "中",
            "low": "低",
            "高": "高",
            "中": "中",
            "低": "低",
        }
        return mapping.get(str(value).strip().lower(), str(value).strip() or "低")

class Recommendation(BaseModel):
    action: str
    rationale: str = ""
    expected_effect: str = ""
    risk: str = ""
    needs_human: bool = True

    @field_validator("needs_human", mode="before")
    @classmethod
    def _normalize_needs_human(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        return str(value).strip().lower() not in {"false", "0", "no", "否", "不需要"}


class ProductAnalysis(BaseModel):
    product_id: str
    summary: str = ""
    fact_analysis: list[str] = Field(default_factory=list)
    possible_causes: list[PossibleCause] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    manual_checks: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @field_validator("possible_causes", mode="before")
    @classmethod
    def _coerce_causes(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return []
        result: list[Any] = []
        for item in value:
            if isinstance(item, str):
                result.append({"cause": item, "confidence": "低"})
            elif isinstance(item, dict):
                result.append(item)
        return result

    @field_validator("recommendations", mode="before")
    @classmethod
    def _coerce_recommendations(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return []
        result: list[Any] = []
        for item in value:
            if isinstance(item, str):
                result.append({"action": item, "needs_human": True})
            elif isinstance(item, dict):
                result.append(item)
        return result

    @field_validator("fact_analysis", "manual_checks", "sources", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
        return []


class AIAnalysis(BaseModel):
    products: list[ProductAnalysis] = Field(default_factory=list)
    global_notes: str = ""


def _extract_json(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise AISchemaError("模型返回为空")
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AISchemaError("模型输出中没有找到 JSON 对象")
    return cleaned[start : end + 1]


def parse_ai_json(text: str) -> AIAnalysis:
    """解析模型输出；兼容 products 为对象或数组。"""
    payload = _extract_json(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AISchemaError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise AISchemaError("模型输出的 JSON 顶层必须是对象")

    products = data.get("products")
    if isinstance(products, dict):
        converted: list[dict[str, Any]] = []
        for product_id, item in products.items():
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("product_id", str(product_id))
                converted.append(item)
        data["products"] = converted
    if not isinstance(data.get("products"), list):
        raise AISchemaError("模型输出缺少 products 数组")

    try:
        return AIAnalysis.model_validate(data)
    except ValidationError as exc:
        raise AISchemaError(f"模型输出不符合约定结构: {exc}") from exc
