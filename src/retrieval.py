"""节点 3：知识库检索（轻量 BM25）。

为什么不直接上向量库：MVP 阶段知识量在百级 chunk，中文短问句用字级 n-gram + BM25
召回质量足够，且零外部依赖、零额外成本、结果可解释。
量级上来后（>5000 chunk）再换向量检索，接口保持不变。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .models import KnowledgeHit

_SPLIT_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_CLEAN_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """中英混合分词：中文取 1-gram + 2-gram，英文/数字按词切。"""

    text = text.lower()
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    # 字母与数字分开切，"SF123" 应切成 sf / 123 两个 token
    latin = re.findall(r"[a-z]+", text)
    digits = re.findall(r"[0-9]+", text)

    tokens: list[str] = list(latin) + list(digits)
    for block in cjk:
        tokens.extend(block)
        tokens.extend(block[i : i + 2] for i in range(len(block) - 1))
    return tokens


class KnowledgeRetriever:
    def __init__(self, cfg: dict[str, Any], chunks: list[dict[str, str]] | None = None) -> None:
        self.top_k = int(cfg.get("retrieval", {}).get("top_k", 3))
        self.min_score = float(cfg.get("retrieval", {}).get("min_score", 0.15))
        self.k1 = float(cfg.get("retrieval", {}).get("bm25_k1", 1.2))
        self.b = float(cfg.get("retrieval", {}).get("bm25_b", 0.75))
        self.chunks = chunks or []
        self._build_index()

    @classmethod
    def from_markdown(cls, cfg: dict[str, Any], paths: list[Any]) -> "KnowledgeRetriever":
        chunks: list[dict[str, str]] = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            chunks.extend(parse_markdown(text, source=path.stem))
        return cls(cfg, chunks)

    def _build_index(self) -> None:
        self._doc_tokens: list[Counter[str]] = []
        self._doc_len: list[int] = []
        df: Counter[str] = Counter()

        for chunk in self.chunks:
            tokens = tokenize(chunk["title"] + " " + chunk["content"])
            counts = Counter(tokens)
            self._doc_tokens.append(counts)
            self._doc_len.append(len(tokens))
            df.update(counts.keys())

        self._n = len(self.chunks) or 1
        self._avg_len = (sum(self._doc_len) / self._n) if self._doc_len else 1.0
        self._idf = {term: math.log(1 + (self._n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

    def search(self, query: str, top_k: int | None = None) -> list[KnowledgeHit]:
        k = top_k or self.top_k
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        scored: list[tuple[float, int]] = []
        for idx, counts in enumerate(self._doc_tokens):
            length = self._doc_len[idx]
            score = 0.0
            for term in set(q_tokens):
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf.get(term, 0.0)
                denom = tf + self.k1 * (1 - self.b + self.b * length / self._avg_len)
                score += idf * tf * (self.k1 + 1) / denom
            if score > 0:
                scored.append((score, idx))

        if not scored:
            return []

        scored.sort(reverse=True)
        max_score = scored[0][0] or 1.0

        hits: list[KnowledgeHit] = []
        for score, idx in scored[:k]:
            normalized = round(score / max_score, 3)
            if normalized < self.min_score:
                continue
            chunk = self.chunks[idx]
            hits.append(
                KnowledgeHit(
                    doc_id=chunk["doc_id"],
                    title=chunk["title"],
                    content=chunk["content"],
                    score=normalized,
                )
            )
        return hits


def parse_markdown(text: str, source: str = "kb") -> list[dict[str, str]]:
    """按 `## 标题` 切分知识切片。"""

    matches = list(_SPLIT_RE.finditer(text))
    chunks: list[dict[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if not content:
            continue
        title = match.group(1).strip()
        chunks.append(
            {
                "doc_id": f"{source}#{i}",
                "title": title,
                "content": content,
            }
        )
    return chunks