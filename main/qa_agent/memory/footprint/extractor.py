"""从 working memory 提取 RawFact 列表（LLM 模式）。

调用 LLM 提取结构化产品事实。LLM 负责判断事实 vs 导航、
提取结构化内容、分类 slot、关联 CLI 命令。

代码只负责：解析 LLM JSON 输出 → RawFact 列表。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from main.qa_agent.memory.footprint.schema import RawFact

logger = logging.getLogger(__name__)

_THREAD_ID_RE = re.compile(r"thread_id:\s*(\S+)")

_SYSTEM_PROMPT = """\
<Role>
你是产品知识提取助手。阅读 IST-Core agent 的工作记忆（包含 tool 调用和 AI 思考），\
提取其中已验证的**产品事实**。
</Role>

<Rules>
## 正向提取范围（只提取以下类型）：
1. **CLI 命令语法和参数** — 来自 cli__part*.md 确认的命令格式、参数枚举值、默认值
2. **产品行为规则** — "当X条件时，行为是Y"，必须有文档或 BUG 证据
3. **已知缺陷** — BUG-ID + 标题 + 影响版本
4. **功能描述** — 某命令/功能的用途、作用范围

## 负面约束（绝对不要提取）：
- agent 工作计划（"接下来搜索"、"需要找到"、"继续读取"）
- 评审结论和建议（"应该补充"、"缺少"、"建议修改"）
- 文件导航日志（"找到3个文件"、"文件为二进制格式"）
- 等价映射（"等价于 F5"、"类似 A10"）
- 重复内容（同一事实只提取一次）

## cli_commands 填写规则（重要）：
- 每条 fact 必须尽力关联到 CLI 命令。从以下来源推断：
  1. tool 调用中 grep/read 的 cli__part*.md 文件上下文
  2. BUG 标题中的功能关键词（如 "[Http rewrite body]" → "http rewrite body"）
  3. 同一 session 中反复出现的命令名
- 只有确实无法推断时才填 []
</Rules>

<Output_Format>
严格输出以下 JSON 格式：

```json
{
  "facts": [
    {
      "cli_commands": ["http rewrite body"],
      "content": "简洁的事实描述",
      "slot": "known_issues",
      "source_file": "BUG-70233",
      "evidence": "[Ustack][Http rewrite body]Fail to rewrite a 1024KB file"
    }
  ]
}
```

字段说明：
- cli_commands：涉及的 CLI 命令全名列表。从 BUG 标题、文档路径、session 上下文推断。
- content：简洁的事实描述（一句话）。
- slot：取值 "cli.commands" | "decision_rules" | "behaviors" | "known_issues"
- source_file：证据来源路径（tool 的 path= 参数）或 BUG-ID。
- evidence：从 tool 输出中摘取的关键原文片段（简短）。

无可提取事实时输出 {"facts": []}。只输出 JSON。
</Output_Format>\
"""


def _parse_thread_id(content: str) -> str:
    m = _THREAD_ID_RE.search(content)
    return m.group(1) if m else ""


def _parse_llm_response(raw: Any, thread_id: str) -> list[RawFact]:
    """解析 LLM 返回的 JSON 为 RawFact 列表。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("footprint LLM 返回非 JSON: %s", raw[:200])
            return []

    if not isinstance(raw, dict):
        return []

    facts_raw = raw.get("facts", [])
    if not isinstance(facts_raw, list):
        return []

    results: list[RawFact] = []
    for item in facts_raw:
        if not isinstance(item, dict):
            continue
        cli_commands_raw = item.get("cli_commands", [])
        if isinstance(cli_commands_raw, list):
            cli_commands = [cmd.split() for cmd in cli_commands_raw if isinstance(cmd, str) and cmd]
        else:
            cli_commands = []

        content = item.get("content", "")
        if not content:
            continue

        results.append(RawFact(
            content=content,
            cli_commands=cli_commands,
            source_file=item.get("source_file", ""),
            quoted_text=item.get("evidence", ""),
            source_thread=thread_id,
        ))

    return results


def extract_facts(content: str, *, llm_chat: Callable | None = None) -> list[RawFact]:
    """从 working memory 文本中提取 RawFact 列表。

    Args:
        content: working memory 文件完整文本
        llm_chat: LLM 调用函数，签名 (prompt: str) -> str|dict
                  必须提供，否则返回空列表
    """
    if llm_chat is None:
        logger.debug("footprint extract: no llm_chat, skip")
        return []

    thread_id = _parse_thread_id(content)

    try:
        result = llm_chat(_SYSTEM_PROMPT, content)
    except Exception as exc:
        logger.warning("footprint LLM 调用失败: %s", exc)
        return []

    facts = _parse_llm_response(result, thread_id)
    _associate_session_commands(facts)
    return facts


def _associate_session_commands(facts: list[RawFact]) -> None:
    """同一文件中，把有 CLI 命令的 facts 关联到没有命令的 facts。"""
    session_commands: list[list[str]] = []
    for f in facts:
        for cmd in f.cli_commands:
            if cmd and cmd not in session_commands:
                session_commands.append(cmd)

    if session_commands:
        for f in facts:
            if not f.cli_commands:
                f.cli_commands = session_commands[:1]
