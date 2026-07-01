"""compile_check_verifiability: 算法类用例「如写能否验证目标行为」的确定性证伪工具。

worker（compile-worker / ist-compile-draft）在为算法类 case 写断言**之前**先调它：把从脑图
expected 抽取的 {算法, 请求数, pool数, 权重, claim类型} 传进来，工具用数学模型（守恒 + 各行为
最小请求数）判可验 / 欠定。欠定 → 返回 NEEDS_USER_DECISION 标记，worker 据此**拒绝编断言、原样
上报 orchestrator**（orchestrator 汇总后 ask_user 改描述/改过程/改预期），而不是死抠形态乱写。

为什么是工具不是 run_python：worker 的 run_python 沙箱 cwd 锁在 knowledge/data、不能 import
main.*，跑不了 main.case_compiler.verifiability。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool


@tool(parse_docstring=True)
def compile_check_verifiability(autoid: str, algo: str, n_requests: int, n_pools: int,
                                claim_kind: str, weights_json: str = "",
                                existing_pools: int = -1) -> str:
    """判一个算法类 case「如写」能否验证它声称的行为（欠定就别编断言，上报 ask_user）。

    先从脑图该 case 的 expected 抽取行为类型 claim_kind 与数值参数，再调本工具。

    Args:
        autoid: 该 case 的 autoid（欠定时写进 NEEDS_USER_DECISION 标记）。
        algo: 算法名（小写，如 rr/wrr/grr/gwrr/ga）。
        n_requests: 该 claim 涉及的那组请求的**总次数**（如「客户端1发1次+客户端2发1次」验同一轮转=2）。
        n_pools: 当前关联的 pool 总数。
        claim_kind: 预期声称的行为类型，取值：absolute_position（第N次必中第N个pool，绝对位置）/
            rotation_order（依次轮转）/ new_member_last（新增pool最后才命中，有序轨迹）/
            new_member_participates（新增pool参与轮转/有命中，弱于最后命中）/
            weight_ratio（wrr按权重比例）/ distribution（一般命中分布）/
            relation_same（两次相同·会话保持）/ relation_diff（两次不同·切换）。
        weights_json: wrr 各 pool 权重的 JSON 数组（按关联顺序，如 "[3,2,1]"）；非 wrr 留空。
        existing_pools: new_member_last 用——新增前已有的 pool 数；缺省 -1 表示按 n_pools-1 推。

    Returns:
        verifiable → "VERIFIABLE: <说明>"（worker 继续选对断言形态落盘）；
        欠定 → "NEEDS_USER_DECISION autoid=… 原因 … 最小可验请求数 … 建议修法 …"
        （worker **不要**编断言，原样把这段返回给 orchestrator）。
    """
    try:
        from main.case_compiler.verifiability import check_verifiability, render_needs_user_decision
    except Exception as e:  # noqa: BLE001
        return f"error: 加载 verifiability 失败: {e}"

    weights = None
    if weights_json and weights_json.strip():
        try:
            parsed = json.loads(weights_json)
            if isinstance(parsed, list) and all(isinstance(x, int) for x in parsed):
                weights = parsed
            else:
                return f"error: weights_json 必须是整数 JSON 数组（如 [3,2,1]），实际 {weights_json!r}"
        except Exception as e:  # noqa: BLE001
            return f"error: weights_json 解析失败: {e}"

    verdict = check_verifiability(
        algo, n_requests, n_pools,
        weights=weights, claim_kind=claim_kind,
        existing_pools=(None if existing_pools is None or existing_pools < 0 else existing_pools),
    )
    if verdict.verifiable:
        note = ("；" + "；".join(verdict.notes)) if verdict.notes else ""
        return f"VERIFIABLE: {verdict.reason}{note}"
    return render_needs_user_decision(autoid, verdict)
