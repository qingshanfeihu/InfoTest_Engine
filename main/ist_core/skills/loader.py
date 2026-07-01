"""Skill + Subagent Loader.

Skills (skills/<name>/SKILL.md):
  - inline: 返回 body 注入主对话
  - fork: SKILL.md body 渲染后作为 HumanMessage 传给 agent: 引用的 subagent

Subagents (agents/<name>.md):
  - frontmatter: name, description, tools, model
  - markdown body = system_prompt（容器行为约束）

后续加新 fork skill 只需写 SKILL.md + 引用已注册的 subagent。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from main.ist_core.resilience import is_transient_error

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent
_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"

# fork 子 agent 可观测性：每次 fork 执行把内部工具调用分布/轮数/耗时落到此日志，
# 用于诊断「draft/grade 慢在哪一步」（fork 内部 LLM 往返不进主 stream）。
# 路径走 IST_SESSION_DIR/runtime，默认 runtime/logs/fork_trace.log。
_FORK_TRACE_PATH = os.environ.get("IST_FORK_TRACE_LOG") or str(
    Path(__file__).resolve().parents[2] / "runtime" / "logs" / "fork_trace.log"
)

# fork 状态记录（结构化 JSONL，可解析）：每个 fork 的最终状态 + 产物摘要持久化，
# 使主循环中途崩溃时「哪些 fork 已完成、产出什么」不丢失（fork_trace.log 是人读摘要，
# 这个是机读状态）。一行一条 JSON。
_FORK_STATUS_PATH = os.environ.get("IST_FORK_STATUS_LOG") or str(
    Path(__file__).resolve().parents[2] / "runtime" / "logs" / "fork_status.jsonl"
)


def _record_fork_status(skill_name: str, agent_name: str, elapsed_s: float,
                        summary: dict, *, ok: bool, output: str = "", error: str = "") -> None:
    """把单次 fork 的最终状态写成一行 JSON（持久化，崩溃不丢已完成记录）。"""
    try:
        import json as _json
        # output 只存摘要（首 500 字符），避免日志膨胀，又足够事后追溯产物。
        out_digest = (output or "").strip()[:500]
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "skill": skill_name,
            "agent": agent_name,
            "ok": ok,
            "elapsed_s": round(elapsed_s, 1),
            "ai_rounds": summary.get("ai_rounds", 0),
            "tool_results": summary.get("tool_results", 0),
            "tool_calls": summary.get("tool_calls", {}),
            "search_queries": summary.get("search_queries", {}),
            "output_digest": out_digest,
            "error": error,
        }
        p = Path(_FORK_STATUS_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 状态记录绝不能影响主流程
        logger.debug("fork status 写入失败", exc_info=True)


def _summarize_fork_messages(messages: list) -> dict:
    """从 fork 子 agent 返回的 messages 统计可观测指标：
    工具调用分布、AI 轮数（≈LLM 往返）、ToolMessage 数。
    额外记录 grep / footprint_lookup 的实际查询词（诊断「在查什么」用，截断防膨胀）。"""
    tool_calls: Counter = Counter()
    ai_rounds = 0
    tool_results = 0
    search_queries: dict[str, list[str]] = {"fs_grep": [],
                                             "kb_footprint": []}
    for m in messages:
        mtype = getattr(m, "type", "")
        if mtype == "ai":
            ai_rounds += 1
            for tc in (getattr(m, "tool_calls", None) or []):
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name:
                    tool_calls[name] += 1
                if name in search_queries:
                    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                    q = ""
                    if isinstance(args, dict):
                        q = str(args.get("pattern") or args.get("command") or args.get("query") or "")
                    if q:
                        search_queries[name].append(q[:80])
        elif mtype == "tool":
            tool_results += 1
    return {
        "ai_rounds": ai_rounds,
        "tool_results": tool_results,
        "tool_calls": dict(tool_calls),
        "search_queries": {k: v for k, v in search_queries.items() if v},
    }


def _trace_fork(skill_name: str, brief: str, elapsed_s: float, summary: dict, error: str = "") -> None:
    """把单次 fork 执行的可观测摘要落到 fork_trace.log（失败静默，不挂主流程）。"""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        # brief 取首行 + 截断，避免日志过长，且不泄露完整内容
        brief_head = (brief or "").strip().splitlines()[0][:80] if brief else ""
        tc = summary.get("tool_calls", {})
        tc_str = ", ".join(f"{k}={v}" for k, v in sorted(tc.items(), key=lambda x: -x[1]))
        line = (
            f"[{ts}] fork={skill_name} elapsed={elapsed_s:.1f}s "
            f"ai_rounds={summary.get('ai_rounds', 0)} "
            f"tool_results={summary.get('tool_results', 0)} "
            f"tools=[{tc_str}]"
            + (f" ERROR={error}" if error else "")
            + f" brief1={brief_head!r}\n"
        )
        p = Path(_FORK_TRACE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
        # 同时进模块 logger（便于 stderr 实时看）
        logger.info(
            "fork %s done: elapsed=%.1fs ai_rounds=%d tools=[%s]",
            skill_name, elapsed_s, summary.get("ai_rounds", 0), tc_str,
        )
    except Exception:  # noqa: BLE001 — 可观测性绝不能影响主流程
        logger.debug("fork trace 写入失败", exc_info=True)


def _dump_full_trace(skill_name: str, messages: list) -> None:
    """``IST_FORK_TRACE_FULL=1`` 时，把 fork **完整对话**（每轮 AI 推理文本 + 工具调用 args +
    工具返回摘要）落到 ``fork_full_trace.log``，供诊断「fork 一步步在想什么、为什么反复查 footprint」。
    默认关；失败静默，绝不影响主流程。"""
    if (os.environ.get("IST_FORK_TRACE_FULL") or "0").strip().lower() not in ("1", "true", "on", "yes"):
        return
    try:
        import json as _json
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"\n{'='*72}", f"[{ts}] FORK={skill_name}  全程思考（{len(messages)} 条消息）", "=" * 72]
        step = 0
        for m in messages:
            mtype = getattr(m, "type", "")
            if mtype == "ai":
                step += 1
                content = m.content if isinstance(m.content, str) else str(m.content)
                if content.strip():
                    lines.append(f"\n[AI#{step} 推理] {content.strip()}")
                for tc in (getattr(m, "tool_calls", None) or []):
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                    lines.append(f"   → 调用 {name}({_json.dumps(args, ensure_ascii=False)[:300]})")
            elif mtype == "tool":
                c = m.content if isinstance(m.content, str) else str(m.content)
                lines.append(f"   ← 返回 {c.strip()[:300]}")
        path = Path(_FORK_TRACE_PATH).parent / "fork_full_trace.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:  # noqa: BLE001
        logger.debug("fork full trace 写入失败", exc_info=True)


_MODEL_MAP = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
}

_TOOL_REGISTRY: dict[str, Any] = {}
_SUBAGENT_RUNNABLE_CACHE: dict[str, Any] = {}


def _get_tool_registry() -> dict[str, Any]:
    """延迟加载工具注册表——包含所有可能被 fork skill 使用的工具。"""
    if not _TOOL_REGISTRY:
        from main.ist_core.tools.deepagent import (
            fs_glob,
            fs_grep,
            fs_ls,
            fs_read,
            fs_write,
        )
        _TOOL_REGISTRY.update({
            "fs_read": fs_read,
            "fs_grep": fs_grep,
            "fs_ls": fs_ls,
            "fs_glob": fs_glob,
            "fs_write": fs_write,
        })
        try:
            from main.ist_core.tools.deepagent.exec_tools import run_shell, run_python
            _TOOL_REGISTRY["run_shell"] = run_shell
            _TOOL_REGISTRY["run_python"] = run_python
        except ImportError:
            logger.debug("工具 run_shell/run_python 未可用，跳过注册")
        try:
            from main.ist_core.tools.device import dev_rest, dev_ssh
            _TOOL_REGISTRY["dev_ssh"] = dev_ssh
            _TOOL_REGISTRY["dev_rest"] = dev_rest
        except ImportError:
            logger.debug("工具 dev_ssh/dev_rest 未可用，跳过注册")
        try:
            from main.ist_core.tools.knowledge.kb_bug_search import kb_bug_search
            _TOOL_REGISTRY["kb_bug_search"] = kb_bug_search
        except ImportError:
            logger.debug("工具 kb_bug_search 未可用，跳过注册")
        try:
            from main.ist_core.tools.knowledge.footprint_lookup import (
                kb_footprint,
            )

            _TOOL_REGISTRY["kb_footprint"] = kb_footprint
        except ImportError:
            logger.debug("工具 kb_footprint 未可用，跳过注册")
        # 单 case 编译/上机 tools（draft/grade 子 agent 用）
        try:
            from main.ist_core.tools.device import (
                compile_emit,
                compile_check_verifiability,
                compile_grade_extract,
                dev_probe,
                dev_run_case,
                dev_init_device,
            )
            _TOOL_REGISTRY["compile_emit"] = compile_emit
            _TOOL_REGISTRY["compile_check_verifiability"] = compile_check_verifiability
            _TOOL_REGISTRY["compile_grade_extract"] = compile_grade_extract
            _TOOL_REGISTRY["dev_run_case"] = dev_run_case
            _TOOL_REGISTRY["dev_probe"] = dev_probe
            _TOOL_REGISTRY["dev_init_device"] = dev_init_device
        except ImportError:
            logger.debug("工具 compile_emit/dev_probe/dev_run_case 未可用，跳过注册")
        # 批量编译 tools（ist_compile 编译链用）：解析清单 + 合并打包 + fan-out + 串行上机
        try:
            from main.ist_core.tools.device import (
                compile_fanout,
                compile_prep,
                compile_emit_merged,
                dev_run_batch,
            )
            _TOOL_REGISTRY["compile_prep"] = compile_prep
            _TOOL_REGISTRY["compile_emit_merged"] = compile_emit_merged
            _TOOL_REGISTRY["compile_fanout"] = compile_fanout
            _TOOL_REGISTRY["dev_run_batch"] = dev_run_batch
        except ImportError:
            logger.debug("工具 compile_prep/compile_emit_merged/compile_fanout/dev_run_batch 未可用，跳过注册")
        try:
            from main.ist_core.tools.device.precedent_tools import (
                compile_score,
                compile_precedent,
            )
            _TOOL_REGISTRY["compile_precedent"] = compile_precedent
            _TOOL_REGISTRY["compile_score"] = compile_score
        except ImportError:
            logger.debug("工具 compile_precedent/compile_score 未可用，跳过注册")
        try:
            from main.ist_core.tools.knowledge.command_builder import build_command
            _TOOL_REGISTRY["build_command"] = build_command
        except ImportError:
            logger.debug("工具 build_command 未可用，跳过注册")
    return _TOOL_REGISTRY


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """解析 frontmatter 布尔值（true/yes/1/on）。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return default


def skill_disable_model_invocation(fm: dict[str, Any]) -> bool:
    """``disable-model-invocation: true`` → 禁止主 agent 经 ``invoke_skill`` 加载。"""
    return _coerce_bool(fm.get("disable-model-invocation"))


def read_skill_frontmatter(skill_md_path: Path) -> dict[str, Any] | None:
    """读取 SKILL.md frontmatter dict；解析失败返回 None。"""
    parsed = _parse_skill_md(skill_md_path)
    return parsed["frontmatter"] if parsed else None


def _parse_skill_md(path: Path) -> dict[str, Any] | None:
    """解析 SKILL.md / subagent .md，返回 {frontmatter, body} 或 None。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        logger.warning("Failed to parse frontmatter: %s", path)
        return None
    return {"frontmatter": fm, "body": parts[2].strip()}


def _resolve_tools(allowed: list[str] | str) -> list[Any]:
    """从 frontmatter tools / allowed-tools 解析实际工具对象。

    支持两种格式：
    - 列表：["tool_a", "tool_b(path/*)"]
    - 字符串：逗号或空格分隔，"tool_a, tool_b" 或 "tool_a tool_b"
    """
    registry = _get_tool_registry()
    if isinstance(allowed, str):
        
        
        items = [t.strip() for t in allowed.replace(",", " ").split() if t.strip()]
    else:
        items = list(allowed or [])

    tools = []
    for name in items:
        base_name = name.split("(")[0].strip()
        if base_name in registry:
            tools.append(registry[base_name])
        elif base_name:
            # 哨兵：子 agent frontmatter 声明了未注册工具 → 静默丢弃曾让 fs_glob 之类
            # 改 frontmatter 也不生效且无报错。打 warning 暴露，提示补进 _get_tool_registry()。
            logger.warning(
                "_resolve_tools: 未注册工具 %r 被忽略（不在 _TOOL_REGISTRY）；"
                "若该工具应供 fork 子流程使用，请补进 _get_tool_registry()。", base_name,
            )
    return tools







def load_subagent(name: str) -> dict[str, Any] | None:
    """从 main/ist_core/agents/<name>.md 加载 subagent 定义。

    其结构设计设计：
    - frontmatter: name, description, tools, model（可选）
    - markdown body = system_prompt

    IST-Core 扩展字段：
    - inherit-parent-prompt: bool — 是否在 body 前 prepend 主 agent 的反偷懒约束块
      （Read-Only / Evidence Discipline / Reading-vs-Verification / Faithful Reporting）

    Returns:
        {name, description, system_prompt, tools_spec, model} 或 None（不存在/解析失败）
    """
    md_path = _AGENTS_DIR / f"{name}.md"
    if not md_path.exists():
        return None

    parsed = _parse_skill_md(md_path)
    if parsed is None:
        return None

    fm = parsed["frontmatter"]
    body = parsed["body"]

    
    if _coerce_bool(fm.get("inherit-parent-prompt"), default=False):
        try:
            from main.ist_core.agents._prompt import build_verifier_inherited_sections
            body = build_verifier_inherited_sections() + "\n\n---\n\n" + body
        except Exception:  # noqa: BLE001
            logger.exception("Failed to prepend verifier inherited sections for %s", name)

    return {
        "name": fm.get("name", name),
        "description": fm.get("description", ""),
        "system_prompt": body,
        "tools_spec": fm.get("tools") or fm.get("allowed-tools") or [],
        "model": fm.get("model", "opus"),
    }


def get_subagent_runnable(name: str) -> Any | None:
    """构建并缓存 subagent 的 LangChain runnable。

    缓存策略：按 name 缓存。如需刷新（如热重载 .md 文件），调 clear_subagent_cache()。
    """
    if name in _SUBAGENT_RUNNABLE_CACHE:
        return _SUBAGENT_RUNNABLE_CACHE[name]

    spec = load_subagent(name)
    if spec is None:
        return None

    try:
        from langchain.agents import create_agent

        from main.ist_core.agents._llm import build_agent_chat_model, ist_core_tier_model

        model_name = spec["model"]
        model_tier = _MODEL_MAP.get(model_name, model_name)
        # fork LLM 强制非流式：fork 子流程不进 TUI 流式渲染,而流式遇不稳定网关会周期发空 chunk
        # → httpx 每 chunk 重置读超时 → 整体响应永不完成(0% CPU 死挂、draft 卡满墙钟)。非流式是
        # 单次请求 + 干净 request_timeout,遇 stall 按时超时重试,不无限挂。主 TUI 流式不受影响。
        model = build_agent_chat_model(
            model=ist_core_tier_model(model_tier), streaming=False, stream_usage=False)

        tools = _resolve_tools(spec["tools_spec"])

        runnable = create_agent(
            model,
            system_prompt=spec["system_prompt"],
            tools=tools,
            name=spec["name"],
        ).with_config({"recursion_limit": int(os.environ.get("IST_FORK_RECURSION_LIMIT") or 120)})

        _SUBAGENT_RUNNABLE_CACHE[spec["name"]] = runnable
        return runnable
    except Exception:
        logger.exception("Failed to build subagent runnable for %s", name)
        return None


def clear_subagent_cache() -> None:
    """清缓存（测试 / 热重载用）。"""
    _SUBAGENT_RUNNABLE_CACHE.clear()


def list_subagents() -> list[dict[str, str]]:
    """列出 agents/ 目录下所有 subagent 定义文件。"""
    out = []
    if not _AGENTS_DIR.exists():
        return out
    for md_file in sorted(_AGENTS_DIR.glob("*.md")):
        spec = load_subagent(md_file.stem)
        if spec:
            out.append({"name": spec["name"], "description": spec["description"]})
    return out







def _fork_step_emit_enabled() -> bool:
    return os.environ.get("IST_FORK_STEP_EMIT", "1") != "0"


# fastlog 式 evidence:fork 步骤行**全速追加写日志文件**,TUI 自己定时 tail 渲染
# (见 ist_app._start_evidence_tailer)。彻底解耦"高频 evidence 产出"与"TUI 渲染"——
# 不论 N case(如 53)并发写多快,TUI 都按固定节奏(~300ms)读、不会被刷卡;且文件
# 可被外部 `tail -f` 直接看运行过程。线程池 worker 并发调用,故共享句柄 + 加锁。
_EV_LOG_FH = None
_EV_LOG_LOCK = threading.Lock()


def _evidence_log_path() -> str:
    """evidence 实时日志路径(IST_EVIDENCE_LOG 可覆盖;默认 runtime/logs/)。"""
    p = os.environ.get("IST_EVIDENCE_LOG")
    if p:
        return p
    # 默认按 pid 分文件:多个 infotest 实例并存时各写各的、互不串台/互不清空(显式给 IST_EVIDENCE_LOG 则共用该路径)。
    return str(Path(__file__).resolve().parents[3] / "runtime" / "logs" / f"compile_evidence.{os.getpid()}.live.log")


def reset_evidence_log() -> None:
    """清空 evidence 日志(TUI 启动时调,每会话从干净开始)。失败静默。"""
    global _EV_LOG_FH
    try:
        with _EV_LOG_LOCK:
            if _EV_LOG_FH is not None:
                try:
                    _EV_LOG_FH.close()
                except Exception:
                    pass
                _EV_LOG_FH = None
            path = Path(_evidence_log_path())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            # 清理同目录早已过时的旧 pid evidence 文件(>6h 未写=对应 infotest 进程多半已退)，避免按 pid 分文件后累积。
            import time as _t
            _cut = _t.time() - 6 * 3600
            for _old in path.parent.glob("compile_evidence.*.live.log"):
                if _old != path and _old.stat().st_mtime < _cut:
                    _old.unlink()
    except Exception:
        pass


def _fork_emit(text: str) -> None:
    """把 fork 内部一步可观测信息**追加到 evidence 日志文件**(fastlog:producer 全速
    写、TUI 定时读)。共享句柄 + 锁(线程池并发);flush 让 tail 端及时见。
    失败静默——可观测性不能拖垮编译。"""
    global _EV_LOG_FH
    try:
        with _EV_LOG_LOCK:
            if _EV_LOG_FH is None:
                path = Path(_evidence_log_path())
                path.parent.mkdir(parents=True, exist_ok=True)
                _EV_LOG_FH = open(path, "a", encoding="utf-8")
            _EV_LOG_FH.write(text + "\n")
            _EV_LOG_FH.flush()
    except Exception:
        pass


# fork token 用量累计:compile 期主 agent 阻塞在 compile_pipeline、footer token 冻结,
# 实际烧的是 draft/grade fork 的 LLM 调用。这里累加,供 TUI footer 单独显示真实成本。
_FORK_TOKENS = [0, 0]  # [input, output]
_FORK_TOKENS_LOCK = threading.Lock()


def _accumulate_fork_tokens(msg: Any) -> None:
    try:
        um = getattr(msg, "usage_metadata", None) or {}
        it = um.get("input_tokens", 0) or 0
        ot = um.get("output_tokens", 0) or 0
        if it or ot:
            with _FORK_TOKENS_LOCK:
                _FORK_TOKENS[0] += it
                _FORK_TOKENS[1] += ot
    except Exception:
        pass


def get_fork_tokens() -> tuple[int, int]:
    """返回 (input, output) fork token 累计(供 TUI 显示)。"""
    with _FORK_TOKENS_LOCK:
        return (_FORK_TOKENS[0], _FORK_TOKENS[1])


def reset_fork_tokens() -> None:
    with _FORK_TOKENS_LOCK:
        _FORK_TOKENS[0] = 0
        _FORK_TOKENS[1] = 0


# 路径类参数:只展示尾部(basename/末两段)——项目绝对路径前缀对所有调用都一样、无信息量。
_FORK_PATH_KEYS = ("path", "file_path", "xlsx_path", "provenance_path", "mindmap_path")
# 取值优先级:语义参数(搜什么/查什么)排在路径前——如 fs_grep 显示搜索 pattern 比显示手册路径有用。
_FORK_ARG_KEYS = (
    "command", "query", "pattern", "glob", "feature_id", "skill", "name", "autoid",
    "path", "file_path", "xlsx_path", "provenance_path", "mindmap_path",
)


def _short_fork_args(args: Any, limit: int = 48) -> str:
    """从 tool_call 的 args 取一个有代表性的标量参数,截断成单行展示。

    路径类参数只显示尾部文件名(前缀对项目内所有绝对路径都一样、纯噪声);
    语义参数(pattern/query/command)优先于路径(fs_grep 显示"搜什么"比"在哪搜"有用)。
    """
    if not isinstance(args, dict) or not args:
        return ""
    for k in _FORK_ARG_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            s = v.strip().replace("\n", " ")
            if k in _FORK_PATH_KEYS and "/" in s:
                parts = [p for p in s.split("/") if p]
                if len(parts) > 2:
                    s = "…/" + "/".join(parts[-2:])
            return "(" + s[:limit] + ")"
    for v in args.values():
        if isinstance(v, (str, int, float)) and str(v).strip():
            return "(" + str(v).strip().replace("\n", " ")[:limit] + ")"
    return ""


# compile_score 等工具返回 indent=2 的 pretty JSON(首行只有 `{`)——_short_fork_result 旧逻辑取
# 首行只会显示 `{`,评分详情(overall/decision)全丢。下面把 JSON 压成单行关键字段预览,跳过
# tool/note/how_to_use 等噪声键(非领域命令),让 TUI 看到 `overall=0.0 decision=CUT… checkpoints[5]`。
_JSON_NOISE_KEYS = {"tool", "note", "hint", "how_to_use", "arm"}


def _json_one_line_preview(s: str, limit: int) -> str:
    """JSON 工具返回压成单行关键字段预览;非合法 JSON(如 run_python 的 py repr)回退纯压平兜底。"""
    import json
    try:
        obj = json.loads(s)
    except Exception:  # noqa: BLE001 — 非合法 JSON → 压平兜底(顺带优雅处理 py repr)
        flat = " ".join(s.split())
        return flat[:limit] + ("…" if len(flat) > limit else "")
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            if k in _JSON_NOISE_KEYS:
                continue
            if isinstance(v, (bool, int, float, str)):
                parts.append(f"{k}={v}")
            elif isinstance(v, list):
                parts.append(f"{k}[{len(v)}]")
            elif isinstance(v, dict):
                parts.append(f"{k}{{…}}")
        out = " ".join(parts) if parts else " ".join(s.split())
    else:   # 顶层数组
        out = f"[{len(obj)}项] " + " ".join(s.split())
    return out[:limit] + ("…" if len(out) > limit else "")


def _short_fork_result(content: Any, limit: int = 140) -> str:
    """把工具结果压成单行简洁预览,带上**实质内容**而不只是节点标识。

    footprint 输出是 `## {feature_id} ({level}, verified Nx)` + `  - {命令}` 列表,
    旧版只抓首行 → 预览只剩节点名(`sdns.host.persistence (leaf, verified 7x)`),
    draft 真正查到的**命令语法**全丢了(用户反馈"footprint 结果都是空")。改为
    `{feature_id}: {首条命令}  (+N)`,让"查到什么命令"可见。dev_probe 设备回显 /
    precedent 条数 / emit 产出·被拒原因(无 `  - ` 列表)行为不变:仍取首行真内容。"""
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or "")
            else:
                parts.append(str(b))
        content = " ".join(p for p in parts if p)
    s = str(content or "").strip()
    if not s:
        return ""
    if s[:1] in ("{", "["):          # JSON 工具返回(compile_score 等 pretty JSON)→ 关键字段单行预览
        return _json_one_line_preview(s, limit)
    # 跳过工具自带的头部横幅/分隔线 + 元数据标签行,抓第一行**真内容**(如 dev_probe 的设备回显)。
    # dev_probe 格式:`=== dev_probe ===` / `command: {cmd}` / `--- 设备回显 ---` / `{真实输出}`
    # —— 不跳 `command:` 就只会显示命令回显而非设备响应(用户要看的是"查到什么")。
    _META = ("command:", "status:", "exit_code:", "host=", "mode=", "key=")
    head = ""           # 首行真内容(footprint 节点头 / dev_probe 回显 / precedent 摘要)
    bullets: list[str] = []  # footprint 的 `  - {命令/规则}` 列表项 = 实质内容
    for ln in s.splitlines():
        t = ln.strip()
        if not t:
            continue
        if t.startswith("===") or t.startswith("---") or all(c in "=-_* #" for c in t):
            continue
        # kb_footprint 对每个子命令查询都前置同一句「⚠ 模块总开关…必须先执行」(enable_hint),
        # 跳过它才能露出查询特定的 `## {feature_id}` 节点行——否则所有 footprint 预览看着一样。
        if t.startswith("⚠"):
            continue
        if t.lower().startswith(_META):
            continue
        if t.startswith("- ") or t.startswith("• "):  # 列表项(命令/规则)= footprint 实质内容
            bullets.append(t[2:].strip())
            continue
        if not head:
            head = t.lstrip("#").strip()  # 去掉 `## ` markdown 头标记
            # 去掉 footprint 头的 `(leaf, verified Nx)` 后缀,留干净的 feature_id
            if head.endswith(")") and "(" in head:
                base, paren = head.rsplit("(", 1)
                if "verified" in paren:
                    head = base.strip()
    if head and bullets:
        sep = "" if head.endswith((":", "：")) else ": "
        out = f"{head}{sep}{bullets[0]}"
        if len(bullets) > 1:
            out += f"  (+{len(bullets) - 1})"
    elif head:
        out = head
    elif bullets:
        out = bullets[0] + (f"  (+{len(bullets) - 1})" if len(bullets) > 1 else "")
    else:  # 整段都是横幅/前言(极少)→ 回退第一非空行
        out = next((ln.strip() for ln in s.splitlines() if ln.strip()), s)
    out = " ".join(out.split())
    return out[:limit] + ("…" if len(out) > limit else "")


def _fork_step_lines(label: str, msg: Any) -> list[str]:
    """从一条新消息提取要展示的 fork 步骤:
    - AIMessage 的每个 tool_call → 调用行 ``↳ {label}: {tool}({arg})``
    - ToolMessage 的结果 → 结果预览行 ``  ⤷ {tool} → {首行/截断}``(让"查到什么"可见)。
    """
    lines: list[str] = []
    tcs = getattr(msg, "tool_calls", None) or []
    for tc in tcs:
        if isinstance(tc, dict):
            name = tc.get("name") or "tool"
            targs = tc.get("args") or {}
        else:
            name = getattr(tc, "name", "") or "tool"
            targs = getattr(tc, "args", {}) or {}
        lines.append(f"↳ {label}: {name}{_short_fork_args(targs)}")
    is_tool_result = (
        getattr(msg, "type", "") == "tool" or msg.__class__.__name__ == "ToolMessage"
    )
    if is_tool_result:
        preview = _short_fork_result(getattr(msg, "content", ""))
        if preview:
            tname = getattr(msg, "name", "") or ""
            head = f"{tname} → " if tname else ""
            lines.append(f"  ⤷ {head}{preview}")
    return lines


def _invoke_fork_streamed(runnable: Any, rendered_body: str, label: str) -> dict:
    """跑 fork 并把内部每个工具调用实时发到主 bus(让 TUI 看到 draft/grade 运行过程)。

    用 ``stream(stream_mode='values')``——每个 superstep 吐全量 state,取最后一个作为
    与 ``invoke()`` 等价的最终返回值(同一 runnable 已 baked recursion_limit,行为不变)。
    ``IST_FORK_STEP_EMIT=0`` 可关实时步骤(只留编排层的轮次标记)。"""
    from langchain_core.messages import HumanMessage
    inp = {"messages": [HumanMessage(content=rendered_body)]}
    stream = getattr(runnable, "stream", None)
    if not callable(stream) or not _fork_step_emit_enabled():
        # runnable 不支持流式 或 关了步骤显示(IST_FORK_STEP_EMIT=0)→ 退回阻塞 invoke,
        # 行为与旧版完全一致(只是看不到实时步骤)。
        return runnable.invoke(inp)
    final_state: dict = {}
    seen = 0
    for state in stream(inp, stream_mode="values"):
        if not isinstance(state, dict):
            continue
        final_state = state
        msgs = state.get("messages", []) or []
        for m in msgs[seen:]:
            for line in _fork_step_lines(label, m):
                _fork_emit(line)
            _accumulate_fork_tokens(m)
        seen = len(msgs)
    return final_state


def execute_fork_skill(skill_name: str, brief: str = "", *, tag: str = "",
                       summary_sink: dict | None = None) -> str:
    """执行 fork skill 的定义逻辑。

    流程：
    1. 读 SKILL.md frontmatter，确认 context: fork
    2. 读 agent: 字段，从 agents/ 加载对应 subagent 定义
    3. 渲染 SKILL.md body：替换 $ARGUMENTS 为 brief 内容
    4. 把渲染后的 body 作为 HumanMessage 传给 subagent
       （subagent 的 system_prompt 来自 .md 文件 body，不是 SKILL.md body）
    5. 返回 subagent 最终 AIMessage text

    关键：subagent 的 system_prompt 来自 agents/<agent>.md，SKILL.md body 是任务。

    summary_sink（可选）：传入一个 dict，fork 成功完成后原地写入 _summarize_fork_messages
    的结果（{ai_rounds, tool_results, tool_calls, search_queries}），供调用方聚合可观测
    指标——compile_pipeline 用它统计每 case draft 的 dev_probe/kb_footprint 调用次数与
    LLM 往返轮数（验证预检索是否真减少 LLM 调用/查找）。fork 异常/早退时清空，不污染调用方。
    """
    skill_file = _SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_file.exists():
        return f"ERROR: fork skill {skill_name!r} not found."

    parsed = _parse_skill_md(skill_file)
    if parsed is None:
        return f"ERROR: failed to parse {skill_name}/SKILL.md."

    fm = parsed["frontmatter"]
    if fm.get("context") != "fork":
        return f"ERROR: skill {skill_name!r} is not a fork skill."

    agent_name = (fm.get("agent") or "").strip()
    if not agent_name:
        return (
            f"ERROR: fork skill {skill_name!r} missing required 'agent:' field. "
            f"Fork skills must specify which subagent type "
            f"to use as execution container."
        )

    runnable = get_subagent_runnable(agent_name)
    if runnable is None:
        return (
            f"ERROR: fork skill {skill_name!r} references unknown subagent "
            f"{agent_name!r}. Check main/ist_core/agents/{agent_name}.md."
        )

    rendered_body = _render_skill_body(parsed["body"], brief)

    _t0 = time.monotonic()
    _label = (tag or skill_name.replace("ist_compile_", "")).strip() or skill_name
    try:
        result = _invoke_fork_streamed(runnable, rendered_body, _label)
    except Exception as exc:
        # 递归上限是「已处理」的预期情况——compile_pipeline 会捕获后**立即 escalate**(不再做
        # 3 轮等价重做:同 brief 必然同样递归 spin)。回带确定性标记 `[recursion-limit]` 让上层
        # 据此分流;只记简讯不打 traceback,其它异常才打完整栈。日志已统一进文件(TUI 不糊屏)。
        if exc.__class__.__name__ == "GraphRecursionError":
            logger.warning("Fork skill %s 触发递归上限(立即 escalate,不做等价重做)", skill_name)
            _err = f"[recursion-limit] {str(exc)[:120]}"
        elif is_transient_error(exc):
            logger.debug("Fork skill %s 瞬态错误(已抑制): %s", skill_name, exc)
            _err = str(exc)[:120]
        else:
            logger.exception("Fork skill %s execution failed", skill_name)
            _err = str(exc)[:120]
        _elapsed = time.monotonic() - _t0
        _trace_fork(skill_name, brief, _elapsed, {}, error=_err)
        _record_fork_status(skill_name, agent_name, _elapsed, {}, ok=False,
                            error=_err[:300])
        if summary_sink is not None:
            summary_sink.clear()   # 异常 fork 无可观测 tool_calls，清空防污染调用方
        return f"ERROR: fork skill {skill_name!r} execution failed: {_err}"

    messages = result.get("messages", [])
    _elapsed = time.monotonic() - _t0
    _summary = _summarize_fork_messages(messages)
    # 可观测性①：把 summary 回传给调用方（pipeline 聚合 per-case LLM 往返/工具调用次数）
    if summary_sink is not None:
        summary_sink.clear()
        summary_sink.update(_summary)
    # 可观测性②：落 fork 内部工具调用分布/轮数/耗时到 fork_trace.log
    _trace_fork(skill_name, brief, _elapsed, _summary)
    _dump_full_trace(skill_name, messages)  # IST_FORK_TRACE_FULL=1 时落完整思考

    output = ""
    for msg in reversed(messages):
        if hasattr(msg, "content") and getattr(msg, "type", "") == "ai":
            content = msg.content
            if isinstance(content, str) and content.strip():
                output = content
                break
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                if text_parts:
                    output = "\n".join(text_parts)
                    break

    if output:
        # 结构化状态记录：fork 成功 + 产物摘要（崩溃不丢）
        _record_fork_status(skill_name, agent_name, _elapsed, _summary,
                            ok=not output.startswith("ERROR:"), output=output)
        return output

    _record_fork_status(skill_name, agent_name, _elapsed, _summary, ok=False,
                        error="fork returned no text output")
    return "ERROR: fork skill returned no text output."


def _render_skill_body(body: str, brief: str) -> str:
    """SKILL.md body 中的 $ARGUMENTS 占位符替换为 brief 内容。

    Fork skill 的 body 用 $ARGUMENTS 引用调用者传入的参数。
    如果 body 不含 $ARGUMENTS，则在末尾追加 brief（兼容性兜底）。
    """
    if "$ARGUMENTS" in body or "${ARGUMENTS}" in body:
        return body.replace("${ARGUMENTS}", brief).replace("$ARGUMENTS", brief)
    if brief:
        return body.rstrip() + "\n\n## Brief from caller\n\n" + brief
    return body


__all__ = [
    "read_skill_frontmatter",
    "skill_disable_model_invocation",
    "load_subagent",
    "get_subagent_runnable",
    "clear_subagent_cache",
    "list_subagents",
    "execute_fork_skill",
]
