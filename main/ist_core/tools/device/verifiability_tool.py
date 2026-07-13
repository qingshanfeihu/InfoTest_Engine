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


def _land_needs_decision(autoid: str, claim_kind: str, entry: dict) -> bool:
    """欠定台账落盘(结构化,机读):同 case 多 claim 按 claim_kind 合并。verifiability
    与通用欠定上报共用——A 层「先问后落」要求台账是结构化文件(散文接力会磨掉锚点,
    593516 有序语义在 main 并组三题时蒸发的实证)。返回落盘是否成功。"""
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
        data["claims"] = [c for c in data["claims"] if c.get("claim_kind") != claim_kind]
        data["claims"].append({**entry, "claim_kind": claim_kind})
        nd_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        logger.debug("needs_decision.json 落盘失败", exc_info=True)
        return False


@tool(parse_docstring=True)
def compile_check_verifiability(autoid: str, algo: str, n_requests: int, n_pools: int,
                                claim_kind: str, weights_json: str = "",
                                existing_pools: int = -1) -> str:
    """判一个算法类 case「如写」能否验证它声称的行为（数学欠定就别编断言，上报用户决策）。

    **何时用**：case 的预期落在运行时不确定区（"某一次请求命中第几个 pool"这类由算法
    随机性/计数器状态决定的 claim）——先从脑图 expected 抽取 claim_kind 与数值参数
    （算法、该 claim 涉及的请求数、候选池数、权重），再调本工具判可验性。
    **何时不用**：预期已被配置/协议/设备规则**唯一确定**（静态层：配了就在、删了就不在、
    固定响应格式）——不欠定，直接按静态层写断言，不进证伪。

    返回两种判定，处置完全不同：
    - ``VERIFIABLE``：可验，按算法类型选断言形态；**notes 带落地约束**（如顺序类 claim
      "统计有命中≠最后才命中"），按 notes 落地、别自行降级成更弱的 claim。
    - ``NEEDS_USER_DECISION``：欠定（按脑图的过程验不出声称的效果），**停手别编断言**，
      把整段原样带回给 orchestrator 汇总问用户（改描述/改过程/改预期）。判定同时落台账
      needs_decision.json——上报有锚，这个词只在本工具判定时使用。

    Args:
        autoid: 该 case 的 autoid（欠定时写进 NEEDS_USER_DECISION 标记）。
        algo: 算法名（小写，如 rr/wrr/grr/gwrr/ga）。
        n_requests: 该 claim 涉及的那组请求的**总次数**——同一组=在同一个候选池集合里
            轮转的请求;候选集合不同的请求分组分别证伪,别并成一组。
        n_pools: 该 claim 的**候选池数**(这组请求实际参与选择的池数),不是绑定池总数——
            被配置或协议规则排除出候选的池不算。候选只剩 1 个时命中是确定的(静态层
            直接断言,不用调本工具);传绑定池总数会把可验的判成欠定。
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
    # worker→main→ask_user 两道散文接力会磨掉关键锚点。ordering_sensitive 标记有序
    # 轨迹类 claim——它们的改法必须显式处理顺序语义的去留。
    entry = verdict.to_dict() if hasattr(verdict, "to_dict") else {
        "reason": verdict.reason, "min_requests": verdict.min_requests,
        "suggested_fix": verdict.suggested_fix}
    entry["ordering_sensitive"] = claim_kind in ("new_member_last", "absolute_position")
    _land_needs_decision(autoid, claim_kind, entry)
    return render_needs_user_decision(autoid, verdict)


@tool(parse_docstring=True)
def compile_report_underdetermined(autoid: str, reason: str, suggested_fix: str = "",
                                   ordering_sensitive: bool = False) -> str:
    """Report a NON-distribution underdetermined case (e.g. the intent's verification path does not exist on this testbed) so the engine asks the user — lands a structured ledger, does not hard-code around it.

    **When to use**: the intent cannot be verified on THIS testbed and no equivalent variant
    within the intent realizes it — e.g. the trigger host cannot emit the traffic form the
    intent requires, a required peer/segment is absent, or the observable the intent needs has
    no probe here. This is underdetermined too, not something to guess an assertion around.
    **When NOT to use**: distribution/rotation/position claims of algorithm cases → those go
    through ``compile_check_verifiability`` (it does the math). Statically-determined
    expectations (config-exists / protocol-fixed) are not underdetermined — just assert them.

    Landing a structured ledger (needs_decision.json) is required by the engine's ask flow
    ("ask first, land after"): a bare ``STATUS: needs_user_decision`` line with no ledger is
    treated as no-output and escalated (655173 evidence). This tool writes the ledger and
    returns the marker for you to pass back verbatim.

    Args:
        autoid: the case autoid.
        reason: why it is unverifiable on this bed (be concrete: which host/observable/path is missing).
        suggested_fix: optional direction for the user (change the description / process / expected, or note the missing bed capability).
        ordering_sensitive: true if the intent carries ordered/temporal semantics whose loss must be an explicit user decision.

    Returns:
        "NEEDS_USER_DECISION autoid=… reason …" — stop, do not write an assertion, return this
        verbatim to the engine (which aggregates it into an ask_user).
    """
    landed = _land_needs_decision(autoid, "verification_path_absent", {
        "reason": str(reason or ""), "suggested_fix": str(suggested_fix or ""),
        "ordering_sensitive": bool(ordering_sensitive)})
    ledger = "landed to needs_decision.json" if landed else "ledger write FAILED (report to engine)"
    return (f"NEEDS_USER_DECISION autoid={autoid} kind=verification_path_absent\n"
            f"reason: {reason}\n"
            + (f"suggested_fix: {suggested_fix}\n" if suggested_fix else "")
            + f"({ledger}; return this verbatim to the engine — do NOT write an assertion around it)")


@tool(parse_docstring=True)
def compile_user_decision(autoid: str, decision: str, assertion_form: str = "",
                          note: str = "", drop_ordering: bool = False) -> str:
    """把用户对欠定 case 的拍板落成机读约束文件(emit 出口门按它核对产物,重派 brief 引用它)。

    本工具只做三件机械事:①校验存在真实的用户问答记录(先问后落);②从
    needs_decision.json 台账**复制**事实锚(min_requests 取各 claim 最大值、
    claim_kinds_preserved 照 ordering_sensitive 原件)——不经手抄(实证:凭记忆
    均一化 min_requests、并组时顺序锚被磨掉);③原样落盘。**断言形态是语义决策,
    工具不代判**——由用户答案决定、你如实传入。

    Args:
        autoid: 该 case 的 autoid(18 位)。
        decision: 用户选择,三选一——改过程 / 改预期 / 改描述(改描述=用例本身歧义
            待人工厘清,不落断言形态约束)。
        note: 用户的补充说明,原样落盘。
        assertion_form: 用户拍板的断言形态(dist/member/captured_relation 之一),
            改过程/改预期时必传——写用户答案里真实对应的那个,emit 出口按它核对产物。
        drop_ordering: 用户**显式批准放弃顺序语义**时传 True(ask_user 选项文本必须
            写明了这一点)——claim_kinds_preserved 置空,产物不再要求顺序锚;台账有
            ordering_sensitive claim 而未传 True 时,顺序锚保留、emit 出口会要求产物
            能证明顺序。

    Returns:
        落盘路径 + 生成的约束回显(重派 brief 直接引用文件路径,不手抄内容)。
    """
    from pathlib import Path
    aid = (autoid or "").strip()
    dec = (decision or "").strip()
    if not aid or len(aid) != 18 or not aid.isdigit():
        return f"error: autoid 必须是 18 位数字,收到 {autoid!r}"
    if dec not in ("改过程", "改预期", "改描述"):
        return f"error: decision 三选一(改过程/改预期/改描述),收到 {decision!r}"

    root = Path(__file__).resolve().parents[4]

    # 「先问后落」机械门(2026-07-05 事故驱动):orchestrator 曾在 ask_user 之前对
    # 8 个欠定 case 自己调本工具拍板(含 drop_ordering=True)——prompt 红线拦不住,
    # 只有凭证是 A 层。校验 runtime/ask_user_answers.jsonl(ask_user 工具对每次
    # 真实问答自动落的台账)里存在**含该 case 指代**(autoid 全名或尾 6 位)的记录。
    _qa_log = root / "runtime" / "ask_user_answers.jsonl"
    _asked = False
    try:
        if _qa_log.is_file():
            _tail6 = aid[-6:]
            for _line in _qa_log.read_text(encoding="utf-8").splitlines():
                if aid in _line or _tail6 in _line:
                    _asked = True
                    break
    except Exception:  # noqa: BLE001
        _asked = False
    if not _asked:
        return (f"error: 没有找到关于 case …{aid[-6:]} 的真实用户问答记录"
                "(runtime/ask_user_answers.jsonl)——先用 ask_user 把欠定问题问用户"
                "(问题或答案里带上该用例的 autoid 或尾 6 位),拿到答案再落决策。"
                "用户没批过的决定不能落盘。")

    outd = root / "workspace" / "outputs" / aid
    outd.mkdir(parents=True, exist_ok=True)

    claims: list[dict] = []
    nd_path = outd / "needs_decision.json"
    if nd_path.is_file():
        try:
            _nd = json.loads(nd_path.read_text(encoding="utf-8"))
            claims = [c for c in (_nd.get("claims") or []) if isinstance(c, dict)]
        except Exception:  # noqa: BLE001
            logger.debug("needs_decision.json 读取失败(按无台账落)", exc_info=True)

    ud: dict = {"autoid": aid, "decision": dec}
    if note.strip():
        ud["note"] = note.strip()
    if dec != "改描述":
        # 形态是语义决策——必须显式传入(用户答案里真实对应的那个),工具不代判
        form = (assertion_form or "").strip()
        if form not in ("dist", "member", "captured_relation"):
            return ("error: 改过程/改预期必须显式传 assertion_form"
                    "(dist/member/captured_relation 之一,按用户答案如实填)——"
                    f"收到 {assertion_form!r}。形态是语义决策,本工具不代填默认值。")
        ud["expected_assertion_form"] = form
        # 以下为台账事实的机械复制(不代判):
        mins = [int(c.get("min_requests") or 0) for c in claims]
        if any(m > 0 for m in mins):
            ud["min_requests"] = max(mins)
        ordering_kinds = [str(c["claim_kind"]) for c in claims
                          if c.get("ordering_sensitive") and c.get("claim_kind")]
        ud["claim_kinds_preserved"] = [] if drop_ordering else ordering_kinds
    if drop_ordering:
        ud["ordering_dropped_by_user"] = True

    ud_path = outd / "user_decision.json"
    ud_path.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    rel = ud_path.relative_to(root)
    return (f"已落盘 {rel}\n{json.dumps(ud, ensure_ascii=False)}\n"
            "重派 brief 引用该文件路径即可,emit 出口会按它机械核对产物;"
            + ("台账无 claims,只落了 decision/形态。" if not claims else
               f"锚取自台账 {len(claims)} 条 claim。"))
