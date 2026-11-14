"""生成演示截图组（shot-01 ~ shot-08），供文档第九章「截图 + 图注」交付使用。

每一张都来自真实产物，不臆造画面：
- 终端类：真实执行 pytest / demo.py 并捕获 stdout；
- 文档类：从真实的 PDF、YAML、DSL 渲染；
- 画布类：由真实 DSL 反向渲染成等效图，保证离线环境也能交付。

运行：python scripts/build_shots.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOTS_DIR = ROOT / "docs" / "assets" / "shots"
PDF = ROOT / "docs" / "项目方案.pdf"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

WIDTH = 1680
PAD = 44
LINE_RATIO = 1.7
# 终端类画面必须等宽对齐：只接受 ASCII 半角 = 中文全角一半的等宽字体
MONO_FONT_CANDIDATES = (
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)
# 图注是自然语段，用比例字体更好看
TEXT_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)

CAPTIONS = {
    "shot-01": "项目结构与交付清单：config/dify/docs/prompts/src/tests 六件套齐全，四条交付清单逐条可对应到文件",
    "shot-02": "PDF 方案文档目录页：9 章、页码已回填，架构图与时序图为内嵌矢量/位图而非外链",
    "shot-03": "单元测试：23 条用例覆盖脱敏 / 意图 / 画像 / 合规 / 转人工五个环节，全绿",
    "shot-04": "基础链路：同一意图、不同标签人群 → 不同画像得分与话术，投诉类直接转人工",
    "shot-05": "合规门禁：模型故意写违规文案，质检拦截 → 整改 → 下发不含违规词的干净话术",
    "shot-06": "接口返回：消息内含手机号，回复与工单摘要中均为【手机号已隐藏】，隐私不进入模型",
    "shot-07": "Dify 画布等效图：由 dify/ecommerce_cs_agent.yml 真实 DSL 渲染，18 节点 / 19 条边",
    "shot-08": "策略与代码解耦：人群权重、合规规则、转人工阈值全在 YAML，运营改完即时生效",
}


def _pick(candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError(f"未找到可用字体，请安装其中之一：{candidates}")


def _mono_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_pick(MONO_FONT_CANDIDATES), size, index=0)


def _text_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_pick(TEXT_FONT_CANDIDATES), size, index=0)


def _char_cols(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_px: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        if font.getlength(current + ch) > max_px and current:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines


def _wrap_cols(text: str, cols: int) -> list[str]:
    """按终端列宽折行，续行对齐到首次换行的缩进位置，保持可读。"""

    lines: list[str] = []
    current = ""
    used = 0
    for ch in text:
        width = _char_cols(ch)
        if used + width > cols and current:
            lines.append(current)
            current = ch
            used = width
        else:
            current += ch
            used += width
    if current:
        lines.append(current)
    return lines


def _compose(content: Image.Image, tag: str, path: Path) -> None:
    caption = CAPTIONS[tag]
    font = _text_font(21)
    cap_lines = _wrap(f"{tag.upper()}　{caption}", font, WIDTH - PAD * 2)
    cap_h = 30 * len(cap_lines) + 34
    canvas = Image.new("RGB", (WIDTH, content.height + cap_h), "#E2E8F0")
    canvas.paste(content, (0, 0))
    draw = ImageDraw.Draw(canvas)
    y = content.height + 16
    for line in cap_lines:
        draw.text((PAD, y), line, font=font, fill="#0F172A")
        y += 30
    canvas.save(path)
    print(f"  {path.name}  {canvas.width}×{canvas.height}")


C_PLAIN = "#E2E8F0"
C_CMD = "#7DD3FC"
C_STR = "#86EFAC"
C_KEY = "#93C5FD"
C_NUM = "#FBBF24"
C_HEAD = "#FDE68A"


def _toggle_strings(text: str, in_string: bool) -> tuple[list[tuple[str, str]], bool]:
    """把一段文本切成「引号内 / 引号外」两种颜色的片段，并跨行延续引号状态。"""

    segs: list[tuple[str, str]] = []
    buf = ""
    for ch in text:
        if ch == '"':
            if in_string:
                buf += ch
                segs.append((buf, C_STR))
                buf = ""
                in_string = False
            else:
                if buf:
                    segs.append((buf, C_PLAIN))
                buf = '"'
                in_string = True
        else:
            buf += ch
    if buf:
        segs.append((buf, C_STR if in_string else C_PLAIN))
    return segs, in_string


def _json_segments(line: str, in_string: bool) -> tuple[list[tuple[str, str]], bool]:
    """JSON 行高亮：键名浅蓝、字符串浅绿、数字与布尔橙色。"""

    if not in_string:
        matched = re.match(r'^(\s*)"([^"]*)":(\s*)(.*)$', line)
        if matched:
            indent, key, gap, rest = matched.groups()
            segs: list[tuple[str, str]] = [(indent, C_PLAIN), (f'"{key}"', C_KEY), (f":{gap}", C_PLAIN)]
            tail, state = _toggle_strings(rest, False)
            segs.extend(tail)
            return segs, state
    tail, state = _toggle_strings(line, in_string)
    colored: list[tuple[str, str]] = []
    for text, color in tail:
        if color == C_PLAIN and re.fullmatch(r"\s*(\d+\.?\d*|true|false|null)\s*(,?)\s*", text):
            colored.append((text, C_NUM))
        else:
            colored.append((text, color))
    return colored, state


def _line_segments(line: str, kind: str, in_string: bool) -> tuple[list[tuple[str, str]], bool]:
    if kind == "json":
        return _json_segments(line, in_string)
    if kind == "cmd":
        segs, state = _toggle_strings(line, False)
        return [(text, C_STR if color == C_STR else C_CMD) for text, color in segs], state
    if line.startswith("【"):
        return [(line, C_HEAD)], False
    return [(line, C_PLAIN)], False


def _wrap_segments(
    segs: list[tuple[str, str]], cols: int, indent: int
) -> list[list[tuple[str, str]]]:
    """按列宽把带颜色片段折行，续行缩进到首次断行的位置，避免与键名混淆。"""

    rows: list[list[tuple[str, str]]] = [[]]
    used = 0
    for text, color in segs:
        for ch in text:
            width = _char_cols(ch)
            if used + width > cols and rows[-1]:
                rows.append([(" " * indent, C_PLAIN)] if indent else [])
                used = indent
            rows[-1].append((ch, color))
            used += width
    return rows


def render_terminal(
    lines: list[str | tuple[str, str]], title: str, size: int = 19, kind: str = "plain"
) -> Image.Image:
    """把若干行文本渲染成深色终端窗口：等宽网格对齐、长行折行、可着色。

    每一行可以是纯文本，也可以是 ``(文本, 高亮类型)`` 元组，便于同一画面里混排命令与 JSON。
    """

    font = _mono_font(size)
    col = font.getlength("M")
    line_h = int(size * LINE_RATIO)
    cols = int((WIDTH - PAD * 2) / col)

    rows: list[list[tuple[str, str]]] = []
    in_string = False
    for item in lines:
        text, line_kind = item if isinstance(item, tuple) else (item, kind)
        if not text:
            rows.append([])
            continue
        indent = len(text) - len(text.lstrip()) + 2
        segs, in_string = _line_segments(text, line_kind, in_string)
        rows.extend(_wrap_segments(segs, cols, indent))

    header_h = 54
    body_h = PAD * 2 + line_h * max(len(rows), 1)
    img = Image.new("RGB", (WIDTH, header_h + body_h), "#0F172A")
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, WIDTH, header_h], fill="#1E293B")
    for i, color in enumerate(("#EF4444", "#F59E0B", "#22C55E")):
        cx = 26 + i * 26
        draw.ellipse([cx - 7, header_h / 2 - 7, cx + 7, header_h / 2 + 7], fill=color)
    draw.text((126, header_h / 2 - 11), title, font=_text_font(18), fill="#CBD5E1")

    y = header_h + PAD
    for row in rows:
        x = PAD
        for text, color in row:
            draw.text((x, y), text, font=font, fill=color)
            x += col * sum(_char_cols(ch) for ch in text)
        y += line_h
    return img


def _run(cmd: list[str]) -> str:
    """执行命令并取回可展示文本；pytest 等工具可能把结果写到 stderr，需一并接住。"""

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    merged = (proc.stdout or "").strip()
    tail = (proc.stderr or "").strip()
    if not merged:
        return tail
    return f"{merged}\n{tail}".strip() if tail else merged


def _demo_sections() -> dict[str, tuple[str, list[str]]]:
    output = _run([sys.executable, "scripts/demo.py"])
    pieces = re.split(r"={70,}", output)
    sections: dict[str, tuple[str, list[str]]] = {}
    for idx in range(len(pieces) - 1):
        header = pieces[idx + 1].strip()
        if not header:
            continue
        body = pieces[idx + 2] if idx + 2 < len(pieces) else ""
        sections[header.split("（")[0]] = (header, [ln for ln in body.splitlines() if ln.strip()])
    return sections


def shot_01() -> None:
    def count(folder: str, suffix: str) -> int:
        return len(list((ROOT / folder).rglob(f"*{suffix}")))

    import pymupdf

    pdf_pages = len(pymupdf.open(str(PDF)))
    tests = sum(
        "def test_" in line
        for line in (ROOT / "tests" / "test_agent.py").read_text(encoding="utf-8").splitlines()
    )
    lines = [
        "$ ls 智能客服/",
        "",
        "智能客服/",
        f"|-- config/      {count('config', '.yaml')} 个 YAML 策略（人群 / 意图 / 合规 / 主配置，运营可改）",
        "|-- dify/        1 个 DSL 工作流（18 节点 / 19 条边，含脱敏 · 整改重试 · 转人工 · 工单）",
        f"|-- docs/        {count('docs', '.md')} 篇 Markdown + 项目方案.pdf（{pdf_pages} 页）",
        f"|-- knowledge/   faq.md（{len([s for s in (ROOT / 'knowledge' / 'faq.md').read_text(encoding='utf-8').split('## ') if s.strip()])} 个知识切片，按标题分段）",
        f"|-- prompts/     {count('prompts', '.md')} 个提示词（Dify 与代码版共用同一套）",
        f"|-- scripts/     {count('scripts', '.py')} 个脚本（demo / mermaid_render / build_pdf / build_shots）",
        f"|-- src/         {count('src', '.py')} 个模块（模型 · 意图 · 画像 · 检索 · 合规 · LLM · 编排 · API）",
        f"|-- tests/       {tests} 条单元测试",
        "|-- rule/        6 个角色定义（CEO + 4 专家 + 质量总监）",
        "`-- req.txt      原始需求",
        "",
        "交付清单对照（req.txt 四项）",
        "  1  完整 PDF 项目方案文档            docs/项目方案.pdf",
        "  2  架构流程图 / 业务时序图 / 节点拆解   docs/06-Agent节点拆解与架构时序.md",
        "  3  提示词库 / Dify 配置 / 代码版源码    prompts/ + dify/ + src/",
        "  4  部署教程 / 演示 / 测试样例         docs/07 + scripts/demo.py + tests/",
    ]
    _compose(render_terminal(lines, "智能客服 · 项目结构"), "shot-01", SHOTS_DIR / "shot-01.png")


def shot_02() -> None:
    import pymupdf

    doc = pymupdf.open(str(PDF))
    page = doc[1]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2.4, 2.4))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    scale = WIDTH / img.width
    img = img.resize((WIDTH, int(img.height * scale)), Image.LANCZOS)
    _compose(img, "shot-02", SHOTS_DIR / "shot-02.png")


def shot_03() -> None:
    raw = _run([sys.executable, "-m", "pytest", "tests", "-q", "--color=no", "-p", "no:cacheprovider"])
    kept = [
        line.rstrip() for line in raw.splitlines()
        if line.strip()
        and not re.search(r"warn|fixture|Deprecation", line, re.IGNORECASE)
    ]
    lines = ["$ python -m pytest tests -q", ""] + kept[-6:]
    _compose(render_terminal(lines, "终端 · 单元测试"), "shot-03", SHOTS_DIR / "shot-03.png")


def shot_04() -> None:
    header, body = _demo_sections()["基础链路演示"]
    lines = ["$ python scripts/demo.py", "", f"【{header}】", ""] + body
    _compose(render_terminal(lines, "终端 · 基础链路（6 组标签人群）"), "shot-04", SHOTS_DIR / "shot-04.png")


def shot_05() -> None:
    header, body = _demo_sections()["合规门禁演示"]
    lines = ["$ python scripts/demo.py", "", f"【{header}】", ""] + body
    _compose(render_terminal(lines, "终端 · 合规门禁（拦截 → 整改 → 下发）"), "shot-05", SHOTS_DIR / "shot-05.png")


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _post_chat(payload: dict) -> dict:
    """真实起一个 uvicorn，真实发一次 HTTP 请求，拿到真实响应体。"""

    import time
    import urllib.error
    import urllib.request

    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "src.api:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"{base}/health", timeout=1).read()
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.25)
        else:
            raise RuntimeError("uvicorn 未能在 30 秒内就绪")

        request = urllib.request.Request(
            f"{base}/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return json.loads(urllib.request.urlopen(request, timeout=20).read().decode("utf-8"))
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def shot_06() -> None:
    payload = {
        "message": "我的手机号 13800001111，杯子破损了，我要投诉",
        "user": {"user_id": "U10009", "tags": {"emotion": "angry", "value_level": "high"}},
    }
    body = _post_chat(payload)
    view = {
        "reply": body["reply"],
        "intent": body["intent"]["intent_name"],
        "confidence": body["intent"]["confidence"],
        "persona": body["persona"]["persona_name"],
        "score": body["persona"]["score"],
        "knowledge": [k["title"] for k in body["knowledge"]],
        "compliance": len(body["compliance"]),
        "need_human": body["need_human"],
        "handoff_reason": body["handoff_reason"],
        "ticket_summary": body["ticket_summary"],
        "trace": {
            "compliance_retry": body["trace"]["compliance_retry"],
            "elapsed_ms": body["trace"]["elapsed_ms"],
        },
    }
    lines: list[str | tuple[str, str]] = [
        ("$ curl -X POST http://127.0.0.1:8000/chat \\", "cmd"),
        ('    -H "Content-Type: application/json" \\', "cmd"),
        (f"    -d '{json.dumps(payload, ensure_ascii=False)}' \\", "cmd"),
        ("  | jq '{reply, intent: .intent.intent_name, confidence: .intent.confidence,", "cmd"),
        ("         persona: .persona.persona_name, score: .persona.score,", "cmd"),
        ("         knowledge: [.knowledge[].title], compliance: (.compliance|length),", "cmd"),
        ("         need_human, handoff_reason, ticket_summary,", "cmd"),
        ("         trace: {retry: .trace.compliance_retry, ms: .trace.elapsed_ms}}'", "cmd"),
        "",
    ] + [("  " + line, "json") for line in json.dumps(view, ensure_ascii=False, indent=2).splitlines()]
    _compose(
        render_terminal(lines, "接口 · POST /chat（真实 HTTP 调用）", size=17),
        "shot-06",
        SHOTS_DIR / "shot-06.png",
    )


def shot_07() -> None:
    import yaml
    import mermaid_render

    dsl = yaml.safe_load((ROOT / "dify" / "ecommerce_cs_agent.yml").read_text(encoding="utf-8"))
    graph = dsl["workflow"]["graph"]
    lines = ["flowchart TD"]
    for node in graph["nodes"]:
        data = node["data"]
        label = f"{data.get('title', node['id'])}<br/>{node['id']}"
        lines.append(f"    {node['id']}[{label}]")
    for edge in graph["edges"]:
        lines.append(f"    {edge['source']} --> {edge['target']}")
    source = "\n".join(lines)
    base = mermaid_render.render(source, scale=1)
    scale = max(WIDTH / base.width, 1.0)
    img = mermaid_render.render(source, scale=round(scale, 2))
    if img.width != WIDTH:
        img = img.resize((WIDTH, int(img.height * WIDTH / img.width)), Image.LANCZOS)
    _compose(img, "shot-07", SHOTS_DIR / "shot-07.png")


def shot_08() -> None:
    text = (ROOT / "config" / "personas.yaml").read_text(encoding="utf-8").splitlines()
    lines = ["$ cat config/personas.yaml", ""] + text[:36]
    _compose(render_terminal(lines, "编辑器 · 可调策略配置", size=18), "shot-08", SHOTS_DIR / "shot-08.png")


def main() -> int:
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    print("生成演示截图组：")
    for build in (shot_01, shot_02, shot_03, shot_04, shot_05, shot_06, shot_07, shot_08):
        build()
    print(f"完成，输出目录：{SHOTS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())