"""批量编译 fan-out 工具：把"逐 case 串行"改成"按阶段批量并行/串行"。

设计依据（见计划 linear-imagining-galaxy.md 决策二）：并行的物理边界落在
**工具内部实现**，不靠 prompt 自律——

- ``qa_compile_fanout``：draft / grade 是纯 LLM + 只读检索/本地写，不碰设备可变态，
  用 ThreadPoolExecutor **并发** fan-out 多个 fork。并发安全已由 P0-S1 验证
  （execute_fork_skill 全局部变量 + LangGraph graph 无状态 + ChatOpenAI/httpx
  并发安全），同一缓存 runnable 可安全被多线程并发 invoke。
- ``qa_run_batch``：上机受跳转机框架全局锁约束（device_mcp_client run_and_wait
  拿不到 task_id 即 "submit failed (lock held?)"），且设备配置/统计是全局共享态，
  **必须单线程串行**。它内部就是一个 for 循环，物理上不可能并发上机。

零硬编码红线：本模块只做"调度 + 结果汇总"，不含任何 APV/sdns 命令、不解析领域
语义、不按关键字分支。命令全程由 draft 子 agent 现场查手册/先例产出。
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import time

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# fan-out 并发上限。draft/grade 是 LLM 调用，并发度受端点限流约束而非 CPU；
# 默认 auto（按待编译数自适应），夹紧到 _MAX_FANOUT 防失控（端点 429 / 把自己打挂）。
_DEFAULT_FANOUT = 4
_MAX_FANOUT = 16

# 单个 fork 的兜底超时（秒）。draft 查手册+emit、grade 判分，给足但不无限挂。
_FORK_TIMEOUT_S = 900

# 429 退避：命中端点限流时指数退避重试，不直接判 fork 失败。
_RATE_LIMIT_MAX_RETRIES = 4
_RATE_LIMIT_BASE_SLEEP_S = 2.0


def _resolve_concurrency(requested: int, n_items: int = 0) -> int:
    """决定 fan-out 并发度。优先级：env 硬覆盖 > 调用方显式值 > auto(按 item 数自适应)。

    auto（requested<=0）：min(_MAX_FANOUT, max(_DEFAULT_FANOUT, n_items))——
    待编译数少时不空开线程，多时自动铺到上限。墙钟从 Σfork/4 降到 Σfork/min(16,n)。
    """
    env = os.environ.get("IST_FANOUT_CONCURRENCY")
    if env:
        try:
            base = int(env)
        except (TypeError, ValueError):
            base = requested
    elif requested and requested > 0:
        base = requested
    else:
        # auto：按待编译数自适应
        base = max(_DEFAULT_FANOUT, n_items) if n_items > 0 else _DEFAULT_FANOUT
    if base <= 0:
        base = _DEFAULT_FANOUT
    return max(1, min(base, _MAX_FANOUT))


def _is_rate_limit_error(exc: Exception) -> bool:
    """判断异常是否端点限流（429 / rate limit）。靠消息匹配，跨 SDK 兜底。"""
    s = str(exc).lower()
    return "429" in s or "rate limit" in s or "too many requests" in s or "overloaded" in s


@tool(parse_docstring=True)
def qa_compile_fanout(skill: str, briefs_json: str, concurrency: int = 0) -> str:
    """并发派发**同一个 fork skill** 给多个 brief，收齐所有子 agent 的输出。

    用于批量编译里 draft / grade 这类**可并行**阶段：每个 case 一个 brief，
    一次性并发跑完（受并发度上限约束，超出的排队），返回每个 brief 的产物。
    比逐个 qa_invoke_skill 串行快 N 倍（N≈并发度），且各 fork 互相隔离、不串话。

    **只用于 draft / grade**（纯 LLM + 检索/本地写，不碰设备可变态）。
    **上机（run）绝不用本工具**——上机受框架全局锁 + 设备共享态约束，必须串行，
    用 qa_run_batch。

    每个 brief 就是你本来要传给 qa_invoke_skill 的那段 brief 文本（需求+现状+规则+
    指路+边界，不含具体命令答案——命令由子 agent 自己查）。

    Args:
        skill: 要并发派发的 fork skill 名（如 "ist_compile_draft" / "ist_compile_grade"）。
        briefs_json: JSON 数组字符串。每项是 {"key": "<标识,如autoid>", "brief": "<完整brief文本>"}。
            key 仅用于把输出对回到 case，不影响执行。
        concurrency: 并发度。**默认 0=auto**（按待编译数自适应：min(16, max(4, N))）；
            传正整数显式指定；env IST_FANOUT_CONCURRENCY 硬覆盖。夹紧到 16 防 429。

    Returns:
        JSON 数组字符串。每项 {"key": ..., "ok": bool, "output": "<子agent输出或错误>"}，
        顺序与输入一致。某个 fork 失败不影响其它（该项 ok=false），你据此决定重做哪些。
    """
    try:
        items = json.loads(briefs_json)
        if not isinstance(items, list):
            raise ValueError("briefs_json 必须是 JSON 数组")
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"briefs_json 解析失败: {exc}"}, ensure_ascii=False)

    if not items:
        return json.dumps([], ensure_ascii=False)

    norm: list[dict] = []
    for i, it in enumerate(items):
        if isinstance(it, dict):
            key = str(it.get("key", i))
            brief = str(it.get("brief", ""))
        else:
            key, brief = str(i), str(it)
        norm.append({"key": key, "brief": brief})

    from main.ist_core.skills.loader import execute_fork_skill

    workers = _resolve_concurrency(concurrency, n_items=len(norm))
    logger.info("qa_compile_fanout skill=%s items=%d concurrency=%d", skill, len(norm), workers)

    def _run(item: dict) -> dict:
        last_exc = None
        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                out = execute_fork_skill(skill, item["brief"])
                ok = not (isinstance(out, str) and out.startswith("ERROR:"))
                return {"key": item["key"], "ok": ok, "output": out}
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _is_rate_limit_error(exc):
                    logger.exception("fanout fork %s key=%s failed", skill, item["key"])
                    return {"key": item["key"], "ok": False, "output": f"ERROR: {exc}"}
                if attempt < _RATE_LIMIT_MAX_RETRIES:
                    sleep_s = _RATE_LIMIT_BASE_SLEEP_S * (2 ** attempt)
                    logger.warning("fanout fork %s key=%s 命中限流(429)，第%d次退避 %.0fs",
                                   skill, item["key"], attempt + 1, sleep_s)
                    time.sleep(sleep_s)
        return {"key": item["key"], "ok": False,
                "output": f"ERROR: 限流重试耗尽({_RATE_LIMIT_MAX_RETRIES}次): {last_exc}"}

    results: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run, it): it["key"] for it in norm}
        for fut in cf.as_completed(futs, timeout=_FORK_TIMEOUT_S * len(norm)):
            key = futs[fut]
            try:
                r = fut.result(timeout=_FORK_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001
                r = {"key": key, "ok": False, "output": f"ERROR: fork 超时/异常: {exc}"}
            results[key] = r

    # 保持输入顺序
    ordered = [results.get(it["key"], {"key": it["key"], "ok": False,
                                       "output": "ERROR: 无结果"}) for it in norm]
    return json.dumps(ordered, ensure_ascii=False)


# 上机串行超时上限（单 case），与 qa_run_case 对齐。
_RUN_DEFAULT_MAX_S = 600
_RUN_MAX_MAX_S = 1200


@tool(parse_docstring=True)
def qa_run_batch(xlsx_path: str, autoids_json: str, module: str = "",
                 build: str = "", max_s_each: int = _RUN_DEFAULT_MAX_S) -> str:
    """把**一个合并 xlsx 里的多个 case** 顺序上机，逐个回 verdict + 框架真实裁决。

    **串行执行**（这是硬约束，不是选择）：跳转机框架有全局运行锁，同一时刻只允许
    一个上机任务；且设备配置/统计是全局共享态，并发上机会互相污染。本工具内部就是
    一个 for 循环，复用一条 SSH 会话顺序 deliver+run+取明细——物理上不会并发上机。

    与 qa_run_case 的区别：qa_run_case 跑单个 autoid；本工具跑同一个 xlsx 里的一批
    autoid（批量编译合并产物的上机验证），少开 N-1 次 SSH 会话，省连接开销。

    verdict 语义同 qa_run_case：来自框架 MySQL 每个 check_point 结果，pass 条件 =
    fail num 全 0 且 success>0。pytest "1 passed" 不代表断言通过。

    Args:
        xlsx_path: 合并后的 case.xlsx 本地路径（含多个真 case + 尾部哨兵）。
        autoids_json: JSON 数组字符串，要上机的 autoid 列表（顺序即上机顺序）。
        module: staging 子模块（默认取 compiler config staging_module）。
        build: 目标设备 build（默认取 compiler config build）。
        max_s_each: 单个 case 上机轮询超时秒（默认 600，夹紧 1200）。

    Returns:
        JSON 数组字符串，每项 {"autoid", "verdict", "task_id", "causality"(check_point
        真实裁决行), "detail_tail"}。串行，按输入顺序。某 case error 不中断后续。
    """
    import re as _re
    from pathlib import Path

    try:
        autoids = json.loads(autoids_json)
        if not isinstance(autoids, list) or not autoids:
            raise ValueError("autoids_json 必须是非空 JSON 数组")
        autoids = [str(a).strip() for a in autoids if str(a).strip()]
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"autoids_json 解析失败: {exc}"}, ensure_ascii=False)

    # 复用 qa_run_case 的多根路径解析（agent 沙箱视角）
    p = None
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        p = _resolve_inside_root(xlsx_path, must_exist=True)
    except Exception:
        p = None
    if p is None or not Path(p).is_file():
        cands = [Path(xlsx_path)]
        if not Path(xlsx_path).is_absolute():
            root = Path(__file__).resolve().parents[4]
            cands += [root / xlsx_path, root / "knowledge" / "data" / xlsx_path]
        p = next((c for c in cands if c.is_file()), None)
    if p is None or not Path(p).is_file():
        return json.dumps({"error": f"xlsx 不存在: {xlsx_path}"}, ensure_ascii=False)
    p = Path(p)

    try:
        from main.case_compiler.config import get_config
        cfg = get_config()
        module = (module or cfg.staging_module).strip()
        build = (build or cfg.build).strip()
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"读取 compiler config 失败: {exc}"}, ensure_ascii=False)

    try:
        max_s_each = max(30, min(int(max_s_each or _RUN_DEFAULT_MAX_S), _RUN_MAX_MAX_S))
    except (TypeError, ValueError):
        max_s_each = _RUN_DEFAULT_MAX_S

    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"加载 FrameworkMCPClient 失败: {exc}"}, ensure_ascii=False)

    out: list[dict] = []
    try:
        with FrameworkMCPClient() as client:
            for autoid in autoids:  # ← 串行：一条 SSH 会话顺序跑，绝不并发
                rec = {"autoid": autoid, "verdict": "error", "task_id": "",
                       "causality": "", "detail_tail": ""}
                try:
                    dres = client.deliver(module, autoid, str(p))
                    if dres.get("error"):
                        rec["detail_tail"] = f"deliver 失败: {dres.get('error')}"
                        out.append(rec)
                        continue
                    run = client.run_and_wait(module, autoid, build, [autoid], max_s=max_s_each)
                    if run.get("busy") or run.get("error") == "device_busy":
                        # 设备正在验证上一个用例——把 busy 信号显式标出，agent 可据此决定
                        # 等待/重试/上报，而非误判为编译错误。串行循环内正常不会撞，多为
                        # 外部并发上机抢锁。
                        rec["verdict"] = "busy"
                        rec["detail_tail"] = run.get("message") or "环境忙：正在验证上一个用例"
                        out.append(rec)
                        continue
                    if run.get("error"):
                        rec["detail_tail"] = f"提交/运行失败: {run.get('error')}"
                        out.append(rec)
                        continue
                    rec["verdict"] = ((run.get("results") or {}).get(autoid)
                                      or run.get("result") or "unknown")
                    rec["task_id"] = run.get("task_id", "")
                    detail = client.fetch_case_detail(autoid)
                    causality = [ln.rstrip() for ln in (detail or "").splitlines()
                                 if _re.search(r"(Success|Fail)\s*Num|fail to find|successed to find",
                                               ln, _re.IGNORECASE)]
                    rec["causality"] = "\n".join(causality[-12:]) if causality else ""
                    rec["detail_tail"] = (detail or "")[-2500:]
                    # 非 pass：附完整设备上下文(配置会话每条命令的设备响应 + dig 真实输出),
                    # 供 agent 据此改配置 / 填 <RUNTIME>。pass 的不附(省体积)。
                    if rec["verdict"] != "pass":
                        rec["device_context"] = client.fetch_device_context(autoid)
                except Exception as exc:  # noqa: BLE001
                    rec["detail_tail"] = f"上机异常: {exc}"
                out.append(rec)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"批量上机异常: {exc}", "partial": out}, ensure_ascii=False)

    return json.dumps(out, ensure_ascii=False)
