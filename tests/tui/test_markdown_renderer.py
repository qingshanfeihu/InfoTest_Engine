"""markdown 渲染可读性门:代码块前景色必须由终端主题解色。

实证(2026-07-06 CNAME 复盘 #4):render_final 曾用 code_theme="monokai"——真彩主题
给代码行涂固定 24-bit 前景(裸围栏也涂 248,248,242 浅灰白),背景又被 _strip_bg_sgr
剥掉,浅色终端上 device_context 围栏段整块近乎不可见。ANSI 系主题对裸围栏不加前景、
带语言时用基础 ANSI 色,由终端调色板保证深浅主题可读。
"""

from __future__ import annotations

import re

from main.ist_core.ink.components.markdown_renderer import MarkdownRenderer

_TRUECOLOR_FG_RE = re.compile(r"\x1b\[[0-9;]*38;2;")
_BG_RE = re.compile(r"\x1b\[[0-9;]*4[0-7]m|\x1b\[[0-9;]*48;")

_DEVICE_CTX_MD = """执行回显:
```
sdns pool member add cname_pool cname.a.com
show statistics sdns pool cname_pool
```
"""

_PY_MD = """```python
x = 1  # comment
```
"""


def test_render_final_code_block_no_truecolor_foreground():
    out = MarkdownRenderer(width=60).render_final(_DEVICE_CTX_MD)
    assert "sdns pool member add cname_pool" in out
    assert not _TRUECOLOR_FG_RE.search(out), (
        "代码块含 24-bit 真彩前景(monokai 特征)——固定 RGB 不随终端主题变,"
        "浅色终端上剥背景后不可见")


def test_render_final_lang_block_no_truecolor_and_no_bg():
    out = MarkdownRenderer(width=60).render_final(_PY_MD)
    assert "x = " in out
    assert not _TRUECOLOR_FG_RE.search(out)
    assert not _BG_RE.search(out), "背景 SGR 应被 _strip_bg_sgr 剥净(灰块阴影回归)"


def test_streaming_code_block_uses_basic_ansi():
    out = MarkdownRenderer(width=60).render_streaming(_DEVICE_CTX_MD)
    assert "\x1b[36msdns pool member add cname_pool cname.a.com\x1b[0m" in out
