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
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


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
    # 欠定台账落盘(结构化,机读):工具内部本就是结构化 Verdict,压平成文本后经
    # worker→main→ask_user 两道散文接力会磨掉关键锚点(实证 593516 的有序语义
    # new_member_last 在 main 并组三题时蒸发,用户从未批准的降级出厂)。台账留一份
    # 机读原件,ask_user 组织与 user_decision 落地都以它为锚;同 case 多 claim 按
    # claim_kind 合并。ordering_sensitive 标记有序轨迹类 claim——它们的改法必须
    # 显式处理顺序语义的去留。
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parents[4]
        outd = root / "workspace" / "outputs" / (autoid or "").strip()
        outd.mkdir(parents=True, exist_ok=True)
        nd_path = outd / "needs_decision.json"
        data: dict = {"autoid": (autoid or "").strip(), "claims": []}
        if nd_path.is_file():
            try:
                loaded = json.loads(nd_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("claims"), list):
                    data = loaded
            except Exception:  # noqa: BLE001
                pass
        entry = verdict.to_dict() if hasattr(verdict, "to_dict") else {
            "claim_kind": claim_kind, "reason": verdict.reason,
            "min_requests": verdict.min_requests, "suggested_fix": verdict.suggested_fix}
        entry["ordering_sensitive"] = claim_kind in ("new_member_last", "absolute_position")
        data["claims"] = [c for c in data["claims"] if c.get("claim_kind") != claim_kind]
        data["claims"].append(entry)
        nd_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("needs_decision.json 落盘失败", exc_info=True)
    return render_needs_user_decision(autoid, verdict)
