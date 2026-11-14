"""节点 1：意图识别。

设计取舍：
- 默认走规则关键词匹配，零成本、可解释、可审计，满足 MVP 的 80% 场景；
- 规则置信度不足时（< guard.min_intent_confidence）才调用 LLM 兜底，
  避免每一单都付 LLM 的钱，也避免 LLM 抖动导致的话术不一致。
"""

from __future__ import annotations

from typing import Any

from .llm import LLMClient
from .models import IntentResult


class IntentClassifier:
    def __init__(self, cfg: dict[str, Any], llm: LLMClient | None = None) -> None:
        self.cfg = cfg["intents"]
        self.llm = llm
        self.confidence_base = float(self.cfg.get("confidence_base", 0.45))
        self.confidence_step = float(self.cfg.get("confidence_step", 0.12))
        self.confidence_cap = float(self.cfg.get("confidence_cap", 0.95))
        self.default_intent = self.cfg.get("default_intent", "other")
        self._by_id = {item["id"]: item for item in self.cfg["intents"]}

    def _score_rule(self, message: str) -> tuple[str, float, list[str]]:
        """按关键词命中数给每个意图打分，返回最高分意图。"""

        best_id = self.default_intent
        best_score = 0.0
        best_hits: list[str] = []

        for item in self.cfg["intents"]:
            # YAML 中形如 315 的关键词会被解析成数字，这里统一转成字符串再比对
            hits = [str(kw) for kw in item.get("keywords", []) if str(kw) in message]
            if not hits:
                continue
            # 长关键词更具体，按长度做轻微加权，避免"价"这类短词抢占
            score = sum(item.get("weight", 1.0) * (1 + 0.1 * (len(kw) - 2)) for kw in hits)
            if score > best_score:
                best_id, best_score, best_hits = item["id"], score, hits

        return best_id, best_score, best_hits

    def classify(self, message: str) -> IntentResult:
        intent_id, score, hits = self._score_rule(message)

        if score > 0:
            confidence = min(self.confidence_cap, self.confidence_base + self.confidence_step * score)
        else:
            confidence = self.confidence_base * 0.6

        result = IntentResult(
            intent=intent_id,
            intent_name=self._by_id.get(intent_id, {}).get("name", intent_id),
            confidence=round(confidence, 3),
            matched_keywords=hits,
            source="rule",
        )

        # 规则拿不准时才升级到 LLM 判定，控制成本
        if confidence < 0.6 and self.llm is not None and self.llm.available:
            llm_result = self._classify_by_llm(message)
            if llm_result is not None:
                return llm_result

        return result

    def _classify_by_llm(self, message: str) -> IntentResult | None:
        """LLM 兜底分类，要求模型只输出意图 id，降低解析难度。"""

        assert self.llm is not None
        options = "\n".join(f"- {item['id']}: {item['name']}" for item in self.cfg["intents"])
        system = (
            "你是电商客服意图分类器。只能从给定意图列表中选择一个最匹配的 id，"
            "只输出 id 本身，不要输出任何解释、标点或多余文字。\n"
            f"意图列表：\n{options}"
        )
        raw = self.llm.chat(system=system, user=message, temperature=0.0)
        if not raw:
            return None
        candidate = raw.strip().strip("`\"'。.").lower()
        if candidate not in self._by_id:
            return None
        return IntentResult(
            intent=candidate,
            intent_name=self._by_id[candidate]["name"],
            confidence=0.6,
            matched_keywords=[],
            source="llm",
        )