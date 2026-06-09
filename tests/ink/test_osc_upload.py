"""OSC 带外上传信号解析测试。

Web Terminal 上传文件后，web_server 把文件名 base64 包成自定义 OSC 序列
``ESC ] 7001 ; <base64> BEL`` 写进 PTY，ink 解析器识别为 UploadEvent。
这套结构化通道取代"在自由文本里用正则猜文件名"，文件名含任何特殊字符都无损。
"""

from __future__ import annotations

import base64

import pytest

from main.ist_core.ink.parse_keypress import (
    InputParser,
    KeyPress,
    UploadEvent,
)


def _osc(filename: str, terminator: str = "\x07") -> str:
    b64 = base64.b64encode(filename.encode("utf-8")).decode("ascii")
    return f"\x1b]7001;{b64}{terminator}"


@pytest.mark.parametrize(
    "filename",
    [
        "bigip.conf",
        "网关配置指南.pdf",
        "test case 121100.xlsx",          # 含空格
        "weird;name'with\"quotes.txt",   # 含分号/引号
        "附件_v2.docx",
        "a.b.c.json",                      # 多点
    ],
)
def test_upload_roundtrip(filename):
    """任意文件名 base64 往返无损 → UploadEvent.filename 精确还原。"""
    p = InputParser()
    events = p.feed(_osc(filename))
    assert len(events) == 1
    assert isinstance(events[0], UploadEvent)
    assert events[0].filename == filename


def test_upload_with_st_terminator():
    """终止符用 ST（ESC \\）而非 BEL 也能解析。"""
    p = InputParser()
    events = p.feed(_osc("doc.pdf", terminator="\x1b\\"))
    assert len(events) == 1
    assert isinstance(events[0], UploadEvent)
    assert events[0].filename == "doc.pdf"


def test_mixed_keyboard_and_upload():
    """同一输入 batch 里键盘字符 + OSC 上传应正确分流。"""
    p = InputParser()
    events = p.feed("hi" + _osc("a.conf"))
    keys = [e for e in events if isinstance(e, KeyPress)]
    uploads = [e for e in events if isinstance(e, UploadEvent)]
    assert "".join(k.char for k in keys) == "hi"
    assert len(uploads) == 1
    assert uploads[0].filename == "a.conf"


def test_standard_osc_ignored():
    """标准 OSC（如设置标题 OSC 0）不应产出 UploadEvent。"""
    p = InputParser()
    events = p.feed("\x1b]0;some terminal title\x07")
    assert not any(isinstance(e, UploadEvent) for e in events)


def test_unknown_osc_code_ignored():
    """非 7001 的私有 OSC 码忽略。"""
    p = InputParser()
    b64 = base64.b64encode(b"x.txt").decode("ascii")
    events = p.feed(f"\x1b]9999;{b64}\x07")
    assert not any(isinstance(e, UploadEvent) for e in events)


def test_malformed_base64_ignored():
    """payload 不是合法 base64 → 安全忽略，不抛异常。"""
    p = InputParser()
    events = p.feed("\x1b]7001;not!valid!base64!\x07")
    assert not any(isinstance(e, UploadEvent) for e in events)


def test_empty_filename_ignored():
    """空文件名（base64 of ""）忽略。"""
    p = InputParser()
    events = p.feed(_osc(""))
    assert not any(isinstance(e, UploadEvent) for e in events)
