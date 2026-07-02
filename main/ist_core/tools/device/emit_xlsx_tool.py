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
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 框架执行契约(死知识):test_xlsx.py 是**延迟执行模型**——最后一个 case 走 `if last_case`
# 收尾分支,只 parser_case_id 记录、**不执行步骤**。所以 xlsx 末尾必须垫一个哨兵 case,
# 让真实 case 都不是最后一个、走正常执行路径。哨兵自己当 last_case 不执行,无副作用。
# 这对单 case 和多 case 合并是同一条契约:cases=[真case..., _sentinel]。
_SENTINEL_AUTOID = "999999999999999"


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
            return [], "error: autoids 列表无有效 id（元素全空）"
        return aid_list, None
    s = str(autoids).strip()
    if not s:
        return None, None
    try:
        parsed = json.loads(s) if s.startswith("[") else [x.strip() for x in s.split(",") if x.strip()]
    except json.JSONDecodeError as e:
        return [], f"error: autoids JSON 解析失败: {e}"
    if not isinstance(parsed, list):
        return [], "error: autoids 须为 JSON 数组或逗号分隔的 id 列表"
    aid_list = [str(a).strip() for a in parsed if str(a).strip()]
    if not aid_list:
        return [], "error: autoids 解析为空(传非空 JSON 数组、逗号分隔字符串,或直接传 list)"
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
            return None, f"step[{i}] 不是 dict"
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if not e or not f:
            return None, f"step[{i}] 缺 E 或 F"
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
        return None, (f"case {autoid} 没有任何 check_point 步骤——上机必 fail"
                      f"(pass 需 success>0)。加一个 found 断言。")
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
    return (f"case {autoid} 用了 {len(bad)} 个**环境不可达 IP**: {', '.join(bad)}\n"
            f"这些 IP 不在本测试床任何子网内,上机 dig/连接必失败(Hit=0、断言全 fail)。\n"
            f"改用真实可达 IP 重写——后端 service/pool 用真实服务器 IP,VIP/listener 用段内未占用 IP:\n\n"
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
    return (f"case {autoid} 含 {len(bad)} 条**破坏性设备生命周期命令**: {lines}\n"
            f"禁止:这会真重启/关停共享设备,且框架重启后无法重连(必 fail)。\n"
            f"若意图是测「配置保存/持久化」,改用不重启的 clear→恢复 范式:\n"
            f"  配置 → write memory(或 write file/all/net 存盘)→ clear sdns all(清运行配置)\n"
            f"  → config memory(或 config file/all/net 从存盘恢复)→ show → 断言配置在不在。\n"
            f"先例参考:smoke_test/sdns/log_backup(已验证的存盘→清→恢复→断言写法)。")


_SAVE_RE = _re_dev.compile(r"\bwrite\s+(memory|mem|file|all|net)\b", _re_dev.IGNORECASE)
_RESTORE_RE = _re_dev.compile(r"\bconfig\s+(memory|file|all|net)\b", _re_dev.IGNORECASE)
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
                errs.append(f"基线污染:配 listener 之前出现保存命令 {c!r}——config 会恢复配 listener "
                            f"之前的旧快照,not_found 假通过。删掉它(基线不该预存盘)。")
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
                errs.append(f"恢复 config {rf} 之前没有任何 write 保存命令(恢复了从没存过的存储)。")
            elif last_save != rf:
                errs.append(f"恢复 config {rf} 与其前最近的保存 write {last_save} 不同族——读的不是刚存的那份。"
                            f"改成 config {last_save},或把保存改成 write {rf}(二者必须同族)。")

    # P1a 清除步(配 listener 与首个恢复之间)
    first_restore_idx = restores[0][0]
    lo = first_listener if first_listener is not None else 0
    if not any(_CLEAR_RE.search(c) for c in cmds[lo:first_restore_idx]):
        errs.append("缺清除步:配 listener 与 config 恢复之间没有 no sdns listener / clear sdns——"
                    "恢复成空操作、not_found 永真、测试空转。在保存后、恢复前加清除步。")

    # P1b 参数完整(file/all/net 变体)
    for c in cmds:
        fam = _save_family(c) or _restore_family(c)
        if fam in _SAVE_REMOTE and not _param_tail(c, fam):
            verb = "write" if _save_family(c) else "config"
            errs.append(f"命令缺参数:{c!r}——{fam} 变体需带参数(如 {verb} {fam} <文件名/目标>),"
                        f"按手册 cli_*_Chapter*.md + cli_*_Appendix*.md 补全,裸命令设备会拒。")

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
            errs.append(f"意图变体不符:本用例应测 write {ev} 的持久化,实际保存却用了 write {used}"
                        f"(意图被偷换、成了别的变体的重复)。保存改回 write {ev}、恢复用 config {ev}。")

    if not errs:
        return None
    body = "\n".join(f"  - {e}" for e in errs)
    return (f"case {autoid} 持久化测试(config 恢复类)结构错误:\n{body}\n"
            f"正确范式:配 listener → show/found → write <意图变体> → no/clear listener → "
            f"config <同变体> → show → 断言。参考先例 smoke_test/sdns/log_backup。")


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
    lines = [f"case {autoid} 触发可达性不合法:"]
    if hit:
        lines.append(f"- listener/VIP 或 dig/curl 目标落在「触发够不着」的 APV 接口段: {', '.join(hit)}")
    if bad_target:
        lines.append(f"- dig/curl 目标 IP 不是测试床的 ★ 可达 listener(也非已知后端): {', '.join(bad_target)}(多半凭空编)")
    lines.append(f"dig/curl 目标必须取 ★ 可达 listener IP(与配置的 listener 一致): {', '.join(listener)}")
    return "\n".join(lines) + "\n\n" + facts.summary_for_agent()



@tool(parse_docstring=True)
def compile_emit(autoid: str, steps_json: str, init_commands: str = "",
                 out_name: str = "", strict_structural: bool = False,
                 provenance_json: str = "", expected_save_variant: str = "") -> str:
    """从步骤列表产出结构正确的 case.xlsx(克隆框架原生模板,你不用管模板结构/列对齐)。

    **用这个,别用 run_python 手搓 openpyxl**——手搓总在 27 行说明区/C=0/C=1/E-F-G 列对齐上
    出错,导致框架跳过你的 case 行(零 check_point、空真 pass)。本工具保证结构 100% 合法。

    你只决定**内容**:文件级前置命令 + 每个步骤的 操作对象/方法/数据。

    列语义(每个 step 一个 dict):
    - ``E`` 操作对象: 被测设备标识 / check_point(断言) / test_env(测试机) / time(等待)
    - ``F`` 方法: 被测设备→cmd_config(单条)|cmds_config(多条\\n分隔);
      check_point→found(正则DOTALL)|not_found|abs_found(字面)|found_times(需I列次数);
      test_env→网络事实源中的主机名; time→sleep
    - ``G`` 数据(**数据类型=字面文本/正则字符串,不是变量、不是 Python 表达式、不是数值**):
      配置步骤=CLI命令原文;check_point=要在上一步输出里**文本查找**的期望文本/正则。
      框架拿 G **原样**匹配——写一个变量名(如 init_ip)它就去找字面 "init_ip" 这几个字符,永远找不到。
    - ``H`` save_as(可选)/``I`` input_var(可选): 捕获+比较——存一次观测输出、之后比同/不同
      (会话保持/亲和性/轮转的正确形态)。完整用法(必需的三步式结构、为什么带 H 的步不更新 result)
      在 knowledge/data/compile_ref/EXCEL_FUNCTIONS.md 的「H 格」那节。
    - ``desc``(可选): 步骤描述

    check_point 自动校验**上一个非 check_point 步骤的输出**,所以断言前要先有产出输出的步骤
    (show/dig)。每个 case 至少一个会通过的 check_point(否则上机必 fail)。

    Args:
        autoid: case autoid for the first case row column A.
        steps_json: JSON array string; each element a dict with keys E/F/G and optional H/I/desc.
        init_commands: file-level preconfig (C=1) commands, newline separated; empty uses project default.
        out_name: output subdir under workspace/outputs; empty uses autoid.
        strict_structural: v2 编译链置 True 时启用结构约束门（命令∈手册allowlist + 断言非悬空，
            correct-by-construction）；v1 默认 False 行为不变。违反结构约束直接打回带原因。
        provenance_json: v3 三层 Provenance IR（CaseProvenance JSON）。默认空＝V2 行为不变；
            传入则旁挂 case.provenance.json（每步标 G/E/V 层 + 来源），供 grade/verify/writeback 复用。
        expected_save_variant: 仅配置保存/持久化类用例传（memory|file|all|net）。脑图要求"执行
            write all 后..."就传 "all"。持久化门据此校验你用的保存命令没被换族(write all 不能写成
            write memory)。非持久化用例留空。

    Returns:
        产出路径 + round-trip 行数统计。编译到此结束；上机验证由独立 ist_verify 流程触发。
    """
    autoid = (autoid or "").strip()
    if not autoid:
        return "error: 必须指定 autoid"
    # autoid 短号格式门(A 层机械):需求系统 autoid 为 18 位数字(20303…);纯数字却不足 15 位
    # 必是完整号的尾段缩写(实证 deepseek 重编把 brief 里的短号 778012 原样烧进 xlsx ID 列 →
    # 需求关联/框架报告 ID 断链)。非纯数字 id(测试/特殊场景)不受限——宁漏勿杀。
    if autoid.isdigit() and len(autoid) < 15:
        return (f"error: autoid '{autoid}' 疑似短号(纯数字但不足 15 位)。请传完整需求系统 autoid"
                f"(18 位,如 203031753342778012)——短号烧进 xlsx 会导致需求关联与框架报告 ID 断链。")
    try:
        steps = json.loads(steps_json) if isinstance(steps_json, str) else steps_json
        if not isinstance(steps, list) or not steps:
            return "error: steps_json 必须是非空列表"
    except Exception as e:  # noqa: BLE001
        return f"error: steps_json 解析失败: {e}"

    # 分布区间断言（F="dist"）→ 确定性展开成 N 条锚定区间正则的 found check_point（算法类 rr/wrr）。
    # 守恒/反恒真门不过直接打回；展开在所有结构门与 caseir 之前，下游只见普通 found。
    from main.case_compiler.distribution_assertion import (
        expand_distribution_steps, expand_provenance_steps_with_plan)
    steps, _dist_plan, _dist_err = expand_distribution_steps(steps)
    if _dist_err:
        return f"error: case {autoid} 分布区间断言声明无效：{_dist_err}"
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
        return f"error: case {autoid} 命中归属断言声明无效：{_member_err}"

    try:
        from main.case_compiler.case_ir import FileIR, Row
        from main.case_compiler.xlsx_emit import emit_xlsx
        from main.case_compiler.config import get_config
    except Exception as e:  # noqa: BLE001
        return f"error: 加载编译器模块失败: {e}"

    # 文件级前置
    init_g = init_commands.strip() if init_commands.strip() else get_config().default_init_g()
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
    _ftres = check_crash_gates_mandatory(steps)
    if not _ftres.ok:
        return f"error: {_ftres.render(autoid)}"

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
    try:
        stats = emit_xlsx(fir, out)
    except Exception as e:  # noqa: BLE001
        return f"error: emit 失败: {e}"

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
            return (f"error: case {autoid} provenance_json 解析失败（非合法 CaseProvenance JSON）。"
                    "provenance 是 grade 核来源的依据，不能缺/坏——修正 JSON 后重新 emit。")
        if not backfill_efg(prov, steps):
            n_prov = len(getattr(prov, "steps", []) or [])
            return (f"error: case {autoid} provenance 步数({n_prov}) 与 emit steps 数({len(steps)}) 不一致。"
                    "每个 step 须对应一个 provenance 条目（只标 layer+source，E/F/G 由 emit 回填）；"
                    "dist 声明步只占 1 条（emit 自动展开）。补齐/删多后重新 emit。")
        # 不瞎写硬契约（仅 strict_structural 链强制）：device_runtime ⟺ <RUNTIME> 占位双向自洽。
        # 抓"标弃权却编数"和"占位却谎称有源"，把诚实弃权从建议变成可拒绝的结构约束。
        if strict_structural:
            from main.case_compiler.provenance_ir import check_runtime_consistency
            rt_problems = check_runtime_consistency(prov)
            if rt_problems:
                return ("error: case {} 违反不瞎写契约（device_runtime ⟺ <RUNTIME> 占位须自洽）：\n  - ".format(autoid)
                        + "\n  - ".join(rt_problems)
                        + "\n\n离线不可知的期望值标 <RUNTIME> 占位 + source.kind=device_runtime；"
                          "可离线定值的填真值 + 标 footprint/precedent/manual/intent。修正后重新 emit。")
        try:
            prov_target.write_text(prov.to_json(), encoding="utf-8")
            gn = len(prov.layer_steps("G")); en = len(prov.layer_steps("E")); vn = len(prov.layer_steps("V"))
            prov_note = f"\nprovenance 已旁挂: G={gn} E={en} V={vn} 步（供 grade/verify/writeback 复用）。"
        except Exception as e:  # noqa: BLE001
            prov_note = f"\n⚠ provenance 写入失败: {e}（xlsx 正常产出）。"
    elif prov_target.exists():
        # 本次未带 provenance（重做忘带 / v1 旧链）：删掉残留旧文件，避免 grade 拿上一版来源误判。
        try:
            prov_target.unlink()
            prov_note = ("\n⚠ 本次未提供 provenance_json，已删除残留的旧 case.provenance.json"
                         "（避免 grade 按 stale 来源核对放水）。重做请随 steps 一并重交 provenance。")
        except Exception as e:  # noqa: BLE001
            prov_note = f"\n⚠ 存在旧 provenance 但删除失败: {e}（建议手动清理，防 grade 误用 stale 来源）。"

    return (f"=== compile_emit ===\n"
            f"已产出结构正确的 xlsx(克隆框架模板): {out}\n"
            f"case={autoid}  steps={len(case.steps)}  check_points=有\n"
            f"round-trip 统计: {stats}{prov_note}\n"
            f"编译到此结束；上机验证由独立 ist_verify 流程触发。")


@tool(parse_docstring=True)
def compile_emit_merged(cases_json: str = "", shared_init: str = "", out_name: str = "", autoids: str | list[str] = "") -> str:
    """把**多个 case 合并成一个 xlsx**(每脑图一个 excel 的打包工具)。

    **首选用法(main-orchestrated):只传 ``autoids``。** 各 worker 已用 compile_emit 把 case
    落到 workspace/outputs/<autoid>/case.xlsx,本工具自己从这些成品 xlsx **回读 steps** 合并——
    你**不用、也不该**自己提供 steps/init(那些数据 worker 早写进 xlsx 了,你手里没有、凑也凑不全)。
    传 autoid 列表即可。``cases_json`` 仅 compile_pipeline 内部回读后自用,手工编排别走它。

    用于批量编译收尾:把同一脑图里已逐个生成好的 N 个 case 合并进一个 case.xlsx,
    末尾自动垫一个哨兵 case(框架延迟执行契约)——这样前 N 个真 case 全部正常执行。
    合并不是简单拼接:它保证 case 顺序、列对齐、哨兵垫底,结构 100% 合法。

    **每个 case 自带它自己的前置配置**(``init``):框架每跑一个 case 前会清设备配置,
    所以每个 case 必须自包含。把这个 case 的完整基线配置放进它自己的 ``init``
    (会被 emit 成该 case 的首个 APV_0 配置步骤),test 动作 + 断言放进 ``steps``。
    不同 case 基线不同时(如各自不同的 pool/算法),各写各的 init——绝不能共用一份。

    ``shared_init`` 只用于**所有 case 真正共享、且每 case 前都要重跑**的文件级前置
    (C=1)。多数情况留空,基线走每个 case 自己的 ``init``。

    零硬编码:本工具不产任何命令,init/steps 全部由你(查过手册/先例的子 agent)提供。

    Args:
        autoids: **首选传这个**。autoid 列表(JSON 数组字符串如 ["203...","203..."],或逗号分隔)。
            工具对每个 autoid 读 workspace/outputs/<autoid>/case.xlsx、用 _load_case_rows 回读
            steps(init 作为首个 APV_0 步已含其中)合并。传了 autoids 就忽略 cases_json。
        cases_json: (compile_pipeline 内部用)JSON 数组字符串,每项 case dict 含键:autoid、
            steps(每步 {E,F,G,H?,I?,desc?},至少一个 check_point)、init(可空)、title(可选)。
            **手工编排不要用它**——你多半凑不全 steps,改传 autoids 让工具自己回读。
        shared_init: 所有 case 共享的文件级前置(C=1),换行分隔;通常留空。
        out_name: 输出子目录名(workspace/outputs/<out_name>/case.xlsx);如脑图名 dongkl。

    Returns:
        产出路径 + round-trip 对账(case 数应=输入数+1哨兵)。编译到此结束；
        上机验证由独立 ist_verify 流程触发。
    """
    # 首选:从 autoids 回读各成品 case.xlsx(main-orchestrated 不用自己提供 steps;
    # 复用 compile_pipeline merge 同一套 _load_case_rows,init 作为首步已含回读结果)。
    aid_list, autoids_err = _parse_autoids_arg(autoids)
    if autoids_err:
        return autoids_err
    if aid_list is not None:
        from main.ist_core.tools.device.precedent_tools import _load_case_rows
        root = Path(__file__).resolve().parents[4]
        cases = []
        for aid in aid_list:
            aid = str(aid).strip()
            xp = root / "workspace" / "outputs" / aid / "case.xlsx"
            if not xp.is_file():
                return f"error: autoid {aid} 的 case.xlsx 不存在({xp});该 case 可能没编译成功,先补编/重派 worker"
            try:
                rows = _load_case_rows(str(xp))  # 含 init 首步 APV_0 + 全步骤(E/F/G/H/I/desc),遇哨兵停
            except Exception as e:  # noqa: BLE001
                return f"error: 回读 {aid} 的 case.xlsx 失败: {e}"
            if not rows:
                return f"error: {aid} 回读 steps 为空(case.xlsx 数据区空?)"
            cases.append({"autoid": aid, "steps": rows})  # init 已在 steps 首行,不另传(传了会重复)
    else:
        try:
            cases = json.loads(cases_json)
            if not isinstance(cases, list) or not cases:
                return "error: 需传 autoids(首选,工具自己回读)或非空 cases_json"
        except Exception as e:  # noqa: BLE001
            return f"error: cases_json 解析失败: {e}"

    try:
        from main.case_compiler.case_ir import FileIR, Row
        from main.case_compiler.xlsx_emit import emit_xlsx
        from main.case_compiler.config import get_config
        from main.case_compiler.distribution_assertion import expand_distribution_steps
        from main.case_compiler.membership_assertion import expand_membership_steps
    except Exception as e:  # noqa: BLE001
        return f"error: 加载编译器模块失败: {e}"

    case_irs = []
    seen_autoids = set()
    for idx, c in enumerate(cases):
        if not isinstance(c, dict):
            return f"error: cases[{idx}] 不是 dict"
        autoid = str(c.get("autoid", "")).strip()
        if not autoid:
            return f"error: cases[{idx}] 缺 autoid"
        if autoid in seen_autoids:
            return f"error: autoid {autoid} 重复(autoid 是主键,不可重复;标题可重名)"
        seen_autoids.add(autoid)
        steps = c.get("steps")
        if not isinstance(steps, list) or not steps:
            return f"error: cases[{idx}] (autoid={autoid}) steps 必须是非空列表"

        # 丢弃 G 空的命令步(零信息量占位)。历史 merge 产物常带「初始化配置/G 空」占位行;
        # openpyxl 把空串单元格**落盘成 None**,再经回读-重写链条后框架 str(None)="None"
        # 原样发给设备 → ^ 拒、整 case fail(实证 final4 19 个 case 连锁)。空步一律不进成品。
        steps = [s for s in steps if not (isinstance(s, dict)
                 and str(s.get("E", "")).strip() in ("APV_0", "test_env")
                 and not str(s.get("G") or "").strip())]
        if not steps:
            return f"error: cases[{idx}] (autoid={autoid}) 过滤空命令步后 steps 为空"

        # 分布区间断言展开（每 case 独立；merged 不带 provenance，只展开 steps）
        steps, _dist_plan, _dist_err = expand_distribution_steps(steps)
        if _dist_err:
            return f"error: cases[{idx}] (autoid={autoid}) 分布区间断言声明无效：{_dist_err}"

        # 命中归属锚点展开（同上，1:1，仅 cases_json 兜底路径会遇到未展开的声明；
        # autoids 首选路径回读的是已成品 xlsx，member 早已在单 case emit 时展开过）。
        steps, _member_err = expand_membership_steps(steps)
        if _member_err:
            return f"error: cases[{idx}] (autoid={autoid}) 命中归属断言声明无效：{_member_err}"

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
        return f"error: emit 失败: {e}"

    autoids = [c.autoid for c in case_irs]
    return (f"=== compile_emit_merged ===\n"
            f"已合并 {len(case_irs)} 个真 case + 1 哨兵 → {out}\n"
            f"autoids: {autoids}\n"
            f"round-trip 统计: {stats}\n"
            f"(case_count 应={len(case_irs)}+1哨兵={len(case_irs)+1})\n"
            f"编译到此结束；上机验证由独立 ist_verify 流程触发。")
