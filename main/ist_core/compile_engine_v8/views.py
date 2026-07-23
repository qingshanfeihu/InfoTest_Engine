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
# pyATS 七码子分类(§18.1/DESIGN_dongkl_finalization §④;仅按协议级硬事实细分,
# 守 (44) 不语义猜测——细分基于物理码非 LLM 判断):
S_BROKEN_ERRORED = "broken_errored"   # Errored:命令畸形/执行错/断言被对齐证据机械反证
                                      # (window-audit false_fail/false_pass、exec-failure
                                      # marker)——原样复跑必再错,处置=reflow 重写(不空跑)
S_BROKEN_BLOCKED = "broken_blocked"   # Blocked:设备 ping 不通(承载链第零层)——处置=env
                                      # 呈报(复跑救不了死设备,别烧设备轮)
S_SUBSET_VERIFIED = "subset_verified" # 子集 pass,待终验
S_DELIVERABLE = "deliverable"         # delivery-ctx pass 且三重匹配
S_CONTRADICTED = "contradicted"       # 矛盾计数>0 且当前不可交付
S_ESCALATED = "escalated"             # 升级事实在案(fork 无产出等基础设施失败)
S_TERMINAL = "failed_terminal"        # 终态标注(仅用户来源的止损裁决,§11.7 三权分立)
S_SUSPENDED = "suspended"             # 用户裁决挂起(非终态:下批同参续跑)


def _user_sourced(att: dict) -> bool:
    """止损归用户(§11.7):env_blocked/defect_candidate 只有携用户来源标记才构成终态;
    归因器自判的是待确认判断(进 ask 边),不是引擎单方终结权。
    判 round==99 单一信号:该值由 ask_contradiction 用户裁决臂**或**
    deesc_auto_resolution 引擎自动封顶/工程故障臂写入(B-1;views 终态表已并列
    engineering_fault)。fork 经 submit_attribution 落账时 round 由工具取自台账
    _round,入参伪造不了;evidence 字符串可被设备回显常见词撞上,不作来源信号。"""
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
    成立;新 authored 事实即解除信号。真·无产出的案不会有 authored,原样升级人工。

    **解除信号集 = {authored, de_escalated}**(2026-07-20 B-1):原来只认 authored,
    于是 no_output 子类(定义即「从未产出 authored」)永远等不到解除——信号有、驱动无,
    案卡死在准终态。用户答「恢复」落的 de_escalated 事实是第二个解除信号,案随即
    自然回落 S_PENDING(无 authored)重进 author,零硬设状态、零新标签。"""
    last_esc = -1
    last_release = -1
    for i, f in enumerate(mine):
        if f.get("ev") == "escalated":
            last_esc = i
        elif f.get("ev") in ("authored", "de_escalated"):
            last_release = i
    return last_esc >= 0 and last_release < last_esc


def case_status(fs: list[dict], aid: str, current_artifact: str,
                current_volume: str) -> str:
    """单案派生状态(全函数:任何事实组合都落入且仅落入一个标签)。优先级从终到始。"""
    mine = [f for f in fs if str(f.get("aid")) == aid]
    if _is_escalated(mine):
        # 恢复问询待答 → awaiting:与 suspended/cap/env/bed 同型,这些"待答呈报"类
        # kind 都不走 needs_decision(那条通道专属 ask_decision/欠定问询),而是各自
        # 一个 `_waiting()` 判据(deesc_recovery_waiting,状态依赖 state 里的床/版本
        # 族才能算判例键收敛,views.py 是纯函数不接 state)——本函数不重算它,只留
        # S_ESCALATED;_shared.view() 在算完本视图后按 deesc_recovery_waiting 的结果
        # 把其中的 aid 现改成 S_AWAITING_USER(判据单源仍在 deesc_recovery_waiting,
        # 这里只是它落不进纯函数签名的必要让步)。all_settled 因此零改动:
        # S_AWAITING_USER 本就不在其稳态集内。
        return S_ESCALATED
    if _is_suspended(mine):
        return S_SUSPENDED
    # 用户来源终态四种:止损记账(user_stop,2026-07-16 N1a 本体分离)/确认环境
    # (env_blocked,env 题面停止的如实语义)/确认产品缺陷(defect_candidate 走候选单)/
    # 工程故障呈报(engineering_fault,B-1 A6 臂——round=99 的哨兵不是"用户真打字"专属,
    # 而是"终局判定,不再重试"的通用记账信号,de-escalate 自动裁决[deesc_auto_resolution]
    # 与人工选"工程故障呈报"都落它;disposition 值本身已把两者与产品缺陷分开,不会被
    # _collect_defect_candidates 的 =="defect_candidate" 精确过滤误收,gate 测试13)
    if any(f.get("ev") == "attribution" and _user_sourced(f)
           and f.get("disposition") in ("env_blocked", "defect_candidate", "user_stop",
                                        "engineering_fault")
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
    # delivery_blocked 打回(H-16,与 emit_invalid 同层):最后 delivery pass 之后被 G3
    # 封堵(卷面缺案尾自清)→ 该 pass 不为交付背书,案回待编写重编补 τ,兑现 emit
    # 「重编补自清后可交付」(此前 closing 手改 vw 写 "delivery_blocked"——fold 外的
    # 第 13 状态,下批派生回 S_DELIVERABLE 造成封堵→复活→再封堵 limbo 循环)。
    # 收敛:重编仍受 rounds_used+granted 封顶;其后有新 delivery pass(重编复验通过)
    # 或已重编(新 authored,封堵已消费)则本支不再命中,自然回到正常生命周期。
    last_db_i = max((i for i, f in enumerate(mine)
                     if f.get("ev") == "delivery_blocked"), default=-1)
    if last_db_i >= 0:
        last_dpass_i = max((i for i, f in enumerate(mine)
                            if f.get("ev") == "verdict"
                            and f.get("ctx") == F.CTX_DELIVERY
                            and f.get("result") == "pass"), default=-1)
        if last_db_i > last_dpass_i and last_db_i > last_auth_i:
            return S_PENDING
    if F.deliverable(mine, aid, current_artifact, current_volume):
        return S_DELIVERABLE
    # 标签跟**当前卷面**走(重编即重置标签;矛盾计数按当前 artifact 窗口——M-19)
    last = F.latest_verdict(mine, aid, artifact=current_artifact) if current_artifact else None
    if last:
        if last.get("result") == "pass":
            return S_SUBSET_VERIFIED
        if last.get("result") in ("broken", "not_run"):
            # (44) 断言有效性:案没跑成,结论无效——非 fail(不计签名/不深归因)。
            # pyATS 七码子分类(§④):按裁决携带的协议级硬码 broken_subtype 定处置——
            # errored→reflow(重写)、blocked→env(呈报)、其余(not_run/stale/协议级分不清)
            # →复跑(streak≥2 落 escalated,护栏在 reconcile)。子分类只读硬事实,不猜。
            sub = str(last.get("broken_subtype") or "")
            if sub == "errored":
                return S_BROKEN_ERRORED
            if sub == "blocked":
                return S_BROKEN_BLOCKED
            return S_BROKEN
        if (last.get("ctx") == F.CTX_DELIVERY
                and F.contradictions(mine, aid, artifact=current_artifact) > 0):
            return S_CONTRADICTED
        return S_FAILED
    if F.rounds_used(mine, aid) > 0:
        return S_AUTHORED
    return S_PENDING


def batch_view(fs: list[dict], manifest: dict) -> dict:
    """全批视图:{aid: {status, rounds, contradictions, frozen}} + 计数汇总。

    manifest 提供 aid 全集与各案当前卷面指纹(authored 事实回填);volume 指纹取自
    最近 **delivery** merge 事实(无则空)。**卷指纹隔离**:deliverable 绑「最近
    delivery 卷」而非「最近任意 merge 卷」——否则别案的子集复跑会 churn
    current_volume,把已 pass@delivery 案降级回 subset_verified 恒占 live 饿死
    gather;真交付组成变化才让旧交付案重新终验(INV-8 组成锚不破)。机理全文:
    DESIGN_dongkl_finalization §⑥ 回归#2 修 C(主文档回指 DESIGN_v8 §16.5b)。
    """
    aids = [str(c.get("autoid")) for c in (manifest.get("cases") or [])]
    # 只**排除** subset 复跑卷(ctx=="subset");delivery 卷与无 ctx 的旧/最小事实照旧
    # 当交付卷(向后兼容,真实 subset merge 必带 ctx="subset",见 nodes.merge)
    d_merges = [f for f in fs if f.get("ev") == "merged"
                and f.get("ctx") != F.CTX_SUBSET]
    current_volume = str(d_merges[-1].get("volume")) if d_merges else ""
    out: dict = {"cases": {}, "volume": current_volume}
    for aid in aids:
        mine = [f for f in fs if str(f.get("aid")) == aid]
        authored = [f for f in mine if f.get("ev") == "authored"]
        artifact = str(authored[-1].get("artifact")) if authored else ""
        st = case_status(fs, aid, artifact, current_volume)
        out["cases"][aid] = {
            "status": st, "artifact": artifact,
            "rounds": F.rounds_used(mine, aid),
            "contradictions": F.contradictions(mine, aid, artifact=artifact or None),
            "frozen": F.frozen(mine, aid, artifact or None),
            "transient_recur": F.transient_recur(mine, aid),
        }
    out["counts"] = dict(Counter(v["status"] for v in out["cases"].values()))
    return out


def all_settled(view: dict) -> bool:
    """不动点判据:每案都在 {deliverable, escalated, failed_terminal, suspended}。"""
    return all(v["status"] in (S_DELIVERABLE, S_ESCALATED, S_TERMINAL, S_SUSPENDED)
               for v in view["cases"].values()) and bool(view["cases"])
