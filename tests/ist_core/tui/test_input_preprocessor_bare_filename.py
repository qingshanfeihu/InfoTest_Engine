"""input_preprocessor 裸文件名识别测试。

复现 Web 上传场景：前端把裸文件名（bigip.conf）发进对话框，预处理器需把它
改写成沙箱相对路径，让 agent 知道文件在 workspace/inputs/ 而非反问用户。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main.ist_core.tui.input_preprocessor as pp


@pytest.fixture
def fake_inbox(tmp_path, monkeypatch):
    """把 _DEFAULT_INBOX / _WORKSPACE 指到临时目录，隔离真实 workspace。"""
    workspace = tmp_path / "workspace"
    inbox = workspace / "inputs"
    inbox.mkdir(parents=True)
    monkeypatch.setattr(pp, "_WORKSPACE", workspace)
    monkeypatch.setattr(pp, "_DEFAULT_INBOX", inbox)
    return inbox


def test_bare_filename_rewritten(fake_inbox):
    (fake_inbox / "bigip.conf").write_text("ltm virtual ...", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("bigip.conf请将这个f5配置翻译成APV的配置")
    assert status is not None and status.startswith("⬆")
    assert "inputs/bigip.conf" in mod
    assert mod.startswith("inputs/bigip.conf")


def test_bare_filename_with_space(fake_inbox):
    (fake_inbox / "bigip.conf").write_text("x", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("请翻译 bigip.conf 这个文件")
    assert "inputs/bigip.conf" in mod
    assert status and "bigip.conf" in status


def test_xlsx_resolves_to_converted_md(fake_inbox):
    """上传的 xlsx 会被转成 .md；裸名 foo.xlsx 应解析到 foo.md。"""
    (fake_inbox / "report.md").write_text("| a | b |", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("评审 report.xlsx 用例")
    assert "inputs/report.md" in mod
    assert status is not None


def test_no_match_when_file_absent(fake_inbox):
    """文件不在 inbox → 不改写（避免幻觉路径）。"""
    mod, status = pp.preprocess_file_paths("翻译 不存在.conf 文件")
    assert status is None
    assert mod == "翻译 不存在.conf 文件"


def test_no_false_positive_on_plain_chat(fake_inbox):
    mod, status = pp.preprocess_file_paths("随便聊聊今天天气怎么样")
    assert status is None
    assert mod == "随便聊聊今天天气怎么样"


def test_no_match_on_ascii_continuation(fake_inbox):
    """foo.confbar 不是 foo.conf——ASCII 延续不应被切出文件名。"""
    (fake_inbox / "foo.conf").write_text("x", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("参考 foo.confbar 设置")
    assert status is None
    assert mod == "参考 foo.confbar 设置"


def test_already_sandbox_relative_left_as_is(fake_inbox):
    """已是 workspace/inputs/xxx 形式的不被裸名规则重复改写。"""
    (fake_inbox / "bigip.conf").write_text("x", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("workspace/inputs/bigip.conf 翻译")
    # 该相对路径已在沙箱内，裸名规则的负向边界 (?<![./\\-]) 阻止吃掉 inputs/ 后的部分
    assert "workspace/inputs/bigip.conf" in mod


def test_multiple_bare_filenames(fake_inbox):
    (fake_inbox / "a.conf").write_text("x", encoding="utf-8")
    (fake_inbox / "b.txt").write_text("y", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("对比 a.conf 和 b.txt")
    assert "inputs/a.conf" in mod
    assert "inputs/b.txt" in mod


def test_no_match_on_trailing_hyphen_suffix(fake_inbox):
    """bigip.conf-v2 不是 bigip.conf——连字符后缀不应被切出文件名。"""
    (fake_inbox / "bigip.conf").write_text("x", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("参考 bigip.conf-v2 设置")
    assert status is None
    assert mod == "参考 bigip.conf-v2 设置"


def test_same_bare_filename_replaced_twice(fake_inbox):
    """同一裸名出现两次时都应改写（replace(..., 1) 只会改第一次）。"""
    (fake_inbox / "a.txt").write_text("y", encoding="utf-8")
    mod, status = pp.preprocess_file_paths("先看 a.txt 再看 a.txt")
    assert mod == "先看 inputs/a.txt 再看 inputs/a.txt"
    assert status is not None
