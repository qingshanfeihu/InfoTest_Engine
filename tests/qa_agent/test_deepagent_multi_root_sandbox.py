"""复合沙箱根（_AGENT_ROOTS）回归测试。

覆盖远程 TUI 场景下的多根隔离：
  - knowledge/data/  共享 KMS（所有 session 共享）
  - sessions/<id>/   per-session 临时区（IST_SESSION_DIR env 注入）
  - users/<u>/       per-user 持久区（IST_USER_DIR env 注入）

测试策略：用 monkeypatch 改 _PROJECT_ROOT / _AGENT_ROOT 到 tmp，
再通过 IST_SESSION_DIR / IST_USER_DIR env 注入额外根，
验证：
  1. env 未设置时退化为单根（向后兼容）
  2. session 根可访问，sessions 之间互相隔离
  3. user 根可访问且与 session 根独立
  4. 平台黑名单仍对所有根生效
  5. 路径穿越仍被三闸拦截
"""

from __future__ import annotations

import pytest

import main.qa_agent.tools.deepagent.file_tools as file_tools


def _setup_multi_root(tmp_path, monkeypatch):
    """模拟远程 TUI 部署：knowledge/data + sessions/<id> + users/<u>。

    返回 (agent_root, session_dir, user_dir, project_root)。
    """
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    session_dir = tmp_path / "sessions" / "abc12345"
    session_dir.mkdir(parents=True)
    user_dir = tmp_path / "users" / "zhang_san"
    user_dir.mkdir(parents=True)

    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setenv("IST_SESSION_DIR", str(session_dir))
    monkeypatch.setenv("IST_USER_DIR", str(user_dir))
    return agent_root, session_dir, user_dir, tmp_path


def test_no_env_falls_back_to_single_root(tmp_path, monkeypatch):
    """没设 env 时，沙箱退化为单根，与历史行为一致。"""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)

    roots = file_tools._agent_roots()
    assert roots == (agent_root,)


def test_session_and_user_roots_added_when_env_set(tmp_path, monkeypatch):
    agent_root, session_dir, user_dir, _ = _setup_multi_root(tmp_path, monkeypatch)
    roots = file_tools._agent_roots()
    assert roots == (agent_root, session_dir, user_dir)


def test_session_dir_path_resolves(tmp_path, monkeypatch):
    """session 内的文件可被 _resolve_inside_root 通过。"""
    _, session_dir, _, _ = _setup_multi_root(tmp_path, monkeypatch)
    (session_dir / "markdown").mkdir()
    target = session_dir / "markdown" / "review.md"
    target.write_text("# review", encoding="utf-8")

    resolved = file_tools._resolve_inside_root(str(target), must_exist=True)
    assert resolved == target.resolve()


def test_user_dir_path_resolves(tmp_path, monkeypatch):
    _, _, user_dir, _ = _setup_multi_root(tmp_path, monkeypatch)
    (user_dir / "history").mkdir()
    target = user_dir / "history" / "old_report.md"
    target.write_text("# old", encoding="utf-8")

    resolved = file_tools._resolve_inside_root(str(target), must_exist=True)
    assert resolved == target.resolve()


def test_session_a_cannot_access_session_b(tmp_path, monkeypatch):
    """两个 session 是平级隔离的：A 进程的 env 只指向 A，访问 B 应被拒。"""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    session_a = tmp_path / "sessions" / "aaa"
    session_b = tmp_path / "sessions" / "bbb"
    session_a.mkdir(parents=True)
    session_b.mkdir(parents=True)
    (session_b / "secret.md").write_text("# B's secret", encoding="utf-8")

    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    # 当前进程是 session A，IST_SESSION_DIR 只指向 A
    monkeypatch.setenv("IST_SESSION_DIR", str(session_a))
    monkeypatch.delenv("IST_USER_DIR", raising=False)

    with pytest.raises(PermissionError, match="outside agent sandbox"):
        file_tools._resolve_inside_root(
            str(session_b / "secret.md"), must_exist=True
        )


def test_user_a_cannot_access_user_b(tmp_path, monkeypatch):
    """两个用户的持久目录互不可见。"""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    user_a = tmp_path / "users" / "zhang_san"
    user_b = tmp_path / "users" / "li_si"
    user_a.mkdir(parents=True)
    user_b.mkdir(parents=True)
    (user_b / "preferences.md").write_text("# li_si prefs", encoding="utf-8")

    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setenv("IST_USER_DIR", str(user_a))
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)

    with pytest.raises(PermissionError, match="outside agent sandbox"):
        file_tools._resolve_inside_root(
            str(user_b / "preferences.md"), must_exist=True
        )


def test_platform_denylist_still_blocks_under_multi_root(tmp_path, monkeypatch):
    """即使开启多根，main/、tests/ 等平台目录仍被黑名单拦截。"""
    agent_root, _, _, project_root = _setup_multi_root(tmp_path, monkeypatch)
    (project_root / "main").mkdir()
    (project_root / "main" / "secret.py").write_text("evil", encoding="utf-8")

    with pytest.raises(PermissionError, match="platform-denied"):
        file_tools._resolve_inside_root(
            str(project_root / "main" / "secret.py"), must_exist=True
        )


def test_traversal_still_rejected_under_multi_root(tmp_path, monkeypatch):
    _setup_multi_root(tmp_path, monkeypatch)

    with pytest.raises(PermissionError, match="traversal"):
        file_tools._resolve_inside_root("../../etc/passwd")
    with pytest.raises(PermissionError, match="traversal"):
        file_tools._resolve_inside_root("~/secret")


def test_glob_finds_files_in_session_dir(tmp_path, monkeypatch):
    """qa_deepagent_glob 应该能找到 session 目录下的文件（通过绝对路径）。"""
    _, session_dir, _, _ = _setup_multi_root(tmp_path, monkeypatch)
    (session_dir / "markdown").mkdir()
    (session_dir / "markdown" / "case.md").write_text("# case", encoding="utf-8")

    out = file_tools.qa_deepagent_glob.invoke(
        {"pattern": "**/*.md", "path": str(session_dir), "max_results": 50}
    )
    assert "case.md" in out


def test_read_file_works_for_user_dir(tmp_path, monkeypatch):
    _, _, user_dir, _ = _setup_multi_root(tmp_path, monkeypatch)
    target = user_dir / "preferences.md"
    target.write_text("# zhang_san prefers detailed reviews\n", encoding="utf-8")

    out = file_tools.qa_deepagent_read_file.invoke(
        {"path": str(target), "limit": 50}
    )
    assert "detailed reviews" in out


def test_relative_path_prefers_first_matching_root(tmp_path, monkeypatch):
    """同名相对路径在多根下，按 _agent_roots() 顺序匹配第一个存在的。

    knowledge/data 优先于 session_dir 优先于 user_dir。
    """
    agent_root, session_dir, _, _ = _setup_multi_root(tmp_path, monkeypatch)
    # 在 knowledge/data 和 session_dir 都放一份 same.md
    (agent_root / "same.md").write_text("from kms\n", encoding="utf-8")
    (session_dir / "same.md").write_text("from session\n", encoding="utf-8")

    resolved = file_tools._resolve_inside_root("same.md", must_exist=True)
    assert resolved.read_text() == "from kms\n"


def test_session_only_path_resolved_via_session_root(tmp_path, monkeypatch):
    """只在 session 根存在的相对路径，应能从 session 根解析到。"""
    _, session_dir, _, _ = _setup_multi_root(tmp_path, monkeypatch)
    (session_dir / "outbox").mkdir()
    (session_dir / "outbox" / "report.md").write_text("# report\n", encoding="utf-8")

    resolved = file_tools._resolve_inside_root(
        "outbox/report.md", must_exist=True
    )
    assert resolved == (session_dir / "outbox" / "report.md").resolve()


def test_nonexistent_session_dir_env_ignored(tmp_path, monkeypatch):
    """env 指向不存在的目录时，应被忽略（不破坏沙箱）。"""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setenv("IST_SESSION_DIR", str(tmp_path / "does_not_exist"))
    monkeypatch.delenv("IST_USER_DIR", raising=False)

    roots = file_tools._agent_roots()
    assert roots == (agent_root,)
