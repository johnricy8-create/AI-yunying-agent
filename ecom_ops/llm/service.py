"""阶段二 AI 建议服务。

职责：
1. 为 Top-N 异常构造紧凑输入；
2. 通过 RAG 检索知识库/历史日报；
3. 调用 GLM-4.7-Flash，要求输出结构化 JSON；
4. 对 1305/429/5xx/超时做退避重试；
5. 失败时返回可降级结果，报告继续生成。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ecom_ops.config import Settings
from ecom_ops.exceptions import AISchemaError
from ecom_ops.llm.client import build_chat_model
from ecom_ops.llm.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from ecom_ops.llm.schema import AIAnalysis, parse_ai_json
from ecom_ops.rag.retriever import RAGRetriever
from ecom_ops.utils.dates import format_datetime
from ecom_ops.utils.files import ensure_dir, write_text_atomic

logger = logging.getLogger(__name__)


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, AISchemaError):
        return True
    status = getattr(exc, "status_code", None)
    if status in {408, 409, 429, 500, 502, 503, 504}:
        return True
    name = type(exc).__name__.lower()
    return any(
        token in name
        for token in ("ratelimit", "timeout", "connection", "internalserver", "serviceunavailable")
    )


def _round(value: Any, digits: int = 2) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return round(number, digits)


def _direction(today: Any, baseline: Any) -> str:
    current = _round(today, 4)
    base = _round(baseline, 4)
    if current is None or base is None or base <= 0:
        return "unknown"
    if current > base * 1.05:
        return "up"
    if current < base * 0.95:
        return "down"
    return "flat"


class AIService:
    def __init__(
        self,
        settings: Settings,
        logger_adapter: logging.LoggerAdapter | logging.Logger | None = None,
        chat_model: Any | None = None,
        retriever: RAGRetriever | Any | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger_adapter or logger
        self.chat_model = chat_model if chat_model is not None else build_chat_model(settings)
        self.retriever = retriever if retriever is not None else RAGRetriever(settings)

    @property
    def configured(self) -> bool:
        return bool(self.settings.llm.enabled and self.chat_model is not None)

    def _base_result(self, status: str, message: str = "", error: str | None = None) -> dict[str, Any]:
        return {
            "status": status,
            "provider": self.settings.llm.provider,
            "model": self.settings.llm.model,
            "prompt_version": PROMPT_VERSION,
            "generated_at": format_datetime(),
            "latency_seconds": None,
            "cached": False,
            "products": {},
            "global_notes": "",
            "message": message,
            "retrieval": self._retrieval_info(),
            "error": error,
        }

    def _retrieval_info(self) -> dict[str, Any]:
        info = getattr(self.retriever, "info", {}) or {}
        return {
            "enabled": bool(info.get("enabled", self.settings.rag.enabled)),
            "available": bool(info.get("available", False)),
            "embedding_model": info.get("embedding_model", self.settings.rag.embedding_model),
            "chunk_count": int(info.get("chunk_count", 0) or 0),
            "selected_count": 0,
            "chunks": [],
            "error": info.get("error"),
        }

    def _anomaly_payload(self, anomaly: dict[str, Any]) -> dict[str, Any]:
        pv_today = _round(anomaly.get("pv_today"), 0)
        pv_baseline = _round(anomaly.get("pv_baseline"), 1)
        orders_today = _round(anomaly.get("orders_today"), 0)
        orders_baseline = _round(anomaly.get("orders_baseline"), 1)
        cr_today = _round(anomaly.get("cr_today"), 4)
        cr_baseline = _round(anomaly.get("cr_baseline"), 4)
        stock = _round(anomaly.get("stock"), 0)
        pv_change_rate = _round(anomaly.get("pv_change_rate"), 4)
        return {
            "product_id": anomaly.get("product_id"),
            "product_name": anomaly.get("product_name"),
            "product_desc": str(anomaly.get("product_desc", ""))[:200],
            "shop": anomaly.get("shop"),
            "platform": anomaly.get("platform"),
            "category": anomaly.get("category"),
            "pv_today": pv_today,
            "pv_yesterday": _round(anomaly.get("pv_yesterday"), 0),
            "pv_baseline": pv_baseline,
            "pv_change_rate": pv_change_rate,
            "pv_change_rate_pct": (
                round(pv_change_rate * 100, 2) if pv_change_rate is not None else None
            ),
            "pv_direction": _direction(pv_today, pv_baseline),
            "orders_today": orders_today,
            "orders_yesterday": _round(anomaly.get("orders_yesterday"), 0),
            "orders_baseline": orders_baseline,
            "orders_direction": _direction(orders_today, orders_baseline),
            "sales_today": _round(anomaly.get("sales_today"), 2),
            "refund_today": _round(anomaly.get("refund_today"), 2),
            "cr_today": cr_today,
            "cr_baseline": cr_baseline,
            "cr_today_pct": round(cr_today * 100, 2) if cr_today is not None else None,
            "cr_baseline_pct": round(cr_baseline * 100, 2) if cr_baseline is not None else None,
            "cr_direction": _direction(cr_today, cr_baseline),
            "stock": stock,
            "stock_status": "out_of_stock" if stock is not None and stock <= 0 else "in_stock",
            "product_age_days": anomaly.get("product_age_days"),
            "is_first_day": anomaly.get("is_first_day"),
            "anomaly_types": anomaly.get("anomaly_types", []),
            "severity_level": anomaly.get("severity_level"),
            "severity_score": anomaly.get("severity_score"),
            "low_confidence": anomaly.get("low_confidence"),
            "rule_hits": [
                {
                    "label": hit.get("label"),
                    "detail": hit.get("detail"),
                    "score": hit.get("score"),
                }
                for hit in anomaly.get("hits", [])
            ],
        }

    def _query_for(self, anomaly: dict[str, Any]) -> str:
        types = " ".join(anomaly.get("anomaly_types", []))
        return (
            f"{anomaly.get('product_name', '')} {anomaly.get('category', '')} "
            f"{anomaly.get('platform', '')} {types} "
            f"浏览量 {anomaly.get('pv_today')} 转化率 {anomaly.get('cr_today')} "
            f"订单 {anomaly.get('orders_today')} 基线 {anomaly.get('pv_baseline')} "
            f"排查 建议"
        )

    def _combine_retrieval(
        self,
        anomalies: list[dict[str, Any]],
        retrieved: list[list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        """合并多个商品的检索结果，按相似度保留高分块，并编号 K1..Kn。"""
        raw_chunks: dict[str, dict[str, Any]] = {}
        product_hits: dict[str, list[str]] = {}

        for anomaly, hits in zip(anomalies, retrieved):
            product_id = str(anomaly.get("product_id", ""))
            original_ids: list[str] = []
            for hit in hits:
                original_id = str(hit.get("id", ""))
                if not original_id:
                    continue
                original_ids.append(original_id)
                if original_id not in raw_chunks:
                    raw_chunks[original_id] = {
                        "original_id": original_id,
                        "source": hit.get("source", ""),
                        "title": hit.get("title", ""),
                        "date": hit.get("date"),
                        "section": hit.get("section", ""),
                        "score": float(hit.get("score", 0) or 0),
                        "text": hit.get("text", ""),
                    }
                else:
                    raw_chunks[original_id]["score"] = max(
                        raw_chunks[original_id]["score"],
                        float(hit.get("score", 0) or 0),
                    )
            product_hits[product_id] = original_ids

        ordered = sorted(
            raw_chunks.values(),
            key=lambda item: item.get("score", 0),
            reverse=True,
        )[: self.settings.rag.max_selected_chunks]

        selected: list[dict[str, Any]] = []
        id_to_label: dict[str, str] = {}
        for index, chunk in enumerate(ordered, start=1):
            label = f"K{index}"
            id_to_label[str(chunk["original_id"])] = label
            selected.append(
                {
                    "id": label,
                    "source": chunk["source"],
                    "title": chunk["title"],
                    "date": chunk["date"],
                    "section": chunk["section"],
                    "score": chunk["score"],
                    "text": chunk["text"],
                }
            )

        anomaly_refs: dict[str, list[str]] = {}
        for product_id, original_ids in product_hits.items():
            refs: list[str] = []
            for original_id in original_ids:
                label = id_to_label.get(original_id)
                if label and label not in refs:
                    refs.append(label)
            anomaly_refs[product_id] = refs
        return selected, anomaly_refs

    def _cache_path(self, stat_date: str, payload: dict[str, Any]) -> Path:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
        return self.settings.llm.cache_dir / f"{stat_date}_{digest}.json"

    def recommend(
        self,
        anomalies: list[dict[str, Any]],
        stat_date: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if not self.settings.llm.enabled:
            return self._base_result("disabled", "阶段二大模型未启用，报告使用规则型建议。")
        if self.chat_model is None:
            return self._base_result(
                "not_configured",
                "未配置 ZHIPU_API_KEY，报告使用规则型建议。",
            )
        if not anomalies:
            return self._base_result("skipped", "本日没有异常商品，无需调用大模型。")

        selected_anomalies = anomalies[: self.settings.llm.max_anomalies]
        payloads = [self._anomaly_payload(item) for item in selected_anomalies]
        queries = [self._query_for(item) for item in selected_anomalies]

        try:
            retrieved = self.retriever.retrieve_many(queries, date_before=stat_date)
        except Exception as exc:  # RAG 失败不影响生成
            self.logger.warning("RAG 检索失败，将不使用检索上下文: %s", exc)
            retrieved = [[] for _ in queries]

        chunks, refs = self._combine_retrieval(selected_anomalies, retrieved)
        for payload in payloads:
            payload["retrieved_refs"] = refs.get(str(payload.get("product_id", "")), [])

        retrieval_info = self._retrieval_info()
        retrieval_info["selected_count"] = len(chunks)
        retrieval_info["chunks"] = [
            {
                "id": chunk["id"],
                "source": chunk["source"],
                "title": chunk["title"],
                "date": chunk["date"],
                "score": chunk["score"],
                "preview": str(chunk["text"])[:300],
            }
            for chunk in chunks
        ]
        if not bool(getattr(self.retriever, "available", False)):
            retrieval_info["error"] = retrieval_info.get("error") or "RAG 未启用或索引缺失"

        cache_payload = {
            "stat_date": stat_date,
            "model": self.settings.llm.model,
            "prompt_version": PROMPT_VERSION,
            "thinking": self.settings.llm.thinking,
            "anomalies": payloads,
            "chunks": [chunk["id"] for chunk in chunks],
        }
        cache_path = self._cache_path(stat_date, cache_payload)
        if self.settings.llm.cache_enabled and not force_refresh and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("status") == "ok":
                    cached["cached"] = True
                    cached["retrieval"] = retrieval_info
                    self.logger.info("AI 结果命中缓存: %s", cache_path)
                    return cached
            except Exception as exc:
                self.logger.warning("AI 缓存读取失败，将重新调用: %s", exc)

        user_prompt = build_user_prompt(
            stat_date=stat_date,
            anomalies=payloads,
            chunks=chunks,
            max_context_chars=self.settings.rag.max_context_chars,
        )
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        backoff = list(self.settings.llm.retry_backoff_seconds)
        last_error: Exception | None = None
        started = time.perf_counter()

        for attempt in range(1, self.settings.llm.max_attempts + 1):
            try:
                response = self.chat_model.invoke(messages)
                content = _message_content(response)
                parsed: AIAnalysis = parse_ai_json(content)
                products = self._validate_products(parsed, payloads, chunks)
                latency = round(time.perf_counter() - started, 2)
                result = self._base_result("ok")
                result.update(
                    {
                        "latency_seconds": latency,
                        "products": products,
                        "global_notes": parsed.global_notes,
                        "retrieval": retrieval_info,
                        "message": "AI 分析完成",
                    }
                )
                self.logger.info(
                    "AI 分析完成：模型 %s，商品 %d，检索块 %d，耗时 %.2fs",
                    self.settings.llm.model,
                    len(products),
                    len(chunks),
                    latency,
                )
                if self.settings.llm.cache_enabled:
                    try:
                        ensure_dir(cache_path.parent)
                        write_text_atomic(
                            cache_path,
                            json.dumps(result, ensure_ascii=False, indent=2),
                        )
                    except Exception as exc:
                        self.logger.warning("AI 结果缓存写入失败: %s", exc)
                return result
            except Exception as exc:
                last_error = exc
                retryable = _is_retryable(exc)
                self.logger.warning(
                    "AI 调用失败（第 %d/%d 次）: %s: %s",
                    attempt,
                    self.settings.llm.max_attempts,
                    type(exc).__name__,
                    str(exc)[:300],
                )
                if not retryable or attempt >= self.settings.llm.max_attempts:
                    break
                wait = backoff[min(attempt - 1, len(backoff) - 1)] if backoff else 5
                self.logger.info("等待 %ss 后重试 AI 调用", wait)
                time.sleep(wait)

        error_text = f"{type(last_error).__name__}: {str(last_error)[:500]}" if last_error else "未知错误"
        result = self._base_result(
            "failed",
            "AI 分析失败，报告已回退到规则型建议；可稍后重跑。",
            error=error_text,
        )
        result["retrieval"] = retrieval_info
        self.logger.warning("AI 分析最终失败：%s", error_text)
        return result

    def _consistency_warnings(
        self,
        data: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[str]:
        """用确定性方向字段检查模型结论是否自相矛盾。"""
        warnings: list[str] = []
        pieces: list[str] = [str(data.get("summary", ""))]
        for cause in data.get("possible_causes", []) or []:
            pieces.append(str(cause.get("cause", "")))
            pieces.extend(str(item) for item in cause.get("evidence", []) or [])
        text = " ".join(pieces)

        if payload.get("stock_status") == "in_stock":
            if any(keyword in text for keyword in ("售罄", "缺货", "无库存", "库存不足", "库存紧张")):
                warnings.append("数据为有库存，但 AI 声称售罄/缺货/库存不足")

        pv_direction = payload.get("pv_direction")
        pv_up_words = ("浏览量上涨", "浏览量高于基线", "浏览上涨")
        pv_down_words = ("浏览量下降", "浏览量低于基线", "浏览下降")
        if pv_direction == "up" and any(
            keyword in text for keyword in pv_down_words + ("流量下滑", "流量下降")
        ):
            warnings.append("数据为浏览量高于基线，但 AI 声称浏览量/流量下降")
        if pv_direction == "down" and any(keyword in text for keyword in pv_up_words):
            warnings.append("数据为浏览量低于基线，但 AI 声称浏览量上涨/高于基线")
        if pv_direction == "flat" and any(
            keyword in text for keyword in pv_up_words + pv_down_words + ("流量下滑", "流量下降", "流量上涨")
        ):
            warnings.append("数据为浏览量相对基线基本持平，但 AI 声称明显上涨/下降")

        orders_direction = payload.get("orders_direction")
        orders_up_words = ("订单量上涨", "订单上涨", "订单量高于基线")
        orders_down_words = ("订单量下降", "订单下降", "订单量低于基线")
        if orders_direction == "up" and any(keyword in text for keyword in orders_down_words):
            warnings.append("数据为订单量高于基线，但 AI 声称订单下降")
        if orders_direction == "down" and any(keyword in text for keyword in orders_up_words):
            warnings.append("数据为订单量低于基线，但 AI 声称订单上涨")
        if orders_direction == "flat" and any(
            keyword in text for keyword in orders_up_words + orders_down_words
        ):
            warnings.append("数据为订单量相对基线基本持平，但 AI 声称明显上涨/下降")

        cr_direction = payload.get("cr_direction")
        if cr_direction == "flat" and (
            "转化率下降" in text or "转化率上涨" in text
        ):
            warnings.append("数据为转化率相对基线基本持平，但 AI 声称明显上涨/下降")

        direction_values = {
            "pv_direction": ("up", "down", "flat"),
            "orders_direction": ("up", "down", "flat"),
            "cr_direction": ("up", "down", "flat"),
            "stock_status": ("in_stock", "out_of_stock"),
        }
        for field, values in direction_values.items():
            expected = payload.get(field)
            if not expected or expected == "unknown":
                continue
            for value in values:
                if value != expected and f"{field}: {value}" in text:
                    warnings.append(
                        f"AI 引用的 {field}={value} 与程序计算的 {expected} 不一致"
                    )

        age = payload.get("product_age_days")
        if isinstance(age, (int, float)) and age > 1 and "首日" in text:
            warnings.append(f"商品已是第 {int(age)} 天，但 AI 称为首日")
        return warnings

    def _validate_products(
        self,
        parsed: AIAnalysis,
        payloads: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        input_ids = {str(item.get("product_id", "")) for item in payloads}
        payload_by_id = {str(item.get("product_id", "")): item for item in payloads}
        valid_sources = {str(chunk.get("id", "")) for chunk in chunks}
        products: dict[str, Any] = {}
        for product in parsed.products:
            product_id = str(product.product_id)
            if product_id not in input_ids:
                continue
            data = product.model_dump()
            data["sources"] = [
                source for source in data.get("sources", []) if str(source) in valid_sources
            ]
            data["consistency_warnings"] = self._consistency_warnings(
                data, payload_by_id.get(product_id, {})
            )
            if data["consistency_warnings"]:
                self.logger.warning(
                    "AI 结论与数据方向不一致（%s）：%s",
                    product_id,
                    "；".join(data["consistency_warnings"]),
                )
            products[product_id] = data
        if not products:
            raise AISchemaError("模型未返回任何输入商品的分析")
        return products
