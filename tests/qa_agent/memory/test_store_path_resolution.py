"""三闸路径校验 + frontmatter 解析。"""

from __future__ import annotations

import pytest

from main.qa_agent.memory.store import MemoryStore


# ---- 闸 1: traversal ----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "/working/../x",
        "~/x",
        "/working/~hidden/x.md",
        "relative.md",  # 必须以 / 开头
        "/etc/passwd",  # 不在 /working/ /memories/ 下
    ],
)
def test_resolve_rejects_traversal_and_outside_paths(bad):
    with pytest.raises(PermissionError):
        MemoryStore._resolve_virtual_path(bad, for_write=True)


# ---- 闸 2: subdir whitelist (写入) ---------------------------------------


@pytest.mark.parametrize(
    "ok",
    [
        "/working/abc.md",
        "/working/thread-id_xyz.md",
        "/memories/AGENTS.md",
        "/memories/preferences.md",
        "/memories/review_conclusions/cookie_21100.md",
        "/memories/feedback/2026-05-llm.md",
    ],
)
def test_resolve_accepts_allowed_paths(ok):
    assert MemoryStore._resolve_virtual_path(ok, for_write=True) == ok


@pytest.mark.parametrize(
    "denied",
    [
        "/memories/random.md",  # 不在写入子目录白名单
        "/memories/scratch/x.md",
    ],
)
def test_resolve_rejects_unlisted_memories_subdirs(denied):
    with pytest.raises(PermissionError):
        MemoryStore._resolve_virtual_path(denied, for_write=True)


# ---- 闸 3: basename 字符 -------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "/working/foo bar.md",
        "/working/中文.md",
        "/memories/preferences.md\\$",
        "/memories/feedback/x;y.md",
    ],
)
def test_resolve_rejects_disallowed_chars(bad):
    with pytest.raises(PermissionError):
        MemoryStore._resolve_virtual_path(bad, for_write=True)


# ---- 读路径放宽 ----------------------------------------------------------


def test_resolve_read_path_loosens_subdir_whitelist():
    # 读路径不强制 subdir 白名单（只做 traversal + 顶层路由检查）
    assert (
        MemoryStore._resolve_virtual_path("/memories/random.md", for_write=False)
        == "/memories/random.md"
    )


# ---- working_path sanitize ----------------------------------------------


def test_working_path_sanitizes_thread_id():
    assert MemoryStore.working_path("thread-abc-123") == "/working/thread-abc-123.md"
    # 中文 / 空格 / 斜杠都被替换为 _
    p = MemoryStore.working_path("foo bar/zh中文")
    assert p.startswith("/working/")
    assert " " not in p
    assert "/" not in p[len("/working/") :]


def test_working_path_default_for_empty():
    assert MemoryStore.working_path("") == "/working/default.md"


# ---- frontmatter 解析 / 渲染 --------------------------------------------


def test_parse_frontmatter_extracts_fields_and_body():
    text = """---
name: x
keywords: a, b, c
turn_count: 3
---

正文 line1
正文 line2
"""
    fields, body = MemoryStore.parse_frontmatter(text)
    assert fields["name"] == "x"
    assert fields["keywords"] == "a, b, c"
    assert fields["turn_count"] == "3"
    assert body.startswith("正文 line1")


def test_parse_frontmatter_handles_missing_frontmatter():
    fields, body = MemoryStore.parse_frontmatter("naked content\n")
    assert fields == {}
    assert body == "naked content\n"


def test_render_frontmatter_roundtrip():
    fields = {"name": "x", "keywords": "a, b"}
    out = MemoryStore.render_frontmatter(fields)
    parsed, _ = MemoryStore.parse_frontmatter(out + "\n")
    assert parsed["name"] == "x"
    assert parsed["keywords"] == "a, b"


# ---- _file_data_to_str 兼容 --------------------------------------------


def test_file_data_to_str_v2():
    fd = {"content": "hello", "encoding": "utf-8"}
    assert MemoryStore._file_data_to_str(fd) == "hello"


def test_file_data_to_str_v1_legacy_list():
    fd = {"content": ["line1", "line2"]}
    assert MemoryStore._file_data_to_str(fd) == "line1\nline2"


def test_file_data_to_str_none_safe():
    assert MemoryStore._file_data_to_str(None) == ""
