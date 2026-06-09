"""Dream task 主流程：orient → gather → consolidate → prune。"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from main.ist_core.memory import dream
from main.ist_core.memory.backend import build_memory_backend
from main.ist_core.memory.store import MemoryStore


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
    
    agents_text = "---\nname: AGENTS\n---\n# 项目指令\n- 旧规则一条\n"
    (isolated_root / "AGENTS.md").write_text(agents_text, encoding="utf-8")
    store.sync_agents_md_to_backend()
    return backend, store





def test_orient_returns_inventory(populated_store):
    backend, store = populated_store
    
    store.upsert_long_term("/memories/preferences.md", "- 偏好 1\n", mode="append")
    store.upsert_long_term(
        "/memories/feedback/x.md", "- 反馈 1\n", mode="append"
    )
    task = dream.DreamTask(store=store, llm_chat=None)
    inv = task.orient()
    paths = [p for p, _ in inv.files]
    
    assert "/memories/AGENTS.md" not in paths
    assert any("preferences" in p for p in paths)
    assert any("feedback" in p for p in paths)





def test_gather_reads_recent_payloads(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- pref 1\n")
    task = dream.DreamTask(store=store, llm_chat=None)
    inv = task.orient()
    payloads = task.gather(inv)
    assert any("pref 1" in p.content for p in payloads)





def test_build_dream_consolidate_llm_uses_openai_compat_endpoint(monkeypatch):
    """统一走 OpenAI 兼容端点：用 OPENAI_API_KEY / OPENAI_BASE_URL / IST_MODEL。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("IST_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("IST_REVIEW_MODEL", raising=False)

    with mock.patch("main.function_llm.chat_completion") as mock_cc:
        mock_cc.return_value = []
        llm = dream.build_dream_consolidate_llm()
        assert llm is not None
        out = llm('{"action":"skip"}')
        assert out == "[]"
        mock_cc.assert_called_once()
        _session, api_key, system, user = mock_cc.call_args[0]
        assert api_key == "sk-test-openai"
        assert mock_cc.call_args.kwargs["model"] == "deepseek-v4-pro"
        assert mock_cc.call_args.kwargs["base_url"] == "https://api.deepseek.com"


def test_build_dream_consolidate_llm_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert dream.build_dream_consolidate_llm() is None


def test_consolidate_skips_when_no_llm(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- p\n")
    task = dream.DreamTask(store=store, llm_chat=None)
    inv = task.orient()
    payloads = task.gather(inv)
    decisions = task.consolidate(payloads)
    
    assert any("skip" in d for d in decisions)


def test_consolidate_appends_to_agents_md(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- p\n")

    # 真实端点开 response_format=json_object，只能返回顶层对象 {"decisions": [...]}
    def fake_llm(prompt: str) -> str:
        return '{"decisions":[{"action":"append_agents_md","content":"- 新规则 from dream"}]}'

    task = dream.DreamTask(store=store, llm_chat=fake_llm)
    inv = task.orient()
    payloads = task.gather(inv)
    decisions = task.consolidate(payloads)
    assert any("append_agents_md" in d for d in decisions)
    new_agents = (task._store.agents_md_disk_path()).read_text(encoding="utf-8")
    assert "新规则 from dream" in new_agents


def test_coerce_decisions_handles_json_object_shapes():
    """response_format=json_object 下模型只能返回对象，归一化要兼容多种形态。"""
    assert dream._coerce_decisions({"decisions": [{"action": "skip"}]}) == [{"action": "skip"}]
    # 模型直接返回单个动作对象
    assert dream._coerce_decisions({"action": "skip"}) == [{"action": "skip"}]
    # 顶层 list 兜底
    assert dream._coerce_decisions([{"action": "skip"}]) == [{"action": "skip"}]
    # 无关 / 非法形态 → 空（视为无操作）
    assert dream._coerce_decisions({"foo": "bar"}) == []
    assert dream._coerce_decisions("not json") == []
    assert dream._coerce_decisions({"decisions": "notlist"}) == []


def test_consolidate_handles_invalid_llm_output(populated_store):
    backend, store = populated_store
    store.upsert_long_term("/memories/preferences.md", "- p\n")

    def bad_llm(prompt: str) -> str:
        return "this is not valid json"

    task = dream.DreamTask(store=store, llm_chat=bad_llm)
    inv = task.orient()
    payloads = task.gather(inv)
    decisions = task.consolidate(payloads)
    
    assert any("error" in d.lower() or "skip" in d.lower() for d in decisions)





def test_run_releases_lock_and_marks_last_run(populated_store, monkeypatch):
    backend, store = populated_store
    
    counter_path = dream._dream_root() / "session_count"
    counter_path.write_text("10", encoding="utf-8")
    ok, reason = dream.should_run_dream()
    assert ok is True, reason

    task = dream.DreamTask(store=store, llm_chat=None)
    report = task.run()
    assert report.duration_s >= 0
    
    assert dream._last_run_path().exists()
    
    assert dream.read_session_counter() == 0


def test_run_swallow_orient_exception(populated_store):
    backend, store = populated_store

    class _BoomBackend:
        def __getattr__(self, name):
            raise RuntimeError("backend down")

    task = dream.DreamTask(store=store, llm_chat=None)
    
    store._backend = _BoomBackend()
    report = task.run()
    
    assert report.orient_count == 0
