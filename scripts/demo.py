"""演示脚本：跑通 6 组典型标签人群 × 典型意图的完整链路。

运行：python scripts/demo.py
无需 API Key，默认使用离线模板生成，保证任何机器上都能复现。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import EcommerceCSAgent  # noqa: E402
from src.llm import ScriptedLLM  # noqa: E402
from src.models import ChatRequest, UserProfile  # noqa: E402

CASES: list[dict] = [
    {
        "name": "高价值VIP · 价格咨询",
        "user": {
            "user_id": "U10001",
            "tags": {"value_level": "high", "member_level": "V5", "lifecycle": "active"},
        },
        "message": "这款面霜有没有优惠，我看直播里说有专属价？",
    },
    {
        "name": "价格敏感新客 · 比价",
        "user": {
            "user_id": "U10002",
            "tags": {"lifecycle": "new", "price_sensitivity": "sensitive", "source": "live"},
        },
        "message": "这个多少钱？能不能再便宜点，别家好像更划算",
    },
    {
        "name": "焦虑催单型 · 物流",
        "user": {
            "user_id": "U10003",
            "tags": {"emotion": "anxious", "lifecycle": "active"},
        },
        "message": "我的快递发货了吗？都五天了还没收到，什么时候到啊",
    },
    {
        "name": "理性研究型 · 售前参数",
        "user": {
            "user_id": "U10004",
            "tags": {"price_sensitivity": "neutral", "service_pref": "self_service"},
        },
        "message": "这个空气炸锅的材质和参数能详细说下吗，适合几个人用",
    },
    {
        "name": "愤怒维权型 · 质量问题",
        "user": {
            "user_id": "U10005",
            "tags": {"emotion": "angry", "value_level": "high"},
        },
        "message": "收到的杯子是破损的，你们质量太差了，我要投诉！",
    },
    {
        "name": "沉默召回 · 发票",
        "user": {
            "user_id": "U10006",
            "tags": {"lifecycle": "silent"},
        },
        "message": "之前买的可以开发票吗，抬头是公司",
    },
]


def run_basic_demo() -> None:
    agent = EcommerceCSAgent()

    print("=" * 78)
    print("基础链路演示（离线模板生成，LLM 未启用）")
    print("=" * 78)

    for case in CASES:
        req = ChatRequest(message=case["message"], user=UserProfile(**case["user"]))
        resp = agent.handle(req)

        print(f"\n【{case['name']}】")
        print(f"  用户原话 : {case['message']}")
        print(f"  意图     : {resp.intent.intent_name} ({resp.intent.intent} / {resp.intent.confidence})")
        print(f"  画像     : {resp.persona.persona_name} (得分 {resp.persona.score})")
        print(f"  命中规则 : {', '.join(resp.persona.matched_rules) or '无（兜底）'}")
        print(f"  知识召回 : {[f'{h.title}({h.score})' for h in resp.knowledge]}")
        print(f"  回复     : {resp.reply}")
        print(f"  转人工   : {resp.need_human}  {resp.handoff_reason or ''}")
        if resp.ticket_summary:
            print(f"  工单摘要 : {resp.ticket_summary}")
        print(f"  耗时     : {resp.trace['elapsed_ms']} ms")


def run_compliance_demo() -> None:
    """演示合规门禁：让"LLM"故意生成一段违规文案，观察整改链路。"""

    print("\n" + "=" * 78)
    print("合规门禁演示（模拟 LLM 输出违规文案 → 质检拦截 → 整改 → 下发）")
    print("=" * 78)

    risky = (
        "亲，这款我们是全网最低价，100%正品假一赔十，别家都是假货，"
        "给你打三折，今天下单包赔。"
    )
    safe = (
        "亲，这款当前到手价 89 元，叠加新人立减后 79 元，属于同价位里性价比较高的选择。"
        "商品由品牌方直供，支持 7 天无理由退货和运费险，不满意可随时退。"
        "券今晚 24 点前有效，需要我帮您下单吗？"
    )

    llm = ScriptedLLM(responses=[risky, safe])
    agent = EcommerceCSAgent(llm=llm)

    req = ChatRequest(
        message="这个多少钱，有没有优惠",
        user=UserProfile(
            user_id="U10007",
            tags={"lifecycle": "new", "price_sensitivity": "sensitive", "source": "live"},
        ),
    )
    resp = agent.handle(req)

    print(f"\n  首次生成（违规）: {risky}")
    print(f"  质检命中        : {resp.trace.get('compliance_hits') or '无'}")
    print(f"  整改重试轮数    : {resp.trace.get('compliance_retry')}")
    print(f"  最终下发        : {resp.reply}")
    print(f"  转人工          : {resp.need_human}  {resp.handoff_reason or ''}")


def run_structured_output() -> None:
    """演示结构化输出，可直接对接前端/坐席工作台。"""

    print("\n" + "=" * 78)
    print("结构化输出示例（JSON，可直接对接前端）")
    print("=" * 78)

    agent = EcommerceCSAgent()
    req = ChatRequest(
        message="买的电饭煲坏了，能换货吗",
        user=UserProfile(user_id="U10008", tags={"lifecycle": "active", "value_level": "medium"}),
    )
    resp = agent.handle(req)
    print(json.dumps(resp.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_basic_demo()
    run_compliance_demo()
    run_structured_output()