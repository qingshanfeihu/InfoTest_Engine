"""批量编译 fan-out 工具：把"逐 case 串行"改成"按阶段批量并行/串行"。

设计依据（见计划 linear-imagining-galaxy.md 决策二）：并行的物理边界落在
**工具内部实现**，不靠 prompt 自律——

- ``compile_fanout``：worker/attributor fork 是纯 LLM + 只读检索/本地写，不碰设备可变态，
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
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    """项目根(workspace 的父)。独立成函数供测试替换沙箱根。"""
    return Path(__file__).resolve().parents[4]

# fan-out 并发上限。draft/grade 是 LLM 调用，并发度受端点限流约束而非 CPU；
# 默认 auto（按待编译数自适应），夹紧到 _MAX_FANOUT 防失控（端点 429 / 把自己打挂）。
_DEFAULT_FANOUT = 4
_MAX_FANOUT = 16

# 单个 fork 的兜底超时（秒）。draft 查手册+emit、grade 判分，给足但不无限挂。
_FORK_TIMEOUT_S = 900

# 429 退避：命中端点限流时指数退避重试，不直接判 fork 失败。
_RATE_LIMIT_MAX_RETRIES = 4
_RATE_LIMIT_BASE_SLEEP_S = 2.0

# 上机互斥(进程内)。起因(2026-07-04 实证):orchestrator 在同一 turn 内把
# dev_run_batch_digest 连发 2-3 次,设备床上多个 pytest 并发互踩配置,产出大片
# 真实但无意义的 fail(三轮结果报废)。框架的全局锁只锁 run 提交窗口,挡不住
# "前一个 client 被 Ctrl-C、设备侧 run 继续跑、新调用又 deliver"的堆积。
# 进程内非阻塞锁 + 设备侧残留探测(下)两层配合,把"同时只有一份在跑"做成不变量。
import threading as _threading
_RUN_MUTEX = _threading.Lock()


def _probe_stale_pytest(env=None) -> str | None:
    """经跳板机 SSH 探测设备床上残留的 ist_staging pytest 进程。

    返回残留描述文本(调用方应拒绝 deliver,附清理指引);无残留返回 None。
    探测本身失败(网络/权限)也返回 None——探测是护栏不是闸门,不能因探测挂掉
    把正常上机也堵死(deliver 后框架自身的锁仍是最后约束)。
    """
    try:
        from main.case_compiler.device_mcp_client import _connect
        c = _connect(env)
        try:
            _, out, _ = c.exec_command(
                "ps -eo pid,lstart,args | grep 'pytest' | grep 'ist_staging' | grep -v grep",
                timeout=15)
            txt = out.read().decode(errors="replace").strip()
        finally:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        if txt:
            return txt
    except Exception:  # noqa: BLE001
        logger.debug("残留 pytest 探测失败(不阻断)", exc_info=True)
    return None


def _kill_stale_pytest(env=None) -> None:
    """清理设备床上残留的 ist_staging pytest(force_clean=True 的执行动作)。"""
    try:
        from main.case_compiler.device_mcp_client import _connect
        c = _connect(env)
        try:
            c.exec_command("pkill -9 -f 'pytest.*ist_staging'", timeout=15)
            time.sleep(2)
        finally:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.warning("残留 pytest 清理失败", exc_info=True)


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


def _coerce_json_array(val, name: str):
    """数组参数双收:原生 list(首选,无字符串序列化拖尾暴露面)或 JSON 数组字符串(兼容)。

    返回 (list|None, err|None)。字符串通道经供应商 function-calling 序列化实测
    18-33% 解析失败(autoids_json/briefs_json,2026-07-03 全史 jsonl 取证),原生数组没有这层。
    """
    if isinstance(val, list):
        return val, None
    s = str(val or "").strip()
    if not s:
        return [], None
    try:
        arr = json.loads(s)
    except Exception as exc:  # noqa: BLE001
        return None, f"{name} 解析失败: {exc}(建议直接传原生数组而非 JSON 字符串)"
    if not isinstance(arr, list):
        return None, f"{name} 必须是数组"
    return arr, None


# fanout 单项 output 内联上限(字符)。fork 的机读尾块(STATUS:/ARTIFACT:/VERDICT:)在输出**末尾**,
# 截尾保留 → orchestrator 机读协议不受影响;全文落盘供深挖。
_FANOUT_INLINE_MAX = 2000


def _offload_large_outputs(items: list[dict], skill: str) -> None:
    """出参截断保护:超限的 fork output 全文落 workspace,内联只留末尾+文件指针。

    N 个 fork 的完整输出拼进返回值会随 N×|output| 无界增长——这是"批量出参无
    落盘/摘要"的载荷通道缺口(2026-07-04 评审):入参截断治好了,出参把 orchestrator
    上下文撑爆是同一个病的另一半。key 为 autoid 的落 outputs/<autoid>/(与凭证/冻结
    标记同目录),其余落 outputs/_fanout/。落盘失败时仍截尾(保护不因磁盘失败而失效)。
    """
    import re as _re
    root = _project_root()
    slug = _re.sub(r"[^A-Za-z0-9_.\-]", "_", (skill or "fork"))[:40] or "fork"
    for it in items:
        out = it.get("output")
        if not isinstance(out, str) or len(out) <= _FANOUT_INLINE_MAX:
            continue
        key = str(it.get("key", ""))
        safe = _re.sub(r"[^A-Za-z0-9_.\-]", "_", key)[:60] or "item"
        tail = out[-_FANOUT_INLINE_MAX:]
        try:
            if _re.fullmatch(r"\d{15,}", safe):
                f = root / "workspace" / "outputs" / safe / f"fanout_{slug}.md"
            else:
                f = root / "workspace" / "outputs" / "_fanout" / f"{safe}_{slug}.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(out, encoding="utf-8")
            rel = f.relative_to(root)
            it["output_path"] = str(rel)
            it["output"] = (f"[输出 {len(out)} 字符超内联上限,全文已落 {rel};"
                            f"以下为末尾 {_FANOUT_INLINE_MAX} 字符(机读尾块在此)]\n…" + tail)
        except Exception:  # noqa: BLE001
            logger.debug("fanout 输出落盘失败(仍截尾保护)", exc_info=True)
            it["output"] = (f"[输出 {len(out)} 字符超内联上限,且落盘失败;"
                            f"只保留末尾 {_FANOUT_INLINE_MAX} 字符]\n…" + tail)


def _xlsx_real_autoids(xlsx_file: str) -> list[str]:
    """扫 xlsx 数据区 A 列的全部真实 case autoid(排除哨兵)。

    与 compile_emit_merged 同款判定(纯数字且 ≥15 位);非数字 id 的特殊卷扫不出
    → 调用方按「全集为空跳过校验」处理,宁漏勿杀。
    """
    out: list[str] = []
    try:
        from openpyxl import load_workbook
        wb = load_workbook(xlsx_file, read_only=True, data_only=True)
        try:
            for row in wb.active.iter_rows(values_only=True):
                a = str((row[0] if row else "") or "").strip()
                if a.isdigit() and len(a) >= 15 and a != "999999999999999" and a not in out:
                    out.append(a)
        finally:
            wb.close()
    except Exception:  # noqa: BLE001
        logger.debug("xlsx autoid 扫描失败: %s", xlsx_file, exc_info=True)
    return out


@tool(parse_docstring=True)
def compile_fanout(skill: str, briefs_json: list | str = "", briefs_path: str = "",
                   concurrency: int = 0, evidence_from_xlsx: str = "") -> str:
    """并发派发**同一个 fork skill** 给多个 brief，收齐所有子 agent 的输出。

    用于批量编译里 worker / attributor 这类**可并行**阶段：每个 case 一个 brief，
    一次性并发跑完（受并发度上限约束，超出的排队），返回每个 brief 的产物。
    比逐个 invoke_skill 串行快 N 倍（N≈并发度），且各 fork 互相隔离、不串话。

    **只用于 worker / attributor**（纯 LLM + 检索/本地写，不碰设备可变态）。
    **上机（run）绝不用本工具**——上机受框架全局锁 + 设备共享态约束，必须串行，
    用 dev_run_batch。

    每个 brief 就是你本来要传给 invoke_skill 的那段 brief 文本（需求+现状+规则+
    指路+边界，不含具体命令答案——命令由子 agent 自己查）。

    briefs 载荷双通道(与 compile_emit 的 steps 同款设计):**大批次(>6 case)一律走
    briefs_path 文件通道**——briefs 总量随 case 数增长,内联大数组会被供应商序列化
    截断(2026-07-04 全量轮实证:18-case 内联截断 → 被迫逐个派发,并发全失)。

    Args:
        skill: 要并发派发的 fork skill 名（如 "compile-worker" / "compile-attributor"）。
        briefs_json: 小批次通道:原生数组(JSON 数组字符串兼容)。每项是含 key 与 brief 两键的
            dict——key 为标识(如 autoid,仅用于把输出对回到 case),brief 为完整 brief 文本。
        briefs_path: **大批次首选**。workspace 内 JSON 文件路径(如
            workspace/outputs/<批名>/briefs_wave1.json),内容为同 schema 的数组。先用
            fs_write / run_python 把 briefs 数组落盘再传路径——brief 正文不经任何
            内联参数,零截断暴露面。briefs_json 传了原生数组时以数组优先。
        concurrency: 并发度。**默认 0=auto**（按待编译数自适应：min(16, max(4, N))）；
            传正整数显式指定；env IST_FANOUT_CONCURRENCY 硬覆盖。夹紧到 16 防 429。
        evidence_from_xlsx: 可选。上机后的重编派发传那份 xlsx 路径——工具自动从同目录
            last_run.json 把每个 key(=autoid) 的 device_context/causality **原文**附进对应
            brief 尾部,消除手抄转述损耗（曾实证独行 ^ 被转述丢失致误归）。

    Returns:
        JSON 数组字符串。每项 {"key": ..., "ok": bool, "output": "<子agent输出或错误>"}，
        顺序与输入一致。某个 fork 失败不影响其它（该项 ok=false），你据此决定重做哪些。
        编写类派发（worker/draft,key=autoid）每项另带 "produced": bool——工具直接探
        outputs/<autoid>/case.xlsx 是否在盘上,「产没产出」以它为准,不用读散文猜。
        单项 output 超内联上限时全文自动落 workspace（该项多出 "output_path"），内联只保留
        **末尾**片段——fork 的机读尾块(STATUS:/ARTIFACT:/VERDICT:)在末尾,机读路径不受影响；
        深挖全文 fs_read 该 output_path。
    """
    # briefs 通道优先级(与 compile_emit steps 三通道同款):原生数组 > briefs_path
    # (workspace 文件) > 字符串。文件通道是大批次的主路——briefs 总量 O(N×|brief|),
    # 内联通道在传输层有硬上限,设计上不能假设它吃得下任意批次。
    items: list | None = None
    if isinstance(briefs_json, list) and briefs_json:
        items = briefs_json
    elif (briefs_path or "").strip():
        sp = (briefs_path or "").strip()
        root = _project_root()
        p = Path(sp) if sp.startswith("/") else (root / sp)
        try:
            p = p.resolve()
            ws = (root / "workspace").resolve()
            if not p.is_relative_to(ws):
                return json.dumps({"error": f"briefs_path 必须在 workspace/ 内: {sp}"},
                                  ensure_ascii=False)
            if not p.is_file():
                return json.dumps({"error": f"briefs_path 文件不存在: {sp}"
                                            "(先 fs_write 落文件再传路径)"}, ensure_ascii=False)
            items = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"briefs_path 读取/解析失败: {exc}"}, ensure_ascii=False)
        if not isinstance(items, list):
            return json.dumps({"error": "briefs_path 文件内容必须是 JSON 数组"
                                        "(每项 {key, brief})"}, ensure_ascii=False)
    else:
        items, err = _coerce_json_array(briefs_json, "briefs_json")
        if err:
            return json.dumps({"error": err + (
                " 大批次别内联:先把 briefs 数组写到 workspace 文件"
                "(如 workspace/outputs/<批名>/briefs_wave1.json)再传 briefs_path"
                "——文件通道没有截断暴露面。")}, ensure_ascii=False)

    if not items:
        # 空派发是调用错误,不静默成功——orchestrator 漏传参时返回 [] 会被当"派发完成",
        # 清单从此丢失(与"过程事实只存在于散文"同型:错误必须显式,不能靠人看出少了)。
        return json.dumps({"error": "briefs 为空:briefs_json 与 briefs_path 都没传有效内容。"
                                    "小批传原生数组,大批(>6)先落 workspace 文件再传 briefs_path。"},
                          ensure_ascii=False)

    norm: list[dict] = []
    for i, it in enumerate(items):
        if isinstance(it, dict):
            key = str(it.get("key", i))
            brief = str(it.get("brief", ""))
        else:
            key, brief = str(i), str(it)
        norm.append({"key": key, "brief": brief})

    # 上机证据自动注入:key=autoid 时从 last_run.json 取该 case 的原文附到 brief 尾,
    # 替代 LLM 手抄转述(转述会丢独行 ^ 等关键证据)。
    if (evidence_from_xlsx or "").strip():
        try:
            from pathlib import Path as _P
            # 沙箱读闸拒绝(路径越界/黑名单)= 直接放弃注入——注入本是 best-effort,
            # 绝不回退原始路径读盘(2026-07-05 安全评审:except 吞拒绝再裸读是读闸旁路)。
            from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
            _xp = _resolve_inside_root(evidence_from_xlsx, must_exist=True)
            _lr = _P(_xp).parent / "last_run.json"
            if _lr.is_file():
                _recs = {str(r.get("autoid")): r
                         for r in json.loads(_lr.read_text(encoding="utf-8"))
                         if isinstance(r, dict)}
                for it in norm:
                    r = _recs.get(it["key"])
                    if not r:
                        continue
                    ev = (r.get("device_context") or r.get("causality") or "").strip()
                    if ev:
                        block = ('<device_evidence source="last_run.json" '
                                 'note="工具注入原文,未经转述">\n'
                                 f"{ev[:6000]}\n</device_evidence>")
                        # 长数据置顶(官方长上下文实践):插在机读信封首行之后——信封保持
                        # 首行供卡片/解析读取,长证据紧随其后,指令留在消息末尾。
                        b = it["brief"]
                        first, sep, rest = b.partition("\n")
                        if first.lstrip().startswith("{"):
                            it["brief"] = first + "\n" + block + (("\n" + rest) if sep else "")
                        else:
                            it["brief"] = block + "\n" + b
        except Exception:  # noqa: BLE001
            logger.debug("fanout 证据注入失败(跳过)", exc_info=True)

    skipped: list[dict] = []

    from main.ist_core.skills.loader import execute_fork_skill

    workers = _resolve_concurrency(concurrency, n_items=len(norm))
    logger.info("compile_fanout skill=%s items=%d concurrency=%d skipped=%d",
                skill, len(norm), workers, len(skipped))

    def _run(item: dict) -> dict:
        # tag=per-item 归属标识(2026-07-06):旧版不传,N worker 的 fastlog 行全是同一个
        # skill 名 label、无法分辨哪行属于哪个 case;格式对齐引擎 `engine:{aid[-6:]}`——
        # `{skill短名}:{autoid尾6}`(非 autoid key 取前 12)。
        _k = str(item.get("key") or "").strip()
        _short = (skill or "fork").replace("ist-compile-", "").replace("compile-", "")
        _tag = f"{_short}:{_k[-6:]}" if len(_k) == 18 and _k.isdigit() else f"{_short}:{_k[:12]}"
        last_exc = None
        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                out = execute_fork_skill(skill, item["brief"], tag=_tag)
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
    ordered += skipped
    # 「产没产出」以落盘为准,工具直接探(编写类派发 key=autoid):worker 说产出了但盘上
    # 没有、或返回是调试残句但盘上有——散文与事实曾张冠李戴,produced 字段是机读事实源。
    if "worker" in (skill or "").lower() or "draft" in (skill or "").lower():
        _root = _project_root()
        for r in ordered:
            aid = str(r.get("key", "")).strip()
            if len(aid) == 18 and aid.isdigit():
                r["produced"] = (_root / "workspace" / "outputs" / aid / "case.xlsx").is_file()
    _offload_large_outputs(ordered, skill)
    return json.dumps(ordered, ensure_ascii=False)


# 上机超时。整份 xlsx **一次**提交即跑完其中全部 case(框架把整份当套件整跑),故超时是**整份级**、
# 随 case 数自适应(单 case 含 sleep/多 dig 约 ~45s),夹紧到总上限,防大文件跑不完被误判超时。
_RUN_DEFAULT_MAX_S = 600
_RUN_MAX_MAX_S = 1200          # 兼容旧签名(单 case 语义)的夹紧上限
_PER_CASE_BUDGET_S = 45        # 整份估时:每 case 预算秒
_RUN_TOTAL_CAP_S = 2400        # 整份总超时硬上限(40min)


@tool(parse_docstring=True)
def dev_run_batch(xlsx_path: str, autoids_json: list | str = "", module: str = "",
                 build: str = "", max_s_each: int = _RUN_DEFAULT_MAX_S,
                 force_clean: bool = False) -> str:
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
    的 case 首跑必 fail（框架找字面 "<RUNTIME>"），属预期待回填，由 ist-verify 回填后复跑。

    Args:
        xlsx_path: 合并后的 case.xlsx 本地路径（含多个真 case + 尾部哨兵）。
        autoids_json: **首选原生数组**(JSON 数组字符串兼容;省略=xlsx 全卷)。要取裁决的
            autoid 列表——工具会对照 xlsx 实际 autoid 全集校验,不在卷内的显式报错
            (防手抄截断 id 被日志文件名子串静默误匹配成 pass)。
        module: staging 子模块（默认取 compiler config staging_module）。
        build: 目标设备 build（默认取 compiler config build）。
        max_s_each: 兼容旧签名——传入则按"整份预算下限"对待；整份总超时 = clamp(max(它, N×45s), …, 2400s)。
        force_clean: 设备床上有残留 pytest 时,默认拒绝上机并报出残留进程(多份 pytest
            并发互踩配置会产出大片无意义 fail);确认残留是弃跑后传 True 先清场再跑。

    Returns:
        JSON 数组字符串，每项 {"autoid", "verdict", "task_id", "causality"(check_point
        真实裁决行), "detail_tail", 非pass附 "device_context"}，按输入顺序。
    """
    import re as _re
    from pathlib import Path

    arr, err = _coerce_json_array(autoids_json, "autoids_json")
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)
    autoids = [str(a).strip() for a in (arr or []) if str(a).strip()]

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

    # autoid 与 xlsx 实际卷内全集对账(A 层校验):空=全卷;不在卷内的显式报错——
    # 曾实证 LLM 手抄把 203031753342778012 截成 "778012",旧版靠日志文件名子串
    # 静默误匹配成 pass,错 id 一路进最终报告且跨轮对照失效。
    real = _xlsx_real_autoids(str(p))
    if not autoids:
        if not real:
            return json.dumps({"error": "未传 autoids 且 xlsx 数据区扫不出 autoid;请显式传原生数组"},
                              ensure_ascii=False)
        autoids = real
    elif real:
        unknown = [a for a in autoids if a not in real]
        if unknown:
            return json.dumps({"error": (
                f"以下 autoid 不在该 xlsx 数据区(手抄错/截断?): {', '.join(unknown)}。"
                f"卷内实际 {len(real)} 个: {', '.join(real[:6])}{'…' if len(real) > 6 else ''};"
                "省略 autoids 参数即按全卷取裁决。")}, ensure_ascii=False)

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

    # 进程内互斥:同一进程里已有一份上机在跑 → 立即拒绝,绝不排队叠加。
    # (2026-07-04 实证:orchestrator 同 turn 连发 2-3 次 digest,设备床多 pytest 互踩,
    # 三轮结果报废。上机是独占设备床的物理动作,重复调用没有任何正确语义。)
    if not _RUN_MUTEX.acquire(blocking=False):
        return json.dumps({"error": "run_in_progress", "busy": True, "message": (
            "本进程已有一份上机在执行中——上机独占设备床,同一时刻只能有一份。"
            "不要重复调用 dev_run_batch/digest,等当前这份返回结果即可。")},
            ensure_ascii=False)

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
            _stack.callback(_RUN_MUTEX.release)
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
            # 设备侧残留探测:上一次跑批被打断时,client 死了但设备上的 pytest 还活着——
            # 此时 deliver 新卷会两份并发互踩配置,产出大片真实但无意义的 fail,且新
            # digest 可能收割到旧执行的日志(2026-07-04 三轮实证)。有残留默认拒绝;
            # 确认残留是弃跑后用 force_clean=True 清场重跑。
            stale = _probe_stale_pytest(env)
            if stale and force_clean:
                _kill_stale_pytest(env)
                stale = _probe_stale_pytest(env)
            if stale:
                return json.dumps({"error": "stale_run_on_device", "busy": True, "message": (
                    "设备床上有残留的 pytest 进程在跑(上次跑批被打断后进程未死):\n"
                    + stale[:500]
                    + "\n此时上机会两份并发互踩配置、结果全部失真。等它自然跑完,"
                      "或确认它是弃跑后带 force_clean=True 重调本工具清场重跑。")},
                    ensure_ascii=False)
            client = _stack.enter_context(FrameworkMCPClient(env))
            dres = client.deliver(module, submit, str(p))
            if dres.get("error"):
                return json.dumps({"error": f"deliver 失败: {dres.get('error')}"}, ensure_ascii=False)
            # run-identity 基线:deliver 时刻的跳板机 epoch。staging 目录跨 run 复用,
            # 上次被打断执行的旧日志会留存;收割时 mtime 早于此基线的日志判 stale,
            # 不产 verdict(2026-07-04 实证:收割旧执行日志 → 0/34、1/34 两轮假结果)。
            # getattr 兼容:旧 client 实现/测试替身没有该方法时基线=0(过滤不启用,行为同旧)。
            deliver_epoch = getattr(client, "jumphost_epoch", lambda: 0.0)()

            # 跑批进度 → evidence fastlog（TUI 300ms tail 同一文件即实时显示，零 TUI 改动）。
            # 降噪：完成数变化或 ≥30s 心跳才写一行；任何异常静默——可观测性不拖垮跑批。
            # 双写(2026-07-06):人读 ▸ 行照旧(tail -f 契约);结构化 progress 事件带稳定
            # key=runbatch:{submit}——TUI 卡片模式同 key 恒一行原地更新,不再 48 条心跳平铺。
            _t0 = time.time()
            _prog_key = f"runbatch:{submit}"
            _prog_state = {"sig": "", "ts": 0.0}
            def _on_poll(st: dict) -> None:
                try:
                    import re
                    from main.ist_core.skills.loader import _fork_emit, _fork_emit_event
                    now = time.time()
                    # 整卷单跑模式下 len(results) 开跑即满(框架一次性建全 per-case 条目),
                    # 旧版拿它当分子显示「34/34」恒满假进度(2026-07-03 实证)。改为诚实
                    # 口径:已跑时长/总预算 + 框架日志尾(真实推进信号在日志里)。
                    _log = st.get("log_tail") or ""
                    tail_lines = _log.strip().splitlines()
                    tail_txt = tail_lines[-1].strip()[-70:] if tail_lines else ""
                    # 当前在跑第几个 case:框架按 autoids 顺序单跑,日志尾最近提到的 18 位
                    # autoid 即当前 case → 在 autoids 里的序号是诚实进度(比时长更直观)。
                    _cur_idx = 0
                    for _id in reversed(re.findall(r"(?<!\d)(\d{18})(?!\d)", _log)):
                        if _id in autoids:
                            _cur_idx = autoids.index(_id) + 1
                            break
                    _env_host = getattr(client, "host", "") or ""
                    sig = f"{tail_txt}|{_cur_idx}"
                    if sig == _prog_state["sig"] and now - _prog_state["ts"] < 30:
                        return
                    _prog_state["sig"], _prog_state["ts"] = sig, now
                    _prog_seg = (f"第{_cur_idx}/{len(autoids)}" if _cur_idx
                                 else f"整卷 {len(autoids)} case 单跑")
                    tail = f" · {tail_txt}" if tail_txt else ""
                    _fork_emit(f"▸ 上机运行 {int(now - _t0)}s/{total_max}s"
                               f"(环境 {_env_host} · {_prog_seg}){tail}")
                    _fork_emit_event({"event": "progress", "key": _prog_key,
                                      "phase": "上机", "elapsed_s": int(now - _t0),
                                      "total_s": int(total_max), "n_cases": len(autoids),
                                      "env": _env_host, "case_idx": _cur_idx,
                                      "detail": tail_txt, "status": "running"})
                except Exception:  # noqa: BLE001
                    pass

            run = client.run_and_wait(module, submit, build, autoids, max_s=total_max,
                                      progress_cb=_on_poll)
            try:
                from main.ist_core.skills.loader import _fork_emit_event as _fee
                _run_err = run.get("error") or ("device_busy" if run.get("busy") else "")
                _fee({"event": "progress", "key": _prog_key, "phase": "上机",
                      "elapsed_s": int(time.time() - _t0), "total_s": int(total_max),
                      "n_cases": len(autoids),
                      "detail": str(_run_err)[:70] if _run_err else "完成",
                      "status": "error" if _run_err else "done"})
            except Exception:  # noqa: BLE001
                pass
            if run.get("busy") or run.get("error") == "device_busy":
                return json.dumps({"error": "device_busy", "busy": True,
                                   "message": run.get("message") or "环境忙：正在验证上一个用例，请稍后重试。"},
                                  ensure_ascii=False)
            task_id = run.get("task_id", "")
            run_err = run.get("error")
            # 无论 run 是否 done（可能撞总超时仍 running），都尽量读回已写出的逐 case 日志。
            # min_epoch=基线-3s(容 stat 秒级粒度):早于本次 deliver 的日志是上次执行残留,
            # 值为 STALE_LOG_MARK → 判 unknown 并显式标注,绝不当本次结果采信。
            # TypeError 回退:旧 client/测试替身签名不收 min_epoch 时按旧行为全收。
            try:
                details = client.fetch_batch_details(
                    submit, min_epoch=(deliver_epoch - 3) if deliver_epoch else 0)
            except TypeError:
                details = client.fetch_batch_details(submit)
            stale_mark = getattr(client, "STALE_LOG_MARK", "<<STALE_LOG>>")
            for autoid in autoids:
                d = details.get(autoid, "")
                if d == stale_mark:
                    out.append({"autoid": autoid, "verdict": "unknown", "task_id": run.get("task_id", ""),
                                "causality": "", "detail_tail": (
                                    "stale_log: 该 case 的 staging 日志早于本次 deliver——是上一次"
                                    "执行的残留,本次没有跑到它(整卷可能中途崩溃/超时)。别按此日志归因。")})
                    continue
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


def _xlsx_apv_lines(xlsx_path) -> dict[str, list[str]]:
    """从(合并)卷机械抽取每个 autoid 的 APV 命令列表(E∈{APV_0,APV_1} 行的 G 列,
    cmds_config 多行逐条拆)。verified_runs 台账的 apv_cmds 字段来源——device_verified
    权威源用它交叉校验"写回的命令真实出现在 PASS 卷面上"。"""
    import openpyxl
    out: dict[str, list[str]] = {}
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            begun = False
            cur = ""
            for row in ws.iter_rows(min_row=2, values_only=True):
                a = str(row[0] or "").strip() if row else ""
                if not begun:
                    begun = a == "自动化ID"
                    continue
                # autoid 行=18 位纯数字(勿按前缀认:曾硬编 "203" 前缀,204 批全体 autoid
                # 不被识别→apv_cmds 恒空→device_verified 写回/行为晋升对 204 批静默失效,
                # 2026-07-08 实测台账 105/105 条空 vs 203 批 26/26 全有)
                if len(a) == 18 and a.isdigit():
                    cur = a
                    out.setdefault(cur, [])
                if not cur or len(row) < 7:
                    continue
                e = str(row[4] or "").strip()
                if e in ("APV_0", "APV_1"):
                    for line in str(row[6] or "").splitlines():
                        line = line.strip()
                        if line:
                            out[cur].append(line)
    finally:
        wb.close()
    return out


def _append_verified_runs(xlsx_path, results: list, cur_round: int, run_ts: float,
                          build: str = "") -> None:
    """运行台账(V6 支柱2a):逐 case 追加 runtime/logs/verified_runs.jsonl。

    build 字段=本次 run 提交用的目标 build(K 锚三元组 (build, run_ts, lineage) 的
    build 位,理论 §5.1)——写回链经 device_run_ref 透传进 footprint 条目的
    evidence.device_run,后续 build 锚差派生 stale 判定靠它;空串=当次未解析出。"""
    apv = _xlsx_apv_lines(xlsx_path)
    ledger = _project_root() / "runtime" / "logs" / "verified_runs.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    xstat = Path(str(xlsx_path)).stat()
    with ledger.open("a", encoding="utf-8") as f:
        for rec in results:
            if not isinstance(rec, dict) or not rec.get("autoid"):
                continue
            aid = str(rec["autoid"])
            f.write(json.dumps({
                "autoid": aid, "verdict": str(rec.get("verdict", "")),
                "run_ts": run_ts, "round": cur_round,
                "xlsx": str(xlsx_path), "xlsx_mtime": xstat.st_mtime,
                "build": (build or "").strip(),
                "apv_cmds": apv.get(aid, []),
            }, ensure_ascii=False) + "\n")


@tool(parse_docstring=True)
def dev_run_batch_digest(xlsx_path: str, autoids_json: list | str = "", module: str = "",
                         build: str = "", max_s_each: int = _RUN_DEFAULT_MAX_S,
                         force_clean: bool = False) -> str:
    """整份 xlsx 上机单跑 + 逐 case 四层归因，回**精简可读**摘要（不被 offload）。

    与 ``dev_run_batch`` 同参、同上机方式（整份单跑 O(N)），但**替你把大结果就地消化**——
    这是把 ist-verify 的确定性核（首跑 → 拆逐 case → 四层归因）提炼成一次调用：

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

    **何时不用**：只想跑**单个** case 看它过不过 → ``dev_run_case``（轻量、免合并）；
    要原样拿完整大 JSON 自己解析 → ``dev_run_batch``（但结果会被 offload，见上）。

    返回摘要形态（据此决定下一步，别再要求全量明细内联）::

        === dev_run_batch_digest ===
        <run_summary>
        excel: <路径> | 总 case: N
        真通过 P:n | fail F:m (G(^拒绝):g 待归因:u) | unknown:k
        全量明细: <last_run.json 路径>
        </run_summary>
        <cross_run_alerts>…跨轮同签名/瞬态复现警报(有则)…</cross_run_alerts>
        …裁决表/指引各自成节…

    Args:
        xlsx_path: 合并后的 case.xlsx 本地路径。
        autoids_json: **首选原生数组**(JSON 数组字符串兼容;省略=xlsx 全卷,推荐)。
            工具对照 xlsx 实际 autoid 全集校验,不在卷内的显式报错。
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
    raw = dev_run_batch.func(xlsx_path, autoids_json, module, build, max_s_each, force_clean)
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
                # 语法层可判定性接线(理论 §3.2,044572 实证):^ 是设备语法反射的入口——
                # 在 ^ 位置追问 ?,"设备此处实际接受什么"是 O(1) 读表事实,落盘给归因/重编。
                # 三分支判定(用例语法错/文档错/特性缺失)由 attributor 拿这份事实做,不再猜。
                if cmds:
                    try:
                        from main.ist_core.tools.device.run_case import dev_help
                        rec["_device_help"] = str(dev_help.func(cmds[0]))[:2000]
                        from main.ist_core.memory.footprint.signals import emit_signal
                        emit_signal("syntax_help_attached", aid,
                                    source="dev_run_batch_digest", rejected_cmd=cmds[0])
                    except Exception:  # noqa: BLE001 — 追问失败不阻断 digest
                        pass
                note = ("⚠配置被拒(^): " + " ; ".join(c[:60] for c in cmds)) if cmds else tail
                rows.append((aid, "fail", "G(^)", "→G", note))
            else:
                # fail 行表尾展示失败签名(fail to find 前缀),不是 causality 末 90 字——
                # 后者常落在最后一条**成功**裁决行上,失败断言反而不可见(2026-07-03 取证)。
                sigs = sorted(_fail_signatures((rec.get("causality") or "") + (detail or "")))
                note = ("✗ " + " | ".join(s[:55] for s in sigs[:2])) if sigs else tail
                rows.append((aid, "fail", "-", "待归因", note))

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
                # 瞬态复现检查双源:旧 _digest_layer(机械预判,收缩后不再产 transient)
                # + _attribution.layer(LLM 归因经 submit_attribution 落盘)——后者是
                # 该护栏的活水源,没有它这分支是 dead code(2026-07-03 取证)。
                prev_layers = {p.get("_digest_layer"),
                               (p.get("_attribution") or {}).get("layer")}
                if "transient" in prev_layers:
                    transient_recur_ids.append(str(rec.get("autoid")))
                sig_now = _fail_signatures((rec.get("causality") or "") + (rec.get("device_context") or ""))
                sig_prev = _fail_signatures((p.get("causality") or "") + (p.get("device_context") or ""))
                if sig_now & sig_prev:
                    rec["_repeat_fail_same_signature"] = True
                    repeat_ids.append(str(rec.get("autoid")))
                    # 冻结标记落 per-case 目录(A 层):同签名连续两轮 fail=同法已证无效。
                    # compile_emit 对带此标记的 case 要求 override_frozen_reason(说明换了
                    # 什么法)才放行——文本指引曾被实证绕过(721e:未核环境直接 ad-hoc 重编),
                    # 升为工具闸门;LLM 换法的自由保留,只是"是否换法"必须显式声明。
                    try:
                        import time as _t0
                        _root = Path(__file__).resolve().parents[4]
                        _cd = _root / "workspace" / "outputs" / str(rec.get("autoid"))
                        _cd.mkdir(parents=True, exist_ok=True)
                        _fz_file = _cd / ".frozen.json"
                        # 重写保留 overrides 历史(emit 门记的换法声明)——曾整文件覆盖,
                        # 换法轨迹跨轮丢失,「换过几次法/各是什么」无据可查。
                        _prev_ov = []
                        if _fz_file.is_file():
                            try:
                                _prev_ov = (json.loads(_fz_file.read_text(encoding="utf-8"))
                                            .get("overrides") or [])
                            except Exception:  # noqa: BLE001
                                pass
                        _fz_file.write_text(json.dumps({
                            "reason": "连续两轮同签名 fail(同法已证无效)",
                            "signatures": sorted(sig_now & sig_prev)[:4],
                            "ts": _t0.time(),
                            **({"overrides": _prev_ov} if _prev_ov else {}),
                        }, ensure_ascii=False, indent=2), encoding="utf-8")
                        try:
                            from main.ist_core.memory.footprint.signals import emit_signal
                            emit_signal("frozen", str(rec.get("autoid")),
                                        source="dev_run_batch_digest",
                                        signature=str(rec.get("_fail_sig") or "")[:120])
                        except Exception:  # noqa: BLE001
                            pass
                    except Exception:  # noqa: BLE001
                        logger.debug("frozen 标记落盘失败", exc_info=True)
        # 按 autoid merge 写盘(不整文件覆盖):分批跑同一卷时第二批曾覆盖丢第一批
        # 17 条记录+10 个 repeat 标记(2026-07-03 取证 dongkl_final8)。本轮没跑到的
        # autoid 保留上一轮记录;每记录带 _round/_run_ts,fail 记录带 _fail_signatures。
        import time as _time
        prev_round = 0
        for r0 in prev_map.values():
            try:
                prev_round = max(prev_round, int(r0.get("_round") or 0))
            except (TypeError, ValueError):
                pass
        cur_round = prev_round + 1
        now_ts = _time.time()
        merged_map = dict(prev_map)
        for rec in results:
            if not isinstance(rec, dict) or not rec.get("autoid"):
                continue
            rec["_round"] = cur_round
            rec["_run_ts"] = now_ts
            if rec.get("verdict") == "fail":
                rec["_fail_signatures"] = sorted(_fail_signatures(
                    (rec.get("causality") or "") + (rec.get("device_context") or "")))
                # 归因历史跨轮保留(2026-07-06 588691 收口):新记录整条替换曾把上一轮
                # _attribution(含 fix_direction)丢掉——归因 fork 看不到「上轮开过什么
                # 方子」,无从核对修法生效性,方向错的修法(^ 锚)被按同因重复归因。
                _pv = prev_map.get(str(rec["autoid"])) or {}
                _pa = _pv.get("_attribution")
                if isinstance(_pa, dict) and _pa:
                    rec["_prev_attribution"] = {**_pa, "_round": _pv.get("_round")}
            merged_map[str(rec["autoid"])] = rec
        # 原子写(2026-07-05 竞态类加固):last_run.json 是跨轮对照/归因/写回的事实源,
        # 与意图索引同病类——非原子 write_text 被杀进程/并发进程截断成拼接损坏后,
        # 整链(冻结判定/翻案证据/写回门)全部失灵。tmp+os.replace 根治。
        _tmp = out_file.with_suffix(".json.tmp")
        _tmp.write_text(json.dumps(list(merged_map.values()), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(_tmp, out_file)
        # 运行台账(V6 支柱2a):每 case 一条 {autoid, verdict, run_ts, apv_cmds…} 追加
        # runtime/logs/verified_runs.jsonl——footprint 写回的 device_verified 第二权威源。
        # runtime/ 在 agent 文件沙箱黑名单,工具进程写、agent 伪造不了;追加失败不阻断 run。
        try:
            # build 锚:digest 入参可能为空,按 dev_run_batch 同款 cfg 兜底解析生效值
            try:
                from main.case_compiler.config import get_config as _gc
                _eff_build = (build or _gc().build or "").strip()
            except Exception:  # noqa: BLE001
                _eff_build = (build or "").strip()
            _append_verified_runs(xlsx_path, results, cur_round, now_ts, build=_eff_build)
        except Exception:  # noqa: BLE001
            logger.debug("verified_runs 台账追加失败(忽略)", exc_info=True)
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
                f"   → 正确处置: **重编移除/替换这些 case 的 {name} 断言**(走 ist-compile 重编)；"
                f"不是改框架、不是逐 case 排查、excel **确实要动**。"
            )

    # 交互面 XML 分节(2026-07-05):摘要/跨轮警报/崩溃分析/裁决表/指引各自成节——
    # 数据与指引不混排(归因抄证据曾从混排文本里抄出转义失真)。行内文本零改动,
    # 只加节标签;本返回仅 LLM 消费,机读事实源仍是 last_run.json。
    lines = ["=== dev_run_batch_digest ===", "<run_summary>"]
    lines.append(f"excel: {xlsx_path} | 总 case: {len(results)}")
    lines.append(
        f"真通过 P:{cnt.get('pass', 0)} | fail F:{cnt.get('fail', 0)} "
        f"(G(^拒绝):{layers['G']} 待归因:{layers['undetermined']}) "
        f"| unknown:{cnt.get('unknown', 0)}"
    )
    lines.append(f"全量明细: {detail_disp}")
    lines.append("</run_summary>")
    if repeat_ids or transient_recur_ids:
        lines.append("<cross_run_alerts>")
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
        lines.append("</cross_run_alerts>")
    if crash_note:
        lines.append("<crash_analysis>")
        lines.append(crash_note)
        lines.append("</crash_analysis>")
    lines.append("<verdict_rows>")
    lines.append("autoid | verdict | 归因层 | reflow | causality/note(尾)")
    for r in rows:
        lines.append(" | ".join(str(x) for x in r))
    lines.append("</verdict_rows>")
    lines.append("<guidance>")
    lines.append(f"深挖某 case: fs_read {detail_disp} 或 fs_grep <autoid> 该文件看完整 device_context。")
    lines.append("归因说明: G(^)=设备语法拒绝(协议级确定事实,先修它——同 case 后续解析/断言失败多为下游后果); "
                 "待归因=未做机械预判,读 last_run.json 里该 case 的 device_context 原文自行判 "
                 "E(可达性/环境)/V(断言期望值)/瞬态(换时间重跑即消失;连续两轮同签名 fail 不是瞬态)/疑似产品缺陷。")
    lines.append("归因第一步: 先对照 knowledge/data/auto_env/env_capabilities.json 的 known_defects——"
                 "命中已知缺陷(DC-*)的 fail 是环境/产品边界,标注即可,别当编译问题重编。")
    # 子集复测节流:迭代期整卷重跑,pass 的 case 每轮白跑一遍(dongkl 闭环实测:修 5-8 个
    # fail 反复整卷 34 跑了 7 轮,≈200 次多余 case 执行,每轮多等 5-9 分钟)。fail 占少数时,
    # 修复轮只跑 fail 子集卷;last_run.json 是按 autoid merge 的,子集结果回填不覆盖 pass
    # 记录。终版交付前仍需整卷跑一次确认(合并后整体行为以整卷为准)。
    fail_ids = [str(r2.get("autoid")) for r2 in results
                if isinstance(r2, dict) and r2.get("verdict") == "fail"
                and len(str(r2.get("autoid", ""))) == 18]
    if 0 < len(fail_ids) <= max(3, len(results) // 2):
        lines.append("")
        lines.append(
            f"节流提示: 本轮仅 {len(fail_ids)}/{len(results)} 个 fail——修复后**只跑 fail 子集**"
            f"(整卷重跑会让 {len(results) - len(fail_ids)} 个已 pass 的 case 白跑一遍):\n"
            f"   compile_emit_merged(autoids={json.dumps(fail_ids, ensure_ascii=False)}, "
            f"out_name=\"<批名>_fails\") → 对子集卷 dev_run_batch_digest。\n"
            f"   子集轮结果落子集卷目录(单卷冻结档 .frozen.json 按 autoid 落、跨轮对照仍有效);"
            f"子集全过后**整卷跑一次**做交付确认(交付以整卷结果为准)。")
    lines.append("</guidance>")
    return "\n".join(lines)
