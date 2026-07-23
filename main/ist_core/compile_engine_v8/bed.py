"""床态体检门+床账(DESIGN §3 bed_gate;ctx=(π,B) 的 B 维,锚差监控 Δ 的多维扩展)。

- 探针清单是数据(domain_grammar.bed_probes,全带手册出处)——引擎零硬编码领域命令;
  probe_fn 注入(真实现包 dev_probe 的 _do_probe;测试注假)。
- 床账 runtime/bed_ledger/<host>.jsonl:本引擎 created/restored 配对(框架 IP 恢复契约
  的推广);**自动清理只限床账内己方未复原产物,非己方残留一律 ask 不动手**(INV-9,
  床是共享的)。跨批接力:上批崩溃未复原的,本批据账继续。
- 版本距离策略(对抗审查):major.minor 同族放行并记锚,跨 minor 失配 → ask。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Callable

from main.case_compiler.domain_grammar import load_grammar

logger = logging.getLogger(__name__)


# ── 版本距离策略 ─────────────────────────────────────────────────────────────

_VER_RE = re.compile(r"(\d+)[._](\d+)(?:[._]\d+)*")


def version_family(build: str) -> tuple:
    """build 串 → (major, minor) 家族键;解析不出返回空元组(视为未知)。

    分隔符归一:配置值惯用下划线(…_10_5_0_568)、设备自述用点(10.5.0.585),两收。
    """
    m = _VER_RE.search(str(build or ""))
    return (int(m.group(1)), int(m.group(2))) if m else ()


def anchor_verdict(device_build: str, cfg_build: str, precedent_build: str = "") -> dict:
    """三方版本锚比对(设备自述为真值)。

    match:同 major.minor 家族(568 先例 vs 585 设备=同族放行,记锚不拦);
    mismatch:跨 minor(10.4 vs 10.5——yzg@103 事故形态)→ 调用方走 ask;
    unknown:任一侧解析不出 → 如实报告,走 ask(不猜)。
    """
    dev, cfg = version_family(device_build), version_family(cfg_build)
    if not dev or not cfg:
        return {"status": "unknown", "device": device_build, "config": cfg_build}
    status = "match" if dev == cfg else "mismatch"
    out = {"status": status, "device": device_build, "config": cfg_build,
           "device_family": list(dev), "config_family": list(cfg)}
    pre = version_family(precedent_build)
    if pre and pre != dev:
        out["precedent_drift"] = {"precedent": precedent_build, "note": "K 主先例锚与设备异族"}
    return out


# ── 床账(per-host, append-only) ──────────────────────────────────────────────


def _ledger_path(root: Path, host: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", str(host))
    return root / "runtime" / "bed_ledger" / f"{safe}.jsonl"


def bed_record(root: Path, host: str, ev: str, kind: str, ident: str,
               batch: str = "", payload: dict | None = None) -> None:
    """记一笔床账。ev ∈ {created, restored, cleaned, maintenance};
    kind ∈ {segment, sdns_config_file, sync_peer, manual, …}。
    payload 承载机械恢复所需数据(如逆放命令列表——(25) 通路一:恢复=回放账本)。
    追加失败静默告警(床账是护栏,不阻断主流程——但 unrestored 差额会在下批体检露头)。"""
    try:
        p = _ledger_path(root, host)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": round(time.time(), 3), "ev": ev, "kind": kind,
               "id": ident, "batch": batch}
        if payload:
            rec["payload"] = payload
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("床账追加失败 host=%s %s %s", host, ev, ident, exc_info=True)


def maintenance_tokens(root: Path, host: str) -> set:
    """维护写的身份 token 集(C1 通道,(38) 写者全集的「运维写」入账消费端)。

    人工修床经 scripts/maintenance/log_bed_maintenance.py 登记(谁/何时/何命令/为何,
    ev=maintenance);此集合供两处解释 diff:①bed_check 残留判定(维护写≠非己方残留,
    不弹 ask)②closing 批后收敛(维护写≠案残留,不入 foreign 告警)。run12 实证:
    五次人工修床(拆桥接层配置、恢复接口基线地址)未入账 → 批后被判非己方漂移误告警。
    """
    p = _ledger_path(root, host)
    toks: set = set()
    if not p.is_file():
        return toks
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if d.get("ev") != "maintenance":
            continue
        for c in (d.get("payload") or {}).get("commands") or []:
            toks.update(_identity_tokens(str(c)))
    return toks


def annotate_maintenance(findings: list[dict], maint: set) -> None:
    """就地标注:finding 的**每一内容行**身份 token 非空且 ⊆ 维护命令面 →
    maintenance_explained。按行判定(与 split_maintained 同型)——聚合判定对
    零 token 行(纯字母实体名)失明,部分真残留会被静默洗白(redline 实测复现:
    维护面只有 maint_seg1,detail 混入 "segment: rogue" 仍被解释)。零 token 的
    非空行=不可解释(保守侧:漏解释多问一次,好过洗白)。保留 finding 本体
    (如实呈报,非静默丢弃);probe_failed(床态未知)不解释。"""
    if not maint:
        return
    for f in findings or []:
        if f.get("kind") == "build_anchor" or f.get("probe_failed"):
            continue
        lines = [ln for ln in str(f.get("detail") or "").splitlines() if ln.strip()]
        if lines and all(
                (toks := set(_identity_tokens(ln))) and toks <= maint for ln in lines):
            f["maintenance_explained"] = True


def split_maintained(foreign: dict, maint: set) -> tuple[dict, dict]:
    """closing 批后收敛:foreign diff 里能被维护命令面解释的行分流为 maintained
    (只报「维护写已解释」,不告警不动手)。判据=行级身份 token 全覆盖(⊆ 维护命令面)。"""
    if not maint:
        return foreign, {}
    left: dict = {}
    maintained: dict = {}
    for name, d in (foreign or {}).items():
        l = {"added": [], "removed": []}
        m = {"added": [], "removed": []}
        for side in ("added", "removed"):
            for ln in d.get(side) or []:
                toks = set(_identity_tokens(ln))
                (m if toks and toks <= maint else l)[side].append(ln)
        if l["added"] or l["removed"]:
            left[name] = l
        if m["added"] or m["removed"]:
            maintained[name] = m
    return left, maintained


def bed_unrestored(root: Path, host: str) -> list[dict]:
    """己方未复原产物 = created 与 restored 的差额(按 (kind,id) 配对)。"""
    p = _ledger_path(root, host)
    if not p.is_file():
        return []
    created: dict[tuple, dict] = {}
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        k = (str(d.get("kind")), str(d.get("id")))
        if d.get("ev") == "created":
            created[k] = d
        elif d.get("ev") == "restored":
            created.pop(k, None)
    return list(created.values())


# ── 床态快照与机械逆放(X11 床账接线;THEORY 2.7.7 (25)(26)+R4) ─────────────────


def _clean_probe_body(out: str) -> list[str]:
    """探针回显 → 内容行(剥元数据/提示符/空行;与 bed_check 的行清洗同源)。"""
    lines = []
    for ln in str(out or "").splitlines():
        s = ln.strip()
        if not s or ln.startswith(("===", "---", "command:", "status:")):
            continue
        if re.match(r"^\w+=\S+(\s+\w+=\S+)*$", s):
            continue
        if len(s) <= 40 and s.endswith(("#", ">")):
            continue
        lines.append(s)
    return lines


def bed_snapshot(probe_fn: Callable[[str], str]) -> dict:
    """床态快照:全部探针(含 snapshot_only 状态面)的内容行。批前/批后各拍一次,
    diff=本批漂移(观测结果,不解析卷面意图——X5 裁决:不做持久写识别器)。
    通道经 probe_resilient 复探一次消解瞬态(瞬态失败的通道被跳过 diff=丢一次漂移观察)。"""
    probes = dict(load_grammar().get("bed_probes") or {})
    probes.pop("_provenance", None)
    probes.pop("cleanup_refs", None)
    snap: dict = {}
    for name, spec in probes.items():
        if name == "build":
            continue
        out = probe_resilient(probe_fn, str(spec.get("cmd") or ""))
        if _probe_failed(out):
            snap[name] = {"failed": True, "lines": []}
        else:
            snap[name] = {"failed": False, "lines": _clean_probe_body(out)}
    return snap


def snapshot_only_channels() -> set:
    """snapshot_only 通道名集合(平台基线状态面:接口地址等)。批后收敛的自动恢复
    绝不触碰它们——只观测呈报/入账,不生成删除命令(见 restorable_diff)。"""
    probes = dict(load_grammar().get("bed_probes") or {})
    return {name for name, spec in probes.items()
            if isinstance(spec, dict) and spec.get("snapshot_only")}


def restorable_diff(diff: dict) -> tuple[dict, dict]:
    """把快照 diff 拆成 (可自动恢复的, 只呈报不动手的)。

    平台基线面(snapshot_only:接口地址等)判据严一档——**只有 diff 含 `removed`
    (批前快照见证消失=快照完整可信,真替换)才可自动恢复;纯 `added` 无 `removed`
    一律只呈报**:纯 added 两种成因都不该删——①批前探针被截断(基线本就在,删=断
    设备,run18 险删管理 IP)②案纯新增地址(框架 IP 恢复契约下 case 开头自清)。
    含 removed 的真替换(run9 vlan100 形态)照常恢复。机理全文:DESIGN §18.8.1
    「平台基线面不自动删接口 IP」;测试锚 test_baseline_face_no_autorestore.py。"""
    so = snapshot_only_channels()
    restorable: dict = {}
    observe_only: dict = {}
    for k, v in diff.items():
        if k not in so or v.get("removed"):
            restorable[k] = v          # 普通残留面 / 基线面但有 removed(快照完整可信)
        else:
            observe_only[k] = v        # 基线面纯 added:截断嫌疑或纯新增,只呈报
    return restorable, observe_only


def bed_diff(before: dict, after: dict) -> dict:
    """快照差分:{probe: {added: […], removed: […]}}(任一侧探测失败的通道跳过——
    比不出=未知,不误报;R4-G2 的诚实边界)。"""
    out: dict = {}
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name) or {}, after.get(name) or {}
        if b.get("failed") or a.get("failed") or (not b and not a):
            continue
        bl, al = set(b.get("lines") or []), set(a.get("lines") or [])
        added, removed = sorted(al - bl), sorted(bl - al)
        if added or removed:
            out[name] = {"added": added, "removed": removed}
    return out


_MASK_SEGS = {"0", "128", "192", "224", "240", "248", "252", "254", "255"}


def _identity_tokens(line: str) -> list[str]:
    """diff 行的身份 token:接口名与 IP。掩码剔除——点分掩码与 masklen 是同一事实
    的两种表示法(show 显点分,命令用 /24),参与身份比对会让己方判定恒失配。"""
    toks: list[str] = []
    for t in re.findall(r"[\w.-]+", line):
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", t):
            if all(seg in _MASK_SEGS for seg in t.split(".")):
                continue   # 掩码形态
            toks.append(t)
        elif any(ch.isdigit() for ch in t) and not t.replace(".", "").isdigit():
            toks.append(t)   # vlan100/port2/eth0.100 类带数字的名字
    return toks


def entity_gate(cmds: list[str], diff_own: dict) -> tuple[list[str], list[str]]:
    """实体越界门(机械):恢复命令的身份 token 必须 ⊆ 己方 diff 的身份 token 集——
    LLM 生成的命令不许碰 diff 之外的任何实体(行动论:判断开放,门闭合)。
    返回 (放行命令, 拒绝命令)。"""
    allowed: set = set()
    for d in diff_own.values():
        for side in ("added", "removed"):
            for ln in d.get(side) or []:
                allowed.update(_identity_tokens(ln))
    ok: list[str] = []
    rejected: list[str] = []
    for c in cmds:
        toks = _identity_tokens(str(c))
        # 无实体 token 的命令(clear all/reboot 类全局命令)一律拒——恢复命令必须
        # 指向 diff 内的具体实体(回归审查 R-7:all([]) 恒真曾让全局命令穿门)
        (ok if toks and all(t in allowed for t in toks) else rejected).append(str(c))
    return ok, rejected


def restore_via_llm(diff_own: dict, llm_fn: Callable[[str, str], str]) -> list[str]:
    """己方漂移 → 恢复命令,**生成归 LLM**(它懂任何状态面的 show↔配置命令对应——
    vlan/路由/ACL 同一条路,零模板零场景枚举);产物过 entity_gate+执行验证双门。
    llm_fn(system, user) -> text(注入;生产=flash 档直调,测试=假)。返回命令列表
    (失败/不可解析返回空——保守,残余入账走下批接力或 ask)。"""
    payload = json.dumps(diff_own, ensure_ascii=False, indent=1)
    sys_p = ("You revert testbed configuration drift on a network device. Given a "
             "before/after diff of `show` output lines (added = lines that appeared "
             "after the batch, removed = lines that disappeared), produce the CLI "
             "commands that restore the BEFORE state: undo each added line, re-create "
             "each removed line. Use the device's native config syntax implied by the "
             "show lines themselves. Reply with a JSON array of command strings only — "
             "no prose, no fences. Touch ONLY entities present in the diff.")
    try:
        out = llm_fn(sys_p, payload)
        m = re.search(r"\[.*\]", str(out or ""), re.DOTALL)
        cmds = json.loads(m.group(0)) if m else []
        return [str(c) for c in cmds if isinstance(c, str) and c.strip()]
    except Exception:  # noqa: BLE001
        logger.warning("恢复命令生成失败(保守:入账待接力)", exc_info=True)
        return []


# ── S4 机械逆放先行(恢复命令从案面真发的 config 命令派生:config X → no X;
#    详见 own_writes_by_command/restore_mechanical docstring 与 DESIGN §18.8.1) ──


def _inverse_pairs() -> dict:
    """inverse_forms 配对表(head→{no,clear,src});读失败=空(调用方回落 LLM)。"""
    try:
        return dict((load_grammar().get("inverse_forms") or {}).get("pairs") or {})
    except Exception:  # noqa: BLE001
        logger.warning("inverse_forms 读取失败——机械逆放本次禁用,回落 LLM", exc_info=True)
        return {}


def _head_match(cmd: str, pairs_lc: dict) -> str | None:
    """命令 token 最长前缀匹配 inverse_forms 键(纯词法,与 tau_coverage._head_match 同型)。"""
    ws = cmd.lower().split()
    for k in range(min(len(ws), 5), 0, -1):
        cand = " ".join(ws[:k])
        if cand in pairs_lc:
            return cand
    return None


def parse_config_commands(corpus: str) -> list[str]:
    """从设备回显 corpus 解析案面真发的**配置命令**——框架
    `<name> - sends command in config: <cmd>` 行(mirror apv_ccypher.py:152 权威格式)。
    只取 config 通道:test/enable 通道的命令(dig 访问等)不是配置写,不参与恢复判据。"""
    out: list[str] = []
    for ln in str(corpus or "").splitlines():
        m = re.search(r"sends command in config:\s*(.+?)\s*$", ln)
        if m:
            out.append(m.group(1).strip())
    return out


def _creating_command(diff_line: str, config_cmds: list, pairs_lc: dict) -> str | None:
    """找案面真发的、创建 diff_line 所述对象的配置命令:head 是可逆构造(命中
    inverse_forms)∧ 实体 token ⊇ diff 行实体。找不到=案面没创建过该对象(基线/
    他人写/仅被访问)——这正是 run18 与 run9 的分界:port2 只被 dig 访问(无创建命令),
    vlan100 被 `ip address vlan100 …` 创建(有)。"""
    d_ents = set(_identity_tokens(diff_line))
    if not d_ents:
        return None
    for cmd in config_cmds:
        cl = cmd.lower()
        if cl.startswith(("no ", "clear ", "show ")):
            continue                       # 逆元/观测命令不是创建命令
        if _head_match(cmd, pairs_lc) is None:
            continue                       # 非可逆构造头
        if d_ents <= set(_identity_tokens(cmd)):
            return cmd
    return None


def own_writes_by_command(diff: dict, config_cmds: list, pairs: dict) -> tuple[dict, dict]:
    """己方判定(S4 兑现②,升级 own_writes 判据):diff 行「己方」iff 案面 config 命令
    里有创建该对象的命令——而非旧版「token 在 corpus 文本出现」(被 dig 访问等非配置写
    污染,run18 删基线的直接成因)。返回 (own, foreign);foreign=案面没创建过(基线/
    他人写),只报不动(INV-9)。pairs 空(inverse_forms 读失败)→ 全归 foreign(保守:
    宁可不恢复也不误删)。"""
    pairs_lc = {k.lower(): v for k, v in (pairs or {}).items()}
    own: dict = {}
    foreign: dict = {}
    for name, d in diff.items():
        o = {"added": [], "removed": []}
        f = {"added": [], "removed": []}
        for side in ("added", "removed"):
            for ln in d.get(side) or []:
                (o if _creating_command(ln, config_cmds, pairs_lc) else f)[side].append(ln)
        if o["added"] or o["removed"]:
            own[name] = o
        if f["added"] or f["removed"]:
            foreign[name] = f
    return own, foreign


def restore_mechanical(diff_own: dict, config_cmds: list, pairs: dict) -> tuple[list, dict]:
    """己方漂移 → 机械逆放命令(S4 兑现②首选路径):
    - added 行(对象多出,需删):取创建命令的 negation `no <创建命令全文>`(作用域恒等于
      原命令,inverse_forms 的 no 公理;仅当该 head 有 no 逆元——只有 clear 的不机械逆放,
      clear 是聚合复位会误伤旁邻对象);
    - removed 行(对象消失,需重建):重放案面创建命令。
    返回 (机械命令列表, 派生不出的残余 diff)——残余走 LLM 后备/入账。零 LLM、零模板。"""
    pairs_lc = {k.lower(): v for k, v in (pairs or {}).items()}
    cmds: list[str] = []
    residual: dict = {}
    for name, d in diff_own.items():
        left = {"added": [], "removed": []}
        for ln in d.get("added") or []:
            create = _creating_command(ln, config_cmds, pairs_lc)
            head = _head_match(create, pairs_lc) if create else None
            if create and head and (pairs_lc.get(head) or {}).get("no"):
                cmds.append(f"no {create}")          # negation,作用域=原命令
            else:
                left["added"].append(ln)             # 无 no 逆元(只 clear/未匹配)→ 残余
        for ln in d.get("removed") or []:
            create = _creating_command(ln, config_cmds, pairs_lc)
            if create:
                cmds.append(create)                  # 重放创建命令
            else:
                left["removed"].append(ln)
        if left["added"] or left["removed"]:
            residual[name] = left
    return cmds, residual


# ── 初始化清理(2026-07-10 用户裁决:开工必净) ─────────────────────────────────


def bed_cleanup(exec_fn: Callable[[str], str], findings: list[dict], *,
                root: Path, host: str, batch: str = "") -> dict:
    """床态初始化清理:编写工作开始前环境必须干净(用户裁决;R1 12/26 崩盘的
    最大嫌疑即两天床残留)。

    exec_fn 必须是**配置模式**执行通道(clear 族在 show 通道被设备拒——2026-07-10
    实证 status:error 却被记成"已清",复检恒 3 项)。清理动作**全部来自文法数据**
    bed_probes.cleanup_refs(手册出处,按 finding.kind 对号)——引擎零硬编码领域命令;
    无清理引用的发现不动手(留给体检 ask 兜底)。**回显必须校验**:status: success
    才算清成(记床账 ev=cleaned);error/异常 → failed 如实上报。调用方清理后必须复检。
    """
    refs = dict((load_grammar().get("bed_probes") or {}).get("cleanup_refs") or {})
    refs.pop("_provenance", None)
    out: dict = {"cleaned": [], "failed": [], "skipped": []}
    for f in findings:
        kind = str(f.get("kind") or "")
        if kind == "build_anchor":
            continue                      # 版本锚不是残留,只能 ask
        spec = refs.get(kind)
        if not isinstance(spec, dict) or not str(spec.get("cmd") or "").strip():
            out["skipped"].append(kind)   # 文法层无清理引用 → 不动手
            continue
        if spec.get("interactive_confirm"):
            # 需交互确认(如 Type "YES")的命令单发通道做不完——会卡在确认提示上且
            # status 无错误标记会被误判成功(2026-07-10 实录);会话式通道支持前跳过
            out["skipped"].append(kind)
            continue
        echo = exec_fn(str(spec["cmd"])) or ""
        item = {"kind": kind, "provenance": str(spec.get("provenance", ""))[:120],
                "echo": echo[:300]}
        if "status: success" in echo:
            bed_record(root, host, "cleaned", kind, "init_cleanup", batch)
            out["cleaned"].append(item)
        else:
            out["failed"].append(item)    # 设备拒绝/通道异常:不谎报,进问询题面
    return out


# ── 体检(只读探针,注入式) ────────────────────────────────────────────────────


def _probe_failed(out: str) -> bool:
    """探针自身失败(床态未知)的协议/契约级判定——不是内容关键字猜测:
    设备拒绝标记(% Invalid + ^ 行)/fastmcp status 契约行/工具 error 前缀。"""
    t = str(out or "")
    if not t.strip():
        return True   # 空回显=探针没跑到(超时/通道断),床态未知≠干净(审计坑#12 盲区)
    if t.startswith("error"):
        return True
    if re.search(r"^status:\s*error", t, re.MULTILINE):
        return True
    if "% Invalid" in t and re.search(r"^\s*\^\s*$", t, re.MULTILINE):
        return True
    # 工具 error 契约行可能跟在来源横幅之后(`=== dev_probe (fastmcp apv_ssh) ===\n
    # error: SSH to X failed`)——只看串首会穿门(2026-07-13 实证:105 床 SSH 挂死被
    # 报成"分区配置残留",批后快照垃圾 diff 入床账 4 条)。首个内容行即工具契约位。
    for ln in t.splitlines():
        s = ln.strip()
        if not s or s.startswith("==="):
            continue
        return s.startswith("error")
    return False


def probe_resilient(probe_fn: Callable[[str], str], cmd: str) -> str:
    """探一次;协议级失败即复探一次(瞬态消解)——两次都失败才算真失败。

    实证两例同型(2026-07-11 / 2026-07-13 run18):合法 show 命令单次被设备回
    `% Invalid input`,同一通道立即复探即成功(空列表)——框架 SSH 读窗串位(P1 已知
    时序缺陷)使命令被截断/错位解析。不复探=一次瞬态就产「该通道床态未知」的假问询
    打断用户,而床其实是干净的。复探成本=一次只读 show,可忽略。

    两次都失败返回**首次**回显:首次是正常路径上的观察,复探路径的新错误(如复探时
    恰好 SSH 断)会误导诊断方向。
    """
    out = probe_fn(cmd)
    if not _probe_failed(out):
        return out
    retry = probe_fn(cmd)
    if not _probe_failed(retry):
        logger.info("探针瞬态失败,复探成功:%s", cmd)
        return retry
    return out


def bed_check(probe_fn: Callable[[str], str], cfg_build: str, *,
              root: Path, host: str, precedent_build: str = "") -> dict:
    """批前床态体检:版本锚三方比对 + 各通道残留探测 + 床账差额。

    probe_fn(cmd)->回显文本(注入;真实现经跳板机只读探针,失败返回 'error:...');
    每个通道经 probe_resilient 复探一次消解瞬态。
    返回报告 dict;`needs_ask=True` 时调用方(bed_gate 节点)必须 interrupt 问用户,
    自动清理只允许对 `ours_unrestored` 项执行(INV-9)。
    """
    probes = dict(load_grammar().get("bed_probes") or {})
    probes.pop("_provenance", None)
    probes.pop("cleanup_refs", None)
    report: dict = {"host": host, "probes": {}, "findings": [], "needs_ask": False}

    # ① 版本锚。探针自身失败=床态未知,不是"版本不匹配"(2026-07-13 实证:SSH 挂死
    # 的空版本被呈报成「⚠ 版本不匹配:设备(空)」——用户拿到的是误导性判断题,真相
    # 是设备不可达);probe_failed 单独归类,题面走"探测失败"形态。
    bspec = probes.get("build") or {}
    raw = probe_resilient(probe_fn, str(bspec.get("cmd") or "show version"))
    report["probes"]["build"] = raw[:400]
    if _probe_failed(raw):
        report["needs_ask"] = True
        report["anchor"] = {"status": "probe_failed", "device": "",
                            "config": cfg_build, "detail": (raw or "").strip()[:400]}
        report["findings"].append({"kind": "build_anchor", "probe_failed": True,
                                   "detail": report["anchor"]})
    else:
        m = re.search(str(bspec.get("extract") or ""), raw or "")
        device_build = (m.group(1).strip() if m else "")
        report["anchor"] = anchor_verdict(device_build, cfg_build, precedent_build)
        if report["anchor"]["status"] != "match":
            report["needs_ask"] = True
            report["findings"].append({"kind": "build_anchor", "detail": report["anchor"]})

    # ② 各通道残留(只读;结果原文交调用方/用户判读,引擎只做"非空即报")
    for name, spec in probes.items():
        if name == "build" or spec.get("snapshot_only"):
            continue   # snapshot_only:合法内容恒在的状态面(非空≠残留),只进快照 diff
        out = probe_resilient(probe_fn, str(spec.get("cmd") or ""))
        report["probes"][name] = (out or "")[:400]
        # 探针失败 ≠ 有残留(2026-07-11 yzg 验收实证:`% Invalid input` 单次瞬态被
        # 报成"分区配置残留"——失败报错文本也是非空回显,混进残留=谎报床上有东西)。
        # 失败=床态未知,单独归类如实呈报;信号全部协议/契约级,非内容词表:
        # ①设备 `% Invalid`+`^` 拒绝标记(与 compile_attribute 的 G 层判据同源)
        # ②fastmcp 回显契约行 `status: error` ③工具错误契约前缀 `error:`
        if _probe_failed(out):
            report["needs_ask"] = True
            report["findings"].append({"kind": name, "probe_failed": True,
                                       "detail": (out or "")[:400]})
            continue
        hdr_pats = [re.compile(p, re.IGNORECASE) for p in (spec.get("header_patterns") or [])]
        body = "\n".join(ln for ln in (out or "").splitlines()
                         if ln.strip()
                         and not ln.startswith(("===", "---", "command:", "status:"))
                         # 探针元数据行:一至多个 key=val(实录 "host=IP  mode=show" 组合行
                         # 穿透单 token 版过滤 → 每个探针恒剩此行 → 幽灵残留恒弹床态问询,
                         # 2026-07-10 两轮实证;三通道实际全空)
                         and not re.match(r"^\w+=\S+(\s+\w+=\S+)*$", ln.strip())
                         and not (len(ln.strip()) <= 40 and ln.strip().endswith(("#", ">")))
                         # 段落标题行(通用):"Running configuration backup files:" 这类
                         # 以冒号收尾的头,空列表也打印,不算残留
                         and not ln.strip().endswith(":")
                         # 列表头(领域数据):探针条目 header_patterns 按引用过滤,
                         # 新表头形态=改 JSON 零代码
                         and not any(p.match(ln.strip()) for p in hdr_pats))
        if body.strip() and "(no output)" not in out:
            report["findings"].append({"kind": name, "detail": body[:300]})

    # ③ 床账差额:己方未复原 → 可自动恢复;维护写(C1 通道)→ 已解释只标注;
    # 其余发现 → ask
    ours = bed_unrestored(root, host)
    report["ours_unrestored"] = ours
    annotate_maintenance(report["findings"], maintenance_tokens(root, host))
    foreign = [f for f in report["findings"] if f["kind"] != "build_anchor"
               and not f.get("maintenance_explained")]
    # H-13:旧 `foreign and not ours` 在 snapshot_only 纯 added 历史账「留账不动手」
    # (R073)使 ours 恒非空后,永久关掉 INV-9 呈报。判定时剔除 snapshot_only 账项——
    # 它们不构成自动恢复资格,也不该静默掉其它通道的非己方残留;可恢复面的
    # ours 仍走自动恢复(INV-9),不在此臂强制 ask。
    so = snapshot_only_channels()
    effective_ours = [o for o in (ours or []) if str(o.get("kind")) not in so]
    if foreign and not effective_ours:
        report["needs_ask"] = True
    return report
