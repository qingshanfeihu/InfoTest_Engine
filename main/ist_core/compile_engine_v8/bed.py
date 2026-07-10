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
               batch: str = "") -> None:
    """记一笔床账。ev ∈ {created, restored};kind ∈ {segment, sdns_config_file, sync_peer, …}。
    追加失败静默告警(床账是护栏,不阻断主流程——但 unrestored 差额会在下批体检露头)。"""
    try:
        p = _ledger_path(root, host)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), "ev": ev, "kind": kind,
                                "id": ident, "batch": batch}, ensure_ascii=False) + "\n")
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


# ── 体检(只读探针,注入式) ────────────────────────────────────────────────────


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
        if name == "build":
            continue
        out = probe_fn(str(spec.get("cmd") or ""))
        report["probes"][name] = (out or "")[:400]
        body = "\n".join(ln for ln in (out or "").splitlines()
                         if ln.strip()
                         and not ln.startswith(("===", "---", "command:", "status:"))
                         and not re.match(r"^\w+=\S*$", ln.strip())      # host=/mode= 等探针元数据行
                         and not (len(ln.strip()) <= 40 and ln.strip().endswith(("#", ">"))))
        if body.strip() and not out.startswith("error:") and "(no output)" not in out:
            report["findings"].append({"kind": name, "detail": body[:300]})

    # ③ 床账差额:己方未复原 → 可自动恢复;其余发现 → ask
    ours = bed_unrestored(root, host)
    report["ours_unrestored"] = ours
    foreign = [f for f in report["findings"] if f["kind"] != "build_anchor"]
    if foreign and not ours:
        report["needs_ask"] = True          # 非己方残留:只报不清
    return report
