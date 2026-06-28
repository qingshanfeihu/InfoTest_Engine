"""Cron consolidation（AutoDream 对齐）：五道闸 + 四阶段。

实现逻辑：
- 五道闸限制：功能开关/24h/10min/5sessions/PID锁
- 四阶段整理：Orient → Gather → Consolidate → Prune
- session counter + fcntl 锁封装

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

from main.ist_core.memory.backend import build_memory_backend, get_default_root, get_default_store
from main.ist_core.memory.middleware import read_session_counter, reset_session_counter
from main.ist_core.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_CONSOLIDATE_SYSTEM_PROMPT = "你是 IST-Core 的 Dream 整理助手，输出严格 JSON。"


def _coerce_decisions(parsed: Any) -> list[dict]:
    """把 consolidate LLM 返回归一化成动作 dict 列表。

    端点开了 ``response_format: json_object``，模型只能返回顶层对象（不可能返回
    顶层数组），所以这里要兼容多种形态：

    - ``{"decisions": [...]}`` —— 约定格式，取 decisions
    - ``{"action": "..."}`` —— 模型直接返回单个动作，包成单元素列表
    - ``[...]`` —— 万一模型/解析给了列表，直接用
    - 其他 —— 空列表（视为无操作）
    """
    if isinstance(parsed, list):
        return [d for d in parsed if isinstance(d, dict)]
    if isinstance(parsed, dict):
        inner = parsed.get("decisions")
        if isinstance(inner, list):
            return [d for d in inner if isinstance(d, dict)]
        if "action" in parsed:
            return [parsed]
    return []



def _load_existing_facts(footprint_dir: Path) -> dict[str, dict[str, list]]:
    """扫描现有 footprint 树，按 feature_id 索引出 fact_key + 内容样例。

    回灌**全部** fact_kind（cli_command/decision_rule/behavior/known_issue），
    让 LLM 在重新提取时看到节点已有的命令、规则、行为、缺陷全貌，
    据此复用 fact_key / 归一化 feature_path，避免重复与分裂。

    返回结构：
        {
          "http.rewrite.body": {
            "cli_command": [("syntax", "http rewrite body {on|off}"), ...],
            "decision_rule": [("default_limit_5120kb", "未配置 → 默认 5120KB"), ...],
            "behavior": [(...)],
            "known_issue": [("BUG-70233", "[Http rewrite body] Fail to rewrite ..."), ...],
          }
        }
    """
    import json as _json

    out: dict[str, dict[str, list]] = {}
    if not footprint_dir.exists():
        return out

    for f in footprint_dir.rglob("*.json"):
        try:
            d = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        fid = d.get("feature_id")
        if not fid:
            continue
        kinds: dict[str, list] = {
            "cli_command": [], "decision_rule": [], "behavior": [], "known_issue": [],
        }
        for c in d.get("cli", {}).get("commands", []):
            key = c.get("fact_key")
            if key:
                
                params = c.get("parameters", [])
                pnames = ",".join(p.get("name", "") for p in params if p.get("name"))
                sample = c.get("command", "")
                if pnames:
                    sample = f"{sample}  [params: {pnames}]"
                kinds["cli_command"].append((key, sample))
        for r in d.get("decision_rules", []):
            key = r.get("fact_key")
            if key:
                cond = r.get("condition", "")
                dec = r.get("decision", "")
                kinds["decision_rule"].append((key, f"{cond} → {dec}"))
        for b in d.get("behaviors", []):
            key = b.get("fact_key")
            if key:
                kinds["behavior"].append((key, b.get("content", "")))
        for i in d.get("known_issues", []):
            iid = i.get("issue_id")
            if iid:
                kinds["known_issue"].append((iid, i.get("title", "")))
        if any(kinds.values()):
            out[fid] = kinds
    return out



def _dream_llm_http_setup(*, tier: str = "default") -> tuple[Any, str, str, str] | None:
    """解析 OpenAI 兼容 HTTP LLM 参数。

    返回 ``(session, api_key, base_url, model)``；无可用 key 时返回 None。
    ``tier`` 为 ``haiku`` 时用 IST_HAIKU_MODEL，否则用平台默认模型。
    """
    try:
        import requests as _requests
        from main.ist_core.agents._llm import (
            ist_core_default_model,
            ist_core_tier_model,
            resolve_llm_api_key,
            resolve_llm_base_url,
        )
    except Exception as exc:
        logger.debug("dream LLM setup import 失败: %s", exc)
        return None

    api_key = resolve_llm_api_key()
    if not api_key:
        logger.debug("dream LLM: no OPENAI_API_KEY")
        return None

    base_url = resolve_llm_base_url()

    model = ist_core_tier_model("haiku") if tier == "haiku" else ist_core_default_model()
    return (_requests.Session(), api_key, base_url, model)


def build_dream_consolidate_llm():
    """构建 Dream consolidate（AGENTS.md 蒸馏）用的 ``(prompt) -> str``；无 key 时返回 None。"""
    setup = _dream_llm_http_setup(tier="default")
    if setup is None:
        return None

    try:
        from main.function_llm import TruncationError, chat_completion
    except Exception as exc:
        logger.warning("dream consolidate LLM 初始化失败: %s", exc)
        return None

    session, api_key, base_url, model = setup

    def _llm_chat(prompt: str) -> str:
        """适配 DreamTask.consolidate 的 (prompt) -> str 接口。"""
        import json

        try:
            result = chat_completion(
                session,
                api_key,
                _CONSOLIDATE_SYSTEM_PROMPT,
                prompt,
                model=model,
                base_url=base_url,
                max_tokens=4096,
                temperature=0.1,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except TruncationError:
            logger.warning("consolidate LLM 输出被截断")
            return "[]"
        except Exception as exc:
            logger.warning("consolidate llm_chat 失败: %s", exc)
            return "[]"

    logger.info("dream consolidate LLM: model=%s", model)
    return _llm_chat


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
    files: list[tuple[str, float]]


@dataclass
class Payload:
    path: str
    content: str







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
    
    if (os.environ.get("IST_DREAM_ENABLED") or "1").strip() == "0":
        return False, "disabled by IST_DREAM_ENABLED=0"

    if (os.environ.get("IST_MEMORY_ENABLED") or "1").strip() == "0":
        return False, "disabled by IST_MEMORY_ENABLED=0"

    if (os.environ.get("IST_MEMORY_DISABLE_LLM") or "0").strip() == "1":
        return False, "disabled by IST_MEMORY_DISABLE_LLM=1"

    
    last_run = _last_run_path()
    if last_run.exists():
        try:
            ts = float(last_run.read_text(encoding="utf-8").strip())
            hours_ago = (time.time() - ts) / 3600
            if hours_ago < 24:
                return False, f"ran {hours_ago:.1f}h ago (< 24h)"
        except Exception:
            pass

    
    pid_path = _pid_lock_path()
    if pid_path.exists():
        try:
            age_min = (time.time() - pid_path.stat().st_mtime) / 60
            if age_min < 10:
                return False, f"scan throttled ({age_min:.1f}min < 10min)"
        except Exception:
            pass

    
    sessions = read_session_counter()
    min_sessions = int(os.environ.get("IST_DREAM_MIN_SESSIONS") or "5")
    if sessions < min_sessions:
        return False, f"only {sessions} sessions (need >= {min_sessions})"

    
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
        
        try:
            old_pid = int(pid_path.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
            return False
        except (ProcessLookupError, ValueError, OSError):
            
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







class DreamTask:
    def __init__(self, *, store: MemoryStore, llm_chat: Any) -> None:
        self._store = store
        self._llm = llm_chat
        self._lookback_days = int(os.environ.get("IST_DREAM_LOOKBACK_DAYS") or "7")
        self._prune_days = int(os.environ.get("IST_DREAM_PRUNE_DAYS") or "7")

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
        """阶段 3：Footprint 纯规则提取 + LLM 抽取 → AGENTS.md。"""
        if not payloads:
            return []

        
        fp_decisions = self._consolidate_footprints()

        
        if self._llm is None:
            return fp_decisions or ["skip: no LLM configured"]

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
            '请输出 JSON 对象，形如 {"decisions": [...]}，其中 decisions 是动作列表，'
            "每个动作为以下之一：\n"
            '  {"action":"skip"}\n'
            '  {"action":"append_agents_md","content":"新增行"}\n'
            '  {"action":"merge","source":"路径","target":"路径","reason":"原因"}\n'
            '只输出 JSON 对象，不要其他文字。如果无操作，输出 {"decisions": []}\n'
        )

        try:
            result = self._llm(prompt)
            import json
            parsed = json.loads(result) if isinstance(result, str) else result
            decisions = _coerce_decisions(parsed)
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
        return fp_decisions + applied

    def _consolidate_footprints(self) -> list[str]:
        """LLM 提取 footprint 产品事实，然后纯代码 route + merge。

        使用 IST_HAIKU_MODEL（默认 deepseek-v4-flash）降低成本。
        """
        if os.environ.get("FOOTPRINT_ENABLED", "1") != "1":
            return []

        try:
            from main.ist_core.memory.footprint import extract_facts, route_facts, merge_fact
        except Exception as exc:
            logger.debug("footprint import 失败: %s", exc)
            return []

        
        llm_chat = self._build_footprint_llm()
        if llm_chat is None:
            return []

        root = get_default_root()
        from main import knowledge_paths as kp
        footprint_dir = kp.KNOWLEDGE_FOOTPRINTS
        working_dir = root / "working"

        if not working_dir.exists():
            return []

        nodes_dir = kp.KNOWLEDGE_FOOTPRINTS_NODES
        nodes_dir.mkdir(parents=True, exist_ok=True)

        cutoff = time.time() - self._lookback_days * 86400
        results: list[str] = []

        for f in sorted(working_dir.glob("*.md")):
            try:
                if f.stat().st_mtime < cutoff:
                    continue
                content = f.read_text(encoding="utf-8")
                if len(content) < 200:
                    continue

                
                
                existing = _load_existing_facts(footprint_dir)
                facts = extract_facts(content, llm_chat=llm_chat, existing_facts=existing)
                if not facts:
                    continue

                routed = route_facts(facts, footprint_dir)
                for rf in routed:
                    r = merge_fact(rf, footprint_dir)
                    if r.action != "skip":
                        results.append(f"footprint:{r.action}:{r.target_file}")
            except Exception as exc:
                logger.debug("footprint %s: %s", f.name, exc)

        
        try:
            from main.ist_core.memory.footprint import reconcile
            stats = reconcile(footprint_dir)
            results.append(
                f"footprint:reconcile:total={stats['total']} "
                f"created={stats['created']} {stats['by_level']}"
            )
        except Exception as exc:
            logger.warning("footprint reconcile 失败: %s", exc)

        return results

    def _build_footprint_llm(self):
        """构建 footprint 提取用的 haiku tier LLM 调用函数。

        复用 function_llm.chat_completion，获得 retry + truncation 检测 + cache。
        使用 IST_HAIKU_MODEL（默认 deepseek-v4-flash）。
        """
        setup = _dream_llm_http_setup(tier="haiku")
        if setup is None:
            return None

        try:
            from main.function_llm import TruncationError, chat_completion
        except Exception as exc:
            logger.debug("footprint LLM 构建失败: %s", exc)
            return None

        session, api_key, base_url, model = setup

        def _call(system_prompt: str, user_prompt: str, tool: dict | None = None):
            try:
                return chat_completion(
                    session,
                    api_key,
                    system_prompt,
                    user_prompt,
                    model=model,
                    base_url=base_url,
                    # 16384：strict schema 填全字段输出更冗长，放大保底避免 max_tokens 截断（与 backfill 一致）。
                    max_tokens=16384,
                    temperature=0.1,
                    top_p=0.1,
                    tool=tool,
                )
            except TruncationError:
                logger.warning("footprint LLM 输出被截断，跳过")
                return {"facts": []}

        logger.info("footprint LLM: model=%s", model)
        return _call

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
                    
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime(mtime))
                    archived = archive_dir / f"{f.stem}.{ts}{f.suffix}"
                    f.replace(archived)
                    pruned += 1
                elif rel.startswith("long_term/"):
                    
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


__all__ = [
    "DreamReport",
    "DreamTask",
    "build_dream_consolidate_llm",
    "should_run_dream",
    "run_dream_with_gates",
    "maybe_trigger_dream_async",
]







def run_dream_with_gates() -> tuple[DreamReport | None, str]:
    """完整 cron 入口：跑五道闸 → 拿锁 → 跑 DreamTask → 释放锁 + 重置计数器。

    返回 (report, reason)；闸拒绝时 report=None 且 reason 给出原因。
    DreamTask.run() finally 块负责释放锁、归零计数器、写 last_run。
    """
    ok, reason = should_run_dream()
    if not ok:
        return None, reason

    try:
        
        backend = build_memory_backend()
        store = MemoryStore(backend, get_default_root())

        llm_chat = build_dream_consolidate_llm()

        task = DreamTask(store=store, llm_chat=llm_chat)
        report = task.run()
        return report, "ok"
    except Exception as exc:
        logger.exception("run_dream_with_gates 失败: %s", exc)

        try:
            _release_pid_lock()
        except Exception:
            pass
        return None, f"setup failed: {exc}"


# 进程内自调度：守护线程后台跑一次 run_dream_with_gates。
# 适用于「TUI 进程常驻、不依赖系统 crontab」的场景——五道闸（24h 节流 + PID 锁）
# 保证一天最多跑一次，且不会与 cron / 其他进程并发。
_INPROC_DREAM_STARTED = False


def maybe_trigger_dream_async() -> bool:
    """在后台守护线程触发一次 dream（受五道闸约束）。

    - 进程内只起一次线程（``_INPROC_DREAM_STARTED`` 幂等）
    - 守护线程：绝不阻塞主流程 / 不阻止进程退出
    - 全异常静默：dream 失败不影响 TUI
    - 闸门拒绝（24h 内已跑 / 不足 5 sessions 等）是正常路径，仅 debug 日志

    返回是否真正起了线程（已起过或被 env 关闭则 False）。
    """
    global _INPROC_DREAM_STARTED
    if _INPROC_DREAM_STARTED:
        return False
    if (os.environ.get("IST_DREAM_ENABLED") or "1").strip() == "0":
        return False
    if (os.environ.get("IST_DREAM_INPROC") or "1").strip() == "0":
        return False
    _INPROC_DREAM_STARTED = True

    import threading

    def _worker() -> None:
        try:
            report, reason = run_dream_with_gates()
            if report is not None:
                logger.info("[dream] in-process run done: %s", report)
            else:
                logger.debug("[dream] in-process skip: %s", reason)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[dream] in-process trigger failed: %s", exc)

    t = threading.Thread(target=_worker, name="ist-dream-inproc", daemon=True)
    t.start()
    return True
