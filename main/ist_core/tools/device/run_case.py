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
    """把一个 case.xlsx 下发到跳转机 pytest 框架并上机运行,返回 pass/fail + 设备日志尾。

    这是**执行验证 oracle**:一个 case 上机 pass/fail 由设备 + 框架裁决,不是 agent 自评。
    用于调查循环——合成/改写 case 后真机跑一次,据 fail 日志诊断(逻辑错/环境/产品缺陷/
    用例描述错/手册描述错),改方案再跑,直到 pass 或确诊为产品缺陷。

    **何时用**:你已经产出/改好一个 case.xlsx,要知道它在真机上到底过不过。
    **何时不用**:只想看一条 CLI 命令的回显或语法对不对 → 用 dev_ssh(更快,单命令)。
    **前置**:断言期望值要先有出处(作者意图/已声明资源/框架先例),别凭空编;CLI 语法
    拿不准先 grep ``knowledge/data/markdown/product/cli_*_Chapter*.md`` + ``cli_*_Appendix*.md`` 或 dev_ssh 探一下。

    框架流程(本工具内部完成,你只看结果):
    1. deliver:把 xlsx 落到跳转机 staging 目录(框架自动 xlsx→python)。
    2. run_and_wait:提交运行 + 轮询到 done。
    3. 取 MySQL result:pass 条件 = fail==0 且 success>0(纯配置无断言必 fail)。

    **verdict 语义(重要,别被 pytest 误导)**:返回的 verdict 来自框架 MySQL 里本 case
    每个 check_point 的结果。日志里 ``=== 1 passed ===`` 只表示 test_xlsx.py 壳跑完没崩,
    **不代表断言通过**;真正看 ``fail num is N`` 行——任一 N>0 则 verdict=fail。
    本工具已把 fail num 行单独抽出高亮,据它诊断。

    Args:
        xlsx_path: 本地 case.xlsx 路径(通常在 workspace/outputs/<feature>/ 下)。
        autoid: 要运行的用例 autoid(xlsx 内 A 列;单 case 跑指定那个)。
        module: staging 子模块归属(默认取 compiler config 的 staging_module)。
        build: 目标设备 build 串(默认取 compiler config 的 build,即当前在测固件)。
        max_s: 上机轮询超时秒数(默认 600,夹紧到 1200)。

    Returns:
        结构化结果:autoid / verdict(pass|fail|error) / task_id / 设备日志尾。
        verdict=fail 时日志尾是诊断的一手材料,据它判 fail 属哪类,绝不靠猜。
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
        return (f"error: xlsx 不存在: {xlsx_path}(已试 agent 沙箱多根解析 + "
                f"knowledge/data 重定向均未命中;确认你 write_file 的真实落盘路径,"
                f"用 fs_ls 看一下)")
    p = Path(p)
    autoid = (autoid or "").strip()
    if not autoid:
        return "error: 必须指定 autoid"

    # 2. 解析默认 module / build(单一事实源:compiler config)
    try:
        from main.case_compiler.config import get_config
        cfg = get_config()
        module = (module or cfg.staging_module).strip()
        build = (build or cfg.build).strip()
    except Exception as exc:  # noqa: BLE001
        return f"error: 读取 compiler config 失败: {exc}"

    # 3. 夹紧超时
    try:
        max_s = max(30, min(int(max_s or _DEFAULT_MAX_S), _MAX_MAX_S))
    except (TypeError, ValueError):
        max_s = _DEFAULT_MAX_S

    # 4. 连跳转机 → deliver → run_and_wait(复用 FrameworkMCPClient,口令在其内部从 env 取)
    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
    except Exception as exc:  # noqa: BLE001
        return f"error: 加载 FrameworkMCPClient 失败(paramiko?): {exc}"

    try:
        with FrameworkMCPClient() as client:
            dres = client.deliver(module, autoid, str(p))
            if dres.get("error"):
                return (f"=== dev_run_case ===\nautoid={autoid}\nverdict: error\n"
                        f"--- deliver 失败 ---\n{dres.get('error')}")
            run = client.run_and_wait(module, autoid, build, [autoid], max_s=max_s)
            if run.get("busy") or run.get("error") == "device_busy":
                # 设备正在验证上一个用例——显式 verdict=busy + 正在跑的 autoid/已跑时长，
                # 让 agent 知道环境忙(而非编译错)，自行决定等待/稍后重试/上报。
                return (f"=== dev_run_case ===\nautoid={autoid}\nverdict: busy\n"
                        f"--- 环境忙 ---\n{run.get('message') or '正在验证上一个用例'}")
            if run.get("error"):
                return (f"=== dev_run_case ===\nautoid={autoid}\nverdict: error\n"
                        f"--- 提交/运行失败 ---\n{run.get('error')}")
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
        return f"error: 上机运行异常: {exc}"

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
        fail_signal = ("(框架日志里没有任何 check_point 的 Success/Fail Num 行——"
                       "说明这个 case 一个断言都没真正执行到,多半在配置阶段就出错了,"
                       "或者根本没有有效的 check_point。看下面执行明细定位卡在哪一步。)")

    return (
        f"=== dev_run_case ===\n"
        f"autoid={autoid}  module={module}  build={build}\n"
        f"verdict: {verdict}\n"
        f"task_id: {task_id}\n"
        f"--- verdict 怎么来的(关键,别被 pytest 误导)---\n"
        f"verdict 来自框架 MySQL 里本 case 每个 check_point 的结果,不是 pytest 那行。\n"
        f"pass 条件 = 所有 check_point 的 `fail num is 0` 且 success>0。\n"
        f"日志里 `=== 1 passed ===` 只表示 test_xlsx.py 这个壳跑完没崩,**不代表断言通过**;\n"
        f"只要有任一 `fail num is N(N>0)`,verdict 就是 fail。\n"
        f"--- 框架对每个 check_point 的真实裁决(Success/Fail Num)---\n"
        f"{fail_signal}\n"
        f"--- 框架逐步骤执行明细(每条命令实际发了什么、断言拿什么和什么比;ground truth)---\n"
        f"{detail[-3500:] if detail else '(未取到执行明细)'}\n"
        + (f"--- ⚠ 完整设备上下文(上机未过,据此改配置/填值)---\n{dev_ctx}\n" if dev_ctx else "")
        + f"--- 任务日志尾 ---\n"
        f"{log_tail or '(无日志)'}"
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
            "probe failed", "设备探针异常", "加载 frameworkmcpclient")):
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


def _do_probe(cmd: str) -> str:
    """真探一次设备。**永不抛**——失败返回 'error:'/包装文本。

    优先走新版 FastMCP ``apv_ssh_execute``（自带 status + 完整回显 + 对齐 ^，治老 probe_show
    剥命令回显行→无效命令只剩裸 ^ 的困惑）；FastMCP 不可达 / 解析不出设备 IP 时回退老 stdio
    ``probe_show``。两路都经跳转机，本地直连 APV 不通。
    """
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
        fr = probe_via_fastmcp(cmd, build=_build)
    except Exception:  # noqa: BLE001
        logger.debug("FastMCP 探针失败(将回退 stdio): cmd=%s", cmd, exc_info=True)
        fr = None
    if isinstance(fr, dict) and fr.get("text"):
        text = fr["text"]
        try:
            text = _redact(str(text))
        except Exception:  # noqa: BLE001
            logger.debug("脱敏处理失败，使用原始文本", exc_info=True)
        # apv_ssh_execute 文本已自带 command/status/回显+对齐 ^，原样回灌(仅打 dev_probe 来源标)
        return f"=== dev_probe (fastmcp apv_ssh) ===\n{text}"
    # 2) 回退：老 stdio probe_show（剥回显，无效命令只剩裸 ^）
    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
    except Exception as exc:  # noqa: BLE001
        return f"error: 加载 FrameworkMCPClient 失败(paramiko?): {exc}"
    try:
        with FrameworkMCPClient() as client:
            res = client.probe_show(cmd, build=_build)
    except RuntimeError as exc:
        return f"error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"error: 设备探针异常: {exc}"
    if isinstance(res, dict) and res.get("error"):
        return f"=== dev_probe ===\ncommand: {cmd}\nstatus: error\n{res.get('error')}"
    output = res.get("output") if isinstance(res, dict) else res
    # 设备回显回灌 agent 前脱敏:show running-config 等可能含口令/community(守红线「日志不打凭据」)
    try:
        from main.case_compiler.device_mcp_client import _redact
        output = _redact(str(output)) if output else output
    except Exception:  # noqa: BLE001
        logger.debug("脱敏处理失败，使用原始输出", exc_info=True)
    return (f"=== dev_probe ===\n"
            f"command: {cmd}\n"
            f"--- 设备回显(经跳转机)---\n"
            f"{output if output else '(无输出)'}")


@tool(parse_docstring=True)
def dev_probe(command: str) -> str:
    """经跳转机在被测 APV 设备上跑**单条只读 show/get 命令**,取真实设备回显。

    **本测试床网络拓扑(关键)**:APV 被测设备只能经跳转机访问,你本地/直连
    (dev_ssh / dev_rest 直打 APV IP)**不通**——那不是设备掉线,是拓扑使然。
    要看设备上某条命令的真实回显(探查配置生效没、show 输出长什么样、确认命令语法),
    用本工具(它经跳转机到设备),不要用 dev_ssh 直连 APV。

    限制:硬白名单,首 token 必须是 show 或 get(只读探针,不改设备状态)。
    要改配置 + 跑断言看 pass/fail → 用 dev_run_case(整 case 上机)。

    **关键策略——把"难直接断言的动态行为"转成"可文本查找的稳定输出"**:
    当某行为用断言难以直接表达(运行时才知道的动态值、时序行为、跨步骤状态变化,
    如"会话保持期内同IP/超时后不同IP""rr轮询分布""连接保持"),**别死磕去捕获那个动态值**——
    设备通常有一条 show 命令能把该行为的**可观测特征**显示成稳定文本(配置生效与否、
    统计计数、状态表条目)。先用本工具探出那条 show 命令、看它输出长什么样,
    再把断言改成对那个稳定输出做 found/not_found。这把"xlsx 表达不了的动态比对"
    降成"xlsx 能表达的文本查找"。

    典型用法:
    - 确认配置生效:``command="show sdns host status"``
    - 看计数器分布:``command="show statistics sdns pool"``
    - 核对命令语法返回:``command="show sdns listener"``

    **设备语法错误**:被测 APV 对无法识别的命令/参数,在出错 token 下方回 `^` 标记。
    框架 server 已把这种回显包装成清晰的 ``% Invalid input ...`` 文字说明(含命令回显行
    与对齐)——遇到即说明该命令语法/参数无效,**换命令或修正语法,不要据此写断言**。

    Args:
        command: 单条只读命令,首词必须 show 或 get(在被测 APV 上执行)。

    Returns:
        设备真实回显(或错误说明)。据此理解设备行为、写/改断言——但断言期望值
        仍须有出处(作者意图/规范/先例),不要"看这次输出是啥就照抄成期望"。
    """
    cmd = (command or "").strip()
    if not cmd:
        return "error: empty command"
    first = cmd.split()[0].lower() if cmd.split() else ""
    if first not in ("show", "get"):
        return f"error: probe 只允许 show/get 开头的只读命令,收到 {first!r}。改配置请用 dev_run_case 整 case 上机。"

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
def dev_init_device(jumphost: str, device_count: int = 0, device_index: int = -1) -> str:
    """通过串口初始化被测设备：清除全部配置 + 重新配置接口 IP。

    在跳板机上执行，经串口（cu -s 9600 -l ttyS{n}）连接设备，执行 clear config all
    后配置 port1（172.16.35.7{n}）、port2（172.16.34.7{n}）、port3（172.16.32.7{n}）
    的 IPv4/IPv6 地址。

    **何时用**：设备配置混乱需要恢复出厂、新设备首次上架、或上机前需要干净基线。
    **何时不用**：只想改某条配置 → 用 dev_run_case 跑 case 或 dev_probe 查状态。

    Args:
        jumphost: 跳板机 IP（如 10.4.127.103），必填。
        device_count: 初始化设备数（1/2/3），0=从 conf 自动推断（默认全部）。
        device_index: 指定初始化哪台（0=APV0, 1=APV1, 2=APV2），优先级高于 device_count。

    Returns:
        每台设备的初始化结果（成功/失败 + 日志）。
    """
    try:
        from main.case_compiler.device_mcp_client import FrameworkMCPClient
        from main.case_compiler.config import Environment
    except Exception as exc:
        return f"error: 加载模块失败: {exc}"

    env = Environment(id="adhoc", jumphost=jumphost)

    try:
        with FrameworkMCPClient(env=env) as client:
            res = client.init_device(device_count=device_count, device_index=device_index)
    except RuntimeError as exc:
        return f"error: {exc}"
    except Exception as exc:
        return f"error: 设备初始化异常: {exc}"

    if isinstance(res, dict) and res.get("error"):
        return f"=== dev_init_device ===\nstatus: error\n{res.get('error')}"

    lines = ["=== dev_init_device ==="]
    for d in (res.get("details") or []):
        status = d.get("status", "?")
        idx = d.get("device", "?")
        ip = d.get("ssh_ip", "?")
        tty = d.get("tty", "?")
        if status == "ok":
            lines.append(f"APV{idx} ({tty}, {ip}): 初始化成功")
        else:
            lines.append(f"APV{idx} ({tty}, {ip}): 失败 — {d.get('error', '?')}")
        for log_line in (d.get("log") or []):
            lines.append(f"  {log_line}")

    lines.append(f"\n总计: {res.get('initialized', 0)} 成功 / {res.get('failed', 0)} 失败 / {res.get('total', 0)} 总数")
    return "\n".join(lines)
