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
    import os as _os
    with path.open("a", encoding="utf-8") as fh:
        for f in facts:
            f = {**f, "_pid": _os.getpid()}   # 写入者审计(僵尸跨写取证用;不参与幂等键)
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
        # 按 run_id 键控(验收实证:同轮二次归因曾被 (aid,round) 键静默去重);
        # 无 run_id 的旧形态退回轮键
        rid = str(f.get("run_id") or "")
        return (ev, aid, rid) if rid else (ev, aid, int(f.get("round") or 0))
    if ev == "decision":
        return (ev, aid, str(f.get("question_id") or f.get("question", ""))[:120])
    if ev in ("writeback", "rollback"):
        return (ev, aid, str(f.get("voucher_run") or f.get("of", "")), str(f.get("reason", "")))
    # 未知/其余类型:内容键(排序序列化;剔除 _ 前缀审计字段——_pid 随进程变,
    # 入键会破坏跨进程续跑的重放幂等)
    core = {k: v for k, v in f.items() if not str(k).startswith("_")}
    return (ev, aid, json.dumps(core, sort_keys=True, ensure_ascii=False))


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


def _norm_sigs(xs) -> set[str]:
    """存量签名归一化(A1 迁移条款消费点):新旧格式签名做交集前两侧共同过
    normalize_fail_signature——旧格式真 Fail 项带 `` in: <file>`` 尾,与新解析纯
    pattern 逐字比较交集恒空 → 冻结/跨床反驳在跨界轮静默失效。惰性 import
    (facts 是引擎纯层,不常驻依赖工具层);取不到时恒等回退(同格式内零影响)。"""
    try:
        from main.ist_core.tools.device.batch_tools import normalize_fail_signature as _n
    except Exception:  # noqa: BLE001
        def _n(s):
            return s
    return {_n(str(x)) for x in (xs or [])}


def frozen(facts: list[dict], aid: str, current_artifact: str | None = None) -> bool:
    """同签名连续两裁决 fail=同法已证伪(按 aid 派生,与路径/目录无关——#7 根治)。

    只看**同一卷面**的连续 fail(重编换卷面即解冻;override 声明经 authored 事实携带)。
    """
    vs = _facts_of(facts, aid, "verdict")
    if current_artifact is not None:
        vs = [v for v in vs if str(v.get("artifact")) == current_artifact]
    # (44) broken/not_run 不构成证据:案没跑成的轮次既不延续也不打断同法证伪序列
    vs = [v for v in vs if v.get("result") in ("pass", "fail")]
    if len(vs) < 2:
        return False
    a, b = vs[-2], vs[-1]
    if a.get("result") != "fail" or b.get("result") != "fail":
        return False
    sa, sb = _norm_sigs(a.get("signatures")), _norm_sigs(b.get("signatures"))
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
    """矛盾计数(第三条 ask 边的输入):同一卷面上「先 pass 后 fail@delivery」的次数。

    两种翻转形态都计(V8 验收实证):①pass@subset → fail@delivery(单跑过/整卷挂,互扰);
    ②pass@delivery → fail@delivery(已交付态被后续终验反证——668015 形态,非确定互扰)。
    卷面变更(重编)重置窗口——新卷面从零计(旧矛盾史仍在流里可查)。
    """
    n = 0
    passed_artifacts: set[str] = set()
    for f in _facts_of(facts, aid, "verdict"):
        art = str(f.get("artifact"))
        if f.get("result") == "pass":
            passed_artifacts.add(art)
        elif f.get("ctx") == CTX_DELIVERY and f.get("result") == "fail":
            if art in passed_artifacts:
                n += 1
    return n


def rounds_used(facts: list[dict], aid: str) -> int:
    """重编轮次=authored 事实数(首败即升 max 的判据来源)。"""
    return len(_facts_of(facts, aid, "authored"))


# 强处置(N1b claim 级证据粘性的作用域):这两类结论携带「设备行为≠预期」的证据主张,
# 后轮归因不得让它静默消失——弱处置(reflow/rerun_isolated/transient/env_blocked/frozen)
# 是过程动作,不承载跨轮主张
STRONG_DISPOSITIONS = ("defect_candidate", "expectation_suspect")


def strong_claims(facts: list[dict], aid: str) -> list[dict]:
    """强处置 claim 历史([主张, 证据] 对,append 序)——N1b claim 级证据粘性。

    粒度在 **claim 级不在处置标签级**(517027 一手复核:r1 dc「不返回 AAAA」是误判、
    r2 dc「Timeout=0」是真缺陷主张——同一标签下两条独立 claim,标签级单调律两头都错);
    事实流 append-only 本就保留历史,本函数是消费端读法:brief/题面/缺陷单由此取全史,
    r3 的改判不再让 r2 的 claim 从消费面消失。
    用户来源(evidence=="user")的行是裁决记账不是设备证据主张,不算 claim(N1a 本体分离);
    同 (disposition, claim) 跨轮重复只记首轮(幂等,防 churn 刷屏)。
    """
    out: list[dict] = []
    seen: set[tuple] = set()
    for f in _facts_of(facts, aid, "attribution"):
        if str(f.get("disposition")) not in STRONG_DISPOSITIONS:
            continue
        ev = str(f.get("evidence") or "")
        if not ev or ev == "user":
            continue
        claim = str(f.get("fix_direction") or "")[:300]
        k = (str(f.get("disposition")), claim)
        if k in seen:
            continue
        seen.add(k)
        # 键形态与题面 claim_history 契约同构([{round,layer,disposition,claim,evidence}],
        # 乙队 questions 消费冻结)——本函数是其强处置子集(brief 注入面)
        out.append({"round": int(f.get("round") or 0),
                    "layer": str(f.get("layer") or ""),
                    "disposition": str(f.get("disposition")),
                    "claim": claim, "evidence": ev[:300]})
    return out


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
