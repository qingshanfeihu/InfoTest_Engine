"""自愈环入库件(V6 验收资产迁入 V8;2026-07-16 A2′ 观察级判据换轴):
uncertain 观察入库 + PASS 行为晋升 + 行为知识 feature head。"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from main.ist_core.compile_engine_v8 import _shared as sh

logger = logging.getLogger(__name__)

# 时间戳形态 token(内容归一化剥除面):同一观察跨轮携带不同时间戳时,逐字 hash 的
# fact_key 每轮都新——幂等被绕过,纯计数触发的观察组会被跨轮重复伪造成"多语境"。
# 只剥时间戳,不剥语义数字(Hit:0 的 0 是观察身份的一部分,剥了会把异观察撞成同键)。
_TS_TOKEN = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?|\b\d{2}:\d{2}:\d{2}\b")


def _normalize_observation(content: str) -> str:
    """观察内容归一化(去重键用;入库 content 保原文):剥时间戳 + 折叠空白。"""
    return " ".join(_TS_TOKEN.sub("<ts>", str(content or "")).split())


def _behavior_feature_head(cmd: str) -> list[str]:
    """观测命令 → 行为知识挂载的叶节点路径 token(剥算子动词与参数值)。

    uncertain 入库与 PASS 晋升**必须同函数**取 head——两路 feature_path/fact_key 同源,
    同一观察的 uncertain→verified 升级(merger 按 fact_key 对齐)才遇得上。动词表来自
    文法数据(domain_grammar verb_classes),不再各处手写((no,show,clear) 硬编码曾与
    文法漂移,红线评审 2026-07-08 低危项)。参数值 token(数字/IP/含点)剥掉只留命令词。
    """
    from main.case_compiler import domain_grammar as _dg
    strip = set(_dg.verbs("mutating") + _dg.verbs("config_query_probes"))
    return [t for t in (cmd or "").split()
            if t.lower() not in strip and t.isalpha()] or (cmd or "").split()[:1]


def _ingest_uncertain_observations(led) -> None:
    """非 pass 案的行为观察以 uncertain 级入库(自愈环入库端;2026-07-16 A2′ 换轴)。

    门键=**观察级判据**,不再按案终态枚举白名单(旧门只收 failed_terminal+escalated,
    suspended/failed/contradicted 案的 defect_candidate 级观察整体丢弃——zhaiyq 532862
    实证;按终态加枚举值是 THEORY §2.7.6 所禁的增长方式,门键挂错轴):
    - 源窗口 ok:broken 三态案由调用侧排除((43) 吸收态——失真窗口上的"观察"不是观察);
    - verbatim 证据在:behavior_candidates 经 submit_behavior_fact 卷面命令门背书,
      attributor 结构化观察经 submit_attribution 子串门背书(evidence=="user" 的裁决
      记账行在合成侧排除);
    - 案终态只作 observed_under 语境标注,不作准入条件。

    数据源双通道(C5 生产侧兜底):led.observation_cases() 给 (aid, 语境标签),
    led.extra_candidates(aid) 给 attributor 结构化观察机械转的候选(777976/593516 型
    从不自愿调 submit_behavior_fact 的案,其归因 verbatim 证据是仅存的设备观察)。
    旧 led(只有 in_state)自动回退旧行为(兼容外部演练脚本)。

    与 _promote_behavior_candidates 的分工:PASS 候选走 device_verified 门升 verified;
    非 pass 候选**不冒充 verified**——RawFact 带 validity="uncertain" + observed_under
    语境短句,渲染层按观察组并列展示。fact_key 用**归一化内容** hash(时间戳剥离)——
    逐字 hash 会被跨轮时间戳绕过幂等,纯计数观察组被重复伪造成多语境。同 fact_key 将来
    PASS 实证时由 merger 升级分支就地转 verified。``FOOTPRINT_UNCERTAIN_WRITEBACK=0`` 关。
    """
    if not sh.env_flag("FOOTPRINT_UNCERTAIN_WRITEBACK"):
        return
    import hashlib
    from main.ist_core.memory.footprint.schema import RawFact
    from main.ist_core.memory.footprint.router import route_facts
    from main.ist_core.memory.footprint.merger import merge_fact
    from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS
    if hasattr(led, "observation_cases"):
        pairs = list(led.observation_cases())
    else:   # 旧适配器回退(终态枚举旧轴)
        pairs = [(a, "") for a in (led.in_state("failed_terminal")
                                   + led.in_state("escalated"))]
    ingested = 0
    for aid, label in pairs:
        cands = list(sh.read_json(sh.outputs_root() / aid / "behavior_candidates.json", []) or [])
        if hasattr(led, "extra_candidates"):
            cands += list(led.extra_candidates(aid) or [])
        seen_keys: set[str] = set()
        for c in cands:
            cmd = str(c.get("observe_cmd") or "").strip()
            content = str(c.get("content") or "").strip()
            if not cmd or not content:
                continue
            note = str(c.get("note") or "").strip()
            ctx = (note[:120] if note
                   else f"{label or 'fail/escalated 轮观察'}(autoid …{aid[-6:]}),"
                        f"配置形态见该批取证")
            head = _behavior_feature_head(cmd)
            key = (f"{' '.join(head)}:"
                   f"{hashlib.sha1(_normalize_observation(content).encode()).hexdigest()[:8]}")
            if key in seen_keys:   # 同案内双通道/跨轮时间戳变体去重
                continue
            seen_keys.add(key)
            rf = RawFact(fact_kind="behavior", feature_path=head,
                         fact_key=key,
                         cli_syntax=cmd, content=content,
                         device_evidence={"autoid": aid, "run_ts": None},
                         source_thread=f"engine_uncertain:{aid}",
                         validity="uncertain", observed_under=ctx)
            try:
                for routed in route_facts([rf], Path(KNOWLEDGE_FOOTPRINTS)):
                    if merge_fact(routed, Path(KNOWLEDGE_FOOTPRINTS)).action != "skip":
                        ingested += 1
                        from main.ist_core.memory.footprint.signals import emit_signal
                        emit_signal("uncertain_ingested", rf.fact_key,
                                    source="closing._ingest_uncertain_observations",
                                    autoid=aid, observed_under=ctx)
            except Exception:  # noqa: BLE001
                continue
    if ingested:
        sh.emit(f"未定观察入库 {ingested} 条(uncertain 级,PASS 实证后自动升级)")


def _promote_behavior_candidates(aid: str, led) -> None:
    """行为候选晋升(V6 支柱2b 两段闸第二段):case 真 PASS 才把候选转
    RawFact(behavior)+device_evidence 入库——merger 的 device_verified 门再校验
    「观测命令真实出现在该 PASS 卷面」。fail/awaiting 的候选永不到这里。
    ``FOOTPRINT_BEHAVIOR_WRITEBACK=0`` 关。"""
    if not sh.env_flag("FOOTPRINT_BEHAVIOR_WRITEBACK"):
        return
    cand_path = sh.outputs_root() / aid / "behavior_candidates.json"
    cands = sh.read_json(cand_path, []) or []
    if not cands:
        return
    # 该 aid 最近一条 PASS 台账(device_evidence 锚)
    ledger_file = sh.project_root() / "runtime" / "logs" / "verified_runs.jsonl"
    ref = None
    if ledger_file.is_file():
        for line in ledger_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if str(rec.get("autoid")) == aid and str(rec.get("verdict")) == "pass":
                ref = {"autoid": aid, "run_ts": rec.get("run_ts")}
                if rec.get("build"):   # K 锚 build 位透传(理论 §5.1)
                    ref["build"] = str(rec["build"])
    if ref is None:
        return
    import hashlib
    from main.ist_core.memory.footprint.schema import RawFact
    from main.ist_core.memory.footprint.router import route_facts
    from main.ist_core.memory.footprint.merger import merge_fact
    from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS
    promoted = 0
    for c in cands:
        cmd = str(c.get("observe_cmd") or "").strip()
        content = str(c.get("content") or "").strip()
        if not cmd or not content:
            continue
        # 行为知识挂**叶节点**(剥前缀后全 token):截 2 段会落父节点,而 lookup
        # 对父节点只展开子树命令、不渲染父自身 behaviors——知识存了却读不回
        # (2026-07-06 种子实证)。head 取法与 uncertain 入库同函数(升级对齐);
        # fact_key 同用归一化内容 hash——两路不同源,uncertain→verified 升级遇不上。
        head = _behavior_feature_head(cmd)
        rf = RawFact(fact_kind="behavior", feature_path=head,
                     fact_key=(f"{' '.join(head)}:"
                               f"{hashlib.sha1(_normalize_observation(content).encode()).hexdigest()[:8]}"),
                     cli_syntax=cmd, content=content,
                     device_evidence=dict(ref),
                     source_thread=f"engine_behavior:{aid}")
        try:
            for routed in route_facts([rf], Path(KNOWLEDGE_FOOTPRINTS)):
                if merge_fact(routed, Path(KNOWLEDGE_FOOTPRINTS)).action != "skip":
                    promoted += 1
        except Exception:  # noqa: BLE001
            continue
    if promoted:
        sh.emit(f"{aid[-6:]} 行为知识晋升 {promoted} 条")
