"""锁住两类 TUI 渲染修复:

1. 缩进保留软换行(output._apply_write):⎿ 工具结果块的续接长行软换行后,续接段
   要对齐到本行的前导缩进列(和 Claude Code 一致),而不是回到第 0 列把行尾字
   (用户报的"线")甩到最左列;⎿ 块外无缩进的普通行软换行仍回第 0 列。

2. 滚动整屏重画不闪(app._repaint_full vs _force_full_render):滚动走 render_full
   逐格重写,**不** emit erase(\\x1b[2J),故无"清空→重画"的全屏空白闪烁;Ctrl+L 的
   显式核爆重画(_force_full_render)仍 erase。

3. transcript._content_height_rows 的可视行数估算与缩进保留换行一致(续接行可用宽
   = width - 缩进),否则长缩进行被低估、滚动到底差一截。
"""

from __future__ import annotations

from main.ist_core.ink.output import Output
from main.ist_core.ink.screen import CharPool, Screen, StylePool


def _render(msg: str, W: int = 40, H: int = 8):
    cp, sp = CharPool(), StylePool()
    scr = Screen(W, H, cp, sp)
    out = Output(W, H, cp, sp, scr)
    out.write(0, 0, msg)
    out.apply()
    return scr, cp


def _first_nonspace_col(scr: Screen, cp: CharPool, y: int) -> int:
    for x in range(scr.width):
        c = cp.get(scr.get_cell(x, y).char_id)
        if c and c != " ":
            return x
    return -1


# ---- 1. 缩进保留软换行 ----

def test_indented_tool_result_softwrap_preserves_indent():
    # ⎿ 续接行有 5 空格缩进,内容长到必软换行;溢出段必须对齐到 col 5,不落 col 0。
    msg = "   ⎿ total_lines=1\n     " + ("x" * 60)
    scr, cp = _render(msg, W=40, H=8)
    # y0=⎿首行, y1=续接首段(col5 起), y2=软换行溢出段
    assert _first_nonspace_col(scr, cp, 1) == 5
    assert _first_nonspace_col(scr, cp, 2) == 5, "续接软换行未对齐缩进,溢到了最左列(线 bug)"


def test_non_indented_line_softwrap_goes_to_col0():
    # ⎿ 块外无缩进长行:软换行续接从第 0 列另起。
    scr, cp = _render("x" * 60, W=40, H=8)
    assert _first_nonspace_col(scr, cp, 0) == 0
    assert _first_nonspace_col(scr, cp, 1) == 0


def test_deep_indent_softwrap_aligns_to_indent():
    # 20 空格深缩进 + 内容,可用续接宽 = 40-20 = 20。
    msg = (" " * 20) + ("x" * 40)
    scr, cp = _render(msg, W=40, H=8)
    assert _first_nonspace_col(scr, cp, 0) == 20
    assert _first_nonspace_col(scr, cp, 1) == 20


# ---- 2. 滚动整屏重画不闪 / Ctrl+L 仍 erase ----

_ERASE_ALL = "\x1b[2J"


def _make_app(monkeypatch):
    from main.ist_core.ink import app as app_mod

    class FakeTerm:
        def __init__(self, *a, **k):
            self.writes: list[str] = []
            self.columns = 80
            self.rows = 24
            self.input_fd = 0

        def write(self, s: str) -> None:
            self.writes.append(s)

        def set_raw_mode(self, enable: bool) -> None:  # noqa: D401
            pass

        def restore(self) -> None:
            pass

    monkeypatch.setattr(app_mod, "Terminal", FakeTerm)
    return app_mod.InkApp(alt_screen=False)


def test_scroll_repaint_emits_no_erase_no_flicker(monkeypatch):
    app = _make_app(monkeypatch)
    app._terminal.writes.clear()
    app._repaint_full()
    out = "".join(app._terminal.writes)
    assert out, "_repaint_full 应产出一帧"
    assert _ERASE_ALL not in out, "滚动重画不应 erase 整屏(那会每次滚动闪一下)"


def test_ctrl_l_force_render_still_erases(monkeypatch):
    app = _make_app(monkeypatch)
    app._terminal.writes.clear()
    app._force_full_render()
    out = "".join(app._terminal.writes)
    assert _ERASE_ALL in out, "Ctrl+L 显式核爆重画仍应 erase 以救回任何残影"


# ---- 3. transcript 行高估算缩进感知 ----

def test_content_height_accounts_for_indent():
    from main.ist_core.ink.components.transcript import Transcript

    t = Transcript()
    t.node.rect.width = 40
    t.node.rect.height = 10
    # 20 空格缩进 + 60 字符 → 可视宽 80。续接宽 = 40-20 = 20。
    # 首行 40 列,余 40 列按续接宽 20 分 → 1 + ceil(40/20) = 3 行(naive ceil(80/40)=2 会低估)。
    t.append_message((" " * 20) + ("x" * 60))
    assert t._content_height_rows() == 3
