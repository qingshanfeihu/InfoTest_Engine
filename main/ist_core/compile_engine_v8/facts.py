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
    if ev == "escalated":
        # M-05:同因重复升级若无 run_id,内容键把第二次吞掉 → attempts 轴永=1、
        # deesc_auto_resolution「完整轨迹」不成立。有 run_id 按次区分;旧账无则退内容键。
        rid = str(f.get("run_id") or "")
        if rid:
            return (ev, aid, rid)
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


# de-escalate 恢复通道(2026-07-20 B-1)。三子类由**产生点所在的失败阶段**固化进
# escalated 事实的 subclass 字段——不按 reason 散文串判(措辞一改静默误路由;且与
# 「有无 xlsx」跨轮打架:round1 产卷+round2 fork 空转的案 xlsx 在、真因却是 author
# 段空转,该走重编)。存量事实无该字段时按 reason 前缀兜底一次。
ESC_NO_OUTPUT = "no_output"                  # author 段:fork 无产出(墙钟/空转)→ 重编
ESC_NOT_EXECUTED = "not_executed"            # run 段:有卷但连续未跑成 → 换床复跑
ESC_NO_LEDGER_CHANNEL = "no_ledger_channel"  # 欠定无落账通道 → 缺陷候选/改描述重编

_ESC_LEGACY_PREFIX = (
    ("no output from fork", ESC_NO_OUTPUT),
    ("case did not execute for", ESC_NOT_EXECUTED),
    ("worker declared underdetermined", ESC_NO_LEDGER_CHANNEL),
)


def _fact_subclass(f: dict) -> str:
    """单条 escalated 事实的子类(结构化字段优先,reason 前缀兜底)——escalated_subclass
    与 escalation_attempts 共用的单事实判据,避免两处各写一份兜底逻辑漂移。"""
    sub = str(f.get("subclass") or "").strip()
    if sub:
        return sub
    reason = str(f.get("reason") or "")
    for prefix, kind in _ESC_LEGACY_PREFIX:
        if prefix in reason:
            return kind
    return ""


def escalated_subclass(facts: list[dict], aid: str) -> str:
    """该案**最后一条** escalated 事实的子类;非 escalated 或无从判 → ""。

    读结构化字段;存量事实(本次改动前落的)无该字段,按 reason 前缀兜底——兜底是
    对历史数据的一次性让步,新事实一律带字段(守门测试 8 锁:reason 被改写不影响分治)。
    """
    esc = _facts_of(facts, aid, "escalated")
    return _fact_subclass(esc[-1]) if esc else ""


def de_escalated_after_last_escalation(facts: list[dict], aid: str) -> dict | None:
    """最后一次 escalated **之后**的 de_escalated 事实(无则 None)。

    位置敏感:de_escalate 后新一轮再次 escalated,新事实在后 → 本函数返回 None、
    案重新是 escalated(守门测试 10:解除不复燃,恢复不是永久豁免)。
    """
    mine = [f for f in facts if str(f.get("aid")) == aid]
    last_esc = max((i for i, f in enumerate(mine) if f.get("ev") == "escalated"),
                   default=-1)
    if last_esc < 0:
        return None
    for f in mine[last_esc + 1:]:
        if f.get("ev") == "de_escalated":
            return f
    return None


def recovery_attempts(facts: list[dict], aid: str) -> int:
    """恢复重派次数=de_escalated 事实数(用户已批准过几次恢复,报告侧上下文用)。"""
    return len(_facts_of(facts, aid, "de_escalated"))


# attempts 轴(Theory+Py-Eng round-cap 修法,2026-07-21):`rounds_used` 数**成功产出**的
# authored,no_output/no_ledger_channel 两子类的定义就是"从未产出 authored"——用
# rounds_used 做封顶判据,封顶对这两类永久失效(nodes.py:657 battle-scar 实证:批3 668
# 族 7 圈空烧 fork,auth=0 verd=0)。escalated 事实反而是这两子类**唯一必然产生**的
# 记账点,天然承载"该案被送进 author/live 但没能正常收尾的次数"——不数 authored 是否
# 产出,只数升级本身,故按此定义 attempts 轴,不改 rounds_used(它仍是另外 4 处消费点
# 的权威定义)。
DEESC_ROUND_CAP = 2   # 第 N 次同子类升级触发封顶(gate 测试#4 字面:"第二次…封顶")


def escalation_attempts(facts: list[dict], aid: str, subclass: str) -> int:
    """该案在**这一子类**上的升级次数(attempts 轴)。按子类分开计数——不同子类
    的恢复路/封顶语义不同(no_ledger_channel 走"先试后判"而非本计数轴,见
    deesc_auto_resolution),混着数会让一个子类的挣扎污染另一个子类的封顶判断。"""
    return sum(1 for f in _facts_of(facts, aid, "escalated")
              if _fact_subclass(f) == subclass)


def deesc_auto_resolution(facts: list[dict], aid: str, new_escalated: dict) -> list[dict]:
    """升级事实即将写入前的自动裁决(先试后判/round-cap 的机械触发,不停下来问人)。

    调用方(author/reconcile)在追加一条新 escalated 事实前先过一次本函数:命中则本函数
    返回要**额外一并追加**的 facts(de_escalated 释放信号 + attribution 终判),调用方把
    这些跟在 escalated 事实后面一起写入——案子仍会留下"又升级了一次"的完整轨迹,只是
    紧接着被引擎自己解除+终判,不会再进 ask 边问第三次。未命中返回 []:原样留给
    deesc_recovery_waiting/ask_contradiction 走正常问询。

    两条独立规则(THEORY §0 A6 三分,leader 收回"no_ledger_channel 统一转缺陷候选"的
    初裁后落地):
    - no_output / not_executed:**第二次同子类升级**即封顶(不问,直接缺陷候选)——
      这两类每次尝试都要烧一次完整 fork/上机轮次且失败了不产出任何新证据,继续问
      只会引出"答重编→仍无产出→再问→再重编"的问-编循环(§2.1)。
    - no_ledger_channel:**同 claim 再次出现**才落"工程故障呈报"(A6 臂,不是缺陷候选)
      ——用一次重编赌"worker 只是忘调 verifiability 工具"(因①,可自愈);若原样复现
      同一条 claim,说明是"这类欠定确实没有落账通道"(因②,引擎缺口),坐实。claim
      文本用 escalated.reason 精确比对(worker 原文含在其中)——不做模糊匹配:漏判
      只是多烧一轮再问,误判会把真缺陷候选错记成工程故障,后者代价更高。
    """
    sub = _fact_subclass(new_escalated)
    if sub in (ESC_NO_OUTPUT, ESC_NOT_EXECUTED):
        prior = escalation_attempts(facts, aid, sub)
        if prior + 1 >= DEESC_ROUND_CAP:
            _n = prior + 1
            return [
                {"ev": "de_escalated", "aid": aid,
                 "note": f"auto: round-cap reached ({_n}x {sub})"},
                # M-05:round=99 归因必带 run_id——否则幂等键退化 (attribution,aid,99),
                # 同案第二次自动封顶/用户终局裁决被静默吞。
                {"ev": "attribution", "aid": aid, "round": 99, "layer": "engine",
                 "run_id": f"auto_cap:{aid}:{sub}:{_n}",
                 "disposition": "defect_candidate",
                 "fix_direction": (f"escalation round-cap reached ({_n}x {sub}) — "
                                   "engine exhausted its recovery attempts for this case "
                                   "without producing new evidence"),
                 "evidence": f"engine_auto_cap:{sub}"},
            ]
        return []
    if sub == ESC_NO_LEDGER_CHANNEL:
        prior_esc = [f for f in _facts_of(facts, aid, "escalated")
                    if _fact_subclass(f) == sub]
        if prior_esc and str(prior_esc[-1].get("reason") or "") == str(
                new_escalated.get("reason") or ""):
            return [
                {"ev": "de_escalated", "aid": aid,
                 "note": "auto: same underdetermined claim recurred after a recovery attempt"},
                {"ev": "attribution", "aid": aid, "round": 99, "layer": "engine",
                 "run_id": f"auto_eng:{aid}:{len(prior_esc) + 1}",
                 "disposition": "engineering_fault",
                 "fix_direction": ("no landing channel for this claim kind — the same claim "
                                   "recurred verbatim after one recovery attempt; this is an "
                                   "engine gap (no needs_decision.json ledger path for this "
                                   "claim kind), not a product defect"),
                 "evidence": f"engine_auto: {str(new_escalated.get('reason') or '')[:300]}"},
            ]
        return []
    return []


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
