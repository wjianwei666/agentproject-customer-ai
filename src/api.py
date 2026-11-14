"""HTTP 接口层（FastAPI）。

启动：uvicorn src.api:app --host 127.0.0.1 --port 8000 --reload
文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .agent import EcommerceCSAgent
from .models import ChatRequest, ChatResponse

app = FastAPI(
    title="电商智能客服 Agent",
    version="1.0.0",
    description="意图识别 → 标签人群匹配 → 知识检索 → 话术生成 → 合规质检 → 转人工",
)

agent = EcommerceCSAgent()


class SearchRequest(BaseModel):
    query: str
    top_k: int | None = None


@app.get("/health")
def health() -> dict:
    """健康检查，同时暴露 LLM 是否就绪，方便运维判断是否在降级运行。"""

    return {
        "status": "ok",
        "llm_available": agent.llm.available,
        "personas": len(agent.matcher.personas),
        "knowledge_chunks": len(agent.retriever.chunks),
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """主链路：一次请求走完 6 个节点，返回结构化结果与 trace。"""

    return agent.handle(req)


@app.get("/personas")
def list_personas() -> dict:
    """画像库查询，供运营核对当前生效的策略。"""

    return {
        "threshold": agent.matcher.threshold,
        "default": agent.matcher.default_id,
        "items": [
            {"id": p["id"], "name": p["name"], "description": p.get("description", "")}
            for p in agent.matcher.personas
        ],
    }


@app.post("/knowledge/search")
def search_knowledge(req: SearchRequest) -> dict:
    """知识检索单测接口，方便运营排查"为什么没召回"。"""

    hits = agent.retriever.search(req.query, req.top_k)
    return {"query": req.query, "hits": [h.model_dump() for h in hits]}