"""配置加载与提示词库。

所有配置放在 config/ 与 prompts/ 目录，业务同学改 YAML/Markdown 即可调参，
不需要改代码，这也是 Dify 低代码路线的核心思想：策略配置化。
"""

from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPT_DIR = ROOT / "prompts"
KNOWLEDGE_DIR = ROOT / "knowledge"


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """一次性加载全部配置，进程内缓存。"""

    return {
        "app": load_yaml(CONFIG_DIR / "app.yaml"),
        "personas": load_yaml(CONFIG_DIR / "personas.yaml"),
        "intents": load_yaml(CONFIG_DIR / "intents.yaml"),
        "compliance": load_yaml(CONFIG_DIR / "compliance.yaml"),
    }


class PromptLibrary:
    """提示词库。

    提示词以 Markdown 文件维护，用 `{{变量名}}` 作为占位符，
    与 Dify 提示词节点的变量命名保持一致，方便两条路线互相对照。
    """

    def __init__(self, prompt_dir: pathlib.Path = PROMPT_DIR) -> None:
        self.prompt_dir = prompt_dir
        self._cache: dict[str, str] = {}

    def get(self, name: str) -> str:
        if name not in self._cache:
            path = self.prompt_dir / f"{name}.md"
            if not path.exists():
                raise FileNotFoundError(f"提示词不存在: {path}")
            self._cache[name] = path.read_text(encoding="utf-8")
        return self._cache[name]

    def render(self, name: str, **kwargs: Any) -> str:
        """极简模板渲染，只做 `{{key}}` 替换，不引入 jinja2 依赖。"""

        text = self.get(name)
        for key, value in kwargs.items():
            text = text.replace("{{" + key + "}}", str(value))
        return text