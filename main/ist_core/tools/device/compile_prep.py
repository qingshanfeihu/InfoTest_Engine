"""compile_prep: 脑图(mind-map JSON)→ 批量编译 manifest(JSON 中间表示)。

批量编译的第一步:把一个脑图文件解析成结构化 manifest,供 V6 编译引擎(compile_engine)prep 节点调用。

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


def _node_text(node: dict) -> str:
    return ((node.get("data") or {}).get("text") or "").strip()


def _node_children(node: dict) -> list:
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
            for step_node in _node_children(node):
                step_desc = _node_text(step_node)
                # 步骤的子节点 = 期望值(脑图原文,如 "命中第一个pool")
                expects = [_node_text(c) for c in _node_children(step_node) if _node_text(c)]
                step_intents.append({
                    "desc": step_desc,
                    "expected": "  ".join(expects) if expects else "",
                })
            cases.append({
                "autoid": autoid,
                "title": _node_text(node),          # 脑图原文标题,重名不去重
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
        title = _node_text(node)
        next_path = group_path + [title] if title else group_path
        for c in _node_children(node):
            walk(c, next_path)

    walk(root, [])
    return cases


@tool(parse_docstring=True)
def compile_prep(mindmap_path: str, out_name: str = "") -> str:
    """Parse one mindmap file into a batch-compile manifest (JSON intermediate representation) for stage-wise orchestration.

    Reads the whole mindmap and lists every case it contains (autoid as primary key) with
    title/grouping/step requirements/expectations (all verbatim mindmap requirements),
    grouped by parent chain.

    **This tool produces requirements only, never commands** (zero-hardcoding red line):
    each case's init_commands/steps/assertions_provenance in the manifest is null — those
    are filled in by the authoring sub-agent after consulting manuals/precedents, never
    written here. prep only answers "which cases does this mindmap compile, what is each
    case's raw requirement, how are they grouped".

    Key contracts:
    - autoid is the primary key; duplicate titles are **not deduplicated** (many same-named
      cases differ only in parameters).
    - group_path records the case's parent-node chain in the mindmap, letting the
      orchestrator recognize group-level shared baselines (some mindmaps hoist the baseline
      into a preceding out-of-group node that in-group cases do not restate).

    Args:
        mindmap_path: mindmap file path (workspace/inputs/automatic_case/*.txt, mind-map JSON).
        out_name: manifest output subdir (workspace/outputs/<out_name>/manifest.json);
            empty uses the mindmap filename (sans extension).

    Returns:
        Manifest path + case statistics (total/groups/duplicate titles). The orchestrator
        fans out by stage from it.
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
        return f"error: mindmap file does not exist: {mindmap_path}"
    p = Path(p)

    try:
        mm = _load_mindmap(p)
        if not isinstance(mm, list) or not mm:
            return "error: mindmap JSON top level should be a non-empty array [root]"
        cases = _extract_cases(mm[0])
    except Exception as exc:  # noqa: BLE001
        return f"error: mindmap parse failed: {exc}"

    if not cases:
        return ("error: no case node with an autoid found in the mindmap — confirm this is a "
                "test-case mindmap (case nodes should carry an autoid field in their data).")

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

    dup_note = f"\n⚠️ duplicate autoids: {dups}" if dups else ""
    return (f"=== compile_prep ===\n"
            f"manifest written: {out}\n"
            f"mindmap: {p.name}  total cases: {len(cases)}\n"
            f"groups ({len(groups)}): {dict(list(groups.items())[:12])}\n"
            f"intent families ({len(families)}): "
            + "; ".join(f"{f['family']}×{f['size']}" for f in families[:8])
            + f"\nduplicate titles: {len(dup_titles)} (autoid is the primary key; duplicate titles are not deduplicated, each compiles independently)\n"
            f"{dup_note}\n"
            f"--- the manifest holds requirements only (title/group/steps/expectations), no commands ---\n"
            f"every case's init_commands/steps/assertions_provenance is null,\n"
            f"filled in by the authoring sub-agent after consulting manuals/precedents. Next: the orchestrator dispatches briefs per case.")
