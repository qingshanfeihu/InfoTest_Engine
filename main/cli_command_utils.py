"""CLI 命令字符串通用工具。

统一被以下模块复用：
- ``main/rag_graph.py``：L1 生成侧 allowlist 与后处理过滤
- ``main/function_evidence.py``：L4 命令主词 substring 校验
- ``main/function_schema.py``：L3 reverse 对称 / sample_cli 回溯校验

设计目标：
1. **与 CLI 语法占位符 (`{}` / `[]` / `<>` / `()`) 解耦**——只比较命令主词序列
2. **容忍等价语法**（``{on|off}`` ↔ ``[on|off]`` ↔ ``<on|off>`` ↔ ``(on|off)``）
3. **零外部依赖**——只用 stdlib
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 主词提取
# ---------------------------------------------------------------------------

_SYNTAX_PLACEHOLDER_PREFIXES = ("{", "[", "<", "(")

# 用于判断 cmd 是否含 on/off 切换语义
_ONOFF_SWITCH_RE = re.compile(
    r"[\{\[\<\(]\s*(on\s*\|\s*off|off\s*\|\s*on)\s*[\}\]\>\)]",
    re.IGNORECASE,
)

_VERB_TOKENS = {"on", "off", "enable", "disable"}

# CLI 章节标题/表格常用中文术语，与英文命令主词做弱语义对齐。
# 仅用于 ``cli_reference`` 的 warning 级上下文兜底，不作为强字面回溯。
_COMMAND_CONTEXT_HINTS = {
    "virtual-server": ("虚拟服务",),
    "server-farm": ("服务器组", "服务组"),
    "health-check": ("健康检查",),
    "real-service": ("真实服务", "真实服务器"),
    "real-server": ("真实服务器", "真实服务"),
    "service-group": ("服务组",),
}


def extract_command_tokens(cmd: str) -> list[str]:
    """提取命令主词序列；遇到第一个占位符/参数即停止。

    例:
        "http2 virtual {on|off} <vs>" → ["http2", "virtual"]
        "http2 flow-control window-size <size>" → ["http2", "flow-control", "window-size"]
        "http2 enable" → ["http2", "enable"]
        "no http2 virtual <vs>" → ["no", "http2", "virtual"]
        "" → []
    """
    if not cmd or not isinstance(cmd, str):
        return []
    tokens: list[str] = []
    for tok in cmd.strip().split():
        if tok.startswith(_SYNTAX_PLACEHOLDER_PREFIXES):
            break
        tokens.append(tok)
    return tokens


def normalize_syntax_brackets(text: str) -> str:
    """把 ``{a|b}`` / ``[a|b]`` / ``<a|b>`` / ``(a|b)`` 归一化为 ``{a|b}``。

    仅用于 substring 比对；不改变用户可见文本。
    """
    if not text:
        return ""
    mapping = str.maketrans({
        "[": "{", "]": "}",
        "<": "{", ">": "}",
        "(": "{", ")": "}",
    })
    return text.translate(mapping)


# ---------------------------------------------------------------------------
# evidence 权威度排序（L5）
# ---------------------------------------------------------------------------


def sort_evidences_by_authority(evidences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """稳定排序 evidence 列表：高权威源在前。

    权威度来自 :func:`main.knowledge_paths.evidence_authority`；
    同权威度时保持原相对顺序。
    """
    if not evidences:
        return []
    # 延迟 import 避免循环依赖
    from main.knowledge_paths import evidence_authority

    indexed = list(enumerate(evidences))
    indexed.sort(key=lambda pair: (-evidence_authority(pair[1]), pair[0]))
    return [ev for _, ev in indexed]


# ---------------------------------------------------------------------------
# evidence substring 校验（L4）
# ---------------------------------------------------------------------------


def command_matches_text(cmd: str, text: str) -> bool:
    """命令主词序列是否按序出现在 ``text`` 中（允许不相邻但同序）。

    用于校验 ``cli.commands[].command`` 是否能在某条 ``evidence.quoted_text``
    里找到回溯（即命令字面本身来自源文，而不是 LLM 凭空拼接）。
    """
    tokens = extract_command_tokens(cmd)
    if not tokens or not text:
        return False
    lower = text.lower()
    pos = 0
    for tok in tokens:
        idx = lower.find(tok.lower(), pos)
        if idx < 0:
            return False
        pos = idx + len(tok)
    return True


def _command_matches_context_terms(cmd: str, text: str) -> bool:
    """弱语义匹配：章节/表格标题是否与命令核心对象一致。"""
    if not cmd or not text:
        return False
    text_lower = text.lower()
    tokens = extract_command_tokens(cmd)
    if len(tokens) > 1:
        tokens = tokens[1:]
    for tok in tokens:
        normalized = tok.lower().replace("-", " ").strip()
        if normalized and normalized in text_lower:
            return True
        for alias in _COMMAND_CONTEXT_HINTS.get(tok.lower(), ()):
            if alias.lower() in text_lower:
                return True
    return False


def find_command_traceability(
    cmd: str,
    evidences: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """返回命令在 evidence 中的回溯情况。

    强匹配来源：
    - ``quoted_text``
    - ``section_title``（适用于 CLI 标题本身就是命令字面的文档）

    弱匹配来源：
    - released ``cli_reference`` 的章节/表格上下文，仅作为 warning 级兜底，
      不视为强字面回溯。
    """
    if not cmd:
        return {
            "matched": False,
            "matched_source": None,
            "match_field": None,
            "context_only": False,
            "context_reason": None,
        }

    for ev in evidences or []:
        if not isinstance(ev, dict):
            continue
        matched_source = ev.get("source_file") or ev.get("stem")
        quoted = str(ev.get("quoted_text") or "")
        if command_matches_text(cmd, quoted):
            return {
                "matched": True,
                "matched_source": matched_source,
                "match_field": "quoted_text",
                "context_only": False,
                "context_reason": None,
            }

        section_title = str(ev.get("section_title") or "")
        if command_matches_text(cmd, section_title):
            return {
                "matched": True,
                "matched_source": matched_source,
                "match_field": "section_title",
                "context_only": False,
                "context_reason": None,
            }

        role = str(ev.get("role") or "")
        context_text = "\n".join(part for part in (section_title, quoted) if part)
        if role == "cli_reference" and _command_matches_context_terms(cmd, context_text):
            return {
                "matched": False,
                "matched_source": matched_source,
                "match_field": None,
                "context_only": True,
                "context_reason": "cli_reference_context_only",
            }

    return {
        "matched": False,
        "matched_source": None,
        "match_field": None,
        "context_only": False,
        "context_reason": None,
    }


def verify_command_against_evidences(
    cmd: str, evidences: Iterable[dict[str, Any]]
) -> tuple[bool, str | None]:
    """检查 ``cmd`` 能否在任一 evidence 的 quoted_text / section_title 中命中。

    返回 ``(matched, matched_source_file)``；未命中返回 ``(False, None)``。
    """
    traceability = find_command_traceability(cmd, evidences)
    return bool(traceability.get("matched")), traceability.get("matched_source")


# ---------------------------------------------------------------------------
# reverse_command 对称性（L3 schema 与 L1 生成）
# ---------------------------------------------------------------------------


def has_onoff_switch(cmd: str) -> bool:
    """判断命令是否含 ``{on|off}`` / ``[on|off]`` 等切换占位符。"""
    if not cmd:
        return False
    return bool(_ONOFF_SWITCH_RE.search(cmd))


def _raw_tokens(cmd: str) -> list[str]:
    return cmd.strip().split() if cmd else []


def _extract_switch_values(cmd: str) -> set[str]:
    """从 ``cmd`` 中的占位符（{a|b} / [a|b] / ...）提取可填值。"""
    values: set[str] = set()
    for tok in _raw_tokens(cmd):
        if not tok.startswith(_SYNTAX_PLACEHOLDER_PREFIXES):
            continue
        inner = tok.strip("{}[]<>()")
        for v in inner.split("|"):
            v = v.strip()
            if v:
                values.add(v)
    return values


def is_reverse_symmetric(cmd: str, reverse_cmd: str) -> tuple[bool, str | None]:
    """检查 ``reverse_cmd`` 与 ``cmd`` 是否语法对称。

    返回 ``(ok, reason_if_not_ok)``。

    合法情形：
      1. reverse_cmd 为空（未提供回退）
      2. reverse_cmd 以 ``"no "`` 开头
      3. reverse_cmd 的 token 序列与 cmd 相比：
         * 首 token 必须相同（保证作用域一致）
         * reverse 额外的 token 必须是 cmd 占位符展开值，或 ``{on, off, enable, disable}``
         * ``on`` / ``off`` 仅在 cmd 含 ``{on|off}`` 切换占位时允许
         * ``enable`` / ``disable`` 仅在 cmd 含对称动词时允许
    """
    if not reverse_cmd or not reverse_cmd.strip():
        return True, None

    reverse = reverse_cmd.strip()
    if reverse.startswith("no "):
        return True, None

    cmd_all = _raw_tokens(cmd)
    rev_all = _raw_tokens(reverse)

    if not cmd_all or not rev_all:
        return False, "empty_tokens"
    if rev_all[0] != cmd_all[0]:
        return False, f"scope_mismatch(prefix={rev_all[0]!r} vs {cmd_all[0]!r})"

    cmd_set = set(cmd_all)
    switch_values = _extract_switch_values(cmd)
    extra = [t for t in rev_all if t not in cmd_set]

    # 含 {on|off} 占位符 或 裸 on/off 作为 token 均视为有 on/off 切换语义
    onoff = has_onoff_switch(cmd) or "on" in cmd_set or "off" in cmd_set
    has_enable = "enable" in cmd_set
    has_disable = "disable" in cmd_set

    for tok in extra:
        if tok in switch_values:
            continue  # 占位符允许的取值（如 {on|off} 展开的 on/off）
        if tok.startswith(_SYNTAX_PLACEHOLDER_PREFIXES):
            continue  # reverse 中新增的占位符（如 [priority_mode]）视作额外可选参数
        if tok not in _VERB_TOKENS:
            return False, f"foreign_token({tok!r})"
        if tok in ("on", "off") and not onoff:
            return False, f"no_onoff_switch_in_command (extra {tok!r})"
        if tok == "enable" and not has_disable:
            return False, "enable_without_disable_verb_in_command"
        if tok == "disable" and not has_enable:
            return False, "disable_without_enable_verb_in_command"
    return True, None


# ---------------------------------------------------------------------------
# allowlist 工具（L1 生成侧）
# ---------------------------------------------------------------------------


def feature_command_allowlist(feature: dict[str, Any]) -> list[str]:
    """返回 feature 的 ``cli.commands[].command`` 字符串列表（去 None/空）。

    用于 RAG 生成时的命令 allowlist；调用方可进一步用
    :func:`extract_command_tokens` 提取主词做比对。
    """
    cli = (feature or {}).get("cli") or {}
    commands = cli.get("commands") or []
    return [
        str(c.get("command", "")).strip()
        for c in commands
        if isinstance(c, dict) and str(c.get("command", "")).strip()
    ]


def collect_allowlist_tokens(commands: Iterable[str]) -> list[list[str]]:
    """把命令字符串列表转为 tokens 列表，供后处理 substring 匹配。"""
    return [extract_command_tokens(c) for c in commands if c]


# ---------------------------------------------------------------------------
# CLI 行检出（生成后后处理）
# ---------------------------------------------------------------------------


# 识别可能的命令行（保留："^\s*<verb> ..." 形式；跳过 markdown 标题/列表符号）
_COMMAND_LINE_RE = re.compile(
    r"^(?P<lead>\s*(?:`{1,3}|!\s*回退:\s*`?|\*\s*回退\*\s*:?\s*`?)?)"
    r"(?P<cmd>[A-Za-z][A-Za-z0-9_\-]*(?:\s+[A-Za-z0-9_\-\{\}\[\]\<\>\(\)\|\.\/\,]+)+)"
    r"(?:\s*`?\s*)?$"
)


# CLI 交互提示符前缀：``Demo(config)#``、``AN(config)#``、``Array(config)#`` 等
_CLI_PROMPT_PREFIX_RE = re.compile(
    r"^\s*[A-Za-z][A-Za-z0-9_\-]*\s*(?:\([A-Za-z0-9_\-\s]+\))?\s*[#>]\s*"
)


def strip_cli_prompt_prefix(line: str) -> str:
    """剥掉 ``Demo(config)#`` / ``AN#`` 等 CLI 提示符前缀。"""
    if not line:
        return line
    m = _CLI_PROMPT_PREFIX_RE.match(line)
    if m:
        return line[m.end():]
    return line


def line_contains_allowlisted_command(
    line: str, allowlist_token_sequences: list[list[str]]
) -> bool:
    """判断一行文本是否至少能被一条 allowlist 命令的主词序列连续紧邻匹配。

    "连续紧邻"：allowlist tokens 必须作为独立词相邻出现，之间仅以空白分隔。
    自动剥离 ``Demo(config)#`` 等 CLI 提示符前缀。

    这样可以区分：
      ``http2 virtual on myvs``          → 命中 ``[http2, virtual]`` ✓
      ``http2 maxstream virtual myvs``   → 不命中 ``[http2, virtual]`` ✗（中间插入了 maxstream）
    """
    if not line or not allowlist_token_sequences:
        return False
    lower = strip_cli_prompt_prefix(line).lower()
    for tokens in allowlist_token_sequences:
        if not tokens:
            continue
        pattern = r"(?:^|[^A-Za-z0-9_\-])" + r"\s+".join(re.escape(t.lower()) for t in tokens) + r"(?:$|[^A-Za-z0-9_\-])"
        if re.search(pattern, lower):
            return True
    return False


__all__ = [
    "extract_command_tokens",
    "normalize_syntax_brackets",
    "command_matches_text",
    "find_command_traceability",
    "verify_command_against_evidences",
    "has_onoff_switch",
    "is_reverse_symmetric",
    "feature_command_allowlist",
    "collect_allowlist_tokens",
    "strip_cli_prompt_prefix",
    "line_contains_allowlisted_command",
    "sort_evidences_by_authority",
]
