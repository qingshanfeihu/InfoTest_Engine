"""markdown_section：长 markdown 自动章节折叠 + P0/P1/P2/P3 token 高亮替换。


src/screens/REPL.tsx 的"pending -> final"切换模式（流式期纯文本，
完成后 Markdown 化）。

cluade.md 验收要点：
- 5 大节（一/二/三/四/五）+ ~15 子节（1./2./3./...） 一次刷屏不可读
- P0/P1/P2/P3 优先级标注必须高亮（红/橙/黄/灰）

实现方式：
- 检测 ``## ``、``### `` 标题分章 -> 每节包 Collapsible，标题作 summary
- ``# `` 顶层标题保持原样不折叠
- 高亮：用 Rich BBCode 标签（``[#priority-p0]P0[/]``）通过 Markdown 不一定生效，
  改用 ``rich.markup`` 直接转义后用 ``Static`` 显示首行带高亮的"概览条"。
  Markdown 内的 ``P0/P1/P2/P3`` 在 Markdown widget 里仍是普通文本，
  我们额外加一行"优先级摘要条"显示彩色 chip。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


# ``## 一、整体结论`` / ``### 1. 边界用例描述与期望矛盾`` 等
_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)

# 优先级 token：cluade.md 第五节用表格 ``| P0 | ... |``
_PRIORITY_RE = re.compile(r"\b(P[0-3])\b")


@dataclass
class MarkdownSection:
    """章节切片。``level=2`` 是 ``## `` 节，``level=3`` 是 ``### `` 子节。"""

    level: int
    title: str
    body: str

    @property
    def is_top_section(self) -> bool:
        return self.level == 2


def split_into_sections(markdown: str) -> List[MarkdownSection]:
    """把长 markdown 切成有序章节列表。

    切分规则：
    - 单个 ``# `` 一级标题（如果有）保留在第一段的 body 顶部，不单独成节
    - 每个 ``## `` 标题开启一个 level=2 的章节，包含其下所有内容（包括嵌套 ``### ``）
    - level=3 由调用方按需进一步切（``split_subsections``）

    返回顺序与 markdown 原顺序一致。Empty 输入返回 ``[MarkdownSection(level=0, title="", body="")]``。
    """
    if not markdown:
        return []

    matches = list(_H2_RE.finditer(markdown))
    sections: List[MarkdownSection] = []
    if not matches:
        # 无 ## 标题 -> 整段作为一个 level=0 章节，调用方按原样渲染
        return [MarkdownSection(level=0, title="", body=markdown.rstrip())]

    # 第一个 ## 之前的内容（前言 / # 一级标题）
    if matches[0].start() > 0:
        prelude = markdown[: matches[0].start()].rstrip()
        if prelude.strip():
            sections.append(MarkdownSection(level=0, title="", body=prelude))

    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end].rstrip()
        sections.append(MarkdownSection(level=2, title=title, body=body))

    return sections


def split_subsections(body: str) -> List[MarkdownSection]:
    """在一个 level=2 节的 body 内按 ``### `` 切子节。

    返回 list of MarkdownSection(level=3 or 0)；level=0 是子节之前的"导语段"。
    """
    if not body:
        return []
    matches = list(_H3_RE.finditer(body))
    if not matches:
        return [MarkdownSection(level=0, title="", body=body)]

    out: List[MarkdownSection] = []
    if matches[0].start() > 0:
        prelude = body[: matches[0].start()].rstrip()
        if prelude.strip():
            out.append(MarkdownSection(level=0, title="", body=prelude))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sub = body[start:end].rstrip()
        out.append(MarkdownSection(level=3, title=title, body=sub))
    return out


def extract_priorities(markdown: str) -> dict[str, int]:
    """统计 markdown 内 P0/P1/P2/P3 出现次数（不含代码块）。"""
    if not markdown:
        return {}
    # 简单去掉代码块（避免误统计）
    cleaned = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    counts: dict[str, int] = {}
    for m in _PRIORITY_RE.finditer(cleaned):
        token = m.group(1)
        counts[token] = counts.get(token, 0) + 1
    return counts


def priority_summary_line(counts: dict[str, int]) -> str:
    """格式化 ``P0×3  P1×5  P2×2`` 风格的概览条。空时返回空串。"""
    if not counts:
        return ""
    parts: List[str] = []
    for key in ("P0", "P1", "P2", "P3"):
        if key in counts:
            parts.append(f"{key}×{counts[key]}")
    return "  ".join(parts)


def should_collapse(markdown: str, *, min_sections: int = 3, min_chars: int = 1500) -> bool:
    """判断是否值得做章节折叠。

    短报告（无章节、< 1500 字符）直接 Markdown 渲染；长报告才走折叠树。
    cluade.md 报告约 4-5k 字符 + 5 大节，一定会触发。
    """
    if len(markdown or "") < min_chars:
        return False
    sections = split_into_sections(markdown)
    top_sections = [s for s in sections if s.level == 2]
    return len(top_sections) >= min_sections
