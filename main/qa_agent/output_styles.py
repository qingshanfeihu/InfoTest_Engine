"""Output Style 系统 —— Explanatory / Learning 模式。

本质：往 system prompt 动态注入一段额外指令，让 LLM 在回复中穿插特定格式的教育性内容。
LLM 输出的 markdown 块（如 ★ Insight / ● Learn by Doing）由 markdown renderer 正常渲染。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OutputStyleConfig:
    name: str
    description: str
    prompt: str


_INSIGHT_SECTION = """\
## Insights
在编写代码前后，使用以下格式提供简短的教育性解释：

`★ Insight ─────────────────────────────────────`
[2-3 个关键教育要点]
`─────────────────────────────────────────────────`

重点关注与当前代码库相关的有趣见解，而非通用编程概念。"""

_EXPLANATORY_PROMPT = f"""\
# Output Style: Explanatory

除了软件工程任务外，你还应在过程中提供关于代码库的教育性见解。\
清晰且具有教育性，在保持任务聚焦的同时提供有用的解释。

{_INSIGHT_SECTION}"""

_LEARNING_PROMPT = f"""\
# Output Style: Learning

除了软件工程任务外，你还应通过动手实践帮助用户更多地了解代码库。\
当生成 20+ 行涉及设计决策的代码时，请人类贡献 2-10 行代码片段：

```
● **Learn by Doing**
**Context:** [已构建的内容及为什么这个决策重要]
**Your Task:** [具体的函数/部分，提及文件和 TODO(human)]
**Guidance:** [需要考虑的权衡和约束]
```

{_INSIGHT_SECTION}"""


OUTPUT_STYLES: dict[str, OutputStyleConfig] = {
    "default": OutputStyleConfig(
        name="default",
        description="标准输出，无额外教育性内容",
        prompt="",
    ),
    "explanatory": OutputStyleConfig(
        name="Explanatory",
        description="在实现过程中穿插 ★ Insight 教育性注释",
        prompt=_EXPLANATORY_PROMPT,
    ),
    "learning": OutputStyleConfig(
        name="Learning",
        description="暂停并请求用户编写小段代码进行动手练习",
        prompt=_LEARNING_PROMPT,
    ),
}


def get_output_style(name: str) -> Optional[OutputStyleConfig]:
    return OUTPUT_STYLES.get(name.lower())


def get_style_prompt(name: str) -> str:
    cfg = get_output_style(name)
    if cfg is None or not cfg.prompt:
        return ""
    return cfg.prompt


_active_style: str = "default"


def set_active_style(name: str) -> None:
    global _active_style
    if name.lower() in OUTPUT_STYLES:
        _active_style = name.lower()


def get_active_style() -> str:
    return _active_style


def get_active_style_prompt() -> str:
    return get_style_prompt(_active_style)
