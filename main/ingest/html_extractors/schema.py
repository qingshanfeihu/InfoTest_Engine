"""``DefectTicket`` Pydantic 模型 —— extractor 的统一输出契约。

v1.5.1 字段扩展：新增 resolution / priority / product / reported_* / resolved_* /
related_case_ids / related_story_ids / related_task_ids / activated_count
对齐真实 Bugzilla + 禅道页面。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str
    filename: str = ""


class DefectTicket(BaseModel):
    """HTML 解析后的统一缺陷/需求模型。

    ``to_index_dict`` 返回的结构可以直接交给 ``main.indexing.defect_index`` 索引。
    """

    model_config = ConfigDict(extra="allow")

    # 失败页面识别：抓回的 HTML 是 "Bug not found" / "无权访问" / 搜索无结果时
    #   extractor 会把 ticket_id 设为 ``UNKNOWN`` 并/或 title 为空 → ``is_valid_detail`` 返回 False
    invalid_reason: str = ""

    # --- 基础 ---
    ticket_id: str
    title: str = ""
    module: str = ""
    product: str = ""                      # 所属产品（禅道），比 module 粒度大
    severity: str = "low"                  # low|mid|high|critical
    priority: str = ""                     # P1-P5 / 1-4 / 原文
    status: str = "open"                   # open|fixed|triage
    resolution: str = ""                   # 解决方案类型：fixed|duplicate|not_repro|by_design|wont_fix|external|postponed
    description: str = ""
    steps_to_reproduce: str = ""
    fix_summary: str = ""

    # --- 时间与人员 ---
    reported_by: str = ""
    reported_at: str = ""                  # ISO8601 或原始字符串
    resolved_by: str = ""
    resolved_at: str = ""

    # --- 版本与代码 ---
    affected_versions: list[str] = Field(default_factory=list)
    fixed_versions: list[str] = Field(default_factory=list)   # 禅道"修复版本"
    fixed_commit: str = ""

    # --- 关联 ---
    related_feature_ids: list[str] = Field(default_factory=list)
    related_case_ids: list[str] = Field(default_factory=list)   # 禅道"相关用例"
    related_story_ids: list[str] = Field(default_factory=list)  # 禅道"相关需求"
    related_task_ids: list[str] = Field(default_factory=list)   # 禅道"相关任务"
    related_bug_ids: list[str] = Field(default_factory=list)    # Depends on / Blocks / 相关 bug

    # --- 其它指标 ---
    activated_count: int = 0               # 禅道"激活次数"；Bugzilla 无，默认 0
    comments_count: int = 0

    attachments: list[Attachment] = Field(default_factory=list)

    # --- 元数据 ---
    backend: str = ""
    doc_type: str = "bug"                  # bug | plm_ticket
    source_html_path: str = ""
    html_sha256: str = ""
    captured_at: str = ""

    def is_valid_detail(self) -> bool:
        """页面是否是一条有效的 bug / story 详情。

        判定（任一为 False 即视为无效）：
        - ``invalid_reason`` 已被 extractor 显式标记
        - ``ticket_id`` 为 ``UNKNOWN`` / 空
        - ``title`` 与 ``description`` 同时为空（典型 404 / 无权页面）
        """
        if self.invalid_reason:
            return False
        tid = (self.ticket_id or "").strip().upper()
        if not tid or tid == "UNKNOWN":
            return False
        if not (self.title or "").strip() and not (self.description or "").strip():
            return False
        return True

    def to_index_dict(self) -> dict:
        """输出与 ``knowledge/defect_cleaned/{backend}/*.json`` 一致的结构。

        page_content 包含所有语义上"可检索"的字段，让 embedding 能命中中文关键字。
        metadata 保留所有可过滤 / 显示的结构化字段（payload 索引在 defect_index.PAYLOAD_FIELDS）。
        """
        pc_parts = [
            f"[{self.ticket_id}][{self.module}][Sev={self.severity}]"
            f"{('[Pri=' + self.priority + ']') if self.priority else ''}"
            f" {self.title}",
        ]
        if self.product and self.product != self.module:
            pc_parts.append(f"产品: {self.product}")
        if self.description:
            pc_parts.append(self.description)
        if self.steps_to_reproduce:
            pc_parts.append("复现:\n" + self.steps_to_reproduce)
        if self.fix_summary:
            pc_parts.append("修复: " + self.fix_summary)
        if self.resolution:
            pc_parts.append(f"解决方案类型: {self.resolution}")
        timeline_parts: list[str] = []
        if self.reported_by or self.reported_at:
            timeline_parts.append(f"由 {self.reported_by} 提交于 {self.reported_at}".strip())
        if self.resolved_by or self.resolved_at:
            timeline_parts.append(f"由 {self.resolved_by} 解决于 {self.resolved_at}".strip())
        if timeline_parts:
            pc_parts.append(" / ".join(p for p in timeline_parts if p))
        relation_parts: list[str] = []
        if self.related_case_ids:
            relation_parts.append(f"相关用例: {', '.join(self.related_case_ids)}")
        if self.related_story_ids:
            relation_parts.append(f"相关需求: {', '.join(self.related_story_ids)}")
        if self.related_task_ids:
            relation_parts.append(f"相关任务: {', '.join(self.related_task_ids)}")
        if self.related_bug_ids:
            relation_parts.append(f"相关 Bug: {', '.join(self.related_bug_ids)}")
        if relation_parts:
            pc_parts.append("\n".join(relation_parts))
        page_content = "\n\n".join(p for p in pc_parts if p)

        return {
            "ticket_id": self.ticket_id,
            "page_content": page_content,
            "title": self.title,
            "description": self.description,
            "steps_to_reproduce": self.steps_to_reproduce,
            "fix_summary": self.fix_summary,
            "metadata": {
                "doc_type": self.doc_type,
                "module": self.module,
                "product": self.product,
                "severity": self.severity,
                "priority": self.priority,
                "status": self.status,
                "resolution": self.resolution,
                "reported_by": self.reported_by,
                "reported_at": self.reported_at,
                "resolved_by": self.resolved_by,
                "resolved_at": self.resolved_at,
                "affected_versions": self.affected_versions,
                "fixed_versions": self.fixed_versions,
                "fixed_commit": self.fixed_commit,
                "related_feature_ids": self.related_feature_ids,
                "related_case_ids": self.related_case_ids,
                "related_story_ids": self.related_story_ids,
                "related_task_ids": self.related_task_ids,
                "related_bug_ids": self.related_bug_ids,
                "activated_count": self.activated_count,
                "comments_count": self.comments_count,
                "backend": self.backend,
                "source_html_path": self.source_html_path,
                "html_sha256": self.html_sha256,
                "captured_at": self.captured_at,
            },
        }
