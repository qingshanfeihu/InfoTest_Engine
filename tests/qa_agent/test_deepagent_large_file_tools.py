from __future__ import annotations

import pytest

import main.qa_agent.tools.deepagent._range_reader as range_reader
import main.qa_agent.tools.deepagent.file_tools as file_tools
from main.qa_agent.tools.deepagent._rg import RipgrepResult


def _setup_sandbox(tmp_path, monkeypatch):
    """Point both _PROJECT_ROOT and _AGENT_ROOT at a tmp tree.

    Mirrors production layout: _AGENT_ROOT = _PROJECT_ROOT / knowledge / data.
    Returns the agent-root path so tests can drop fixtures inside it.
    """
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    return agent_root


def test_glob_uses_rg_shape_and_keeps_denied_dirs_out(tmp_path, monkeypatch):
    agent_root = _setup_sandbox(tmp_path, monkeypatch)
    (agent_root / "pkg").mkdir()
    (agent_root / "pkg" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (agent_root / "pkg" / "b.py").write_text("print('b')\n", encoding="utf-8")
    # Repo-root .venv must remain invisible to the agent even when present on disk.
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "hidden.py").write_text("print('hidden')\n", encoding="utf-8")

    out = file_tools.qa_deepagent_glob.invoke({"pattern": "**/*.py", "max_results": 1})

    assert "pkg/" in out
    assert ".venv" not in out
    assert "truncated" in out


def test_grep_supports_files_content_and_count_modes(tmp_path, monkeypatch):
    agent_root = _setup_sandbox(tmp_path, monkeypatch)
    (agent_root / "pkg").mkdir()
    (agent_root / "pkg" / "a.py").write_text("alpha\nneedle one\n", encoding="utf-8")
    (agent_root / "pkg" / "b.txt").write_text("needle two\n", encoding="utf-8")
    # Repo-root .venv must not leak into grep results.
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "secret.py").write_text("needle secret\n", encoding="utf-8")

    files = file_tools.qa_deepagent_grep.invoke(
        {"pattern": "needle", "output_mode": "files_with_matches", "head_limit": 10}
    )
    assert "pkg/a.py" in files
    assert "pkg/b.txt" in files
    assert ".venv" not in files

    content = file_tools.qa_deepagent_grep.invoke(
        {"pattern": "needle", "glob": "**/*.py", "output_mode": "content", "head_limit": 10}
    )
    assert "pkg/a.py:2:" in content
    assert "pkg/b.txt" not in content

    counts = file_tools.qa_deepagent_grep.invoke(
        {"pattern": "needle", "output_mode": "count", "head_limit": 10}
    )
    assert "pkg/a.py:1" in counts
    assert "pkg/b.txt:1" in counts


def test_grep_falls_back_to_python_when_rg_unavailable(tmp_path, monkeypatch):
    agent_root = _setup_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(
        file_tools,
        "run_ripgrep",
        lambda *_args, **_kwargs: RipgrepResult(lines=[], unavailable=True, returncode=127),
    )
    (agent_root / "a.py").write_text("needle\n", encoding="utf-8")

    out = file_tools.qa_deepagent_grep.invoke({"pattern": "needle", "output_mode": "content"})

    assert "a.py:1: needle" in out


def test_read_file_streams_line_range_for_large_files(tmp_path, monkeypatch):
    agent_root = _setup_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(range_reader, "FAST_PATH_MAX_SIZE", 1)
    target = agent_root / "large.txt"
    target.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")

    out = file_tools.qa_deepagent_read_file.invoke({"path": "large.txt", "offset": 2, "limit": 2})

    assert "total_lines=5, offset=2, returned=2, next_offset=4" in out
    assert "3: three" in out
    assert "4: four" in out
    assert "1: one" not in out


# ---------------------------------------------------------------------------
# Security regression tests — sandbox must hold against platform-code reads.
# ---------------------------------------------------------------------------


def test_ls_does_not_list_repo_root_platform_dirs(tmp_path, monkeypatch):
    agent_root = _setup_sandbox(tmp_path, monkeypatch)
    (agent_root / "markdown").mkdir()
    (agent_root / "markdown" / "ok.md").write_text("ok\n", encoding="utf-8")
    # Plant platform code at repo root that must NOT be visible.
    (tmp_path / "main").mkdir()
    (tmp_path / "main" / "leak.py").write_text("LEAKED\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()

    out = file_tools.qa_deepagent_ls.invoke({"path": "."})

    assert "markdown/" in out
    assert "main/" not in out
    assert "tests/" not in out
    assert "scripts/" not in out
    assert "leak.py" not in out


def test_grep_cannot_reach_main_package(tmp_path, monkeypatch):
    agent_root = _setup_sandbox(tmp_path, monkeypatch)
    # benign content inside the sandbox so grep has somewhere legitimate to look
    (agent_root / "ok.md").write_text("hello\n", encoding="utf-8")
    # secret string under the platform-denied main/ tree
    (tmp_path / "main").mkdir()
    (tmp_path / "main" / "secret.py").write_text("__SECRET_NOT_FOR_AGENT__\n", encoding="utf-8")

    out = file_tools.qa_deepagent_grep.invoke(
        {"pattern": "__SECRET_NOT_FOR_AGENT__", "path": ".", "output_mode": "content"}
    )

    assert "__SECRET_NOT_FOR_AGENT__" not in out
    assert "main/" not in out


def test_read_file_rejects_path_outside_knowledge_data(tmp_path, monkeypatch):
    _setup_sandbox(tmp_path, monkeypatch)
    (tmp_path / "main").mkdir()
    target = tmp_path / "main" / "secret.py"
    target.write_text("LEAKED\n", encoding="utf-8")

    out = file_tools.qa_deepagent_read_file.invoke({"path": "main/secret.py"})

    assert "platform-denied directory: main/" in out
    assert "LEAKED" not in out


def test_glob_pattern_cannot_traverse_up(tmp_path, monkeypatch):
    _setup_sandbox(tmp_path, monkeypatch)

    out = file_tools.qa_deepagent_glob.invoke({"pattern": "../../**/*.py"})

    assert "traversal not allowed" in out


def test_absolute_path_outside_sandbox_rejected(tmp_path, monkeypatch):
    _setup_sandbox(tmp_path, monkeypatch)

    out = file_tools.qa_deepagent_read_file.invoke({"path": "/etc/passwd"})

    assert "outside agent sandbox" in out or "platform-denied" in out


@pytest.mark.parametrize(
    "denied",
    [
        "main",
        "tests",
        "scripts",
        "agent-chat-ui",
        ".venv",
        ".venv311",
        ".git",
        ".langgraph_api",
        ".pytest_cache",
        "memory",
        ".claude",
        ".github",
    ],
)
def test_platform_denylist_blocks_all_listed_dirs(tmp_path, monkeypatch, denied):
    _setup_sandbox(tmp_path, monkeypatch)
    (tmp_path / denied).mkdir()
    (tmp_path / denied / "leak.py").write_text("LEAK\n", encoding="utf-8")

    ls_out = file_tools.qa_deepagent_ls.invoke({"path": denied})
    read_out = file_tools.qa_deepagent_read_file.invoke({"path": f"{denied}/leak.py"})

    assert f"platform-denied directory: {denied}/" in ls_out
    assert f"platform-denied directory: {denied}/" in read_out
    assert "LEAK" not in read_out


@pytest.mark.parametrize(
    "filename",
    [
        "CLAUDE.md",
        "todolist.md",
        "ARCHITECTURE.md",
        "README.md",
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "environment.example",
    ],
)
def test_platform_denylist_blocks_metadata_files(tmp_path, monkeypatch, filename):
    _setup_sandbox(tmp_path, monkeypatch)
    target = tmp_path / filename
    target.write_text("PLATFORM_META\n", encoding="utf-8")

    out = file_tools.qa_deepagent_read_file.invoke({"path": filename})

    assert f"platform metadata file: {filename}" in out
    assert "PLATFORM_META" not in out
