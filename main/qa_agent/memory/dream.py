"""Cron consolidation（AutoDream 对齐）：五道闸 + 四阶段。

参考实现：
- cc-haha src/services/autoDream/（五道闸：功能开关/24h/10min/5sessions/PID锁）
- cc-haha src/tasks/DreamTask/（四阶段：Orient → Gather → Consolidate → Prune）
- 本仓库 middleware.py 的 session counter + fcntl 锁封装

调度方式：
- 系统 crontab 调 scripts/maintenance/memory_dream.py（不依赖 langgraph dev 长跑）
- 每次进入先跑五道闸，全部通过再执行 DreamTask
"""

from __future__ import annotations

import fcntl
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from main.qa_agent.memory.backend import build_memory_backend, get_default_root, get_default_store
from main.qa_agent.memory.middleware import read_session_counter, reset_session_counter
from main.qa_agent.memory.store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class DreamReport:
    orient_count: int = 0
    gather_bytes: int = 0
    decisions: list[str] = field(default_factory=list)
    pruned_count: int = 0
    duration_s: float = 0.0

    def __str__(self) -> str:
        return (
            f"orient={self.orient_count} gather={self.gather_bytes}B "
            f"decisions={len(self.decisions)} pruned={self.pruned_count} "
            f"duration={self.duration_s:.1f}s"
        )


@dataclass
class Inventory:
    files: list[tuple[str, float]]  # (path, mtime_epoch)


@dataclass
class Payload:
    path: str
    content: str


# ---------------------------------------------------------------------------
# 五道闸
# ---------------------------------------------------------------------------


def _dream_root() -> Path:
    root = get_default_root()
    dream_dir = root / ".dream"
    dream_dir.mkdir(parents=True, exist_ok=True)
    return dream_dir


def _pid_lock_path() -> Path:
    return _dream_root() / "running.pid"


def _last_run_path() -> Path:
    return _dream_root() / "last_run"


def should_run_dream() -> tuple[bool, str]:
    """五道闸判断。返回 (是否跑, 原因说明)。"""
    # 闸 1：功能开关
    if (os.environ.get("QA_AGENT_DREAM_ENABLED") or "1").strip() == "0":
        return False, "disabled by QA_AGENT_DREAM_ENABLED=0"

    if (os.environ.get("QA_AGENT_MEMORY_ENABLED") or "1").strip() == "0":
        return False, "disabled by QA_AGENT_MEMORY_ENABLED=0"

    if (os.environ.get("QA_AGENT_MEMORY_DISABLE_LLM") or "0").strip() == "1":
        return False, "disabled by QA_AGENT_MEMORY_DISABLE_LLM=1"

    # 闸 2：24h 时间门
    last_run = _last_run_path()
    if last_run.exists():
        try:
            ts = float(last_run.read_text(encoding="utf-8").strip())
            hours_ago = (time.time() - ts) / 3600
            if hours_ago < 24:
                return False, f"ran {hours_ago:.1f}h ago (< 24h)"
        except Exception:
            pass

    # 闸 3：10min 扫描节流（用 lockfile mtime）
    pid_path = _pid_lock_path()
    if pid_path.exists():
        try:
            age_min = (time.time() - pid_path.stat().st_mtime) / 60
            if age_min < 10:
                return False, f"scan throttled ({age_min:.1f}min < 10min)"
        except Exception:
            pass

    # 闸 4：会话计数门 ≥ 5
    sessions = read_session_counter()
    min_sessions = int(os.environ.get("QA_AGENT_DREAM_MIN_SESSIONS") or "5")
    if sessions < min_sessions:
        return False, f"only {sessions} sessions (need >= {min_sessions})"

    # 闸 5：PID 锁
    if not _acquire_pid_lock():
        return False, "another dream process running (PID lock held)"

    return True, "ok"


_pid_lock_fd: Any = None


def _acquire_pid_lock() -> bool:
    """fcntl LOCK_EX | LOCK_NB。支持 stale lock 检测（进程已死）。"""
    global _pid_lock_fd
    pid_path = _pid_lock_path()
    try:
        fd = open(pid_path, "w", encoding="utf-8")
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        _pid_lock_fd = fd
        return True
    except (OSError, IOError):
        # 检查 stale：文件里的 PID 是否还活着
        try:
            old_pid = int(pid_path.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
            return False  # 进程还在
        except (ProcessLookupError, ValueError, OSError):
            # stale lock：进程已死，强制删除重试
            try:
                pid_path.unlink(missing_ok=True)
                fd2 = open(pid_path, "w", encoding="utf-8")
                fcntl.flock(fd2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fd2.write(str(os.getpid()))
                fd2.flush()
                _pid_lock_fd = fd2
                return True
            except Exception:
                return False
    except Exception:
        return False


def _release_pid_lock() -> None:
    global _pid_lock_fd
    if _pid_lock_fd is not None:
        try:
            fcntl.flock(_pid_lock_fd.fileno(), fcntl.LOCK_UN)
            _pid_lock_fd.close()
        except Exception:
            pass
        _pid_lock_fd = None
    try:
        _pid_lock_path().unlink(missing_ok=True)
    except Exception:
        pass


def _mark_last_run() -> None:
    try:
        _last_run_path().write_text(str(time.time()), encoding="utf-8")
    except Exception as exc:
        logger.debug("mark last_run 失败: %s", exc)


# ---------------------------------------------------------------------------
# DreamTask 四阶段
# ---------------------------------------------------------------------------


class DreamTask:
    def __init__(self, *, store: MemoryStore, llm_chat: Any) -> None:
        self._store = store
        self._llm = llm_chat
        self._lookback_days = int(os.environ.get("QA_AGENT_DREAM_LOOKBACK_DAYS") or "7")
        self._prune_days = int(os.environ.get("QA_AGENT_DREAM_PRUNE_DAYS") or "7")

    def run(self) -> DreamReport:
        t0 = time.time()
        report = DreamReport()
        try:
            inventory = self.orient()
            report.orient_count = len(inventory.files)

            payloads = self.gather(inventory)
            report.gather_bytes = sum(len(p.content) for p in payloads)

            decisions = self.consolidate(payloads)
            report.decisions = decisions

            pruned = self.prune(inventory)
            report.pruned_count = pruned
        except Exception as exc:
            logger.warning("DreamTask.run 异常: %s", exc)
        finally:
            _release_pid_lock()
            reset_session_counter()
            _mark_last_run()
            report.duration_s = time.time() - t0
        return report

    def orient(self) -> Inventory:
        """阶段 1：扫 long_term/ + working/ 目录列清单 + mtime（真实磁盘）。"""
        root = get_default_root()
        files: list[tuple[str, float]] = []
        for sub in ("long_term", "working"):
            d = root / sub
            if not d.exists():
                continue
            try:
                for f in d.rglob("*.md"):
                    if not f.is_file():
                        continue
                    rel = f.relative_to(root).as_posix()
                    if "/.archive/" in "/" + rel:
                        continue
                    try:
                        mtime = f.stat().st_mtime
                    except Exception:
                        mtime = time.time()
                    files.append((rel, mtime))
            except Exception as exc:
                logger.debug("orient scan %s 失败: %s", d, exc)
        return Inventory(files=files)

    def gather(self, inventory: Inventory) -> list[Payload]:
        """阶段 2：读最近 N 天文件的正文（磁盘）。"""
        cutoff = time.time() - self._lookback_days * 86400
        root = get_default_root()
        payloads: list[Payload] = []
        for rel, mtime in inventory.files:
            if mtime < cutoff:
                continue
            f = root / rel
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            if content:
                if len(content) > 5000:
                    content = content[:4997] + "..."
                payloads.append(Payload(path=rel, content=content))
        return payloads

    def consolidate(self, payloads: list[Payload]) -> list[str]:
        """阶段 3：LLM 抽取 → 判断是否合并 / 蒸馏 / 更新 AGENTS.md。"""
        if not payloads:
            return []
        if self._llm is None:
            return ["skip: no LLM configured"]

        combined = "\n\n---\n\n".join(
            f"## {p.path}\n{p.content[:2000]}" for p in payloads[:20]
        )
        agents_md = self._store.read_agents_md(max_lines=300)

        prompt = (
            "你是 IST-Core 的 Dream 整理助手。阅读以下长期记忆文件摘要，"
            "判断是否有重复 / 矛盾 / 可以合并到 AGENTS.md 的项目级规则。\n\n"
            "当前 AGENTS.md 内容（可能已有规则）：\n"
            f"```\n{agents_md}\n```\n\n"
            "长期记忆摘要：\n"
            f"```\n{combined}\n```\n\n"
            "请输出 JSON 列表：\n"
            '[{"action":"skip"} 或 {"action":"append_agents_md","content":"新增行"} '
            '或 {"action":"merge","source":"路径","target":"路径","reason":"原因"}]\n'
            "只输出 JSON，不要其他文字。如果无操作，输出 []\n"
        )

        try:
            result = self._llm(prompt)
            import json
            decisions = json.loads(result) if isinstance(result, str) else result
            if not isinstance(decisions, list):
                return ["skip: LLM returned non-list"]
        except Exception as exc:
            logger.warning("consolidate LLM 失败: %s", exc)
            return [f"error: {exc}"]

        applied: list[str] = []
        for d in decisions:
            if not isinstance(d, dict):
                continue
            action = d.get("action", "skip")
            if action == "append_agents_md":
                content = d.get("content", "")
                if content:
                    try:
                        current = self._store.read_agents_md(max_lines=10000)
                        new_text = current.rstrip() + "\n" + content + "\n"
                        self._store.update_agents_md(new_text)
                        self._store.sync_agents_md_to_backend()
                        applied.append(f"append_agents_md: {content[:80]}")
                    except Exception as exc:
                        applied.append(f"error append: {exc}")
            elif action == "merge":
                applied.append(f"merge: {d.get('source')} → {d.get('target')} (TODO)")
        if not applied:
            applied.append("skip: no changes needed")
        return applied

    def prune(self, inventory: Inventory) -> int:
        """阶段 4：归档过期文件（>prune_days 天未更新）。

        - long_term/*.md：在 frontmatter 加 archived: true，保留可读
        - working/<tid>.md：物理移到 working/.archive/<tid>.<ts>.md
        """
        cutoff = time.time() - self._prune_days * 86400
        root = get_default_root()
        archive_dir = root / "working" / ".archive"
        pruned = 0

        for rel, mtime in inventory.files:
            if mtime > cutoff:
                continue
            f = root / rel
            if not f.exists():
                continue
            try:
                if rel.startswith("working/"):
                    # working：移到 .archive
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime(mtime))
                    archived = archive_dir / f"{f.stem}.{ts}{f.suffix}"
                    f.replace(archived)
                    pruned += 1
                elif rel.startswith("long_term/"):
                    # long_term：加 archived 标记
                    content = f.read_text(encoding="utf-8")
                    if "archived: true" in content:
                        continue
                    fields, body = self._store.parse_frontmatter(content)
                    fields["archived"] = "true"
                    new_text = self._store.render_frontmatter(fields) + "\n" + body
                    tmp = f.with_suffix(f.suffix + f".tmp.{int(time.time() * 1000)}")
                    tmp.write_text(new_text, encoding="utf-8")
                    tmp.replace(f)
                    pruned += 1
            except Exception as exc:
                logger.debug("prune %s 失败: %s", rel, exc)
        return pruned


__all__ = ["DreamReport", "DreamTask", "should_run_dream", "run_dream_with_gates"]


# ---------------------------------------------------------------------------
# Cron 入口便捷函数
# ---------------------------------------------------------------------------


def run_dream_with_gates() -> tuple[DreamReport | None, str]:
    """完整 cron 入口：跑五道闸 → 拿锁 → 跑 DreamTask → 释放锁 + 重置计数器。

    返回 (report, reason)；闸拒绝时 report=None 且 reason 给出原因。
    DreamTask.run() finally 块负责释放锁、归零计数器、写 last_run。
    """
    ok, reason = should_run_dream()
    if not ok:
        return None, reason

    try:
        # PID 锁已由 should_run_dream 闸 5 拿到
        backend = build_memory_backend()
        store = MemoryStore(backend, get_default_root())

        try:
            from main.function_llm import chat_completion
            import requests

            session = requests.Session()
            api_key = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()

            def _llm_chat(prompt: str) -> str:
                """适配 DreamTask.consolidate 的 (prompt) -> str 接口。"""
                if not api_key:
                    return "[]"
                try:
                    result = chat_completion(
                        session, api_key,
                        "你是 IST-Core 的 Dream 整理助手，输出严格 JSON。",
                        prompt,
                        max_tokens=4096,
                        temperature=0.1,
                    )
                    import json
                    return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                except Exception as exc:
                    logger.warning("consolidate llm_chat 失败: %s", exc)
                    return "[]"

            llm_chat = _llm_chat if api_key else None
        except Exception as exc:
            logger.warning("dream LLM 初始化失败: %s", exc)
            llm_chat = None

        task = DreamTask(store=store, llm_chat=llm_chat)
        report = task.run()
        return report, "ok"
    except Exception as exc:
        logger.exception("run_dream_with_gates 失败: %s", exc)
        # 锁可能没释放，强制释放一次
        try:
            _release_pid_lock()
        except Exception:
            pass
        return None, f"setup failed: {exc}"
