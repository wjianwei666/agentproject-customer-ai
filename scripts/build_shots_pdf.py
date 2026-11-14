"""把 8 张演示截图 + 教程第九章打包成独立《演示截图组.pdf》（交付物 D4）。

运行：python scripts/build_shots_pdf.py
输出：docs/演示截图组.pdf

实现说明：
- 复用 build_pdf.py 的字体注册、样式与 Markdown 解析，保证与项目方案.pdf 观感一致；
- 前段嵌入教程第九章「演示截图组」的完整说明文字（9.1~9.6），
  后段把 shot-01 ~ shot-08 每张图单独成页（图片自带图注，不重复标注）；
- 图片等比缩放到竖版 A4 可用区，超长图按高度适配，避免被压小到看不清。
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage, PageBreak, Paragraph, Spacer

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
SHOTS_DIR = DOCS_DIR / "assets" / "shots"
OUTPUT = DOCS_DIR / "演示截图组.pdf"

sys.path.insert(0, str(ROOT / "scripts"))
import build_pdf  # noqa: E402 - 复用字体注册 / 样式 / Markdown 解析

SHOT_TITLES = {
    "shot-01": "项目结构与交付清单",
    "shot-02": "PDF 方案文档目录页（页码已回填）",
    "shot-03": "单元测试（23 条全绿）",
    "shot-04": "基础链路（6 组画像对照）",
    "shot-05": "合规门禁（拦截 → 整改 → 下发）",
    "shot-06": "POST /chat 接口演示（含手机号脱敏）",
    "shot-07": "Dify 工作流等效图（18 节点 / 19 条边）",
    "shot-08": "personas.yaml 策略配置（策略与代码解耦）",
}

# 竖版正文 frame 可用区：174mm × 263mm，图片上方还需留标题行
AVAIL_W = 174 * mm
AVAIL_H = 245 * mm


def build() -> None:
    build_pdf.register_font()
    styles = build_pdf.build_styles()

    shot_title = ParagraphStyle(
        "shot_title", fontName=build_pdf.FONT, fontSize=14, leading=20,
        textColor=colors.HexColor("#1E3A8A"), spaceBefore=6, spaceAfter=10,
    )

    chapter_text = (DOCS_DIR / "07-本地部署与演示教程.md").read_text(encoding="utf-8")
    marker = "## 九、演示截图组"
    nine = (marker + chapter_text.split(marker, 1)[1]) if marker in chapter_text else chapter_text

    story: list = []
    story.append(Spacer(1, 70 * mm))
    story.append(Paragraph("演示截图组", styles["cover_title"]))
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("电商智能客服 Agent 项目 · 交付物 D4", styles["cover_sub"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("8 张真实产物截图 + 逐张图注，可脱离口头讲解单独阅读", styles["cover_sub"]))
    story.append(PageBreak())

    story.extend(build_pdf.parse_markdown(nine, styles, "09"))
    story.append(PageBreak())

    for index in range(1, 9):
        key = f"shot-{index:02d}"
        path = SHOTS_DIR / f"{key}.png"
        if not path.exists():
            print(f"[警告] 缺失 {path.name}，已跳过")
            continue
        story.append(Paragraph(f"图 {index}｜{SHOT_TITLES[key]}", shot_title))
        w_px, h_px = ImageReader(str(path)).getSize()
        ratio = min(AVAIL_W / w_px, AVAIL_H / h_px)
        story.append(RLImage(str(path), width=w_px * ratio, height=h_px * ratio))
        story.append(PageBreak())

    page_map: dict[str, int] = {}

    class ShotsCanvas(build_pdf.NumberedCanvas):
        footer_text = "演示截图组"

    build_pdf.PlanDoc(str(OUTPUT), page_map).build(story, canvasmaker=ShotsCanvas)
    print(f"演示截图组 PDF 已生成：{OUTPUT}")


if __name__ == "__main__":
    build()