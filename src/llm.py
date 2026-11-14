"""LLM 客户端（OpenAI 兼容协议）。

用标准库 urllib 直接打 /chat/completions，不引入 openai SDK，
好处是版本兼容风险为零，也能无缝对接 DeepSeek、通义、Moonshot 等兼容网关
（只改 base_url 与 model 即可）。

设计要点：LLM 永远只是"可选增强"。没有 API Key 时 available=False，
上层自动降级到规则+模板，保证本地演示与单元测试不依赖外网。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class LLMClient:
    def __init__(self, cfg: dict[str, Any]) -> None:
        llm_cfg = cfg.get("llm", {}) if "llm" in cfg else cfg
        self.enabled = bool(llm_cfg.get("enabled", True))
        self.base_url = str(llm_cfg.get("base_url", "")).rstrip("/")
        self.model = str(llm_cfg.get("model", "gpt-4o-mini"))
        self.api_key = os.getenv(str(llm_cfg.get("api_key_env", "OPENAI_API_KEY")), "")
        self.timeout = int(llm_cfg.get("timeout", 30))
        self.temperature = float(llm_cfg.get("temperature", 0.3))

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url)

    def chat(self, system: str, user: str, temperature: float | None = None) -> str | None:
        if not self.available:
            return None

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
        }
        req = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError, OSError):
            # 任何异常都视为本次调用失败，交由上层降级，不向用户抛错
            return None


class ScriptedLLM:
    """离线演示/测试用的假 LLM：按脚本返回固定文案，用于验证合规门禁链路。"""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[dict[str, str]] = []

    @property
    def available(self) -> bool:
        return True

    def chat(self, system: str, user: str, temperature: float | None = None) -> str | None:
        self.calls.append({"system": system, "user": user})
        if not self.responses:
            return None
        if len(self.calls) == 1:
            return self.responses[0]
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]