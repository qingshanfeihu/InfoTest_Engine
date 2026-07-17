"""CJK 宽字符渲染失同步回归(2026-07-04 V轮乱码取证驱动)。

症状:中文重度界面 + footer/busy 行数字高频微更新,叠影/散落数字/半字(�)持续累积。
根因三件套:① 行末最后一列写宽字符头,物理终端 wrap 污染下一行而网格不知情;
② diff span 起点落在宽字符右半格(spacer),重写右半让终端把整字擦成半字;
③ output._char_width 与 string_width.char_width 两套宽度表不一致,布局与写格列错位。
增量 diff 假设「网格模型==物理终端」,任何一处破裂都是永久残影(模型自身没变,diff
永不重写)。另有 app._do_render_inner 周期性 render_full 自愈兜底(本文件不测帧循环)。
"""
from __future__ import annotations

from main.ist_core.ink.output import Output, _char_width
from main.ist_core.ink.screen import (
    CELL_SPACER,
    CharPool,
    Screen,
    StylePool,
    diff_screens,
    set_cell_style_id,
)
from main.ist_core.ink.string_width import char_width


def _grid(width=10, height=3):
    cp, sp = CharPool(), StylePool()
    scr = Screen(width, height, cp, sp)
    return cp, sp, scr


def test_wide_char_never_heads_last_column():
    # '汉' 恰好落在最后一列 → 必须整字下移到续接行,原位留空格;
    # 否则物理终端把它 wrap 到下一行开头,网格与终端从此失同步。
    cp, sp, scr = _grid()
    out = Output(10, 3, cp, sp, scr)
    out.write(0, 0, "abcdefghi汉", sp.none)
    out.apply()
    assert cp.get(scr.get_cell(9, 0).char_id) in (" ", "")
    assert cp.get(scr.get_cell(0, 1).char_id) == "汉"
    assert scr.get_cell(1, 1).width == CELL_SPACER


def test_diff_span_starting_on_spacer_widens_to_head():
    # span 起点落在宽字符右半格时左扩带上头格——只重写右半会让终端擦掉整个宽字符。
    cp, sp = CharPool(), StylePool()
    prev, curr = Screen(10, 1, cp, sp), Screen(10, 1, cp, sp)
    o1 = Output(10, 1, cp, sp, prev)
    o1.write(0, 0, "汉x", sp.none)
    o1.apply()
    o2 = Output(10, 1, cp, sp, curr)
    o2.write(0, 0, "汉y", sp.none)
    o2.apply()
    set_cell_style_id(curr, 1, 0, sp.intern(["\x1b[1m"]))  # 头相同、右半 style 变
    ops = diff_screens(prev, curr, sp, cp)
    starts = [op.x for op in ops]
    assert all(s != 1 for s in starts), f"span 不得从 spacer 列开始: {starts}"
    assert any(s == 0 for s in starts)


def test_output_and_layout_width_tables_agree():
    # 单一事实源:写格(_char_width)与布局(string_width.char_width)对同一字符判宽必须一致。
    for ch in ("汉", "〇", "ｱ", "Ａ", "·", "…", "✶", "A", "1", "─", "│"):
        assert _char_width(ch) == char_width(ch), ch


def test_textnode_sanitizes_tab_and_cr():
    """控制字符规格化(2026-07-17 team4 实弹:ask 题干携带设备回显的 \t——char_width
    按 1 列布局、终端跳 8 列制表位且不清跳过区,屏显前帧字符碎片叠影)。\t→单空格、
    \r 剥除、\n 保留(wrapped_rows 原生支持)。__init__ 与 set_value 两入口同门。"""
    from main.ist_core.ink.dom import create_text

    t = create_text("a\t\tb\rc")
    assert t.value == "a  bc"
    t.set_value("x\ty\nz\r")
    assert t.value == "x y\nz"
    # 无控制字符:值原样(快速路径)
    t.set_value("干净文本 clean")
    assert t.value == "干净文本 clean"
