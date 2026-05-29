"""Slash 命令：/memory + /remember。

参考实现：
- 子命令分发模式
- SlashCommandResult 协议

提供：
- /memory                 总览：3 类长期 + 当前 thread working
- /memory show <path>     显示某条目全文
- /memory clear working   清当前 thread working
- /memory clear long      清 long_term/* (preferences + feedback + review_conclusions)
- /memory clear all       清 working + long_term（保留 AGENTS.md，受 git 跟踪）
- /memory status          dream session counter / last run / 闸状态
- /remember <text>        追加到 preferences.md（可选 --topic xxx → feedback/<topic>.md）
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from main.ist_core.tui.slash_commands import (
    ErrorResult,
    InfoResult,
    SlashCommandResult,
    TextResult,
)

if TYPE_CHECKING:
    from main.ist_core.tui.app import IstApp  # noqa: F401

logger = logging.getLogger(__name__)


_HELP_TEXT = """/memory subcommands:
  /memory                   总览（默认）
  /memory show <path>       查看条目全文（path 形如 long_term/preferences.md）
  /memory clear working     清当前 thread working/<tid>.md
  /memory clear long        清所有 long_term/* 条目
  /memory clear all         清 working + long_term（AGENTS.md git 管理，不动）
  /memory status            dream session 计数 + 上次运行 + 闸状态

/remember <text>             追加 user 偏好到 long_term/preferences.md
/remember --feedback <topic> <text>   追加到 long_term/feedback/<topic>.md
/remember --project <topic> <text>    追加到 long_term/project/<topic>.md
/remember --reference <topic> <text>  追加到 long_term/reference/<topic>.md

核心分类语义：
  user (preferences)   用户画像 / 偏好 / 角色
  feedback             反复纠正的反馈
  project              项目动态 / 决策 / 状态
  reference            外部引用（文档、链接等）"""


_TYPE_TO_PATH = {
    "user": "long_term/preferences.md",
    "feedback": "long_term/feedback/{topic}.md",
    "project": "long_term/project/{topic}.md",
    "reference": "long_term/reference/{topic}.md",
}


def _store_for_app(app: "IstApp"):
    """构造一个 MemoryStore（不缓存到 app，避免循环依赖）。"""
    from main.ist_core.memory.backend import build_memory_backend, get_default_root
    from main.ist_core.memory.store import MemoryStore

    backend = build_memory_backend()
    return MemoryStore(backend, get_default_root())


def _root_path():
    from main.ist_core.memory.backend import get_default_root
    return get_default_root()


def _current_thread_id(app: "IstApp") -> str:
    """从 IstApp.tui_state 拿当前 thread_id。"""
    try:
        tid = getattr(app.tui_state, "thread_id", None) or "default"
        return str(tid)
    except Exception:
        return "default"







def cmd_memory(args: str, app: "IstApp") -> SlashCommandResult:
    parts = (args or "").strip().split(None, 2)
    if not parts or parts[0] in ("", "help", "--help", "-h"):
        if parts and parts[0] in ("help", "--help", "-h"):
            return TextResult(text=_HELP_TEXT)
        return _cmd_overview(app)
    sub = parts[0].lower()
    if sub == "status":
        return _cmd_status()
    if sub == "show":
        if len(parts) < 2:
            return ErrorResult(text="usage: /memory show <path>  (e.g. long_term/preferences.md)")
        return _cmd_show(parts[1])
    if sub == "clear":
        if len(parts) < 2:
            return ErrorResult(text="usage: /memory clear {working|long|all}")
        return _cmd_clear(parts[1].lower(), app)
    return ErrorResult(text=f"unknown /memory subcommand: {sub!r}\n{_HELP_TEXT}")







def _cmd_overview(app: "IstApp") -> SlashCommandResult:
    """列总览：长期记忆条目 + 当前 thread working。"""
    root = _root_path()
    if not root.exists():
        return InfoResult(text="(memory 未初始化，目录不存在)")

    lines = ["Memory overview:", ""]

    
    agents = root / "AGENTS.md"
    if agents.exists():
        size = agents.stat().st_size
        lines.append(f"  AGENTS.md (project, git tracked) {size}B")

    
    long_dir = root / "long_term"
    long_files: list = []
    if long_dir.exists():
        
        for top in ("preferences.md",):
            f = long_dir / top
            if f.exists():
                long_files.append(f)
        
        for sub in ("feedback", "project", "reference", "review_conclusions"):
            d = long_dir / sub
            if d.exists():
                for f in sorted(d.glob("*.md")):
                    long_files.append(f)

    
    
    if long_files:
        lines.append("")
        lines.append("Long-term notes:")
        for f in long_files:
            try:
                rel = f.relative_to(root).as_posix()
            except ValueError:
                rel = str(f)
            try:
                size = f.stat().st_size
            except Exception:
                size = 0
            preview = _peek(f)
            lines.append(f"  {rel} ({size}B) — {preview}")

    
    tid = _current_thread_id(app)
    wf = root / "working" / f"{_sanitize(tid)}.md"
    if wf.exists():
        lines.append("")
        lines.append("Working (this thread):")
        try:
            text = wf.read_text(encoding="utf-8")
            l = text.splitlines()
            lines.append(f"  working/{wf.name} ({wf.stat().st_size}B, {len(l)} lines)")
        except Exception as exc:
            lines.append(f"  working/{wf.name} (read failed: {exc})")

    if len(lines) == 2:
        lines.append("(empty — no long-term notes, no working memory for this thread)")
    lines.append("")
    lines.append("Type /memory show <path> to view full content.")
    return TextResult(text="\n".join(lines))


def _cmd_status() -> SlashCommandResult:
    try:
        from main.ist_core.memory.dream import (
            should_run_dream,
            _last_run_path,
            read_session_counter,
        )

        ok, reason = should_run_dream()
        
        try:
            from main.ist_core.memory.dream import _release_pid_lock
            _release_pid_lock()
        except Exception:
            pass
        sessions = read_session_counter()
        last_run = _last_run_path()
        last_str = "never"
        if last_run.exists():
            import time
            ago_h = (time.time() - last_run.stat().st_mtime) / 3600
            last_str = f"{ago_h:.1f}h ago"

        lines = [
            f"  dream gate: {'PASS' if ok else 'BLOCKED'} ({reason})",
            f"  session counter: {sessions}",
            f"  last run: {last_str}",
        ]
        return TextResult(text="Memory dream status:\n" + "\n".join(lines))
    except Exception as exc:
        return ErrorResult(text=f"failed to read dream status: {exc}")


def _cmd_show(path: str) -> SlashCommandResult:
    root = _root_path()
    rel = (path or "").strip().lstrip("/")
    if not rel:
        return ErrorResult(text="usage: /memory show <path>")
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return ErrorResult(text=f"path outside memory/: {path!r}")
    if not target.exists():
        return ErrorResult(text=f"file not found: {rel}")
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as exc:
        return ErrorResult(text=f"read failed: {exc}")
    
    lines = text.splitlines()
    if len(lines) > 200:
        lines = lines[:200] + [f"... [{len(text.splitlines()) - 200} more lines truncated]"]
    return TextResult(text=f"=== {rel} ===\n" + "\n".join(lines))


def _cmd_clear(scope: str, app: "IstApp") -> SlashCommandResult:
    root = _root_path()
    if scope not in ("working", "long", "all"):
        return ErrorResult(text="usage: /memory clear {working|long|all}")
    removed: list[str] = []
    try:
        if scope in ("working", "all"):
            tid = _current_thread_id(app)
            wf = root / "working" / f"{_sanitize(tid)}.md"
            if wf.exists():
                wf.unlink()
                removed.append(f"working/{wf.name}")
        if scope in ("long", "all"):
            long_dir = root / "long_term"
            if long_dir.exists():
                for f in long_dir.rglob("*.md"):
                    try:
                        f.unlink()
                        removed.append(f.relative_to(root).as_posix())
                    except Exception:
                        pass
        if not removed:
            return InfoResult(text="(nothing to clear)")
        return InfoResult(text=f"cleared {len(removed)} files: {', '.join(removed[:5])}{'...' if len(removed) > 5 else ''}")
    except Exception as exc:
        return ErrorResult(text=f"clear failed: {exc}")







def cmd_remember(args: str, app: "IstApp") -> SlashCommandResult:
    raw = (args or "").strip()
    if not raw:
        return ErrorResult(text=(
            "usage:\n"
            "  /remember <text>                       → long_term/preferences.md (user 类)\n"
            "  /remember --feedback <topic> <text>    → long_term/feedback/<topic>.md\n"
            "  /remember --project <topic> <text>     → long_term/project/<topic>.md\n"
            "  /remember --reference <topic> <text>   → long_term/reference/<topic>.md\n"
            "  /remember --topic <name> <text>        别名等价于 --feedback（向后兼容）"
        ))

    type_flag = "user"
    topic: str | None = None
    text = raw

    
    flag_map = {
        "--feedback": "feedback",
        "--project": "project",
        "--reference": "reference",
        "--topic": "feedback",
    }
    for flag, t in flag_map.items():
        prefix = flag + " "
        if raw.startswith(prefix):
            rest = raw[len(prefix):].lstrip()
            sp = rest.split(None, 1)
            if len(sp) < 2:
                return ErrorResult(text=f"usage: /remember {flag} <topic> <text>")
            topic = sp[0].strip()
            text = sp[1].strip()
            type_flag = t
            if not topic.replace("-", "").replace("_", "").isalnum():
                return ErrorResult(text=f"topic name must be alphanumeric/-/_: {topic!r}")
            break

    if not text:
        return ErrorResult(text="text required")

    
    if type_flag == "user":
        rel = _TYPE_TO_PATH["user"]
    else:
        rel = _TYPE_TO_PATH[type_flag].format(topic=topic)
    disk_path = _root_path() / rel

    try:
        _append_to_disk(disk_path, text, mem_type=type_flag)
        return InfoResult(text=f"saved to {rel} ({len(text)} chars, type={type_flag})")
    except Exception as exc:
        return ErrorResult(text=f"remember failed: {exc}")







def _sanitize(thread_id: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_\-.]", "_", thread_id or "default")[:80]


def _peek(path) -> str:
    """读文件首段（跳过 frontmatter），<60 字。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return "(unreadable)"
    
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            text = text[end + 4:]
    text = " ".join(text.split())
    if len(text) > 60:
        return text[:57] + "..."
    return text or "(empty)"


def _append_to_disk(path, text: str, *, mem_type: str = "user") -> None:
    """append 一段文本到磁盘文件（带 frontmatter 自维护、原子写）。

    mem_type: user / feedback / project / reference（四类长期记忆语义，写到 frontmatter）。
    """
    from main.ist_core.memory.store import MemoryStore
    from datetime import datetime, timezone
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""

    fields, body = (MemoryStore.parse_frontmatter(existing) if existing else ({}, ""))
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    if not fields.get("created"):
        fields["created"] = now
    fields["updated"] = now
    if mem_type and "type" not in fields:
        fields["type"] = mem_type
    try:
        fields["entry_count"] = str(int(fields.get("entry_count", "0") or "0") + 1)
    except Exception:
        fields["entry_count"] = "1"
    if "name" not in fields:
        fields["name"] = path.stem

    sep = "\n\n" if body and not body.endswith("\n") else "\n"
    bullet = f"- [{now[:10]}] {text}"
    new_body = (body or "").rstrip() + sep + bullet + "\n"

    new_text = MemoryStore.render_frontmatter(fields) + "\n" + new_body.lstrip("\n")
    tmp = path.with_suffix(path.suffix + f".tmp.{int(time.time() * 1000)}")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)


__all__ = ["cmd_memory", "cmd_remember"]
