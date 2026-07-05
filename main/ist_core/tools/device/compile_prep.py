"""compile_prep: 脑图(mind-map JSON)→ 批量编译 manifest(JSON 中间表示)。

批量编译的第一步:把一个脑图文件解析成结构化 manifest,供 ist-compile 编译链(compile_pipeline)按阶段调度。

**零硬编码红线(第一原则,见计划 linear-imagining-galaxy.md)**:
本工具**只产"需求 + 分组 + 先例引用"**,绝不产任何设备命令/参数/断言。manifest 里
case 的 init_commands/steps/assertions_provenance 全部留 null——它们由 draft 子 agent
现场查手册/先例后自己回填。prep 只做:
  1. 解析脑图树:autoid(主键)、标题、分组(父节点)、步骤描述、期望(更深叶子)——全是脑图原文需求
  2. 标题重名**不去重**(autoid 是主键)
  3. 不解析领域语义、不按关键字分支、不推断命令

脑图格式(实证 dongkl/yzg/zhaiyq):mind-map app 导出的 JSON,顶层 [root],每个节点
{data:{text,autoid?,auto?,priority?,resource?}, children:[...]}。case = 带 data.autoid
的节点;它的 text=标题,children 的 text=步骤描述,步骤的 children=期望值。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _load_mindmap(path: Path) -> list:
    """读脑图文件:跳过 BOM/噪声前缀到首个 '[',按 utf-8 解析 JSON。"""
    raw = path.read_bytes()
    i = raw.find(b"[")
    if i < 0:
        raise ValueError("非 mind-map JSON(找不到 '[')")
    return json.loads(raw[i:].decode("utf-8"))


def _text(node: dict) -> str:
    return ((node.get("data") or {}).get("text") or "").strip()


def _kids(node: dict) -> list:
    return node.get("children") or []


def _node_data(node: dict) -> dict:
    return node.get("data") or {}


def _extract_cases(root: dict) -> list[dict]:
    """深度遍历,带 data.autoid 的节点即一个 case。记录其分组(父节点链)、步骤、期望。

    返回每个 case 的**原始需求**(脑图原文),不含任何命令/答案。
    """
    cases: list[dict] = []

    def walk(node: dict, group_path: list[str]) -> None:
        d = _node_data(node)
        autoid = str(d.get("autoid") or "").strip()
        if autoid:
            # 这是一个 case:text=标题,children=步骤描述,步骤的 children=期望
            step_intents = []
            for step_node in _kids(node):
                step_desc = _text(step_node)
                # 步骤的子节点 = 期望值(脑图原文,如 "命中第一个pool")
                expects = [_text(c) for c in _kids(step_node) if _text(c)]
                step_intents.append({
                    "desc": step_desc,
                    "expected": "  ".join(expects) if expects else "",
                })
            cases.append({
                "autoid": autoid,
                "title": _text(node),          # 脑图原文标题,重名不去重
                "group_path": list(group_path),  # 分组链(父节点 text)
                "priority": d.get("priority"),
                "step_intents": step_intents,
                # —— 以下 _filled_by_draft:draft 子 agent 查证后回填,prep 阶段全 null ——
                "init_commands": None,
                "steps": None,
                "assertions_provenance": None,
                "compile_state": {"draft_xlsx": None, "verdict": None,
                                  "device_truth": None, "grade": None,
                                  "rounds": 0, "status": "pending"},
            })
            # case 节点下不再找嵌套 case(autoid 节点是叶层 case 单元)
            return
        # 非 case 节点:继续下钻,把自己的 text 加进分组链
        title = _text(node)
        next_path = group_path + [title] if title else group_path
        for c in _kids(node):
            walk(c, next_path)

    walk(root, [])
    return cases


@tool(parse_docstring=True)
def compile_prep(mindmap_path: str, out_name: str = "") -> str:
    """把一个脑图文件解析成批量编译 manifest(JSON 中间表示),供编排器按阶段调度。

    通读整个脑图,列出它包含的所有 case(autoid 主键)、各自的
    标题/分组/步骤需求/期望(全是脑图原文需求),分组归类。

    **本工具只产需求,不产命令**(零硬编码红线):manifest 里每个 case 的
    init_commands/steps/assertions_provenance 都是 null——这些是 draft 子 agent 现场查
    手册/先例后回填的,不是这里写死的。prep 只负责"这个脑图要编译哪些 case、每个 case
    的原始需求是什么、怎么分组"。

    关键契约:
    - autoid 是主键,标题重名**不去重**(yzg/zhaiyq 有大量同名 case,区别只在参数)。
    - 分组(group_path)记录 case 在脑图里的父节点链,供编排器识别"组级共享基线"
      (如 zhaiyq 把基线抽到组外前置节点,组内 case 都不重述)。

    Args:
        mindmap_path: 脑图文件路径(workspace/inputs/automatic_case/*.txt,mind-map JSON 格式)。
        out_name: manifest 落盘子目录名(workspace/outputs/<out_name>/manifest.json);
            空则用脑图文件名(去扩展名)。

    Returns:
        manifest 落盘路径 + case 统计(总数/分组/重名标题数)。编排器据此按阶段 fan-out。
    """
    # 解析路径(走 agent 沙箱多根)
    p = None
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        p = _resolve_inside_root(mindmap_path, must_exist=True)
    except Exception:
        p = None
    if p is None or not Path(p).is_file():
        cands = [Path(mindmap_path)]
        if not Path(mindmap_path).is_absolute():
            root = Path(__file__).resolve().parents[4]
            cands += [root / mindmap_path]
        p = next((c for c in cands if c.is_file()), None)
    if p is None or not Path(p).is_file():
        return f"error: 脑图文件不存在: {mindmap_path}"
    p = Path(p)

    try:
        mm = _load_mindmap(p)
        if not isinstance(mm, list) or not mm:
            return "error: 脑图 JSON 顶层应是非空数组 [root]"
        cases = _extract_cases(mm[0])
    except Exception as exc:  # noqa: BLE001
        return f"error: 解析脑图失败: {exc}"

    if not cases:
        return ("error: 脑图里没找到任何带 autoid 的 case 节点——确认这是用例脑图"
                "(case 节点 data 里应有 autoid 字段)。")

    # autoid 唯一性检查(主键)
    seen, dups = set(), []
    for c in cases:
        if c["autoid"] in seen:
            dups.append(c["autoid"])
        seen.add(c["autoid"])

    # 分组聚合(按 group_path 的末级,供编排器参考;不做语义判断)
    from collections import Counter
    groups = Counter(" / ".join(c["group_path"]) for c in cases)
    titles = Counter(c["title"] for c in cases)
    dup_titles = {t: n for t, n in titles.items() if n > 1}

    # 意图族聚类(V4 步骤3,H_G 摊销的路由依据;定理3.10)。族键=首步(配置意图)句式的
    # 参数化(数字→N、去空白)——2026-07-04 实证:该键在 dongkl 34 case 聚出 14 族、
    # 25/34 被多成员族覆盖、最大族 12(rr/wrr/ga 全系共享配置基线,族内骨架重合 45-51%);
    # 曾试 _intent_similarity(词重叠+bigram)在同数据上聚出 0 族,不可用。
    # 纯代码零语义判断:同族=配置前置的自然语言句式相同,骨架选择仍由族首 worker(LLM)做。
    import re as _re
    def _family_key(c: dict) -> str:
        si = c.get("step_intents") or []
        first = (si[0].get("desc") or "") if si else ""
        return _re.sub(r"\s+", "", _re.sub(r"\d+", "N", first))
    fam_map: dict[str, list[str]] = {}
    for c in cases:
        fam_map.setdefault(_family_key(c), []).append(c["autoid"])
    fam_id = 0
    families = []
    for key, aids in fam_map.items():
        fam_id += 1
        fid = f"F{fam_id:02d}"
        for c in cases:
            if c["autoid"] in aids:
                c["family"] = fid
        families.append({"family": fid, "size": len(aids), "head": aids[0],
                         "members": aids, "key_hint": key[:60]})
    families.sort(key=lambda f: -f["size"])

    sub = (out_name or p.stem).strip().replace("/", "_")
    manifest = {
        "batch_id": f"compile-{sub}",
        "source": str(p),
        "case_count": len(cases),
        "groups": dict(groups),
        "families": families,
        "cases": cases,
    }
    root = Path(__file__).resolve().parents[4]
    # 环境能力事实源注入(2026-07-05 坑3):双机可用性/已知缺陷/静默失败模式——
    # 编译前一次查询回答"用例前提在本环境是否成立",不满足的编译期就标注/上报,
    # 不再靠上机去撞(DC-1/2/3 三条缺陷全是烧了设备时间撞出来的)。缺文件不阻断。
    try:
        cap = json.loads((root / "knowledge" / "data" / "auto_env" / "env_capabilities.json")
                         .read_text(encoding="utf-8"))
        manifest["env_capabilities"] = cap
    except Exception:  # noqa: BLE001
        logger.debug("env_capabilities.json 不可用(manifest 不带该节)", exc_info=True)
    out = root / "workspace" / "outputs" / sub / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    dup_note = f"\n⚠️ autoid 重复: {dups}" if dups else ""
    return (f"=== compile_prep ===\n"
            f"manifest 已落盘: {out}\n"
            f"脑图: {p.name}  case 总数: {len(cases)}\n"
            f"分组({len(groups)}): {dict(list(groups.items())[:12])}\n"
            f"意图族({len(families)}): "
            + "; ".join(f"{f['family']}×{f['size']}" for f in families[:8])
            + f"\n≥4 成员的族先派族首(head)全力编写,族首过门后族内 brief 附其配置骨架"
            f"(compile_skeleton 取),族内只做差异绑定——同族配置基线实测重合 45-51%,"
            f"逐 case 重推导是重复支付。<4 成员的族按原流程逐个派。\n"
            f"重名标题数: {len(dup_titles)}(autoid 是主键,标题重名不去重,各自独立编译)\n"
            f"{dup_note}\n"
            f"--- manifest 只含需求(标题/分组/步骤/期望),不含任何命令 ---\n"
            f"每个 case 的 init_commands/steps/assertions_provenance 都是 null,\n"
            f"由 draft 子 agent 现场查手册/先例后回填。下一步:编排器按 case 组 brief 派发 draft。")


@tool(parse_docstring=True)
def compile_skeleton(autoid: str) -> str:
    """取一个已编译成品卷的配置骨架(init + 全部配置步命令原文),供同族 case 复用。

    族摊销(V4 步骤3,定理3.10 H_G 共享):族首 case 全力推导出的配置基线,族内 case
    直接引用后只做差异绑定——同族配置命令实测重合 45-51%,逐 case 重新查手册推导
    同一套基线是重复支付。纯反解零语义:命令原文逐行返回,取舍仍由族内 worker 判断。

    Args:
        autoid: 族首 case 的完整 autoid(其 case.xlsx 已在 workspace/outputs/<autoid>/)。

    Returns:
        配置骨架文本(init 与配置步的命令逐行)+ 断言形态摘要;卷不存在则 error。
    """
    import re as _re
    aid = (autoid or "").strip()
    # 安全:autoid 白名单(路径分量净化)——aid="../.." 可读 outputs 外任意 case.xlsx
    # 并把 G 列命令原文回显给 agent(安全评审中危读穿越项)。
    if not _re.fullmatch(r"[A-Za-z0-9_.\-]+", aid) or ".." in aid:
        return f"error: autoid 非法(只允许字母数字._-,禁 ..): {aid!r}"
    root = Path(__file__).resolve().parents[4]
    xp = root / "workspace" / "outputs" / aid / "case.xlsx"
    if not xp.is_file():
        return f"error: {aid} 的 case.xlsx 不存在——族首要先编完过门,才能给族内供骨架。"
    # 过门检查:族首必须持有对应当前卷面的新鲜凭证——否则 emit 半途的残卷会把坏骨架
    # 扩散到全族(红线评审弱门:文案说"编完过门"但只验了 xlsx 存在)。
    credf = xp.parent / ".grade_credential.json"
    if credf.is_file():
        try:
            import json as _j
            cred = _j.loads(credf.read_text(encoding="utf-8"))
            if abs(float(cred.get("xlsx_mtime", -1)) - xp.stat().st_mtime) >= 1e-6:
                return (f"error: {aid} 凭证与当前卷面不匹配(族首编到一半或改过)——"
                        "等族首过门拿到新鲜凭证再取骨架,别用残卷供全族。")
        except Exception:  # noqa: BLE001
            pass
    else:
        return (f"error: {aid} 无凭证(族首还没过 emit 门)——族首过门后才能给族内供骨架。")
    try:
        import openpyxl
        ws = openpyxl.load_workbook(xp).active
        cfg_lines: list[str] = []
        shapes: list[str] = []
        for r in ws.iter_rows(min_row=2):
            E = str(r[4].value or "")
            F = str(r[5].value or "")
            G = str(r[6].value or "")
            H = str(r[7].value or "")
            if E == "APV_0" and F in ("cmds_config", "cmd_config"):
                cfg_lines.extend(ln for ln in G.split("\n") if ln.strip())
            elif E == "check_point":
                shapes.append(f"{F}" + ("(H引用)" if H.strip() else ""))
        if not cfg_lines:
            return f"error: {aid} 卷面没有配置步(不是常规成品卷?)"
        # 去重保序
        seen: set[str] = set()
        uniq = [c for c in cfg_lines if not (c in seen or seen.add(c))]
        from collections import Counter
        shape_summary = dict(Counter(shapes))
        return (f"=== 族骨架(来自 {aid}) ===\n"
                f"配置命令({len(uniq)} 条,已按卷面顺序去重):\n"
                + "\n".join(uniq)
                + f"\n断言形态摘要: {shape_summary}\n"
                "用法:族内 case 的 CONFIG 组合子以此为基线,按本 case 的脑图差异增删"
                "(权重/成员/池数等参数不同处必须改);差异之外不重新推导。")
    except Exception as exc:  # noqa: BLE001
        return f"error: 骨架反解失败: {exc}"
