"""下载提醒回归 —— agent 生成 outputs 文件后，run_done 应发 OSC 7002 通知前端。

与上传方向对称：写文件发生在 agent 工具层（与渲染解耦），故在回合结束的渲染
线程做 outputs 目录 diff + 发带外 OSC 信号。本测试用裸 IstInkApp 实例 + stub
app/transcript + 临时 outputs 目录，驱动 _snapshot_outputs / _notify_new_outputs。
"""

from __future__ import annotations

import base64
from pathlib import Path

from main.ist_core.ink.components.ist_app import IstInkApp


class _StubTranscript:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def append_message(self, text: str, *, style: str = "") -> None:
        self.lines.append(text)


class _StubApp:
    """捕获 write_passthrough 发出的 OSC 序列。"""

    def __init__(self) -> None:
        self.passthrough: list[str] = []

    def write_passthrough(self, data: str) -> None:
        self.passthrough.append(data)

    def render(self) -> None:
        pass


def _bare_app(outputs_dir: Path) -> IstInkApp:
    app = object.__new__(IstInkApp)
    app._transcript = _StubTranscript()
    app._app = _StubApp()
    app._outputs_snapshot = set()
    # 把 _outputs_dir 指向临时目录
    app.__dict__["_outputs_dir_override"] = outputs_dir
    return app


def _patch_outputs_dir(app: IstInkApp, monkeypatch, outputs_dir: Path) -> None:
    monkeypatch.setattr(
        type(app), "_outputs_dir", staticmethod(lambda: outputs_dir)
    )


def _decode_osc(seq: str) -> str:
    # seq 形如 \x1b]7002;<base64>\x07
    assert seq.startswith("\x1b]7002;") and seq.endswith("\x07")
    b64 = seq[len("\x1b]7002;"):-1]
    return base64.b64decode(b64).decode("utf-8")


def test_new_output_emits_osc(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    app = _bare_app(outputs)
    _patch_outputs_dir(app, monkeypatch, outputs)

    # 基线快照（空）
    app._outputs_snapshot = app._snapshot_outputs()
    # agent 生成两个文件
    (outputs / "report.md").write_text("x", encoding="utf-8")
    (outputs / "评审报告.md").write_text("y", encoding="utf-8")

    app._notify_new_outputs()

    decoded = sorted(_decode_osc(s) for s in app._app.passthrough)
    assert decoded == ["report.md", "评审报告.md"]
    # transcript 也留了一条提示
    assert any("已生成" in ln for ln in app._transcript.lines)


def test_no_new_output_no_osc(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "old.md").write_text("x", encoding="utf-8")
    app = _bare_app(outputs)
    _patch_outputs_dir(app, monkeypatch, outputs)

    app._outputs_snapshot = app._snapshot_outputs()  # 含 old.md
    # 本回合没生成新文件
    app._notify_new_outputs()

    assert app._app.passthrough == []


def test_dotfiles_ignored(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    app = _bare_app(outputs)
    _patch_outputs_dir(app, monkeypatch, outputs)

    app._outputs_snapshot = app._snapshot_outputs()
    (outputs / ".gitkeep").write_text("", encoding="utf-8")  # 隐藏文件不算产物

    app._notify_new_outputs()
    assert app._app.passthrough == []


def test_snapshot_updates_after_notify(tmp_path, monkeypatch):
    """通知后快照应更新，避免同一文件下回合重复提醒。"""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    app = _bare_app(outputs)
    _patch_outputs_dir(app, monkeypatch, outputs)

    app._outputs_snapshot = app._snapshot_outputs()
    (outputs / "a.md").write_text("x", encoding="utf-8")
    app._notify_new_outputs()
    assert len(app._app.passthrough) == 1

    # 第二回合没有新文件 → 不再发
    app._app.passthrough.clear()
    app._notify_new_outputs()
    assert app._app.passthrough == []


def test_notify_fires_on_snapshot_done_transition(tmp_path, monkeypatch):
    """回归：notify 必须挂在 snapshot status running→done 转换上（_on_snapshot_locked），
    而非 bridge 从不发送的 run_done 事件。实测发现的真 bug：原先只挂 run_done →
    下载提醒永不触发。

    构造最小 snapshot 驱动 _on_snapshot_locked，断言：
    - running→done 转换 + 有新文件 → 发 OSC 7002
    - running→running（未完成）→ 不发
    """
    from main.ist_core.tui.message_model import MessageSnapshot

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    app = _bare_app(outputs)
    _patch_outputs_dir(app, monkeypatch, outputs)

    # 补齐 _on_snapshot_locked 依赖的最小组件
    class _StubFooter:
        def update(self, **kw): pass

    class _StubPlanPanel:
        is_visible = False
        def mark_all_done(self): pass

    app._footer = _StubFooter()
    app._plan_panel = _StubPlanPanel()
    app._prev_snapshot = None
    app._ai_stream_idx = -1
    app._tokens_used = 0
    app._is_loading = True
    app._flush_pending_tools = lambda: None

    # 基线快照（空 outputs）
    app._outputs_snapshot = app._snapshot_outputs()

    def snap(status):
        return MessageSnapshot(messages=(), streaming_text=None, status=status)

    # 第一帧：running（agent 还在跑）→ 不应触发
    app._on_snapshot_locked(snap("running"))
    assert app._app.passthrough == []

    # agent 写了文件
    (outputs / "result.md").write_text("done", encoding="utf-8")

    # running→done 转换 → 应发 OSC 7002
    app._on_snapshot_locked(snap("done"))
    assert len(app._app.passthrough) == 1
    assert _decode_osc(app._app.passthrough[0]) == "result.md"
