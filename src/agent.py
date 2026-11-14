"""Agent 编排器：把 6 个节点串成一条可观测的链路。

链路：脱敏 → 意图识别 → 标签人群匹配 → 知识检索 → 话术生成 → 合规质检 → 转人工决策

设计取舍：
1. 单文件编排而非图框架（LangGraph/Dify），MVP 场景节点少、无循环依赖，
   直白的分步函数更容易被业务方理解和调试；
2. 每一步都写 trace，方便质检与运营复盘"为什么这个用户收到了这句话"；
3. 兜底优先：任何节点失败都不抛异常给用户，最差也落到转人工。
"""

from __future__ import annotations

import re
import time
from typing import Any

from .compliance import ComplianceChecker
from .config_loader import KNOWLEDGE_DIR, PromptLibrary, load_config
from .intent import IntentClassifier
from .llm import LLMClient
from .models import ChatRequest, ChatResponse, ComplianceIssue, IntentResult, KnowledgeHit, PersonaMatch
from .retrieval import KnowledgeRetriever
from .tag_matcher import PersonaMatcher

# 顺序很关键：必须先替换 18 位证件号，否则会被 11 位手机号规则截断
_IDCARD_RE = re.compile(r"\d{18}")
_PHONE_RE = re.compile(r"\d{11}")

_HANDOFF_REPLY = (
    "非常抱歉，这个问题需要由人工客服为您处理。已为您生成工单，"
    "专属客服将在 30 分钟内与您联系，您也可以直接点击下方「转人工」按钮。"
)


def redact(text: str) -> str:
    """入参脱敏：手机号与身份证号不进入后续链路，避免隐私落盘。"""

    text = _IDCARD_RE.sub("【证件号已隐藏】", text)
    text = _PHONE_RE.sub("【手机号已隐藏】", text)
    return text


class EcommerceCSAgent:
    def __init__(self, cfg: dict[str, Any] | None = None, llm: Any = None) -> None:
        self.cfg = cfg or load_config()
        self.llm = llm if llm is not None else LLMClient(self.cfg["app"])
        self.prompts = PromptLibrary()

        guard = self.cfg["app"].get("guard", {})
        self.min_intent_confidence = float(guard.get("min_intent_confidence", 0.45))
        self.handoff_intents = set(guard.get("handoff_intents", []))
        self.compliance_max_retry = int(guard.get("compliance_max_retry", 2))

        self.intent_clf = IntentClassifier(self.cfg, self.llm)
        self.matcher = PersonaMatcher(self.cfg)
        self.retriever = KnowledgeRetriever.from_markdown(
            self.cfg["app"], sorted(KNOWLEDGE_DIR.glob("*.md"))
        )
        self.compliance = ComplianceChecker(self.cfg["compliance"])

    # ------------------------------------------------------------------ 主流程

    def handle(self, req: ChatRequest) -> ChatResponse:
        trace: dict[str, Any] = {"steps": []}
        t0 = time.perf_counter()

        message = redact(req.message.strip())
        trace["steps"].append({"node": "redact", "input_len": len(req.message), "output_len": len(message)})

        intent = self.intent_clf.classify(message)
        trace["steps"].append(
            {"node": "intent", "value": intent.intent, "confidence": intent.confidence, "source": intent.source}
        )

        persona = self.matcher.match(req.user, intent.intent)
        trace["steps"].append(
            {"node": "persona", "value": persona.persona_id, "score": persona.score, "hits": persona.matched_rules}
        )

        hits = self.retriever.search(message)
        trace["steps"].append(
            {"node": "retrieval", "hits": [{"title": h.title, "score": h.score} for h in hits]}
        )

        reply, issues = self._generate_with_guard(req, message, intent, persona, hits, trace)

        need_human, reason = self._decide_handoff(intent, persona, hits, issues)
        if need_human and self.compliance.has_blocking(issues):
            # 兜底文案本身经过校验，绝不把违规内容下发给用户
            reply = _HANDOFF_REPLY

        ticket = self._ticket_summary(req, message, intent, persona, need_human, reason)
        trace["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        trace["compliance_retry"] = trace.get("compliance_retry", 0)

        return ChatResponse(
            reply=reply,
            intent=intent,
            persona=persona,
            knowledge=hits,
            compliance=issues,
            need_human=need_human,
            handoff_reason=reason,
            ticket_summary=ticket,
            trace=trace,
        )

    # ------------------------------------------------------------------ 生成

    def _generate_with_guard(
        self,
        req: ChatRequest,
        message: str,
        intent: IntentResult,
        persona: PersonaMatch,
        hits: list[KnowledgeHit],
        trace: dict[str, Any],
    ) -> tuple[str, list[ComplianceIssue]]:
        """生成 → 质检 → 整改 的闭环，最多重试 compliance_max_retry 轮。"""

        reply = self._generate(req, message, intent, persona, hits)
        issues = self.compliance.check(reply)
        trace["compliance_retry"] = 0
        trace["compliance_hits"] = [(i.rule_name, i.hit) for i in issues]

        while self.compliance.has_blocking(issues) and trace["compliance_retry"] < self.compliance_max_retry:
            trace["compliance_retry"] += 1
            reply = self._revise(reply, issues, persona)
            issues = self.compliance.check(reply)

        if self.compliance.has_blocking(issues):
            # 最后一层兜底：本地规则替换，保证文案能下发
            reply = self.compliance.sanitize(reply)
            issues = self.compliance.check(reply)

        return reply, issues

    def _generate(
        self,
        req: ChatRequest,
        message: str,
        intent: IntentResult,
        persona: PersonaMatch,
        hits: list[KnowledgeHit],
    ) -> str:
        if self.llm.available:
            reply = self._generate_by_llm(req, message, intent, persona, hits)
            if reply:
                return reply
        return self._generate_by_template(req, intent, persona, hits)

    def _generate_by_llm(
        self,
        req: ChatRequest,
        message: str,
        intent: IntentResult,
        persona: PersonaMatch,
        hits: list[KnowledgeHit],
    ) -> str | None:
        knowledge = "\n\n".join(f"【{h.title}】\n{h.content}" for h in hits) or "（无匹配知识，请勿编造事实）"
        system = self.prompts.render(
            "03-话术生成",
            persona_name=persona.persona_name,
            tone=persona.strategy.get("tone", ""),
            address=persona.strategy.get("address", "您"),
            focus="；".join(persona.strategy.get("focus", [])),
            perks="、".join(persona.strategy.get("perks", [])),
            taboos="；".join(persona.strategy.get("taboos", [])),
            closing=persona.strategy.get("closing", ""),
            max_discount=persona.strategy.get("max_discount", 0.05),
            intent_name=intent.intent_name,
            knowledge=knowledge,
        )
        user = self.prompts.render(
            "03-话术生成-用户输入",
            member_level=req.user.tags.get("member_level", "非会员"),
            lifecycle=req.user.tags.get("lifecycle", "未知"),
            message=message,
        )
        return self.llm.chat(system=system, user=user)

    def _generate_by_template(
        self,
        req: ChatRequest,
        intent: IntentResult,
        persona: PersonaMatch,
        hits: list[KnowledgeHit],
    ) -> str:
        """离线模板生成：没有 LLM 时的确定性兜底，保证演示与测试可跑。"""

        strategy = persona.strategy
        address = str(strategy.get("address", "您")).replace(
            "{{member_level}}", req.user.tags.get("member_level", "会员")
        )

        empathy = {
            "complaint": "非常抱歉给您带来了不好的体验，这是我们的问题。",
            "quality_issue": "非常抱歉商品出现问题，给您添麻烦了。",
            "logistics": "理解您等货着急的心情，我马上帮您确认。",
            "refund_return": "理解您的顾虑，退换流程很简单，我一步步告诉您。",
            "price_promo": "我帮您把能省的都算清楚。",
            "product_consult": "我按实际参数给您说清楚，方便您判断。",
            "invoice": "发票可以开，我把需要的材料和时效说明一下。",
            "order_query": "我帮您核对一下订单状态。",
        }.get(intent.intent, "")

        if not hits:
            core = "这个问题我需要核实后再给您准确答复，避免说错影响您决策。"
            action = "我已记录您的诉求，稍后会有专人与您确认具体细节。"
        else:
            top = hits[0]
            core = _first_sentences(top.content, 3)
            action = "如果需要，我可以继续帮您确认细节或直接为您安排处理。"

        closing_raw = str(strategy.get("closing", "")).strip()
        closing = "请问还有其他可以帮您的吗？" if not closing_raw or _is_instruction(closing_raw) else closing_raw
        greeting = "您好。" if address in ("您", "你") else f"{address}，您好。"
        parts = [greeting]
        if empathy:
            parts.append(empathy)
        parts.append(core)
        parts.append(action)
        parts.append(closing)
        return "".join(parts)

    def _revise(self, reply: str, issues: list[ComplianceIssue], persona: PersonaMatch) -> str:
        """合规整改：有 LLM 时让模型重写，没有则走本地替换。"""

        blocking = [i for i in issues if i.level == "block"]
        if not blocking:
            return reply

        if self.llm.available:
            system = self.prompts.render(
                "04-合规质检",
                persona_name=persona.persona_name,
                taboos="；".join(persona.strategy.get("taboos", [])),
                issues="；".join(f"{i.rule_name}：{i.message}（命中「{i.hit}」）" for i in blocking),
            )
            revised = self.llm.chat(system=system, user=reply, temperature=0.2)
            if revised:
                return revised

        return self.compliance.sanitize(reply)

    # ------------------------------------------------------------------ 决策

    def _decide_handoff(
        self,
        intent: IntentResult,
        persona: PersonaMatch,
        hits: list[KnowledgeHit],
        issues: list[ComplianceIssue],
    ) -> tuple[bool, str | None]:
        if self.compliance.has_blocking(issues):
            return True, "compliance_unresolved"

        if intent.confidence < self.min_intent_confidence:
            return True, "low_intent_confidence"

        if intent.intent in self.handoff_intents and not hits:
            return True, "high_risk_intent_without_knowledge"

        if persona.persona_id == "angry_complaint":
            return True, "angry_user_escalation"

        return False, None

    def _ticket_summary(
        self,
        req: ChatRequest,
        message: str,
        intent: IntentResult,
        persona: PersonaMatch,
        need_human: bool,
        reason: str | None,
    ) -> str | None:
        if not need_human:
            return None
        closing = str(persona.strategy.get("closing", ""))
        return (
            f"用户{req.user.user_id}｜画像：{persona.persona_name}({persona.score}分)"
            f"｜意图：{intent.intent_name}({intent.confidence})"
            f"｜转人工原因：{reason}"
            f"｜诉求原文：{message[:60]}"
            f"｜建议动作：{closing}"
        )


def _first_sentences(text: str, count: int) -> str:
    """取知识片段前若干句，避免把整段政策原文砸给用户。"""

    sentences = re.split(r"[。\n]", text)
    picked = [s.strip() for s in sentences if s.strip()][:count]
    return "。".join(picked) + "。"


# 画像策略里的 closing 是写给模型的「动作指令」，不是给用户看的文案；
# 命中这些前缀时改用通用礼貌收尾，避免把"给出工单号"这类指令直接下发。
_INSTRUCTION_PREFIXES = (
    "给出", "主动", "引导", "不要", "确认是否", "请人工", "提示", "设置", "提供", "留下", "优先",
)


def _is_instruction(text: str) -> bool:
    return any(text.startswith(prefix) for prefix in _INSTRUCTION_PREFIXES)