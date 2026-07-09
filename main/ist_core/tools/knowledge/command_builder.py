"""确定性命令构建器 — LLM 只填参数值，命令结构由手册文法保证。

用法：
    build_command("slb virtual http", {"virtual_service": "vs1", "vip": "10.0.0.100", "vport": 80, "arp_support": "arp"})
    → "slb virtual http vs1 10.0.0.100 80 arp"

LLM 不碰命令名、参数顺序、枚举值——全部由工具从 CLI 手册文法中确定性生成。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from functools import lru_cache

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── 手册文法解析（与 verify_commands.py 同算法）───────────

_CMD_RE = re.compile(r"\*{1,2}([^*]+?)\*{1,2}\s+_(.+)_", re.MULTILINE)
# 处理命令关键字中的 {a|b} 变体：如 **slb virtual {enable|disable}** _<vs>_
# 拆分为 slb virtual enable 和 slb virtual disable 两条
_CMD_KEYWORD_EXPAND_RE = re.compile(r"\{(.+?)\}")
_RANGE_RE = re.compile(
    r"取值必须为\s*([\d,]+)\s*(?:到|至)\s*([\d,]+)\s*之间的整数",
    re.IGNORECASE,
)

def _extract_range(text: str) -> tuple[int, int] | None:
    """从参数描述文本中提取数值范围约束。"""
    m = _RANGE_RE.search(text)
    if m:
        lo = int(m.group(1).replace(",", ""))
        hi = int(m.group(2).replace(",", ""))
        return (lo, hi)
    return None


def _find_param_ranges(content: str, syntax_match_end: int, param_names: list[str]) -> dict[str, tuple[int, int]]:
    """在语法行之后的参数表中查找参数的范围约束。"""
    ranges = {}
    # 取语法行后 ~2000 字符找参数表
    tail = content[syntax_match_end : syntax_match_end + 3000]
    # 对每个参数名在尾文中搜索描述行
    for pname in param_names:
        for m in re.finditer(rf"\|?\s*{re.escape(pname)}\s*\|?\s*(.+?)(?:\||$)", tail, re.IGNORECASE):
            r = _extract_range(m.group(1).strip())
            if r:
                ranges[pname] = r
                break
    return ranges


def _parse_params(raw: str) -> list:
    # 只去 *，保留下划线（hc_up、max_connection 等参数名需要）
    cleaned = re.sub(r"\*", "", raw).strip()
    # 去首尾的 _ 包裹标记，但保留参数名内部的 _
    cleaned = cleaned.strip("_")
    tokens = cleaned.split()
    params = []
    for tok in tokens:
        # 跳过不含参数标记的 token（`*rr*`/`*lc*` 等示例值去掉 * 后变成 `rr`/`lc`）
        if not any(c in tok for c in ("<", "[", "{")):
            continue
        if not tok:
            continue
        is_enum = False
        required = True
        if tok.startswith("{") and tok.endswith("}"):
            is_enum = True
            tok = tok[1:-1]
        if tok.startswith("[") and tok.endswith("]"):
            required = False
            tok = tok[1:-1]
        tok = re.sub(r"^<|>$", "", tok)
        enum = None
        if is_enum and "|" in tok:
            parts = tok.split("|")
            if not any("_" in p or len(p) > 15 for p in parts):
                enum = set(parts)
        # 跳过空名或纯符号（如 `|`）
        if not tok or tok in ("|", "-", "*"):
            continue
        params.append({"name": tok, "required": required, "enum": enum})
    return params


@lru_cache(maxsize=1)
def _load_grammar() -> dict:
    """加载手册文法索引（缓存，只解析一次）。"""
    manual_dir = Path(__file__).resolve().parents[4] / "knowledge" / "data" / "markdown" / "product"
    index = {}
    for mp in sorted(manual_dir.glob("cli_*_Chapter*.md")):
        content = mp.read_text(encoding="utf-8", errors="replace")
        for m in _CMD_RE.finditer(content):
            raw_keyword = m.group(1).strip()
            raw_line = m.group(2).strip()
            params = _parse_params(raw_line)
            if not params:
                continue
            # 展开 `slb virtual {enable|disable}` → slb virtual enable + slb virtual disable
            m_expand = _CMD_KEYWORD_EXPAND_RE.search(raw_keyword)
            if m_expand:
                options = m_expand.group(1).split("|")
                prefix = raw_keyword[: m_expand.start()].strip()
                suffix = raw_keyword[m_expand.end() :].strip()
                keywords = [f"{prefix} {opt} {suffix}".strip() for opt in options]
            else:
                keywords = [raw_keyword]
            # 保留第一个匹配（手册中基类语法总是先出现）
            for keyword in keywords:
                if keyword in index:
                    continue
                param_names = [p["name"] for p in params]
                param_ranges = _find_param_ranges(content, m.end(), param_names)
                if param_ranges:
                    for p in params:
                        if p["name"] in param_ranges:
                            p["range"] = param_ranges[p["name"]]
                index[keyword] = {"params": params, "file": mp.name}
    return index


# ── 命令构建 ──────────────────────────────────────────────


def _format_value(val) -> str:
    """将参数值格式化为命令 token。"""
    s = str(val)
    if any(c in s for c in ('"', "'", " ", "@", "!", "~", ":", "-", ".", "<", ">")):
        return f'"{s}"'
    return s


def _build(keyword: str, values: dict) -> tuple[str, str | None]:
    """构建命令字符串。返回 (command_string, error_or_none)。"""
    grammar = _load_grammar()
    if keyword not in grammar:
        return "", (f"command '{keyword}' is not in the manual grammar. Available commands: "
                    f"{', '.join(sorted(grammar.keys())[:20])}...")

    entry = grammar[keyword]
    params = entry["params"]
    parts = keyword.split()

    # 构建参数名映射：支持管道分隔的变体名（如 virtual|real → 接受 virtual 或 real）
    param_aliases = {}
    for p in params:
        param_aliases[p["name"]] = p["name"]
        if "|" in p["name"]:
            for alt in p["name"].split("|"):
                param_aliases[alt] = p["name"]

    # 检查必选参数
    for p in params:
        if p["required"] and not any(a in values for a in param_aliases if param_aliases[a] == p["name"]):
            return "", (f"missing required parameter '{p['name']}' ({keyword}: {entry['file']}). "
                        f"Accepted aliases: {[a for a in param_aliases if param_aliases[a] == p['name']]}")

    # 检查多余参数
    all_aliases = set(param_aliases.keys())
    for k in values:
        if k not in all_aliases:
            return "", (f"unknown parameter '{k}'; parameters of {keyword}: "
                        f"{list(p['name'] for p in params)} (accepted aliases: {sorted(all_aliases)})")

    used_keys = set()
    skipped = []
    for p in params:
        key = param_aliases.get(p["name"], p["name"])
        found_key = None
        for a, canonical in param_aliases.items():
            if canonical == p["name"] and a in values:
                found_key = a
                break
        if found_key:
            if skipped:
                unapplied = [k for k in values if k not in used_keys]
                return "", (f"cannot set '{unapplied[0]}': the preceding optional parameters "
                            f"{skipped} were not provided. CLI parameters are positional — to "
                            f"fill a later one, every earlier one must be filled first")
            val = values[found_key]
            used_keys.add(found_key)
            # 枚举校验
            if p["enum"] and not any("_" in e or len(e) > 8 for e in p["enum"]):
                if str(val).lower() not in p["enum"]:
                    return "", (f"value '{val}' for parameter '{p['name']}' is not in the "
                                f"allowed set {p['enum']}")
            # 数值范围校验
            if "range" in p and isinstance(p["range"], tuple):
                try:
                    n = int(str(val).replace(",", ""))
                    lo, hi = p["range"]
                    if n < lo or n > hi:
                        return "", f"value {n} for parameter '{p['name']}' is out of range [{lo}, {hi}]"
                except (ValueError, TypeError):
                    pass
            parts.append(_format_value(val))
        elif p["required"]:
            return "", f"missing required parameter '{p['name']}'"
        else:
            skipped.append(p["name"])

    # 检查完全未使用的值
    unapplied = [k for k in values if k not in used_keys]
    if unapplied:
        return "", (f"unused parameters: {unapplied}. Check the parameter names for typos, or "
                    f"whether an earlier optional parameter was left unfilled")

    return " ".join(parts), None


# ── 工具入口 ──────────────────────────────────────────────


@tool(parse_docstring=True)
def build_command(keyword: str, values_json: str = "{}") -> str:
    """Deterministic command builder: generate an APV CLI command from the manual grammar —
    the LLM supplies only parameter values; the command structure is guaranteed by the tool.

    Usage: after grepping the manual for a command's syntax, do not hand-write the command;
    generate it with this tool.

    Args:
        keyword: Command keyword, e.g. "slb virtual http", "slb real tcp", "slb group method".
            Must be a complete command name that actually exists in the manual (matched
            against an index of 660+ commands).
        values_json: JSON string mapping parameter name → value.
            Take parameter names from the grepped manual syntax line (the name part inside
            `_<name>_` or `[name]`). Optional parameters may be omitted — the tool skips
            unprovided optional parameters automatically.

    Returns:
        The generated command string, or an error message (missing parameter / bad type /
        illegal enum value).
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return "error: keyword is required (e.g. 'slb virtual http')"

    try:
        values = json.loads(values_json) if values_json and values_json.strip() else {}
    except json.JSONDecodeError as e:
        return f"error: failed to parse values_json: {e}"

    cmd, err = _build(keyword, values)
    if err:
        return f"error: {err}"
    return cmd
