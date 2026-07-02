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
    except Exception:  # noqa: BLE001
        logger.debug("xlsx 路径解析失败(将回退兜底): %s", xlsx_path, exc_info=True)
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
    import contextlib as _ctx
    try:
        from main.case_compiler import env_pool as _pool
    except Exception:  # noqa: BLE001
        logger.debug("加载 env_pool 失败，回退单环境模式", exc_info=True)
        _pool = None
    try:
        with _ctx.ExitStack() as _stack:
            # 环境池：启用时认领一个空闲就绪环境（各自独立设备床→真并行）；
            # 未启用/池异常→ env=None 回退现役单环境（行为同今天）；全忙→device_busy。
            env = None
            if _pool is not None and _pool.is_enabled():
                try:
                    env = _stack.enter_context(_pool.acquire(timeout=300))
                except TimeoutError:
                    return json.dumps({"error": "device_busy", "busy": True,
                                       "message": "所有自动化环境都忙，请稍后重试。"},
                                      ensure_ascii=False)
                except Exception:  # noqa: BLE001
                    logger.warning("环境池 acquire 异常，回退单环境", exc_info=True)
                    env = None
            client = _stack.enter_context(FrameworkMCPClient(env))
            dres = client.deliver(module, submit, str(p))
            if dres.get("error"):
                return json.dumps({"error": f"deliver 失败: {dres.get('error')}"}, ensure_ascii=False)

            # 跑批进度 → evidence fastlog（TUI 300ms tail 同一文件即实时显示，零 TUI 改动）。
            # 降噪：完成数变化或 ≥30s 心跳才写一行；任何异常静默——可观测性不拖垮跑批。
            _t0 = time.time()
            _prog_state = {"done": -1, "ts": 0.0}
            def _on_poll(st: dict) -> None:
                try:
                    from main.ist_core.skills.loader import _fork_emit
                    done = len(st.get("results") or {})
                    now = time.time()
                    if done == _prog_state["done"] and now - _prog_state["ts"] < 30:
                        return
                    _prog_state["done"], _prog_state["ts"] = done, now
                    tail_lines = (st.get("log_tail") or "").strip().splitlines()
                    tail = f" · {tail_lines[-1].strip()[-70:]}" if tail_lines else ""
                    _fork_emit(f"▸ 上机进度 {done}/{len(autoids)} · {int(now - _t0)}s{tail}")
                except Exception:  # noqa: BLE001
                    pass

            run = client.run_and_wait(module, submit, build, autoids, max_s=total_max,
                                      progress_cb=_on_poll)
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
            # 文件级崩溃可见性：有 unknown（某 case 把整份 pytest 搞崩、后续全不跑）→ 取框架 task 日志
            # 的 traceback 附到 unknown 上，让 agent 看到“崩在哪一行/什么异常”，而非只看到一堆无解释的 unknown。
            if task_id and any(r["verdict"] == "unknown" for r in out):
                tb = client.fetch_task_log_errors(task_id)
                if tb:
                    for r in out:
                        if r["verdict"] == "unknown":
                            r["framework_traceback"] = tb
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"批量上机异常: {exc}", "partial": out}, ensure_ascii=False)

    return json.dumps(out, ensure_ascii=False)


def _scan_xlsx_for_check_method(xlsx_path: str, method: str) -> list:
    """扫 xlsx 找用了某 check_point 方法（如 found_times）的行，返回 [(autoid, 行号)]。

    供 digest 在识别到文件级崩溃（某断言崩整份 pytest）时**点名元凶 case**，让归因落到
    具体 autoid，而非笼统"框架崩了"。失败静默返回空（点名是增益、非硬依赖）。
    """
    try:
        import openpyxl
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        p = _resolve_inside_root(xlsx_path, must_exist=True)
        ws = openpyxl.load_workbook(p, data_only=True).active
        hits, cur = [], None
        for i, row in enumerate(ws.iter_rows(values_only=True), 1):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if cells and cells[0].isdigit() and len(cells[0]) >= 12:
                cur = cells[0]
            if method in cells and "check_point" in cells:
                hits.append((cur, i))
        return hits
    except Exception:  # noqa: BLE001
        return []


def _fail_signatures(text: str) -> set[str]:
    """从裁决明细抽 fail 签名集合（``fail to find[:]? <expect>`` 的 expect 前 60 字符）。

    跨轮对照用：两轮签名集合**交集非空** = 同签名 fail（同一断言以同样方式不中）。
    保守短截断——签名只用于同/异判定，不追求完整还原 expect。
    """
    import re
    return {m.group(1).strip()[:60]
            for m in re.finditer(r"fail to find:?\s*([^\r\n]{1,80})", text or "")}


@tool(parse_docstring=True)
def dev_run_batch_digest(xlsx_path: str, autoids_json: str, module: str = "",
                         build: str = "", max_s_each: int = _RUN_DEFAULT_MAX_S) -> str:
    """整份 xlsx 上机单跑 + 逐 case 四层归因，回**精简可读**摘要（不被 offload）。

    与 ``dev_run_batch`` 同参、同上机方式（整份单跑 O(N)），但**替你把大结果就地消化**——
    这是把 ist_verify 的确定性核（首跑 → 拆逐 case → 四层归因）提炼成一次调用：

    - 全量逐 case 明细（causality / device_context / framework_traceback）落
      ``workspace/outputs/<feature>/last_run.json``（**缩进 JSON**：``fs_read`` 可分页、
      ``fs_grep <autoid>`` 可定位、``run_python`` 可 ``json.load``）；
    - 每个非 pass case 过确定性四层归因（与 ``compile_attribute`` 同款分类器，瞬态>E>G>默认V）；
    - **只返回** summary 计数 + 逐 case 一行表 + 明细文件指针（几 KB → 不触发 offload）。

    为什么要它：``dev_run_batch`` 原样返回的大 JSON 会被 middleware offload 成单块，agent
    读得回、却难就地逐 case 解析（且 ``run_python``/``run_shell`` 够不到 offload 落点）。本工具在
    **进程内**消化完，agent 拿到的是已分类的小摘要；要深挖某个 case 的完整 device_context，
    再对 ``last_run.json`` ``fs_read`` / ``fs_grep <autoid>`` 即可（它在 workspace 内、全工具可用）。

    含 ``<RUNTIME>`` 占位的 case 首跑必 fail（框架找字面 "<RUNTIME>"），属预期待回填——
    先看 digest 里它归到哪层，回填仍走 ``compile_runtime_slots`` / ``compile_runtime_fill``。

    Args:
        xlsx_path: 合并后的 case.xlsx 本地路径。
        autoids_json: JSON 数组字符串，要取裁决的 autoid 列表。
        module: staging 子模块（默认取 compiler config）。
        build: 目标设备 build（默认取 compiler config）。
        max_s_each: 整份预算下限（同 ``dev_run_batch``）。

    Returns:
        人类可读摘要：summary 计数 + 逐 case 表（autoid | verdict | 归因层 | reflow | causality 尾）
        + 全量明细文件路径。上机错误 / device_busy 原样透传。
    """
    from pathlib import Path
    from main.ist_core.tools.device.fail_attribution import attribute_fail

    # 进程内跑 dev_run_batch：拿到的完整 JSON 不经 offload（offload 只在 tool→agent 时发生）
    raw = dev_run_batch.func(xlsx_path, autoids_json, module, build, max_s_each)
    try:
        results = json.loads(raw)
    except Exception:  # noqa: BLE001
        return raw
    if not isinstance(results, list):
        return raw   # error / device_busy / partial dict 原样透传

    cnt = {"pass": 0, "fail": 0, "unknown": 0}
    layers = {"G": 0, "undetermined": 0}
    rows: list[tuple] = []
    for rec in results:
        aid = rec.get("autoid", "?")
        verdict = rec.get("verdict", "unknown")
        cnt[verdict] = cnt.get(verdict, 0) + 1
        causal = (rec.get("causality") or "").strip().replace("\n", " ")
        tail = causal[-90:] if causal else ""
        if verdict == "pass":
            rows.append((aid, "pass", "-", "-", tail))
        elif verdict == "unknown":
            tb = (rec.get("framework_traceback") or "").strip()
            note = "崩溃/未跑到"
            if tb:
                note += f"; tb尾: {tb.splitlines()[-1][:70]}"
            rows.append((aid, "unknown", "?", "-", note))
        else:  # fail → 机械预判只认设备 ^ 拒绝；其余给原文不猜（见 fail_attribution）
            detail = rec.get("device_context") or rec.get("detail_tail") or causal
            ar = attribute_fail(detail)
            layers[ar.layer] = layers.get(ar.layer, 0) + 1
            rec["_digest_layer"] = ar.layer   # 落盘供下一轮跨轮对照
            if ar.layer == "G":
                from main.ist_core.tools.device.fail_attribution import caret_rejected_commands
                cmds = caret_rejected_commands(detail, limit=2)
                note = ("⚠配置被拒(^): " + " ; ".join(c[:60] for c in cmds)) if cmds else tail
                rows.append((aid, "fail", "G(^)", "→G", note))
            else:
                rows.append((aid, "fail", "-", "待归因", tail))

    # 全量明细落 workspace（缩进 JSON，全工具可用）——feature 目录 = xlsx 的父目录
    detail_disp = ""
    repeat_ids: list[str] = []          # 连续两轮同签名 fail（非瞬态实锤）
    transient_recur_ids: list[str] = []  # 上轮归瞬态、本轮复现 fail（误归瞬态）
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root, _WORKSPACE_ROOT
        xp = _resolve_inside_root(xlsx_path, must_exist=True)
        out_file = Path(xp).parent / "last_run.json"
        # 跨轮对照（机械事实）：覆盖写之前读上一轮结果。瞬态定义=不可复现——
        # 同签名连续两轮 fail 即系统性问题（实证 dongkl：5 个"瞬态"下一轮 100% 复现=全部误归）。
        prev_map: dict[str, dict] = {}
        try:
            if out_file.exists():
                for r0 in json.loads(out_file.read_text(encoding="utf-8")):
                    if isinstance(r0, dict) and r0.get("autoid"):
                        prev_map[str(r0["autoid"])] = r0
        except Exception:  # noqa: BLE001
            prev_map = {}
        if prev_map:
            for rec in results:
                if not isinstance(rec, dict) or rec.get("verdict") != "fail":
                    continue
                p = prev_map.get(str(rec.get("autoid")))
                if not p or p.get("verdict") != "fail":
                    continue
                if p.get("_digest_layer") == "transient":
                    transient_recur_ids.append(str(rec.get("autoid")))
                sig_now = _fail_signatures((rec.get("causality") or "") + (rec.get("device_context") or ""))
                sig_prev = _fail_signatures((p.get("causality") or "") + (p.get("device_context") or ""))
                if sig_now & sig_prev:
                    rec["_repeat_fail_same_signature"] = True
                    repeat_ids.append(str(rec.get("autoid")))
        out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            detail_disp = str(out_file.relative_to(_WORKSPACE_ROOT.parent))
        except Exception:  # noqa: BLE001
            detail_disp = str(out_file)
    except Exception as exc:  # noqa: BLE001
        detail_disp = f"(明细落盘失败: {exc})"

    # 文件级崩溃识别：unknown 常是"某 case 断言崩了整份 pytest → 崩溃点后全 unknown（级联）"。
    # 认已知崩溃签名（如 found_times），扫 xlsx 点名元凶 case，给**正确归因**——编译缺陷、
    # 非框架 bug、非各 case 各自失败、非"逐 case 排查"。这是 bare main 最易归因错的地方。
    crash_note = ""
    tb_joined = "\n".join(
        rec.get("framework_traceback", "") for rec in results
        if rec.get("verdict") == "unknown" and rec.get("framework_traceback")
    )
    if tb_joined:
        from main.ist_core.tools.device.fail_attribution import attribute_file_crash
        hit = attribute_file_crash(tb_joined)
        if hit:
            name, guide = hit
            culprits = _scan_xlsx_for_check_method(xlsx_path, name)
            who = ("元凶 case: " + ", ".join(f"{a}(行{r})" for a, r in culprits[:8])
                   ) if culprits else "（未在 xlsx 定位到，可能在合并前的单 case draft）"
            crash_note = (
                f"⚠ 文件级崩溃(编译缺陷,非框架bug): {name} 断言崩了整份 pytest → 崩溃点之后 "
                f"{cnt.get('unknown', 0)} 个 unknown 是**级联**(后续 case 根本没跑)、非各自失败。\n"
                f"   崩因: {guide}\n   {who}\n"
                f"   → 正确处置: **重编移除/替换这些 case 的 {name} 断言**(走 ist_compile 重编)；"
                f"不是改框架、不是逐 case 排查、excel **确实要动**。"
            )

    lines = ["=== dev_run_batch_digest ==="]
    lines.append(f"excel: {xlsx_path} | 总 case: {len(results)}")
    lines.append(
        f"真通过 P:{cnt.get('pass', 0)} | fail F:{cnt.get('fail', 0)} "
        f"(G(^拒绝):{layers['G']} 待归因:{layers['undetermined']}) "
        f"| unknown:{cnt.get('unknown', 0)}"
    )
    lines.append(f"全量明细: {detail_disp}")
    if repeat_ids or transient_recur_ids:
        lines.append("")
        if repeat_ids:
            lines.append(
                f"⚠ 跨轮对照:连续两轮**同签名** fail({len(repeat_ids)}个): {', '.join(repeat_ids)}\n"
                f"   → 非瞬态、且上轮修法无效。**冻结同法重编**(第三轮同法大概率再 fail)；按环境阻塞"
                f"/疑似产品缺陷处置:先核实环境事实(该 IP/配置在设备上的真实状态),环境正常则走"
                f" kb_bug_search 比对缺陷库、产出缺陷候选记录,而非继续重编。"
            )
        if transient_recur_ids:
            lines.append(
                f"⚠ 上轮归\"瞬态\"本轮复现 fail({len(transient_recur_ids)}个): {', '.join(transient_recur_ids)}\n"
                f"   → 瞬态=不可复现;复现即误归,按系统性问题重新归因(G/E/V/产品缺陷)。"
            )
    if crash_note:
        lines.append("")
        lines.append(crash_note)
    lines.append("")
    lines.append("autoid | verdict | 归因层 | reflow | causality/note(尾)")
    for r in rows:
        lines.append(" | ".join(str(x) for x in r))
    lines.append("")
    lines.append(f"深挖某 case: fs_read {detail_disp} 或 fs_grep <autoid> 该文件看完整 device_context。")
    lines.append("归因说明: G(^)=设备语法拒绝(协议级确定事实,先修它——同 case 后续解析/断言失败多为下游后果); "
                 "待归因=未做机械预判,读 last_run.json 里该 case 的 device_context 原文自行判 "
                 "E(可达性/环境)/V(断言期望值)/瞬态(换时间重跑即消失;连续两轮同签名 fail 不是瞬态)/疑似产品缺陷。")
    return "\n".join(lines)
