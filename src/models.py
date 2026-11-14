"""全链路数据结构定义。

约定：所有在 Agent 各节点之间流转的数据都用这里的 Pydantic 模型承载，
保证 Dify 工作流与本地代码两条路线的输入输出字段完全对齐。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """用户画像入参。

    tags 为标签人群匹配的核心依据，字段名与 config/personas.yaml 中的 rule.field 一一对应。
    缺失标签是常态，匹配器会跳过缺失字段而不是报错。
    """

    user_id: str
    tags: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """一次客服请求。"""

    message: str
    user: UserProfile
    session_id: str | None = None
    channel: str | None = None


class IntentResult(BaseModel):
    """意图识别结果。"""

    intent: str
    intent_name: str
    confidence: float
    matched_keywords: list[str] = Field(default_factory=list)
    source: Literal["rule", "llm"] = "rule"


class PersonaMatch(BaseModel):
    """标签人群匹配结果。"""

    persona_id: str
    persona_name: str
    score: float
    matched_rules: list[str] = Field(default_factory=list)
    strategy: dict[str, Any] = Field(default_factory=dict)


class KnowledgeHit(BaseModel):
    """知识库召回片段。"""

    doc_id: str
    title: str
    content: str
    score: float


class ComplianceIssue(BaseModel):
    """合规质检问题项。"""

    rule_id: str
    rule_name: str
    level: Literal["block", "warn"]
    message: str
    hit: str


class ChatResponse(BaseModel):
    """Agent 最终输出。

    reply 为可直接下发给用户的文案；
    need_human 为 True 时前端应展示转人工入口，并把 trace 与工单摘要一起传给坐席。
    """

    reply: str
    intent: IntentResult
    persona: PersonaMatch
    knowledge: list[KnowledgeHit] = Field(default_factory=list)
    compliance: list[ComplianceIssue] = Field(default_factory=list)
    need_human: bool = False
    handoff_reason: str | None = None
    ticket_summary: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)