"""V8 事实台账:append-only 事实流 + 纯函数派生视图(THEORY §5.5 四公理的代码本体)。

四公理 → 代码契约:
- 语境锚:verdict 事实绑 (ctx, artifact, volume, bed, build)——旧卷面/旧卷组成的裁决
  不为新卷面背书(deliverable 三重匹配)。
- oracle 残差:fold 是**全函数**(任何事实序列都有定义的视图;未知 ev 跳过),
  reconcile 对 dom(V) 全射入账并给每条裁决显式结局(transition/confirm)——不存在第四种。
- 全射对账:reconcile 遍历"本轮裁决集",不按视图反查。
- 审计器权威:delivery-ctx 裁决 > subset-ctx 裁决(fold 内权威序,非写屏障;
  低权威照常入流,视图查询可见被遮盖关系)。

工程纪律(对抗审查):单写者(引擎进程)、原子追加、容损加载、幂等键去重(崩溃重放安全)、
未知事实类型前向兼容。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 语境常量:delivery=交付语境(整卷连跑,组成=当时交付集);subset=子集/单卷语境
CTX_DELIVERY = "delivery"
CTX_SUBSET = "subset"

# ── 事实 I/O(单写者;原子追加;容损加载) ─────────────────────────────────────


def append_facts(path: Path, facts: list[dict]) -> int:
    """追加事实(带幂等去重:与盘上已有幂等键重复的不再写)。返回实际写入条数。

    单写者契约:只有引擎进程调用本函数;fork 产物是文件,引擎收割后记账。
    崩溃安全:逐行 append+flush;重放时靠幂等键在这里与 fold 双重去重。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {idem_key(f) for f in load_facts(path)}
    written = 0
    with path.open("a", encoding="utf-8") as fh:
        for f in facts:
            k = idem_key(f)
            if k in existing:
                continue
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
            existing.add(k)
            written += 1
    return written


def load_facts(path: Path) -> list[dict]:
    """容损加载:坏行跳过并计数告警(被杀进程的半行不摧毁整账——意图索引拼接损坏教训)。"""
    if not path.is_file():
        return []
    out: list[dict] = []
    bad = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if isinstance(d, dict) and d.get("ev"):
                out.append(d)
            else:
                bad += 1
        except Exception:  # noqa: BLE001
            bad += 1
    if bad:
        logger.warning("事实流 %s 跳过损坏行 %d 条", path, bad)
    return dedup(out)


def idem_key(f: dict) -> tuple:
    """确定性幂等键——「append 后 checkpoint 前」崩溃重放不产生重复语义(INV-10)。

    键按事实类型取该类型的自然身份;未知类型退化为整体内容键(前向兼容:新类型
    不会因缺专属键而被错误去重/漏去重)。
    """
    ev, aid = str(f.get("ev")), str(f.get("aid", ""))
    if ev == "verdict":
        return (ev, aid, str(f.get("run_id")))
    if ev == "authored":
        return (ev, aid, int(f.get("round") or 0))
    if ev == "attribution":
        return (ev, aid, int(f.get("round") or 0))
    if ev == "decision":
        return (ev, aid, str(f.get("question_id") or f.get("question", ""))[:120])
    if ev in ("writeback", "rollback"):
        return (ev, aid, str(f.get("voucher_run") or f.get("of", "")), str(f.get("reason", "")))
    # 未知/其余类型:内容键(排序序列化)
    return (ev, aid, json.dumps(f, sort_keys=True, ensure_ascii=False))


def dedup(facts: list[dict]) -> list[dict]:
    """幂等键去重,先到者胜(append 序)。fold 一律吃去重后的流。"""
    seen: set = set()
    out: list[dict] = []
    for f in facts:
        k = idem_key(f)
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


# ── 派生谓词(纯函数;全函数——任何事实子序列都有定义结果) ────────────────────


def _facts_of(facts: list[dict], aid: str, ev: str | None = None) -> list[dict]:
    return [f for f in facts if str(f.get("aid")) == aid and (ev is None or f.get("ev") == ev)]


def latest_verdict(facts: list[dict], aid: str, ctx: str | None = None,
                   artifact: str | None = None) -> dict | None:
    """最新裁决(可按语境/卷面过滤)。事实流本身有序(append 序=时间序)。"""
    vs = [f for f in _facts_of(facts, aid, "verdict")
          if (ctx is None or f.get("ctx") == ctx)
          and (artifact is None or str(f.get("artifact")) == artifact)]
    return vs[-1] if vs else None


def deliverable(facts: list[dict], aid: str, current_artifact: str,
                current_volume: str) -> bool:
    """交付判据(公式15,INV-8):最新 delivery 裁决 pass ∧ 卷面指纹匹配 ∧ 卷组成匹配。

    旧卷面/旧组成的 delivery-pass 不为当前背书;subset-pass 永远不构成交付判据
    (权威序:它只令 case 进入待终验集合)。
    """
    v = latest_verdict(facts, aid, ctx=CTX_DELIVERY)
    return bool(v and v.get("result") == "pass"
                and str(v.get("artifact")) == current_artifact
                and str(v.get("volume")) == current_volume)


def subset_verified(facts: list[dict], aid: str, current_artifact: str) -> bool:
    """子集实证(进入终验集合的资格;不是交付判据)。"""
    v = latest_verdict(facts, aid, artifact=current_artifact)
    return bool(v and v.get("result") == "pass")


def frozen(facts: list[dict], aid: str, current_artifact: str | None = None) -> bool:
    """同签名连续两裁决 fail=同法已证伪(按 aid 派生,与路径/目录无关——#7 根治)。

    只看**同一卷面**的连续 fail(重编换卷面即解冻;override 声明经 authored 事实携带)。
    """
    vs = _facts_of(facts, aid, "verdict")
    if current_artifact is not None:
        vs = [v for v in vs if str(v.get("artifact")) == current_artifact]
    if len(vs) < 2:
        return False
    a, b = vs[-2], vs[-1]
    if a.get("result") != "fail" or b.get("result") != "fail":
        return False
    sa, sb = set(a.get("signatures") or []), set(b.get("signatures") or [])
    return bool(sa & sb)


def transient_recur(facts: list[dict], aid: str) -> bool:
    """上一归因判瞬态、其后又 fail=误归瞬态(护栏从 dead code 变派生谓词)。"""
    fs = _facts_of(facts, aid)
    last_transient_i = None
    for i, f in enumerate(fs):
        if f.get("ev") == "attribution" and f.get("layer") == "transient":
            last_transient_i = i
    if last_transient_i is None:
        return False
    return any(f.get("ev") == "verdict" and f.get("result") == "fail"
               for f in fs[last_transient_i + 1:])


def contradictions(facts: list[dict], aid: str) -> int:
    """矛盾计数(第三条 ask 边的输入):同一卷面上 pass@subset 之后出现 fail@delivery 的次数。

    卷面变更(重编)重置矛盾窗口——新卷面的矛盾从零计(旧矛盾史仍在流里可查)。
    """
    n = 0
    passed_subset_artifacts: set[str] = set()
    for f in _facts_of(facts, aid, "verdict"):
        art = str(f.get("artifact"))
        if f.get("ctx") == CTX_SUBSET and f.get("result") == "pass":
            passed_subset_artifacts.add(art)
        elif f.get("ctx") == CTX_DELIVERY and f.get("result") == "fail":
            if art in passed_subset_artifacts:
                n += 1
    return n


def rounds_used(facts: list[dict], aid: str) -> int:
    """重编轮次=authored 事实数(首败即升 max 的判据来源)。"""
    return len(_facts_of(facts, aid, "authored"))


# ── reconcile:全射对账(公式17;oracle 残差公理的执行体) ─────────────────────


def reconcile(facts: list[dict], verdicts: list[dict]) -> dict:
    """对本轮全部裁决(dom(V))做全射入账分类——每条裁决恰得一个显式结局。

    返回 {"append": [...要写入的裁决事实], "transition": [aid...视图被改变],
          "confirm": [aid...视图不变但显式核对一致], "duplicate": [aid...幂等重放]}。
    结局枚举即公理:不存在「无痕」分支;调用方必须先 append 再依 transition 派工。
    """
    out = {"append": [], "transition": [], "confirm": [], "duplicate": []}
    known = {idem_key(f) for f in facts}
    for v in verdicts:
        f = dict(v)
        f["ev"] = "verdict"
        if idem_key(f) in known:
            out["duplicate"].append(str(f.get("aid")))
            continue
        aid = str(f.get("aid"))
        prev = latest_verdict(facts, aid, ctx=str(f.get("ctx") or "") or None,
                              artifact=str(f.get("artifact")))
        same = bool(prev and prev.get("result") == f.get("result"))
        out["append"].append(f)
        (out["confirm"] if same else out["transition"]).append(aid)
        facts = facts + [f]   # 后续同批裁决基于已入账视图判定
        known.add(idem_key(f))
    return out
