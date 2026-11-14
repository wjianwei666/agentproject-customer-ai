"""把 Mermaid 图渲染为 PNG（纯 Python，零外部依赖）。

支持本项目文档实际用到的语法子集：

- ``flowchart TD/LR``：矩形 / 圆角(体育场) / 菱形 / 子程序 节点，
  带标签连线、``style X fill:#xxx`` 配色、``<br/>`` 换行；
- ``sequenceDiagram``：``participant``、``autonumber``、``->>`` / ``-->>``、
  ``alt/else/loop/opt`` 区块、自调用消息。

实现说明：
- 用 Pillow 绘制，中文走系统字体（微软雅黑 / 黑体 / 苹方 / Noto）；
- 布局自研：最长路径分层 + 重心排序 + 贝塞尔/正交混合路由；
- 只覆盖上述子集，遇到不认识的语法直接抛异常，
  由调用方（build_pdf）回退成代码块，绝不阻断 PDF 生成。

单独使用：
    python scripts/mermaid_render.py docs/06-Agent节点拆解与架构时序.md
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    (r"C:\Windows\Fonts\msyh.ttf", 0),
    (r"C:\Windows\Fonts\simhei.ttf", 0),
    (r"C:\Windows\Fonts\simsun.ttc", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]

BOLD_CANDIDATES = [
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),
    (r"C:\Windows\Fonts\simhei.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
]

PALETTE = {
    "node_fill": "#ECECFF",
    "node_stroke": "#9370DB",
    "text": "#333333",
    "edge": "#5A5A5A",
    "edge_label": "#444444",
    "lifeline": "#BFBFBF",
    "block_stroke": "#9E9E9E",
    "block_label": "#666666",
    "note_fill": "#FFF5AD",
    "note_stroke": "#B8B84A",
}

MARGIN = 28
LINE_RATIO = 1.5

_font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    for path, index in (BOLD_CANDIDATES if bold else FONT_CANDIDATES):
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size, index=index)
        except Exception:
            continue
        _font_cache[key] = font
        return font
    raise RuntimeError("找不到可用的中文字体，请安装微软雅黑 / 黑体 / Noto CJK 任一种")


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _split_label(raw: str) -> list[str]:
    text = re.sub(r"<br\s*/?>", "\n", raw)
    return [ln.strip() for ln in text.split("\n") if ln.strip()] or [""]


def _bezier(p0, p1, p2, p3, steps: int = 32) -> list[tuple[float, float]]:
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u ** 2 * t * p1[0] + 3 * u * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u ** 2 * t * p1[1] + 3 * u * t ** 2 * p2[1] + t ** 3 * p3[1]
        points.append((x, y))
    return points


def _unit(a, b) -> tuple[float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    dist = math.hypot(dx, dy) or 1.0
    return dx / dist, dy / dist


def _arrow_head(draw, tip, direction, color, length=9, half=4.6):
    dx, dy = direction
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    px, py = -dy, dx
    draw.polygon(
        [tip, (bx + px * half, by + py * half), (bx - px * half, by - py * half)],
        fill=color, outline=color,
    )


def _open_head(draw, tip, direction, color, length=9, half=4.6):
    dx, dy = direction
    bx, by = tip[0] - dx * length, tip[1] - dy * length
    px, py = -dy, dx
    draw.line([(bx + px * half, by + py * half), tip], fill=color, width=2)
    draw.line([(bx - px * half, by - py * half), tip], fill=color, width=2)


def _dashed(draw, p0, p1, color, width=1, dash=7, gap=5):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    dist = math.hypot(dx, dy)
    if dist == 0:
        return
    ux, uy = dx / dist, dy / dist
    pos = 0.0
    while pos < dist:
        end = min(pos + dash, dist)
        draw.line(
            [(p0[0] + ux * pos, p0[1] + uy * pos), (p0[0] + ux * end, p0[1] + uy * end)],
            fill=color, width=width,
        )
        pos = end + gap


def _label_box(draw, center, lines, font, color):
    line_h = font.size * LINE_RATIO
    w = max(_measure(draw, ln, font)[0] for ln in lines)
    h = line_h * len(lines)
    pad = 3
    draw.rectangle(
        [center[0] - w / 2 - pad, center[1] - h / 2 - pad, center[0] + w / 2 + pad, center[1] + h / 2 + pad],
        fill="white",
    )
    for i, ln in enumerate(lines):
        y = center[1] - h / 2 + line_h * i + line_h / 2
        draw.text((center[0], y), ln, font=font, fill=color, anchor="mm")


# ================================================================ flowchart

CONN_RE = re.compile(r"(--\s*[^>|]*?\s*-->|\-\->|\.\-\>|\-\-\-)")

NODE_TOKEN_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?:\s*(\[\[[^\]]*\]\]|\(\[[^\]]*\]\)|\(\([^)]*\)\)|\([^)]*\)|\{[^}]*\}|\[[^\]]*\]))?$"
)

SHAPE_KINDS = [
    ("[[", "subroutine", 2),
    ("([", "stadium", 2),
    ("((", "circle", 2),
    ("(", "stadium", 1),
    ("{", "diamond", 1),
    ("[", "rect", 1),
]


def _parse_node(token: str) -> tuple[str, str | None, str] | None:
    m = NODE_TOKEN_RE.match(token)
    if not m:
        return None
    nid, shape = m.group(1), m.group(2)
    if not shape:
        return nid, None, nid
    for prefix, kind, closing in SHAPE_KINDS:
        if shape.startswith(prefix):
            return nid, kind, shape[closing:-closing]
    return nid, "rect", shape[1:-1]


def _conn_label(conn: str) -> str:
    if conn.startswith("--") and conn.endswith("-->"):
        return conn[2:-3].strip().strip("|").strip()
    return ""


def parse_flowchart(source: str) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    styles: dict[str, str] = {}
    direction = "TD"

    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if line.startswith("flowchart") or line.startswith("graph"):
            parts = line.split()
            if len(parts) > 1:
                direction = parts[1].upper()
            continue
        if line.startswith("style "):
            m = re.match(r"style\s+([A-Za-z0-9_]+)\s+(.*)", line)
            if m:
                for pair in m.group(2).split(","):
                    k, _, v = pair.partition(":")
                    if k.strip() == "fill":
                        styles[m.group(1)] = v.strip()
            continue

        segments: list[tuple[str, str]] = []
        for idx, piece in enumerate(CONN_RE.split(line)):
            piece = piece.strip()
            if idx % 2 == 1:
                segments.append(("conn", piece))
                continue
            parsed = _parse_node(piece) if piece else None
            if not parsed:
                segments = []
                break
            nid, kind, label = parsed
            if nid not in nodes:
                nodes[nid] = {"id": nid, "kind": kind or "rect", "label": label}
            elif kind:
                nodes[nid]["kind"] = kind
                nodes[nid]["label"] = label
            segments.append(("node", nid))

        for idx in range(0, len(segments) - 2, 2):
            src, dst = segments[idx][1], segments[idx + 2][1]
            if src != dst:
                edges.append({"src": src, "dst": dst, "label": _conn_label(segments[idx + 1][1])})

    if not nodes:
        raise ValueError("flowchart 未解析到任何节点")
    return {"direction": direction, "nodes": nodes, "edges": edges, "styles": styles}


def _children(graph: dict, nid: str) -> list[str]:
    return [e["dst"] for e in graph["edges"] if e["src"] == nid and not e.get("back")]


def _mark_back_edges(graph: dict) -> None:
    adj: dict[str, list[str]] = {nid: [] for nid in graph["nodes"]}
    for edge in graph["edges"]:
        adj[edge["src"]].append(edge["dst"])

    edge_index = {}
    for idx, edge in enumerate(graph["edges"]):
        edge_index.setdefault((edge["src"], edge["dst"]), idx)
        edge["back"] = False

    state = {nid: 0 for nid in adj}
    for root in adj:
        if state[root] != 0:
            continue
        stack = [(root, iter(adj[root]))]
        state[root] = 1
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if state[nxt] == 1:
                    idx = edge_index.get((node, nxt))
                    if idx is not None:
                        graph["edges"][idx]["back"] = True
                elif state[nxt] == 0:
                    state[nxt] = 1
                    stack.append((nxt, iter(adj[nxt])))
                    advanced = True
                    break
            if not advanced:
                state[node] = 2
                stack.pop()


def _layering(graph: dict) -> dict[str, int]:
    nodes = graph["nodes"]
    indeg = {nid: 0 for nid in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for edge in graph["edges"]:
        if edge["back"]:
            continue
        adj[edge["src"]].append(edge["dst"])
        indeg[edge["dst"]] += 1

    layer = {nid: 0 for nid in nodes}
    queue = [nid for nid, deg in indeg.items() if deg == 0]
    while queue:
        node = queue.pop(0)
        for nxt in adj[node]:
            layer[nxt] = max(layer[nxt], layer[node] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return layer


def _order_layers(graph: dict, layer: dict[str, int]) -> list[list[str]]:
    count = max(layer.values()) + 1
    layers: list[list[str]] = [[] for _ in range(count)]
    for nid in graph["nodes"]:
        layers[layer[nid]].append(nid)

    parents: dict[str, list[str]] = {nid: [] for nid in graph["nodes"]}
    for edge in graph["edges"]:
        if not edge["back"]:
            parents[edge["dst"]].append(edge["src"])

    for _ in range(4):
        for idx in range(1, count):
            pos = {nid: i for i, nid in enumerate(layers[idx - 1])}
            layers[idx].sort(
                key=lambda nid: sum(pos.get(p, len(pos)) for p in parents[nid]) / max(len(parents[nid]), 1)
            )
        for idx in range(count - 2, -1, -1):
            pos = {nid: i for i, nid in enumerate(layers[idx + 1])}
            layers[idx].sort(
                key=lambda nid: (
                    sum(pos.get(c, len(pos)) for c in _children(graph, nid))
                    / max(len(_children(graph, nid)), 1)
                )
            )
    return layers


def _draw_node(draw, node, scale):
    x, y = node["cx"], node["cy"]
    w, h = node["w"], node["h"]
    stroke = PALETTE["node_stroke"]
    fill = node["fill"]
    lw = 2

    if node["kind"] == "diamond":
        draw.polygon(
            [(x, y - h / 2), (x + w / 2, y), (x, y + h / 2), (x - w / 2, y)],
            fill=fill, outline=stroke, width=lw,
        )
    elif node["kind"] == "stadium":
        draw.rounded_rectangle([x - w / 2, y - h / 2, x + w / 2, y + h / 2], radius=h / 2, fill=fill, outline=stroke, width=lw)
    elif node["kind"] == "circle":
        draw.ellipse([x - w / 2, y - h / 2, x + w / 2, y + h / 2], fill=fill, outline=stroke, width=lw)
    else:
        draw.rounded_rectangle([x - w / 2, y - h / 2, x + w / 2, y + h / 2], radius=4, fill=fill, outline=stroke, width=lw)
        if node["kind"] == "subroutine":
            inset = 9
            draw.line([(x - w / 2 + inset, y - h / 2), (x - w / 2 + inset, y + h / 2)], fill=stroke, width=lw)
            draw.line([(x + w / 2 - inset, y - h / 2), (x + w / 2 - inset, y + h / 2)], fill=stroke, width=lw)

    line_h = node["font"].size * LINE_RATIO
    total = line_h * len(node["lines"])
    for i, ln in enumerate(node["lines"]):
        ty = y - total / 2 + line_h * i + line_h / 2
        draw.text((x, ty), ln, font=node["font"], fill=PALETTE["text"], anchor="mm")


def render_flowchart(source: str, scale: int = 2) -> Image.Image:
    graph = parse_flowchart(source)
    _mark_back_edges(graph)
    layer = _layering(graph)
    layers = _order_layers(graph, layer)

    node_font = get_font(14 * scale)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for node in graph["nodes"].values():
        node["font"] = node_font
        node["lines"] = _split_label(node["label"])
        text_w = max(_measure(probe, ln, node_font)[0] for ln in node["lines"]) / scale
        text_h = len(node["lines"]) * 14 * LINE_RATIO
        if node["kind"] == "diamond":
            node["w"] = max(text_w * 1.62 + 34, 132)
            node["h"] = max(text_h * 1.92 + 26, 78)
        elif node["kind"] == "stadium":
            node["w"] = max(text_w + 46, 118)
            node["h"] = max(text_h + 26, 46)
        else:
            node["w"] = max(text_w + 36, 108)
            node["h"] = max(text_h + 26, 46)
        node["fill"] = graph["styles"].get(node["id"], PALETTE["node_fill"])

    rank_gap = 40
    layer_gap = 44
    band_gap = 116

    n_layers = len(layers)
    max_rows = 9
    cols = max(1, math.ceil(n_layers / max_rows))
    rows = math.ceil(n_layers / cols)

    layer_heights = [max(graph["nodes"][nid]["h"] for nid in ids) for ids in layers]
    layer_widths = [
        sum(graph["nodes"][nid]["w"] for nid in ids) + layer_gap * (len(ids) - 1) for ids in layers
    ]

    col_widths = [0.0] * cols
    row_heights = [0.0] * rows
    for idx in range(n_layers):
        c, r = idx // rows, idx % rows
        col_widths[c] = max(col_widths[c], layer_widths[idx])
        row_heights[r] = max(row_heights[r], layer_heights[idx])

    total_w = sum(col_widths) + band_gap * (cols - 1) + 2 * MARGIN
    col_x: list[float] = []
    acc = MARGIN
    for c in range(cols):
        col_x.append(acc)
        acc += col_widths[c] + band_gap

    row_top: list[float] = []
    acc = MARGIN
    for r in range(rows):
        row_top.append(acc)
        acc += row_heights[r] + rank_gap
    total_h = acc - rank_gap + MARGIN

    node_col: dict[str, int] = {}
    node_row: dict[str, int] = {}
    for idx, ids in enumerate(layers):
        c, r = idx // rows, idx % rows
        cursor_x = col_x[c] + (col_widths[c] - layer_widths[idx]) / 2
        for nid in ids:
            node = graph["nodes"][nid]
            node["cx"] = cursor_x + node["w"] / 2
            node["cy"] = row_top[r] + (row_heights[r] - node["h"]) / 2 + node["h"] / 2
            node_col[nid], node_row[nid] = c, r
            cursor_x += node["w"] + layer_gap

    col_bounds: list[tuple[float, float]] = []
    for c in range(cols):
        ids = [nid for nid in graph["nodes"] if node_col[nid] == c]
        col_bounds.append(
            (
                min(graph["nodes"][nid]["cx"] - graph["nodes"][nid]["w"] / 2 for nid in ids),
                max(graph["nodes"][nid]["cx"] + graph["nodes"][nid]["w"] / 2 for nid in ids),
            )
        )

    image = Image.new("RGB", (int(total_w * scale), int(total_h * scale)), "white")
    draw = ImageDraw.Draw(image)
    edge_font = get_font(12 * scale)

    def S(v):
        return v * scale

    side_slots: dict[tuple[int, int], int] = {}

    def side_channel(col: int, side: int) -> tuple[float, int]:
        left, right = col_bounds[col]
        key = (col, side)
        slot = side_slots.get(key, 0)
        side_slots[key] = slot + 1
        channel = right + 30 + 22 * slot if side > 0 else left - 30 - 22 * slot
        return channel, slot

    cross_slots: dict[tuple[int, int], int] = {}
    cross_offsets = [0, -16, 16, -32, 32, -48, 48]

    def cross_channel(sc: int, dc: int) -> float:
        mid = col_x[dc] - band_gap / 2 if dc > sc else col_x[sc] - band_gap / 2
        key = (sc, dc)
        slot = cross_slots.get(key, 0)
        cross_slots[key] = slot + 1
        return mid + cross_offsets[min(slot, len(cross_offsets) - 1)]

    for edge in graph["edges"]:
        src = graph["nodes"][edge["src"]]
        dst = graph["nodes"][edge["dst"]]
        color = PALETTE["edge"]
        width = 2
        sc, dc = node_col[edge["src"]], node_col[edge["dst"]]
        sr, dr = node_row[edge["src"]], node_row[edge["dst"]]

        if sc != dc:
            side = 1 if dc > sc else -1
            channel = cross_channel(sc, dc)
            start = (src["cx"] + side * src["w"] / 2, src["cy"])
            end = (dst["cx"] - side * dst["w"] / 2, dst["cy"])
            points = [start, (channel, start[1]), (channel, end[1]), end]
            draw.line([(S(p[0]), S(p[1])) for p in points], fill=color, width=width, joint="curve")
            _arrow_head(draw, (S(end[0]), S(end[1])), (side, 0), color, 9 * scale, 4.6 * scale)
            label_pos = ((channel + end[0]) / 2, end[1] - 13)
        elif dr <= sr:
            side = -1 if src["cx"] <= sum(col_bounds[sc]) / 2 else 1
            channel, slot = side_channel(sc, side)
            start = (src["cx"] + side * src["w"] / 2, src["cy"])
            end = (dst["cx"] + side * dst["w"] / 2, dst["cy"])
            points = [start, (channel, start[1]), (channel, end[1]), end]
            draw.line([(S(p[0]), S(p[1])) for p in points], fill=color, width=width, joint="curve")
            _arrow_head(draw, (S(end[0]), S(end[1])), (-side, 0), color, 9 * scale, 4.6 * scale)
            label_pos = (channel + side * 17, (start[1] + end[1]) / 2 + (slot - 0.5) * 30)
        elif dr - sr > 2:
            side = -1 if src["cx"] <= sum(col_bounds[sc]) / 2 else 1
            channel, slot = side_channel(sc, side)
            y_out = src["cy"] + src["h"] / 2
            y_in = dst["cy"] - dst["h"] / 2
            points = [
                (src["cx"], y_out),
                (src["cx"], y_out + 20),
                (channel, y_out + 20),
                (channel, y_in - 20),
                (dst["cx"], y_in - 20),
                (dst["cx"], y_in),
            ]
            draw.line([(S(p[0]), S(p[1])) for p in points], fill=color, width=width, joint="curve")
            _arrow_head(draw, (S(dst["cx"]), S(y_in)), (0, 1), color, 9 * scale, 4.6 * scale)
            label_pos = (channel + side * 17, (y_out + y_in) / 2 + (slot - 0.5) * 30)
        else:
            p0 = (src["cx"], src["cy"] + src["h"] / 2)
            p3 = (dst["cx"], dst["cy"] - dst["h"] / 2)
            gap = p3[1] - p0[1]
            p1 = (p0[0], p0[1] + max(gap * 0.45, 16))
            p2 = (p3[0], p3[1] - max(gap * 0.45, 16))
            points = _bezier(p0, p1, p2, p3)
            draw.line([(S(p[0]), S(p[1])) for p in points], fill=color, width=width, joint="curve")
            _arrow_head(draw, (S(p3[0]), S(p3[1])), _unit(points[-3], points[-1]), color, 9 * scale, 4.6 * scale)
            label_pos = points[len(points) // 2]

        if edge["label"]:
            _label_box(
                draw,
                (S(label_pos[0]), S(label_pos[1])),
                _split_label(edge["label"]),
                edge_font,
                PALETTE["edge_label"],
            )

    for node in graph["nodes"].values():
        _draw_node(
            draw,
            {
                **node,
                "cx": S(node["cx"]),
                "cy": S(node["cy"]),
                "w": S(node["w"]),
                "h": S(node["h"]),
            },
            scale,
        )

    return image


# ========================================================== sequenceDiagram

MSG_RE = re.compile(r"([A-Za-z0-9_]+)\s*(-->>|->>)\s*([A-Za-z0-9_]+)\s*:\s*(.*)")
PART_RE = re.compile(r"participant\s+([A-Za-z0-9_]+)(?:\s+as\s+(.+))?")
BLOCK_RE = re.compile(r"(alt|else|loop|opt|par|end)\s*(.*)")
NOTE_RE = re.compile(r"Note\s+(over|left of|right of)\s+([A-Za-z0-9_, ]+)\s*:\s*(.*)")


def parse_sequence(source: str) -> dict:
    lines = [ln.strip() for ln in source.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%%")]
    if not lines or not lines[0].lower().startswith("sequencediagram"):
        raise ValueError("不是 sequenceDiagram")

    participants: list[dict] = []
    order: dict[str, int] = {}
    events: list[dict] = []
    autonumber = False

    def ensure(pid: str, name: str | None = None) -> None:
        if pid in order:
            return
        order[pid] = len(participants)
        participants.append({"id": pid, "name": name or pid})

    for line in lines[1:]:
        if line.startswith("autonumber"):
            autonumber = True
            continue
        if line.startswith("participant"):
            m = PART_RE.match(line)
            if m:
                ensure(m.group(1), (m.group(2) or m.group(1)).strip())
            continue
        if line.startswith("Note"):
            m = NOTE_RE.match(line)
            if m:
                targets = [t.strip() for t in m.group(2).split(",")]
                for t in targets:
                    ensure(t)
                events.append({"type": "note", "targets": targets, "text": m.group(3)})
            continue
        block = BLOCK_RE.match(line)
        if block and block.group(1) in ("alt", "else", "loop", "opt", "par", "end"):
            kind = block.group(1)
            if kind == "end":
                events.append({"type": "block_end"})
            elif kind == "else":
                events.append({"type": "block_mid", "label": block.group(2).strip()})
            else:
                events.append({"type": "block_start", "kind": kind, "label": block.group(2).strip()})
            continue
        m = MSG_RE.match(line)
        if m:
            src, arrow, dst, text = m.group(1), m.group(2), m.group(3), m.group(4).strip()
            ensure(src)
            ensure(dst)
            events.append({"type": "msg", "src": src, "dst": dst, "dashed": arrow == "-->>", "text": text})
            continue

    if not events:
        raise ValueError("sequenceDiagram 未解析到任何消息")
    return {"participants": participants, "order": order, "events": events, "autonumber": autonumber}


def render_sequence(source: str, scale: int = 2) -> Image.Image:
    data = parse_sequence(source)
    participants, events = data["participants"], data["events"]
    order = data["order"]

    name_font = get_font(14 * scale)
    msg_font = get_font(13 * scale)
    tag_font = get_font(12 * scale)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    box_w = []
    for p in participants:
        tw = _measure(probe, p["name"], name_font)[0] / scale
        box_w.append(max(tw + 34, 92))
    box_h = 38

    wrap_w = 168

    def _wrap_msg(text: str) -> list[str]:
        if _measure(probe, text, msg_font)[0] / scale <= wrap_w:
            return [text]
        limit = wrap_w * 1.06
        tokens = re.findall(r"[A-Za-z0-9_./:=+<>()'\"-]+|\s+|.", text)
        lines: list[str] = []
        cur = ""
        for tok in tokens:
            if cur and _measure(probe, cur + tok, msg_font)[0] / scale > limit:
                if tok.isspace():
                    lines.append(cur)
                    cur = ""
                    continue
                if _measure(probe, tok, msg_font)[0] / scale <= limit:
                    lines.append(cur)
                    cur = tok
                    continue
                for ch in tok:
                    if cur and _measure(probe, cur + ch, msg_font)[0] / scale > limit:
                        lines.append(cur)
                        cur = ch
                    else:
                        cur += ch
                continue
            cur += tok
        if cur.strip():
            lines.append(cur.strip())
        return lines or [text]

    label_need = 150
    for ev in events:
        if ev["type"] != "msg":
            continue
        lines = _wrap_msg(ev["text"])
        ev["lines"] = lines
        tw = max(_measure(probe, ln, msg_font)[0] / scale for ln in lines)
        span = abs(order[ev["src"]] - order[ev["dst"]])
        if span == 0:
            label_need = max(label_need, tw + 90)
            continue
        label_need = max(label_need, (tw + 50) / span)
    spacing = max(max(box_w) + 44, label_need, 156)

    centers = [MARGIN + max(box_w) / 2 + idx * spacing for idx in range(len(participants))]
    total_w = centers[-1] + max(box_w) / 2 + MARGIN
    frame_left = min(centers) - 46
    frame_right = max(centers) + 46

    row_msg, row_block_head, row_block_mid, row_block_end, row_note = 46, 34, 28, 18, 0
    msg_line_h = 13 * LINE_RATIO

    ys: list[float] = []
    cursor = MARGIN + box_h + 30
    for ev in events:
        if ev["type"] == "msg":
            ys.append(cursor)
            n = len(ev.get("lines") or [ev["text"]])
            cursor += max(row_msg, n * msg_line_h + 24)
        elif ev["type"] == "block_start":
            ys.append(cursor)
            cursor += row_block_head
        elif ev["type"] == "block_mid":
            ys.append(cursor)
            cursor += row_block_mid
        elif ev["type"] == "block_end":
            ys.append(cursor)
            cursor += row_block_end
        elif ev["type"] == "note":
            ys.append(cursor)
            cursor += 34 + 16
    total_h = cursor + MARGIN

    image = Image.new("RGB", (int(total_w * scale), int(total_h * scale)), "white")
    draw = ImageDraw.Draw(image)

    def S(v):
        return v * scale

    for p, cx, w in zip(participants, centers, box_w):
        draw.rounded_rectangle(
            [S(cx - w / 2), S(MARGIN), S(cx + w / 2), S(MARGIN + box_h)],
            radius=4, fill=PALETTE["node_fill"], outline=PALETTE["node_stroke"], width=2 * scale,
        )
        draw.text((S(cx), S(MARGIN + box_h / 2)), p["name"], font=name_font, fill=PALETTE["text"], anchor="mm")
        _dashed(
            draw, (S(cx), S(MARGIN + box_h)), (S(cx), S(total_h - MARGIN + 6)),
            PALETTE["lifeline"], width=max(1, scale), dash=6 * scale, gap=5 * scale,
        )

    stack: list[dict] = []
    number = 0
    for ev, y in zip(events, ys):
        if ev["type"] == "block_start":
            stack.append({"kind": ev["kind"], "label": ev["label"], "top": y, "segments": []})
            continue
        if ev["type"] == "block_mid":
            if stack:
                stack[-1]["segments"].append((y - row_block_mid / 2, ev["label"]))
            continue
        if ev["type"] == "block_end":
            if not stack:
                continue
            block = stack.pop()
            bottom = y + row_block_end
            draw.rounded_rectangle(
                [S(frame_left), S(block["top"]), S(frame_right), S(bottom)],
                radius=3, outline=PALETTE["block_stroke"], width=max(1, scale),
            )
            tag_w = _measure(probe, block["kind"], tag_font)[0] / scale + 20
            draw.rectangle(
                [S(frame_left), S(block["top"]), S(frame_left + tag_w), S(block["top"] + 22)],
                fill="white", outline=PALETTE["block_stroke"], width=max(1, scale),
            )
            draw.text(
                (S(frame_left + tag_w / 2), S(block["top"] + 11)),
                block["kind"], font=tag_font, fill=PALETTE["block_label"], anchor="mm",
            )
            if block["label"]:
                draw.text(
                    (S(frame_left + tag_w + 8), S(block["top"] + 11)),
                    block["label"], font=tag_font, fill=PALETTE["block_label"], anchor="lm",
                )
            for seg_y, seg_label in block["segments"]:
                draw.line([S(frame_left), S(seg_y), S(frame_right), S(seg_y)], fill=PALETTE["block_stroke"], width=max(1, scale))
                draw.line(
                    [S(frame_left), S(seg_y), S(frame_left + tag_w), S(seg_y)],
                    fill=PALETTE["block_stroke"], width=max(1, scale),
                )
                draw.text(
                    (S(frame_left + 10), S(seg_y - 4)),
                    f"[{seg_label}]" if seg_label else "[else]",
                    font=tag_font, fill=PALETTE["block_label"], anchor="lb",
                )
            continue
        if ev["type"] == "note":
            targets = ev["targets"]
            xs = [centers[order[t]] for t in targets]
            nx0, nx1 = min(xs) - 40, max(xs) + 40
            nh = 34
            draw.rectangle(
                [S(nx0), S(y), S(nx1), S(y + nh)],
                fill=PALETTE["note_fill"], outline=PALETTE["note_stroke"], width=max(1, scale),
            )
            draw.text(
                (S((nx0 + nx1) / 2), S(y + nh / 2)), ev["text"], font=tag_font, fill=PALETTE["text"], anchor="mm",
            )
            continue

        # 消息
        number += 1
        prefix = f"{number}: " if data["autonumber"] else ""
        lines = list(ev.get("lines") or [ev["text"]])
        lines[0] = prefix + lines[0]
        x0, x1 = centers[order[ev["src"]]], centers[order[ev["dst"]]]
        color = PALETTE["edge"]
        label_h = msg_line_h * len(lines)

        if ev["src"] == ev["dst"]:
            loop_w, loop_h = 54, 22
            pts = [(x0 + 12, y), (x0 + loop_w, y), (x0 + loop_w, y + loop_h), (x0 + 14, y + loop_h)]
            if ev["dashed"]:
                for a, b in zip(pts, pts[1:]):
                    _dashed(draw, (S(a[0]), S(a[1])), (S(b[0]), S(b[1])), color, max(1, scale), 6 * scale, 4 * scale)
                _open_head(draw, (S(pts[-1][0]), S(pts[-1][1])), (-1, 0), color, 8 * scale, 4 * scale)
            else:
                draw.line([(S(p[0]), S(p[1])) for p in pts], fill=color, width=2 * scale, joint="curve")
                _arrow_head(draw, (S(pts[-1][0]), S(pts[-1][1])), (-1, 0), color, 8 * scale, 4 * scale)
            _label_box(
                draw,
                (S(x0 + loop_w + 10 + _measure(probe, max(lines, key=len), msg_font)[0] / (2 * scale)), S(y + 4)),
                lines, msg_font, PALETTE["text"],
            )
            continue

        direction = 1 if x1 > x0 else -1
        end_x = x1 - direction * 2
        if ev["dashed"]:
            _dashed(draw, (S(x0), S(y)), (S(end_x), S(y)), color, max(1, scale), 6 * scale, 4 * scale)
            _open_head(draw, (S(end_x), S(y)), (direction, 0), color, 8 * scale, 4 * scale)
        else:
            draw.line([S(x0), S(y), S(end_x), S(y)], fill=color, width=2 * scale)
            _arrow_head(draw, (S(end_x), S(y)), (direction, 0), color, 8 * scale, 4 * scale)

        mid = (x0 + x1) / 2
        _label_box(draw, (S(mid), S(y - 5 - label_h / 2)), lines, msg_font, PALETTE["text"])

    while stack:
        block = stack.pop()
        bottom = ys[-1] + 20 if ys else total_h - MARGIN
        draw.rounded_rectangle(
            [S(frame_left), S(block["top"]), S(frame_right), S(bottom)],
            radius=3, outline=PALETTE["block_stroke"], width=max(1, scale),
        )

    return image


# ===================================================================== API

def render(source: str, scale: int = 2) -> Image.Image:
    head = next((ln.strip() for ln in source.splitlines() if ln.strip() and not ln.strip().startswith("%%")), "")
    if head.lower().startswith("sequencediagram"):
        return render_sequence(source, scale)
    if head.lower().startswith(("flowchart", "graph")):
        return render_flowchart(source, scale)
    raise ValueError(f"暂不支持的 Mermaid 图类型：{head[:40]}")


MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)```", re.S)


def extract_blocks(markdown: str) -> list[str]:
    return [m.group(1).strip("\n") for m in MERMAID_BLOCK_RE.finditer(markdown)]


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("docs/06-Agent节点拆解与架构时序.md")
    out_dir = Path(argv[2]) if len(argv) > 2 else target.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    blocks = extract_blocks(target.read_text(encoding="utf-8"))
    if not blocks:
        print("未找到 mermaid 代码块")
        return 1
    for idx, block in enumerate(blocks, 1):
        image = render(block, scale=2)
        out = out_dir / f"{target.stem}-{idx}.png"
        image.save(out)
        print(f"已生成 {out}  {image.size[0]}x{image.size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))