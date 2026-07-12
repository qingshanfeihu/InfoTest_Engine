"""compile_emit: 从简单步骤列表产出**结构正确**的 case.xlsx(克隆框架原生模板)。

为什么要它:agent 用 run_python 手搓 openpyxl 总在模板结构/列对齐上出错(E/F/G 错位、缺
27 行说明区、缺 C=0/C=1)→ 框架找不到 case 行 → 零 check_point → 空真 pass。
本工具复用 case_compiler.xlsx_emit.emit_xlsx——它克隆真实跑通的 sdns_listener.xlsx 模板,
只重写数据区,保留全部说明区/字典区/格式/列对齐。**结构由工具保证,内容由 agent 决定。**

agent 只需给:文件级前置命令(init) + 步骤列表(每步 actor/action/data)。列语义:
  E=操作对象(被测设备/check_point/test_env/time)  F=方法(cmd_config/cmds_config/found/
  not_found/found_times/事实源主机名/sleep...)  G=数据(命令/期望文本)
  H=save_as(存变量,可选)  I=input_var(引用变量,可选)
工具自动放进正确的行/列,agent 不碰模板结构。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 框架执行契约(死知识):test_xlsx.py 是**延迟执行模型**——最后一个 case 走 `if last_case`
# 收尾分支,只 parser_case_id 记录、**不执行步骤**。所以 xlsx 末尾必须垫一个哨兵 case,
# 让真实 case 都不是最后一个、走正常执行路径。哨兵自己当 last_case 不执行,无副作用。
# 这对单 case 和多 case 合并是同一条契约:cases=[真case..., _sentinel]。
_SENTINEL_AUTOID = "999999999999999"

# 同 autoid 的 steps_json 连续解析失败计数(进程内):worker 对解析错误常原样重试
# (2026-07-02 实证单 case 连摔 25 次),连败达阈值时在报错里附停止重试的升级指引。
# 成功解析即清零;fork LoopGuard 对"参数微变的连续 error"不敏感,这层是精准补位。
import threading as _threading

_EMIT_FAIL_STREAK: dict[str, int] = {}
_EMIT_FAIL_LOCK = _threading.Lock()


def _emit_fail_streak_bump(autoid: str) -> int:
    with _EMIT_FAIL_LOCK:
        _EMIT_FAIL_STREAK[autoid] = _EMIT_FAIL_STREAK.get(autoid, 0) + 1
        return _EMIT_FAIL_STREAK[autoid]


def _emit_fail_streak_clear(autoid: str) -> None:
    with _EMIT_FAIL_LOCK:
        _EMIT_FAIL_STREAK.pop(autoid, None)


def _parse_autoids_arg(autoids: str | list[str] | None) -> tuple[list[str] | None, str | None]:
    """解析 ``compile_emit_merged`` 的 autoids 参数。

    返回 ``(aid_list, error)``：
    - ``(None, None)`` — 未提供 autoids（缺省、空串、空 list），走 cases_json 分支；
    - ``([], "error: …")`` — 显式传了 autoids 但解析后无有效 id（如 ``'[]'``、``["", "  "]``）；
    - ``(aid_list, None)`` — 解析成功，aid_list 非空。

    与旧 ``bool(autoids) and (list or strip())`` 不同：不再把「参数存在」与「解析非空」混在一个布尔里。
    """
    if autoids is None:
        return None, None
    if isinstance(autoids, list):
        if not autoids:
            return None, None
        aid_list = [str(a).strip() for a in autoids if str(a).strip()]
        if not aid_list:
            return [], "error: autoids list has no valid id (all elements empty)"
        return aid_list, None
    s = str(autoids).strip()
    if not s:
        return None, None
    try:
        parsed = json.loads(s) if s.startswith("[") else [x.strip() for x in s.split(",") if x.strip()]
    except json.JSONDecodeError as e:
        return [], f"error: autoids JSON parse failed: {e}"
    if not isinstance(parsed, list):
        return [], "error: autoids must be a JSON array or a comma-separated id list"
    aid_list = [str(a).strip() for a in parsed if str(a).strip()]
    if not aid_list:
        return [], ("error: autoids resolved to empty (pass a non-empty JSON array, a "
                    "comma-separated string, or a native list)")
    return aid_list, None


def _build_sentinel():
    """构造垫底哨兵 case(框架延迟执行契约,见上)。show version=最通用无副作用只读占位。"""
    from main.case_compiler.case_ir import CaseIR, Row, Step
    return CaseIR(
        autoid=_SENTINEL_AUTOID, priority="P9", title="sentinel-do-not-execute",
        steps=[Step(stmt_type=2, description="sentinel",
                    rows=[Row(test_object="APV_0", method="cmd_config", data="show version")])],
    )


_PREFIX_TO_DOTTED = {"8": r"255\.0\.0\.0", "16": r"255\.255\.0\.0",
                     "24": r"255\.255\.255\.0", "32": r"255\.255\.255\.255"}


def _persistence_netmask_to_dotted(g: str) -> str:
    """断言里 sdns host persistence 的 ipv4 掩码字段 prefix→点分（correct-by-construction）。

    `show sdns host persistence` 回显把掩码显示成**点分 netmask**(255.255.255.0)，不是配置时的
    prefix(24)。断言(check_point G)若写 prefix `"24"` 必与 show 输出不匹配、断言 fail（实证 zhaiyq
    netmask 类 fail）。这里把 persistence 断言里 host 之后那个 1-2 位数字掩码字段转成点分正则。
    只动断言、不动配置命令(配置用 prefix 合法)。
    """
    if "persistence" not in g:
        return g
    return _re_dev.sub(
        r'(persistence\s+\d+\s+"[^"]*"\s+)"(8|16|24|32)"',
        lambda m: m.group(1) + '"' + _PREFIX_TO_DOTTED.get(m.group(2), m.group(2)) + '"',
        g,
    )


def _steps_to_caseir(autoid: str, steps: list, *, title: str = ""):
    """把 [{E,F,G,H?,I?,desc?}, ...] 步骤列表转成一个 CaseIR。

    返回 (CaseIR, has_check_point) 或 (None, 错误字符串)。单 case 和合并多 case 共用,
    保证 stmt_type 递增/列语义/check_point 校验完全一致。
    """
    from main.case_compiler.case_ir import CaseIR, Row, Step

    ist_steps = []
    has_cp = False
    seen_vars: set[str] = set()   # 前序步骤捕获过的变量名(H/save_as)
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            return None, f"step[{i}] is not a dict"
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if not e or not f:
            return None, f"step[{i}] is missing E or F"
        # 归一化(correct-by-construction):test_env 步的 F=触发机主机名,框架按 getattr(env, F)
        # 精确分派且**不转小写**(实证 test_xlsx.py)。draft 偶尔写成混合大小写 → AttributeError、
        # 触发步骤不执行、无回显。这里强制降为小写(合法 test_env 主机名来自网络事实源,均为小写),
        # 保证可分派——不靠 prompt 自觉。
        if e == "test_env":
            f = f.lower()
        g_val = str(s.get("G", "") or "")
        h_val = s.get("H") or None
        i_val = str(s.get("I")) if s.get("I") is not None else None
        # 归一化(correct-by-construction):check_point 引用捕获变量若误放 G 列(字面)→自动移到 H 列(寄存器查找)。
        # draft 常把"比对 v1"写成 G="v1"(框架按字面找串"v1",IP 输出里没有→上机必 fail);
        # 只有 H 列(row[7])才被 test_xlsx 当寄存器 locals[v1] 取捕获值。仅当 G 恰是前序捕获过的变量名才移,安全。
        if e == "check_point" and not h_val and g_val in seen_vars:
            h_val, g_val = g_val, ""
        if e == "check_point":
            has_cp = True
            # 捕获比较归一化(correct-by-construction):check_point 引用 H 寄存器作期望值时,
            # found → abs_found。框架 found() 把 expect 当**正则**(re.compile(expect));而捕获值是
            # dig 整段输出,含 +short 的 `+`、IP 的 `.`、`@` 等正则元字符 → 连自匹配都 fail
            # (实证 re.search(v1, v1)=False、re.search(re.escape(v1), v1)=True)。abs_found() 用
            # re.escape(expect) **字面**匹配,捕获比较"同值"才判得对。not_found 不转(无 abs_not_found)。
            if h_val and f == "found":
                f = "abs_found"
            # persistence 断言掩码 prefix→点分(匹配 show 回显);只动断言不动配置
            if g_val and "persistence" in g_val:
                g_val = _persistence_netmask_to_dotted(g_val)
        elif h_val:  # 非 check_point 的 H = 把本步输出捕获进变量,登记供后续 check_point 引用
            seen_vars.add(str(h_val))
        row = Row(test_object=e, method=f, data=g_val,
                  save_as=h_val,
                  input_var=i_val)
        ist_steps.append(Step(stmt_type=2 + i, description=str(s.get("desc", "") or ""),
                              rows=[row]))
    if not has_cp:
        return None, (f"case {autoid} has no check_point step at all — it is bound to fail "
                      f"on-device (pass requires success>0). Add a found assertion.")
    case = CaseIR(autoid=autoid, priority="P1",
                  title=(title or f"agent_{autoid}"), steps=ist_steps)
    return case, has_cp


def _gate_unreachable_ips(autoid: str, steps: list, init: str = "") -> str | None:
    """可达性校验门(事实源白名单投影):配置类步骤的 G 列 + init 里的 IP 必须落在拓扑可达集。

    病根:draft 凭空写 1.1.1.1/2.2.2.2 等示例 IP 当 service IP→设备不可达→dig 失败→断言全 fail。
    这里在 emit 出口兜底:发现不可达 IP 直接打回,并把"可达集合是什么"原样告诉 draft 让它重写
    (供给+校验,不做事后猜测映射——契约,非死字典)。

    只校验**配置类**(APV_0 的 cmd_config/cmds_config)与 init 的 G;check_point 的期望文本里
    可能有正则/IP 片段不在此列(那是断言匹配目标,不是要连接的设备),不拦。
    """
    from main.ist_core.tools._shared.env_facts import get_env_facts

    # 消融实验 Arm-E(基线裸生成):跳过可达性校验门(E 段),模拟无拓扑查表的自由生成。
    # 生产默认 Arm-L 不进此分支。
    from main.ist_core.tools._shared.ablation import is_baseline
    if is_baseline():
        return None

    facts = get_env_facts()
    if not facts.devices:  # JSON 缺失 → 宽松降级,不拦(与 ssh.py 一致)
        return None

    bad: list[str] = []
    texts: list[str] = []
    if init:
        texts.append(init)
    for s in steps:
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        # 只校验被测设备的配置步骤(要真连/真生效的);test_env 触发(dig 目标)同样需可达
        if e.startswith("APV") and f in ("cmd_config", "cmds_config"):
            texts.append(str(s.get("G", "") or ""))
        elif e == "test_env":
            texts.append(str(s.get("G", "") or ""))
    for t in texts:
        for ip in facts.unreachable_ipv4s(t):
            if ip not in bad:
                bad.append(ip)
    if not bad:
        return None
    return (f"case {autoid} uses {len(bad)} **environment-unreachable IP(s)**: {', '.join(bad)}\n"
            f"These IPs are not in any subnet of this testbed; on-device dig/connections are bound to fail (Hit=0, all assertions fail).\n"
            f"Rewrite with real reachable IPs — use real server IPs for backend service/pool, and unused in-segment IPs for VIP/listener:\n\n"
            f"{facts.summary_for_agent()}")


import re as _re_dev
# 设备生命周期类破坏性命令:重启/重载/关机。命令词匹配(词边界),不碰 clear/config(持久化范式要用)。
_DESTRUCTIVE_RE = _re_dev.compile(r"\b(reboot|reload|shutdown|halt|poweroff)\b", _re_dev.IGNORECASE)


def _gate_destructive_commands(autoid: str, steps: list, init: str = "") -> str | None:
    """安全门:拒绝 system reboot/reload/shutdown 等**破坏性设备生命周期命令**。

    两条理由(都与意图无关、确定性可判):
    1. 共享设备:上机 verify 跑到 `system reboot` 会真把别人在用的 APV 重启/关机;
    2. 框架不支持:apv_ssh 单连接、read_until 5s、无重连——重启后必在死通道上读空 → 必 fail。

    持久化/配置保存类用例**不该真重启**:用 clear→恢复→show 范式(write → clear sdns all →
    config memory/file/all/net 从存盘恢复 → show → 断言),先例 log_backup 已验证。
    本门只拦设备生命周期命令,**不碰** clear/config(范式本身要用)。
    """
    bad: list[tuple[int, str]] = []

    def _scan(text: str, idx: int) -> None:
        for line in (text or "").splitlines():
            line = line.strip()
            if line and _DESTRUCTIVE_RE.search(line):
                bad.append((idx, line))

    _scan(init, -1)
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if e.startswith("APV") and f in ("cmd_config", "cmds_config"):
            _scan(str(s.get("G", "") or ""), i)
    if not bad:
        return None
    lines = "; ".join(f"step[{i}]={cmd!r}" for i, cmd in bad)
    return (f"case {autoid} contains {len(bad)} **destructive device-lifecycle command(s)**: {lines}\n"
            f"Forbidden: this would really reboot/shut down a shared device, and the framework cannot reconnect after a reboot (bound to fail).\n"
            f"If the intent is to test \"config save/persistence\", use the no-reboot clear→restore paradigm:\n"
            f"  configure → write memory (or write file/all/net to save) → clear sdns all (clear running config)\n"
            f"  → config memory (or config file/all/net to restore from storage) → show → assert whether the config is present.\n"
            f"Precedent: smoke_test/sdns/log_backup (verified save→clear→restore→assert pattern).")


_SAVE_RE = _re_dev.compile(r"\bwrite\s+(memory|mem|file|all|net)\b", _re_dev.IGNORECASE)
# clear/show 前缀排除:`clear config file X` 是删除保存文件(清理写)、`show config …`
# 是只读,都不是恢复动作——run13 实证:worker 把 `clear config file` 放进 init 防残留,
# 被误判 restore 触发 P0b/P1a 双报错,worker 被迫绕门直改 xlsx → 凭证过期 → merge 拒
_RESTORE_RE = _re_dev.compile(r"(?<!clear\s)(?<!show\s)\bconfig\s+(memory|file|all|net)\b",
                              _re_dev.IGNORECASE)
_LISTENER_CFG_RE = _re_dev.compile(r"^sdns\s+listener\s+\S", _re_dev.IGNORECASE)  # 配置形态(show/no 不算)
_CLEAR_RE = _re_dev.compile(r"\b(no\s+sdns\s+listener|clear\s+sdns)\b", _re_dev.IGNORECASE)
_SAVE_REMOTE = ("file", "all", "net")  # 这些保存/恢复变体需带参数(文件名/目标);memory 无参合法


def _norm_family(tok: str) -> str:
    t = tok.lower()
    return "memory" if t in ("memory", "mem") else t


def _save_family(cmd: str) -> str | None:
    m = _SAVE_RE.search(cmd)
    return _norm_family(m.group(1)) if m else None


def _restore_family(cmd: str) -> str | None:
    m = _RESTORE_RE.search(cmd)
    return m.group(1).lower() if m else None


def _ordered_apv_cmds(steps: list, init: str) -> list[str]:
    """按执行顺序的 APV 配置命令行(init 基线在前,再各步骤 G 行)。"""
    out: list[str] = []
    for line in (init or "").splitlines():
        line = line.strip()
        if line:
            out.append(line)
    for s in steps:
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if e.startswith("APV") and f in ("cmd_config", "cmds_config"):
            for line in str(s.get("G", "") or "").splitlines():
                line = line.strip()
                if line:
                    out.append(line)
    return out


def _param_tail(cmd: str, fam: str) -> str:
    """取 write/config <file|all|net> 命令在族词之后的参数尾(判断是否缺参)。"""
    m = _re_dev.search(rf"\b(?:write|config)\s+{fam}\b(.*)$", cmd, _re_dev.IGNORECASE)
    return (m.group(1).strip() if m else "")


def _gate_save_restore_pairing(autoid: str, steps: list, init: str = "",
                               expected_save_variant: str = "") -> str | None:
    """持久化测试结构门(按执行顺序的有限状态校验,论文 correct-by-construction)。

    **仅在 case 含 config 恢复命令(memory/file/all/net)时触发**——即"配置保存/持久化"类用例。
    无恢复命令的用例(listener/forward/rr/pool 等 99%)直接 no-op,行为零变化(零回归)。

    校验(都与意图无关、确定性可判):
    - P0a 基线污染:首个 listener 配置之前不得有 write 保存(否则 config 恢复的是配 listener
      之前的旧快照→not_found 假通过,668015 类);
    - P0b 紧邻配对:每个 config X 须配对其**前最近**的 write Y 且同族(不是无序集合成员);
    - P1a 清除步:配 listener 与 config 恢复之间须有 no sdns listener / clear sdns(否则恢复
      空操作、not_found 永真、测试空转,668015/044 类);
    - P1b 参数完整:file/all/net 保存/恢复变体须带参数(裸 write net 设备拒,668044 类);
    - P1c 意图变体:被 config 配对的那个 save 变体须 == manifest 透传的 expected_save_variant
      (防 draft 偷换 write all→write memory,668030 类)。**缺 expected 则 no-op 放行**(防误拒)。

    write↔config 对称命令对(memory/file/all/net 各恢复各的存储,手册4015-4049);先例 log_backup。
    """
    cmds = _ordered_apv_cmds(steps, init)
    restores = [(i, c, _restore_family(c)) for i, c in enumerate(cmds) if _restore_family(c)]
    if not restores:
        return None  # ★ 回归护栏:非恢复类用例不进闸

    errs: list[str] = []
    first_listener = next((i for i, c in enumerate(cmds) if _LISTENER_CFG_RE.search(c)), None)

    # P0a 基线污染
    if first_listener is not None:
        for c in cmds[:first_listener]:
            if _save_family(c):
                errs.append(f"baseline pollution: save command {c!r} appears before the listener is "
                            f"configured — config would restore the old snapshot taken before the "
                            f"listener config, and not_found passes falsely. Delete it (the baseline "
                            f"should not be pre-saved).")
                break

    # P0b 紧邻配对
    last_save = None
    for c in cmds:
        sf = _save_family(c)
        if sf:
            last_save = sf
        rf = _restore_family(c)
        if rf:
            if last_save is None:
                errs.append(f"restore config {rf} has no preceding write save command "
                            f"(restoring a storage that was never saved).")
            elif last_save != rf:
                errs.append(f"restore config {rf} and its nearest preceding save write {last_save} are "
                            f"of different families — it does not read the copy just saved. Change it "
                            f"to config {last_save}, or change the save to write {rf} (the two must be "
                            f"the same family).")

    # P1a 清除步(配 listener 与首个恢复之间)
    first_restore_idx = restores[0][0]
    lo = first_listener if first_listener is not None else 0
    if not any(_CLEAR_RE.search(c) for c in cmds[lo:first_restore_idx]):
        errs.append("missing clear step: there is no no sdns listener / clear sdns between the "
                    "listener config and the config restore — the restore becomes a no-op, "
                    "not_found is always true, and the test idles. Add a clear step after the "
                    "save and before the restore.")

    # P1b 参数完整(file/all/net 变体)
    for c in cmds:
        fam = _save_family(c) or _restore_family(c)
        if fam in _SAVE_REMOTE and not _param_tail(c, fam):
            verb = "write" if _save_family(c) else "config"
            errs.append(f"command missing argument: {c!r} — the {fam} variant needs an argument "
                        f"(like {verb} {fam} <filename/target>); complete it per the manual "
                        f"cli_*_Chapter*.md + cli_*_Appendix*.md, the device rejects the bare command.")

    # P1c 意图变体(manifest 透传;缺失 no-op)
    if expected_save_variant:
        ev = _norm_family(expected_save_variant.strip())
        used = None
        ls = None
        for c in cmds:
            sf = _save_family(c)
            if sf:
                ls = sf
            if _restore_family(c):
                used = ls
                break
        if used and used != ev:
            errs.append(f"intent variant mismatch: this case should test persistence of write {ev}, "
                        f"but the save actually used write {used} (the intent got swapped and this "
                        f"duplicates another variant). Change the save back to write {ev} and "
                        f"restore with config {ev}.")

    if not errs:
        return None
    body = "\n".join(f"  - {e}" for e in errs)
    return (f"case {autoid} persistence test (config-restore class) structural errors:\n{body}\n"
            f"Correct paradigm: configure listener → show/found → write <intent variant> → "
            f"no/clear listener → config <same variant> → show → assert. "
            f"See precedent smoke_test/sdns/log_backup.")


def _gate_unreachable_listener(autoid: str, steps: list, init: str = "") -> str | None:
    """触发可达性门:listener/VIP 及 dig/curl 目标 IP 不能落在「触发够不着」的 APV 接口段。

    病根(655233 类):listener 配在 APV 的纯管理/纯后端段接口,
    该网段没有路由器/客户端,dig/curl 源够不着 → 上机 NXDOMAIN/无应答、断言全 fail。
    与意图无关、确定性可判(IP 是否在「触发同段」是拓扑客观事实),且对 dig/curl/任意触发
    通用——不针对具体命令。env_facts 派生,零硬编码 IP。
    """
    from main.ist_core.tools._shared.env_facts import get_env_facts
    from main.ist_core.tools._shared.ablation import is_baseline
    if is_baseline():
        return None
    facts = get_env_facts()
    if not facts.devices:
        return None
    import re as _re
    _ip_re = _re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
    # --- denylist(原逻辑):已知 APV 接口 IP 落「触发够不着」段(listener/VIP/dig/curl 都查)---
    blind = set(facts.unreachable_lb_ips())
    texts: list[str] = []
    if init:
        texts.append(init)
    for s in steps:
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if (e.startswith("APV") and f in ("cmd_config", "cmds_config")) or e == "test_env":
            texts.append(str(s.get("G", "") or ""))
    hit: list[str] = []
    if blind:
        for t in texts:
            for m in _ip_re.finditer(t):
                ip = m.group(1)
                if ip in blind and ip not in hit:
                    hit.append(ip)
    # --- allowlist(C 兜底):test_env 的 dig/curl 目标(@IP 或 ://IP)必须 ∈ ★ listener ∪ 后端 service。
    # 治"凭空编的、落可达子网但非任何真实接口 IP"——denylist 抓不到(它不是已知接口)。
    # 仅当拓扑能派生 ★ 时启用(空 ★ → 降级放行,不误杀);只查 dig/curl 的目标 IP(@/://后),不查命令里其它 IP。
    allow = set(facts.listener_ips()) | set(facts.service_ips())
    _tgt_re = _re.compile(r"@(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})|://(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
    bad_target: list[str] = []
    if facts.listener_ips():
        for s in steps:
            if not isinstance(s, dict) or str(s.get("E", "")).strip() != "test_env":
                continue
            for m in _tgt_re.finditer(str(s.get("G", "") or "")):
                ip = m.group(1) or m.group(2)
                if ip and ip not in allow and ip not in bad_target:
                    bad_target.append(ip)
    if not hit and not bad_target:
        return None
    listener = facts.listener_ips()
    lines = [f"case {autoid} trigger reachability is illegal:"]
    if hit:
        lines.append(f"- listener/VIP or dig/curl target falls in an APV interface segment the trigger hosts cannot reach: {', '.join(hit)}")
    if bad_target:
        lines.append(f"- dig/curl target IP is not a ★ reachable listener of the testbed (nor a known backend): {', '.join(bad_target)} (most likely made up)")
    lines.append(f"dig/curl targets must use a ★ reachable listener IP (consistent with the configured listener): {', '.join(listener)}")
    return "\n".join(lines) + "\n\n" + facts.summary_for_agent()



# 反馈文案 2026-07-09 英文化(LLM-facing 语言分层),英文 pattern 与原中文并列保序——
# 分类判定语义不变(中文 pattern 保留兼容历史串)。
_EMIT_REASON_PATTERNS = (
    ("组合子无效", "blocks_invalid"),
    ("invalid blocks combinator", "blocks_invalid"),
    ("provenance 解析失败", "prov_parse"),
    ("provenance parse failed", "prov_parse"),
    ("provenance steps 数", "prov_shape"),
    ("必传 provenance", "prov_missing"),
    ("G 列为 None", "payload_empty"),
    ("column G is None", "payload_empty"),
    ("解析失败", "parse"),
    ("parse failed", "parse"),
    ("违反结构约束", "structural"),
    ("violates structural constraints", "structural"),
    ("违反用户决策", "user_decision"),
    ("violates user decision", "user_decision"),
    ("frozen", "frozen"),
    ("冻结", "frozen"),
    ("lint", "lint"),
)


def _verify_command_evidence(evidence: str, missing_cmds: list[str]) -> tuple[bool, str]:
    """机械核验存在性证据。两种形态:
    ① `<file>.md:<line>`(可多个,逗号/空格分隔)——该行 ±3 行内须含对应命令前两个
      词(每条 miss 至少被一个引用覆盖);② `dev_help: <一句>`——设备 `?`/`^` 实测
    声明,按 attestation 接受并记信号(离线无法复核,如实标注)。"""
    ev = (evidence or "").strip()
    if ev.lower().startswith("dev_help:"):
        return True, f"device attestation accepted: {ev[:120]}"
    refs = [r for r in re.split(r"[,\s]+", ev) if ":" in r and ".md" in r]
    if not refs:
        return False, "evidence must be `<file>.md:<line>` (manual line ref) or `dev_help: <one line>`"
    root = Path(__file__).resolve().parents[4]
    from main.case_compiler.command_inventory import load_inventory
    inv = load_inventory() or {}
    src_dir = root / str(inv.get("source_dir", "knowledge/data/markdown/product"))
    windows: list[str] = []
    for r in refs:
        fname, _, lno = r.rpartition(":")
        try:
            lines = (src_dir / Path(fname).name).read_text(encoding="utf-8").splitlines()
            n = int(lno)
            windows.append("\n".join(lines[max(0, n - 4):n + 3]).lower())
        except Exception:  # noqa: BLE001
            return False, f"evidence ref unreadable: {r}"
    for cmd in missing_cmds:
        toks = re.sub(r"\s+", " ", cmd.strip().lower()).split(" ")[:2]
        if not any(all(t in w for t in toks) for w in windows):
            return False, (f"evidence does not cover command {cmd!r} — the referenced line "
                           "vicinity must actually contain its leading words")
    return True, f"manual line evidence verified for {len(missing_cmds)} command(s)"


def _gate_command_existence(autoid: str, steps: list, init: str = "",
                            evidence: str = "") -> str | None:
    """S6 命令存在性呈报门(理论 (33) 版本参数化;DESIGN §15-S6/§16.2-F 片1)。

    「测本版本不存在的功能」在 v8 曾烧 3 编写轮+多次上机+1 个封顶面板才到人
    (668059 fulldns,10.5 专属手册零记载而设备 585 拒绝=行为正确、记载互斥)。
    本门在 emit 期做版本命令集成员判定,未命中**呈报不硬拒**(D5):写 needs_decision
    台账(问询节点消费)+拒落卷面与凭证,给 worker 两条出路——行级证据重 emit
    (手册记载有 MinerU 截断上限,合法命令可能查无记载),或尾块 NEEDS_USER_DECISION。
    误报校准:48 个真机 PASS 卷 865 条命令误报 0、唯一 MISS=fulldns(2026-07-12)。"""
    if os.getenv("IST_COMMAND_EXISTENCE_GATE", "1") == "0":
        return None
    try:
        from main.case_compiler.command_inventory import (load_inventory, match_command,
                                                          nearest_heads)
    except Exception:  # noqa: BLE001
        return None
    inv = load_inventory()
    if inv is None:
        return None  # 清单不可用:fail-open,如实不判
    seen: set[str] = set()
    misses: list[tuple[str, list[str]]] = []
    for cmd in _ordered_apv_cmds(steps, init):
        if cmd in seen:
            continue
        seen.add(cmd)
        r = match_command(cmd)
        if r["decided"] and not r["hit"]:
            misses.append((cmd, nearest_heads(cmd)))
    if not misses:
        return None
    ver = str(inv.get("version", ""))
    stats = inv.get("stats") or {}
    # 逃生①:worker 携行级证据(机械核验)
    if (evidence or "").strip():
        ok, note = _verify_command_evidence(evidence, [c for c, _ in misses])
        if ok:
            try:
                from main.ist_core.memory.footprint.signals import emit_signal
                emit_signal("command_existence_evidence_accepted", autoid,
                            source="compile_emit", commands=[c for c, _ in misses],
                            evidence=evidence[:200])
            except Exception:  # noqa: BLE001
                pass
            # 剔除此前同命令落下的 stale claims——证据已坐实,别让过期题面
            # 在该案后续因他因进问询流时被带出(redline 评审建议②)
            try:
                root = Path(__file__).resolve().parents[4]
                ndp = root / "workspace" / "outputs" / (autoid or "").strip() / "needs_decision.json"
                if ndp.is_file():
                    _nd = json.loads(ndp.read_text(encoding="utf-8"))
                    _cl = [c for c in (_nd.get("claims") or [])
                           if not (c.get("claim_kind") == "command_existence"
                                   and c.get("command") in {m[0] for m in misses})]
                    if _cl != _nd.get("claims"):
                        if _cl:
                            _nd["claims"] = _cl
                            ndp.write_text(json.dumps(_nd, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
                        else:
                            ndp.unlink()
            except Exception:  # noqa: BLE001
                logger.debug("stale command_existence claims 清理失败", exc_info=True)
            return None
        return (f"error: command-existence evidence rejected — {note}. Commands still "
                f"unmatched: {[c for c, _ in misses]}.")
    # 逃生②:该案已有用户裁决(同键不复问,(20) 收敛律)
    try:
        root = Path(__file__).resolve().parents[4]
        outd = root / "workspace" / "outputs" / (autoid or "").strip()
        udp, ndp = outd / "user_decision.json", outd / "needs_decision.json"
        if udp.is_file() and ndp.is_file():
            _ud = json.loads(udp.read_text(encoding="utf-8"))
            _nd = json.loads(ndp.read_text(encoding="utf-8"))
            if (_ud.get("decision") in ("改过程", "改预期")
                    and any(c.get("claim_kind") == "command_existence"
                            for c in (_nd.get("claims") or []))):
                return None
    except Exception:  # noqa: BLE001
        logger.debug("command_existence 用户裁决检查失败(按未裁决)", exc_info=True)
    # 呈报:写 needs_decision 台账(问询节点按 questions.py 组题)+信号,拒落卷
    try:
        root = Path(__file__).resolve().parents[4]
        outd = root / "workspace" / "outputs" / (autoid or "").strip()
        outd.mkdir(parents=True, exist_ok=True)
        ndp = outd / "needs_decision.json"
        data: dict = {"autoid": (autoid or "").strip(), "claims": []}
        if ndp.is_file():
            try:
                loaded = json.loads(ndp.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("claims"), list):
                    data = loaded
            except Exception:  # noqa: BLE001
                pass
        old = [c for c in data["claims"]
               if not (c.get("claim_kind") == "command_existence"
                       and c.get("command") in {m[0] for m in misses})]
        for cmd, near in misses:
            old.append({
                "claim_kind": "command_existence", "command": cmd,
                "reason": (f"命令『{cmd}』在 {ver} 版本专属 CLI 手册命令集"
                           f"({stats.get('signatures', '?')} 签名,解析覆盖率 "
                           f"{stats.get('coverage_excl_noise', '?')})未命中;最近似记载:"
                           f"{('、'.join(near) if near else '无')}。已检索:"
                           f"{inv.get('source_dir', '')} 全分册。手册抽取有已知截断上限,"
                           "也可能该功能不属本版本(记载互斥类,fulldns 先例)"),
                "suggested_fix": "换用版本内存在的等价命令/形态,或确认功能不属本版本后挂起",
                "min_requests": 0, "ordering_sensitive": False,
            })
        data["claims"] = old
        ndp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("command_existence needs_decision 落盘失败", exc_info=True)
    try:
        from main.ist_core.memory.footprint.signals import emit_signal
        emit_signal("command_existence_miss", autoid, source="compile_emit",
                    commands=[c for c, _ in misses], version=ver)
    except Exception:  # noqa: BLE001
        pass
    lines = "\n".join(f"  - {c!r}  (nearest recorded: {', '.join(n) if n else 'none'})"
                      for c, n in misses)
    return ("error: command-existence gate — the following command(s) are not found in the "
            f"version-specific CLI manual command set for {ver} "
            f"({stats.get('signatures', '?')} signatures parsed, coverage "
            f"{stats.get('coverage_excl_noise', '?')}):\n{lines}\n"
            "This burned 3 authoring rounds + multiple device runs once (a feature absent "
            "from this build). Two exits:\n"
            "1) The command may genuinely exist (manual extraction has a truncation "
            "ceiling): verify via the device `?` syntax reflection (dev_probe) or locate "
            "the manual line, then re-emit with command_existence_evidence="
            "'<file>.md:<line>' or 'dev_help: <what you verified>'.\n"
            "2) If it truly does not exist on this build (or records conflict), the "
            "needs_decision ledger entry is already written — end your reply with "
            "状态：NEEDS_USER_DECISION and the engine will bring it to the user.")


def _gate_tau_coverage(autoid: str, steps: list, init: str = "") -> str | None:
    """G1 配对恢复门(V8.5 片5;理论锚 (39) 六元组 τ/(32) 复位差集;DESIGN §17-G1)。

    创建型 L2/L3 写(vlan/bond/ip address——框架 per-case 清理够不着的复位差集
    分量)无案内恢复步 → 呈报不硬拒:写 needs_decision(missing_teardown claim,
    携机械派生的逆元建议序列),拒落卷与凭证。实证:655203/233 两案六次拆床
    (run12),共同上游=卷面无 τ 且 L 无 teardown 槽位、门无物可检。
    逃生:①卷面补恢复步自然过 ②用户已裁决(同键不复问) ③IST_TAU_GATE=0。"""
    if os.getenv("IST_TAU_GATE", "1") == "0":
        return None
    try:
        from main.case_compiler.tau_coverage import check_tau_coverage
    except Exception:  # noqa: BLE001
        return None
    rep = check_tau_coverage(steps if isinstance(steps, list) else [], init)
    if rep.ok:
        return None
    # 逃生②:该案已有用户裁决(missing_teardown claim 已答)
    try:
        root = Path(__file__).resolve().parents[4]
        outd = root / "workspace" / "outputs" / (autoid or "").strip()
        udp, ndp = outd / "user_decision.json", outd / "needs_decision.json"
        if udp.is_file() and ndp.is_file():
            _ud = json.loads(udp.read_text(encoding="utf-8"))
            _nd = json.loads(ndp.read_text(encoding="utf-8"))
            if (_ud.get("decision") in ("改过程", "改预期")
                    and any(c.get("claim_kind") == "missing_teardown"
                            for c in (_nd.get("claims") or []))):
                return None
    except Exception:  # noqa: BLE001
        logger.debug("missing_teardown 用户裁决检查失败(按未裁决)", exc_info=True)
    # 呈报:needs_decision 台账+信号
    try:
        root = Path(__file__).resolve().parents[4]
        outd = root / "workspace" / "outputs" / (autoid or "").strip()
        outd.mkdir(parents=True, exist_ok=True)
        ndp = outd / "needs_decision.json"
        data: dict = {"autoid": (autoid or "").strip(), "claims": []}
        if ndp.is_file():
            try:
                loaded = json.loads(ndp.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("claims"), list):
                    data = loaded
            except Exception:  # noqa: BLE001
                pass
        data["claims"] = [c for c in data["claims"]
                          if c.get("claim_kind") != "missing_teardown"]
        inv_seq = [m["suggested_inverse"] for m in reversed(rep.missing)]
        data["claims"].append({
            "claim_kind": "missing_teardown",
            "commands": [m["cmd"] for m in rep.missing],
            "suggested_tau": inv_seq,
            "reason": (f"卷面有 {len(rep.missing)} 条网络层配置写(框架自动清理"
                       f"够不着的分量),但没有案尾恢复步——该类残留会污染同批后续"
                       f"用例(233/203 两案六次拆床实证)。机械派生的恢复序列:"
                       + "；".join(inv_seq)),
            "suggested_fix": "案尾追加恢复序列(逆序 no 回放),或确认该写是被测行为本身需保留",
            "min_requests": 0, "ordering_sensitive": False,
        })
        ndp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("missing_teardown needs_decision 落盘失败", exc_info=True)
    try:
        from main.ist_core.memory.footprint.signals import emit_signal
        emit_signal("missing_teardown", autoid, source="compile_emit",
                    commands=[m["cmd"] for m in rep.missing])
    except Exception:  # noqa: BLE001
        pass
    lines = "\n".join(f"  - {m['cmd']!r}  → suggested inverse: {m['suggested_inverse']!r}"
                      for m in rep.missing)
    return ("error: paired-teardown gate — this case writes network-layer config that the "
            "framework's per-case cleanup cannot reach, with no in-case restore step:\n"
            f"{lines}\n"
            "Leftovers of this kind poisoned the shared bed six times in one batch "
            "(measured: two cases repeatedly moved a listener IP onto a vlan/empty bond, "
            "killing every downstream case). Two exits:\n"
            "1) Append the restore steps at the end of the case (reverse-order `no` "
            "replay as suggested above; place them AFTER your assertions so they do not "
            "destroy what you are verifying), then re-emit.\n"
            "2) If the write itself IS the behavior under test and must persist, the "
            "needs_decision ledger entry is already written — end your reply with the "
            "NEEDS_USER_DECISION tail and the engine will bring it to the user.")


def _emit_stat(autoid: str, out: str, channel: str) -> None:
    """emit 出口台账(runtime/logs/emit_stats.jsonl)——打回率的机读事实源
    (E2 基线 48-52% 来自 fastlog 解析;此后量化门直接聚合本文件)。追加失败静默。"""
    try:
        import time as _t
        ok = not str(out).startswith("error:")
        reason = "ok"
        if not ok:
            reason = "other"
            for pat, cls in _EMIT_REASON_PATTERNS:
                if pat in out:
                    reason = cls
                    break
        rec = {"ts": _t.time(), "autoid": str(autoid), "ok": ok,
               "reason_class": reason, "channel": channel}
        if reason == "other":
            # 观测缺口修复(2026-07-06 诊断 P2):未分类打回带原文头,可追溯
            rec["error_head"] = str(out)[:80]
        p = Path(__file__).resolve().parents[4] / "runtime" / "logs" / "emit_stats.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        logger.debug("emit_stats 记账失败(忽略)", exc_info=True)


_ASSERT_METHODS = {"found", "not_found", "abs_found", "found_times"}


def _coverage_profile(rows: list[dict]) -> tuple[set, set]:
    """卷面观测覆盖档案：(观测动词类集, 观测命令中出现的 DNS 记录类型集)。

    单调门(理论 §2.4 守恒律的可判定投影)的比较基元——只看**观测维度**是否存在,
    不看断言文本(修法合法地改断言;非法的是把观测维度整个删掉)。
    行形状与 steps 入参 / _load_case_rows 回读同构({E,F,G,...}),两侧共用。
    """
    from main.case_compiler.observe_ops import observe_kind
    from main.case_compiler import domain_grammar as _dg
    kinds: set = set()
    types: set = set()
    try:
        rec_types = tuple(_dg.dns_record_types())
    except Exception:  # noqa: BLE001
        rec_types = ()
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("F") or "").strip().lower() in _ASSERT_METHODS:
            continue  # 断言行的 G 是 pattern,不是命令
        g = str(r.get("G") or "")
        for line in g.splitlines():
            k = observe_kind(line)
            if not k:
                continue
            kinds.add(k)
            if k != "behavior":
                continue  # 记录类型维度只在行为观测(dig 等)里有意义
            for t in rec_types:
                # 大小写敏感:记录类型惯例大写(dig … AAAA);小写匹配会误命中
                # 主机名里的独立字母(test-a.com 的 a 撞类型 A),新旧卷不对称时假拦
                if re.search(rf"(?<![A-Za-z0-9]){t}(?![A-Za-z0-9])", line):
                    types.add(t)
    return kinds, types


def _with_emit_stats(fn):
    import functools

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        out = fn(*args, **kwargs)
        try:
            _aid = kwargs.get("autoid") or (args[0] if args else "")
            if kwargs.get("blocks"):
                _ch = "blocks"
            elif isinstance(kwargs.get("steps"), list):
                _ch = "steps"
            elif (kwargs.get("steps_path") or "").strip():
                _ch = "steps_path"
            else:
                _ch = "json_string"
            _emit_stat(str(_aid), str(out), _ch)
        except Exception:  # noqa: BLE001
            pass
        return out
    return _wrapped


@tool(parse_docstring=True)
@_with_emit_stats
def compile_emit(autoid: str, steps_json: str = "", init_commands: str = "",
                 out_name: str = "", strict_structural: bool = False,
                 provenance_json: str = "", expected_save_variant: str = "",
                 steps: list | str | None = None, steps_path: str = "",
                 override_frozen_reason: str = "",
                 coverage_reduction_reason: str = "",
                 provenance: dict | list | str | None = None,
                 provenance_path: str = "",
                 blocks: list | str | None = None,
                 command_existence_evidence: str = "") -> str:
    """Produce a structurally correct case.xlsx from a step list (clones the framework-native template; you never deal with template structure/column alignment).

    **When to use**: the semantic design of a single case (config/trigger/assertions) is settled
    and you want to land it as a runnable xlsx.
    **When not to use**: merging multiple cases into one package → ``compile_emit_merged``; and
    don't emit before the assertion form / expected-value provenance is thought through — every
    version rejected by the structural gates burns a round for nothing.
    **Use this instead of hand-rolling openpyxl via run_python** — hand-rolled sheets always get
    the 27-row description area / C=0/C=1 / E-F-G column alignment wrong, so the framework skips
    your case rows (zero check_point, vacuously true pass). This tool guarantees a 100% legal
    structure.

    You only decide the **content**: file-level preconfig commands + each step's
    object/method/data. **Prefer the blocks combinator channel** (native array; the five
    combinator syntaxes are at the top of EXCEL_FUNCTIONS.md — read it before emitting) — you
    make only semantic decisions, and the low-level representation (capture three-step
    form/registers/column alignment) is expanded by the tool; shapes like dangling assertions
    cannot be written in the combinator language. Only fall back to the ``steps`` native-array
    channel (column semantics below) for corner shapes blocks cannot express.

    Column semantics (one dict per step):
    - ``E`` object to operate: device-under-test id / check_point (assertion) / test_env (test host) / time (wait)
    - ``F`` method: device→cmd_config (single) | cmds_config (multiple, \\n-separated);
      check_point→found (regex DOTALL) | not_found | abs_found (literal) | found_times (needs count in column I);
      test_env→a host name from the network facts source; time→sleep
    - ``G`` data (**data type = literal text / regex string — not a variable, not a Python expression, not a number**):
      config steps = raw CLI command text; check_point = the expected text/regex to **text-search** in the previous step's output.
      The framework matches G **verbatim** — write a variable name (e.g. init_ip) and it searches for the literal characters "init_ip", never found.
    - ``H`` save_as (optional) / ``I`` input_var (optional): capture + compare — store one observation output, later compare same/different
      (the correct form for session persistence/affinity/rotation). Full usage (the required three-step structure, why a step with H does not update result)
      is in the "H column" section of knowledge/data/compile_ref/EXCEL_FUNCTIONS.md.
    - ``desc`` (optional): step description

    check_point automatically checks **the output of the previous non-check_point step**, so an
    output-producing step (show/dig) must come before the assertion. Every case needs at least
    one check_point that will pass (otherwise it is bound to fail on-device).

    Args:
        autoid: case autoid for the first case row column A.
        steps_json: (compat channel) JSON array string. **Prefer the ``steps`` native array** —
            vendor function-calling serialization leaves trailing garbage after long string
            arguments (measured 73% parse failures in a single round); the array channel has
            no such exposure.
        blocks: **Top priority.** Native array of semantic combinators, 5 kinds — CONFIG (cmds command list, one command per element) / OBSERVE_ASSERT (host+cmd+asserts assertion list, op one of found, not_found, abs_found) / CAPTURE_COMPARE (host+capture_cmd+relation one of same or differs, registers auto-allocated) / OBSERVE_ONLY (host+cmd) / SLEEP (seconds). You make only semantic decisions; the capture-compare three-step form, registers, and E-F-H columns are expanded by the tool — dangling assertions, literal backslash-n and undefined registers cannot be written in this language. With blocks, provenance is one-to-one at combinator granularity (equal counts); expansion is synchronized by the tool.
        steps: Fallback. Native array of step dicts (not a JSON string), each with E/F/G and optional H/I/desc; use only for shapes blocks cannot express.
        steps_path: Fallback file channel. Path to a JSON file inside workspace (e.g.
            workspace/outputs/<autoid>/steps.json, content is the steps array — only the
            outputs/ subdir of workspace is writable); when the steps array repeatedly gets
            trailing garbage / grows too long, fs_write the file first and pass its path to
            bypass argument serialization.
        override_frozen_reason: Required when the case is frozen by cross-round on-device
            comparison (two consecutive rounds failed with the same signature = the same
            approach is proven ineffective) — one sentence on what you changed this time
            (which kind of assertion/config/trigger). Without it, re-emitting is refused;
            this is not a formality — it prevents slamming the exact same write-up into
            another round.
        command_existence_evidence: Only needed when the command-existence gate reported
            commands missing from the version-specific CLI manual command set. Give either
            a manual line reference (file name and line number joined by a colon; exact
            format is shown in the gate message) whose vicinity must actually contain the
            command words (mechanically verified), or a ``dev_help`` attestation that you
            verified the syntax on the device via the ``?`` reflection. The manual
            extraction has a known truncation ceiling, so a genuinely existing command can
            be unrecorded — verify first, then re-emit with evidence. If the command truly
            does not exist on this build (or records conflict), end your reply with the
            NEEDS_USER_DECISION tail instead — the ledger entry is already written.
        coverage_reduction_reason: Required only when a **recompile** removes an observation
            dimension the previous volume had (an observation-verb class or a DNS record type
            that appeared in the old volume's observe commands but not in the new one).
            Fixing a failing case must not silently shrink what it observes — a measured
            failure mode is deleting the assertion that fails (e.g. dropping the AAAA probe
            when the intent says "A or AAAA"), which turns a real failure into a fake PASS.
            If the reduction is genuinely intended (e.g. the user re-scoped the case), state
            in one sentence which dimension you dropped and why; the gate then lets it
            through and records the declaration.
        init_commands: file-level preconfig (C=1) commands, newline separated; empty uses project default.
        out_name: output subdir under workspace/outputs; empty uses autoid.
        strict_structural: set True on the v2 compile chain to enable the structural constraint
            gate (commands ∈ manual allowlist + non-dangling assertions,
            correct-by-construction); v1 default False keeps behavior unchanged. Structural
            violations are rejected with reasons.
        provenance: Preferred native-object channel, required. Three-layer Provenance IR (dict with a steps array, each step tagged layer one of G/E/V, source with kind and ref) — it is the sole basis for approval without re-retrieval, four-layer on-device attribution, and PASS write-back to the knowledge base; missing means the output is refused. The string channel is measured to fail from serialization trailing garbage; the object channel has no such exposure.
        provenance_json: compat channel, same as above but a JSON string; prefer provenance.
        provenance_path: fallback file channel (path to a JSON file inside workspace, e.g.
            workspace/outputs/<autoid>/prov.json). When the native provenance object keeps
            getting swallowed/nulled by the vendor, fs_write the file first and pass its path.
        expected_save_variant: pass only for config-save/persistence cases (memory|file|all|net).
            If the mindmap says "after running write all ...", pass "all". The persistence gate
            uses it to verify your save command's family was not swapped (write all must not
            become write memory). Leave empty for non-persistence cases.

    Returns:
        Output path + round-trip row stats. Compilation ends here; on-device verification is
        triggered by the separate ist-verify flow.
    """
    autoid = (autoid or "").strip()
    if not autoid:
        return "error: autoid is required"
    # autoid 短号格式门(A 层机械):需求系统 autoid 为 18 位数字(20303…);纯数字却不足 15 位
    # 必是完整号的尾段缩写(实证 deepseek 重编把 brief 里的短号 778012 原样烧进 xlsx ID 列 →
    # 需求关联/框架报告 ID 断链)。非纯数字 id(测试/特殊场景)不受限——宁漏勿杀。
    if autoid.isdigit() and len(autoid) < 15:
        return (f"error: autoid '{autoid}' looks like a truncated short id (all digits but fewer "
                f"than 15). Pass the full requirements-system autoid (18 digits, e.g. "
                f"203031753342778012) — a short id baked into the xlsx breaks requirement "
                f"linkage and framework-report ID chains.")
    # 组合子通道(V4 步骤2,最优先):worker 只做语义决策,展开器保证底层表示——
    # 悬空断言/未定义寄存器/带H步后直接断言/字面\n 在组合子语言下不可表达
    # (实证:34 已验证卷反解 5 组合子 round-trip 33/34 字节级等价,唯一失败卷=上机 fail 卷)。
    # 展开产物仍走下游全部机械门作自检(应零触发,触发=展开器 bug)。
    if blocks not in (None, "", []):
        # 双收字符串(2026-07-11 yzg 实测:26 案 worker 首发多数把组合子数组序列化成
        # JSON 字符串,被参数校验层整调拒绝、每案多烧 1-2 往返——steps 通道同款兜底)
        if isinstance(blocks, str):
            try:
                blocks = json.loads(blocks)
            except Exception:  # noqa: BLE001
                return (f"error: case {autoid} blocks arrived as an unparseable string — pass a "
                        "native array of combinator objects (preferred), or a valid JSON-encoded "
                        "array string")
        if not isinstance(blocks, list):
            return (f"error: case {autoid} blocks must be a native array (a list of semantic "
                    "combinators), got " + type(blocks).__name__)
        from main.case_compiler.blocks import expand_blocks
        _prov_steps = None
        _prov_obj: dict | None = None
        if provenance is not None and isinstance(provenance, dict):
            _prov_obj = dict(provenance)
            _prov_steps = _prov_obj.get("steps")
        elif provenance_json and str(provenance_json).strip():
            try:
                _pj0 = json.loads(str(provenance_json))
                if isinstance(_pj0, dict):
                    _prov_obj = _pj0
                    _prov_steps = _pj0.get("steps")
            except Exception:  # noqa: BLE001
                return (f"error: case {autoid} in blocks mode provenance_json parse failed — "
                        "pass the native provenance object instead (steps count equal to blocks "
                        "count, one entry per combinator).")
        _bsteps, _bprov, _berr = expand_blocks(blocks, _prov_steps)
        if _berr:
            return f"error: case {autoid} invalid blocks combinator — {_berr}"
        steps = _bsteps
        if _prov_obj is not None and _bprov is not None:
            _prov_obj["steps"] = _bprov
            provenance = _prov_obj
            provenance_json = ""
        elif _prov_obj is None and _bprov and (
                os.environ.get("IST_PROV_AUTOASSEMBLE") or "1").strip().lower() not in ("0", "false", "no"):
            # 自动组装(V6 支柱3):worker 未传 provenance 时,用展开器按 block 的
            # ref/cmd_ref/asserts[].ref 机械组装的 steps 直接成 IR——"LLM 拼 JSON+
            # 门打回"的形态税(E2 实证打回率 48-52% 的主体)在构造上消失。
            # 显式 provenance 仍最优先;IST_PROV_AUTOASSEMBLE=0 回旧行为(必传门)。
            provenance = {"autoid": autoid, "steps": _bprov}
            provenance_json = ""

    # 步骤载荷三通道,优先级 steps(原生数组)> steps_path(workspace 文件)> steps_json(字符串,兼容)。
    # 原生数组没有"长字符串参数拖尾"的暴露面(2026-07-02 实证字符串通道单轮 73% 解析失败);
    # 供应商仍可能把数组 stringify(mimo 实证),故 steps 收到 str 也双收。
    _payload: list | None = None
    _src = ""
    if steps not in (None, []):
        if isinstance(steps, list):
            _payload = list(steps)
        else:
            _src = str(steps)
    elif (steps_path or "").strip():
        sp = (steps_path or "").strip()
        root = Path(__file__).resolve().parents[4]
        p = Path(sp) if sp.startswith("/") else (root / sp)
        try:
            p = p.resolve()
            ws = (root / "workspace").resolve()
            if not p.is_relative_to(ws):
                return f"error: steps_path must be inside workspace/: {sp}"
            if not p.is_file():
                return f"error: steps_path file does not exist: {sp} (fs_write the file first, then pass its path)"
            _src = p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return f"error: steps_path read failed: {e}"
    else:
        if isinstance(steps_json, list):
            _payload = steps_json
        else:
            _src = steps_json if isinstance(steps_json, str) else str(steps_json or "")
    if _payload is None:
        if not (_src or "").strip():
            # 空载荷同样计连败(2026-07-05 v12 实证:供应商间歇性把整个数组参数吞掉,
            # 211027 空载荷原样重试 30+ 次——旧版只有 steps_json 解析分支有连败升级,
            # 这个分支直接 return,worker 在同一堵墙上撞到 fork 预算耗尽)。
            _streak = _emit_fail_streak_bump(autoid)
            _msg = (f"error: case {autoid} step payload is empty — none of the four channels "
                    "blocks/steps/steps_path/steps_json carried valid content (your array "
                    "argument may have been dropped entirely by vendor serialization). Prefer "
                    "blocks semantic combinators (native array); use the steps native array "
                    "for shapes blocks cannot express.")
            if _streak >= 2:
                _msg += ("\n→ Consecutive empty payloads: do not retry as-is. First fs_write "
                         f"the steps array to workspace/outputs/{autoid}/steps.json, then pass "
                         "steps_path=that path — the file channel bypasses argument "
                         "serialization and cannot be swallowed.")
            if _streak >= 3:
                _msg += (f"\n⚠ {_streak} consecutive empty payloads. If steps_path also fails "
                         "to get through, stop retrying and copy this error verbatim into your "
                         "reply for the orchestrator to re-dispatch.")
            return _msg
        try:
            _payload = json.loads(_src)
        except Exception as e:  # noqa: BLE001
            # 回显收到参数的首尾片段(repr 让不可见字符现形):解析失败的常见根因是
            # LLM 供应商在 tool_call 长字符串参数后拖尾(实证 JSON 闭合后跟 2-11 字符
            # 意图词如 ]push / ]doublecheck);报错只给 char 位置时 worker 看不到自己
            # 实际传了什么,反复换姿势重试全部无效。首尾片段让 worker 对症改,
            # 并引导切换 steps 原生数组或 steps_path 文件通道。
            head = repr(_src[:120])
            tail = repr(_src[-120:]) if len(_src) > 240 else ""
            streak = _emit_fail_streak_bump(autoid)
            msg = (f"error: steps_json parse failed: {e}\n"
                   f"argument actually received (len={len(_src)}) head: {head}"
                   + (f"\ntail: {tail}" if tail else ""))
            if streak >= 2:
                msg += ("\n→ Switch channel: pass steps as a native array (not a JSON string), "
                        "or first fs_write the steps array to "
                        "workspace/outputs/<autoid>/steps.json and pass steps_path (only "
                        "outputs/ under workspace is writable) — neither has the "
                        "trailing-garbage exposure of the string channel.")
            if streak >= 3:
                msg += (f"\n⚠ This case has failed parsing {streak} times in a row — stop "
                        "retrying as-is; if switching channels still fails, stop and copy this "
                        "error verbatim into your reply for the orchestrator to handle.")
            return msg
    if not isinstance(_payload, list) or not _payload:
        return "error: steps must be a non-empty array (each element a dict with E/F/G)"
    _emit_fail_streak_clear(autoid)
    steps = _payload

    # 冻结闸门(A 层):digest 跨轮对照发现连续两轮同签名 fail 时在 outputs/<autoid>/ 落
    # .frozen.json——同法已证无效。重编必须显式声明换法(override_frozen_reason),
    # 文本止损指引曾被实证绕过(直接 ad-hoc 重编),此门把「是否换法」变成必答题;
    # 声明后记入冻结历史并放行(换法自由保留)。
    try:
        _fz_path = Path(__file__).resolve().parents[4] / "workspace" / "outputs" / autoid / ".frozen.json"
        if _fz_path.is_file():
            _ov = (override_frozen_reason or "").strip()
            if not _ov:
                _fz = {}
                try:
                    _fz = json.loads(_fz_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
                _sig = " | ".join((_fz.get("signatures") or [])[:2])
                return (f"error: case {autoid} is frozen by cross-round on-device comparison "
                        "(two consecutive rounds failed with the same signature — the same "
                        "approach is proven ineffective"
                        + (f"; signatures: {_sig}" if _sig else "") +
                        "). Re-emitting requires override_frozen_reason = one sentence on what "
                        "you changed this time (which kind of assertion/config/trigger); if you "
                        "judge it an environment blockage, verify the environment per "
                        "ist-verify's stop-loss guidance first — do not slam into it again "
                        "unchanged.")
            try:
                _fz = json.loads(_fz_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _fz = {}
            _hist = _fz.get("overrides") or []
            import time as _t1
            _hist.append({"reason": _ov, "ts": _t1.time()})
            _fz["overrides"] = _hist
            _fz_path.write_text(json.dumps(_fz, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                from main.ist_core.memory.footprint.signals import emit_signal
                emit_signal("override_frozen", autoid, source="compile_emit", reason=_ov[:200])
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.debug("frozen 门校验异常(放行)", exc_info=True)

    # user_decision 落地门(A 层):用户在 ask_user 拍板的断言形态是硬约束——worker 挑省事
    # 形态会把用户选择跑偏(777976 实证选分布产出关系断言;593516 实证有序轨迹语义被静默
    # 降级成参与统计,用户从未批准)。orchestrator 带决策重派前把 user_decision.json 写进
    # outputs/<autoid>/,此处对产物机械核对;文件不存在=无决策约束,零行为变化。
    try:
        _ud_path = Path(__file__).resolve().parents[4] / "workspace" / "outputs" / autoid / "user_decision.json"
        if _ud_path.is_file():
            _ud = json.loads(_ud_path.read_text(encoding="utf-8"))
            _form = str(_ud.get("expected_assertion_form") or "").strip()
            _fvals = [str(s.get("F", "") or "").strip() for s in steps if isinstance(s, dict)]
            _has_h = any(str(s.get("H", "") or "").strip() for s in steps if isinstance(s, dict))
            _need = {"dist": "dist" in _fvals, "member": "member" in _fvals,
                     "captured_relation": _has_h}
            if _form in _need and not _need[_form]:
                return (f"error: case {autoid} violates user decision — the user-approved "
                        f"assertion form is {_form}, which is absent from the produced steps "
                        f"(F values present: {sorted(set(_fvals))}, has H capture: {_has_h}). "
                        "Rewrite the assertion in the form recorded in user_decision.json; "
                        "substituting an easier form is not allowed.")
            _kinds = _ud.get("claim_kinds_preserved") or []
            # 有序轨迹判定按台账的 ordering_sensitive 布尔(工具落盘的机读事实),不枚举
            # kind 名——orchestrator 会自创 kind(实证 rotation_order_after_delete 绕过
            # 了只认 new_member_last 的旧检查,靠 grade 兜住);new_member_last 保留兼容。
            _ordering_kinds = {"new_member_last"}
            try:
                _nd_path = _ud_path.parent / "needs_decision.json"
                if _nd_path.is_file():
                    _nd = json.loads(_nd_path.read_text(encoding="utf-8"))
                    for _c in (_nd.get("claims") or []):
                        if _c.get("ordering_sensitive") and _c.get("claim_kind"):
                            _ordering_kinds.add(str(_c["claim_kind"]))
            except Exception:  # noqa: BLE001
                pass
            if any(k in _ordering_kinds for k in _kinds):
                _presents = [s.get("member", {}).get("present") for s in steps
                             if isinstance(s, dict) and str(s.get("F", "") or "").strip() == "member"
                             and isinstance(s.get("member"), dict)]
                if not (True in _presents and False in _presents):
                    return (f"error: case {autoid} preserves an ordered-trajectory claim "
                            "(user_decision's claim_kinds_preserved plus the ledger's "
                            "ordering_sensitive mark) — the product must carry an ordering "
                            "anchor: in time order, a not_found segment (target pool member "
                            "set, member declared present=false) followed by a found segment "
                            "(present=true). Distribution/participation statistics alone "
                            "cannot prove ordering — that is a semantic downgrade, refused. If "
                            "the ordering semantics has been proven unverifiable, report the "
                            "underdetermination as-is to the orchestrator for the user to "
                            "revise expectations, and update user_decision.json accordingly.")
    except Exception:  # noqa: BLE001
        logger.debug("user_decision 门校验异常(放行)", exc_info=True)

    # provenance 三通道,优先级同 steps:原生对象 > provenance_path(workspace 文件) > 字符串。
    # (2026-07-05 v12 实证:供应商把原生 provenance 传成 {"steps": null} / 整体吞掉——
    # 文件通道是与 steps_path 同款的兜底,载荷通道一致性原则覆盖 provenance。)
    if provenance is not None and not (isinstance(provenance, str) and not provenance.strip()):
        if isinstance(provenance, (dict, list)):
            provenance_json = json.dumps(provenance, ensure_ascii=False)
        elif isinstance(provenance, str):
            provenance_json = provenance
    elif (provenance_path or "").strip() and not (provenance_json and provenance_json.strip()):
        _pp = (provenance_path or "").strip()
        _root = Path(__file__).resolve().parents[4]
        _p = Path(_pp) if _pp.startswith("/") else (_root / _pp)
        try:
            _p = _p.resolve()
            if not _p.is_relative_to((_root / "workspace").resolve()):
                return f"error: provenance_path must be inside workspace/: {_pp}"
            if not _p.is_file():
                return f"error: provenance_path file does not exist: {_pp} (fs_write the file first, then pass its path)"
            provenance_json = _p.read_text(encoding="utf-8")
        except Exception as _e:  # noqa: BLE001
            return f"error: provenance_path read failed: {_e}"

    # provenance 必传门(V4 步骤0,2026-07-04):主路 worker 34 卷 provenance=0 的实证——
    # 它断掉则 grade 免检索/四层归因/上机写回全部无依据(V3 名存实亡的机械根因)。
    # prompt 层约束在长上下文下必被遗忘(2026-07-02 零 grade 合并同型事故),故 A 层强制。
    if not (provenance_json and provenance_json.strip()):
        if (os.environ.get("IST_PROVENANCE_OPTIONAL") or "").strip() != "1":
            return (f"error: case {autoid} missing provenance — pass provenance along with steps "
                    "(native object with a steps array, each step {layer: G|E|V, source: {kind, ref}}; aligned one-to-one with the sheet steps). "
                    "It is the sole basis for approval without re-retrieval, four-layer "
                    "on-device attribution, and PASS write-back to the knowledge base. "
                    "layer meaning: G=command skeleton (from footprint/manual), E=environment "
                    "binding (from topology), V=assertion semantics (from "
                    "precedent/manual/user decision).")

    # provenance_json 前缀抢救:供应商在长字符串参数后拖尾(同 steps_json 的坑,2026-07-03
    # 实测 mimo 单轮 3 个 case 各摔 5 次)——JSON 本体合法、尾部粘了杂散 token 时,取第一个
    # 完整 JSON 值继续,不让整次 emit 因此报废。真正的坏 JSON(前缀都解不出)仍走原报错。
    if provenance_json and isinstance(provenance_json, str) and provenance_json.strip():
        _ps = provenance_json.strip()
        try:
            json.loads(_ps)
        except Exception:  # noqa: BLE001
            try:
                _obj, _end = json.JSONDecoder().raw_decode(_ps)
                if isinstance(_obj, dict) and _ps[_end:].strip():
                    provenance_json = json.dumps(_obj, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                pass  # 前缀也解不出 → 保留原串,由下游 parse_provenance 给出明确报错

    # 分布区间断言（F="dist"）→ 确定性展开成 N 条锚定区间正则的 found check_point（算法类 rr/wrr）。
    # 守恒/反恒真门不过直接打回；展开在所有结构门与 caseir 之前，下游只见普通 found。
    from main.case_compiler.distribution_assertion import (
        expand_distribution_steps, expand_provenance_steps_with_plan)
    steps, _dist_plan, _dist_err = expand_distribution_steps(steps)
    if _dist_err:
        return f"error: case {autoid} distribution-interval assertion declaration is invalid: {_dist_err}"
    # provenance 与 steps 同步展开（dist 桶标 V/distribution_derived），保持逐位对齐免旁挂跳过。
    if provenance_json and provenance_json.strip():
        try:
            _pj = json.loads(provenance_json)
            if isinstance(_pj, dict):
                _pj["steps"] = expand_provenance_steps_with_plan(_pj.get("steps"), _dist_plan)
                provenance_json = json.dumps(_pj, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass  # 坏 provenance 交给下游容错（旁挂跳过，xlsx 仍正常产出）

    # 命中归属锚点（F="member"）→ 确定性展开成 1 条锚定成员集合正则的 found/not_found check_point
    # （pool 内多成员/新增 pool 场景，命中归属靠"输出∈配置已知的成员集合"确定判出，不是猜同异）。
    # 1:1 展开，天然与 steps 逐位对齐，provenance 不需要额外 plan 同步（同 dist 的 "normal" 位）。
    from main.case_compiler.membership_assertion import expand_membership_steps
    steps, _member_err = expand_membership_steps(steps)
    if _member_err:
        return f"error: case {autoid} hit-membership assertion declaration is invalid: {_member_err}"

    try:
        from main.case_compiler.case_ir import FileIR, Row
        from main.case_compiler.xlsx_emit import emit_xlsx
        from main.case_compiler.config import get_config
    except Exception as e:  # noqa: BLE001
        return f"error: failed to load compiler modules: {e}"

    # 文件级前置
    init_g = init_commands.strip() if init_commands.strip() else get_config().default_init_g()
    # 字面 \n 自动纠正(拒绝改纠正,2026-07-04 V轮 token 取证):worker 批量在命令载荷里
    # 写字面反斜杠+n(LLM 在 JSON 字符串里双转义),一轮 17 卷。命令语境(init 与
    # APV_0/test_env 的 G 列)里字面 \n 没有任何合法用途——设备/dig/shell 语法都不用它,
    # 只可能是"想要换行"写错了。此前按必崩形态拒绝打回重做:每卷一轮 worker+grade 重做
    # ≈1-2M token,17 卷纯纠正一个双转义 ≈20M 白烧。无损替换,返回文本注明教 worker 下次
    # 写对;check_point 的 G 是正则([^\n] 合法),不在纠正范围。必须在 init_rows 构造与
    # 各 gate 之前做——写卷面与门检查都要看到纠正后的值。
    _fixed_literal_n = 0
    if "\\n" in init_g:
        init_g = init_g.replace("\\n", "\n")
        _fixed_literal_n += 1
    if isinstance(steps, list):
        for _s in steps:
            if not isinstance(_s, dict):
                continue
            if str(_s.get("E", "")).strip() in ("APV_0", "test_env"):
                _g = _s.get("G")
                if isinstance(_g, str) and "\\n" in _g:
                    _s["G"] = _g.replace("\\n", "\n")
                    _fixed_literal_n += 1
    init_rows = [Row(test_object="APV_0", method="cmds_config", data=init_g)]

    # 可达性校验门:配置/触发用的 IP 必须在拓扑可达集(挡住 1.1.1.1 等不可达示例 IP)
    gate = _gate_unreachable_ips(autoid, steps, init=init_g)
    if gate:
        return f"error: {gate}"

    # 触发可达性门:listener/VIP/dig 目标不能落在「触发够不着」的 APV 接口段(655233 类)
    gate = _gate_unreachable_listener(autoid, steps, init=init_g)
    if gate:
        return f"error: {gate}"

    # 安全门:拒绝 reboot/reload/shutdown 等破坏性命令(共享设备 + 框架不重连)
    gate = _gate_destructive_commands(autoid, steps, init=init_g)
    if gate:
        return f"error: {gate}"

    # 持久化门:config 恢复类用例的有序结构校验(基线污染/紧邻配对/清除步/参数/意图变体)
    gate = _gate_save_restore_pairing(autoid, steps, init=init_g,
                                      expected_save_variant=expected_save_variant)
    if gate:
        return f"error: {gate}"

    # 必崩形态**无条件**拒绝门集合(A 层机械崩溃,与 strict_structural opt-in 解耦):
    # found_times(分派只传 2 参必 TypeError) + 悬空断言(check_point 前无 result 生产步 →
    # found(None) 必崩)。两者都崩整份文件——等同语法错、机械可判、误判即真错,拒绝绝不该 opt-in
    # (实证两次:found_times 漏网→dongkl 首跑 31 unknown;悬空断言漏网→778012 重编 33 unknown)。
    # 语义"可证伪性"归 verifiability 工具 + LLM,不在此门。
    from main.ist_core.tools.device.structural_gate import check_crash_gates_mandatory
    # init_commands 与 steps 走同一门:init 会成为卷面首个 cmds_config 步,载荷形态问题
    # (字面 \n、None)同样必被设备 ^ 拒。此前只扫 steps,init 通道漏网——2026-07-04 V轮
    # 实证 worker 批量在 init 里写字面 \n,17 个卷 emit 放行、到 grade 的成品 lint 才被拦。
    _gate_steps = list(steps) if isinstance(steps, list) else steps
    if isinstance(_gate_steps, list) and (init_g or "").strip():
        _gate_steps = [{"D": "初始化配置", "E": "APV_0", "F": "cmds_config", "G": init_g}] + _gate_steps
    _ftres = check_crash_gates_mandatory(_gate_steps)
    if not _ftres.ok:
        return f"error: {_ftres.render(autoid)}"

    # S6 命令存在性呈报门(V8.5 片1):版本命令集成员判定,未命中呈报不硬拒——
    # 写 needs_decision 台账+拒落卷,worker 出路=行级证据重 emit 或 NEEDS_USER_DECISION。
    gate = _gate_command_existence(autoid, steps, init=init_g,
                                   evidence=command_existence_evidence)
    if gate:
        return gate

    # G1 配对恢复门(V8.5 片5,(39) τ):创建型 L2/L3 写须有案内恢复步,缺失呈报。
    gate = _gate_tau_coverage(autoid, steps, init=init_g)
    if gate:
        return gate

    # v2 结构约束门(opt-in,命题3.18 correct-by-construction):命令∈allowlist + 断言非悬空。
    # 与 grade 独立的确定性强制;v1(strict_structural=False)跳过,行为零变化。
    if strict_structural:
        from main.ist_core.tools.device.structural_gate import check_structural_constraints
        sresult = check_structural_constraints(autoid, steps, init=init_g)
        if not sresult.ok:
            return f"error: {sresult.render(autoid)}"

    # 步骤 → CaseIR(与合并工具共用同一构造,保证列语义一致)
    case, info = _steps_to_caseir(autoid, steps)
    if case is None:
        return f"error: {info}"

    # 末尾垫哨兵(框架延迟执行契约,见 _build_sentinel)
    sub = (out_name or autoid).strip().replace("/", "_")
    fir = FileIR(feature=sub, author="IST-Core-agent", init_rows=init_rows,
                 cases=[case, _build_sentinel()], module="ist_smoke")
    root = Path(__file__).resolve().parents[4]
    out = root / "workspace" / "outputs" / sub / "case.xlsx"

    # 单调门(A 层,理论 §2.4 守恒律的可判定投影):重编不得静默删观测维度。
    # 实证:035644/644 在 frozen override 压力下删掉会 fail 的 AAAA 断言——意图「A 或 AAAA」
    # 的 AAAA 半边被砍,真 fail 变假 PASS 还写回毒先例。比较基元=观测动词类+DNS 记录类型
    # 集合(不看断言文本——修法合法改断言,非法的是删观测维度)。旧卷在写盘前即天然基线;
    # 显式声明 coverage_reduction_reason 放行并记信号(用户改需求缩范围是合法路径)。
    if out.is_file():
        try:
            from main.ist_core.tools.device.precedent_tools import _load_case_rows
            _old_rows = _load_case_rows(str(out))
            _old_kinds, _old_types = _coverage_profile(_old_rows)
            _new_kinds, _new_types = _coverage_profile(steps)
            _rm_kinds = sorted(_old_kinds - _new_kinds)
            _rm_types = sorted(_old_types - _new_types)
            if _rm_kinds or _rm_types:
                _rm_desc = "; ".join(
                    ([f"observation verb class(es) removed: {', '.join(_rm_kinds)}"] if _rm_kinds else [])
                    + ([f"DNS record type(s) no longer probed: {', '.join(_rm_types)}"] if _rm_types else []))
                _cr = (coverage_reduction_reason or "").strip()
                if not _cr:
                    try:
                        from main.ist_core.memory.footprint.signals import emit_signal
                        emit_signal("monotonicity_violation", autoid, source="compile_emit",
                                    removed_kinds=_rm_kinds, removed_types=_rm_types)
                    except Exception:  # noqa: BLE001
                        pass
                    return ("error: monotonicity gate — this recompile removes observation "
                            f"coverage the previous volume had ({_rm_desc}). A fix may change "
                            "assertion text/values freely, but deleting an observation "
                            "dimension usually means deleting the probe that fails — that "
                            "turns a real failure into a fake PASS (measured: an AAAA probe "
                            "dropped under frozen-override pressure while the intent said "
                            "'A or AAAA'). Keep the observation and fix its expectation, or, "
                            "if the reduction is genuinely intended, re-emit with "
                            "coverage_reduction_reason = one sentence on which dimension you "
                            "dropped and why.")
                try:
                    from main.ist_core.memory.footprint.signals import emit_signal
                    emit_signal("monotonicity_violation", autoid, source="compile_emit",
                                removed_kinds=_rm_kinds, removed_types=_rm_types,
                                declared=True, reason=_cr[:200])
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            logger.debug("单调门比对异常(放行)", exc_info=True)

    try:
        stats = emit_xlsx(fir, out)
    except Exception as e:  # noqa: BLE001
        return f"error: emit failed: {e}"

    # v3：旁挂三层 Provenance IR。worker 主路必带；它是 grade 核来源的唯一依据。
    # ★关键：**绝不静默留旧 provenance**——重做没带/带坏，旧 case.provenance.json 残留就让 grade
    #   按上一版来源核对错位、放水（778012 实测：stale provenance 让 grade 拿到旧 src，写死命中 IP
    #   带病 PASS）。故：带了就必须解析成功 + 步数对齐，否则**打回**；没带就**删旧文件**。
    prov_note = ""
    prov_target = out.parent / "case.provenance.json"
    if provenance_json and provenance_json.strip():
        from main.case_compiler.provenance_ir import parse_provenance, backfill_efg
        prov = parse_provenance(provenance_json)
        if prov is None:
            try:
                json.loads(provenance_json)
                _bad = "JSON parses but the structure does not conform (need {autoid, steps:[{layer,source:{kind,ref}},…]})"
            except Exception as _je:  # noqa: BLE001
                _bad = f"the JSON itself is broken: {_je}"
            return (f"error: case {autoid} provenance parse failed — {_bad}; first 80 chars: "
                    f"{provenance_json.strip()[:80]!r}. "
                    "Pass provenance as a **native object argument** instead (a dict directly, "
                    "not serialized into a string stuffed into provenance_json) — the string "
                    "channel suffers trailing garbage/double escaping; the object channel has "
                    "no such exposure.")
        if not backfill_efg(prov, steps):
            n_prov = len(getattr(prov, "steps", []) or [])
            return (f"error: case {autoid} provenance step count ({n_prov}) does not match emit steps count ({len(steps)}). "
                    "Each step needs exactly one provenance entry (tag only layer+source; E/F/G are backfilled by emit); "
                    "a dist declaration step takes exactly 1 entry (emit expands it automatically). Fill in / remove extras and emit again.")
        # 不瞎写硬契约（仅 strict_structural 链强制）：device_runtime ⟺ <RUNTIME> 占位双向自洽。
        # 抓"标弃权却编数"和"占位却谎称有源"，把诚实弃权从建议变成可拒绝的结构约束。
        if strict_structural:
            from main.case_compiler.provenance_ir import check_runtime_consistency
            rt_problems = check_runtime_consistency(prov)
            if rt_problems:
                return ("error: case {} violates the no-fabrication contract (device_runtime ⟺ <RUNTIME> placeholder must be self-consistent):\n  - ".format(autoid)
                        + "\n  - ".join(rt_problems)
                        + "\n\nFor expected values unknowable offline, mark the <RUNTIME> placeholder + source.kind=device_runtime; "
                          "for values determinable offline, fill the real value + mark footprint/precedent/manual/intent. Fix and emit again.")
        try:
            prov_target.write_text(prov.to_json(), encoding="utf-8")
            gn = len(prov.layer_steps("G")); en = len(prov.layer_steps("E")); vn = len(prov.layer_steps("V"))
            prov_note = f"\nprovenance side-mounted: G={gn} E={en} V={vn} steps (reused by grade/verify/writeback)."
        except Exception as e:  # noqa: BLE001
            prov_note = f"\n⚠ provenance write failed: {e} (the xlsx itself was produced normally)."
    elif prov_target.exists():
        # 本次未带 provenance（重做忘带 / v1 旧链）：删掉残留旧文件，避免 grade 拿上一版来源误判。
        try:
            prov_target.unlink()
            prov_note = ("\n⚠ No provenance_json was provided this time; the stale old "
                         "case.provenance.json was deleted (so grade will not be lenient by "
                         "checking against stale sources). On redo, re-submit provenance along "
                         "with steps.")
        except Exception as e:  # noqa: BLE001
            prov_note = (f"\n⚠ An old provenance exists but deletion failed: {e} (clean it up "
                         "manually to keep grade from misusing stale sources).")

    _fix_note = ""
    if _fixed_literal_n:
        _fix_note = (f"\n⚠ Auto-corrected {_fixed_literal_n} literal backslash-n occurrence(s) "
                     "in command payloads to real newlines (in command context it can only be "
                     "a miswritten newline; in a JSON string a single backslash n is enough — "
                     "a double backslash becomes literal characters).")

    # lint 凭证:合并门判据=「过全部机械门」。实证依据(942 对时点配对):LLM grade
    # verdict 判别力仅 3pp(PASS 56% vs CUT 53%),LLM 审 LLM 不构成质量门,机械 lint +
    # 上机 oracle(ist-verify)才是。emit 走到这里=8 道门+crash-gate 全过,直接落凭证
    # (source=lint、xlsx_mtime 精确签名,直改立即失效);合并门只校验签名新鲜度。
    try:
        import time as _time
        _credp = Path(out).parent / ".grade_credential.json"
        _cred: dict = {}
        if _credp.is_file():
            try:
                _cred = json.loads(_credp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _cred = {}
        _cred.update({
            "autoid": autoid, "xlsx": str(out),
            "xlsx_mtime": Path(out).stat().st_mtime,
            "verdict": "PASS", "source": "lint",
            "lint_ok": True, "verdict_ts": _time.time(),
        })
        _credp.write_text(json.dumps(_cred, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("lint 凭证落盘失败(合并门会如实报缺)", exc_info=True)

    return (f"=== compile_emit ===\n"
            f"produced structurally-correct xlsx (cloned from the framework template): {out}\n"
            f"case={autoid}  steps={len(case.steps)}  check_points=present\n"
            f"round-trip stats: {stats}{prov_note}{_fix_note}\n"
            f"Compilation ends here; on-device verification is triggered by the separate ist-verify flow.")


def precheck_merge_case(aid: str) -> str | None:
    """单案合并就绪预检(V8 引擎 merge 节点消费;#74-② run13 二次实证驱动)。

    与 compile_emit_merged 的 autoids 门同构三查:xlsx 在盘/lint 凭证新鲜/成品卷
    lint 干净。返回 None=就绪;str=不就绪原因(进 emit_invalid 事实与用户面叙述)。
    引擎在合并前逐案预检,把不就绪案踢出本卷打回重编——单案违例不再拖死全批
    (run13 实证:一案凭证过期曾致 merge error→closing,26 案零上机收口)。
    工具本体的全拒行为不变(手动编排的最后防线)。
    """
    root = Path(__file__).resolve().parents[4]
    xp = root / "workspace" / "outputs" / str(aid).strip() / "case.xlsx"
    if not xp.is_file():
        return "case.xlsx 不在盘(编写未产出或已被挪走)"
    sj = xp.parent / ".grade_credential.json"
    if not sj.is_file():
        return "缺 lint 凭证(未经 compile_emit 过门产出)"
    try:
        cred = json.loads(sj.read_text(encoding="utf-8"))
        if abs(float(cred.get("xlsx_mtime", -1)) - xp.stat().st_mtime) >= 1e-6:
            return "lint 凭证过期(卷面在 emit 之后被修改——须重新 compile_emit 过门)"
    except Exception:  # noqa: BLE001
        return "lint 凭证不可读"
    from main.ist_core.tools.device.structural_gate import lint_xlsx_case
    lr = lint_xlsx_case(xp)
    if not lr.ok:
        return "成品卷 lint 违例:" + "; ".join(f"[{it.code}]" for it in lr.violations)[:200]
    return None


@tool(parse_docstring=True)
def compile_emit_merged(cases_json: str = "", shared_init: str = "", out_name: str = "", autoids: str | list[str] = "") -> str:
    """Merge **multiple cases into one xlsx** (the packaging tool for one excel per mindmap).

    **Preferred usage (main-orchestrated): pass only ``autoids``.** Each worker has already
    landed its case at workspace/outputs/<autoid>/case.xlsx via compile_emit; this tool
    **reads the steps back** from those finished xlsx files by itself and merges them — you
    **need not and must not** supply steps/init yourself (the workers baked that data into the
    xlsx long ago; you don't have it and cannot piece it together). Just pass the autoid list.
    ``cases_json`` is only for internal use by the V6 engine closing node (gate-free archive
    channel); do not take it in manual orchestration.

    For batch-compile wrap-up: merges the N cases already generated one by one from the same
    mindmap into a single case.xlsx, automatically padding a sentinel case at the end
    (framework deferred-execution contract) — so the first N real cases all execute normally.
    Merging is not simple concatenation: it guarantees case order, column alignment, and the
    sentinel at the bottom; the structure is 100% legal.

    **Each case carries its own preconfig** (``init``): the framework clears device config
    before running every case, so each case must be self-contained. Put this case's full
    baseline config into its own ``init`` (emitted as the case's first APV_0 config step), and
    the test actions + assertions into ``steps``. When cases have different baselines (e.g.
    each with its own pool/algorithm), each writes its own init — never share one.

    ``shared_init`` is only for file-level preconfig (C=1) that **all cases truly share and
    that must rerun before every case**. Usually leave it empty; baselines go into each case's
    own ``init``.

    Zero hardcoding: this tool produces no commands; init/steps all come from you (the
    sub-agent that has consulted manuals/precedents).

    Args:
        autoids: **Pass this first.** autoid list (JSON array string like ["203...","203..."],
            or comma separated). For each autoid the tool reads
            workspace/outputs/<autoid>/case.xlsx and merges the steps read back via
            _load_case_rows (init is already included as the first APV_0 step). When autoids
            is given, cases_json is ignored.
        cases_json: (V6 engine closing internal use) JSON array string, each item a case dict
            with keys autoid, steps (each step {E,F,G,H?,I?,desc?}, at least one check_point),
            init (may be empty), title (optional). **Do not use it in manual orchestration** —
            you most likely cannot assemble the full steps; pass autoids and let the tool read
            them back itself.
        shared_init: file-level preconfig (C=1) shared by all cases, newline separated; usually empty.
        out_name: output subdir name (workspace/outputs/<out_name>/case.xlsx); e.g. the mindmap name dongkl.

    Returns:
        Output path + round-trip reconciliation (case count should = input count + 1 sentinel).
        Compilation ends here; on-device verification is triggered by the separate ist-verify flow.

    Note:
        The autoids path carries the lint-credential mechanical gate: each autoid must have
        passed all of compile_emit's mechanical gates on the current case.xlsx (passing the
        gates auto-lands .grade_credential.json with the exact xlsx_mtime signature). Missing
        or stale credential → the merge is refused with the case list. The cases_json path
        (V6 engine closing archive) does not go through this gate.
    """
    # 首选:从 autoids 回读各成品 case.xlsx(不用自己提供 steps;
    # _load_case_rows 回读,init 作为首步已含回读结果)。
    aid_list, autoids_err = _parse_autoids_arg(autoids)
    if autoids_err:
        return autoids_err
    if aid_list is not None:
        from main.ist_core.tools.device.precedent_tools import _load_case_rows
        root = Path(__file__).resolve().parents[4]
        cases = []
        no_grade: list[str] = []
        stale_grade: list[str] = []
        for aid in aid_list:
            aid = str(aid).strip()
            xp = root / "workspace" / "outputs" / aid / "case.xlsx"
            if not xp.is_file():
                return (f"error: case.xlsx for autoid {aid} does not exist ({xp}); the case may "
                        "not have compiled successfully — compile it first / re-dispatch the worker")
            # lint 凭证机械门(A 层):每个 case 必须在**当前这份** case.xlsx 上过 emit 的全部
            # 机械门——compile_emit 过门时自动落盘 .grade_credential.json(source=lint、精确
            # 签名 xlsx_mtime)。凭证缺失=没经 gated emit;xlsx_mtime 不匹配=重编后没重新 emit。
            # 校验内容签名字段(xlsx_mtime)而非文件 mtime——mtime 冒充得了、精确 xlsx_mtime 值
            # 只能从工具落盘获得,手写文件冒充不了。质量门=机械 lint + 上机 oracle(ist-verify);
            # 实证依据=942 对时点配对里 LLM grade verdict 判别力仅 3pp,故语义终判交上机不交 grade。
            sj = xp.parent / ".grade_credential.json"
            cred_ok = False
            if sj.is_file():
                try:
                    cred = json.loads(sj.read_text(encoding="utf-8"))
                    cred_ok = abs(float(cred.get("xlsx_mtime", -1)) - xp.stat().st_mtime) < 1e-6
                except Exception:  # noqa: BLE001
                    cred_ok = False
            if not sj.is_file():
                no_grade.append(aid)
            elif not cred_ok:
                stale_grade.append(aid)
            try:
                rows = _load_case_rows(str(xp))  # 含 init 首步 APV_0 + 全步骤(E/F/G/H/I/desc),遇哨兵停
            except Exception as e:  # noqa: BLE001
                return f"error: failed to read back case.xlsx for {aid}: {e}"
            if not rows:
                return f"error: {aid} read back empty steps (case.xlsx data area empty?)"
            cases.append({"autoid": aid, "steps": rows})  # init 已在 steps 首行,不另传(传了会重复)
        if no_grade or stale_grade:
            parts = []
            if no_grade:
                parts.append(f"missing lint credential (did not go through gated compile_emit): {', '.join(no_grade)}")
            if stale_grade:
                parts.append(f"re-compiled but not re-emitted (the credential does not match the current case.xlsx): {', '.join(stale_grade)}")
            return ("error: merge rejected by the lint-credential gate — the following cases have not passed all of emit's mechanical gates on their current case.xlsx:\n"
                    + "\n".join(parts)
                    + "\nRun compile_emit again for each listed case (passing all mechanical gates auto-lands the lint credential), then merge.")
        # 成品卷 lint(最后防线):凭证全绿也可能是 lint 挂点上线前落的旧凭证,或卷面在
        # 凭证之后又被直改。合并是终卷产出的最后一道必经之路,对每卷再跑必崩/必假 lint——
        # 一个必崩 case 会让整份 pytest 39 秒崩掉、其余 33 个全不跑(2026-07-04 两轮实证)。
        from main.ist_core.tools.device.structural_gate import lint_xlsx_case
        lint_bad: list[str] = []
        for aid in aid_list:
            xp = root / "workspace" / "outputs" / str(aid).strip() / "case.xlsx"
            lr = lint_xlsx_case(xp)
            if not lr.ok:
                lint_bad.append(f"{aid}: " + "; ".join(f"[{it.code}]" for it in lr.violations))
        if lint_bad:
            return ("error: merge rejected by finished-sheet lint — the following cases carry "
                    "mechanically decidable must-crash/always-fail shapes (one must-crash case "
                    "crashes the whole pytest file and none of the rest run):\n  "
                    + "\n  ".join(lint_bad)
                    + "\nFix them, run compile_emit again, then merge (violation details are in the corresponding emit returns).")
    else:
        try:
            cases = json.loads(cases_json)
            if not isinstance(cases, list) or not cases:
                return "error: pass autoids (preferred; the tool reads the sheets back itself) or a non-empty cases_json"
        except Exception as e:  # noqa: BLE001
            return f"error: cases_json parse failed: {e}"

    try:
        from main.case_compiler.case_ir import FileIR, Row
        from main.case_compiler.xlsx_emit import emit_xlsx
        from main.case_compiler.config import get_config
        from main.case_compiler.distribution_assertion import expand_distribution_steps
        from main.case_compiler.membership_assertion import expand_membership_steps
    except Exception as e:  # noqa: BLE001
        return f"error: failed to load compiler modules: {e}"

    case_irs = []
    seen_autoids = set()
    for idx, c in enumerate(cases):
        if not isinstance(c, dict):
            return f"error: cases[{idx}] is not a dict"
        autoid = str(c.get("autoid", "")).strip()
        if not autoid:
            return f"error: cases[{idx}] is missing autoid"
        if autoid in seen_autoids:
            return f"error: autoid {autoid} is duplicated (autoid is the primary key and must be unique; titles may repeat)"
        seen_autoids.add(autoid)
        steps = c.get("steps")
        if not isinstance(steps, list) or not steps:
            return f"error: cases[{idx}] (autoid={autoid}) steps must be a non-empty list"

        # 丢弃 G 空的命令步(零信息量占位)。历史 merge 产物常带「初始化配置/G 空」占位行;
        # openpyxl 把空串单元格**落盘成 None**,再经回读-重写链条后框架 str(None)="None"
        # 原样发给设备 → ^ 拒、整 case fail(实证 final4 19 个 case 连锁)。空步一律不进成品。
        steps = [s for s in steps if not (isinstance(s, dict)
                 and str(s.get("E", "")).strip() in ("APV_0", "test_env")
                 and not str(s.get("G") or "").strip())]
        if not steps:
            return f"error: cases[{idx}] (autoid={autoid}) steps became empty after dropping empty command steps"

        # 分布区间断言展开（每 case 独立；merged 不带 provenance，只展开 steps）
        steps, _dist_plan, _dist_err = expand_distribution_steps(steps)
        if _dist_err:
            return f"error: cases[{idx}] (autoid={autoid}) distribution-interval assertion declaration is invalid: {_dist_err}"

        # 命中归属锚点展开（同上，1:1，仅 cases_json 兜底路径会遇到未展开的声明；
        # autoids 首选路径回读的是已成品 xlsx，member 早已在单 case emit 时展开过）。
        steps, _member_err = expand_membership_steps(steps)
        if _member_err:
            return f"error: cases[{idx}] (autoid={autoid}) hit-membership assertion declaration is invalid: {_member_err}"

        # 每个 case 的自包含前置 → 该 case 的首个 APV_0 配置步骤(不是文件级 C=1)。
        # 框架每 case 前清配置,故基线必须在 case 内,且不同 case 各写各的。
        case_init = str(c.get("init", "") or "").strip()

        # 可达性校验门(逐 case):init + 步骤里的 IP 必须可达,挡住 1.1.1.1 等不可达示例 IP
        gate = _gate_unreachable_ips(autoid, steps, init=case_init)
        if gate:
            return f"error: cases[{idx}] {gate}"

        # 触发可达性门:listener/VIP/dig 目标不能落在「触发够不着」的 APV 接口段
        gate = _gate_unreachable_listener(autoid, steps, init=case_init)
        if gate:
            return f"error: cases[{idx}] {gate}"

        # 安全门:拒绝 reboot/reload/shutdown 等破坏性命令
        gate = _gate_destructive_commands(autoid, steps, init=case_init)
        if gate:
            return f"error: cases[{idx}] {gate}"

        # 持久化门:config 恢复类用例的有序结构校验(意图变体可逐 case 透传)
        gate = _gate_save_restore_pairing(autoid, steps, init=case_init,
                                          expected_save_variant=str(c.get("expected_save_variant", "") or ""))
        if gate:
            return f"error: cases[{idx}] {gate}"

        full_steps = list(steps)
        if case_init:
            full_steps = [{"E": "APV_0", "F": "cmds_config", "G": case_init,
                           "desc": "case 自包含前置配置"}] + full_steps

        case, info = _steps_to_caseir(autoid, full_steps, title=str(c.get("title", "") or ""))
        if case is None:
            return f"error: cases[{idx}] (autoid={autoid}): {info}"
        case_irs.append(case)

    # 文件级共享前置(通常空)
    shared = shared_init.strip()
    init_rows = ([Row(test_object="APV_0", method="cmds_config", data=shared)]
                 if shared else [])

    # 末尾垫哨兵(框架延迟执行契约)——前 N 个真 case 全执行
    sub = (out_name or case_irs[0].autoid).strip().replace("/", "_")
    fir = FileIR(feature=sub, author="IST-Core-agent", init_rows=init_rows,
                 cases=[*case_irs, _build_sentinel()], module="ist_smoke")
    root = Path(__file__).resolve().parents[4]
    out = root / "workspace" / "outputs" / sub / "case.xlsx"
    try:
        stats = emit_xlsx(fir, out)
    except Exception as e:  # noqa: BLE001
        return f"error: emit failed: {e}"

    # 回填重放(2026-07-05 生命周期洞修复):重合并从 per-case 卷重建,会静默丢掉
    # 此前 compile_runtime_fill 写进旧合并卷的值。fill 侧已把成功回填按内容键
    # (autoid+原 G 全文)记到同目录 runtime_fills.json——这里对新卷按内容匹配重放:
    # 卷面未变必中,重编过的 case 必不中(安全跳过,如实报数,不猜)。
    replay_note = ""
    try:
        _side = out.parent / "runtime_fills.json"
        if _side.is_file():
            from main.case_compiler.runtime_fill import apply_fills, list_runtime_slots
            _recs = [r for r in json.loads(_side.read_text(encoding="utf-8")) if isinstance(r, dict)]
            _slots = {(s.autoid, s.observe_cmd, s.current_g): s for s in list_runtime_slots(out)}
            _fills, _skipped = [], 0
            for r in _recs:
                s = _slots.get((str(r.get("autoid")), str(r.get("observe_cmd")),
                                str(r.get("g_original"))))
                if s is None:
                    _skipped += 1
                    continue
                _fills.append({"slot_id": s.slot_id,
                               "runtime_value": str(r.get("runtime_value") or ""),
                               "evidence": str(r.get("evidence") or "")})
            if _fills:
                _res = apply_fills(out, _fills, project_root=root, run_meta="merged-replay")
                replay_note = (f"\n回填重放: 恢复 {len(_res.filled)}/{len(_recs)} 个已验证回填值"
                               f"(卷面已变跳过 {_skipped} 个——重编过的 case 需重新上机取值)")
            elif _recs:
                replay_note = (f"\n回填重放: 0/{len(_recs)}——sidecar 记录与新卷面全部不匹配"
                               "(相关 case 已重编,原回填值失效,需重新上机取值)")
    except Exception:  # noqa: BLE001
        logger.debug("runtime_fills 重放失败(合并本身已完成)", exc_info=True)

    autoids = [c.autoid for c in case_irs]
    return (f"=== compile_emit_merged ===\n"
            f"已合并 {len(case_irs)} 个真 case + 1 哨兵 → {out}\n"
            f"autoids: {autoids}\n"
            f"round-trip stats: {stats}"
            f"{replay_note}\n"
            f"(case_count expected={len(case_irs)}+1 sentinel={len(case_irs)+1})\n"
            f"Compilation ends here; on-device verification is triggered by the separate ist-verify flow.")
