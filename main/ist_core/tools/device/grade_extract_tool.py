"""compile_grade_extract: grade 子流程的确定性探针工具（包装 grade_extract.extract）。

为什么是工具不是 run_python：grade fork 此前靠 `run_python` 跑
`skills/ist-compile-grade/scripts/grade_extract.py`，但 fork 的 run_python cwd/sys.path 不含
项目根、相对路径又依赖 CWD——实测 grade 找不到脚本（"script doesn't exist"）直接 fallback
肉眼判，确定性信号（distribution_coverage_gap_suspect / layer_mismatch / weak_v_coverage_suspect
等）全没生效、放水（778012 写死命中 IP + Hit:固定数 带病 PASS 即此根因）。包成工具后在主进程
内按**绝对路径** importlib 加载 extract()，免 CWD/路径之祸，grade 第一步必能拿到信号。

脚本仍留在 skill 目录（anthropics skill 自洽、可单独命令行跑），本工具只按文件路径加载其 extract()。
红线：只透传 grade_extract 的确定性信号，不下 PASS/CUT 终判（终判仍由 grade LLM 据真证据现场判）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.tools import tool


def _load_extract():
    """importlib 按文件路径加载 skill 目录下 grade_extract.py 的 extract()（非 main 包内模块）。"""
    import importlib.util as ilu

    root = Path(__file__).resolve().parents[4]
    script = (root / "main" / "ist_core" / "skills"
              / "ist-compile-grade" / "scripts" / "grade_extract.py")
    if not script.is_file():
        raise FileNotFoundError(f"grade_extract.py 不存在: {script}")
    spec = ilu.spec_from_file_location("ist-compile-grade_extract", script)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载 grade_extract spec")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.extract


@tool(parse_docstring=True)
def compile_grade_extract(xlsx_path: str, prov_path: str = "-") -> str:
    """对一份 case.xlsx 跑确定性探针，返回 V 段覆盖/恒真/分布等结构化信号（grade 判定前第一步必做）。

    grade 第一步调它（别再用 run_python 跑脚本——fork 里 cwd/路径不稳、会找不到脚本而放水）。
    它只产**确定性信号**、不下终判；终判由你据真实证据 + source_ref 现场判。

    Args:
        xlsx_path: 待审 case.xlsx 路径。
        prov_path: 对应 case.provenance.json 路径；无 provenance / 不确定时传 "-"。

    Returns:
        JSON。case 级关键信号：has_distribution_method（配了 rr/wrr）、has_distribution_assertion、
        distribution_coverage_gap_suspect（配了分布算法却无分布区间也无关系断言＝漏测分布）、
        weak_v_coverage_suspect、count_tautology_count（无界 Hit:\\d+ 恒真）、
        count_hardcoded_count（写死单计数 Hit:固定数）、hardcoded_hit_ip_count（分布算法下写死单次
        命中落点 IP）、genuine_v_count、suspect_count；每个 check_point 带 mode/expect/layer/
        observe_kind/is_genuine_v_assertion/layer_mismatch/source_kind/各 suspect 标志/suspect_reason。
    """
    xp = (xlsx_path or "").strip()
    if not xp:
        return "error: 必须指定 xlsx_path"
    if not Path(xp).is_file():
        return f"error: case.xlsx 不存在: {xp}"
    try:
        extract = _load_extract()
    except Exception as e:  # noqa: BLE001
        return f"error: 加载 grade_extract 失败: {e}"
    try:
        facts = extract(xp, (prov_path or "-").strip() or "-")
    except Exception as e:  # noqa: BLE001
        return f"error: grade_extract 执行失败: {e}"
    return json.dumps(facts, ensure_ascii=False, indent=1)


@tool(parse_docstring=True)
def submit_verdict(autoid: str, verdict: str, root_cause: str = "",
                   caveats: list | str | None = None, report_md: str = "",
                   xlsx_path: str = "") -> str:
    """grade 审批的**交付动作**:提交机读判定 + 落盘凭证与上机注意事项。审批完必调、只调一次。

    为什么是工具不是末行文本标记:末行「判定：PASS」靠输出纪律维持,历史上被 rfind 误读过
    (「改成 X 才能 PASS」),34-case 实跑还出现过整环节被遗忘;工具化后判定是结构化参数
    (枚举校验)、凭证在工具内落盘(合并门直接认)、caveats 有了流向 ist-verify 的载体
    (旧文本通道里它们随 PASS 一起消失)。**报告正文仍是自由文本**(report_md)——评审理由
    不 schema 化。

    调它之后,仍在返回末行带「判定：PASS|CUT」文本标记(pipeline fallback 的解析兼容)。

    Args:
        autoid: 被审批 case 的完整 autoid。
        verdict: PASS 或 CUT(仅此二值)。
        root_cause: CUT 时必填,二选一:用例预期冲突(期望值无手册/先例支撑且与手册/实机矛盾,
            非 draft 可修)或 可修复(草稿质量问题,重做有望通过)。PASS 时留空。
        caveats: 上机注意事项数组(每项一句话,如需第一发核对的回显/框架观测语义依赖),
            会随凭证落盘供 ist-verify 消费;无则省略。
        report_md: 完整审批报告(自由文本 markdown):逐断言证据、来源核对、重做意见。
        xlsx_path: 被审批 xlsx 路径;省略= workspace/outputs/<autoid>/case.xlsx。

    Returns:
        确认信息(凭证落盘路径 + 判定回显);参数不合法时 error 并说明改法。
    """
    autoid = (autoid or "").strip()
    v = (verdict or "").strip().upper()
    if not autoid:
        return "error: 必须传 autoid"
    if not re.fullmatch(r"\d{18}", autoid):
        return (f"error: autoid 必须是 18 位数字,收到 {autoid!r}({len(autoid)} 位)——"
                "手抄截断 id 会静默生成垃圾目录并混入终卷。从 last_run.json/manifest 机读全名。")
    if v not in ("PASS", "CUT"):
        return f"error: verdict 必须是 PASS 或 CUT,收到 {verdict!r}"
    rc = (root_cause or "").strip()
    if v == "CUT" and rc not in ("用例预期冲突", "可修复"):
        return ("error: 判 CUT 必须给 root_cause(二选一:用例预期冲突 / 可修复),"
                f"收到 {root_cause!r}")
    if isinstance(caveats, str):
        caveats = [c.strip() for c in caveats.splitlines() if c.strip()]
    caveats = [str(c) for c in (caveats or [])]

    root = Path(__file__).resolve().parents[4]
    xp = Path(xlsx_path) if (xlsx_path or "").strip() else (
        root / "workspace" / "outputs" / autoid / "case.xlsx")
    if not xp.is_absolute():
        xp = root / xp
    if not xp.is_file():
        return f"error: case.xlsx 不存在: {xp}(先确认产物路径,或显式传 xlsx_path)"

    # 成品卷 lint:凭证是卷面进入合并的唯一通行证,必崩/必假形态在这里出示
    # (卷面可能不经 compile_emit 被直改——门只放编辑入口挡不住绕行;实证:直改版
    # 带"dig(H)后直接断言"上机 39 秒崩整份 pytest,连续两轮)。PASS 一律拒绝;
    # CUT 放行但把违例并进 caveats(重做者能看见)。
    from main.ist_core.tools.device.structural_gate import lint_xlsx_case
    lint = lint_xlsx_case(xp)
    if not lint.ok:
        lint_lines = [f"[{it.code}] {it.detail}" for it in lint.violations]
        if v == "PASS":
            return ("error: 卷面未过成品 lint,拒绝落 PASS 凭证——以下是机械可判的必崩/必假形态"
                    "(与评审意见无关,任何来源的卷面都必须先改对):\n  - "
                    + "\n  - ".join(lint_lines))
        caveats = list(caveats) + [f"lint违例待修: {ln}" for ln in lint_lines]

    # 凭证:与 compile_score 落盘同文件合并(score 字段保留),xlsx_mtime 为签名字段
    # (合并门校验它精确等于当前 xlsx mtime——只有工具落盘能拿到)。
    import time as _time
    cred_path = xp.parent / ".grade_credential.json"
    cred: dict = {}
    if cred_path.is_file():
        try:
            cred = json.loads(cred_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cred = {}

    # 翻案需新证据:同一份卷面(xlsx_mtime 未变)已有 PASS 凭证,再判 CUT 必须在
    # caveats/report 里给出行级引用(rN / row N / 行N)——否则是意见随抽样漂移的翻案,
    # 不产生新信息只打破已收口状态(实证:34 卷收口期同卷 PASS↔CUT 反复 5 轮)。
    # 只对 grade 自己落的 PASS 生效:lint 凭证(source=lint,emit 过机械门自动落)是结构
    # 凭证不是审批意见,grade 对其首判 CUT 不是"翻案"、不受行级证据要求约束。
    if (v == "CUT" and cred.get("verdict") == "PASS"
            and str(cred.get("source") or "grade") == "grade"
            and abs(float(cred.get("xlsx_mtime", -1)) - xp.stat().st_mtime) < 1e-6):
        evidence_text = " ".join(caveats) + " " + (report_md or "")
        if not re.search(r"(?:r|row\s*|行\s*)\d+", evidence_text, re.IGNORECASE):
            return ("error: 该卷面(内容未变)已有 PASS 凭证,推翻它需要行级新证据——"
                    "在 caveats 或 report_md 里写明具体行号(如 r42/row 42/第42行)和该行"
                    "的缺陷;没有行级证据的重审翻案不被接受(意见漂移不是新信息)。")
    # CUT 连击计数(跨重编累计,PASS 清零):778041 实证三连 CUT 循环被人工才停;
    # 942 对时点配对实证 grade CUT 重做零增益——连击是"意见循环"信号,不是质量信号。
    cut_streak = int(cred.get("cut_streak") or 0) + 1 if v == "CUT" else 0
    cred.update({
        "autoid": autoid,
        "xlsx": str(xp),
        "xlsx_mtime": xp.stat().st_mtime,
        "verdict": v,
        "source": "grade",
        "root_cause": rc or None,
        "caveats": caveats,
        "cut_streak": cut_streak,
        "verdict_ts": _time.time(),
    })
    try:
        cred_path.write_text(json.dumps(cred, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"error: 凭证落盘失败: {e}"
    if (report_md or "").strip():
        try:
            (xp.parent / "grade_report.md").write_text(report_md, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    out = (f"已提交判定并落盘凭证: {cred_path}\n"
           f"autoid={autoid} verdict={v}"
           + (f" root_cause={rc}" if rc else "")
           + (f" caveats={len(caveats)}条" if caveats else ""))
    if cut_streak >= 2:
        out += (f"\n⚠ 该 autoid 已连续 {cut_streak} 次 CUT(跨重编累计)。942 对配对实证:"
                "grade 判 PASS→上机 56%、判 CUT→53%,CUT 重做零增益——继续 CUT-重编循环"
                "只烧 token 不产信息。上机才能回答的疑虑(回显格式/计数器行为/轮转起点)"
                "写 caveats 落 PASS 交上机 oracle 终判;只有带行级引用的结构/事实错误才值得再 CUT。")
    return out
