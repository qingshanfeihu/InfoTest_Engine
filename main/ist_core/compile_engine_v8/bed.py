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
    """记一笔床账。ev ∈ {created, restored};kind ∈ {segment, sdns_config_file, sync_peer, …}。
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
    diff=本批漂移(观测结果,不解析卷面意图——X5 裁决:不做持久写识别器)。"""
    probes = dict(load_grammar().get("bed_probes") or {})
    probes.pop("_provenance", None)
    probes.pop("cleanup_refs", None)
    snap: dict = {}
    for name, spec in probes.items():
        if name == "build":
            continue
        out = probe_fn(str(spec.get("cmd") or ""))
        if _probe_failed(out):
            snap[name] = {"failed": True, "lines": []}
        else:
            snap[name] = {"failed": False, "lines": _clean_probe_body(out)}
    return snap


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


def own_writes(diff: dict, command_corpus: str) -> tuple[dict, dict]:
    """己方交叉验证(R4-G4):diff 行的身份 token(接口名/IP)全部在本批执行命令面出现
    → 认己方可逆放;对不上的归 foreign(共享床上他人并行动的,只报不动——INV-9)。"""
    own: dict = {}
    foreign: dict = {}
    corpus = str(command_corpus or "")
    for name, d in diff.items():
        o = {"added": [], "removed": []}
        f = {"added": [], "removed": []}
        for side in ("added", "removed"):
            for ln in d.get(side) or []:
                toks = _identity_tokens(ln)
                (o if toks and all(t in corpus for t in toks) else f)[side].append(ln)
        if o["added"] or o["removed"]:
            own[name] = o
        if f["added"] or f["removed"]:
            foreign[name] = f
    return own, foreign


def _mask_to_len(mask: str) -> int:
    try:
        return sum(bin(int(o)).count("1") for o in mask.split("."))
    except Exception:  # noqa: BLE001
        return 24


def restore_plan(diff_own: dict) -> tuple[list[str], list[str]]:
    """己方漂移 → 机械逆放命令(仅已建模状态面;模板=grammar 数据带 provenance,
    R4-G3:机械回放非 LLM 生成)。返回 (commands, unmodeled_notes)。"""
    syn = dict(load_grammar().get("bed_restore_syntax") or {})
    cmds: list[str] = []
    notes: list[str] = []
    for name, d in diff_own.items():
        spec = syn.get(name)
        if not isinstance(spec, dict):
            for side in ("added", "removed"):
                for ln in d.get(side) or []:
                    notes.append(f"{name}:{side}:{ln}")
            continue
        line_re = re.compile(str(spec.get("line_re") or "$^"))
        for ln in d.get("added") or []:      # 批后多出的 → 撤销
            m = line_re.match(ln)
            if m:
                cmds.append(str(spec.get("del")).format(**m.groupdict()))
            else:
                notes.append(f"{name}:added:{ln}")
        for ln in d.get("removed") or []:    # 批后缺失的 → 原值回放
            m = line_re.match(ln)
            if m:
                gd = dict(m.groupdict())
                if "mask" in gd:
                    gd["masklen"] = _mask_to_len(gd["mask"])
                cmds.append(str(spec.get("add")).format(**gd))
            else:
                notes.append(f"{name}:removed:{ln}")
    return cmds, notes


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
    if t.startswith("error"):
        return True
    if re.search(r"^status:\s*error", t, re.MULTILINE):
        return True
    if "% Invalid" in t and re.search(r"^\s*\^\s*$", t, re.MULTILINE):
        return True
    return False


def bed_check(probe_fn: Callable[[str], str], cfg_build: str, *,
              root: Path, host: str, precedent_build: str = "") -> dict:
    """批前床态体检:版本锚三方比对 + 各通道残留探测 + 床账差额。

    probe_fn(cmd)->回显文本(注入;真实现经跳板机只读探针,失败返回 'error:...')。
    返回报告 dict;`needs_ask=True` 时调用方(bed_gate 节点)必须 interrupt 问用户,
    自动清理只允许对 `ours_unrestored` 项执行(INV-9)。
    """
    probes = dict(load_grammar().get("bed_probes") or {})
    probes.pop("_provenance", None)
    probes.pop("cleanup_refs", None)
    report: dict = {"host": host, "probes": {}, "findings": [], "needs_ask": False}

    # ① 版本锚
    bspec = probes.get("build") or {}
    raw = probe_fn(str(bspec.get("cmd") or "show version"))
    report["probes"]["build"] = raw[:400]
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
        out = probe_fn(str(spec.get("cmd") or ""))
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

    # ③ 床账差额:己方未复原 → 可自动恢复;其余发现 → ask
    ours = bed_unrestored(root, host)
    report["ours_unrestored"] = ours
    foreign = [f for f in report["findings"] if f["kind"] != "build_anchor"]
    if foreign and not ours:
        report["needs_ask"] = True          # 非己方残留:只报不清
    return report
