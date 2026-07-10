"""submit_ask_panel:归因孔的 ought-欠定呈报面板(DESIGN §11.11 构件一)。

设计依据:THEORY §2.6——实验只能建立实然,应然属于意图所有者;两意图投影冲突且
选边即改写某方意图(同形判据)时,引擎呈报差异+自身理解,由用户确认后继续。
schema 走 strict 工具通道(mimo 实测:response_format 双形态不守约,strict 工具满分);
verbatim 双侧门与 submit_attribution 同型(防转述失真);retrieval_receipt 必填=
「空手问」在 schema 层不可能(检索先于 ask,A9)。
"""

from __future__ import annotations

import difflib
import json
import logging
import time
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CONFLICT_SHAPES = ("manual_vs_device", "expected_vs_observed",
                   "method_vs_implementation", "ordering_vs_persistence", "other")
RECEIPT_OUTCOMES = ("miss", "hit_conflicting", "hit_adopted_blocked")


class _Side(BaseModel):
    """One conflicting record (a side of the discrepancy)."""
    source_ref: str = Field(description=(
        'Where the quote lives: "device_context" (or the last_run path) for device-side '
        "evidence; a repo-relative doc path (manual / mindmap markdown) for document-side."))
    quote: str = Field(description=(
        "Verbatim substring of that source — copy character-for-character, never retell; "
        "single-line fragments are safest (gate-checked)."))
    anchor: str | None = Field(description=(
        "Version/date anchor of this record (e.g. manual version, device build), or null."))


class _Receipt(BaseModel):
    """One retrieval you performed before asking."""
    slug: str = Field(description=(
        'What you searched, as a short slug (until the intent-search tool lands, use '
        '"manual_declared").'))
    outcome: Literal["miss", "hit_conflicting", "hit_adopted_blocked"] = Field(
        description="miss = nothing found; hit_conflicting = records disagree; "
                    "hit_adopted_blocked = a record matched but contradicts the live device.")


class AskPanelArgs(BaseModel):
    """submit_ask_panel arguments (strict schema: flat, all required, enums lowercase)."""
    last_run_path: str = Field(description=(
        "The brief's last_run_path (run ledger; device-side quotes are gate-checked "
        "against this case's raw text in it)."))
    autoid: str = Field(description="The case's full autoid (must exist in last_run.json).")
    intent_signature: str = Field(description=(
        "Short semantic slug naming the disputed intent, lowercase-hyphen "
        '(e.g. "rr-new-member-tail-position") — becomes the adjudication key.'))
    conflict_shape: Literal["manual_vs_device", "expected_vs_observed",
                            "method_vs_implementation", "ordering_vs_persistence",
                            "other"] = Field(description="The discrepancy's shape.")
    version_family: str = Field(description=(
        'Product version family this dispute belongs to (e.g. "10.5" or the brief\'s '
        "device_build)."))
    sides: list[_Side] = Field(description=(
        ">=2 conflicting records; at least the two whose conflict you are reporting."))
    retrieval_receipt: list[_Receipt] = Field(description=(
        ">=1 records of what you searched before asking — asking without having searched "
        "is rejected."))
    hypothesis: str = Field(description=(
        "Your best understanding of which side should win and why — in Chinese, shown "
        "to the user verbatim."))
    ask: str = Field(description="One Chinese question sentence the user will be asked.")

# device 侧语料字段(与 submit_attribution 的 evidence 门同一语料面)
_DEVICE_CORPUS_KEYS = ("device_context", "causality", "detail_tail", "framework_traceback")


def _norm(s: str) -> str:
    """字面转义还原+空白折叠(与 submit_attribution 门同源:防编造,不防序列化失真)。"""
    s = s.replace("\\r", " ").replace("\\n", " ").replace("\\t", " ")
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(s.split())


def _closest_line(quote: str, corpus: str) -> str:
    """poka-yoke 反馈素材:语料里与 quote 最相似的一行(供模型自纠,非判定)。"""
    lines = [ln.strip() for ln in corpus.splitlines() if ln.strip()]
    if not lines:
        return ""
    got = difflib.get_close_matches(_norm(quote), [_norm(ln) for ln in lines],
                                    n=1, cutoff=0.1)
    if not got:
        return ""
    idx = [_norm(ln) for ln in lines].index(got[0])
    return lines[idx][:200]


def _coerce_list(value, field: str) -> tuple[list | None, str]:
    """原生数组首选,JSON 字符串双收(非 strict 供应商序列化兜底)。"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:  # noqa: BLE001
            return None, (f"error: {field} must be a JSON array (got an unparseable "
                          f"string) — pass a native array, or a JSON-encoded array string")
    if not isinstance(value, list):
        return None, f"error: {field} must be an array of objects, got {type(value).__name__}"
    return value, ""


@tool(args_schema=AskPanelArgs)
def submit_ask_panel(last_run_path: str, autoid: str, intent_signature: str,
                     conflict_shape: str, version_family: str,
                     sides, retrieval_receipt,
                     hypothesis: str, ask: str) -> str:
    """Report an intent-level (ought) underdetermination for one case: two intent projections conflict and picking a side would rewrite someone's intent — file the discrepancy so the engine can present it to the user for confirmation.

    **When to use**: experiments established what the device DOES, but what it SHOULD do is
    owned by the case author / developers — e.g. the manual's command form disagrees with the
    live device, the mindmap's expected result disagrees with observed behavior, or the case's
    verification method disagrees with how the feature is implemented. You state both sides
    verbatim plus your best understanding; the user confirms, corrects, or declares a defect.
    **When not to use**: the fix is derivable from evidence alone (just recompile with it);
    or evidence is merely insufficient (that is reflow with a named missing observation, not
    a user question).

    This does NOT replace submit_attribution — file your layer verdict as usual; the panel
    rides alongside it.

    Returns confirmation (path written); on validation failure an error naming the field, the
    expected shape, and the closest matching line for verbatim mismatches.
    """
    aid = (autoid or "").strip()
    shape = (conflict_shape or "").strip().lower()
    if shape not in CONFLICT_SHAPES:
        return (f"error: conflict_shape must be one of {'/'.join(CONFLICT_SHAPES)}, "
                f"got {conflict_shape!r}")
    if not (intent_signature or "").strip():
        return "error: intent_signature is required — a short lowercase-hyphen slug naming the disputed intent"
    if not (hypothesis or "").strip():
        return "error: hypothesis is required — state your best understanding (Chinese; shown to the user)"
    if not (ask or "").strip():
        return "error: ask is required — one Chinese question sentence for the user"

    # args_schema 通道给 pydantic 模型实例,直调 .func 可能给裸 dict/JSON 字符串——统一成 dict
    if isinstance(sides, list):
        sides = [s.model_dump() if hasattr(s, "model_dump") else s for s in sides]
    if isinstance(retrieval_receipt, list):
        retrieval_receipt = [r.model_dump() if hasattr(r, "model_dump") else r
                             for r in retrieval_receipt]
    sides_l, err = _coerce_list(sides, "sides")
    if err:
        return err
    if len(sides_l) < 2:
        return ("error: sides needs >=2 entries — a discrepancy has at least two conflicting "
                "records (e.g. one device-side quote + one document-side quote); got "
                f"{len(sides_l)}")
    receipt_l, err = _coerce_list(retrieval_receipt, "retrieval_receipt")
    if err:
        return err
    if len(receipt_l) < 1:
        return ("error: retrieval_receipt needs >=1 entry — asking without having searched is "
                "not allowed; record what you looked up (slug + outcome). Until the intent-search "
                "tool lands, use {\"slug\": \"manual_declared\", \"outcome\": \"miss\"}")
    for i, r in enumerate(receipt_l):
        if not isinstance(r, dict) or not str(r.get("slug") or "").strip():
            return f"error: retrieval_receipt[{i}] must be an object with a non-empty slug"
        oc = str(r.get("outcome") or "").strip().lower()
        if oc not in RECEIPT_OUTCOMES:
            return (f"error: retrieval_receipt[{i}].outcome must be one of "
                    f"{'/'.join(RECEIPT_OUTCOMES)}, got {r.get('outcome')!r}")
        r["outcome"] = oc

    # last_run 定位(与 submit_attribution 同型:直传 last_run.json 或旁路 xlsx)
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        xp = _resolve_inside_root(last_run_path, must_exist=True)
    except Exception:  # noqa: BLE001
        xp = None
    p = Path(xp) if xp else Path(last_run_path)
    lr = p if p.name == "last_run.json" else p.parent / "last_run.json"
    if not lr.is_file():
        return f"error: last_run.json does not exist: {lr} — pass the brief's last_run_path"
    try:
        records = json.loads(lr.read_text(encoding="utf-8"))
        assert isinstance(records, list)
    except Exception as e:  # noqa: BLE001
        return f"error: failed to read last_run.json: {e}"
    rec = next((r for r in records if isinstance(r, dict) and str(r.get("autoid")) == aid), None)
    if rec is None:
        have = [str(r.get("autoid")) for r in records if isinstance(r, dict)][:8]
        return f"error: autoid {aid} not in last_run.json (present: {', '.join(have)}…)"
    device_corpus = "\n".join(str(rec.get(k) or "") for k in _DEVICE_CORPUS_KEYS)

    # verbatim 双侧门:device 侧对 last_run 原文,doc 侧对源文件(多根沙箱内)
    checked = []
    for i, s in enumerate(sides_l):
        if not isinstance(s, dict):
            return f"error: sides[{i}] must be an object {{source_ref, quote, anchor}}"
        src = str(s.get("source_ref") or "").strip()
        quote = str(s.get("quote") or "").strip()
        if not src or not quote:
            return f"error: sides[{i}] needs non-empty source_ref and quote"
        if src in _DEVICE_CORPUS_KEYS or "last_run" in src or src == "device":
            corpus, corpus_name = device_corpus, f"this case's device raw text in {lr.name}"
        else:
            try:
                from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
                fp = Path(_resolve_inside_root(src, must_exist=True))
                corpus = fp.read_text(encoding="utf-8", errors="ignore")
                corpus_name = src
            except Exception:  # noqa: BLE001
                return (f"error: sides[{i}].source_ref {src!r} is neither a device corpus "
                        f"key ({'/'.join(_DEVICE_CORPUS_KEYS)}) nor a readable file path — "
                        f"point it at the manual/mindmap markdown you quoted")
        if quote not in corpus and _norm(quote) not in _norm(corpus):
            near = _closest_line(quote, corpus)
            return (f"error: sides[{i}].quote is not a verbatim substring of {corpus_name} — "
                    f"copy it character-for-character, never retell. "
                    + (f"Closest line in the source: {near!r}" if near
                       else "No similar line found — check source_ref points at the right document."))
        checked.append({"source_ref": src, "quote": quote[:2000],
                        "anchor": (str(s.get("anchor")).strip() or None)
                        if s.get("anchor") is not None else None,
                        "_is_device": corpus is device_corpus})

    # 形态-侧别一致门:声称「记载 vs 实机」的差异,记载侧必须以原文出场——
    # 否则文档侧意图只活在 hypothesis 的转述里,verbatim 门形同虚设
    if shape in ("manual_vs_device", "expected_vs_observed", "method_vs_implementation"):
        if all(c["_is_device"] for c in checked):
            return (f"error: conflict_shape={shape} claims a record-vs-device discrepancy, but "
                    "every side quotes the device corpus — add >=1 side quoting the record "
                    "itself (manual / mindmap markdown path as source_ref), so the user "
                    "adjudicates two originals, not your retelling.")
    for c in checked:
        c.pop("_is_device", None)

    panel = {
        "autoid": aid,
        "intent_signature": intent_signature.strip().lower(),
        "conflict_shape": shape,
        "version_family": str(version_family or "").strip(),
        "sides": checked,
        "retrieval_receipt": [{"slug": str(r.get("slug")).strip(), "outcome": r["outcome"]}
                              for r in receipt_l],
        "hypothesis": hypothesis.strip(),
        "ask": ask.strip(),
        "_round": rec.get("_round"),
        "ts": time.time(),
    }
    # 常规布局:outputs/<batch>/last_run.json 与 outputs/<aid>/ 平级(引擎在此收割)
    out_dir = lr.parent.parent / aid
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "ask_panel.json"
    dst.write_text(json.dumps(panel, ensure_ascii=False, indent=2), encoding="utf-8")
    return (f"ask panel filed: {dst} (shape={shape}, sides={len(checked)}, "
            f"receipt={len(panel['retrieval_receipt'])}). The engine will present it to the "
            f"user at the ask edge; continue with submit_attribution as usual.")
