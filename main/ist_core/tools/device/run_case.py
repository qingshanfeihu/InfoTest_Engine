"""dev_run_case tool: 把一个 case.xlsx 下发到跳转机 pytest 框架并上机运行,回 pass/fail + 日志。

这是 agent 调查循环的"上机验证"一手——agent 合成/改写一个 case 后,用本工具真机跑一次,
拿 pass/fail(设备说了算,非 agent 自评)+ 失败日志尾,据此诊断、改方案、重跑。

与 dev_ssh 的区别:
- dev_ssh = 直连 APV 设备发**单条 CLI**,看一条命令的回显(细粒度探查)。
- dev_run_case = 把**整个 case.xlsx** 交框架跑完整流程(deliver→run→MySQL 取 result),
  拿这个 case 的整体裁决。agent 通常先 dev_ssh 探命令语法,再 dev_run_case 验整 case。

凭据:跳转机 SSH 口令从 env IST_JUMPHOST_PASS / JUMPHOST_PASS 取(device_mcp_client 内部),
不落盘不回显。复用 case_compiler.device_mcp_client.FrameworkMCPClient(单一事实源,不重造)。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 上机超时上限(秒)。框架单 case 一般 35s~10min;给 agent 可调但夹紧防失控。
_DEFAULT_MAX_S = 600
_MAX_MAX_S = 1200


@tool(parse_docstring=True)
def dev_run_case(
    xlsx_path: str,
    autoid: str,
    module: str = "",
    build: str = "",
    max_s: int = _DEFAULT_MAX_S,
) -> str:
    """Deliver one case.xlsx to the jumphost pytest framework, run it on-device, return pass/fail + log tail.

    This is the **execution oracle**: pass/fail is decided by the device + framework, not by
    agent self-review. Use it in the investigation loop — after producing/rewriting a case,
    run it for real, diagnose from the fail log (logic error / environment / product defect /
    case-description error / manual error), adjust, and rerun until pass or a confirmed defect.

    **When to use**: you have a produced/fixed case.xlsx and need its real on-device verdict.
    **When not to use**: you only want one CLI command's echo or syntax check → dev_ssh
    (faster, single command).
    **Prerequisite**: assertion expected values need provenance first (author intent /
    declared resources / framework precedents) — never invented; for uncertain CLI syntax,
    grep ``knowledge/data/markdown/product/cli_*_Chapter*.md`` + ``cli_*_Appendix*.md`` or probe
    with dev_ssh first.

    Framework flow (handled inside this tool; you only read the result):
    1. deliver: land the xlsx in the jumphost staging dir (framework converts xlsx→python).
    2. run_and_wait: submit the run + poll until done.
    3. Fetch the MySQL result: pass requires fail==0 and success>0 (config-only cases with
       no assertion always fail).

    **verdict semantics (important — do not be misled by pytest)**: the returned verdict comes
    from the framework MySQL results of every check_point in this case. ``=== 1 passed ===``
    in the log only means the test_xlsx.py shell finished without crashing — **not that the
    assertions passed**; the real signal is the ``fail num is N`` lines — any N>0 makes the
    verdict fail. This tool extracts and highlights those lines for diagnosis.

    Args:
        xlsx_path: local case.xlsx path (usually under workspace/outputs/<feature>/).
        autoid: the case autoid to run (column A in the xlsx; runs that single case).
        module: staging submodule (default: compiler config staging_module).
        build: target device build string (default: compiler config build, i.e. the firmware under test).
        max_s: on-device polling timeout in seconds (default 600, clamped to 1200).

    Returns:
        Structured result: autoid / verdict (pass|fail|error) / task_id / device log tail.
        On verdict=fail the log tail is the primary diagnostic material — classify the fail
        from it, never guess.
    """
    # 1. 校验 xlsx 存在。**走 agent 文件沙箱的同一套多根解析**——agent 写 `workspace/outputs/x`
    #    实际可能落在 knowledge/data/workspace/outputs/x(_agent_roots 优先级 knowledge/data>workspace)。
    #    裸 Path() 在 CWD 找会"xlsx 不存在",必须用 _resolve_inside_root 对齐 agent 的视角。
    p = None
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        p = _resolve_inside_root(xlsx_path, must_exist=True)
    except Exception:  # noqa: BLE001
        logger.debug("xlsx 路径解析失败(将回退兜底): %s", xlsx_path, exc_info=True)
        p = None
    if p is None or not Path(p).is_file():
        # 兜底:裸路径 + 常见重定向根都试一遍
        cands = [Path(xlsx_path)]
        if not Path(xlsx_path).is_absolute():
            from pathlib import Path as _P
            root = _P(__file__).resolve().parents[4]
            cands += [root / xlsx_path, root / "knowledge" / "data" / xlsx_path]
        p = next((c for c in cands if c.is_file()), None)
    if p is None or not Path(p).is_file():
        return (f"error: xlsx not found: {xlsx_path} (tried agent-sandbox multi-root resolution "
                f"and the knowledge/data redirect; confirm the real on-disk path you wrote "
                f"to, e.g. with fs_ls)")
    p = Path(p)
    autoid = (autoid or "").strip()
    if not autoid:
        return "error: autoid is required"

    # 2. 解析默认 module / build(单一事实源:compiler config)
    try:
        from main.case_compiler.config import get_config
        cfg = get_config()
        module = (module or cfg.staging_module).strip()
        build = (build or cfg.build).strip()
    except Exception as exc:  # noqa: BLE001
        return f"error: failed to read compiler config: {exc}"

    # 3. 夹紧超时
    try:
        max_s = max(30, min(int(max_s or _DEFAULT_MAX_S), _MAX_MAX_S))
    except (TypeError, ValueError):
        max_s = _DEFAULT_MAX_S

    # 4. 连跳转机 → deliver → run_and_wait(复用 FrameworkMCPClient,口令在其内部从 env 取)
    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
    except Exception as exc:  # noqa: BLE001
        return f"error: failed to load FrameworkMCPClient (paramiko?): {exc}"

    try:
        with FrameworkMCPClient() as client:
            dres = client.deliver(module, autoid, str(p))
            if dres.get("error"):
                return (f"=== dev_run_case ===\nautoid={autoid}\nverdict: error\n"
                        f"--- deliver failed ---\n{dres.get('error')}")
            run = client.run_and_wait(module, autoid, build, [autoid], max_s=max_s)
            if run.get("busy") or run.get("error") == "device_busy":
                # 设备正在验证上一个用例——显式 verdict=busy + 正在跑的 autoid/已跑时长，
                # 让 agent 知道环境忙(而非编译错)，自行决定等待/稍后重试/上报。
                return (f"=== dev_run_case ===\nautoid={autoid}\nverdict: busy\n"
                        f"--- environment busy ---\n{run.get('message') or 'a previous case is still being verified'}")
            if run.get("error"):
                return (f"=== dev_run_case ===\nautoid={autoid}\nverdict: error\n"
                        f"--- submit/run failed ---\n{run.get('error')}")
            verdict = (run.get("results") or {}).get(autoid) or run.get("result") or "unknown"
            task_id = run.get("task_id", "")
            log_tail = (run.get("log_tail") or "")[-1200:]
            # 拉框架逐步骤执行明细(test_xlsx.txt)——每条命令实际发了什么、每个 check_point
            # 拿什么和什么比、Success/Fail Num 因果。这是框架对产物的**真实执行陈述**(ground truth),
            # pytest 的 "1 passed" 看不到这些。原样回给 agent,不解析不判断。
            detail = client.fetch_case_detail(autoid)
            # 上机非 pass：额外拉**完整设备上下文**(配置会话每条命令的设备响应 + dig 真实输出),
            # 让 agent 看到哪条命令被设备拒/为什么、dig 实际返回啥 → 知道怎么改配置/怎么填 <RUNTIME>。
            dev_ctx = client.fetch_device_context(autoid) if verdict != "pass" else ""
    except RuntimeError as exc:  # 口令缺失等
        return f"error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"error: on-device run exception: {exc}"

    # 从执行明细 + 日志尾抽 Success/Fail Num 因果行(框架对每个断言的真实裁决)。
    import re as _re
    causality = [ln.rstrip() for ln in (detail or "").splitlines()
                 if _re.search(r"(Success|Fail)\s*Num|fail to find|successed to find", ln, _re.IGNORECASE)]
    fail_lines = [ln.strip() for ln in (log_tail or "").splitlines()
                  if _re.search(r"fail\s*num\s*is", ln, _re.IGNORECASE)]
    if causality:
        fail_signal = "\n".join(causality[-12:])
    elif fail_lines:
        fail_signal = "\n".join(fail_lines[-8:])
    else:
        fail_signal = ("(no check_point Success/Fail Num line in the framework log — "
                       "not a single assertion of this case actually executed; most likely it "
                       "broke during the config phase, or there is no valid check_point at "
                       "all. Use the step-by-step detail below to locate where it stalled.)")

    return (
        f"=== dev_run_case ===\n"
        f"autoid={autoid}  module={module}  build={build}\n"
        f"verdict: {verdict}\n"
        f"task_id: {task_id}\n"
        f"--- where the verdict comes from (key — do not be misled by pytest) ---\n"
        f"verdict comes from the framework MySQL results of every check_point, not the pytest line.\n"
        f"pass requires every check_point to show `fail num is 0` with success>0.\n"
        f"`=== 1 passed ===` only means the test_xlsx.py shell finished without crashing — "
        f"**not that assertions passed**;\n"
        f"any `fail num is N` with N>0 makes the verdict fail.\n"
        f"--- framework ruling per check_point (Success/Fail Num) ---\n"
        f"{fail_signal}\n"
        f"--- framework step-by-step detail (what each command actually sent, what each assertion compared; ground truth) ---\n"
        f"{detail[-3500:] if detail else '(no execution detail retrieved)'}\n"
        + (f"--- ⚠ full device context (case did not pass; fix config / fill values from this) ---\n{dev_ctx}\n" if dev_ctx else "")
        + f"--- task log tail ---\n"
        f"{log_tail or '(no log)'}"
    )


# ── probe 缓存:run 作用域 single-flight(对抗评审定稿,替掉原关键字黑名单) ──────────
# 为什么不判命令"静/动":volatility 在**回显字段层**不在命令名层(`show sdns host status` 命令长得像
# 配置 show、回显却是探活实时态),黑名单漏判 novel 动态命令→喂 stale、白名单又会把这类收进来;
# 且 footprint 节点无 volatility 字段可派生——"判命令静动"本仓没可靠数据源,押不赢。
# 改用**结构性保证**:compile 期设备只读(dev_probe 硬白名单仅 show/get、无写命令),故**一次 run 内
# 同一条 show、N 个并发 draft 只真探一次、其余等结果**(single-flight),精准解"N draft 各探一遍同
# show + 都砸设备锁"的真慢主因。**run 结束即弃、不跨 run**(跨 run 设备态会变、不 sound;真静态事实
# 由 footprint _FP_CACHE 缓)。动态命令一次 run 内的微小漂移对 draft 合法行为无害——断言期望值禁止
# observe-then-assert(红线),draft 要的是回显结构/语法,不是此刻精确计数。soundness 来自"作用域内
# 只探一次"(可证),不靠"分类准不准"(易错)。
import contextvars

_current_run_token: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "probe_run_token", default=None)
_PROBE_WAIT_TIMEOUT_S = 180.0       # 等待者等首探者的上限,超时自己裸探(防永久阻塞)


class _ProbeEntry:
    """single-flight 槽:首探者填 result 后 set(event);等待者 wait() 返回后读 result(happens-before)。"""
    __slots__ = ("event", "result")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: str | None = None


_PROBE_RUN_CACHE: dict[str, dict[str, _ProbeEntry]] = {}   # {run_token: {cmd_key: _ProbeEntry}}
_PROBE_RUN_LOCK = threading.Lock()
_run_token_counter = 0


def _new_run_token() -> str:
    """每次 _run_pipeline 生成唯一 run_token(进程内单调,不依赖随机)。"""
    global _run_token_counter
    with _PROBE_RUN_LOCK:
        _run_token_counter += 1
        return f"run-{_run_token_counter}"


def _clear_run_cache(run_token: str) -> None:
    """run 结束清掉该 run 的 single-flight 桶(跨 run 不复用)。"""
    with _PROBE_RUN_LOCK:
        _PROBE_RUN_CACHE.pop(run_token, None)


def _probe_uncacheable(result: str) -> bool:
    """该探针结果是否不该进 single-flight 缓存(失败/锁竞争/空)——移除槽留待重探,不喂坏值。

    **关键区分(切 FastMCP 后)**：`status: error` 有两种来源——
      - CLI 语法错误(无效命令)：FastMCP 回 `status: error` + `--- output ---`(对齐 ^)。这是
        **确定性结果**(命令就是无效,重探也一样)→ **必须缓存**,否则无效命令被反复真探(churn 根因,
        43dcabe5 实测无效命令真探 21 次)。
      - 传输/连接/认证/锁失败：`error: SSH ... failed` / `--- error ---` / `another run in progress`
        → 瞬态,不缓存,留待重探。
    """
    r = result or ""
    rl = r.lower()
    if not r.strip():
        return True
    # 瞬态/传输/锁失败 → 不缓存
    if any(m in rl for m in (
            "another run in progress", "lock held",
            "--- error ---",                       # FastMCP restapi 传输失败段
            "connection refused", "authentication failed", "timed out",
            "probe failed", "device probe exception", "load frameworkmcpclient")):
        return True
    # 裸 'error:' 行(老 _do_probe 加载/异常返回 / apv_ssh 'error: SSH ... failed' 传输失败)
    for line in r.splitlines():
        if line.strip().lower().startswith("error:"):
            return True
    # status:error 仅当带 '--- output ---'(确定性 CLI 回显/语法错误)才可缓存;
    # 无 '--- output ---' 的 status:error 是错误消息(如老 probe_show 错误分支)→ 不缓存
    if "status: error" in rl and "--- output ---" not in rl:
        return True
    return False


def _annotate_if_empty_probe(text: str) -> str:
    """探针回显**实质为空**（剥标头/命令行/裸提示符后无内容）时附时机语义提示。

    实证（OBS-15）：worker 编译期探统计类命令拿到裸提示符就困惑重试/转 grep 文档。
    根因是 probe 的时机语义——每个 case 跑完框架清配置，编译期设备是干净态，
    统计/会话/状态类数据只在 case 执行中存在，此时探必空。这不是探针故障。
    """
    body = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s or s.startswith(("===", "---", "command:", "status:")):
            continue
        # 裸提示符行（如 `XXX#` / `XXX>`）不算实质内容
        if len(s) <= 40 and (s.endswith("#") or s.endswith(">")) and " " not in s:
            continue
        if s == "(no output)":
            continue
        body.append(s)
    if body:
        return text
    return (f"{text}\n"
            "(note: an empty echo does not mean the probe failed — at compile time the device "
            "is in a **clean state** (the framework wipes config after every case), so "
            "statistics/session/state data exist only while a case is executing and always "
            "probe empty here. This probe is valid for: command-syntax verification (invalid "
            "commands get the ^ marker) and persistent-config inspection. For output **format**, "
            "consult the product manual/spec or precedents — do not keep re-probing emptiness.)")


def _do_probe(cmd: str, mode: str = "show", *, annotate: bool = True) -> str:
    """真探一次设备。**永不抛**——失败返回 'error:'/包装文本。

    优先走新版 FastMCP ``apv_ssh_execute``（自带 status + 完整回显 + 对齐 ^，治老 probe_show
    剥命令回显行→无效命令只剩裸 ^ 的困惑）；FastMCP 不可达 / 解析不出设备 IP 时回退老 stdio
    ``probe_show``。两路都经跳转机，本地直连 APV 不通。

    mode="config":配置模式执行(床态初始化清理专用——clear 族在 show 通道被拒,
    2026-07-10 实证);该模式不回退 stdio(老通道只有只读)。

    annotate=True(默认,worker 便利):空回显尾部附时机语义提示(OBS-15,别对空统计反复重探)。
    annotate=False:返回**原始设备事实**,不拼提示——**机器消费者(bed 残留检测)专用**:那段提示
    是探针元输出、非床内容,`annotate=True` 时会被 bed_check 误当"分区配置残留"(回归#3 根因,
    2026-07-15;分离关注点=worker 拿带提示的、bed 拿原始的)。
    """
    _wrap = _annotate_if_empty_probe if annotate else (lambda s: s)
    # build 决定 conf 设备段(单一事实源:compiler config)
    try:
        from main.case_compiler.config import get_config
        _build = get_config().build
    except Exception:  # noqa: BLE001
        logger.debug("读取 compiler config 失败，build 使用空串", exc_info=True)
        _build = ""
    # 1) 新版 FastMCP apv_ssh_execute —— status + 对齐 ^，不剥回显
    try:
        from main.case_compiler.device_mcp_client import probe_via_fastmcp, _redact
        fr = probe_via_fastmcp(cmd, build=_build, mode=mode)
    except Exception:  # noqa: BLE001
        logger.debug("FastMCP 探针失败(将回退 stdio): cmd=%s", cmd, exc_info=True)
        fr = None
    if mode != "show" and not (isinstance(fr, dict) and fr.get("text")):
        return "error: config-mode execution unavailable (FastMCP unreachable)"
    if isinstance(fr, dict) and fr.get("text"):
        text = fr["text"]
        try:
            text = _redact(str(text))
        except Exception:  # noqa: BLE001
            logger.debug("脱敏处理失败，使用原始文本", exc_info=True)
        # 服务端把 SSH/通道级失败以 `error:` 契约行返回——此时不包横幅:本函数契约是
        # "失败返回 'error:' 前缀",下游(床态 _probe_failed 等)按首行识别工具级失败;
        # 包了横幅错误就穿门成"设备内容"(2026-07-13 实证:105 床 SSH 挂死被报成残留)
        if str(text).lstrip().startswith("error"):
            return str(text).strip()
        # apv_ssh_execute 文本已自带 command/status/回显+对齐 ^，原样回灌(仅打 dev_probe 来源标)
        return _wrap(f"=== dev_probe (fastmcp apv_ssh) ===\n{text}")
    # 2) 回退：老 stdio probe_show（剥回显，无效命令只剩裸 ^）
    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
    except Exception as exc:  # noqa: BLE001
        return f"error: failed to load FrameworkMCPClient (paramiko?): {exc}"
    try:
        with FrameworkMCPClient() as client:
            res = client.probe_show(cmd, build=_build)
    except RuntimeError as exc:
        return f"error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"error: device probe exception: {exc}"
    if isinstance(res, dict) and res.get("error"):
        return f"=== dev_probe ===\ncommand: {cmd}\nstatus: error\n{res.get('error')}"
    output = res.get("output") if isinstance(res, dict) else res
    # 设备回显回灌 agent 前脱敏:show running-config 等可能含口令/community(守红线「日志不打凭据」)
    try:
        from main.case_compiler.device_mcp_client import _redact
        output = _redact(str(output)) if output else output
    except Exception:  # noqa: BLE001
        logger.debug("脱敏处理失败，使用原始输出", exc_info=True)
    return _wrap(
        f"=== dev_probe ===\n"
        f"command: {cmd}\n"
        f"--- device echo (via jumphost) ---\n"
        f"{output if output else '(no output)'}")


@tool(parse_docstring=True)
def dev_probe(command: str) -> str:
    """Run a **single read-only show/get command** on the APV device under test via the jumphost, returning the real device echo.

    **Testbed topology (key)**: the APV device is reachable only through the jumphost; local /
    direct access (dev_ssh / dev_rest straight at the APV IP) **does not work** — that is the
    topology, not a device outage. To see a command's real echo (whether config took effect,
    what a show output looks like, confirming command syntax), use this tool (it goes via the
    jumphost); do not dev_ssh straight to the APV.

    Restriction: hard allowlist — the first token must be show or get (read-only probe, never
    mutates device state). To change config and run assertions for pass/fail → dev_run_case
    (whole case on-device).

    **Key strategy — turn "dynamic behavior that is hard to assert directly" into "stable
    output that a text search can verify"**: when a behavior resists direct assertion
    (runtime-only dynamic values, timing behavior, cross-step state changes — e.g. "same IP
    within the persistence window / different IP after timeout", "rr rotation distribution",
    "connection keep-alive"), **do not grind on capturing the dynamic value** — the device
    usually has a show command that renders that behavior's **observable signature** as stable
    text (config in effect, statistics counters, state-table entries). Probe that show command
    first, see the shape of its output, then write the assertion as found/not_found over the
    stable output. This lowers "a dynamic comparison the xlsx cannot express" into "a text
    search the xlsx can express".

    Typical uses (which concrete show command fits is a domain judgment — derive it from
    the version manual / verified precedents / footprint, never from this docstring):
    - confirm config took effect (a config-view show of the object you configured)
    - inspect a behavior's stable signature (a statistics/state-table show for that object)
    - check a command's syntax response (probe the show form first, read the echo shape)

    **Device syntax errors**: for unrecognized commands/parameters the APV echoes a ``^``
    marker under the offending token. The framework server wraps that echo into a clear
    ``% Invalid input ...`` explanation (with the command echo line and alignment) — seeing it
    means the command syntax/parameter is invalid: **change the command or fix the syntax; never
    write an assertion based on it**.

    Args:
        command: a single read-only command; the first word must be show or get (runs on the APV under test).

    Returns:
        The real device echo (or an error explanation). Use it to understand device behavior
        and write/fix assertions — but expected values still need provenance (author intent /
        spec / precedent); never copy "whatever this output happens to show" as the expectation.
    """
    cmd = (command or "").strip()
    if not cmd:
        return "error: empty command"
    first = cmd.split()[0].lower() if cmd.split() else ""
    if first not in ("show", "get"):
        return (f"error: probe only accepts read-only commands starting with show/get, got {first!r}. "
                "The probe exists to understand behavior/format at compile time and performs no "
                "config action; config/trigger/assertions go into case steps, and behavioral "
                "effect is verified by the separate ist-verify on-device flow.")

    # run 作用域 single-flight:同一 run 内同命令只真探一次,其余等结果(见上方设计注释)。
    key = " ".join(cmd.lower().split())
    run_token = _current_run_token.get()
    if run_token is None:
        return _do_probe(cmd)        # 无 compile run 上下文(main agent 手动探)→ 裸探、不缓、不串

    with _PROBE_RUN_LOCK:
        bucket = _PROBE_RUN_CACHE.setdefault(run_token, {})
        entry = bucket.get(key)
        first = entry is None
        if first:
            entry = _ProbeEntry()
            bucket[key] = entry

    if first:                        # 首探者:真探 → 填结果 → 唤醒等待者
        try:
            result = _do_probe(cmd)
            if _probe_uncacheable(result):
                with _PROBE_RUN_LOCK:   # 失败/锁竞争:移槽让后续重探(已在等的拿到本结果)
                    _PROBE_RUN_CACHE.get(run_token, {}).pop(key, None)
            entry.result = result       # 先写结果,再 set(event)——happens-before,等待者 wait 后读安全
        finally:
            entry.event.set()           # BaseException 也 set,防等待者卡满 _PROBE_WAIT_TIMEOUT_S
        return result

    # 等待者:等首探者出结果;超时则自己裸探(防永久阻塞,不污染缓存)
    if not entry.event.wait(timeout=_PROBE_WAIT_TIMEOUT_S):
        return _do_probe(cmd)
    return entry.result if entry.result is not None else _do_probe(cmd)


@tool(parse_docstring=True)
def dev_help(command: str) -> str:
    """When the device rejects a command (``^`` or ``Failed to execute the command`` in the echo),
    ask the device what it expects at that position — turning the wordless ``^`` into an explanation.

    ``^`` stops under the last token the device could parse left-to-right — parsing cannot
    continue past there. The ``^`` itself carries no text, so the reason is invisible. The
    diagnostic move: keep the command up to where ``^`` stopped, add a space and a question
    mark there, and the device states what it expects at that position. This tool does that
    step for you: it finds the longest device-recognizable prefix, asks once at that position
    (ask only — no Enter, nothing executed, no config change; the line is cleared with
    Ctrl-U), and brings back the device's description.

    Example (synthetic shape — the mechanism, not a command to copy): ``<verb> <object>
    "name-a" "name-b" <word>`` gets ``^`` under ``<word>`` — the device parsed up to
    ``"name-b"`` and stopped. Asking at that position returns the device's own statement of
    what it expects there (say, a numeric field with its valid range and applicability). Now
    it is clear a different token type is required where you wrote ``<word>``.

    When to use: you saw ``^`` or ``Failed to execute the command`` in a dev_probe or on-device
    echo and need to know why and how to fix it. When not to use: the command runs but the
    result is wrong — that is semantics or config; read the reason line in the device echo, or
    run the whole case with dev_run_case.

    Also: if ``Failed to execute the command`` comes with a reason line (e.g. "The SDNS host
    \"x\" does not exist"), that is a semantic problem — a nonexistent object was referenced or
    prerequisite config is missing, not a syntax error. In that case this tool reports the
    syntax as complete; trust the device's reason line and create the prerequisite object.

    Args:
        command: the rejected command (pass it verbatim, including quotes).

    Returns:
        The longest device-recognizable prefix + what that position expects + which of your
        tokens violated it. Fix the command syntax / switch the parameter accordingly.
    """
    cmd = (command or "").strip()
    if not cmd:
        return "error: empty command"
    try:
        from main.case_compiler.config import get_config
        _build = get_config().build
    except Exception:  # noqa: BLE001
        logger.debug("读取 compiler config 失败，build 使用空串", exc_info=True)
        _build = ""
    try:
        from main.case_compiler.device_mcp_client import cli_qhelp
    except Exception as exc:  # noqa: BLE001
        return f"error: failed to load cli_qhelp (paramiko?): {exc}"

    try:
        r = cli_qhelp(cmd, build=_build)
    except Exception as exc:  # noqa: BLE001
        return f"error: dev_help exception: {exc}"

    if not r.get("ok"):
        return (f"=== dev_help ===\ncommand: {cmd}\nstatus: query failed\n"
                f"{r.get('error', 'unknown reason')}\n"
                f"(if the device is unreachable, fall back to dev_probe for the raw echo, "
                f"or look up the syntax in precedents/the manual.)")

    lines = [f"=== dev_help ===", f"command: {cmd}", f"mode: {r.get('mode')}"]
    if r.get("full_valid"):
        lines.append("The device parses the whole command — `^` is not a syntax problem.")
        if r.get("expect"):
            lines.append(f"After this command, this position can additionally take: {r['expect']}")
        lines.append("If on-device it reports `Failed to execute the command`, that is most "
                     "likely semantics: a nonexistent object was referenced or prerequisite "
                     "config is missing. Trust the reason line in the device echo and create "
                     "the prerequisite first.")
    else:
        vp = r.get("valid_prefix") or "(none)"
        off = r.get("offending")
        lines.append(f"Longest prefix the device parses left-to-right (`^` stops right after it): `{vp}`")
        if r.get("expect"):
            lines.append(f"At that position the device expects: {r['expect']}")
        if off is not None:
            lines.append(f"Your token `{off}` does not meet that expectation — that is why `^` stopped there.")
        lines.append("Check whether this position wants a value or a fixed keyword and fix "
                     "accordingly; values quoted in the description are examples only — never "
                     "copy them into assertions.")
    # 附各位置期望图（供自查更细的位置）
    mp = [m for m in (r.get("map") or []) if m.get("expect")]
    if mp:
        lines.append("--- expectations at each prefix position (for self-check) ---")
        for m in mp:
            lines.append(f"  `{m['prefix']}` ▸ {m['expect']}")
    return "\n".join(lines)


@tool(parse_docstring=True)
def dev_init_device(jumphost: str, device_count: int = 0, device_index: int = -1,
                    confirm_wipe_reason: str = "") -> str:
    """Initialize the device under test over the serial console: wipe all config + reconfigure interface IPs.

    Runs on the jumphost, connects to the device over serial (cu -s 9600 -l ttyS{n}), issues
    clear config all, then configures the interface IPv4/IPv6 addresses from the testbed conf.

    **DESTRUCTIVE — whole-device config wipe on a SHARED testbed.** This erases ALL config
    (including anything another run is mid-way through) and can only be justified by an
    explicit human decision. It requires ``confirm_wipe_reason``; called without it (the
    default for an autonomous agent) it refuses and does nothing. A wrong wipe on a shared
    bed is the exact class of accident that killed two beds — see the destructive-command
    ban (§18.4.1). Recovering a dirty bed is normally the human's call; do not self-authorize.

    **When to use**: a human has decided the device needs a factory reset (config in disarray,
    a newly-racked device, a clean baseline before a run) AND passes the reason.
    **When not to use**: to change one piece of config → dev_run_case; to inspect state →
    dev_probe. Never call this to "clean up" on your own initiative.

    Args:
        jumphost: jumphost IP (e.g. 10.4.127.103), required.
        device_count: number of devices to initialize (1/2/3); 0 = infer from conf (default all).
        device_index: initialize one specific device (0=APV0, 1=APV1, 2=APV2); takes precedence over device_count.
        confirm_wipe_reason: REQUIRED human-authorized reason for the whole-device wipe; empty = refuse.

    Returns:
        Per-device initialization result (ok/failed + log), or a refusal if confirm_wipe_reason is empty.
    """
    # 确认闸(2026-07-13,两床事故后):整机清配是「误判即毁床」操作,非交互 agent 直调
    # 无 reason 一律拒——保留运维/受控点带 reason 的调用能力(与 emit override_frozen_reason
    # 同型:高危动作强制显式声明)。作用域=共享床,授权归人(§18.4.1 destructive 红线)。
    if not str(confirm_wipe_reason or "").strip():
        return ("=== dev_init_device ===\nstatus: refused\n"
                "This wipes ALL config on a shared device (clear config all over serial) and "
                "requires an explicit human-authorized reason. Pass confirm_wipe_reason=... only "
                "when a human has decided a factory reset is warranted. Do NOT self-authorize a "
                "wipe to 'clean up' — recovering a dirty bed is the human's call. To change one "
                "piece of config use dev_run_case; to inspect state use dev_probe.")
    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
        from main.case_compiler.config import Environment
    except Exception as exc:
        return f"error: failed to load modules: {exc}"
    logger.warning("dev_init_device 整机清配授权执行: jumphost=%s reason=%s",
                   jumphost, str(confirm_wipe_reason)[:120])

    env = Environment(id="adhoc", jumphost=jumphost)

    try:
        with FrameworkMCPClient(env=env) as client:
            res = client.init_device(device_count=device_count, device_index=device_index)
    except RuntimeError as exc:
        return f"error: {exc}"
    except Exception as exc:
        return f"error: device initialization exception: {exc}"

    if isinstance(res, dict) and res.get("error"):
        return f"=== dev_init_device ===\nstatus: error\n{res.get('error')}"

    lines = ["=== dev_init_device ==="]
    for d in (res.get("details") or []):
        status = d.get("status", "?")
        idx = d.get("device", "?")
        ip = d.get("ssh_ip", "?")
        tty = d.get("tty", "?")
        if status == "ok":
            lines.append(f"APV{idx} ({tty}, {ip}): initialized")
        else:
            lines.append(f"APV{idx} ({tty}, {ip}): failed — {d.get('error', '?')}")
        for log_line in (d.get("log") or []):
            lines.append(f"  {log_line}")

    lines.append(f"\ntotal: {res.get('initialized', 0)} ok / {res.get('failed', 0)} failed / {res.get('total', 0)} devices")
    return "\n".join(lines)
