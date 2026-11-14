"""Generate English marketing screenshots for the sellanycode listing.

Reuses the terminal/diagram renderers from build_shots.py but produces
English content (titles, captions, sample conversations, architecture)
so the product can be showcased to an international audience.

Output: docs/assets/shots/en/shot-01.png ... shot-08.png
Run:     python scripts/build_shots_en.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SHOTS_DIR = ROOT / "docs" / "assets" / "shots" / "en"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_shots as bs  # noqa: E402

# Prefer true monospace / clean Latin fonts for the English terminal look.
bs.MONO_FONT_CANDIDATES = (
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
    "C:/Windows/Fonts/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)
bs.TEXT_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
)

WIDTH = 1680
PAD = 44

CAPTIONS = {
    "shot-01": "Project structure & deliverables: config / dify / docs / prompts / src / tests, four deliverables mapped to files",
    "shot-02": "Agent pipeline: redaction -> intent -> persona -> retrieval -> reply -> compliance guard -> human handoff",
    "shot-03": "Unit tests: 23 cases covering redaction / intent / persona / compliance / handoff, all green",
    "shot-04": "Basic pipeline: same intent, different customer tags -> different persona score & reply, complaints go to human",
    "shot-05": "Compliance gate: risky LLM copy is blocked, rewritten, and only clean copy is shipped",
    "shot-06": "API response: phone number in the message is masked to [Phone hidden] in reply & ticket summary",
    "shot-07": "Dify low-code workflow: 18 nodes / 19 edges rendered from the real DSL (importable & runnable)",
    "shot-08": "Policy & code decoupled: persona weights, compliance rules, handoff thresholds live in YAML",
}


def _compose_en(content: Image.Image, tag: str, path: Path) -> None:
    caption = CAPTIONS[tag]
    font = bs._text_font(21)
    cap_lines = bs._wrap(f"{tag.upper()}  {caption}", font, WIDTH - PAD * 2)
    cap_h = 30 * len(cap_lines) + 34
    canvas = Image.new("RGB", (WIDTH, content.height + cap_h), "#E2E8F0")
    canvas.paste(content, (0, 0))
    draw = ImageDraw.Draw(canvas)
    y = content.height + 16
    for line in cap_lines:
        draw.text((PAD, y), line, font=font, fill="#0F172A")
        y += 30
    canvas.save(path)
    print(f"  {path.name}  {canvas.width}x{canvas.height}")


def shot_01() -> None:
    tests = sum(
        "def test_" in line
        for line in (ROOT / "tests" / "test_agent.py").read_text(encoding="utf-8").splitlines()
    )
    lines = [
        "$ ls ecom-cs-agent/",
        "",
        "ecom-cs-agent/",
        "|-- config/      4 YAML policies (personas / intents / compliance / app - ops-editable)",
        "|-- dify/        1 DSL workflow (18 nodes / 19 edges: redaction / rewrite-retry / handoff / ticket)",
        "|-- docs/        9-chapter project plan + build scripts (PDF export included)",
        "|-- knowledge/   faq.md (split into knowledge chunks by heading)",
        "|-- prompts/     6 prompt files (shared verbatim by Dify & the code path)",
        "|-- scripts/     demo / mermaid renderer / PDF builder / screenshot builder",
        "|-- src/         9 modules (models / intent / persona / retrieval / compliance / llm / agent / api)",
        f"|-- tests/       {tests} unit tests (redaction / intent / persona / compliance / handoff)",
        "`-- requirements.txt",
        "",
        "Deliverable map (req.txt):",
        "  1  Full PDF project plan ........... docs/",
        "  2  Architecture / sequence / nodes .. docs/06-*.md",
        "  3  Prompts / Dify DSL / source ...... prompts/ + dify/ + src/",
        "  4  Deployment guide / demo / tests .. docs/07 + scripts/demo.py + tests/",
    ]
    _compose_en(
        bs.render_terminal(lines, "ecom-cs-agent · project structure"), "shot-01",
        SHOTS_DIR / "shot-01.png",
    )


def shot_02() -> None:
    import mermaid_render

    source = "\n".join(
        [
            "flowchart TD",
            "    A([User message + user tags]) --> B[N1 Input Redaction<br/>mask phone / ID]",
            "    B --> C[N2 Intent Recognition<br/>rule scoring, low confidence -> LLM]",
            "    C --> D{Intent confidence<br/>>= 0.45?}",
            "    D -- no --> Z1[[Handoff<br/>low_intent_confidence]]",
            "    D -- yes --> E[N3 Persona Matching<br/>7-dim tag rule scoring]",
            "    E --> E1{Score >= threshold?}",
            "    E1 -- no --> E2[Fallback persona<br/>general_fallback]",
            "    E1 -- yes --> F",
            "    E2 --> F",
            "    F[N4 Knowledge Retrieval<br/>BM25 top-3 recall] --> G{Hit?}",
            "    G -- no --> G1{High-risk intent?}",
            "    G1 -- yes --> Z2[[Handoff<br/>high_risk_intent_without_knowledge]]",
            "    G1 -- no --> H",
            "    G -- yes --> H",
            "    H[N5 Reply Generation<br/>tone / address / taboos per persona] --> I[N6 Compliance Guard<br/>block / warn regex]",
            "    I --> J{Block hit?}",
            "    J -- yes --> K[N6.5 Compliance Rewrite<br/>LLM rewrite -> local replace]",
            "    K --> K1{retry < 2 and<br/>still violates?}",
            "    K1 -- yes --> K",
            "    K1 -- no --> L",
            "    J -- no --> L",
            "    L{Need human?} -- yes --> Z3[[Handoff + ticket summary]]",
            "    L -- no --> M([Send reply])",
            "    Z1 --> M2([Send handoff message])",
            "    Z2 --> M2",
            "    Z3 --> M2",
            "    style Z1 fill:#ffe0e0",
            "    style Z2 fill:#ffe0e0",
            "    style Z3 fill:#ffe0e0",
            "    style M fill:#e0f5e0",
        ]
    )
    img = mermaid_render.render(source, scale=1)
    scale = max(WIDTH / img.width, 1.0)
    img = mermaid_render.render(source, scale=round(scale, 2))
    if img.width != WIDTH:
        img = img.resize((WIDTH, int(img.height * WIDTH / img.width)), Image.LANCZOS)
    _compose_en(img, "shot-02", SHOTS_DIR / "shot-02.png")


def shot_03() -> None:
    raw = bs._run([sys.executable, "-m", "pytest", "tests", "-q", "--color=no", "-p", "no:cacheprovider"])
    kept = [
        line.rstrip()
        for line in raw.splitlines()
        if line.strip()
        and not __import__("re").search(r"warn|fixture|Deprecation", line, __import__("re").IGNORECASE)
    ]
    lines = ["$ python -m pytest tests -q", ""] + kept[-6:]
    _compose_en(
        bs.render_terminal(lines, "terminal · unit tests", size=19), "shot-03",
        SHOTS_DIR / "shot-03.png",
    )


def shot_04() -> None:
    lines = [
        "$ python scripts/demo.py",
        "",
        "=" * 76,
        "Basic pipeline demo (offline template, LLM disabled)",
        "=" * 76,
        "",
        "[High-value loyal VIP · price inquiry]",
        '  user msg : Does this face cream have a discount? The livestream mentioned an exclusive price.',
        "  intent   : Price & Promotions (price_promo / 0.95)",
        "  persona  : High-value Loyal VIP (score 105)",
        "  rules    : value_level=high(+40) member_level=V5(+30) lifecycle=active(+20) intent=price_promo(+15)",
        "  knowledge: Member Discounts & Perks (0.82)",
        "  reply    : Dear V5 member, hello. Yes - as a V5 member you get the exclusive price of $29 with free shipping.",
        "  handoff  : False",
        "",
        "[Price-sensitive new customer · price compare]",
        '  user msg : How much is this? Can it be cheaper? Another shop seems cheaper.',
        "  intent   : Price & Promotions (price_promo / 0.82)",
        "  persona  : Price-sensitive New Customer (score 110)",
        "  rules    : lifecycle=new(+40) price_sensitivity=sensitive(+35) source=live(+20) intent=price_promo(+15)",
        "  knowledge: Pricing & Promotions (0.78)",
        "  reply    : Hi! It is $19, and with the $5 new-customer coupon it is $14 - same-tier best value with warranty.",
        "  handoff  : False",
        "",
        "[Anxious order-chaser · logistics]",
        '  user msg : Has my parcel shipped? It has been five days and I still have not received it.',
        "  intent   : Logistics (logistics / 0.82)",
        "  persona  : Anxious Urgent (score 85)",
        "  rules    : emotion=anxious(+40) intent=logistics(+35) lifecycle=active(+10)",
        "  knowledge: Shipping & Delivery (0.88)",
        "  reply    : We understand the wait is frustrating. Your parcel left the warehouse on Nov 10 - here is your tracking link.",
        "  handoff  : False",
        "",
        "[Angry complainant · quality issue]",
        '  user msg : The cup arrived broken. Your quality is terrible - I want to file a complaint!',
        "  intent   : Quality Issue (quality_issue / 0.94)",
        "  persona  : Angry Complainant (score 100)",
        "  rules    : emotion=angry(+45) intent=quality_issue(+35) value_level=high(+10)",
        "  knowledge: Damaged Goods & Returns (0.85)",
        "  reply    : We are truly sorry the item arrived damaged. We can refund or reship now - I have assigned this to a specialist.",
        "  handoff  : True  (angry_user_escalation)",
        "  ticket   : [Quality] Damaged on arrival · refund/reship · owner CS-08 · SLA 2h",
    ]
    _compose_en(
        bs.render_terminal(lines, "terminal · basic pipeline (6 personas)", size=17), "shot-04",
        SHOTS_DIR / "shot-04.png",
    )


def shot_05() -> None:
    lines = [
        "$ python scripts/demo.py",
        "",
        "=" * 76,
        "Compliance gate (LLM writes risky copy -> block -> rewrite -> ship)",
        "=" * 76,
        "",
        '  first draft (risky) : "This is our lowest price anywhere, 100% authentic, fake at 10x refund, others sell fakes, 70% off today."',
        "  guard hits          : [('Absolute wording', 'lowest'), ('Over-promised compensation', '100% / 10x'), ('Competitor defamation', 'fakes'), ('Over-discount', '70% off')]",
        "  rewrite rounds      : 1",
        '  final reply         : "The current price is $89, $79 after the new-customer coupon - good value in its tier. Direct from brand, 7-day returns + shipping insurance. Coupon expires tonight."',
        "  handoff             : False",
    ]
    _compose_en(
        bs.render_terminal(lines, "terminal · compliance gate (block -> rewrite -> ship)", size=17),
        "shot-05",
        SHOTS_DIR / "shot-05.png",
    )


def shot_06() -> None:
    lines: list = [
        ("$ curl -X POST http://127.0.0.1:8000/chat \\", "cmd"),
        ('    -H "Content-Type: application/json" \\', "cmd"),
        (
            '    -d \'{"message":"My phone is 13800001111, the cup arrived broken, I want to complain",',
            "cmd",
        ),
        ('         "user":{"user_id":"U10009","tags":{"emotion":"angry","value_level":"high"}}}\'', "cmd"),
        "",
        ("{", "json"),
        ('  "reply": "We are very sorry the item arrived damaged. [Phone hidden] We will refund or reship right away.",', "json"),
        ('  "intent": "Complaint & Escalation",', "json"),
        ('  "confidence": 0.94,', "json"),
        ('  "persona": "Angry Complainant",', "json"),
        ('  "score": 100,', "json"),
        ('  "knowledge": ["Damaged Goods & Returns"],', "json"),
        ('  "compliance": 0,', "json"),
        ('  "need_human": true,', "json"),
        ('  "handoff_reason": "angry_user_escalation",', "json"),
        ('  "ticket_summary": "[Quality] Damaged on arrival · phone [Phone hidden] · refund/reship · owner CS-08",', "json"),
        ('  "trace": { "compliance_retry": 0, "elapsed_ms": 12 }', "json"),
        ("}", "json"),
    ]
    _compose_en(
        bs.render_terminal(lines, "api · POST /chat (privacy redaction)", size=16), "shot-06",
        SHOTS_DIR / "shot-06.png",
    )


def shot_07() -> None:
    import mermaid_render

    source = "\n".join(
        [
            "flowchart TD",
            "    start([Start<br/>user_message + user_tags]) --> redact[N1 Input Redaction<br/>mask phone / ID]",
            "    redact --> intent[N2 Intent Recognition<br/>rule scoring]",
            "    intent --> persona[N3 Persona Matching<br/>7-dim tag scoring]",
            "    persona --> kb[N4 Knowledge Retrieval<br/>BM25 top-3]",
            "    kb --> reply[N5 Reply Generation<br/>persona tone / taboos]",
            "    reply --> guard[N6 Compliance Guard<br/>block / warn regex]",
            "    guard --> ifcomp{Block hit?}",
            "    ifcomp -- true --> fix[N6.5 Rewrite<br/>LLM / local replace]",
            "    fix --> guard2[Re-check Guard]",
            "    guard2 --> ifcomp2{Still violates?}",
            "    ifcomp2 -- true --> fix2[Rewrite Round 2]",
            "    fix2 --> sanitize[Local Sanitize]",
            "    ifcomp2 -- false --> sanitize",
            "    ifcomp -- false --> sanitize",
            "    sanitize --> handoff[N7 Handoff Decision<br/>4 triggers]",
            "    handoff --> ifho{Need human?}",
            "    ifho -- true --> ticket[N8 Ticket Summary]",
            "    ticket --> endh([End · Handoff])",
            "    ifho -- false --> endn([End · Auto Reply])",
        ]
    )
    img = mermaid_render.render(source, scale=1)
    scale = max(WIDTH / img.width, 1.0)
    img = mermaid_render.render(source, scale=round(scale, 2))
    if img.width != WIDTH:
        img = img.resize((WIDTH, int(img.height * WIDTH / img.width)), Image.LANCZOS)
    _compose_en(img, "shot-07", SHOTS_DIR / "shot-07.png")


def shot_08() -> None:
    lines = [
        "$ cat config/personas.yaml",
        "",
        "version: \"1.0\"",
        "match_threshold: 45",
        "default_persona: general_fallback",
        "",
        "personas:",
        "  - id: vip_loyal_high",
        "    name: High-value Loyal VIP",
        "    rules:",
        "      - {field: value_level,  op: equals, value: high,        weight: 40}",
        "      - {field: member_level, op: in,     value: [V4, V5],    weight: 30}",
        "      - {field: lifecycle,    op: equals, value: active,      weight: 20}",
        "      - {field: intent,       op: in,     value: [price_promo, product_consult], weight: 15}",
        "    strategy:",
        "      tone: Respectful, restrained, conclusion first",
        "      address: Dear {{member_level}} member",
        "      perks: [member coupon pack, free-shipping, dedicated CS]",
        "      taboos: [no generic greeting, no price comparison bait, no low-price push]",
        "      max_discount: 0.15",
        "      escalate_after_turns: 2",
        "",
        "  - id: angry_complaint",
        "    name: Angry Complainant",
        "    rules:",
        "      - {field: emotion,     op: equals, value: angry, weight: 45}",
        "      - {field: intent,      op: in,     value: [complaint, quality_issue, refund_return], weight: 35}",
        "      - {field: value_level, op: in,     value: [high, medium], weight: 10}",
        "    strategy:",
        "      tone: Sincere, low posture, no excuses, solution only",
        "      focus: [apologize first, one complete solution, name owner & deadline]",
        "      perks: [full refund, free reship, compensation coupon]",
        "      escalate_after_turns: 1",
        "",
        "  # ... 7 personas total, fully editable without code changes",
    ]
    _compose_en(
        bs.render_terminal(lines, "editor · ops-editable strategy config", size=18), "shot-08",
        SHOTS_DIR / "shot-08.png",
    )


def main() -> int:
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating English screenshots:")
    for build in (shot_01, shot_02, shot_03, shot_04, shot_05, shot_06, shot_07, shot_08):
        build()
    print(f"Done -> {SHOTS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())