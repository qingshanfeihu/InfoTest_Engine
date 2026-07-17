"""K 信号机：状态迁移与合取违例的统一 append-only 记录（理论 §5.2/审计 §三，2026-07-09）。

设计约束：
- 单一事实流 ``runtime/logs/k_signals.jsonl``——runtime/ 在 agent 文件沙箱黑名单内，
  与 verified_runs.jsonl 同信任根（理论 C5：锚的可信性依赖沙箱）。
- 信号名是**闭集**（SIGNALS），一条状态机迁移对应一个信号——新增迁移先改理论文档
  的迁移表再扩闭集，防止信号语义漂移成自由文本日志。
- emit 失败静默：信号是观测设施，永不阻断主流程。
- 消费方式：``fs_grep <fact_key|autoid> runtime/logs/k_signals.jsonl`` 即得该主体
  全生命周期轨迹（debug 的"这条知识/这个 case 经历了什么"一问一答）；
  DS-1/DS-4 数据集追加可由本流驱动。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# 信号闭集(与 THEORY_k_state_machine.md §5.2 迁移表一一对应;补充见 AUDIT §三)
SIGNALS = frozenset({
    # K 条目生命周期
    "uncertain_ingested",        # fail/escalated 观察入库(absent→uncertain)
    "upgraded_verified",         # PASS 实证升级(uncertain→verified)
    "observation_group_formed",  # 互异语境 ≥2(→conditional,计数派生首达)
    "conflict_declared",         # conflicts_with 追加(→contested)
    "writeback_done",            # 先例/footprint 写回(带 build 锚)
    "stale_flagged",             # build 锚差派生
    "stale_refreshed",           # 复验通过,锚刷新
    "quarantined",               # poisoned 处置(留案底)
    # case 生命周期(第二状态机,与 K 迁移互为因果,同流记录便于关联 debug)
    "frozen",                    # digest 跨轮同签名
    "override_frozen",           # emit 换法声明
    "defect_claim_deferred",     # 形态检验轮触发
    "syntax_help_attached",      # ^→dev_help 读表结果落盘
    "monotonicity_violation",    # 守恒律 ΔI_V<0 拦截
    "intent_gap_flagged",        # 意图↔卷面投影缺口
    "escalated",
    "awaiting_user",
    "user_decided",
    # V8(2026-07-10 验收期转正):终验反证已交付态 / 对账兜底(健康运行恒零)
    "final_verify_failed",
    "verdict_unconsumed",
})

# 生产默认路径;测试可 monkeypatch 本变量把信号定向到自定义位置断言(既有用法)。
_LOG = Path(__file__).resolve().parents[4] / "runtime" / "logs" / "k_signals.jsonl"
_LOG_DEFAULT = _LOG


def _log_path() -> Path:
    """信号流水取径:_LOG 被测试显式改过=尊重之;否则经 runtime_path
    (pytest 隔离——引擎链路测试间接触发的 emit_signal 曾 +19 行/轮灌生产台账)。"""
    if _LOG is not _LOG_DEFAULT:
        return _LOG
    from main.common.runtime_paths import runtime_path
    return runtime_path("logs", "k_signals.jsonl")


def emit_signal(signal: str, subject: str, *, batch: str = "",
                source: str = "", **payload) -> None:
    """追加一条信号。signal 必须在闭集内(不在则记为 _unknown_signal 事件而非丢弃——
    宁可留下走样的痕迹供 debug,不静默吞)。subject=fact_key 或 autoid。"""
    try:
        rec = {
            "ts": round(time.time(), 3),
            "signal": signal if signal in SIGNALS else f"_unknown:{signal}",
            "subject": str(subject),
        }
        if batch:
            rec["batch"] = batch
        if source:
            rec["source"] = source
        if payload:
            # payload 按值截断,防单条信号膨胀(证据用 ref 不内联,与载荷通道纪律一致)
            rec["payload"] = {k: (v if not isinstance(v, str) else v[:400])
                              for k, v in payload.items()}
        _p = _log_path()
        _p.parent.mkdir(parents=True, exist_ok=True)
        with open(_p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 观测设施永不阻断主流程
        pass
