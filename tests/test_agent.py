"""单元测试（标准库 unittest，无第三方测试依赖）。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import EcommerceCSAgent, redact  # noqa: E402
from src.compliance import ComplianceChecker  # noqa: E402
from src.config_loader import load_config  # noqa: E402
from src.intent import IntentClassifier  # noqa: E402
from src.llm import ScriptedLLM  # noqa: E402
from src.models import ChatRequest, UserProfile  # noqa: E402
from src.retrieval import KnowledgeRetriever, parse_markdown, tokenize  # noqa: E402
from src.tag_matcher import PersonaMatcher  # noqa: E402

CFG = load_config()


class TestRedact(unittest.TestCase):
    def test_mask_phone_and_idcard(self) -> None:
        text = redact("我的手机 13800001111，身份证 110101199001011234")
        self.assertNotIn("13800001111", text)
        self.assertNotIn("110101199001011234", text)
        self.assertIn("手机号已隐藏", text)
        self.assertIn("证件号已隐藏", text)


class TestIntent(unittest.TestCase):
    def setUp(self) -> None:
        self.clf = IntentClassifier(CFG, llm=None)

    def test_logistics_intent(self) -> None:
        result = self.clf.classify("快递发货了吗，几天能到")
        self.assertEqual(result.intent, "logistics")
        self.assertGreater(result.confidence, 0.6)

    def test_complaint_intent(self) -> None:
        result = self.clf.classify("我要投诉你们，客服态度太差了")
        self.assertEqual(result.intent, "complaint")

    def test_fallback_other(self) -> None:
        result = self.clf.classify("今天天气不错")
        self.assertEqual(result.intent, "other")
        self.assertLess(result.confidence, 0.6)


class TestPersonaMatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = PersonaMatcher(CFG)

    def test_vip_match(self) -> None:
        user = UserProfile(
            user_id="U1",
            tags={"value_level": "high", "member_level": "V5", "lifecycle": "active"},
        )
        result = self.matcher.match(user, "price_promo")
        self.assertEqual(result.persona_id, "vip_loyal_high")
        self.assertGreaterEqual(result.score, 45)

    def test_angry_match(self) -> None:
        user = UserProfile(user_id="U2", tags={"emotion": "angry", "value_level": "high"})
        result = self.matcher.match(user, "complaint")
        self.assertEqual(result.persona_id, "angry_complaint")

    def test_fallback_when_no_tags(self) -> None:
        user = UserProfile(user_id="U3", tags={})
        result = self.matcher.match(user, "other")
        self.assertEqual(result.persona_id, "general_fallback")

    def test_intent_participates_in_match(self) -> None:
        user = UserProfile(
            user_id="U4",
            tags={"price_sensitivity": "neutral", "service_pref": "self_service"},
        )
        result = self.matcher.match(user, "product_consult")
        self.assertEqual(result.persona_id, "rational_researcher")


class TestRetrieval(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = KnowledgeRetriever.from_markdown(CFG["app"], sorted((ROOT / "knowledge").glob("*.md")))

    def test_tokenize_mixed(self) -> None:
        tokens = tokenize("顺丰快递 SF123")
        self.assertIn("顺", tokens)
        self.assertIn("sf", tokens)

    def test_parse_markdown_chunks(self) -> None:
        chunks = parse_markdown("## 标题A\n内容A\n## 标题B\n内容B")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["title"], "标题A")

    def test_search_returns_refund_doc(self) -> None:
        hits = self.retriever.search("七天无理由退货怎么申请")
        self.assertTrue(hits)
        self.assertIn("退换货", hits[0].title)

    def test_search_invoice(self) -> None:
        hits = self.retriever.search("开发票抬头写公司税号")
        self.assertTrue(hits)
        self.assertIn("发票", hits[0].title)

    def test_empty_query(self) -> None:
        self.assertEqual(self.retriever.search(""), [])


class TestCompliance(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = ComplianceChecker(CFG["compliance"])

    def test_block_absolute_wording(self) -> None:
        issues = self.checker.check("我们是全网最低价")
        self.assertTrue(self.checker.has_blocking(issues))
        self.assertEqual(issues[0].rule_id, "absolute_wording")

    def test_block_compensation(self) -> None:
        issues = self.checker.check("假一赔十，放心买")
        self.assertTrue(self.checker.has_blocking(issues))

    def test_warn_vague_timeline(self) -> None:
        issues = self.checker.check("大概明天能到")
        self.assertFalse(self.checker.has_blocking(issues))
        self.assertEqual(issues[0].level, "warn")

    def test_clean_text(self) -> None:
        issues = self.checker.check("商品支持 7 天无理由退货，运费险已赠送。")
        self.assertEqual(issues, [])

    def test_sanitize(self) -> None:
        text = self.checker.sanitize("我们是全网最低价，100%正品，假一赔十")
        issues = self.checker.check(text)
        self.assertFalse(self.checker.has_blocking(issues))


class TestAgentEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = EcommerceCSAgent()

    def test_basic_reply(self) -> None:
        req = ChatRequest(
            message="快递几天能到",
            user=UserProfile(user_id="U9", tags={"emotion": "anxious"}),
        )
        resp = self.agent.handle(req)
        self.assertTrue(resp.reply)
        self.assertEqual(resp.intent.intent, "logistics")
        self.assertEqual(resp.persona.persona_id, "anxious_urgent")
        self.assertIn("elapsed_ms", resp.trace)

    def test_angry_user_goes_human(self) -> None:
        req = ChatRequest(
            message="杯子破损了，我要投诉",
            user=UserProfile(user_id="U10", tags={"emotion": "angry"}),
        )
        resp = self.agent.handle(req)
        self.assertTrue(resp.need_human)
        self.assertEqual(resp.handoff_reason, "angry_user_escalation")
        self.assertIsNotNone(resp.ticket_summary)

    def test_low_confidence_goes_human(self) -> None:
        req = ChatRequest(message="随便聊聊", user=UserProfile(user_id="U11", tags={}))
        resp = self.agent.handle(req)
        self.assertTrue(resp.need_human)
        self.assertEqual(resp.handoff_reason, "low_intent_confidence")

    def test_compliance_auto_revision(self) -> None:
        risky = "我们是全网最低价，100%正品，假一赔十。"
        safe = "亲，这款到手价 89 元，支持 7 天无理由退货，运费险已赠送。"
        agent = EcommerceCSAgent(llm=ScriptedLLM(responses=[risky, safe]))
        req = ChatRequest(
            message="这个多少钱，有没有优惠活动",
            user=UserProfile(user_id="U12", tags={"lifecycle": "new", "price_sensitivity": "sensitive"}),
        )
        resp = agent.handle(req)
        self.assertEqual(resp.reply, safe)
        self.assertEqual(resp.trace["compliance_retry"], 1)
        self.assertFalse(resp.need_human)

    def test_compliance_sanitize_last_resort(self) -> None:
        """LLM 反复整改失败时，走本地兜底替换，保证违规文案绝不下发。"""

        risky = "全网最低，假一赔十。"
        agent = EcommerceCSAgent(llm=ScriptedLLM(responses=[risky, risky, risky]))
        req = ChatRequest(
            message="这个多少钱，有没有优惠活动",
            user=UserProfile(user_id="U13", tags={}),
        )
        resp = agent.handle(req)
        self.assertEqual(resp.trace["compliance_retry"], 2)
        self.assertFalse(any(i.level == "block" for i in resp.compliance))
        self.assertNotIn("假一赔十", resp.reply)
        self.assertNotIn("全网最低", resp.reply)


if __name__ == "__main__":
    unittest.main()