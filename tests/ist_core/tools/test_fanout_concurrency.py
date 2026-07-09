"""V3 步骤0：fan-out 并发自适应 + 429 退避（batch_tools）。

验证 auto 模式按 item 数自适应、env 硬覆盖、显式值、夹紧上限，以及 429 退避重试。
"""

from __future__ import annotations

import importlib

import main.ist_core.tools.device.batch_tools as bt


def test_resolve_concurrency_auto_floors_at_default():
    assert bt._resolve_concurrency(0, n_items=1) == bt._DEFAULT_FANOUT
    assert bt._resolve_concurrency(0, n_items=2) == bt._DEFAULT_FANOUT


def test_resolve_concurrency_auto_scales_with_items():
    assert bt._resolve_concurrency(0, n_items=10) == 10


def test_resolve_concurrency_auto_caps_at_max():
    assert bt._resolve_concurrency(0, n_items=100) == bt._MAX_FANOUT


def test_resolve_concurrency_explicit_value_wins_over_auto():
    assert bt._resolve_concurrency(8, n_items=100) == 8


def test_resolve_concurrency_explicit_still_capped():
    assert bt._resolve_concurrency(999, n_items=5) == bt._MAX_FANOUT


def test_resolve_concurrency_env_hard_override(monkeypatch):
    monkeypatch.setenv("IST_FANOUT_CONCURRENCY", "3")
    assert bt._resolve_concurrency(0, n_items=100) == 3
    assert bt._resolve_concurrency(8, n_items=100) == 3


def test_resolve_concurrency_zero_items_auto_is_default():
    assert bt._resolve_concurrency(0, n_items=0) == bt._DEFAULT_FANOUT


def test_is_rate_limit_error_detects_variants():
    assert bt._is_rate_limit_error(Exception("Error code: 429"))
    assert bt._is_rate_limit_error(Exception("rate limit exceeded"))
    assert bt._is_rate_limit_error(Exception("Too Many Requests"))
    assert bt._is_rate_limit_error(Exception("model overloaded"))
    assert not bt._is_rate_limit_error(Exception("connection reset by peer"))
    assert not bt._is_rate_limit_error(Exception("timeout"))


def test_fanout_retries_on_rate_limit_then_succeeds(monkeypatch):
    # 前两次抛 429，第三次成功 → 应重试到成功，不判失败。
    calls = {"n": 0}

    def fake_execute(skill, brief, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("Error code: 429 Too Many Requests")
        return "ok-output"

    import main.ist_core.skills.loader as loader
    monkeypatch.setattr(loader, "execute_fork_skill", fake_execute)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)  # 不真睡

    out = bt.compile_fanout.invoke({
        "skill": "ist-compile-draft",
        "briefs_json": '[{"key": "c1", "brief": "b"}]',
    })
    import json
    res = json.loads(out)
    assert res[0]["ok"] is True
    assert res[0]["output"] == "ok-output"
    assert calls["n"] == 3


def test_fanout_gives_up_after_max_retries(monkeypatch):
    def always_429(skill, brief, **kw):
        raise Exception("429 rate limit")

    import main.ist_core.skills.loader as loader
    monkeypatch.setattr(loader, "execute_fork_skill", always_429)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)

    import json
    out = bt.compile_fanout.invoke({
        "skill": "ist-compile-draft",
        "briefs_json": '[{"key": "c1", "brief": "b"}]',
    })
    res = json.loads(out)
    assert res[0]["ok"] is False
    assert "限流重试耗尽" in res[0]["output"]


# ---------------------------------------------------------------------------
# 载荷通道断层修复(2026-07-04 评审 docs/REVIEW_payload_channel_gap.md):
# 入参 briefs_path 文件通道 + 出参落盘/截尾。回归锚定**全量规模**(18+),
# 治"小规模测盖不出"——3-4 case 内联不撞上限,一上 18+ 并发才炸。
# ---------------------------------------------------------------------------

import json as _json


def _sandbox(tmp_path, monkeypatch):
    """把 fanout 的项目根指到 tmp,workspace 隔离(briefs_path 围栏/输出落盘都走它)。"""
    (tmp_path / "workspace" / "outputs").mkdir(parents=True)
    monkeypatch.setattr(bt, "_project_root", lambda: tmp_path)
    return tmp_path


def _fake_fork(monkeypatch, fn):
    import main.ist_core.skills.loader as loader
    # fanout 真实调用带 tag= 归属参数;桩签名多为 (skill, brief),包一层吞掉额外 kwargs
    monkeypatch.setattr(loader, "execute_fork_skill",
                        lambda skill, brief, **kw: fn(skill, brief))


def test_fanout_briefs_path_18_case_batch(tmp_path, monkeypatch):
    # 全量规模主路:18-case briefs 走文件通道,零内联、全派发、顺序保持。
    root = _sandbox(tmp_path, monkeypatch)
    briefs = [{"key": f"2030317533427{i:05d}", "brief": f"case-{i} " + "约束" * 300}
              for i in range(18)]
    bp = root / "workspace" / "outputs" / "wave1" / "briefs.json"
    bp.parent.mkdir(parents=True)
    bp.write_text(_json.dumps(briefs, ensure_ascii=False), encoding="utf-8")

    seen: list[str] = []
    def fake(skill, brief):
        seen.append(brief[:12])
        return f"ok:{brief[:8]}\nSTATUS: produced"
    _fake_fork(monkeypatch, fake)

    out = bt.compile_fanout.invoke({"skill": "ist-compile-draft",
                                    "briefs_path": "workspace/outputs/wave1/briefs.json"})
    res = _json.loads(out)
    assert isinstance(res, list) and len(res) == 18
    assert [r["key"] for r in res] == [b["key"] for b in briefs]
    assert all(r["ok"] for r in res)
    assert len(seen) == 18


def test_fanout_briefs_path_rejects_outside_workspace(tmp_path, monkeypatch):
    root = _sandbox(tmp_path, monkeypatch)
    evil = root / "briefs.json"   # 项目根、不在 workspace 内
    evil.write_text("[]", encoding="utf-8")
    out = bt.compile_fanout.invoke({"skill": "s", "briefs_path": str(evil)})
    assert "workspace" in _json.loads(out)["error"]


def test_fanout_briefs_path_missing_file(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    out = bt.compile_fanout.invoke({"skill": "s",
                                    "briefs_path": "workspace/outputs/nope.json"})
    assert "不存在" in _json.loads(out)["error"]


def test_fanout_truncated_json_error_points_to_file_channel(tmp_path, monkeypatch):
    # 字符串通道被截断(minimax 实况)→ 报错必须指路 briefs_path,不能只说"解析失败"。
    _sandbox(tmp_path, monkeypatch)
    out = bt.compile_fanout.invoke({"skill": "s",
                                    "briefs_json": '[{"key": "c1", "brief": "被截'})
    err = _json.loads(out)["error"]
    assert "briefs_path" in err


def test_fanout_native_array_wins_over_briefs_path(tmp_path, monkeypatch):
    # 通道优先级与 emit 同款:原生数组 > 文件。两个都传时派原生数组的内容。
    root = _sandbox(tmp_path, monkeypatch)
    bp = root / "workspace" / "outputs" / "b.json"
    bp.write_text(_json.dumps([{"key": "file", "brief": "from-file"}]), encoding="utf-8")
    _fake_fork(monkeypatch, lambda skill, brief: brief)
    out = bt.compile_fanout.invoke({
        "skill": "s", "briefs_json": [{"key": "native", "brief": "from-native"}],
        "briefs_path": "workspace/outputs/b.json"})
    res = _json.loads(out)
    assert res[0]["key"] == "native" and res[0]["output"] == "from-native"


def test_fanout_large_output_offloaded_tail_kept(tmp_path, monkeypatch):
    # 出参保护:超长 output 全文落盘,内联只留末尾——机读尾块(末两行)必须完整保留。
    root = _sandbox(tmp_path, monkeypatch)
    aid = "203031753342777001"
    big = "分析过程" * 20000 + "\nSTATUS: produced\nARTIFACT: workspace/outputs/x/case.xlsx"
    _fake_fork(monkeypatch, lambda skill, brief: big)
    out = bt.compile_fanout.invoke({"skill": "ist-compile-draft",
                                    "briefs_json": [{"key": aid, "brief": "b"}]})
    item = _json.loads(out)[0]
    assert len(item["output"]) < bt._FANOUT_INLINE_MAX + 300
    assert item["output"].rstrip().endswith("ARTIFACT: workspace/outputs/x/case.xlsx")
    assert "STATUS: produced" in item["output"]
    fp = root / item["output_path"]
    assert fp.is_file() and fp.read_text(encoding="utf-8") == big
    # autoid key → 落在该 case 的 outputs/<autoid>/ 下(与凭证/冻结标记同目录)
    assert f"outputs/{aid}/" in item["output_path"].replace("\\", "/")


def test_fanout_small_output_untouched(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    _fake_fork(monkeypatch, lambda skill, brief: "短输出\nSTATUS: produced")
    out = bt.compile_fanout.invoke({"skill": "s", "briefs_json": [{"key": "k1", "brief": "b"}]})
    item = _json.loads(out)[0]
    assert item["output"] == "短输出\nSTATUS: produced"
    assert "output_path" not in item


def test_fanout_evidence_injection_skipped_on_sandbox_rejection(tmp_path, monkeypatch):
    # 安全回归(2026-07-05 中危修复):evidence_from_xlsx 被沙箱读闸拒绝时必须放弃注入,
    # 绝不回退原始路径读盘(旧版 except 吞掉 PermissionError 后裸读=读闸旁路)。
    _sandbox(tmp_path, monkeypatch)
    # 沙箱外目录放一个 last_run.json,旧行为会读到它并注入 brief
    evil_dir = tmp_path / "outside_sandbox"
    evil_dir.mkdir()
    (evil_dir / "case.xlsx").write_text("x", encoding="utf-8")
    (evil_dir / "last_run.json").write_text(_json.dumps([
        {"autoid": "k1", "verdict": "fail", "device_context": "SECRET-EVIDENCE"}]),
        encoding="utf-8")
    import main.ist_core.tools.deepagent.file_tools as ft
    def _deny(path, must_exist=True):
        raise PermissionError("path outside agent sandbox")
    monkeypatch.setattr(ft, "_resolve_inside_root", _deny)

    seen: list[str] = []
    _fake_fork(monkeypatch, lambda skill, brief: seen.append(brief) or "ok")
    out = bt.compile_fanout.invoke({
        "skill": "s", "briefs_json": [{"key": "k1", "brief": "b"}],
        "evidence_from_xlsx": str(evil_dir / "case.xlsx")})
    assert _json.loads(out)[0]["ok"]
    assert seen and "SECRET-EVIDENCE" not in seen[0]   # 注入被放弃,brief 未被污染


def test_fanout_empty_briefs_is_error_not_silent_success(tmp_path, monkeypatch):
    # 双通道皆空=调用错误。旧行为返回 [] 会被 orchestrator 当"派发完成",清单静默丢失。
    _sandbox(tmp_path, monkeypatch)
    out = bt.compile_fanout.invoke({"skill": "s"})
    assert "briefs 为空" in _json.loads(out)["error"]


def test_fanout_return_size_bounded_at_scale(tmp_path, monkeypatch):
    # N 不变性:20 个 fork 各回 50k 字符,总返回必须有界(旧版 ≈1M 字符撑爆 orchestrator)。
    _sandbox(tmp_path, monkeypatch)
    _fake_fork(monkeypatch, lambda skill, brief: "x" * 50_000 + "\nSTATUS: produced")
    briefs = [{"key": f"k{i}", "brief": "b"} for i in range(20)]
    out = bt.compile_fanout.invoke({"skill": "s", "briefs_json": briefs})
    res = _json.loads(out)
    assert len(res) == 20
    assert len(out) < 20 * (bt._FANOUT_INLINE_MAX + 400)   # ~48k 上界;旧行为 >1M
