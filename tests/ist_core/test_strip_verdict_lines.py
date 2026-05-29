"""_strip_verdict_lines 同时剥离 VERDICT 与 LEVEL 行."""

from __future__ import annotations

from main.ist_core.graph import _strip_verdict_lines


def test_strip_verdict_and_level_lines():
    text = "报告正文\nVERDICT: FAIL\nLEVEL: P2\n"
    assert _strip_verdict_lines(text) == "报告正文"

    text_bold = "正文\n**VERDICT:** PASS\n**LEVEL:** P0\n"
    assert _strip_verdict_lines(text_bold) == "正文"

    
    assert _strip_verdict_lines("尾\n**VERDICT** : FAIL\n") == "尾"

    mixed = "A\n*VERDICT:* PARTIAL\n  **LEVEL:** P3\nB"
    assert _strip_verdict_lines(mixed) == "A\n\nB"
