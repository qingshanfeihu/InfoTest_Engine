r"""结构化测试报告 Agent 工具。

注册为 LangChain @tool，Agent 通过 ``invoke_skill("report-gen")`` 间接触发，
或直接调用 ``report_to_doc`` 生成报告并保存为企微云文档。

内部流程：Agent 传结构化字段 → 构造 ReportSchema → to_markdown() → DocToolKit → MCP。
Agent 不感知 doc_id / token / Markdown 格式 / MCP 细节。
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("wecom_bot_smart.report_tool")


def _compute_content_hash(markdown: str) -> str:
    """内容指纹（SHA-256 前 16 位），用于变更检测。"""
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:16]


@tool(parse_docstring=False)
def report_to_doc(
    title: str,
    summary: str,
    environment: dict[str, str],
    test_cases: list[dict[str, str]],
    defects: list[dict[str, str]],
    conclusions: list[str],
    recommendations: list[str],
    topic: str = "",
    task_id: str = "",
) -> str:
    r"""生成结构化测试报告并保存为企业微信云文档。

    一次性完成「数据结构化 → Markdown 生成 → 创建云文档 → 注册表记录」。
    相同 topic 不会重复创建，返回已有文档链接。
    指定 task_id 时，报告自动注册到 ArtifactRegistry 并关联任务，
    支持后续查询「某测试任务产生的所有结果」。

    使用场景：
    - 用户要求「生成测试报告」「把结果写成文档」「输出报告」
    - 测试执行完毕，需要将结果输出为结构化云文档
    - /report 命令触发的报告生成流程

    不使用场景：
    - 简单技术问答（直接回复）
    - 只需几句话回答的查询
    - 用户没有明确要求生成文档

    Args:
        title: 报告标题（如 "2026-07-13 IPv6 功能测试报告"）
        summary: 执行摘要（1-3 句话概括核心结果）
        environment: 测试环境信息 {"设备型号": "...", "软件版本": "..."}
        test_cases: 测试结果列表，每项含：
            - case_id: 用例编号
            - description: 描述
            - status: PASSED / FAILED / BLOCKED / SKIPPED / ERROR
            - evidence: 证据（日志摘录）
            - duration_s: 执行耗时（秒，可选）
            - device_info: 设备信息（可选）
            - notes: 备注（可选）
        defects: 缺陷列表，每项含：
            - defect_id: 缺陷编号
            - description: 描述
            - severity: critical / major / minor / info
            - case_id: 关联用例（可选）
            - root_cause: 根因分析（可选）
        conclusions: 结论列表
        recommendations: 建议列表
        topic: 文档主题标识（去重用）。相同 topic 返回已有文档链接。
               格式建议："test-report-{YYYY-MM-DD}-{批次名}"。为空则每次新建。
        task_id: 测试任务 ID（如 "TEST-20260713-001"）。
                 指定时自动注册到 ArtifactRegistry，支持按任务查询。
                 同一 task_id 多次生成报告自动递增版本号。

    Returns:
        文档链接或错误信息
    """
    from .report_schema import (
        ReportSchema,
        TestCaseResult,
        Defect,
        TestStatus,
        Severity,
    )
    from .registry import DocumentRegistry
    from .tools import DocToolKit, DocMcpClient
    from .config import server_config

    # --- 去重检查 ---
    registry = DocumentRegistry()
    if topic:
        existing = registry.lookup(topic)
        if existing and existing.get("url"):
            logger.info("topic=%s 已有文档，返回已有链接", topic)
            return (
                f"该主题的报告已存在：\n"
                f"标题：{existing.get('title', '-')}\n"
                f"链接：{existing.get('url', '-')}\n"
                f"创建时间：{existing.get('created_at', '-')}\n"
                f"如需覆盖更新，请修改 topic 后重新调用。"
            )

    # --- 构造 ReportSchema ---
    parsed_cases: list[TestCaseResult] = []
    for tc in test_cases:
        try:
            status = TestStatus(tc.get("status", "ERROR").upper())
        except ValueError:
            status = TestStatus.ERROR
        parsed_cases.append(TestCaseResult(
            case_id=tc.get("case_id", "-"),
            description=tc.get("description", ""),
            status=status,
            evidence=tc.get("evidence", ""),
            duration_s=float(tc.get("duration_s", 0)),
            device_info=tc.get("device_info", ""),
            notes=tc.get("notes", ""),
        ))

    parsed_defects: list[Defect] = []
    for d in defects:
        try:
            sev = Severity(d.get("severity", "info").lower())
        except ValueError:
            sev = Severity.INFO
        parsed_defects.append(Defect(
            defect_id=d.get("defect_id", "-"),
            description=d.get("description", ""),
            severity=sev,
            case_id=d.get("case_id", ""),
            root_cause=d.get("root_cause", ""),
        ))

    report = ReportSchema(
        title=title,
        summary=summary,
        environment=environment,
        test_cases=parsed_cases,
        defects=parsed_defects,
        conclusions=conclusions,
        recommendations=recommendations,
    )

    # --- 生成 Markdown ---
    markdown = report.to_markdown()
    content_hash = _compute_content_hash(markdown)

    # --- MCP 创建文档 ---
    mcp_url = server_config.mcp_doc_url
    if not mcp_url:
        return "文档功能未配置。请在 environment 文件中设置 WECOM_SMART_MCP_DOC_URL。"

    try:
        client = DocMcpClient(mcp_url)
        client.initialize()
        toolkit = DocToolKit(client)
        url = toolkit.create_doc_with_content(title, markdown)
    except Exception as e:
        logger.exception("文档创建失败: title=%s", title)
        return f"文档创建失败: {e}"

    if not url:
        return (
            "文档创建失败：MCP 服务未返回文档链接。"
            "请检查 WECOM_SMART_MCP_DOC_URL 配置是否过期（有效期 7 天）。"
        )

    # --- 提取 docid + 注册 ---
    docid = ""
    try:
        from urllib.parse import urlparse, parse_qs

        params = parse_qs(urlparse(url).query)
        docid = params.get("docid", [""])[0] or params.get("id", [""])[0]
    except Exception:
        pass

    if topic:
        registry.register(
            topic=topic,
            docid=docid,
            url=url,
            title=title,
            content_hash=content_hash,
            creator_type="agent",
            metadata={
                "total": report.total_count,
                "passed": report.passed_count,
                "failed": report.failed_count,
                "blocked": report.blocked_count,
                "pass_rate": f"{report.pass_rate:.1%}",
                "defect_count": len(parsed_defects),
            },
        )

    # --- ArtifactRegistry 注册（task_id 关联 + 版本追踪） ---
    version_info = ""
    if task_id:
        try:
            from .artifact_registry import ArtifactRegistry
            from .artifact_schema import ArtifactType

            ar = ArtifactRegistry()
            ar.create_task(task_id, name=title)
            artifact_id = ar.register_artifact(
                artifact_type=ArtifactType.REPORT,
                name=title,
                url=url,
                docid=docid,
                related_task_id=task_id,
                metadata={
                    "total": report.total_count,
                    "passed": report.passed_count,
                    "failed": report.failed_count,
                    "pass_rate": f"{report.pass_rate:.1%}",
                    "topic": topic,
                },
            )
            if topic:
                ar.register_document_version(
                    artifact_id=artifact_id,
                    topic=topic,
                    content_hash=content_hash,
                    version=ar.get_next_version(task_id, ArtifactType.REPORT) - 1,
                )
            artifact = ar.get_artifact(artifact_id)
            if artifact:
                version_info = f"版本：v{artifact.version} | 任务：{task_id}\n"
            logger.info(
                "Artifact 注册: task=%s artifact_id=%d type=report",
                task_id, artifact_id,
            )
        except Exception as e:
            logger.warning("ArtifactRegistry 注册失败（不影响文档创建）: %s", e)

    logger.info(
        "报告已生成: title=%s topic=%s total=%d passed=%d url=%s",
        title, topic, report.total_count, report.passed_count, url,
    )
    return (
        f"测试报告已生成！\n"
        f"标题：{title}\n"
        f"{version_info}"
        f"用例数：{report.total_count}"
        f"（通过 {report.passed_count}，失败 {report.failed_count}，"
        f"通过率 {report.pass_rate:.1%}）\n"
        f"缺陷数：{len(parsed_defects)}\n"
        f"链接：{url}"
    )
