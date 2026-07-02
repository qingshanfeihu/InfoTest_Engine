"""``/reset`` 与 ``infotest reset`` 共享核心逻辑。

清理范围：
- ``$IST_SQLITE_PATH`` (.db + .wal/.shm)：对话 checkpoint
- ``memory/working/*.md``：工作记忆
- ``runtime/large_tool_results/*``：大工具输出缓存
- ``runtime/conversation_history/*``：对话历史产物
- ``memory/.dream/`` (不含 ``running.pid``)：dream 会话状态

可选 (``--all``)：
- ``memory/long_term/**/*.md``：长期记忆（preferences / feedback / project / reference）

不动：``memory/AGENTS.md``（git 管理）、``runtime/logs/``、``runtime/users/``。
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ResetResult:
    """清理结果汇总。"""

    cleared_items: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        lines: list[str] = []
        if self.cleared_items:
            lines.append(f"已清理 {len(self.cleared_items)} 项：")
            for item in self.cleared_items:
                lines.append(f"  ✓ {item}")
        else:
            lines.append("无可清理内容。")
        if self.skipped:
            lines.append("")
            lines.append("跳过：")
            for s in self.skipped:
                lines.append(f"  - {s}")
        if self.errors:
            lines.append("")
            lines.append(f"错误 ({len(self.errors)})：")
            for err in self.errors:
                lines.append(f"  ✗ {err}")
        return "\n".join(lines)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _memory_root() -> Path:
    from main.ist_core.memory.backend import get_default_root

    return get_default_root()


def _sqlite_path() -> Optional[Path]:
    raw = (os.environ.get("IST_SQLITE_PATH") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _postgres_dsn_set() -> bool:
    return bool(
        (os.environ.get("IST_POSTGRES_CHECKPOINT_DSN") or "").strip()
        or (os.environ.get("LANGGRAPH_POSTGRES_DSN") or "").strip()
    )


def reset_checkpoints(result: ResetResult) -> None:
    """删除 SQLite checkpoint 文件（含 .wal / .shm 同伴文件）。"""
    if _postgres_dsn_set():
        result.skipped.append(
            "Postgres checkpoint：请用 psql 手动 TRUNCATE checkpoints 表"
        )
        return

    db_path = _sqlite_path()
    if db_path is None:
        result.skipped.append("checkpoint：未设置 IST_SQLITE_PATH（InMemorySaver）")
        return
    if not db_path.exists():
        result.skipped.append(f"checkpoint：{db_path.name} 不存在")
        return
    try:
        db_path.unlink()
        for suffix in (".wal", ".shm", "-wal", "-shm"):
            companion = db_path.parent / (db_path.name + suffix)
            if companion.exists():
                companion.unlink()
        result.cleared_items.append(f"checkpoint ({db_path.name})")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"checkpoint: {exc}")


def reset_working_memory(result: ResetResult) -> None:
    """清空 ``memory/working/*.md``。"""
    working_dir = _memory_root() / "working"
    if not working_dir.exists():
        result.skipped.append("工作记忆：目录不存在")
        return
    count = 0
    for f in working_dir.glob("*.md"):
        try:
            f.unlink()
            count += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"working/{f.name}: {exc}")
    if count:
        result.cleared_items.append(f"工作记忆 ({count} 个文件)")
    else:
        result.skipped.append("工作记忆：空")


def reset_runtime_temp(result: ResetResult) -> None:
    """清空大结果 / 会话历史 offload 缓存。

    落点历史上在 ``runtime/``，现默认在 ``offload_artifacts_dir()``
    （``/tmp/ist_core_artifacts``，见 ``memory.backend``）。**两处都清**——
    legacy ``runtime/`` 兜底 + 当前 artifacts 落点，避免 offload 移位后
    "reset 了却没清到真缓存"（安全评审 drift 提示）。
    """
    from main.ist_core.memory.backend import offload_artifacts_dir

    roots: list[Path] = [_project_root() / "runtime"]
    try:
        art = Path(offload_artifacts_dir())
        if art.resolve() not in {r.resolve() for r in roots}:
            roots.append(art)
    except Exception:  # noqa: BLE001
        pass

    seen: set[str] = set()
    for root in roots:
        for subdir in ("large_tool_results", "conversation_history"):
            target = root / subdir
            if not target.exists():
                continue
            key = str(target.resolve())
            if key in seen:
                continue
            seen.add(key)
            count = 0
            for item in target.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                    count += 1
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"{root.name}/{subdir}/{item.name}: {exc}")
            if count:
                result.cleared_items.append(f"{root.name}/{subdir} ({count} 项)")


def reset_dream_state(result: ResetResult) -> None:
    """清空 ``memory/.dream/`` 中除 ``running.pid`` 外的状态文件。"""
    dream_dir = _memory_root() / ".dream"
    if not dream_dir.exists():
        result.skipped.append("dream 状态：目录不存在")
        return
    count = 0
    pid_active = False
    for f in dream_dir.iterdir():
        if f.name == "running.pid":
            pid_active = True
            continue
        try:
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
            count += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f".dream/{f.name}: {exc}")
    if count:
        result.cleared_items.append(f"dream 状态 ({count} 项)")
    if pid_active:
        result.skipped.append("dream running.pid（可能有活跃进程，未删）")


def reset_long_term_memory(result: ResetResult) -> None:
    """清空 ``memory/long_term/`` 全部 .md 文件（含子目录）。"""
    long_dir = _memory_root() / "long_term"
    if not long_dir.exists():
        result.skipped.append("长期记忆：目录不存在")
        return
    count = 0
    for f in long_dir.rglob("*.md"):
        try:
            f.unlink()
            count += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"long_term/{f.relative_to(long_dir)}: {exc}")
    if count:
        result.cleared_items.append(f"长期记忆 ({count} 个文件)")
    else:
        result.skipped.append("长期记忆：空")


def perform_reset(*, include_long_term: bool = False) -> ResetResult:
    """执行完整清理序列。"""
    result = ResetResult()
    reset_checkpoints(result)
    reset_working_memory(result)
    reset_runtime_temp(result)
    reset_dream_state(result)
    if include_long_term:
        reset_long_term_memory(result)
    return result


def preview_reset(*, include_long_term: bool = False) -> str:
    """预览将清理的内容（不执行）。"""
    lines = ["以下内容将被清理：", ""]

    if _postgres_dsn_set():
        lines.append("  - Postgres checkpoint（不会自动清理，需手动 psql）")
    else:
        db_path = _sqlite_path()
        if db_path and db_path.exists():
            size_kb = db_path.stat().st_size // 1024
            lines.append(f"  - 对话 checkpoint：{db_path.name} ({size_kb}KB)")

    working_dir = _memory_root() / "working"
    if working_dir.exists():
        wcount = len(list(working_dir.glob("*.md")))
        if wcount:
            lines.append(f"  - 工作记忆：{wcount} 个文件 (memory/working/)")

    runtime = _project_root() / "runtime"
    for subdir in ("large_tool_results", "conversation_history"):
        target = runtime / subdir
        if target.exists():
            count = sum(1 for _ in target.iterdir())
            if count:
                lines.append(f"  - runtime/{subdir}：{count} 项")

    dream_dir = _memory_root() / ".dream"
    if dream_dir.exists():
        count = sum(1 for f in dream_dir.iterdir() if f.name != "running.pid")
        if count:
            lines.append(f"  - dream 状态：{count} 项 (memory/.dream/)")

    if include_long_term:
        long_dir = _memory_root() / "long_term"
        if long_dir.exists():
            lcount = sum(1 for _ in long_dir.rglob("*.md"))
            if lcount:
                lines.append(f"  - 长期记忆：{lcount} 个文件 (memory/long_term/，永久删除)")

    if len(lines) == 2:
        return "无可清理内容。"

    lines.append("")
    if not include_long_term:
        lines.append("(长期记忆 memory/long_term/ 已保留。加 --all 一并清理。)")
    lines.append("(memory/AGENTS.md、runtime/logs/、runtime/users/ 不会清理。)")
    return "\n".join(lines)


__all__ = [
    "ResetResult",
    "perform_reset",
    "preview_reset",
    "reset_checkpoints",
    "reset_working_memory",
    "reset_runtime_temp",
    "reset_dream_state",
    "reset_long_term_memory",
]
