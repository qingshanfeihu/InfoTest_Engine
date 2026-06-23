"""compile_prep: 脑图(mind-map JSON)→ 批量编译 manifest(JSON 中间表示)。

批量编译的第一步:把一个脑图文件解析成结构化 manifest,供 ist_compile 编译链(compile_pipeline)按阶段调度。

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

    sub = (out_name or p.stem).strip().replace("/", "_")
    manifest = {
        "batch_id": f"compile-{sub}",
        "source": str(p),
        "case_count": len(cases),
        "groups": dict(groups),
        "cases": cases,
    }
    root = Path(__file__).resolve().parents[4]
    out = root / "workspace" / "outputs" / sub / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    dup_note = f"\n⚠️ autoid 重复: {dups}" if dups else ""
    return (f"=== compile_prep ===\n"
            f"manifest 已落盘: {out}\n"
            f"脑图: {p.name}  case 总数: {len(cases)}\n"
            f"分组({len(groups)}): {dict(list(groups.items())[:12])}\n"
            f"重名标题数: {len(dup_titles)}(autoid 是主键,标题重名不去重,各自独立编译)\n"
            f"{dup_note}\n"
            f"--- manifest 只含需求(标题/分组/步骤/期望),不含任何命令 ---\n"
            f"每个 case 的 init_commands/steps/assertions_provenance 都是 null,\n"
            f"由 draft 子 agent 现场查手册/先例后回填。下一步:编排器按 case 组 brief 派发 draft。")
