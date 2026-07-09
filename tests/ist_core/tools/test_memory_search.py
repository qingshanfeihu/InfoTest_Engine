"""kb_memory_search 回归(2026-07-05):FTS5/BM25 拉式记忆检索。

守:CJK bigram 命中、ASCII 命中、层过滤、懒 reconcile(删文件即出索引)、
top1 带正文(memory/ 不在文件工具沙箱内,内容必须由工具带回)、无命中口径。
"""

from __future__ import annotations

import pytest

import main.ist_core.tools.knowledge.memory_search as ms


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    (root / "long_term" / "feedback").mkdir(parents=True)
    (root / "working").mkdir(parents=True)
    (root / "long_term" / "feedback" / "crash-gate.md").write_text(
        "## 必崩门教训\nfound_times 会崩整份 pytest,框架只传 2 参。autoid 203031753342777976。",
        encoding="utf-8")
    (root / "working" / "session-note.md").write_text(
        "今天调了 TUI 渲染,和编译无关。", encoding="utf-8")
    monkeypatch.setattr(ms, "_memory_root", lambda: root)
    monkeypatch.setattr(ms, "_index_db_path", lambda: tmp_path / "idx.sqlite")
    return root


def test_cjk_bigram_hit_with_body(mem):
    out = ms.kb_memory_search.invoke({"query": "必崩"})
    assert "crash-gate.md" in out
    assert "found_times 会崩整份 pytest" in out   # top1 带正文
    assert "do not fs_read" in out                 # 沙箱口径提示


def test_ascii_token_hit(mem):
    out = ms.kb_memory_search.invoke({"query": "found_times"})
    assert "crash-gate.md" in out


def test_rare_token_ranks_target_first(mem):
    out = ms.kb_memory_search.invoke({"query": "777976"})
    assert out.index("crash-gate.md") < len(out)
    assert "session-note.md" not in out.split("[2]")[0] or "session-note" not in out


def test_layer_filter(mem):
    out = ms.kb_memory_search.invoke({"query": "必崩", "layer": "working"})
    assert "No hits" in out or "crash-gate" not in out


def test_no_hit_is_honest(mem):
    out = ms.kb_memory_search.invoke({"query": "量子纠缠"})
    assert "No hits" in out


def test_reconcile_removes_deleted(mem):
    assert "crash-gate.md" in ms.kb_memory_search.invoke({"query": "必崩"})
    (mem / "long_term" / "feedback" / "crash-gate.md").unlink()
    out = ms.kb_memory_search.invoke({"query": "必崩"})
    assert "crash-gate.md" not in out


def test_hidden_dirs_not_indexed(mem):
    d = mem / ".dream"
    d.mkdir()
    (d / "secret.md").write_text("必崩隐藏内容", encoding="utf-8")
    out = ms.kb_memory_search.invoke({"query": "隐藏内容"})
    assert "secret.md" not in out
