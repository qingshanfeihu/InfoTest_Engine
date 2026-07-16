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
import os

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _write_json_atomic(path, obj) -> None:
    """原子落盘 JSON:tmp + os.replace(同 batch_tools last_run 先例)。裸 write_text 被
    Ctrl-C/崩溃打断会留截断文件——needs_decision/user_decision 是「先问后落」台账 + 放行凭据,
    截断=损坏(96 份交付中 1 份实证 needs_decision.json 截断),下轮读崩或凭据失效。
    os.replace 是原子操作、无半写窗口;内容与旧 write_text 逐字节等价(仅崩溃安全性变化)。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _norm(s: str) -> str:
    """字面转义还原 + 空白折叠(同 fail_attribution._norm 先例算法——子串门防转述/
    参数序列化失真,非字节保真;两侧同款归一化后判子串,编造的内容照样对不上)。"""
    s = str(s or "")
    s = s.replace("\\r", " ").replace("\\n", " ").replace("\\t", " ")
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = s.replace("\xa0", " ")   # 脑图 xlsx 常带非断空格(NBSP),否则含它的诚实引用假失败
    return " ".join(s.split())


def _case_mindmap_slice(autoid: str) -> str | None:
    """该案脑图切片(§18.13 子串门 corpus):manifest 的 title + 逐 step_intents 的
    desc/expected 拼接。工具只有 autoid,遍历 outputs/*/manifest.json 定位。
    找不到返回 None(门 fail-open 留声,manifest 缺席是环境问题非 worker 造假)。"""
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parents[4]
        outs = root / "workspace" / "outputs"
        aid = str(autoid or "").strip()
        for mf in outs.glob("*/manifest.json"):
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for c in (m.get("cases") or []):
                if str(c.get("autoid")) == aid:
                    parts = [str(c.get("title") or "")]
                    for si in (c.get("step_intents") or []):
                        parts.append(str(si.get("desc") or ""))
                        parts.append(str(si.get("expected") or ""))
                    return "\n".join(p for p in parts if p)
    except Exception:  # noqa: BLE001
        logger.debug("_case_mindmap_slice 定位失败", exc_info=True)
    return None


def _substring_gate(sources: list, corpus: str | None) -> str | None:
    """出处子串门:每个 quote 必须是脑图切片的(归一化)子串。返回 error 文本或 None。
    corpus=None(切片不可得)→放行(留声),不误伤。"""
    if corpus is None:
        return None
    ncorpus = _norm(corpus)
    for i, s in enumerate(sources):
        q = str((s or {}).get("quote") or "").strip()
        if not q:
            return (f"error: sources[{i}] has an empty quote — every source must quote a "
                    f"verbatim fragment of this case's mindmap (title/step desc/expected).")
        if q not in corpus and _norm(q) not in ncorpus:
            return (f"error: sources[{i}].quote {q[:60]!r} is NOT a substring of this case's "
                    f"mindmap text — **copy it directly** from the case's title/step/expected in "
                    f"the mindmap, never retell. Quote a key fragment within a single line "
                    f"(whitespace is normalized, no byte-exact match needed).")
    return None


def _cycle_kind_from_algo(algo: str) -> str | None:
    """算法名→周期语义类映射(E10b 通用性红线:映射属领域知识,放调用方且**数据现查**,
    零算法语义入 .py——新算法=加 grammar JSON 条目零代码)。
    - `algorithm_classes.uniform_rotation.methods` 命中 → "uniform_rotation"(判);
    - `distribution.methods` 命中但非 uniform → None(该算法的剩余类语义未上机钉死,
      纯函数按未知 fail-open 中性放行——wrr/grr/gwrr 现况,C7 钉死后加数据条目);
    - 两者都不中 → "none"(确定性映射无轮转周期——grammar distribution provenance 背书);
    - grammar 不可读 → None(fail-open)。
    worker 显式传 cycle_kind 时本映射不生效(语义抽取优先——LLM 读脑图语境比算法名可靠)。"""
    a = (algo or "").strip().lower()
    if not a:
        return None
    try:
        from main.case_compiler.domain_grammar import (distribution_methods,
                                                       uniform_rotation_methods)
        if a in uniform_rotation_methods():
            return "uniform_rotation"
        if a in distribution_methods():
            return None
        return "none"
    except Exception:  # noqa: BLE001
        return None


def _parse_sequence_json(sequence_json: str) -> tuple[list[int], list[int]] | str:
    """sequence_json → (found_idx, notfound_idx)。元素按请求序:"found"|"not_found"|null
    (null=该次对该成员无断言)。解析失败返回 error 文本。"""
    try:
        seq = json.loads(sequence_json)
    except Exception as e:  # noqa: BLE001
        return f"error: sequence_json 解析失败: {e}"
    if not isinstance(seq, list):
        return f"error: sequence_json 必须是 JSON 数组,收到 {type(seq).__name__}"
    found_idx: list[int] = []
    notfound_idx: list[int] = []
    for i, x in enumerate(seq):
        if x == "found":
            found_idx.append(i)
        elif x == "not_found":
            notfound_idx.append(i)
        elif x is None:
            continue
        else:
            return (f"error: sequence_json[{i}]={x!r} 非法——元素取 \"found\"/"
                    f"\"not_found\"/null(该次无该成员断言)")
    return found_idx, notfound_idx


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
        _write_json_atomic(nd_path, data)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("needs_decision.json 落盘失败", exc_info=True)
        return False


@tool(parse_docstring=True)
def compile_check_verifiability(autoid: str, algo: str, n_requests: int, n_pools: int,
                                claim_kind: str, weights_json: str = "",
                                existing_pools: int = -1, sequence_json: str = "",
                                cycle_kind: str = "") -> str:
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
            relation_same（两次相同·会话保持）/ relation_diff（两次不同·切换）/
            cross_client_landing（特定客户端命中特定池/跨客户端共享轮转的落点主张——
            计数器跨客户端共享还是独立由设备实现决定，分布算法下该主张无手册/判例
            支撑即欠定；可验等价=同客户端关系断言或按客户端分组的分布区间，对应用户
            拍板形态 captured_relation/dist）。
        weights_json: wrr 各 pool 权重的 JSON 数组（按关联顺序，如 "[3,2,1]"）；非 wrr 留空。
        existing_pools: new_member_last 用——新增前已有的 pool 数；缺省 -1 表示按 n_pools-1 推。
        sequence_json: 可选，时序自洽自查（claim_kind ∈ rotation_order/absolute_position/
            new_member_last 时生效）——**单一成员视角**按请求序的 JSON 数组，元素
            "found"|"not_found"|null（null=该次对该成员无断言），如
            '["not_found","not_found","not_found","found","found"]'。工具附加做剩余类
            可满足性判定：排布与声明周期数学恒假（任何设备行为下断言组都不可能全真）
            → 覆盖为 NEEDS_USER_DECISION 呈报。
        cycle_kind: 可选，周期语义类（uniform_rotation=等权严格轮转/weighted=加权/
            none=确定性映射无周期）——从脑图语境语义抽取后传入；留空则按 algo 从
            domain_grammar.json 算法分类数据现查。语义未知一律中性放行不误杀。

    Returns:
        verifiable → "VERIFIABLE: <说明>"（worker 继续选对断言形态落盘）；
        欠定 → "NEEDS_USER_DECISION autoid=… 原因 … 最小可验请求数 … 建议修法 …"
        （worker **不要**编断言，原样把这段返回给 orchestrator）。
    """
    try:
        from main.case_compiler.verifiability import (check_sequence_periodicity,
                                                      check_verifiability,
                                                      render_needs_user_decision)
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

    # E10b 附加:序列↔周期自洽(advisory;开关+传参双门)。周期语义类=显式传参优先
    # (worker 语义抽取),否则按 algo 从 grammar 算法分类数据现查——映射是数据不是代码,
    # 新算法加 JSON 条目零代码(通用性红线 2026-07-16)。
    seq_verdict = None
    _seq_on = os.environ.get("IST_SEQ_CONSISTENCY_CHECK", "1").strip().lower() not in (
        "0", "false", "no")
    if (_seq_on and sequence_json and sequence_json.strip()
            and claim_kind in ("rotation_order", "absolute_position", "new_member_last")):
        parsed_seq = _parse_sequence_json(sequence_json)
        if isinstance(parsed_seq, str):
            return parsed_seq
        found_idx, notfound_idx = parsed_seq
        ck = (cycle_kind or "").strip().lower() or _cycle_kind_from_algo(algo)
        seq_verdict = check_sequence_periodicity(ck, n_pools, found_idx, notfound_idx,
                                                 algo=algo)
        if not seq_verdict.verifiable:
            # 数学恒假覆盖主判定:独立落台账条目(claim_kind=sequence_periodicity),
            # 与主 claim 的台账并存——改法必须同时对得上两条。
            seq_entry = seq_verdict.to_dict()
            seq_entry["ordering_sensitive"] = True
            _land_needs_decision(autoid, "sequence_periodicity", seq_entry)
            return render_needs_user_decision(autoid, seq_verdict)

    if verdict.verifiable:
        note = ("；" + "；".join(verdict.notes)) if verdict.notes else ""
        seq_note = ""
        if seq_verdict is not None and seq_verdict.verifiable:
            seq_note = f"；序列自洽自查:{seq_verdict.reason}"
        return f"VERIFIABLE: {verdict.reason}{note}{seq_note}"
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
def compile_report_underdetermined(autoid: str, test_point: str = "", sources_json: str = "",
                                   obstacle: str = "", equivalent_procedure: str = "",
                                   equivalent_preserves: str = "", no_equivalent_reason: str = "",
                                   ordering_sensitive: bool = False,
                                   reason: str = "", suggested_fix: str = "") -> str:
    """Report a NON-distribution underdetermined case (the intent's verification path cannot run as-written on this testbed) so the engine asks the USER — lands a structured triple the panel shows verbatim, does not hard-code around it.

    **When to use**: the intent cannot be verified AS WRITTEN on this testbed — e.g. it needs a
    device reboot/power-cycle this bed forbids, a trigger host that cannot emit the required
    traffic, or an absent peer/segment. Underdetermined, not something to guess an assertion for.
    **When NOT to use**: distribution/rotation/position algorithm claims → ``compile_check_verifiability``
    (it does the math). Statically-determined expectations (config-exists / protocol-fixed) → just assert.

    **The fields below are shown to the USER verbatim — write them as clear Chinese sentences.**
    Fill them by walking the reasoning the user needs: state the test point (quoting the mindmap),
    name why this bed can't run it, then — if you can — give a config-plane equivalent that keeps
    the SAME falsifying observation, or say honestly why no equivalent exists. This IS the analysis;
    the panel is your report, projected 1:1.

    Args:
        autoid: the case autoid.
        test_point: 中文一句话说清这个用例要验证的行为(R)。引用脑图原文的部分放进 sources。
        sources_json: JSON array ``[{"kind":"step|expected|title","quote":"…"}]`` — each quote MUST be a verbatim substring of THIS case's mindmap (title/step desc/expected). Copy directly, do not retell; a mechanical gate rejects non-substrings.
        obstacle: 中文说清本测试床为何跑不了原写法(事实,如"自动化环境无法重启:断连即无法继续")。
        equivalent_procedure: 中文,若能给出保持同一证伪观测的等价验证步骤就写在这(具体、可读的一句)。给不出留空。
        equivalent_preserves: 中文,若给了 equivalent,说明它为何保持原证伪观测(供用户判断,你的自评)。
        no_equivalent_reason: 中文,equivalent_procedure 为空时必填——如实说明为何推不出等价方案(挂起理由)。
        ordering_sensitive: true if the intent carries ordered/temporal semantics whose loss must be an explicit user decision.
        reason: (legacy, optional) free-text fallback if you are not using the triple fields yet.
        suggested_fix: (legacy, optional) free-text fallback.

    Returns:
        "NEEDS_USER_DECISION autoid=…" — stop, do not write an assertion, return this verbatim to
        the engine (which projects the triple into the user panel).
    """
    # 兼容路径:只给了 legacy reason(未用三元组)→ 原样落,不启子串门(旧调用/旧测试)。
    if not test_point and not sources_json:
        landed = _land_needs_decision(autoid, "verification_path_absent", {
            "reason": str(reason or ""), "suggested_fix": str(suggested_fix or ""),
            "ordering_sensitive": bool(ordering_sensitive)})
        ledger = "landed" if landed else "ledger write FAILED (report to engine)"
        return (f"NEEDS_USER_DECISION autoid={autoid} kind=verification_path_absent\n"
                f"reason: {reason}\n"
                + (f"suggested_fix: {suggested_fix}\n" if suggested_fix else "")
                + f"({ledger}; return this verbatim — do NOT write an assertion around it)")
    # 三元组路径(§18.13)。
    try:
        sources = json.loads(sources_json) if sources_json else []
        if not isinstance(sources, list):
            return f"error: sources_json must be a JSON array of {{kind,quote}}, got {type(sources).__name__}"
    except Exception as e:  # noqa: BLE001
        return f"error: sources_json parse failed: {e}"
    if not test_point.strip():
        return "error: test_point is required (state the behavior under test in Chinese)."
    if not obstacle.strip():
        return "error: obstacle is required (why this bed can't run it as-written, in Chinese)."
    if not equivalent_procedure.strip() and not no_equivalent_reason.strip():
        return ("error: give either equivalent_procedure (a config-plane equivalent) OR "
                "no_equivalent_reason (why none exists) — one is required.")
    # 出处子串门(P2:corpus=manifest 切片,两侧 _norm)。
    gate = _substring_gate(sources, _case_mindmap_slice(autoid))
    if gate:
        return gate
    has_equiv = bool(equivalent_procedure.strip())
    entry = {
        "test_point": test_point.strip(),
        "sources": [{"kind": str((s or {}).get("kind") or ""),
                     "quote": str((s or {}).get("quote") or "")} for s in sources],
        "obstacle": obstacle.strip(),
        "equivalent": ({"procedure": equivalent_procedure.strip(),
                        "preserves": equivalent_preserves.strip()} if has_equiv else None),
        "no_equivalent_reason": no_equivalent_reason.strip(),
        "ordering_sensitive": bool(ordering_sensitive),
        # 兼容字段:旧渲染/日志仍读 reason/suggested_fix(合成兜底,不影响三元组投影)。
        "reason": f"{test_point.strip()} / 障碍:{obstacle.strip()}",
        "suggested_fix": equivalent_procedure.strip() or no_equivalent_reason.strip(),
    }
    # P2:claim_kind 保持 verification_path_absent(ledger mech,_land 不 activelock);
    # 呈现形态由 equivalent 字段有无派生,不新增 claim_kind。
    landed = _land_needs_decision(autoid, "verification_path_absent", entry)
    ledger = "landed" if landed else "ledger write FAILED (report to engine)"
    return (f"NEEDS_USER_DECISION autoid={autoid} kind=verification_path_absent "
            f"equivalent={'yes' if has_equiv else 'none'}\n"
            f"test_point: {test_point.strip()}\n"
            f"({ledger}; return this verbatim — the engine projects the triple into the user panel)")


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
    # H1(§18.11 横切,2026-07-14 对抗评审 BLOCKER):form 要求按 claim_kind 条件化。
    # 机制类 claim(验证路径缺失/禁令机制)的「改过程」语义是**换实现路径**,不存在
    # dist/member 形态可选——旧的无条件 form 门使引擎侧 ask_decision(不传 form)
    # 对这两类落盘必败→决策丢失下轮重问(问询活锁;655248 走通纯因选了改描述)。
    # 台账全为机制类 → 免 form;含任一形态类 claim → 仍旧强制(形态是语义决策不代判)。
    # §18.14 D1:command_existence(换版本内命令)/missing_teardown(补恢复步)同属"换
    # 实现路径"、无 dist/member 形态可选——也免 form,否则经 ask_decision 答改过程同样
    # 活锁(668059 command_existence + G1 missing_teardown 姊妹分支,655248 形态)。
    _MECH_KINDS = {"verification_path_absent", "forbidden_mechanism",
                   "command_existence", "missing_teardown"}
    _mech_only = bool(claims) and all(
        str(c.get("claim_kind")) in _MECH_KINDS for c in claims)
    if dec != "改描述" and not _mech_only:
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
    _write_json_atomic(ud_path, ud)
    rel = ud_path.relative_to(root)
    return (f"已落盘 {rel}\n{json.dumps(ud, ensure_ascii=False)}\n"
            "重派 brief 引用该文件路径即可,emit 出口会按它机械核对产物;"
            + ("台账无 claims,只落了 decision/形态。" if not claims else
               f"锚取自台账 {len(claims)} 条 claim。"))
