"""节点 5：合规质检。

这是电商客服最容易踩坑的一环：绝对化用语、超权限赔付、贬低竞品、医疗功效宣称。
本节点在文案下发前做最后一道门禁：
- block 级命中 → 先尝试用 LLM 整改，整改失败再本地兜底替换，仍不通过则转人工；
- warn 级命中 → 记录告警，不阻断下发。
"""

from __future__ import annotations

import re
from typing import Any

from .models import ComplianceIssue


class ComplianceChecker:
    def __init__(self, cfg: dict[str, Any]) -> None:
        # 兼容两种入参：完整的全局配置，或单独加载的 compliance.yaml
        root = cfg["compliance"] if "compliance" in cfg else cfg
        self.rules = root["rules"]
        self._compiled = [
            (rule, [re.compile(str(p)) for p in rule.get("patterns", [])]) for rule in self.rules
        ]

    def check(self, text: str) -> list[ComplianceIssue]:
        issues: list[ComplianceIssue] = []
        for rule, patterns in self._compiled:
            for pattern in patterns:
                found = pattern.search(text)
                if found:
                    issues.append(
                        ComplianceIssue(
                            rule_id=rule["id"],
                            rule_name=rule["name"],
                            level=rule["level"],
                            message=rule["message"],
                            hit=found.group(0),
                        )
                    )
                    break
        return issues

    def has_blocking(self, issues: list[ComplianceIssue]) -> bool:
        return any(issue.level == "block" for issue in issues)

    def sanitize(self, text: str) -> str:
        """离线兜底整改：按规则 fix 字段做替换，保证无 LLM 时也能出合规文案。"""

        for rule, patterns in self._compiled:
            if rule["level"] != "block":
                continue
            fix = rule.get("fix", "")
            for pattern in patterns:
                text = pattern.sub(fix, text)
        # 清理替换后可能出现的重复标点与空括号
        text = re.sub(r"（）|\(\)", "", text)
        text = re.sub(r"[，,]{2,}", "，", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text