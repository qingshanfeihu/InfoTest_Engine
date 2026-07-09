"""Footprint 数据结构和 JSON 模板。

设计原则：LLM 直接输出对齐 schema 的字段，代码只做反序列化、路由、合并。
不再用关键词正则判断 slot / level。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FactKind = Literal["cli_command", "decision_rule", "behavior", "known_issue"]
Level = Literal["leaf", "trunk", "branch", "root"]


@dataclass
class RawFact:
    """LLM 提取的一条结构化事实。所有 slot 决策由 LLM 一次给齐。"""

    fact_kind: FactKind
    feature_path: list[str]
    fact_key: str

    
    cli_syntax: str = ""
    parameters: list[dict] = field(default_factory=list)
    condition: str = ""
    decision: str = ""
    content: str = ""
    issue_id: str = ""
    issue_title: str = ""
    affected_versions: list[str] = field(default_factory=list)

    
    evidence_file: str = ""
    evidence_quote: str = ""
    # 第二权威源(V6 支柱2a):设备实证——{autoid, run_ts} 指向 runtime/logs/
    # verified_runs.jsonl 的一条上机 PASS 台账;非空时 merge 的 evidence 门走
    # device_verified 分支(命令必须真实出现在该 PASS 卷面上),不再要求手册命中。
    device_evidence: dict = field(default_factory=dict)

    # 观察级字段(2026-07-08 判例化,自愈环):validity=verified(默认,PASS 实证)|
    # uncertain(fail/escalated 轮的设备观察——最有信息量的 episode 此前被"fail 候选
    # 永不入库"整体丢弃,pe1 570/608 实证正解卡在知识断层外);observed_under=观测语境
    # 短句(配置形态)。渲染层按语境并列同主题观察、自动组头提示,矛盾由读者 LLM 识别。
    validity: str = "verified"
    observed_under: str = ""

    
    source_thread: str = ""


@dataclass
class RoutedFact:
    """路由后的事实：已确定 level + target_file。"""

    fact: RawFact
    level: Level
    target_file: str


@dataclass
class MergeResult:
    action: str = "skip"
    target_file: str = ""
    detail: str = ""














def node_template(feature_id: str, level: str = "leaf") -> dict[str, Any]:
    return {
        "schema_version": 3,
        "feature_id": feature_id,
        "level": level,
        "cli": {"commands": []},
        "decision_rules": [],
        "behaviors": [],
        "known_issues": [],
        "children": [],
        "version_scope": {},
        "footprint_meta": _meta_template(),
    }



def leaf_template(feature_id: str) -> dict[str, Any]:
    return node_template(feature_id, "leaf")


def trunk_template(feature_id: str) -> dict[str, Any]:
    return node_template(feature_id, "trunk")


def branch_template(feature_id: str) -> dict[str, Any]:
    return node_template(feature_id, "branch")


def root_template(feature_id: str) -> dict[str, Any]:
    return node_template(feature_id, "root")


def _meta_template() -> dict[str, Any]:
    return {
        "created_at": None,
        "verified_count": 0,
        "source_threads": [],
    }


TEMPLATE_MAP: dict[str, Any] = {
    "leaf": leaf_template,
    "trunk": trunk_template,
    "branch": branch_template,
    "root": root_template,
}




LEVEL_KINDS: dict[str, set[str]] = {
    "leaf": {"cli_command", "decision_rule", "behavior", "known_issue"},
    "trunk": {"cli_command", "decision_rule", "behavior", "known_issue"},
    "branch": {"cli_command", "decision_rule", "behavior", "known_issue"},
    "root": {"cli_command", "decision_rule", "behavior", "known_issue"},
}
