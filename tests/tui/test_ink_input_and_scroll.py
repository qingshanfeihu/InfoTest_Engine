"""新版 Ink TUI 移植后补回的交互能力的单元测试。

覆盖：
- shift+enter 在 ESC+CR (alt+enter alias) 与 kitty CSI u (13;2u) 两种序列下的解析
- pageup/pagedown 仍能被解析为 KeyPress
- SGR mouse wheel 解析为 MouseEvent(type='wheel')
- Transcript.scroll_by 的 sticky 状态机：主动滚远后停止 sticky，回到底部恢复
- PromptInput 接受 shift+enter 触发换行（不提交）
"""

from __future__ import annotations

from main.ist_core.ink.components.prompt_input import PromptInput
from main.ist_core.ink.components.transcript import Transcript
from main.ist_core.ink.cursor import CursorManager
from main.ist_core.ink.parse_keypress import (
    InputParser,
    KeyPress,
    MouseEvent,
)


def _feed(parser: InputParser, data: str):
    return parser.feed(data)





def test_shift_enter_parsed_from_alt_enter_sequence():
    p = InputParser()
    events = _feed(p, "\x1b\r")
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, KeyPress)
    assert ev.key == "shift+enter"


def test_shift_enter_parsed_from_kitty_csi_u():
    p = InputParser()
    events = _feed(p, "\x1b[13;2u")
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, KeyPress)
    assert ev.key == "shift+enter"
    assert ev.shift is True


def test_pageup_pagedown_still_parsed():
    p = InputParser()
    events = _feed(p, "\x1b[5~\x1b[6~")
    keys = [e.key for e in events if isinstance(e, KeyPress)]
    assert "pageup" in keys
    assert "pagedown" in keys





def test_unbracketed_multi_line_paste_synthesizes_paste_event():
    """Some terminals/multiplexers/SSH paths strip ESC[200~ markers.
    A run of printable + LF should still be coalesced into a PasteEvent."""
    from main.ist_core.ink.parse_keypress import PasteEvent
    p = InputParser()
    text = "line1\nline2\nline3\nline4"
    events = _feed(p, text)
    pastes = [e for e in events if isinstance(e, PasteEvent)]
    assert len(pastes) == 1
    assert pastes[0].text == text


def test_short_text_run_without_newlines_stays_keypresses():
    from main.ist_core.ink.parse_keypress import PasteEvent
    p = InputParser()
    events = _feed(p, "hi")
    assert all(isinstance(e, KeyPress) for e in events)
    assert not any(isinstance(e, PasteEvent) for e in events)


def test_long_text_run_without_newlines_synthesizes_paste_event():
    from main.ist_core.ink.parse_keypress import PasteEvent
    p = InputParser()
    text = "x" * 100
    events = _feed(p, text)
    pastes = [e for e in events if isinstance(e, PasteEvent)]
    assert len(pastes) == 1
    assert pastes[0].text == text


def test_single_ctrl_j_stays_keypress_for_shift_enter_in_input():
    """Bare Shift+Enter (Ctrl+J) for in-input newline must not be
    swallowed as a paste."""
    p = InputParser()
    events = _feed(p, "\x0a")
    assert len(events) == 1
    assert isinstance(events[0], KeyPress)
    assert events[0].key == "ctrl+j"


def test_sgr_wheel_up_parsed_as_mouse_event():
    p = InputParser()
    
    events = _feed(p, "\x1b[<64;10;5M")
    mouse = [e for e in events if isinstance(e, MouseEvent)]
    assert len(mouse) == 1
    me = mouse[0]
    assert me.type == "wheel"
    assert me.button == 0


def test_sgr_wheel_down_parsed_as_mouse_event():
    p = InputParser()
    events = _feed(p, "\x1b[<65;10;5M")
    mouse = [e for e in events if isinstance(e, MouseEvent)]
    assert len(mouse) == 1
    assert mouse[0].type == "wheel"
    assert mouse[0].button == 1





def test_prompt_input_shift_enter_inserts_newline_marker():
    captured = []
    pi = PromptInput(
        cursor_manager=CursorManager(),
        on_submit=lambda v: captured.append(v),
    )
    pi.set_value("hello")
    consumed = pi.handle_key("shift+enter")
    assert consumed is True
    assert pi.value == "hello↵"
    assert captured == []





def test_transcript_scroll_by_disables_sticky_when_user_scrolls_up():
    t = Transcript()
    
    t.node.rect.height = 10
    t.node.rect.width = 80
    for i in range(50):
        t.append_message(f"line {i}")
    assert t.node.sticky_scroll is True

    t.scroll_by(-5)
    assert t.node.sticky_scroll is False
    assert t.node.scroll_top < 50


def test_transcript_scroll_back_to_bottom_restores_sticky():
    t = Transcript()
    t.node.rect.height = 10
    t.node.rect.width = 80
    for i in range(50):
        t.append_message(f"line {i}")
    t.scroll_by(-5)
    assert t.node.sticky_scroll is False

    
    t.scroll_by(1000)
    assert t.node.sticky_scroll is True


def test_transcript_clear_resets_sticky():
    t = Transcript()
    t.node.rect.height = 10
    t.node.rect.width = 80
    for i in range(50):
        t.append_message(f"line {i}")
    t.scroll_by(-5)
    assert t.node.sticky_scroll is False
    t.clear()
    assert t.node.sticky_scroll is True
    assert t.node.scroll_top == 0
