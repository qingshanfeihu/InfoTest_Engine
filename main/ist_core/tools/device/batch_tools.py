"""批量编译 fan-out 工具：把"逐 case 串行"改成"按阶段批量并行/串行"。

设计依据（见计划 linear-imagining-galaxy.md 决策二）：并行的物理边界落在
**工具内部实现**，不靠 prompt 自律——

- ``compile_fanout``：draft / grade 是纯 LLM + 只读检索/本地写，不碰设备可变态，
  用 ThreadPoolExecutor **并发** fan-out 多个 fork。并发安全已由 P0-S1 验证
  （execute_fork_skill 全局部变量 + LangGraph graph 无状态 + ChatOpenAI/httpx
  并发安全），同一缓存 runnable 可安全被多线程并发 invoke。
- ``dev_run_batch``：上机受跳转机框架全局锁约束（device_mcp_client run_and_wait
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
def compile_fanout(skill: str, briefs_json: str, concurrency: int = 0) -> str:
    """并发派发**同一个 fork skill** 给多个 brief，收齐所有子 agent 的输出。

    用于批量编译里 draft / grade 这类**可并行**阶段：每个 case 一个 brief，
    一次性并发跑完（受并发度上限约束，超出的排队），返回每个 brief 的产物。
    比逐个 invoke_skill 串行快 N 倍（N≈并发度），且各 fork 互相隔离、不串话。

    **只用于 draft / grade**（纯 LLM + 检索/本地写，不碰设备可变态）。
    **上机（run）绝不用本工具**——上机受框架全局锁 + 设备共享态约束，必须串行，
    用 dev_run_batch。

    每个 brief 就是你本来要传给 invoke_skill 的那段 brief 文本（需求+现状+规则+
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
    logger.info("compile_fanout skill=%s items=%d concurrency=%d", skill, len(norm), workers)

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


# 上机超时。整份 xlsx **一次**提交即跑完其中全部 case(框架把整份当套件整跑),故超时是**整份级**、
# 随 case 数自适应(单 case 含 sleep/多 dig 约 ~45s),夹紧到总上限,防大文件跑不完被误判超时。
_RUN_DEFAULT_MAX_S = 600
_RUN_MAX_MAX_S = 1200          # 兼容旧签名(单 case 语义)的夹紧上限
_PER_CASE_BUDGET_S = 45        # 整份估时:每 case 预算秒
_RUN_TOTAL_CAP_S = 2400        # 整份总超时硬上限(40min)


@tool(parse_docstring=True)
def dev_run_batch(xlsx_path: str, autoids_json: str, module: str = "",
                 build: str = "", max_s_each: int = _RUN_DEFAULT_MAX_S) -> str:
    """把**一个合并 xlsx 整份上机一次**，回每个 case 的 verdict + 框架真实裁决。

    **整份单跑（O(N) 关键修复）**：框架 ``test_xlsx.py`` 把交付的整份 xlsx 当一个**套件整跑**
    ——提交**一个** autoid 就会顺序执行文件里**所有** case，全部内层 case 的逐 check_point 日志
    都落在该提交 autoid 的 staging 下。故本工具**只 deliver+run 一次**，再从该 staging 一把读回
    所有 autoid 的裁决；绝不按 autoid 逐个重复整跑（旧实现 O(N²)、且大文件撞 600s 轮询上限拿不到
    结果——"跑 20 分钟无结果"的根因）。

    **串行硬约束仍在**：跳转机框架有全局运行锁、设备态全局共享，同一时刻只允许一个上机任务；
    本工具一次只提交一份 xlsx，物理上不并发。

    verdict 取每个 case 专属日志的逐 check_point 结果：``#### Fail Num`` 全无且 ``#### Success
    Num`` >0 → pass；有 Fail → fail；无日志 → unknown（未执行到/被跳过）。含 ``<RUNTIME>`` 占位
    的 case 首跑必 fail（框架找字面 "<RUNTIME>"），属预期待回填，由 ist_verify 回填后复跑。

    Args:
        xlsx_path: 合并后的 case.xlsx 本地路径（含多个真 case + 尾部哨兵）。
        autoids_json: JSON 数组字符串，xlsx 里要取裁决的 autoid 列表。
        module: staging 子模块（默认取 compiler config staging_module）。
        build: 目标设备 build（默认取 compiler config build）。
        max_s_each: 兼容旧签名——传入则按"整份预算下限"对待；整份总超时 = clamp(max(它, N×45s), …, 2400s)。

    Returns:
        JSON 数组字符串，每项 {"autoid", "verdict", "task_id", "causality"(check_point
        真实裁决行), "detail_tail", 非pass附 "device_context"}，按输入顺序。
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

    # 复用 dev_run_case 的多根路径解析（agent 沙箱视角）
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

    # 整份总超时随 case 数自适应（单 case 含 sleep/多 dig ~45s），夹紧到硬上限。
    try:
        floor = int(max_s_each or _RUN_DEFAULT_MAX_S)
    except (TypeError, ValueError):
        floor = _RUN_DEFAULT_MAX_S
    total_max = max(floor, len(autoids) * _PER_CASE_BUDGET_S)
    total_max = max(_RUN_DEFAULT_MAX_S, min(total_max, _RUN_TOTAL_CAP_S))

    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"加载 FrameworkMCPClient 失败: {exc}"}, ensure_ascii=False)

    submit = autoids[0]   # 整份只用一个 autoid 提交，框架据它建 staging 并整跑全文件
    out: list[dict] = []
    try:
        with FrameworkMCPClient() as client:
            dres = client.deliver(module, submit, str(p))
            if dres.get("error"):
                return json.dumps({"error": f"deliver 失败: {dres.get('error')}"}, ensure_ascii=False)
            run = client.run_and_wait(module, submit, build, autoids, max_s=total_max)
            if run.get("busy") or run.get("error") == "device_busy":
                return json.dumps({"error": "device_busy", "busy": True,
                                   "message": run.get("message") or "环境忙：正在验证上一个用例，请稍后重试。"},
                                  ensure_ascii=False)
            task_id = run.get("task_id", "")
            run_err = run.get("error")
            # 无论 run 是否 done（可能撞总超时仍 running），都尽量读回已写出的逐 case 日志。
            details = client.fetch_batch_details(submit)
            for autoid in autoids:
                d = details.get(autoid, "")
                succ = len(_re.findall(r"#### Success\s*Num", d))
                fail = len(_re.findall(r"#### Fail\s*Num", d))
                if fail > 0:
                    verdict = "fail"
                elif succ > 0:
                    verdict = "pass"
                else:
                    verdict = "unknown"   # 无日志：未执行到/被跳过(如 test_env 主机不支持)/超时未跑到
                causality = [ln.rstrip() for ln in d.splitlines()
                             if _re.search(r"(Success|Fail)\s*Num|fail to find|successed to find",
                                           ln, _re.IGNORECASE)]
                rec = {"autoid": autoid, "verdict": verdict, "task_id": task_id,
                       "causality": "\n".join(causality[-12:]) if causality else "",
                       "detail_tail": d[-2500:]}
                if verdict != "pass":
                    rec["device_context"] = client.fetch_device_context_under(submit, autoid)
                    if run_err and not d:
                        rec["detail_tail"] = (f"(无 case 日志；run state={run_err})\n" + rec["detail_tail"])
                out.append(rec)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"批量上机异常: {exc}", "partial": out}, ensure_ascii=False)

    return json.dumps(out, ensure_ascii=False)
