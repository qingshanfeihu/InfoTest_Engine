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
    "flash": "flash",   # 两档收敛后的新词;旧三词经 tier 解析归并(opus/sonnet→主档,haiku→flash)
    "pro": "opus",
}

_TOOL_REGISTRY: dict[str, Any] = {}
_TOOL_REGISTRY_LOCK = threading.Lock()
_SUBAGENT_RUNNABLE_CACHE: dict[str, Any] = {}


def _get_tool_registry() -> dict[str, Any]:
    """延迟加载工具注册表——包含所有可能被 fork skill 使用的工具。

    必须整体加锁:并发 fork 首调时,无锁版会让后到线程拿到"正在逐段填充"的
    半满 registry(晚注册的 compile_precedent/compile_score 缺失),该线程装配的
    缺工具 runnable 又被 _SUBAGENT_RUNNABLE_CACHE 永久缓存——2026-07-02 实证:
    首轮 34-case 编译 worker 全程调不到 compile_precedent(ToolNode not-a-valid-tool
    ×4,退化 glob 瞎找先例),单线程离线不可复现。
    """
    with _TOOL_REGISTRY_LOCK:
        return _build_tool_registry_locked()


def _build_tool_registry_locked() -> dict[str, Any]:
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
        # 单 case 编译/上机 tools（compile-worker fork 用）
        try:
            from main.ist_core.tools.device import (
                compile_emit,
                compile_check_verifiability,
                dev_probe,
                dev_run_case,
                dev_init_device,
            )
            _TOOL_REGISTRY["compile_emit"] = compile_emit
            _TOOL_REGISTRY["compile_check_verifiability"] = compile_check_verifiability
            _TOOL_REGISTRY["dev_run_case"] = dev_run_case
            _TOOL_REGISTRY["dev_probe"] = dev_probe
            _TOOL_REGISTRY["dev_init_device"] = dev_init_device
        except ImportError:
            logger.debug("工具 compile_emit/dev_probe/dev_run_case 未可用，跳过注册")
        # 批量编译 tools（V6 引擎构件 / ist-verify 链）：解析清单 + 合并打包 + fan-out + 串行上机
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
                compile_precedent,
                compile_writeback,
            )
            _TOOL_REGISTRY["compile_precedent"] = compile_precedent
            _TOOL_REGISTRY["compile_writeback"] = compile_writeback
            from main.ist_core.tools.device.checker_tool import compile_expected_hits
            _TOOL_REGISTRY["compile_expected_hits"] = compile_expected_hits
            # 归因孔(compile-attributor,V6)专用
            from main.ist_core.tools.device import compile_attribute, submit_attribution
            from main.ist_core.tools.device.runtime_fill_tools import (
                compile_runtime_slots, compile_runtime_fill,
            )
            from main.ist_core.tools.knowledge.behavior_tool import submit_behavior_fact
            _TOOL_REGISTRY["compile_attribute"] = compile_attribute
            _TOOL_REGISTRY["submit_attribution"] = submit_attribution
            _TOOL_REGISTRY["compile_runtime_slots"] = compile_runtime_slots
            _TOOL_REGISTRY["compile_runtime_fill"] = compile_runtime_fill
            _TOOL_REGISTRY["submit_behavior_fact"] = submit_behavior_fact
        except ImportError:
            logger.debug("工具 compile_precedent/compile_writeback 未可用，跳过注册")
        try:
            from main.ist_core.tools.knowledge.command_builder import build_command
            _TOOL_REGISTRY["build_command"] = build_command
        except ImportError:
            logger.debug("工具 build_command 未可用，跳过注册")
    return _TOOL_REGISTRY


def resolve_skill_dirname(name: str) -> str:
    """skill 名 → 实际目录名(下划线/连字符互通)。

    B1(2026-07-05):skill 名按官方字符集连字符化(ist_compile→ist-compile 等)。
    旧下划线名仍会出现在历史对话/长会话续聊/旧脚本里——目录级别名兜底,与 TUI
    slash 的互通语义一致。两种拼法都不存在时原样返回,调用方照常报 not found。
    """
    n = (name or "").strip()
    if not n or (_SKILLS_DIR / n / "SKILL.md").exists():
        return n
    for cand in (n.replace("_", "-"), n.replace("-", "_")):
        if cand != n and (_SKILLS_DIR / cand / "SKILL.md").exists():
            logger.info("skill 名别名解析: %r → %r(规范名为连字符,调用方可更新)", n, cand)
            return cand
    return n


# 动态 agent(D 阶段,2026-07-05):main 经 agent_define 工具按 B2 骨架自主生成的
# fork agent/skill 落这里。在 runtime/ 下=文件工具沙箱黑名单内——LLM 只能走
# agent_define 的校验闸创建,不能 fs_write 手搓(门挂凭证路)。
_DYN_SKILLS_DIR = Path(__file__).resolve().parents[3] / "runtime" / "dyn_skills"
_DYN_AGENTS_DIR = Path(__file__).resolve().parents[3] / "runtime" / "dyn_agents"


def skill_md_path(name: str) -> Path:
    """skill 名 → SKILL.md 路径(静态目录优先,动态目录兜底;都不存在返回静态路径供报错)。"""
    static = _SKILLS_DIR / name / "SKILL.md"
    if static.exists():
        return static
    dyn = _DYN_SKILLS_DIR / name / "SKILL.md"
    if dyn.exists():
        return dyn
    return static


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
        md_path = _DYN_AGENTS_DIR / f"{name}.md"   # 动态生成 agent(agent_define 产物)
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
        "effort": str(fm.get("effort", "") or ""),   # 思考深度 high|max(空=全局默认)
    }


def _build_fork_middleware() -> list:
    """fork 子 agent 的中间件栈——与主 agent 对齐(2026-07-05 坑2 修复)。

    曾只挂 LoopGuard:fork worker 单个可跑 900s、堆几十个工具返回,剪枝/信封全漏,
    上下文裸堆积。现对齐三件:LoopGuard(死循环护栏,2026-07-02 实证 emit 连败打转
    25 次)/ ToolResultPrune(旧结果剪枝)/ ToolEnvelope(<tool_result> 统一信封)。
    不挂 ToolGating:fork 工具白名单已由 agents/*.md frontmatter 显式声明。
    """
    out: list = []
    import importlib as _il
    for _mw_name, _mw_import in (
        ("LoopGuardMiddleware", "main.ist_core.middleware.loop_guard"),
        ("MessageSanitizeMiddleware", "main.ist_core.middleware.message_sanitize"),
        ("ToolResultPruneMiddleware", "main.ist_core.middleware.tool_result_prune"),
        ("ToolEnvelopeMiddleware", "main.ist_core.middleware.tool_envelope"),
    ):
        try:
            out.append(getattr(_il.import_module(_mw_import), _mw_name)())
        except Exception:  # noqa: BLE001
            logger.info("fork %s 不可用,跳过", _mw_name)
    return out


def get_subagent_runnable(name: str, *, effort_override: str = "") -> Any | None:
    """构建并缓存 subagent 的 LangChain runnable。

    缓存策略：按 name 缓存。如需刷新（如热重载 .md 文件），调 clear_subagent_cache()。
    effort_override（可选,high|max）：按调用点覆盖 frontmatter 的思考深度——升级重编
    的最后一次用 max。覆盖态另建 runnable、按 `name#effort` 独立缓存键(不污染常规态)。
    """
    eff = (effort_override or "").strip().lower()
    if eff not in ("high", "max"):
        eff = ""
    cache_key = f"{name}#{eff}" if eff else name
    if cache_key in _SUBAGENT_RUNNABLE_CACHE:
        return _SUBAGENT_RUNNABLE_CACHE[cache_key]

    spec = load_subagent(name)
    if spec is None:
        return None

    try:
        from langchain.agents import create_agent

        from main.ist_core.agents._llm import build_agent_chat_model, ist_core_tier_model

        model_name = spec["model"]
        model_tier = _MODEL_MAP.get(model_name, model_name)
        # fork 跟随全局流式(2026-07-07 翻案):历史上强制非流式是「空 chunk 挂死」还没停滞守卫
        # 时的止血(streaming=False 引入 06-28,守卫 07-05 晚一周、fork 那条一直没回头重审)。现在
        # _stream/_astream 的 _chunk_has_substance 守卫已能区分保活空 chunk 与真进度(真 reasoning
        # 增量持续续期,连续 180s 纯空 chunk 才断流)——非流式不再必需。走流式让 fork 的 .invoke 经
        # _should_stream→_stream 守卫(langchain_core:self.streaming 为真且未 disable_streaming →
        # _generate 委托 _stream),深思考 worker 靠「有真输出就续期」不被固定墙钟误杀;批量 print
        # 模式 IST_LLM_STREAMING=0 时 build_agent_chat_model 全局回落非流式(并发批量仍稳)。
        # 不传 streaming= → 由 build_agent_chat_model 按 _resolve_streaming() 全局默认决定。
        # max request_timeout 兜底仅在非流式模式生效(env IST_LLM_TIMEOUT_MAX,默认 600)。
        _extra: dict[str, Any] = {}
        if eff == "max":
            try:
                _extra["request_timeout"] = float(os.environ.get("IST_LLM_TIMEOUT_MAX") or 600)
            except (TypeError, ValueError):
                _extra["request_timeout"] = 600.0
        model = build_agent_chat_model(
            model=ist_core_tier_model(model_tier),
            effort=eff or spec.get("effort") or "", **_extra)

        tools = _resolve_tools(spec["tools_spec"])

        fork_middleware = _build_fork_middleware()

        runnable = create_agent(
            model,
            system_prompt=spec["system_prompt"],
            tools=tools,
            name=spec["name"],
            middleware=fork_middleware,
        ).with_config({"recursion_limit": int(os.environ.get("IST_FORK_RECURSION_LIMIT") or 120)})

        _SUBAGENT_RUNNABLE_CACHE[cache_key] = runnable
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
# 双通道(2026-07-06):.live.log 人读行(tail -f 契约不变) + .events.jsonl 结构化
# 事件流(fork_start/tool/tool_result/fork_end/run_meta/engine_tick/progress),
# TUI 卡片模式(IST_FORK_CARDS)读后者按 fork/run 聚合原地更新,不再平铺。
_EV_LOG_FH = None
_EV_EVENTS_FH = None
_EV_LOG_LOCK = threading.Lock()


def _evidence_log_path() -> str:
    """evidence 实时日志路径(IST_EVIDENCE_LOG 可覆盖;默认 runtime/logs/)。"""
    p = os.environ.get("IST_EVIDENCE_LOG")
    if p:
        return p
    # 默认按 pid 分文件:多个 infotest 实例并存时各写各的、互不串台/互不清空(显式给 IST_EVIDENCE_LOG 则共用该路径)。
    return str(Path(__file__).resolve().parents[3] / "runtime" / "logs" / f"compile_evidence.{os.getpid()}.live.log")


def _fork_events_path() -> str:
    """结构化事件流路径:与 .live.log 同 stem 的 .events.jsonl(IST_EVIDENCE_LOG 覆盖时同规则派生)。"""
    p = _evidence_log_path()
    if p.endswith(".live.log"):
        return p[: -len(".live.log")] + ".events.jsonl"
    return p + ".events.jsonl"


def reset_evidence_log() -> None:
    """清空 evidence 日志(TUI 启动时调,每会话从干净开始)。失败静默。"""
    global _EV_LOG_FH, _EV_EVENTS_FH
    try:
        with _EV_LOG_LOCK:
            for _attr in ("_EV_LOG_FH", "_EV_EVENTS_FH"):
                _fh = globals().get(_attr)
                if _fh is not None:
                    try:
                        _fh.close()
                    except Exception:
                        pass
            _EV_LOG_FH = None
            _EV_EVENTS_FH = None
            path = Path(_evidence_log_path())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            Path(_fork_events_path()).write_text("", encoding="utf-8")
            # 清理同目录早已过时的旧 pid evidence 文件(>6h 未写=对应 infotest 进程多半已退)，避免按 pid 分文件后累积。
            import time as _t
            _cut = _t.time() - 6 * 3600
            for _pat in ("compile_evidence.*.live.log", "compile_evidence.*.events.jsonl"):
                for _old in path.parent.glob(_pat):
                    if _old not in (path, Path(_fork_events_path())) and _old.stat().st_mtime < _cut:
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


def _fork_emit_event(rec: dict) -> None:
    """结构化 fork/引擎/进度事件追加写 .events.jsonl(TUI 卡片数据源)。

    契约:每条 record **自含该卡完整可见状态**(n_calls 是累计值、engine_tick 带全量
    counts)——消费端纯覆盖,乱序/丢事件容忍。一行一 JSON;失败静默同 _fork_emit。
    """
    global _EV_EVENTS_FH
    try:
        import json as _json
        rec.setdefault("ts", time.time())
        line = _json.dumps(rec, ensure_ascii=False, default=str)
        with _EV_LOG_LOCK:
            if _EV_EVENTS_FH is None:
                path = Path(_fork_events_path())
                path.parent.mkdir(parents=True, exist_ok=True)
                _EV_EVENTS_FH = open(path, "a", encoding="utf-8")
            _EV_EVENTS_FH.write(line + "\n")
            _EV_EVENTS_FH.flush()
    except Exception:
        pass


# fork token 用量累计:compile 期主 agent 阻塞在 compile_pipeline、footer token 冻结,
# 实际烧的是 draft/grade fork 的 LLM 调用。这里累加,供 TUI footer 单独显示真实成本。
_FORK_TOKENS = [0, 0, 0]  # [input, output, cache_hit]
_FORK_TOKENS_LOCK = threading.Lock()


def get_fork_tokens() -> tuple[int, int, int]:
    """返回 (input, output, cache_hit) fork token 累计(供 TUI 显示+成本计算)。"""
    with _FORK_TOKENS_LOCK:
        return (_FORK_TOKENS[0], _FORK_TOKENS[1], _FORK_TOKENS[2])


def reset_fork_tokens() -> None:
    with _FORK_TOKENS_LOCK:
        _FORK_TOKENS[0] = 0
        _FORK_TOKENS[1] = 0
        _FORK_TOKENS[2] = 0




class _ForkUsageTally:
    """挂在 fork invoke config 上的轻量 usage 回调——fork 每次 LLM 调用即时计量。

    曾用「末态 messages 的 usage_metadata 累加」直计:fork 内摘要压缩把早期轮次
    AIMessage 撤出末态(整轮丢计)、transient 重试第一次烧的、看门狗杀掉的 fork
    全不进账——系统性偏小,与供应商官方(按每请求真实计量)对不上。显式挂载不依赖
    callback contextvar 传播(线程池/引擎路径断传播),每条 on_llm_end 都到。
    """
    raise_error = False
    ignore_llm = False
    ignore_chain = True
    ignore_agent = True
    ignore_retriever = True
    ignore_chat_model = False
    run_inline = True

    def __init__(self) -> None:
        # per-fork 实例计量(2026-07-06):全局 _FORK_TOKENS 是会话累计,fork_end 事件
        # 要报**本 fork** 的 tokens——双写:全局照旧进 footer,实例进卡片摘要。
        self.tokens = [0, 0, 0]   # [input, output, cache_hit]

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        from main.ist_core.graph import extract_llm_usage
        u = extract_llm_usage(response)
        if u:
            accumulate_fork_tokens_from_usage(u)
            try:
                self.tokens[0] += int(u.get("input_tokens") or 0)
                self.tokens[1] += int(u.get("output_tokens") or 0)
                self.tokens[2] += int(u.get("prompt_cache_hit_tokens") or 0)
            except Exception:  # noqa: BLE001
                pass

    def __getattr__(self, name):  # 其余回调一律 no-op(鸭型 BaseCallbackHandler)
        if name.startswith("on_"):
            return lambda *a, **k: None
        raise AttributeError(name)


def accumulate_fork_tokens_from_usage(usage: dict) -> None:
    """从 callback 的 usage dict 累加 fork token(由 graph.py handler 的 fork 分支调用)。

    这是 _FORK_TOKENS 的唯一写入口。曾有从 AIMessage.usage_metadata 累加的
    _accumulate_fork_tokens(loader 流式循环里调)与本函数并存——AIMessage 实际
    带 usage_metadata,两路同时活着即 fork 双计(2026-07-02 实证),已删旧路。
    """
    try:
        it = int(usage.get("input_tokens") or 0)
        ot = int(usage.get("output_tokens") or 0)
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        if it or ot:
            with _FORK_TOKENS_LOCK:
                _FORK_TOKENS[0] += it
                _FORK_TOKENS[1] += ot
                _FORK_TOKENS[2] += hit
    except Exception:  # noqa: BLE001
        pass


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
    # 信封剥离(2026-07-06):fork 挂 ToolEnvelopeMiddleware,ToolMessage.content 是
    # <tool_result name=… status=…> 包装——旧版首行抓取把开标签原文当"真内容"泄漏
    # 进预览(TUI 满屏 `<tool_result name="dev_probe" status="ok">`)。拆回 body 取
    # 实质内容;error 结果带 ✗ 前缀,失败原因可见。
    from main.ist_core.middleware.tool_envelope import parse_tool_result_envelope
    err_prefix = ""
    env = parse_tool_result_envelope(s)
    if env is not None:
        _, env_status, env_body = env
        s = env_body.strip()
        if env_status == "error":
            err_prefix = "✗ "
        if not s:
            return (err_prefix + "(空结果)") if err_prefix else ""
    if s[:1] in ("{", "["):          # JSON 工具返回(compile_score 等 pretty JSON)→ 关键字段单行预览
        return err_prefix + _json_one_line_preview(s, limit)
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
    return err_prefix + out[:limit] + ("…" if len(out) > limit else "")


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


def _emit_fork_step_events(fork_id: str, msg: Any, counter: list[int]) -> None:
    """结构化步骤事件——与 ``_fork_step_lines`` 人读行同源双写(卡片数据面)。

    tool 事件带该 fork 累计 n_calls(自含,消费端纯覆盖);tool_result 的 status 从
    信封属性取(fork 挂 ToolEnvelopeMiddleware),summary 复用 _short_fork_result。
    """
    tcs = getattr(msg, "tool_calls", None) or []
    for tc in tcs:
        if isinstance(tc, dict):
            name = tc.get("name") or "tool"
            targs = tc.get("args") or {}
        else:
            name = getattr(tc, "name", "") or "tool"
            targs = getattr(tc, "args", {}) or {}
        counter[0] += 1
        arg = _short_fork_args(targs, limit=60)
        _fork_emit_event({"event": "tool", "fork_id": fork_id, "tool": name,
                          "arg": arg[1:-1] if arg.startswith("(") else arg,
                          "n_calls": counter[0]})
    is_tool_result = (
        getattr(msg, "type", "") == "tool" or msg.__class__.__name__ == "ToolMessage"
    )
    if is_tool_result:
        content = getattr(msg, "content", "")
        s = content if isinstance(content, str) else str(content or "")
        status = "ok"
        try:
            from main.ist_core.middleware.tool_envelope import parse_tool_result_envelope
            env = parse_tool_result_envelope(s.strip())
            if env is not None:
                status = env[1]
            elif s.lstrip().lower().startswith(("error:", "错误")) or s.lstrip().startswith("ERROR:"):
                status = "error"
        except Exception:  # noqa: BLE001
            pass
        _fork_emit_event({"event": "tool_result", "fork_id": fork_id,
                          "tool": getattr(msg, "name", "") or "", "status": status,
                          "summary": _short_fork_result(content)[:140]})


def _invoke_fork_streamed(runnable: Any, rendered_body: str, label: str, *,
                          tally: Any = None, fork_id: str = "") -> dict:
    """跑 fork 并把内部每个工具调用实时发到主 bus(让 TUI 看到 draft/grade 运行过程)。

    用 ``stream(stream_mode='values')``——每个 superstep 吐全量 state,取最后一个作为
    与 ``invoke()`` 等价的最终返回值(同一 runnable 已 baked recursion_limit,行为不变)。
    ``IST_FORK_STEP_EMIT=0`` 可关实时步骤(只留编排层的轮次标记)。
    tally/fork_id 可选(默认行为不变):tally 由调用方传入以读 per-fork tokens;
    fork_id 非空时步骤同步双写结构化事件(.events.jsonl,TUI 卡片数据源)。"""
    from langchain_core.messages import HumanMessage
    inp = {"messages": [HumanMessage(content=rendered_body)]}
    cfg = {"callbacks": [tally if tally is not None else _ForkUsageTally()]}   # fork usage 唯一采集点
    cfg = {"callbacks": [_ForkUsageTally()]}   # fork usage 唯一采集点(每次 LLM 调用即时计)
    # [已注释] Langfuse LLM 可观测性
    # try:
    #     from main.ist_core.sinks.langfuse_sink import inject_langfuse_callbacks
    #     inject_langfuse_callbacks(cfg["callbacks"])
    # except Exception:
    #     pass
    stream = getattr(runnable, "stream", None)
    if not callable(stream) or not _fork_step_emit_enabled():
        # runnable 不支持流式 或 关了步骤显示(IST_FORK_STEP_EMIT=0)→ 退回阻塞 invoke,
        # 行为与旧版完全一致(只是看不到实时步骤)。
        return runnable.invoke(inp, cfg)
    final_state: dict = {}
    seen = 0
    n_calls = [0]
    for state in stream(inp, cfg, stream_mode="values"):
        if not isinstance(state, dict):
            continue
        final_state = state
        msgs = state.get("messages", []) or []
        for m in msgs[seen:]:
            for line in _fork_step_lines(label, m):
                _fork_emit(line)
            if fork_id:
                _emit_fork_step_events(fork_id, m, n_calls)
        seen = len(msgs)
    return final_state


def execute_fork_skill(skill_name: str, brief: str = "", *, tag: str = "",
                       summary_sink: dict | None = None, effort: str = "") -> str:
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
    skill_name = resolve_skill_dirname(skill_name)
    skill_file = skill_md_path(skill_name)
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

    runnable = get_subagent_runnable(agent_name, effort_override=effort)
    if runnable is None:
        return (
            f"ERROR: fork skill {skill_name!r} references unknown subagent "
            f"{agent_name!r}. Check main/ist_core/agents/{agent_name}.md."
        )

    rendered_body = _render_skill_body(parsed["body"], brief)

    _t0 = time.monotonic()
    _label = (tag or skill_name.replace("ist_compile_", "")).strip() or skill_name
    # 卡片数据面(2026-07-06):fork 生命周期结构化事件。fork_id 是本次执行唯一标识,
    # autoid 从 brief 提取(与 ist_app 批派可观察性同款正则),消费端按 fork_id 聚合。
    import re as _re
    import uuid as _uuid
    _fork_id = _uuid.uuid4().hex[:8]
    _m = _re.search(r"(?<!\d)20\d{16}(?!\d)", brief or "")
    _autoid = _m.group(0) if _m else ""
    # brief_head:卡片标题里的任务一瞥。机读 JSON 信封(引擎/fanout 路径)原文是噪声——
    # 抽语义字段(round/redispatch_reason);自由文本 brief 原样压缩截断。
    _bh = " ".join((brief or "").split())[:80]
    if (brief or "").lstrip().startswith("{"):
        try:
            import json as _json
            _env0 = _json.loads((brief or "").strip().splitlines()[0])
            if isinstance(_env0, dict):
                _parts = []
                if _env0.get("round"):
                    # 卡片=该 case 第几次编写(per-case,rounds_used+1)。与底部条的
                    # 「轮次N」(全局上机轮次)是两个计数,故用不同的词「第N次」避免同词歧义。
                    _parts.append(f"第{_env0['round']}次")
                if _env0.get("redispatch_reason"):
                    _parts.append(str(_env0["redispatch_reason"])[:40])
                _bh = " · ".join(_parts)
        except Exception:  # noqa: BLE001
            _bh = ""
    _tally = _ForkUsageTally()
    _eff_norm = (effort or "").strip().lower()
    _eff_norm = _eff_norm if _eff_norm in ("high", "max") else ""
    _fork_emit_event({"event": "fork_start", "fork_id": _fork_id, "skill": skill_name,
                      "agent": agent_name, "tag": tag, "autoid": _autoid,
                      "brief_head": _bh, "effort": _eff_norm})

    def _emit_fork_end(ok: bool, error: str, summary: dict) -> None:
        tc = summary.get("tool_calls")
        _fork_emit_event({"event": "fork_end", "fork_id": _fork_id, "ok": ok,
                          "error": (error or "")[:200],
                          "elapsed_s": round(time.monotonic() - _t0, 1),
                          "calls": sum(tc.values()) if isinstance(tc, dict) else 0,
                          "ai_rounds": int(summary.get("ai_rounds") or 0),
                          "tokens_in": _tally.tokens[0], "tokens_out": _tally.tokens[1],
                          "cache_hit": _tally.tokens[2]})

    try:
        result = _invoke_fork_streamed(runnable, rendered_body, _label,
                                       tally=_tally, fork_id=_fork_id)
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
        _emit_fork_end(False, _err, {})
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
        _ok = not output.startswith("ERROR:")
        _record_fork_status(skill_name, agent_name, _elapsed, _summary,
                            ok=_ok, output=output)
        _emit_fork_end(_ok, "" if _ok else output, _summary)
        return output

    _record_fork_status(skill_name, agent_name, _elapsed, _summary, ok=False,
                        error="fork returned no text output")
    _emit_fork_end(False, "fork returned no text output", _summary)
    return "ERROR: fork skill returned no text output."


def _render_skill_body(body: str, brief: str) -> str:
    """SKILL.md body 中的 $ARGUMENTS 占位符替换为 brief 内容。

    Fork skill 的 body 用 $ARGUMENTS 引用调用者传入的参数。
    如果 body 不含 $ARGUMENTS，则在末尾追加 brief（兼容性兜底）。
    """
    # 交互面 XML 分节(2026-07-05):brief 是「调用方数据」,SKILL 正文是「行为指令」
    # ——<brief_from_caller> 标签让 fork 一眼分清边界(worker md 的 <rules> 收尾
    # 紧邻此块,指令/数据相邻但不混排)。空 brief 不产空标签。
    tagged = f"<brief_from_caller>\n{brief}\n</brief_from_caller>" if brief else ""
    if "$ARGUMENTS" in body or "${ARGUMENTS}" in body:
        return body.replace("${ARGUMENTS}", tagged).replace("$ARGUMENTS", tagged)
    if brief:
        return body.rstrip() + "\n\n" + tagged
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
