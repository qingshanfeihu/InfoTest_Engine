"""Footprint merger：把 RoutedFact 按 fact_kind + fact_key 写入对应 schema 字段。

设计原则：
- 不再做关键词正则判断 slot
- (fact_kind, fact_key) 作为同一节点内的唯一指纹做 dedup
- level gating 已由 router 做完，这里只按 fact_kind 分发
- evidence 验证闸：cli/rule/behavior 必须能在 evidence_file 中实际 grep 到 evidence_quote
  片段，否则 skip — 防止 LLM 幻觉/agent thought 复述污染
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from main.ist_core.memory.footprint.schema import (
    LEVEL_KINDS,
    MergeResult,
    RoutedFact,
    TEMPLATE_MAP,
)

logger = logging.getLogger(__name__)



_LINE_PREFIX_RE = re.compile(r"^\s*\d+:\s*")

_ELLIPSIS_RE = re.compile(r"\.{3,}")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]



_MARKDOWN_ROOT = ("knowledge", "data", "markdown")


def _resolve_evidence_path(evidence_file: str) -> Path | None:
    """把 evidence_file 解析为可读的绝对路径——**拒绝落在 agent 可写区(workspace)内的文件**。

    安全（评审中危：幻觉命令注入）：evidence_file 可能含 agent 输入（如 verify 写回的 manual_glob）。
    evidence 门的信任前提是证据源**只读、非 agent 掌控**；若 evidence_file 指向 agent 自己 fs_write
    到 `workspace/outputs/` 的文件，门就被架空——agent 把命令写进该文件即 100% 过门、往 footprint
    注入幻觉命令。故拒绝 workspace 内的证据（agent 唯一可写区，正是攻击面）；md_root / 手册 / 框架
    mirror 等只读源照常。
    不硬编码具体子目录（product/qa/...），在 markdown 树下通用解析：
    1. 当路径解析，但**不得落在 workspace 内**
    2. 在 knowledge/data/markdown 下按 basename 递归匹配（结果天然在只读手册根内）
    """
    if not evidence_file:
        return None
    root = _project_root()

    def _in_workspace(p: Path) -> bool:
        try:
            p.resolve().relative_to((root / "workspace").resolve())
            return True
        except ValueError:
            return False

    direct = (root / evidence_file).resolve()
    if direct.is_file() and not _in_workspace(direct):
        return direct

    md_root = root.joinpath(*_MARKDOWN_ROOT)
    if not md_root.is_dir():
        return None

    name = Path(evidence_file).name
    if not name:
        return None

    for p in md_root.rglob(name):   # md_root 内,天然非 workspace
        if p.is_file():
            return p
    return None


_BR_RE = re.compile(r"<br\s*/?>")

# CJK 字符相邻的空白是排版/硬换行产生的，**不是词边界**（中文词间无空格）。手册把一句话
# 硬换行成多行（如 "类型的DNS" 换行后接 "解析请求"），" ".join(s.split()) 把换行归一成空格
# → "DNS 解析"，而 LLM 引的是连续句 "DNS解析" → 失配；长 quote 跨换行点被切成两段、均 <60%
# 覆盖率 → rule/behavior 被证据门假阴性丢弃。比对前删掉 CJK 相邻空白即可对齐（英文词间空格如
# "Canonical Name" / "show version" 因两侧非 CJK 而保留，不受影响）。
# 范围：CJK 标点 U+3000-303F、扩展A U+3400-4DBF、统一表意 U+4E00-9FFF、全角符号 U+FF00-FFEF。
_CJK_RANGE = "\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef"
_CJK_SPACE_RE = re.compile(rf"(?<=[{_CJK_RANGE}])\s+|\s+(?=[{_CJK_RANGE}])")


def _normalize(s: str) -> str:
    r"""归一化行号、省略号、`<br>`/硬换行、markdown 强调、空白，便于子串匹配。

    手册参数表/注意段用 `<br>` 软换行、正文用硬换行 `\n` 把一句话拆成多段，LLM 引用的是
    清洗后的连续句 → 原文最长连续逐字命中 <60% → rule/behavior 被证据门假丢弃。比对前把
    `<br>`/`**` 规整掉、并删除 CJK 相邻空白(中文换行非词边界)，碎句才能与连续 quote 对齐。
    """
    s = _LINE_PREFIX_RE.sub("", s)
    s = _ELLIPSIS_RE.sub("", s)
    s = _BR_RE.sub("", s)          # <br> 软换行直接接上(中文无词间空格,LLM 引的是连续句)
    s = s.replace("**", "").replace("　", " ")
    s = " ".join(s.split())        # 多空白(含硬换行 \n)→单空格
    return _CJK_SPACE_RE.sub("", s)  # 删 CJK 相邻空白(硬换行非词边界;英文词间空格保留)


import math



_EVIDENCE_COVERAGE = 0.6


def _covers_quote(quote: str, haystack: str) -> bool:
    """quote 中是否存在长度 ≥ 60% 的连续子串逐字出现在 haystack 里。

    只需检测一个长度 L=ceil(0.6·len)：若某条长度 L 的窗口命中，则最长连续
    匹配 ≥ L，覆盖率达标；若无一命中，则最长匹配必 < L，不达标。无需二分。
    quote ≤300 字符，窗口数 ≈ 0.4·len（最多 ~120 次 C 级 `in`），单次校验亚百毫秒。
    """
    n = len(quote)
    if n == 0:
        return False
    L = math.ceil(n * _EVIDENCE_COVERAGE)
    for i in range(0, n - L + 1):
        if quote[i:i + L] in haystack:
            return True
    return False


_VERIFIED_RUNS_LEDGER = ("runtime", "logs", "verified_runs.jsonl")


def _device_evidence_supports(fact) -> bool:
    """device_verified 权威源(V6 支柱2a):fact.device_evidence={autoid, run_ts} 指向
    runtime/logs/verified_runs.jsonl 的一条台账(digest 工具进程写;runtime/ 在 agent
    文件沙箱黑名单内,agent 伪造不了)。三重校验——台账条目存在 ∧ verdict==pass ∧
    命令真实出现在该 PASS 卷面的 APV 命令列表里。**门没有放松**:幻觉命令(不在卷面)
    照拒、fail 卷照拒;强度=设备真实接受过这条命令且整 case 上机通过。
    ``IST_WRITEBACK_DEVICE_AUTHORITY=0`` 关闭本分支(回手册单权威)。
    """
    import os as _os
    if (_os.environ.get("IST_WRITEBACK_DEVICE_AUTHORITY") or "1").strip().lower() in ("0", "false", "no"):
        return False
    dev = getattr(fact, "device_evidence", None) or {}
    aid = str(dev.get("autoid") or "").strip()
    run_ts = dev.get("run_ts")
    cmd = (getattr(fact, "cli_syntax", "") or getattr(fact, "content", "") or "").strip()
    if not aid or run_ts is None or not cmd:
        return False
    ledger = _project_root().joinpath(*_VERIFIED_RUNS_LEDGER)
    if not ledger.is_file():
        return False
    try:
        for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if (str(rec.get("autoid")) == aid
                    and abs(float(rec.get("run_ts", -1)) - float(run_ts)) < 1e-6
                    and str(rec.get("verdict")) == "pass"):
                cmds = [str(c).strip() for c in (rec.get("apv_cmds") or [])]
                body = re.split(r"[<\[{]", cmd)[0].strip()
                return any(c == cmd or (body and c.startswith(body)) for c in cmds)
    except OSError:
        return False
    return False


def _evidence_supports(fact) -> bool:
    """验证 evidence_quote 能在 evidence_file 中真实命中。

    known_issue 类型有 issue_id 自带凭证，不走这个闸。
    cli/rule/behavior 缺 evidence_quote 或 evidence_file 直接判 false。
    device_evidence 非空时优先走 _device_evidence_supports(第二权威源,V6 支柱2a)。

    判定：
    1. 归一化后整段子串命中 → 通过（LLM 老实引用的常见情形）
    2. 否则按覆盖率：quote 中最长的逐字命中片段 ≥ quote 长度的 60% → 通过
       （容忍 LLM 在首尾轻微改写/补字，但不容忍整体编造）
    覆盖率与语言、quote 绝对长度无关，不再用 `>=N 字符` 这种硬阈值。
    """
    if getattr(fact, "device_evidence", None):
        # uncertain 级观察(2026-07-08 自愈环):fail/escalated 轮的设备观察没有 PASS
        # 台账可锚(pass-voucher 查证必假),但它的锚定已由上游两道门保证——behavior_tool
        # 入口"observe_cmd 必在该 case 卷面"(卷面机械校验) + device_evidence 记 autoid。
        # 放行条件:validity 明确为 uncertain ∧ 有 autoid ∧ 有观测命令。入库后带
        # uncertain 标记渲染,不冒充 verified;同 fact_key 将来 PASS 实证时升级(见
        # _append_behavior 的升级分支)。此前"fail 候选永不入库"把最有信息量的 episode
        # 整体丢弃(pe1 570/608 实证:正解形态卡在知识断层外)。
        if (getattr(fact, "validity", "") or "").strip() == "uncertain":
            dev = fact.device_evidence or {}
            cmd = (getattr(fact, "cli_syntax", "") or getattr(fact, "content", "") or "").strip()
            return bool(str(dev.get("autoid") or "").strip() and cmd)
        if _device_evidence_supports(fact):
            return True
        # 设备证据校验不过时**不回落手册**——传了 device_evidence 表示调用方明知
        # 该命令不在手册,校验失败即拒(防"传个假 ref 混过手册分支"的绕行)。
        return False

    if not fact.evidence_quote or not fact.evidence_file:
        return False

    path = _resolve_evidence_path(fact.evidence_file)
    if path is None:
        return False

    try:
        haystack = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    haystack_norm = _normalize(haystack)

    quote = _normalize(fact.evidence_quote)
    if quote and (quote in haystack_norm or _covers_quote(quote, haystack_norm)):
        return True

    # cli_command 兜底：LLM 的 quote 偶尔整体改写不达标,但命令本身是 ground truth——
    # 命令主体的粗体签名 `**cmd**` 逐字在手册原文里 → 命令真实存在(非编造),放行。
    # 修掉「命令明明在手册、却因 LLM quote 改写被整条毙掉」的门误拒(单遍漏命令的一个原因)。
    if getattr(fact, "fact_kind", "") == "cli_command":
        cmd = (getattr(fact, "cli_syntax", "") or "").strip()
        body = re.split(r"[<\[{]", cmd)[0].strip()
        if body and _normalize(f"**{body}**") in haystack_norm:
            return True

    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _update_meta(fp: dict, source_thread: str, *, count_verified: bool = True) -> None:
    meta = fp.setdefault("footprint_meta", {})
    if not meta.get("created_at"):
        meta["created_at"] = _now_iso()
    # uncertain 观察入库不累计 verified_count——节点头的 `verified Nx` 是权威度信号,
    # 未实证观察计入=冒充(红线评审 2026-07-08 中危项);升级 verified 时那次 merge 会计。
    if count_verified:
        meta["verified_count"] = meta.get("verified_count", 0) + 1
    threads = meta.setdefault("source_threads", [])
    if source_thread and source_thread not in threads:
        threads.append(source_thread)
        if len(threads) > 10:
            threads[:] = threads[-10:]


def _evidence(fact) -> dict:
    ev: dict = {}
    if fact.evidence_file:
        ev["source_file"] = fact.evidence_file
    if fact.evidence_quote:
        ev["quoted_text"] = fact.evidence_quote
    # K 锚持久化(理论 §5.1 anchor=(build, run_ts, lineage)):设备实证的条目把运行锚
    # 落进 evidence.device_run——没有它,后续 build 锚差派生 stale(缺口 C)无数据可算。
    # 缺位诚实缺位(autoid 有而 run/build 无=uncertain 级观察只有谱系锚),不造值。
    dev = getattr(fact, "device_evidence", None) or {}
    if dev.get("autoid"):
        run: dict = {"autoid": str(dev["autoid"])}
        if dev.get("run_ts"):
            run["run_ts"] = dev["run_ts"]
        if dev.get("build"):
            run["build"] = str(dev["build"])
        ev["device_run"] = run
    return ev


def _merge_parameters(existing: list[dict], incoming: list[dict]) -> bool:
    """按 name 合并参数表。新增缺失参数 / 补全已有参数空字段。返回是否有变更。"""
    changed = False
    by_name = {p.get("name"): p for p in existing if p.get("name")}
    for inc in incoming:
        name = inc.get("name")
        if not name:
            continue
        if name not in by_name:
            existing.append(inc)
            by_name[name] = inc
            changed = True
            continue
        cur = by_name[name]
        for k, v in inc.items():
            if k == "name":
                continue
            if v not in (None, "") and not cur.get(k):
                cur[k] = v
                changed = True
    return changed


def _append_cli_command(fp: dict, fact) -> str:
    """按完整 cli_syntax 去重（非 fact_key）。

    同一 feature_id 下，no/show/clear/配置 四态是不同命令，各自完整形态并存：
      slb real http <rs_name>   (配置)
      no slb real http          (否定/删除)
      show slb real http        (查询)
      clear slb real http       (清除)
    它们 feature_path 相同（C1 剥前缀后归一），但 cli_syntax 不同 → 都保留。
    只有 cli_syntax 完全相同才视为重复，此时合并参数表（补全而非丢弃）。
    """
    commands = fp.setdefault("cli", {}).setdefault("commands", [])
    syntax = fact.cli_syntax.strip()
    for existing in commands:
        if existing.get("command", "").strip() == syntax:
            if fact.parameters:
                changed = _merge_parameters(
                    existing.setdefault("parameters", []), fact.parameters
                )
                return "append" if changed else "skip"
            return "skip"
    entry = {
        "fact_key": fact.fact_key,
        "command": fact.cli_syntax,
        "evidence": _evidence(fact),
    }
    if fact.parameters:
        entry["parameters"] = fact.parameters
    commands.append(entry)
    return "append"


def _append_decision_rule(fp: dict, fact) -> str:
    rules = fp.setdefault("decision_rules", [])
    for existing in rules:
        if existing.get("fact_key") == fact.fact_key:
            return "skip"
    rules.append({
        "fact_key": fact.fact_key,
        "condition": fact.condition,
        "decision": fact.decision,
        "evidence": _evidence(fact),
    })
    return "append"


def _append_behavior(fp: dict, fact) -> str:
    behaviors = fp.setdefault("behaviors", [])
    validity = (getattr(fact, "validity", "") or "verified").strip() or "verified"
    observed_under = (getattr(fact, "observed_under", "") or "").strip()
    for existing in behaviors:
        if existing.get("fact_key") == fact.fact_key:
            # 升级分支(自愈环演化端):同 fact_key 的 uncertain 观察,后续 PASS 实证
            # (validity=verified 到达)→ 就地升级并更新内容/证据;反向(verified 已在、
            # uncertain 又来)不降级、不覆盖。
            if existing.get("validity") == "uncertain" and validity == "verified":
                existing["content"] = fact.content or existing.get("content", "")
                existing["evidence"] = _evidence(fact)
                existing["validity"] = "verified"
                if observed_under:
                    existing["observed_under"] = observed_under
                try:
                    from main.ist_core.memory.footprint.signals import emit_signal
                    emit_signal("upgraded_verified", fact.fact_key,
                                source="merger._append_behavior",
                                autoid=str((fact.device_evidence or {}).get("autoid") or ""))
                except Exception:  # noqa: BLE001
                    pass
                return "update"
            return "skip"
    entry = {
        "fact_key": fact.fact_key,
        "content": fact.content,
        "evidence": _evidence(fact),
    }
    # 观察级字段(判例化):非默认才写,verified 且无语境的旧形态条目保持原样干净。
    if validity != "verified":
        entry["validity"] = validity
    if observed_under:
        entry["observed_under"] = observed_under
    behaviors.append(entry)
    return "append"


def _append_known_issue(fp: dict, fact) -> str:
    issues = fp.setdefault("known_issues", [])
    for existing in issues:
        if existing.get("issue_id") == fact.issue_id:
            
            updated = False
            if fact.issue_title and not existing.get("title"):
                existing["title"] = fact.issue_title
                updated = True
            if fact.affected_versions:
                merged = sorted(set(existing.get("affected_versions", [])) | set(fact.affected_versions))
                if merged != existing.get("affected_versions"):
                    existing["affected_versions"] = merged
                    updated = True
            return "update" if updated else "skip"

    entry: dict[str, Any] = {"issue_id": fact.issue_id}
    if fact.issue_title:
        entry["title"] = fact.issue_title
    if fact.affected_versions:
        entry["affected_versions"] = sorted(set(fact.affected_versions))
        
        if fp.get("level") == "leaf":
            vs = fp.setdefault("version_scope", {})
            cur = set(vs.get("product_versions", []))
            cur.update(fact.affected_versions)
            vs["product_versions"] = sorted(cur)
    issues.append(entry)
    return "append"


def _distinct_observation_contexts(fp: dict) -> set:
    """节点内互异观察语境集(decision_rules+behaviors,与 footprint_lookup 渲染层
    观察组判定同口径——那边是消费端每次查询都算,这里是入库端算迁移)。"""
    out = set()
    for e in (fp.get("decision_rules") or []) + (fp.get("behaviors") or []):
        if isinstance(e, dict):
            ou = (e.get("observed_under") or "").strip()
            if ou:
                out.add(ou)
    return out


_DISPATCH = {
    "cli_command": _append_cli_command,
    "decision_rule": _append_decision_rule,
    "behavior": _append_behavior,
    "known_issue": _append_known_issue,
}


def merge_fact(routed: RoutedFact, footprint_dir: Path) -> MergeResult:
    """把 RoutedFact 写入/合并到目标 footprint 文件。

    level + fact_kind 不匹配（router 已 gating，这里是兜底）→ skip。
    cli/rule/behavior 的 evidence_quote 必须能在 evidence_file 中真实命中，
    否则视为幻觉，skip。
    """
    fact = routed.fact
    target_path = footprint_dir / routed.target_file

    # 安全：写盘前收敛,挡 target_file(含 feature_id)里的 / .. 穿越到 footprint 根外——
    # 与 router 的 feature_id 白名单纵深防御(dream/verify 写核共用此闸)。安全评审高危项。
    try:
        target_path.resolve().relative_to(Path(footprint_dir).resolve())
    except ValueError:
        return MergeResult(action="skip", target_file=routed.target_file,
                           detail="path escapes footprint dir")

    if fact.fact_kind not in LEVEL_KINDS.get(routed.level, set()):
        return MergeResult(action="skip", target_file=routed.target_file, detail="kind not allowed at level")

    
    if fact.fact_kind != "known_issue" and not _evidence_supports(fact):
        return MergeResult(
            action="skip",
            target_file=routed.target_file,
            detail="evidence not found in source file",
        )

    handler = _DISPATCH.get(fact.fact_kind)
    if handler is None:
        return MergeResult(action="skip", target_file=routed.target_file, detail="unknown fact_kind")

    if not target_path.exists():
        template_fn = TEMPLATE_MAP[routed.level]
        fp = template_fn(target_path.stem)
        action = handler(fp, fact)
        if action == "skip":
            return MergeResult(action="skip", target_file=routed.target_file, detail="empty after handler")
        _update_meta(fp, fact.source_thread,
                     count_verified=(getattr(fact, "validity", "") or "verified") != "uncertain")
        _write_json(target_path, fp)
        return MergeResult(action="create", target_file=routed.target_file, detail=fact.fact_kind)

    try:
        fp = json.loads(target_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("footprint read failed %s: %s", target_path, exc)
        return MergeResult(action="skip", target_file=routed.target_file, detail=str(exc))

    _ctx_before = _distinct_observation_contexts(fp)
    action = handler(fp, fact)
    if action == "skip":
        return MergeResult(action="skip", target_file=routed.target_file, detail="duplicate")

    _update_meta(fp, fact.source_thread,
                 count_verified=(getattr(fact, "validity", "") or "verified") != "uncertain")
    _write_json(target_path, fp)
    # 观察组形成信号(→conditional 派生态,理论 §5.2):互异语境数在本次合并中首次
    # 跨过 2——只在入库端的迁移瞬间发一次;渲染端每次查询都会看到组,不发(会刷屏)。
    _ctx_after = _distinct_observation_contexts(fp)
    if len(_ctx_before) < 2 <= len(_ctx_after):
        try:
            from main.ist_core.memory.footprint.signals import emit_signal
            emit_signal("observation_group_formed", target_path.stem,
                        source="merger.merge_fact", fact_key=fact.fact_key,
                        contexts=sorted(_ctx_after)[:6])
        except Exception:  # noqa: BLE001
            pass
    return MergeResult(action=action, target_file=routed.target_file, detail=fact.fact_kind)
