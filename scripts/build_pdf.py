"""把 docs/ 下的 Markdown 方案文档合并生成一份 PDF（交付物 D1）。

运行：python scripts/build_pdf.py
输出：docs/项目方案.pdf

实现说明：
- 使用 reportlab 内置的 STSong-Light（CID 中文字体），无需额外字体文件；
- 做轻量 Markdown 解析（标题 / 列表 / 表格 / 代码块 / Mermaid 图），保证 PDF 可读；
- Mermaid 图由 scripts/mermaid_render.py 用 Pillow 渲染成 PNG 后嵌入，
  渲染失败时自动回退为代码块，不会中断 PDF 生成；
- 刻意不引入 pandoc 等外部工具，保证交付方任何机器都能一键生成。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image as RLImage,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
ASSETS_DIR = DOCS_DIR / "assets"
OUTPUT = DOCS_DIR / "项目方案.pdf"

DOC_ORDER = [
    ("00-项目总控评审纪要.md", "第一章  项目总控评审纪要"),
    ("01-需求调研报告.md", "第二章  需求调研报告"),
    ("02-产品方案.md", "第三章  产品方案"),
    ("03-技术方案.md", "第四章  技术方案"),
    ("04-营销方案.md", "第五章  市场营销方案"),
    ("05-质量保障方案.md", "第六章  质量保障方案"),
    ("06b-提示词库.md", "第七章  提示词库"),
    ("06-Agent节点拆解与架构时序.md", "第八章  Agent 节点拆解与架构时序"),
    ("07-本地部署与演示教程.md", "第九章  本地部署与演示教程"),
]

FONT = "STSong-Light"


def register_font() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title", fontName=FONT, fontSize=30, leading=40,
            alignment=TA_CENTER, textColor=colors.HexColor("#1E3A8A"), spaceAfter=14,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontName=FONT, fontSize=14, leading=24,
            alignment=TA_CENTER, textColor=colors.HexColor("#475569"),
        ),
        "h1": ParagraphStyle(
            "h1", fontName=FONT, fontSize=19, leading=28,
            textColor=colors.HexColor("#1E3A8A"), spaceBefore=16, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2", fontName=FONT, fontSize=14, leading=22,
            textColor=colors.HexColor("#0F766E"), spaceBefore=12, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", fontName=FONT, fontSize=12, leading=18,
            textColor=colors.HexColor("#334155"), spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", fontName=FONT, fontSize=10, leading=17,
            textColor=colors.HexColor("#111827"), spaceAfter=4,
        ),
        "quote": ParagraphStyle(
            "quote", fontName=FONT, fontSize=10, leading=17,
            textColor=colors.HexColor("#64748B"), leftIndent=10, spaceAfter=6,
        ),
        "code": ParagraphStyle(
            "code", fontName=FONT, fontSize=8.5, leading=12.5,
            textColor=colors.HexColor("#1F2937"), backColor=colors.HexColor("#F8FAFC"),
            leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "caption", fontName=FONT, fontSize=9, leading=14,
            alignment=TA_CENTER, textColor=colors.HexColor("#475569"),
            spaceBefore=4, spaceAfter=8,
        ),
        # 目录标题与条目：刻意不用 h1 样式名，避免被识别成章节标题计入页码
        "toc_title": ParagraphStyle(
            "toc_title", fontName=FONT, fontSize=20, leading=30,
            textColor=colors.HexColor("#1E3A8A"), spaceBefore=6, spaceAfter=14,
        ),
        "toc_item": ParagraphStyle(
            "toc_item", fontName=FONT, fontSize=11, leading=22,
            textColor=colors.HexColor("#111827"),
        ),
        "toc_page": ParagraphStyle(
            "toc_page", fontName=FONT, fontSize=11, leading=22,
            alignment=TA_RIGHT, textColor=colors.HexColor("#111827"),
        ),
    }


INLINE_RE = [
    (re.compile(r"`([^`]+)`"), r"<font color='#B91C1C'>\1</font>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<b>\1</b>"),
]


def clean_inline(text: str) -> str:
    """把 Markdown 行内语法转成 reportlab 支持的标签。"""

    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for pattern, repl in INLINE_RE:
        text = pattern.sub(repl, text)
    text = text.replace("✅", "是").replace("❌", "否")
    text = re.sub(r"[🔴🟠🟡🟢🟣]", "•", text)
    return text.strip()


def render_table(rows: list[str], styles: dict[str, ParagraphStyle]) -> Table:
    """把 Markdown 表格转成 reportlab Table。"""

    cells: list[list[Paragraph]] = []
    for row in rows:
        if re.match(r"\s*\|[\s\-:|]+\|\s*$", row):
            continue
        parts = [c.strip() for c in row.strip().strip("|").split("|")]
        cells.append([Paragraph(clean_inline(c), styles["body"]) for c in parts])

    col_count = max(len(r) for r in cells)
    for row in cells:
        while len(row) < col_count:
            row.append(Paragraph("", styles["body"]))

    table = Table(cells, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def mermaid_figure(code: str, chapter_no: str, index: int, styles: dict[str, ParagraphStyle]) -> list:
    """把一段 Mermaid 源码渲染成 PNG 并包装成可嵌入 PDF 的 flowable 列表。

    宽高比超过 1.45 的图（横向流程图、多泳道时序图）自动切到横版页，
    避免整图被压进 A4 竖版后字号小到看不清。
    """

    try:
        import mermaid_render

        image = mermaid_render.render(code, scale=2)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        path = ASSETS_DIR / f"ch{chapter_no}-figure{index}.png"
        image.save(path)
    except Exception as exc:  # 降级：渲染失败不影响 PDF 生成
        print(f"[警告] Mermaid 渲染失败（第 {chapter_no} 章第 {index} 图），已回退为代码块：{exc}")
        return [Preformatted(code, styles["code"])]

    w_px, h_px = ImageReader(str(path)).getSize()
    # 宽高比大、或原始像素过宽（缩到竖版后字号会小于 5pt）时，切横版页
    wide = w_px / h_px > 1.45 or w_px > 2600
    avail_w, avail_h = (250 * mm, 158 * mm) if wide else (174 * mm, 205 * mm)
    ratio = min(avail_w / w_px, avail_h / h_px)

    flows: list = []
    if wide:
        flows.extend([NextPageTemplate("landscape"), PageBreak()])
    flows.extend(
        [
            Spacer(1, 4),
            RLImage(str(path), width=w_px * ratio, height=h_px * ratio),
            Paragraph(f"图 {chapter_no}-{index}  Mermaid 图（源码见对应 Markdown 文档）", styles["caption"]),
        ]
    )
    if wide:
        flows.extend([NextPageTemplate("portrait"), PageBreak()])
    return flows


def parse_markdown(text: str, styles: dict[str, ParagraphStyle], chapter_no: str = "") -> list:
    """极简 Markdown → Platypus flowables。"""

    flowables: list = []
    lines = text.splitlines()
    idx = 0
    table_buf: list[str] = []
    fig_count = 0

    def flush_table() -> None:
        nonlocal table_buf
        if len(table_buf) >= 2:
            flowables.append(render_table(table_buf, styles))
            flowables.append(Spacer(1, 6))
        table_buf = []

    while idx < len(lines):
        line = lines[idx].rstrip()

        # 代码块（含 Mermaid 图）
        if line.strip().startswith("```"):
            fence = line.strip().strip("`").strip().lower()
            flush_table()
            idx += 1
            code_lines: list[str] = []
            while idx < len(lines) and not lines[idx].strip().startswith("```"):
                code_lines.append(lines[idx].replace("\t", "    "))
                idx += 1
            idx += 1
            if fence == "mermaid" and code_lines:
                fig_count += 1
                flowables.extend(mermaid_figure("\n".join(code_lines), chapter_no, fig_count, styles))
            elif code_lines:
                flowables.append(Preformatted("\n".join(code_lines), styles["code"]))
            continue

        # 表格
        if line.strip().startswith("|"):
            table_buf.append(line)
            idx += 1
            continue
        flush_table()

        stripped = line.strip()
        if not stripped:
            idx += 1
            continue
        if stripped in ("---", "***", "___"):
            flowables.append(
                HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#CBD5E1"), spaceBefore=6, spaceAfter=8)
            )
        elif stripped.startswith(">"):
            flowables.append(Paragraph(clean_inline(stripped.lstrip("> ")), styles["quote"]))
        elif stripped.startswith("#### "):
            flowables.append(Paragraph(clean_inline(stripped[5:]), styles["h3"]))
        elif stripped.startswith("### "):
            flowables.append(Paragraph(clean_inline(stripped[4:]), styles["h3"]))
        elif stripped.startswith("## "):
            flowables.append(Paragraph(clean_inline(stripped[3:]), styles["h2"]))
        elif stripped.startswith("# "):
            flowables.append(Paragraph(clean_inline(stripped[2:]), styles["h1"]))
        elif re.match(r"^[-*+]\s+", stripped):
            flowables.append(Paragraph("• " + clean_inline(re.sub(r"^[-*+]\s+", "", stripped)), styles["body"]))
        elif re.match(r"^\d+\.\s+", stripped):
            flowables.append(Paragraph(clean_inline(stripped), styles["body"]))
        else:
            flowables.append(Paragraph(clean_inline(stripped), styles["body"]))
        idx += 1

    flush_table()
    return flowables


class NumberedCanvas(canvas.Canvas):
    """在所有页面上补「第 X 页 / 共 N 页」页码，需要攒齐总页数后统一回填。"""

    footer_text = "电商智能客服 Agent 项目方案"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._page_states: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 - reportlab 规定的方法名
        self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        if self._pageNumber <= 1:  # 封面不写页码
            return
        width, _ = self._pagesize
        self.saveState()
        self.setFont(FONT, 8)
        self.setFillColor(colors.HexColor("#94A3B8"))
        self.drawCentredString(width / 2, 9 * mm, f"第 {self._pageNumber} 页 / 共 {total} 页")
        self.drawRightString(width - 18 * mm, 9 * mm, self.footer_text)
        self.restoreState()


def _norm(text: str) -> str:
    """统一空白：reportlab 取纯文本时会把连续空格压成一个，目录键必须同口径比较。"""

    return " ".join(text.split())


class PlanDoc(BaseDocTemplate):
    """竖版正文 + 横版大图的双模板文档，同时记录各章节起始页码供目录使用。"""

    def __init__(self, filename: str, page_map: dict[str, int]) -> None:
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=16 * mm,
            title="电商智能客服 Agent 项目方案",
            author="项目组",
        )
        self.page_map = page_map
        pw, ph = A4
        lw, lh = landscape(A4)
        self.addPageTemplates(
            [
                PageTemplate(
                    id="portrait",
                    frames=[Frame(18 * mm, 16 * mm, pw - 36 * mm, ph - 34 * mm, id="p")],
                    pagesize=A4,
                ),
                PageTemplate(
                    id="landscape",
                    frames=[Frame(18 * mm, 16 * mm, lw - 36 * mm, lh - 34 * mm, id="l")],
                    pagesize=landscape(A4),
                ),
            ]
        )

    def afterFlowable(self, flowable) -> None:  # noqa: N802 - reportlab 规定的方法名
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            self.page_map.setdefault(_norm(flowable.getPlainText()), self.page)


def add_page_break(story: list) -> None:
    """避免连续两个 PageBreak 产生空白页。"""

    if story and isinstance(story[-1], PageBreak):
        return
    story.append(PageBreak())


def build_story(styles: dict[str, ParagraphStyle], page_map: dict[str, int]) -> list:
    story: list = []
    story.append(Spacer(1, 70 * mm))
    story.append(Paragraph("电商智能客服 Agent", styles["cover_title"]))
    story.append(Paragraph("项目方案文档", styles["cover_title"]))
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("按标签人群差异化应答 · 合规话术零下发", styles["cover_sub"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("技术路线：Dify 低代码 + 本地代码版（双交付）", styles["cover_sub"]))
    story.append(Paragraph("交付版本：V1.0", styles["cover_sub"]))
    add_page_break(story)

    story.append(Paragraph("目录", styles["toc_title"]))
    toc_rows = [
        [
            Paragraph(chapter, styles["toc_item"]),
            Paragraph(str(page_map.get(_norm(chapter), "—")), styles["toc_page"]),
        ]
        for _, chapter in DOC_ORDER
    ]
    toc = Table(toc_rows, colWidths=[140 * mm, 34 * mm])
    toc.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#CBD5E1")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(toc)
    add_page_break(story)

    missing: list[str] = []
    for pos, (filename, chapter) in enumerate(DOC_ORDER, start=1):
        path = DOCS_DIR / filename
        if not path.exists():
            missing.append(filename)
            continue
        story.append(Paragraph(chapter, styles["h1"]))
        story.append(Spacer(1, 4))
        story.extend(parse_markdown(path.read_text(encoding="utf-8"), styles, str(pos)))
        add_page_break(story)

    if missing:
        print(f"[警告] 以下文档缺失，已跳过：{', '.join(missing)}")
    return story


def main() -> int:
    register_font()
    styles = build_styles()

    # 第一遍：占位目录，只为采集各章节真实起始页码
    page_map: dict[str, int] = {}
    PlanDoc(str(OUTPUT), page_map).build(build_story(styles, page_map), canvasmaker=NumberedCanvas)

    # 第二遍：用真实页码回填目录（目录恒为 1 页，两次排版页码一致）
    PlanDoc(str(OUTPUT), page_map).build(build_story(styles, page_map), canvasmaker=NumberedCanvas)

    print(f"PDF 已生成：{OUTPUT}（共 {len(DOC_ORDER)} 章，目录页码已回填）")
    return 0


if __name__ == "__main__":
    sys.exit(main())