"""compile_engine_run(V8):主 agent 一句话触发整条编译闭环的薄工具。

图套图边界(与 V6 同型):qa_agent 图经本工具进程内 invoke V8 图;checkpointer 分库
(runtime/compile_engine_v8_checkpoints.db,thread=v8:<out_name>)——账实分离(INV-7):
checkpoint 只存图游标+interrupt 挂起态+引用,业务真理在批目录 facts.jsonl。
[user] 孔桥接:interrupt payload(bed_gate/ask_decision/ask_contradiction 三类)→
既有 ask_user 面板 → Command(resume) 续跑。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MAX_INTERRUPT_ROUNDS = 12


import re as _re


def _panel(questions: list[dict]) -> dict:
    """interrupt 问题组 → ask_user 面板(≤4 题/批,面板 schema:question/header/options)
    → {key: 答案label}。非交互/异常 → {_non_interactive: True}。"""
    from main.ist_core.tools.ask_user import ask_user
    answers: dict = {}
    for i in range(0, len(questions), 4):
        batch = questions[i:i + 4]
        payload = [{k: v for k, v in q.items() if not str(k).startswith("_")} for q in batch]
        try:
            out = ask_user.func(payload)
        except Exception:  # noqa: BLE001
            logger.exception("ask 面板桥接失败")
            return {"_non_interactive": True}
        if isinstance(out, str) and (out.startswith("error") or "非交互" in out):
            return {"_non_interactive": True}
        for q in batch:
            header = str(q.get("header", ""))
            # 非贪婪到「下一键或串尾」:Other 自由输入可含引号,[^"]+ 会早停截断
            m = _re.search(rf'"{_re.escape(header)}"="(.*?)"(?=\. "|\.?\s*$)', out or "")
            if m:
                answers[str(q.get("_key", header))] = m.group(1)
    return answers


def _bridge(payload: dict) -> dict:
    """三类挂起 → 面板问题(形态转换,零语义判断)。"""
    kind = str(payload.get("kind") or "")
    if kind == "bed_gate":
        rep = payload.get("report") or {}
        anchor = rep.get("anchor") or {}
        cu = rep.get("cleanup") or {}
        _CHAN_CN = {"segments": "分区配置", "sdns_config_files": "SDNS 配置文件",
                    "sync_peers": "同步对端配置", "interface_addresses": "接口地址",
                    "mirror_sync": "框架镜像同步"}

        def _fail_sig(detail) -> str:
            """探针失败签名:剥来源横幅/契约行后的首个错误载荷行(逐字比对,零语义猜测)。"""
            if isinstance(detail, dict):
                detail = detail.get("detail") or ""
            for ln in str(detail or "").splitlines():
                s = ln.strip()
                if (not s or s.startswith(("===", "---", "command:"))
                        or _re.match(r"^\w+=\S+(\s+\w+=\S+)*$", s)
                        or _re.match(r"^status:\s*\w+$", s)):
                    continue
                low = s.lower()
                for p in ("probe failed:", "error:"):
                    if low.startswith(p):
                        s = s[len(p):].strip()
                        break
                if s:
                    return s[:160]
            return str(detail or "").strip()[:160]

        kinds, stuck, internal = [], [], []
        failed: list = []   # (中文通道名, 失败签名)
        for f in (rep.get("findings") or []):
            k = str(f.get("kind"))
            if k == "build_anchor":
                continue   # 版本锚单独渲染;probe_failed 时并入下方同因组
            if k in ("mirror_sync", "bed_closure_failed"):
                internal.append(str(f.get("detail") or ""))   # 引擎内部发现,不是设备残留
                continue
            cn = _CHAN_CN.get(k, k)
            if f.get("probe_failed"):
                failed.append((cn, _fail_sig(f.get("detail"))))
            elif f.get("ledger_stuck"):
                stuck.append(cn)
            else:
                kinds.append(cn + "残留")
        if str(anchor.get("status")) == "probe_failed":
            failed.append(("版本锚", _fail_sig(anchor)))
        # 共因合题(2026-07-13 实证:105 床 SSH 挂死被摊成「残留×3+探测未完成+版本
        # 不匹配」五段误导题面):同一失败签名覆盖 ≥2 路探针 → 合成一句,直说疑似设备
        # 不可达;签名=逐字相等,不做语义归并
        by_sig: dict = {}
        for cn, sig in failed:
            by_sig.setdefault(sig, []).append(cn)
        failed_parts = []
        for sig, chans in by_sig.items():
            if len(chans) >= 2:
                failed_parts.append(f"{'、'.join(chans)}共 {len(chans)} 路探针同因失败"
                                    f"({sig})——疑似设备不可达,床态未知")
            else:
                failed_parts.append(f"{chans[0]}通道探测未完成(探针命令未跑通:{sig},"
                                    f"该通道床态未知)")
        parts = []
        if kinds:
            parts.append(f"测试床上仍有残留:{'、'.join(kinds)}")
        if stuck:
            parts.append(f"上批留下的{'、'.join(stuck)}改动,自动恢复尝试未成"
                         f"(命令被拒或生成失败)——需要人工恢复后继续")
        if failed_parts:
            parts.append(";".join(failed_parts)
                         + "(「继续」为床态不明自担风险,或「停止」后修床重探/人工核查)")
        if internal:
            parts.extend(internal)
        cl, fl, sk = cu.get("cleaned") or [], cu.get("failed") or [], cu.get("skipped") or []
        if cl or fl or sk:
            seg = []
            if cl:
                seg.append(f"已自动清掉 {len(cl)} 项")
            if fl:
                seg.append(f"{len(fl)} 项清理被设备拒绝")
            if sk:
                seg.append(f"{len(sk)} 项引擎不认识、不敢动")
            parts.append("(" + ",".join(seg) + ")")
        _astat = str(anchor.get("status"))
        if _astat == "match":
            parts.append(f"版本正常(实测 {str(anchor.get('device', ''))[-12:]},与配置同族)")
        elif _astat == "probe_failed":
            pass   # 已并入上方探针失败段,不再谎报"版本不匹配"
        elif _astat == "unknown":
            parts.append(f"⚠ 版本未知:设备回显未解析出版本号(配置 {anchor.get('config', '?')})")
        else:
            parts.append(f"⚠ 版本不匹配:设备 {anchor.get('device', '?')} vs 配置 {anchor.get('config', '?')}")
        q = ";".join(parts) + "。如何处理?"
        qs = [{"question": q, "header": "床态体检",
               "options": [
                   {"label": "继续", "description": "接受现状照跑——残留不再清理,风险自担;所有结果记录在实测版本上"},
                   {"label": "停止", "description": "先人工清理/换床,之后同参数重跑会从这里续接"}],
               "_key": "decision"}]
        ans = _panel(qs)
        v = str(ans.get("decision") or "").strip()
        # H-12:精确认选项 label/proceed——旧 `"继续" in v` 把「不继续」「先别继续」
        # 反转成 proceed(INV-9 床权在用户)。自由输入含继续且无局部否定仍可放行。
        if v in ("继续", "proceed"):
            return {"decision": "proceed"}
        if "继续" in v and not _re.search(r"(不|别|勿|没|未)(要|能|可|该|应|再|先)?.{0,2}继续", v):
            return {"decision": "proceed"}
        return {"decision": v or "停止"}
    if kind == "ask_decision":
        qs = list(payload.get("questions") or [])
        for q in qs:
            q["_key"] = str(q.get("_autoid") or q.get("header") or "")
        return _panel(qs)
    if kind == "ask_contradiction":
        qs = [_contradiction_question(c) for c in (payload.get("cases") or [])]
        raw = _panel(qs)
        if raw.get("_non_interactive"):
            return raw
        # label→token 引擎同源精确映射(W3:label 是引擎自己产的,不猜;
        # Other 自由输入不在表 → token 空,节点侧语义兜底)
        out: dict = {}
        for q in qs:
            k = str(q.get("_key") or "")
            if k in raw:
                label = raw[k]
                out[k] = {"answer": label,
                          "token": (q.get("_tokens") or {}).get(label, "")}
        return out
    return {"_non_interactive": True}


# 题面组装在 questions.py(ask 面板语义单一事实源);一行委托保持
# `ET._contradiction_question` 既有调用与测试路径不变
from main.ist_core.compile_engine_v8.questions import (  # noqa: E402
    build_ask_question as _contradiction_question)


@tool(parse_docstring=True)
def compile_engine_run(mindmap_path: str, product_version: str,
                       out_name: str = "", max_rounds: int = 3) -> str:
    """Run the V8 compile engine: mindmap → bed check → per-case authoring → ask on underdetermined → merge → on-device run → reconcile → attribution → targeted recompile → final delivery verify → writeback → report.

    Facts are append-only (workspace/outputs/<batch>/facts.jsonl); every on-device verdict is
    reconciled with an explicit outcome — swallowed verdicts are structurally impossible. Three
    user-decision edges may pause the run (bed anchor mismatch / underdetermined claims /
    delivery contradiction); answers resume from checkpoint. Re-calling with the same
    arguments resumes an interrupted run without re-burning device rounds.

    Args:
        mindmap_path: mindmap txt path (e.g. workspace/inputs/automatic_case/x.txt).
        product_version: product version (e.g. 10.5) — decides which manual workers consult.
        out_name: batch name (deliverables at workspace/outputs/<out_name>/); defaults to
            the mindmap filename.
        max_rounds: per-case recompile cap (default 3).

    Returns:
        Result summary; full report at workspace/outputs/<out_name>/delivery_report.md,
        machine-readable at engine_report.json, facts at facts.jsonl.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from main.ist_core.compile_engine_v8.graph import build_v8_graph
    from main.ist_core.compile_engine_v8 import _shared as sh

    name = (out_name or Path(mindmap_path).stem).strip()
    root = sh.project_root()
    db = root / "runtime" / "compile_engine_v8_checkpoints.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SqliteSaver.from_conn_string(str(db)) as saver:
            g = build_v8_graph(checkpointer=saver)
            cfg = {"configurable": {"thread_id": f"v8:{name}"}, "recursion_limit": 200}
            state = {"mindmap_path": mindmap_path, "product_version": product_version,
                     "out_name": name, "max_rounds": int(max_rounds or 3)}
            res = g.invoke(state, cfg)
            rounds = 0
            while isinstance(res, dict) and "__interrupt__" in res and rounds < _MAX_INTERRUPT_ROUNDS:
                payload = res["__interrupt__"][0].value
                res = g.invoke(Command(resume=_bridge(payload)), cfg)
                rounds += 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("V8 引擎异常")
        return (f"error: compile engine aborted — {type(exc).__name__}: {exc}\n"
                f"Progress is saved (checkpoint + facts); re-call with the same arguments to resume.")

    rp = sh.outputs_root() / name / "engine_report.json"
    if not rp.is_file():
        return f"error: engine finished without a report (state keys: {sorted((res or {}).keys())[:12]})"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    t = rep.get("totals", {})
    lines = [
        f"compile engine (v8) done: {rep.get('outcome')}",
        f"cases {t.get('cases', 0)}: deliverable {t.get('deliverable', 0)}"
        + (f", labels {json.dumps({k: v for k, v in t.items() if k not in ('cases', 'deliverable') and v}, ensure_ascii=False)}"
           if any(v for k, v in t.items() if k not in ("cases", "deliverable")) else ""),
        f"full report (on disk): workspace/outputs/{name}/delivery_report.md",
        f"facts ledger: {rep.get('refs', {}).get('facts')}",
    ]
    return "\n".join(lines)
