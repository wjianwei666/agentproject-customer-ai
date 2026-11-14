"""节点 2：标签人群匹配。

核心思路：把用户标签 + 当前意图组成一个"匹配空间"，用画像规则逐条打分，
得分最高且过阈值的画像胜出。这样做的三个好处：
1. 可解释：每个画像得分都能拆到具体命中的规则上，运营可复盘；
2. 可调参：运营改 YAML 里的权重就能调策略，不需要研发介入；
3. 有兜底：标签全缺失时回落 general_fallback，链路永不中断。
"""

from __future__ import annotations

from typing import Any

from .models import PersonaMatch, UserProfile


def _rule_hit(rule: dict[str, Any], fields: dict[str, str]) -> bool:
    field = rule.get("field")
    op = rule.get("op", "equals")
    expected = rule.get("value")
    actual = fields.get(field) if field else None

    if actual is None:
        # 标签缺失直接判不命中，不做推断，避免误伤
        return False

    if op == "equals":
        return str(actual) == str(expected)
    if op == "in":
        return str(actual) in [str(v) for v in expected]
    if op == "not_in":
        return str(actual) not in [str(v) for v in expected]
    if op == "contains_any":
        return any(str(v) in str(actual) for v in expected)
    if op == "gte":
        return _to_float(actual) >= _to_float(expected)
    if op == "lte":
        return _to_float(actual) <= _to_float(expected)
    return False


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class PersonaMatcher:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg["personas"]
        self.threshold = float(self.cfg.get("match_threshold", 45))
        self.default_id = self.cfg.get("default_persona", "general_fallback")
        self.personas = self.cfg["personas"]

    def match(self, user: UserProfile, intent_id: str) -> PersonaMatch:
        # 意图也参与画像匹配：同一个用户在咨询和投诉场景应走不同话术策略
        fields: dict[str, str] = {**user.tags, "intent": intent_id}
        for key, value in user.metrics.items():
            fields.setdefault(key, value)

        best: PersonaMatch | None = None
        for persona in self.personas:
            score = 0.0
            matched: list[str] = []
            for rule in persona.get("rules", []):
                if _rule_hit(rule, fields):
                    score += float(rule.get("weight", 0))
                    matched.append(f"{rule.get('field')}={fields.get(rule.get('field'))}")
            if score <= 0:
                continue
            if best is None or score > best.score:
                best = PersonaMatch(
                    persona_id=persona["id"],
                    persona_name=persona["name"],
                    score=round(score, 2),
                    matched_rules=matched,
                    strategy=persona.get("strategy", {}),
                )

        if best is not None and best.score >= self.threshold:
            return best

        return self._fallback(best.score if best else 0.0)

    def _fallback(self, best_score: float) -> PersonaMatch:
        persona = next((p for p in self.personas if p["id"] == self.default_id), None)
        if persona is None:
            return PersonaMatch(
                persona_id="general_fallback",
                persona_name="通用兜底人群",
                score=best_score,
                strategy={},
            )
        return PersonaMatch(
            persona_id=persona["id"],
            persona_name=persona["name"],
            score=round(best_score, 2),
            matched_rules=[],
            strategy=persona.get("strategy", {}),
        )