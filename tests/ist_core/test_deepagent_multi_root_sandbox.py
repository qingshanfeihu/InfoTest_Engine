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

import main.ist_core.tools.deepagent.file_tools as file_tools


@pytest.fixture(autouse=True)
def _isolate_framework_mirror(tmp_path, monkeypatch):
    """本文件验 session/user/workspace 根逻辑；框架 mirror 根（真实存在于仓库）正交，
    统一隔离成不存在路径，避免它被追加进 roots 污染精确断言。
    mirror 根本身的注册由 test_framework_mirror_registered_when_exists 单独验。
    """
    monkeypatch.setattr(file_tools, "_FRAMEWORK_MIRROR_ROOT",
                        tmp_path / "no_mirror_here", raising=False)


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
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "workspace_nonexist")
    monkeypatch.setenv("IST_SESSION_DIR", str(session_dir))
    monkeypatch.setenv("IST_USER_DIR", str(user_dir))
    return agent_root, session_dir, user_dir, tmp_path


def test_no_env_falls_back_to_single_root(tmp_path, monkeypatch):
    """没设 env 时，沙箱退化为单根，与历史行为一致。"""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "workspace_nonexist")
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)

    roots = file_tools._agent_roots()
    assert roots == (agent_root,)


def test_framework_mirror_registered_when_exists(tmp_path, monkeypatch):
    """框架源码 mirror 根存在时被注册进只读根（与人工诊断对等：agent 能读 test_xlsx.py 等）。"""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    mirror = tmp_path / "knowledge" / "framework" / "mirror"
    mirror.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "workspace_nonexist")
    monkeypatch.setattr(file_tools, "_FRAMEWORK_MIRROR_ROOT", mirror)  # 覆盖 autouse 隔离
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)
    roots = file_tools._agent_roots()
    assert roots == (agent_root, mirror)


def test_framework_mirror_read_allowlist(tmp_path, monkeypatch):
    """mirror 只放行断言机制白名单文件（lib/test_xlsx.py、lib/check_point.py）；
    含明文口令的 conftest.py/mysqldb.py/apv_ssh.py 与元数据 .sync_meta.json 一律拒
    （默认拒、最小暴露面——安全评审要求）。"""
    mirror = tmp_path / "knowledge" / "framework" / "mirror"
    (mirror / "lib" / "apv").mkdir(parents=True)
    (mirror / "smoke_test").mkdir(parents=True)
    (mirror / "lib" / "check_point.py").write_text("def found(): pass", encoding="utf-8")
    (mirror / "lib" / "test_xlsx.py").write_text("# dispatch", encoding="utf-8")
    (mirror / "lib" / "mysqldb.py").write_text("password='click1'", encoding="utf-8")
    (mirror / "lib" / "apv" / "apv_ssh.py").write_text("passwd='click1'", encoding="utf-8")
    (mirror / "smoke_test" / "conftest.py").write_text("passwd='click1'", encoding="utf-8")
    (mirror / ".sync_meta.json").write_text('{"source":"10.4.127.103"}', encoding="utf-8")
    (tmp_path / "knowledge" / "data").mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", tmp_path / "knowledge" / "data")
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "ws_none")
    monkeypatch.setattr(file_tools, "_FRAMEWORK_MIRROR_ROOT", mirror)  # 覆盖 autouse 隔离
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)
    # 白名单内放行
    assert file_tools._resolve_inside_root(str(mirror / "lib" / "check_point.py"), must_exist=True)
    assert file_tools._resolve_inside_root(str(mirror / "lib" / "test_xlsx.py"), must_exist=True)
    # 含口令/内网元数据一律拒
    for bad in ("lib/mysqldb.py", "lib/apv/apv_ssh.py", "smoke_test/conftest.py", ".sync_meta.json"):
        with pytest.raises(PermissionError):
            file_tools._resolve_inside_root(str(mirror / bad), must_exist=True)


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
    """fs_glob 应该能找到 session 目录下的文件（通过绝对路径）。"""
    _, session_dir, _, _ = _setup_multi_root(tmp_path, monkeypatch)
    (session_dir / "markdown").mkdir()
    (session_dir / "markdown" / "case.md").write_text("# case", encoding="utf-8")

    out = file_tools.fs_glob.invoke(
        {"pattern": "**/*.md", "path": str(session_dir), "max_results": 50}
    )
    assert "case.md" in out


def test_read_file_works_for_user_dir(tmp_path, monkeypatch):
    _, _, user_dir, _ = _setup_multi_root(tmp_path, monkeypatch)
    target = user_dir / "preferences.md"
    target.write_text("# zhang_san prefers detailed reviews\n", encoding="utf-8")

    out = file_tools.fs_read.invoke(
        {"path": str(target), "limit": 50}
    )
    assert "detailed reviews" in out


def test_relative_path_prefers_first_matching_root(tmp_path, monkeypatch):
    """同名相对路径在多根下，按 _agent_roots() 顺序匹配第一个存在的。

    knowledge/data 优先于 session_dir 优先于 user_dir。
    """
    agent_root, session_dir, _, _ = _setup_multi_root(tmp_path, monkeypatch)
    
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
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "workspace_nonexist")
    monkeypatch.setenv("IST_SESSION_DIR", str(tmp_path / "does_not_exist"))
    monkeypatch.delenv("IST_USER_DIR", raising=False)

    roots = file_tools._agent_roots()
    assert roots == (agent_root,)


def test_workspace_inputs_registered_as_root(tmp_path, monkeypatch):
    """workspace/inputs/ 存在时登记为解析根（Web 上传落地区）。"""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", workspace)
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)

    roots = file_tools._agent_roots()
    assert roots == (agent_root, workspace.resolve(), inputs.resolve())


def test_bare_uploaded_filename_resolves_into_inputs(tmp_path, monkeypatch):
    """裸文件名（Web 上传后打进对话框的形式）能解析到 workspace/inputs/。

    回归：Web TUI 上传后只把文件名注入对话框，agent 需用裸名定位上传文件。
    """
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    target = inputs / "cookie_cases.xlsx"
    target.write_bytes(b"PK\x03\x04stub")
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", workspace)
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)

    
    resolved = file_tools._resolve_inside_root("cookie_cases.xlsx", must_exist=True)
    assert resolved == target.resolve()

    explicit = file_tools._resolve_inside_root(
        "workspace/inputs/cookie_cases.xlsx", must_exist=True
    )
    assert explicit == target.resolve()


# ── 大结果 offload 只读通道 ────────────────────────────────────────────────
# FilesystemMiddleware 把超大 tool result 落到真实磁盘 artifacts_dir/large_tool_results/，
# 只给 agent 虚拟路径 /large_tool_results/<id>。原生 read_file 被屏蔽，fs_read 走本沙箱 →
# 必须在 _resolve_inside_root 里把该虚拟前缀映射到真实落点，agent 才能读回整份上机结果。
# 这些测试固化「读通 + 只读 + 不逃逸」三点，防回归（改前 main 读不到 offload 被迫小批 workaround）。

def _setup_offload(tmp_path, monkeypatch):
    """建 artifacts_dir/large_tool_results/<id>，把 IST_ARTIFACTS_DIR 指过去。"""
    artifacts = tmp_path / "artifacts"
    ltr = artifacts / "large_tool_results"
    ltr.mkdir(parents=True)
    call = ltr / "call_deadbeef"
    call.write_text('[{"autoid": "203031", "verdict": "pass"}]')
    monkeypatch.setenv("IST_ARTIFACTS_DIR", str(artifacts))
    # 沙箱根设成与 artifacts 无关的目录，证明放行来自 offload 通道、不是碰巧落进某读根
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path / "proj_nonexist")
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "workspace_nonexist")
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)
    return call.resolve()


def test_offload_virtual_prefix_maps_to_real_artifacts(tmp_path, monkeypatch):
    """/large_tool_results/<id> → 真实 artifacts 落点（读通）。"""
    real = _setup_offload(tmp_path, monkeypatch)
    resolved = file_tools._resolve_inside_root(
        "/large_tool_results/call_deadbeef", must_exist=True
    )
    assert resolved == real


def test_offload_relative_form_also_maps(tmp_path, monkeypatch):
    """不带前导斜杠的 large_tool_results/<id> 同样放行（agent 两种写法都可能用）。"""
    real = _setup_offload(tmp_path, monkeypatch)
    resolved = file_tools._resolve_inside_root(
        "large_tool_results/call_deadbeef", must_exist=True
    )
    assert resolved == real


def test_offload_missing_id_raises_not_found(tmp_path, monkeypatch):
    """不存在的 offload id + must_exist → FileNotFoundError（而非沉默返回坏路径）。"""
    _setup_offload(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        file_tools._resolve_inside_root(
            "/large_tool_results/call_nope", must_exist=True
        )


def test_offload_traversal_still_blocked(tmp_path, monkeypatch):
    """offload 前缀内塞 .. 逃逸仍被 traversal 闸拦（映射前先挡）。"""
    _setup_offload(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        file_tools._resolve_inside_root(
            "/large_tool_results/../../environment"
        )


def test_offload_channel_is_read_only(tmp_path, monkeypatch):
    """写路径不含此映射——offload 区永远不可写（agent 仍只能写 workspace/outputs）。"""
    _setup_offload(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        file_tools._resolve_writable_path("/large_tool_results/call_deadbeef")


def test_offload_symlink_escape_blocked(tmp_path, monkeypatch):
    """offload 根内的 symlink 指向根外（如 /etc/passwd / 项目 environment 明文口令）
    读不出去：resolve() 规范化 symlink 目标后 relative_to 越界即拒。

    该安全性**依赖 resolve()-先于-relative_to 的顺序**——此测试锁住它，防日后有人
    "简化"成对 _mapped 去掉 .resolve()、或把越界判定换成字符串 startswith，导致
    symlink 防护静默失效且无测试兜住（安全评审加固建议）。
    """
    real = _setup_offload(tmp_path, monkeypatch)   # 建 artifacts/large_tool_results/
    ltr = real.parent
    secret = tmp_path / "secret_outside.txt"
    secret.write_text("PLAINTEXT-CREDENTIAL")
    (ltr / "evil_link").symlink_to(secret)
    with pytest.raises(PermissionError):
        file_tools._resolve_inside_root(
            "/large_tool_results/evil_link", must_exist=True
        )


def test_offload_read_write_same_source(monkeypatch):
    """读侧 offload 通道与写侧 backend 共用 offload_artifacts_dir()——同源、不漂移。"""
    from main.ist_core.memory.backend import offload_artifacts_dir
    monkeypatch.setenv("IST_ARTIFACTS_DIR", "/tmp/some_probe_dir")
    assert offload_artifacts_dir() == "/tmp/some_probe_dir"
    monkeypatch.delenv("IST_ARTIFACTS_DIR", raising=False)
    assert offload_artifacts_dir() == "/tmp/ist_core_artifacts"


def test_offload_prefix_requires_exact_segment(tmp_path, monkeypatch):
    """只拦 large_tool_results 段本身（== 或 后接 /）；'large_tool_results_notes.md'
    这类相似名不被 offload 通道劫持，仍走普通沙箱解析（落 agent_root，非 artifacts）。"""
    _setup_offload(tmp_path, monkeypatch)
    resolved = file_tools._resolve_inside_root("large_tool_results_notes.md")
    assert "artifacts" not in resolved.parts

