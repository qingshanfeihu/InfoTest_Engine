"""Stage 5 markdown_section 解析器测试。

cluade.md 验收标杆：5 大节（一/二/三/四/五）+ ~15 子节 + P0/P1/P2/P3 高亮。
单测覆盖：split_into_sections / split_subsections / extract_priorities /
priority_summary_line / should_collapse 五个核心函数。
"""

from __future__ import annotations

from main.qa_agent.tui.markdown_section import (
    extract_priorities,
    priority_summary_line,
    should_collapse,
    split_into_sections,
    split_subsections,
)


# ---------------------------------------------------------------------------
# split_into_sections
# ---------------------------------------------------------------------------


CLUADE_LIKE_REPORT = """\
# 静态评审过程和结果

## 一、整体结论

用例覆盖 273 行...

## 二、严重问题（建议必改）

### 1. 边界用例描述与期望矛盾

#26/#27 的描述完全相同...

### 2. 安全维度大面积缺失

加密能力的核心风险没有被覆盖。

## 三、覆盖缺口（建议补充）

| 类别 | 缺失项 |
|---|---|
| 安全 | 篡改 cookie、伪造 cookie |

## 四、测试设计 / 规范问题

ID 列基本为空。

## 五、建议优先级

| 优先级 | 动作 |
|---|---|
| P0 | 修正描述歧义，补 Bug 121100 原始场景 |
| P1 | 补 HTTPS/HTTP2、IPv6、SameSite |
| P2 | 拆分 Pre/Steps/Expected |
| P3 | 修正拼写、Stress 时长 |
"""


def test_split_into_sections_finds_5_top_sections():
    sections = split_into_sections(CLUADE_LIKE_REPORT)
    top = [s for s in sections if s.level == 2]
    assert len(top) == 5
    titles = [s.title for s in top]
    assert "一、整体结论" in titles
    assert "二、严重问题（建议必改）" in titles
    assert "五、建议优先级" in titles


def test_split_into_sections_preserves_prelude():
    """``# 一级标题`` 和正文之前的内容应保留作 level=0 段。"""
    sections = split_into_sections(CLUADE_LIKE_REPORT)
    assert sections[0].level == 0
    assert "# 静态评审过程和结果" in sections[0].body


def test_split_into_sections_no_h2_returns_single_level0():
    text = "# Title\n\nBody only, no H2 here."
    sections = split_into_sections(text)
    assert len(sections) == 1
    assert sections[0].level == 0


def test_split_into_sections_empty_returns_empty():
    assert split_into_sections("") == []
    assert split_into_sections(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# split_subsections
# ---------------------------------------------------------------------------


def test_split_subsections_extracts_h3_blocks():
    sections = split_into_sections(CLUADE_LIKE_REPORT)
    sec_two = next(s for s in sections if s.title.startswith("二"))
    subs = split_subsections(sec_two.body)
    h3 = [s for s in subs if s.level == 3]
    assert len(h3) == 2
    titles = [s.title for s in h3]
    assert "1. 边界用例描述与期望矛盾" in titles
    assert "2. 安全维度大面积缺失" in titles


def test_split_subsections_no_h3_returns_single_level0():
    sections = split_into_sections(CLUADE_LIKE_REPORT)
    sec_one = next(s for s in sections if s.title.startswith("一"))
    subs = split_subsections(sec_one.body)
    assert len(subs) == 1
    assert subs[0].level == 0


# ---------------------------------------------------------------------------
# extract_priorities + priority_summary_line
# ---------------------------------------------------------------------------


def test_extract_priorities_counts_p0_p3():
    counts = extract_priorities(CLUADE_LIKE_REPORT)
    # 第五节优先级表格各 1 次（P0/P1/P2/P3）
    assert counts.get("P0") == 1
    assert counts.get("P1") == 1
    assert counts.get("P2") == 1
    assert counts.get("P3") == 1


def test_extract_priorities_skips_code_blocks():
    text = """\
```python
P0_BUDGET = 100  # 不应统计
```

P0 必须修复。
"""
    counts = extract_priorities(text)
    assert counts.get("P0") == 1


def test_priority_summary_line_orders_p0_first():
    summary = priority_summary_line({"P3": 5, "P0": 2, "P1": 3, "P2": 1})
    # 期望顺序 P0 -> P1 -> P2 -> P3
    assert summary.startswith("P0×2")
    assert summary.endswith("P3×5")


def test_priority_summary_empty():
    assert priority_summary_line({}) == ""


# ---------------------------------------------------------------------------
# should_collapse
# ---------------------------------------------------------------------------


def test_should_collapse_long_report_with_5_sections():
    """cluade.md 真实报告 ~4-5k 字符；fixture 加长到 >1500 字符确保触发折叠。"""
    extended = CLUADE_LIKE_REPORT + "\n\n" + ("详细说明若干内容点 " * 300)
    assert len(extended) > 1500
    assert should_collapse(extended) is True


def test_should_collapse_short_with_many_sections_returns_false():
    """章节数够，但总字符不足 1500 -> 不折叠（避免短报告被无谓拆开）。"""
    short_with_sections = "## A\n\nx\n\n## B\n\ny\n\n## C\n\nz"
    assert should_collapse(short_with_sections) is False


def test_should_collapse_short_report_returns_false():
    short = "## 节一\n\n短内容\n\n## 节二\n\n更短"
    assert should_collapse(short) is False  # < 1500 chars


def test_should_collapse_long_but_only_2_sections_returns_false():
    long_text = "## 仅一节\n\n" + "x" * 2000
    assert should_collapse(long_text) is False  # < 3 sections


def test_should_collapse_empty_returns_false():
    assert should_collapse("") is False
