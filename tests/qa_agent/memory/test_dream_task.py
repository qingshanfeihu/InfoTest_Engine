"""Dream task 主流程：orient → gather → consolidate → prune。"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from main.qa_agent.memory import dream
from main.qa_agent.memory.backend import build_memory_backend
from main.qa_agent.memory.store import MemoryStore


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setenv("IST_MEMORY_ROOT", str(tmp_path / "memory"))
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    dream._release_pid_lock()
    yield tmp_path / "memory"
    dream._release_pid_lock()


@pytest.fixture
def populated_store(isolated_root):
    """构造一个带 AGENTS.md + 几条 long-term 记忆的 store。"""
    backend = build_memory_backend()
    store = MemoryStore(backend, isolated_root)
    # 写 AGENTS.md（磁盘），sync 到 backend
    agents_text = "---\nname: AGENTS\n---\n# 项目指令\n- 旧规则一条\n"
    (isolated_root / "AGENTS.md").write_text(agents_text, encoding="utf-8")
    store.sync_agents_md_to_backend()
    return backend, store


# ---- DreamTask.orient ---------------------------------------------------


def test_orient_returns_inventory(populated_store):
    backend, store = populated_store
    # 写一些 /memories/ 文件
    store.upsert_long_term("/memories/preferences.md", "- 偏好 1\n", mode="append")
    store.upsert_long_term(
        "/memories/feedback/x.md", "- 反馈 1\n", mode="append"
    )
    task = dream.DreamTask(store=store, llm_chat=None)
    inv = task.orient()
    paths = [p for p, _ in inv.files]
    # AGENTS.md 应被 orient 排除（由 dream 单独管理）
    assert "/memories/AGENTS.md" not in paths
    assert any("preferences" in p for p in paths)
    assert any("feedback" in p for p in paths)


# ---- DreamTask.gather ---------------------------------------------------


def test_gather_reads_recent_payloads(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- pref 1\n")
    task = dream.DreamTask(store=store, llm_chat=None)
    inv = task.orient()
    payloads = task.gather(inv)
    assert any("pref 1" in p.content for p in payloads)


# ---- DreamTask.consolidate -----------------------------------------------


def test_build_dream_consolidate_llm_uses_deepseek_provider(monkeypatch):
    """IST_LLM_PROVIDER=deepseek 时应走 DEEPSEEK_API_KEY，而非仅 DASHSCOPE。"""
    monkeypatch.setenv("IST_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("IST_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with mock.patch("main.function_llm.chat_completion") as mock_cc:
        mock_cc.return_value = []
        llm = dream.build_dream_consolidate_llm()
        assert llm is not None
        out = llm('{"action":"skip"}')
        assert out == "[]"
        mock_cc.assert_called_once()
        _session, api_key, system, user = mock_cc.call_args[0]
        assert api_key == "sk-test-deepseek"
        assert mock_cc.call_args.kwargs["model"] == "deepseek-v4-pro"
        assert mock_cc.call_args.kwargs["base_url"] == "https://api.deepseek.com"


def test_build_dream_consolidate_llm_none_without_key(monkeypatch):
    monkeypatch.setenv("IST_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    assert dream.build_dream_consolidate_llm() is None


def test_consolidate_skips_when_no_llm(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- p\n")
    task = dream.DreamTask(store=store, llm_chat=None)
    inv = task.orient()
    payloads = task.gather(inv)
    decisions = task.consolidate(payloads)
    # 没 LLM → 报告 skip 而不是写 AGENTS.md
    assert any("skip" in d for d in decisions)


def test_consolidate_appends_to_agents_md(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- p\n")

    # mock LLM 返回一个 append 决策
    def fake_llm(prompt: str) -> str:
        return '[{"action":"append_agents_md","content":"- 新规则 from dream"}]'

    task = dream.DreamTask(store=store, llm_chat=fake_llm)
    inv = task.orient()
    payloads = task.gather(inv)
    decisions = task.consolidate(payloads)
    assert any("append_agents_md" in d for d in decisions)
    new_agents = (task._store.agents_md_disk_path()).read_text(encoding="utf-8")
    assert "新规则 from dream" in new_agents


def test_consolidate_handles_invalid_llm_output(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- p\n")

    def bad_llm(prompt: str) -> str:
        return "this is not valid json"

    task = dream.DreamTask(store=store, llm_chat=bad_llm)
    inv = task.orient()
    payloads = task.gather(inv)
    decisions = task.consolidate(payloads)
    # 不抛异常，返回 error 标记
    assert any("error" in d.lower() or "skip" in d.lower() for d in decisions)


# ---- DreamTask.run 端到端 -----------------------------------------------


def test_run_releases_lock_and_marks_last_run(populated_store, monkeypatch):
    backend, store = populated_store
    # 准备闸条件全部通过
    counter_path = dream._dream_root() / "session_count"
    counter_path.write_text("10", encoding="utf-8")
    ok, reason = dream.should_run_dream()
    assert ok is True, reason

    task = dream.DreamTask(store=store, llm_chat=None)
    report = task.run()
    assert report.duration_s >= 0
    # last_run 已写入
    assert dream._last_run_path().exists()
    # session counter 已重置
    assert dream.read_session_counter() == 0


def test_run_swallow_orient_exception(populated_store):
    backend, store = populated_store

    class _BoomBackend:
        def __getattr__(self, name):
            raise RuntimeError("backend down")

    task = dream.DreamTask(store=store, llm_chat=None)
    # 替换 store._backend 为坏的
    store._backend = _BoomBackend()
    report = task.run()
    # 不抛异常，返回空报告
    assert report.orient_count == 0
