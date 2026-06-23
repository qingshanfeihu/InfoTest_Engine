"""用例编译的检索与评估 tools:把置信函数 f() + 已验证先例检索 包成 agent 可调的 tool。

**red line(goal:不许硬代码)**:本文件不写"某模式该用某断言形态"的规则表、不做关键词意图匹配、
不派魔数分。检索只按**客观配置结构相似度**,判分交给 **LLM 看真实证据**(已验证先例+手册+需求)。

角色对应:
- compile_precedent(先例检索):给你的用例配置,按"配置结构相似度"返回最像的已验证先例
  (客观距离,不判模式、不派分)。你自己看先例的断言形态、自己归纳该怎么测。
- compile_score(质量评估判据):把"待判断言+所测配置+已验证先例+原始需求"喂给 LLM 判分,
  给CUT/PASS决策。不替代上机 verdict——verdict 看"能不能跑通",f() 看"是不是要测的那个行为"。

红线:f() 只做快筛+abstain,绝不单独定生死;终判仍上机(dev_run_case)。
"""
from __future__ import annotations

import logging
import re as _re
import threading
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MIRROR = Path(__file__).resolve().parents[4] / "knowledge" / "framework" / "mirror"
_INTENT_INDEX_PATH = (
    Path(__file__).resolve().parents[4]
    / "knowledge" / "framework" / "mirror_intent_index.json"
)

_INTENT_INDEX_CACHE: dict | None = None

# mirror 先例语料缓存（per-file 静态解析只做一次）。根因：compile_precedent 原本每次调用都
# openpyxl 全量加载 380+ 个 mirror xlsx，16 并发 draft 下被 GIL 串行化成 CPU 墙（编译慢的主因）。
# 静态部分（cfg_tokens + 触发→断言链 seq）缓存一次；相似度仍每次按 query 实时算，结果不变。
_MIRROR_CORPUS_CACHE: list[dict] | None = None
_MIRROR_CORPUS_LOCK = threading.Lock()


def _load_mirror_corpus() -> list[dict]:
    """解析全部 mirror 先例 xlsx **一次**并缓存：返回 [{fn, cfg_tokens, seq}, ...]。

    线程安全（双检 + 锁）：16 并发 draft 同时首调时只有一个线程解析，其余复用，
    避免 16×380 次重复 openpyxl 加载。mirror 在一次运行内静态，无需失效。
    """
    global _MIRROR_CORPUS_CACHE
    if _MIRROR_CORPUS_CACHE is not None:
        return _MIRROR_CORPUS_CACHE
    with _MIRROR_CORPUS_LOCK:
        if _MIRROR_CORPUS_CACHE is not None:
            return _MIRROR_CORPUS_CACHE
        import glob as _glob
        import openpyxl
        corpus: list[dict] = []
        for fp in _glob.glob(str(_MIRROR / "**" / "*.xlsx"), recursive=True):
            try:
                ws = openpyxl.load_workbook(fp, data_only=True).active
            except Exception:  # noqa: BLE001
                continue
            rows = []
            for r in range(29, ws.max_row + 1):
                E = str(ws.cell(r, 5).value or "").strip()
                F = str(ws.cell(r, 6).value or "").strip()
                G = str(ws.cell(r, 7).value or "").strip()
                if E or F:
                    rows.append({"E": E, "F": F, "G": G})
            if not rows:
                continue
            cfg = " ".join(r["G"] for r in rows if r["E"].startswith("APV") and r["G"])
            # 返回**完整**链：APV 配置基线(含 sdns on / 启用 / 池法 等)+ show + 触发 + 断言。
            # 旧版只留 show/method，把配置基线滤掉 → draft 看不到完整可用配置 → 拼出残缺配置
            # (缺 sdns on 致服务不起、dig 零解析、断言全 fail)。基线必须原样可见,draft 才能照抄。
            seq = [(r["E"], r["F"], r["G"]) for r in rows
                   if r["E"] in ("test_env", "check_point", "time") or r["E"].startswith("APV")]
            corpus.append({"fn": Path(fp).name, "cfg_tokens": _cmd_tokens(cfg), "seq": seq[:40]})
        _MIRROR_CORPUS_CACHE = corpus
        logger.info("mirror 先例语料已缓存: %d 个先例", len(corpus))
        return _MIRROR_CORPUS_CACHE


def _load_intent_index() -> dict:
    """懒加载 {xlsx_basename: [intent_path,...]} 意图索引（build_intent_index 产出）。

    索引缺失/损坏 → 返回空 dict（intent 轴自动退化为不可用，config 轴照常）。
    """
    global _INTENT_INDEX_CACHE
    if _INTENT_INDEX_CACHE is not None:
        return _INTENT_INDEX_CACHE
    import json as _json
    try:
        _INTENT_INDEX_CACHE = _json.loads(
            _INTENT_INDEX_PATH.read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001
        _INTENT_INDEX_CACHE = {}
    return _INTENT_INDEX_CACHE


def _intent_tokens(text: str) -> set:
    """意图文本分词：中英文混排，取 ≥2 字的中文片段 + 字母词，丢标点/分隔符。

    意图相似度初版用词重叠即可（PLAN §八：别一上来上向量库 YAGNI）。
    """
    toks = set()
    for w in _re.findall(r"[a-zA-Z][a-zA-Z_]+", text or ""):
        toks.add(w.lower())
    # 中文按 2-gram 切（无分词器，bigram 足够捕捉"健康检查""通道建立"等共现）
    for seg in _re.findall(r"[一-鿿]+", text or ""):
        for i in range(len(seg) - 1):
            toks.add(seg[i:i + 2])
        if len(seg) == 1:
            toks.add(seg)
    return toks


def _intent_similarity(intent: str, intent_paths: list[str]) -> float:
    """intent 与某 xlsx 的 intent_path 列表的最大词重叠相似度（Jaccard）。"""
    q = _intent_tokens(intent)
    if not q:
        return 0.0
    best = 0.0
    for path in intent_paths:
        a = _intent_tokens(path)
        if not a:
            continue
        sim = len(a & q) / len(a | q)
        if sim > best:
            best = sim
    return best



def _load_case_rows(xlsx_path: str) -> list[dict]:
    """读 case.xlsx 数据区为 [{E,F,G}...],遇哨兵 case(999...)停。"""
    import openpyxl
    ws = openpyxl.load_workbook(xlsx_path, data_only=True).active
    rows = []
    for r in range(29, ws.max_row + 1):
        A = ws.cell(r, 1).value
        if A and str(A).startswith("999999"):
            break
        E = str(ws.cell(r, 5).value or "").strip()
        F = str(ws.cell(r, 6).value or "").strip()
        G = str(ws.cell(r, 7).value or "").strip()
        if E or F:
            rows.append({"E": E, "F": F, "G": G})
    return rows


def _cmd_tokens(text: str) -> set:
    """取命令词(字母开头的词),丢具体值(IP/数字/引号串)→ 只比'配了什么命令'。客观,无领域偏好。"""
    toks = set()
    for w in _re.findall(r"[a-zA-Z][a-zA-Z_]+", text or ""):
        toks.add(w.lower())
    return toks


def _resolve_xlsx(xlsx_path: str):
    p = None
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        p = _resolve_inside_root(xlsx_path, must_exist=True)
    except Exception:
        p = None
    if p is None or not Path(p).is_file():
        cands = [Path(xlsx_path)]
        if not Path(xlsx_path).is_absolute():
            root = Path(__file__).resolve().parents[4]
            cands += [root / xlsx_path, root / "knowledge" / "data" / xlsx_path]
        p = next((c for c in cands if c.is_file()), None)
    return p if (p and Path(p).is_file()) else None


@tool(parse_docstring=True)
def compile_precedent(my_config: str, limit: int = 3, intent: str = "") -> str:
    """【先例检索】给你这个用例的配置/意图,返回最像的已验证先例当参考。

    排序看**客观事实**两轴(融合):
    - config 轴:已验证先例配置命令 与 你的 my_config 命令词的重叠度(Jaccard);
    - intent 轴(可选):你的 intent 需求描述 与 该先例对应脑图意图链(intent_path)的文本重叠度。
    不判"测试模式"、不给断言形态派分、不掺领域偏好——纯结构/语义距离。越像的排越前。

    **意图轴治"分布外猜不出 config 就检索不到"**:需求只一句话、还没想好配什么命令时,
    传 intent(原始需求/作者意图原文),靠意图链也能找到骨架先例。my_config 为空但 intent
    非空时,改用纯意图轴检索(不再报错)。两者都传则融合排序。

    你拿到最像的先例后,**自己看它们的断言形态、自己归纳"这类配置该怎么验"**——
    已验证先例清单是参考(Voyager:检索不冻结),你仍自走上机验证,期望值溯源到先例+手册,不凭空编。

    Args:
        my_config: 你这个用例的关键配置命令(多行),用于按结构相似度找最像的先例。可留空(走纯意图轴)。
        limit: 返回先例数(默认3)。
        intent: 原始用例需求/作者意图原文(可选)。传了则启用意图轴,分布外 case 也能凭意图检索到骨架。

    Returns:
        最像的已验证先例 + 它们的完整断言形态(配置→断言的真实写法)。你自己判断哪个适用。
    """
    # 消融实验 Arm-E(基线裸生成):不提供先例约束(G 段),模拟业界默认的无先例自由生成。
    # 生产默认 Arm-L 不进此分支。
    from main.ist_core.tools._shared.ablation import is_baseline
    if is_baseline():
        return ("=== compile_precedent(基线臂:不提供先例) ===\n"
                "本臂不检索已验证先例(对照实验 Arm-E)。请直接依据需求与通用知识生成,"
                "不依赖同类先例的触发→断言形态。")
    my_toks = _cmd_tokens(my_config)
    intent = (intent or "").strip()
    # 向后兼容:config 与 intent 都空才报错;只要有一轴可用就检索（intent 轴治分布外）。
    if not my_toks and not intent:
        return ("error: my_config 与 intent 均为空——请传入你这个用例的关键配置命令"
                "(配置对象/动作那几行),或传 intent(原始需求描述)走意图轴检索。")
    intent_index = _load_intent_index() if intent else {}
    cands = []
    # 用缓存语料（静态解析一次），每个先例按本次 query 实时算相似度。
    for entry in _load_mirror_corpus():
        a = entry["cfg_tokens"]
        cfg_sim = (len(a & my_toks) / len(a | my_toks)) if (a and my_toks) else 0.0
        # 意图轴:该 xlsx 的脑图意图链与 intent 的文本重叠度
        intent_sim = 0.0
        if intent:
            paths = intent_index.get(entry["fn"], [])
            if paths:
                intent_sim = _intent_similarity(intent, paths)
        # 融合排序分:两轴都启用时取等权和;只有一轴时退化为该轴。
        if my_toks and intent:
            score = cfg_sim + intent_sim
        elif intent:
            score = intent_sim
        else:
            score = cfg_sim
        if score <= 0:
            continue
        # 返回完整"触发→断言"步骤链(test_env 的 dig/触发 + check_point),不只摘断言——
        # 否则 agent 看不到先例怎么触发的(如 A/AAAA 分查、多次触发),学不全做法。
        cands.append((score, cfg_sim, intent_sim, entry["fn"], entry["seq"]))
    cands.sort(key=lambda x: -x[0])
    hits = [c for c in cands[:limit] if c[0] > 0]
    if not hits:
        return ("=== compile_precedent ===\n你的配置/意图在先例库里没有结构相近的先例(分布外/新类型)。\n"
                "→ 没有现成范式可抄,你得自己查手册推断该测什么 + 上机验证;f() 会因无锚点给低置信,"
                "做不出就诚实上报(escalate-when-stuck)。")
    axis = "config+intent 融合" if (my_toks and intent) else ("intent 意图轴" if intent else "config 结构轴")
    out = [f"=== compile_precedent(按{axis}相似度排序;含完整触发→断言链)==="]
    for score, cfg_sim, intent_sim, fn, seq in hits:
        if my_toks and intent:
            tag = f"配置{cfg_sim:.2f}+意图{intent_sim:.2f}"
        elif intent:
            tag = f"意图{intent_sim:.2f}"
        else:
            tag = f"相似度{cfg_sim:.2f}"
        out.append(f"\n先例 {fn}({tag})的触发→断言链:")
        for e, f, g in seq:
            # 多行 cmds_config 用**真换行**展示(缩进续行),draft 照抄即得真 \n——
            # 切勿用 ⏎ 等替身字符:draft 会把字面替身抄进配置,框架按 \n 拆命令时整串变一条废命令。
            g_show = g[:300].replace("\n", "\n        ")
            out.append(f"  {e} {f}: {g_show}")
    out.append("\n⚠ 照先例的**完整配置基线**写,别截断:先例里的启用/激活步(如 sdns on)、"
               "数据中心/池法/监听器等基线步**一个都不能漏**——漏了设备服务起不来、dig 零解析、断言全 fail。"
               "先例'怎么配(完整基线)+怎么触发(dig 类型/次数)+怎么断言'是配套的,照它整条链写。"
               "期望值溯源到先例+手册;离线不可知的运行时值(dig 解析出的具体 IP 等)留 <RUNTIME>,别编。")
    # 契约:先例 G 列可能混有不可达示例 IP(1.1.1.1 等历史脏数据)。在同一返回里附上本测试床
    # 真实可达集合,让你写 IP 时取真值,别照抄先例的示例 IP——emit 出口会按此校验,不可达必打回。
    try:
        from main.ist_core.tools._shared.env_facts import get_env_facts
        facts = get_env_facts()
        if facts.devices:
            out.append("\n" + facts.summary_for_agent())
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(out)


@tool(parse_docstring=True)
def compile_score(xlsx_path: str, need_intent: str = "",
                        anchor_examples: str = "", manual_facts: str = "") -> str:
    """【质量评估判据】判 case.xlsx 的断言"配不配得上它所测的配置行为",给CUT/PASS决策(LLM判,无硬规则)。

    **第二判据,不是 verdict**:dev_run_case 看"能不能跑通"(弱断言 found 一个总在的域名也 pass);
    本工具看"断言有没有咬住需求要测的行为"。

    **判分由 LLM 看真实证据现场判**(原始需求 + 每个断言所测的配置 + 已验证先例 + 手册行为),
    不写"某模式该怎样"的规则、不派魔数。证据越全判得越准:先用 compile_precedent 拿先例填
    anchor_examples、grep 手册填 manual_facts,再调本工具。

    overall<0.5 → CUT:断言没咬住需求行为,看 reason 换做法重写,别充数。
    overall≥0.5 → 放行候选,终判仍以上机 verdict 为准(f() 只快筛,不单独定生死)。
    最弱 check_point 拖垮全局(防一堆强断言掩护一个弱断言——这是结构规则,非领域硬编码)。

    Args:
        xlsx_path: 本地 case.xlsx 路径。
        need_intent: 原始用例需求/作者意图原文(用于跨层对齐判定)。
        anchor_examples: compile_precedent 返回的同类已验证先例文本(判分锚点,强烈建议填)。
        manual_facts: grep 手册得到的"该配置该产生什么可观测行为"(判分依据,建议填)。

    Returns:
        overall置信 / CUTor放行 / 每个 check_point 的 score + LLM 理由。
    """
    # 消融实验 Arm-E(基线裸生成):无质量门,一律放行(模拟业界默认的无 grade 审批)。
    # 生产默认 Arm-L 不进此分支。
    from main.ist_core.tools._shared.ablation import is_baseline
    if is_baseline():
        import json as _json
        return _json.dumps({
            "tool": "compile_score", "arm": "E_baseline",
            "note": "基线臂:无质量审批门,直接放行(对照实验 Arm-E)",
            "overall": 1.0, "abstain": False, "decision": "PASS(基线臂不判分)",
            "checkpoints": [],
        }, ensure_ascii=False, indent=2)
    p = _resolve_xlsx(xlsx_path)
    if p is None:
        return f"error: xlsx 不存在: {xlsx_path}(用 fs_ls 看真实落盘路径)"
    try:
        from main.case_compiler.confidence_f import score_case
        rows = _load_case_rows(str(p))
    except Exception as exc:  # noqa: BLE001
        return f"error: 读取失败: {exc}"
    if not rows:
        return "error: xlsx 数据区为空,无 check_point 可判"

    res = score_case(rows, need_intent=need_intent,
                     anchor_examples=anchor_examples, manual_facts=manual_facts)
    import json as _json
    # 统一 JSON 格式化返回(不再拼文本):保留逐 check_point 的 score/理由结构,
    # 下游(agent/driver)可直接 json.loads 取结构化判分,不用正则从文本抠数字。
    if res.get("reason") and not res.get("rows"):
        return _json.dumps({
            "tool": "compile_score", "abstain": True, "overall": 0.0,
            "decision": "abstain", "reason": res["reason"],
            "hint": "f() 不在缺 LLM 时硬猜分;确保判分模型可用,或直接 dev_run_case 由 verdict 兜底。",
            "checkpoints": [],
        }, ensure_ascii=False, indent=2)
    out = {
        "tool": "compile_score",
        "note": "第二判据(LLM据证据判,非框架verdict);质量评估判据",
        "overall": round(res["overall"], 2),
        "abstain": res["abstain"],
        "decision": "CUT/abstain(断言没咬住需求行为,该换做法重写)" if res["abstain"]
                    else "放行候选(终判仍以上机 verdict 为准)",
        "checkpoints": [
            {"assertion": rs.cp_g, "score": round(rs.score, 2),
             "reasons": [n for n in rs.notes if n]}
            for rs in res.get("rows", [])
        ],
        "how_to_use": "CUT→看每个checkpoint的reasons,用compile_precedent查相似先例正确断言形态改写;放行→dev_run_case上机终判。",
    }
    return _json.dumps(out, ensure_ascii=False, indent=2)
