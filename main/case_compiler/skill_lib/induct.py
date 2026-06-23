"""技能诱导:把 agent 上机 pass 的成功 case 蒸馏成可复用技能(Voyager add_new_skill 的精神)。

抄 Voyager voyager.py:357 `if info["success"]: add_new_skill` + AWM 诱导原则:
- 只有**上机 pass** 才入库(success gate = dev_run_case verdict)。
- 蒸馏成**可复用范式**(描述 + 断言做法),可变部分参数化、不写死具体 IP/域名。
- 落成 SKILL.md 进 knowledge/induced_skills/<name>/(source=induced,与人写 skill 分离)。
- 检索时只看描述(retrieve),命中当参考,agent 仍自走验证不冻结。

红线:不入库未 pass 的;不把单 case 具体值写进技能(防过拟合,AWM 参数化原则)。
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]   # skill_lib→case_compiler→main→<repo root>
_INDUCED = _ROOT / "knowledge" / "induced_skills"

_DISTILL_SYS = """你把一个**已上机验证通过**的测试用例,蒸馏成一条**可复用的断言方法论技能**。

要求(AWM 参数化原则):
- 抽出"这类用例该怎么测、断言该怎么写"的**通用范式**,不是这一个 case 的复制。
- 可变部分(域名/IP/pool名/次数)用占位描述,不写死具体值。
- 重点写清:① 这类用例的识别特征 ② 断言的正确形态(及为什么,踩过的坑)③ 期望值从哪来。
- 输出纯 markdown body,不要 frontmatter(调用方会加)。150-400 字。"""


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "induced-skill")[:48]


def induce_skill(model, *, name_hint: str, description: str, when_to_use: str,
                 source_autoid: str, success_summary: str) -> Path | None:
    """把一次成功调查蒸馏成 induced 技能 SKILL.md。返回写入路径(失败 None)。

    name_hint/description/when_to_use 给检索用;success_summary 是 agent 跑通后的
    根因+做法陈述(蒸馏输入)。**调用方须确保已 verdict=pass 才调本函数。**
    """
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        resp = model.invoke([SystemMessage(content=_DISTILL_SYS),
                             HumanMessage(content=success_summary[:4000])])
        body = str(resp.content).strip()
    except Exception:
        body = success_summary[:1500]
    if not body:
        return None

    name = _slug(name_hint)
    # frontmatter:source=induced,evidence.induced_from 记来源轨迹(schema 已设计此字段)
    desc = description.replace('"', "'")[:200]
    wtu = when_to_use.replace('"', "'")[:300]
    md = (
        "---\n"
        f"name: {name}\n"
        f'description: "{desc}"\n'
        "context: inline\n"
        "source: induced\n"
        "effort: medium\n"
        f'when_to_use: "{wtu}"\n'
        "evidence:\n"
        f"  induced_from: [\"{source_autoid}\"]\n"
        "---\n\n"
        f"{body}\n"
    )
    try:
        from main.case_compiler.skill_lib.schema import SkillSpec
        # 结构合法性自检(basic_errors)——不合法不落盘,防污染库
        spec = SkillSpec(name=name, description=desc, when_to_use=wtu,
                         context="inline", source="induced", effort="medium", body=body)
        errs = spec.basic_errors()
        if errs:
            print(f"[induce] 技能结构非法,不入库: {errs}")
            return None
    except Exception as e:  # noqa: BLE001
        print(f"[induce] schema 校验跳过: {e}")

    out_dir = _INDUCED / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "SKILL.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"[induce] 入库成功: {out_path}")
    return out_path
