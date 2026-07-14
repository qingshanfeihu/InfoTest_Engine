"""批视图:事实流 → 逐案派生状态(路由唯一依据;INV-7 账实分离的"实"侧)。

状态是**标签不是存储**——每次路由现算(26 案×百级事实,纯函数,微秒级)。
checkpoint 里的计数只是缓存,恢复时以本视图为准。
"""

from __future__ import annotations

from collections import Counter

from main.ist_core.compile_engine_v8 import facts as F

# 派生状态标签(路由词汇;与 V6 状态枚举的区别:这些由事实现算,不可写)
S_PENDING = "pending"                 # 无 authored 事实
S_AWAITING_USER = "awaiting_user"     # 有未答的 needs_decision
S_AUTHORED = "authored"               # 有当前轮卷面,未上机
S_FAILED = "failed"                   # 最新裁决 fail(同卷面),未终态
S_BROKEN = "broken"                   # 最新裁决 broken/not_run:案没跑成(级联崩溃/
                                      # stale/超时/执行相位失败),结论无效≠断言红
                                      # ——(44) 断言有效性/xUnit ERROR;处置=复跑
S_SUBSET_VERIFIED = "subset_verified" # 子集 pass,待终验
S_DELIVERABLE = "deliverable"         # delivery-ctx pass 且三重匹配
S_CONTRADICTED = "contradicted"       # 矛盾计数>0 且当前不可交付
S_ESCALATED = "escalated"             # 升级事实在案(fork 无产出等基础设施失败)
S_TERMINAL = "failed_terminal"        # 终态标注(仅用户来源的止损裁决,§11.7 三权分立)
S_SUSPENDED = "suspended"             # 用户裁决挂起(非终态:下批同参续跑)


def _user_sourced(att: dict) -> bool:
    """止损归用户(§11.7):env_blocked/defect_candidate 只有携用户来源标记才构成终态;
    归因器自判的是待确认判断(进 ask 边),不是引擎单方终结权。
    判 round==99 单一信号:该值只能由 ask_contradiction 节点写——fork 经
    submit_attribution 落账时 round 由工具内部取自台账 _round,入参伪造不了;
    而 evidence 字符串可被设备回显里的常见词(如 "user")撞上,不作来源信号。"""
    return int(att.get("round") or 0) == 99


def _is_suspended(mine: list[dict]) -> bool:
    """挂起非终态(§11.11):最后一个 suspended 之后出现 resumed 即解除(跨批恢复通道)。"""
    last_susp = -1
    last_resume = -1
    for i, f in enumerate(mine):
        if f.get("ev") == "suspended":
            last_susp = i
        elif f.get("ev") == "resumed":
            last_resume = i
    return last_susp >= 0 and last_resume < last_susp


def _is_escalated(mine: list[dict]) -> bool:
    """升级非绝对终态(run18 实弹修,与 suspended/resumed 同型):最后一个 escalated
    之后出现 authored 即解除。

    escalated 的成因是「本轮无产出」(fork 墙钟超时/空转)或「连续未跑成」——两者
    都是关于**当时**的判断。fork 超时后 worker 线程未死、迟到落盘合格卷(run18:
    655233 在 935s 时 emit 成功,凭证有效),或重编产出新卷,都使该判断的前提不再
    成立;新 authored 事实即解除信号。真·无产出的案不会有 authored,原样升级人工。"""
    last_esc = -1
    last_auth = -1
    for i, f in enumerate(mine):
        if f.get("ev") == "escalated":
            last_esc = i
        elif f.get("ev") == "authored":
            last_auth = i
    return last_esc >= 0 and last_auth < last_esc


def case_status(fs: list[dict], aid: str, current_artifact: str,
                current_volume: str) -> str:
    """单案派生状态(全函数:任何事实组合都落入且仅落入一个标签)。优先级从终到始。"""
    mine = [f for f in fs if str(f.get("aid")) == aid]
    if _is_escalated(mine):
        return S_ESCALATED
    if _is_suspended(mine):
        return S_SUSPENDED
    # 用户来源终态两种:止损(env_blocked)与确认产品缺陷(defect_candidate 走候选单)
    if any(f.get("ev") == "attribution" and _user_sourced(f)
           and f.get("disposition") in ("env_blocked", "defect_candidate")
           for f in mine):
        return S_TERMINAL
    # H2(§18.11 横切,2026-07-14):按 question_id 配对——旧谓词「有任意 decision 即
    # 非等待」与 ask_decision 的按题配对二义,同案第二次欠定(F6 新增来源)会被
    # author 重派或漏停车
    _answered_q = {f.get("question_id") for f in mine if f.get("ev") == "decision"}
    if any(f.get("ev") == "needs_decision"
           and f.get("question_id") not in _answered_q for f in mine):
        return S_AWAITING_USER
    # emit_invalid 打回(#74-②):最新 authored 之后被合并预检拒(凭证过期/lint 违例,
    # 常见成因=emit 后绕门直改卷面)→ 当前卷面不可信,回待编写(author 重派,
    # rounds_used 不变、重编 round+1 自然升思考深度)
    last_auth_i = max((i for i, f in enumerate(mine) if f.get("ev") == "authored"),
                      default=-1)
    if last_auth_i >= 0 and any(f.get("ev") == "emit_invalid"
                                for f in mine[last_auth_i + 1:]):
        return S_PENDING
    if F.deliverable(mine, aid, current_artifact, current_volume):
        return S_DELIVERABLE
    # 标签跟**当前卷面**走(重编即重置标签;矛盾计数保全史供 ask 策略)
    last = F.latest_verdict(mine, aid, artifact=current_artifact) if current_artifact else None
    if last:
        if last.get("result") == "pass":
            return S_SUBSET_VERIFIED
        if last.get("result") in ("broken", "not_run"):
            # (44) 断言有效性:案没跑成,结论无效——非 fail(不计签名/不深归因),
            # 处置=复跑;连续未跑成的护栏在 reconcile(streak≥2 落 escalated)
            return S_BROKEN
        if last.get("ctx") == F.CTX_DELIVERY and F.contradictions(mine, aid) > 0:
            return S_CONTRADICTED
        return S_FAILED
    if F.rounds_used(mine, aid) > 0:
        return S_AUTHORED
    return S_PENDING


def batch_view(fs: list[dict], manifest: dict) -> dict:
    """全批视图:{aid: {status, rounds, contradictions, frozen}} + 计数汇总。

    manifest 提供 aid 全集与各案当前卷面指纹(authored 事实回填);
    volume 指纹取自最近 merge 事实(无则空——尚未合并)。
    """
    aids = [str(c.get("autoid")) for c in (manifest.get("cases") or [])]
    merges = [f for f in fs if f.get("ev") == "merged"]
    current_volume = str(merges[-1].get("volume")) if merges else ""
    out: dict = {"cases": {}, "volume": current_volume}
    for aid in aids:
        mine = [f for f in fs if str(f.get("aid")) == aid]
        authored = [f for f in mine if f.get("ev") == "authored"]
        artifact = str(authored[-1].get("artifact")) if authored else ""
        st = case_status(fs, aid, artifact, current_volume)
        out["cases"][aid] = {
            "status": st, "artifact": artifact,
            "rounds": F.rounds_used(mine, aid),
            "contradictions": F.contradictions(mine, aid),
            "frozen": F.frozen(mine, aid, artifact or None),
            "transient_recur": F.transient_recur(mine, aid),
        }
    out["counts"] = dict(Counter(v["status"] for v in out["cases"].values()))
    return out


def all_settled(view: dict) -> bool:
    """不动点判据:每案都在 {deliverable, escalated, failed_terminal, suspended}。"""
    return all(v["status"] in (S_DELIVERABLE, S_ESCALATED, S_TERMINAL, S_SUSPENDED)
               for v in view["cases"].values()) and bool(view["cases"])
