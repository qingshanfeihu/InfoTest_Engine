"""Markdown → ANSI renderer with two-phase strategy.

- Streaming phase: fast regex-based rendering (handles partial/unclosed blocks)
- Final phase: Rich Markdown for complete, syntax-highlighted output
"""

from __future__ import annotations

import re

_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_UNDERLINE = "\x1b[4m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"

_NON_SGR_RE = re.compile(r"\x1b\[[0-9;]*[^m0-9;\x1b]")
_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_HR_RE = re.compile(r"^(\s*)([-*_])\s*\2\s*\2[\s\2]*$")
_OL_RE = re.compile(r"^(\s*)\d+\.\s+(.+)$")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_QUOTE_RE = re.compile(r"^(\s*)>\s?(.*)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


class MarkdownRenderer:
    def __init__(self, width: int = 80):
        self._width = max(width, 20)

    def set_width(self, width: int) -> None:
        self._width = max(width, 20)

    def render_streaming(self, text: str) -> str:
        if not text:
            return ""
        lines = text.split("\n")
        result: list[str] = []
        in_code = False
        code_lines: list[str] = []
        code_lang = ""

        for line in lines:
            fence_m = _FENCE_RE.match(line)
            if fence_m:
                if in_code:
                    result.append(self._fmt_code_block(code_lines, code_lang))
                    code_lines = []
                    code_lang = ""
                    in_code = False
                else:
                    in_code = True
                    code_lang = fence_m.group(1)
                continue
            if in_code:
                code_lines.append(line)
                continue
            result.append(self._render_line(line))

        if in_code:
            lang_tag = f"{_DIM}```{code_lang}{_RESET}" if code_lang else f"{_DIM}```{_RESET}"
            result.append(lang_tag)
            for cl in code_lines:
                result.append(f"  {_CYAN}{cl}{_RESET}")

        return "\n".join(result)

    def _render_line(self, line: str) -> str:
        hm = _HEADER_RE.match(line)
        if hm:
            level = len(hm.group(1))
            text = self._inline(hm.group(2))
            if level == 1:
                return f"{_BOLD}{_UNDERLINE}{text}{_RESET}"
            elif level == 2:
                return f"{_BOLD}{text}{_RESET}"
            else:
                return f"{_BOLD}{_DIM}{text}{_RESET}"

        if _HR_RE.match(line):
            return f"{_DIM}{'─' * min(self._width, 40)}{_RESET}"

        qm = _QUOTE_RE.match(line)
        if qm:
            indent = qm.group(1)
            content = self._inline(qm.group(2))
            return f"{indent}{_DIM}│{_RESET} {content}"

        ol_m = _OL_RE.match(line)
        if ol_m:
            indent = ol_m.group(1)
            num_prefix = line[len(indent):].split(".", 1)[0]
            content = self._inline(ol_m.group(2))
            return f"{indent}{num_prefix}. {content}"

        ul_m = _UL_RE.match(line)
        if ul_m:
            indent = ul_m.group(1)
            content = self._inline(ul_m.group(2))
            return f"{indent}• {content}"

        return self._inline(line)

    def _inline(self, text: str) -> str:
        text = _BOLD_RE.sub(lambda m: f"{_BOLD}{m.group(1) or m.group(2)}{_RESET}", text)
        text = _INLINE_CODE_RE.sub(lambda m: f"{_CYAN}{m.group(1)}{_RESET}", text)
        text = _LINK_RE.sub(
            lambda m: f"{_UNDERLINE}{m.group(1)}{_RESET} {_DIM}({m.group(2)}){_RESET}",
            text,
        )
        return text

    def _fmt_code_block(self, lines: list[str], lang: str) -> str:
        parts: list[str] = []
        if lang:
            parts.append(f"{_DIM}┌─ {lang}{_RESET}")
        else:
            parts.append(f"{_DIM}┌─{_RESET}")
        for ln in lines:
            parts.append(f"  {_CYAN}{ln}{_RESET}")
        parts.append(f"{_DIM}└─{_RESET}")
        return "\n".join(parts)

    def render_final(self, text: str) -> str:
        if not text:
            return ""
        try:
            return self._rich_render(text)
        except Exception:
            return self.render_streaming(text)

    def _rich_render(self, text: str) -> str:
        from io import StringIO
        from rich.console import Console
        from rich.markdown import Markdown

        buf = StringIO()
        console = Console(
            file=buf,
            width=self._width,
            force_terminal=True,
            no_color=False,
            highlight=False,
        )
        md = Markdown(text, code_theme="monokai")
        console.print(md, end="")
        rendered = buf.getvalue()
        rendered = _NON_SGR_RE.sub("", rendered)
        return rendered.rstrip("\n")
