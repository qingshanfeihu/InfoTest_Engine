from __future__ import annotations

import main.qa_agent.tools.deepagent._range_reader as range_reader
import main.qa_agent.tools.deepagent.file_tools as file_tools
from main.qa_agent.tools.deepagent._rg import RipgrepResult


def test_glob_uses_rg_shape_and_keeps_denied_dirs_out(tmp_path, monkeypatch):
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("print('b')\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "hidden.py").write_text("print('hidden')\n", encoding="utf-8")

    out = file_tools.qa_deepagent_glob.invoke({"pattern": "**/*.py", "max_results": 1})

    assert "pkg/" in out
    assert ".venv" not in out
    assert "truncated" in out


def test_grep_supports_files_content_and_count_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("alpha\nneedle one\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.txt").write_text("needle two\n", encoding="utf-8")
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
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        file_tools,
        "run_ripgrep",
        lambda *_args, **_kwargs: RipgrepResult(lines=[], unavailable=True, returncode=127),
    )
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")

    out = file_tools.qa_deepagent_grep.invoke({"pattern": "needle", "output_mode": "content"})

    assert "a.py:1: needle" in out


def test_read_file_streams_line_range_for_large_files(tmp_path, monkeypatch):
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(range_reader, "FAST_PATH_MAX_SIZE", 1)
    target = tmp_path / "large.txt"
    target.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")

    out = file_tools.qa_deepagent_read_file.invoke({"path": "large.txt", "offset": 2, "limit": 2})

    assert "total_lines=5, offset=2, returned=2, next_offset=4" in out
    assert "3: three" in out
    assert "4: four" in out
    assert "1: one" not in out
