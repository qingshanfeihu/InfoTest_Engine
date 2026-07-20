"""企业微信云文档 Agent 工具。

注册为 LangChain @tool，Agent 可自主决定何时创建文档。
内部调用 DocToolKit + DocRegistry 去重。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("wecom_bot_smart.doc_tool")

# 延迟导入（避免循环依赖，gateway 初始化后再用）
_tk: Any = None  # DocToolKit
_registry: Any = None  # DocumentRegistry (SQLite)


def _ensure_initialized() -> tuple[Any, Any]:
    """懒初始化 DocToolKit + DocumentRegistry。"""
    global _tk, _registry
    if _registry is None:
        from .registry import DocumentRegistry
        _registry = DocumentRegistry()

    if _tk is None:
        from .tools import DocToolKit, DocMcpClient
        from .config import server_config

        mcp_url = server_config.mcp_doc_url
        if not mcp_url:
            raise RuntimeError(
                "文档工具未配置。请在 environment 文件中设置 WECOM_SMART_MCP_DOC_URL。\n"
                "获取方式：企微后台 → 智能机器人 → 编辑 → 可使用权限 → 授权 → 复制 streamableHTTP URL"
            )
        client = DocMcpClient(mcp_url)
        client.initialize()
        _tk = DocToolKit(client)
        logger.info("DocToolKit 初始化完成")

    return _tk, _registry


@tool(parse_docstring=False)
def wx_create_doc(title: str, content: str, topic: str = "", owner_userid: str = "") -> str:
    """创建企业微信云文档并写入 Markdown 内容。

    使用场景：
    - 用户明确要求「生成报告」「创建文档」「输出方案」「保存分析结果」
    - 测试执行完毕，需要将结果输出为结构化文档
    - 用户说「保存到文档」「发个文档」「生成个链接」

    不使用场景：
    - 普通技术问答（直接回复即可，不需要文档化）
    - 简单查询结果（几句话能说清的）
    - 用户只是聊天，没有要求创建文档

    Args:
        title: 文档标题，简洁明了（如 "2026-07-13 IPv6 测试报告"）
        content: 完整的 Markdown 内容。建议包含标题、章节、表格。
        topic: 文档主题标识，用于去重。相同 owner_userid + topic 不会重复创建。
               格式建议："{类别}-{日期}" 如 "daily-test-2026-07-13"。
        owner_userid: 创建者企微用户 ID（可选，用于文档隔离。不传则不隔离）
    """
    try:
        tk, registry = _ensure_initialized()
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.exception("文档工具初始化失败")
        return f"文档工具初始化失败: {e}"

    # 去重检查
    if topic:
        existing = registry.lookup(topic)
        if existing:
            logger.info("topic=%s 已有文档，返回已有链接: %s", topic, existing.get("url", ""))
            return (
                f"该主题的文档已存在：\n"
                f"标题：{existing.get('title', '-')}\n"
                f"链接：{existing.get('url', '-')}\n"
                f"创建时间：{existing.get('created_at', '-')}\n"
                f"如需更新内容，请使用 wx_update_doc 工具。"
            )

    # 创建文档
    try:
        url = tk.create_doc_with_content(title, content)
    except Exception as e:
        logger.exception("文档创建失败: title=%s", title)
        return f"文档创建失败: {e}"

    if not url:
        return "文档创建失败：MCP 服务未返回文档链接。请检查 WECOM_SMART_MCP_DOC_URL 配置是否过期（有效期 7 天）。"

    # 注册到 DocumentRegistry（SQLite）
    # 从 URL 中提取 docid（URL 格式通常含 docid 参数）
    docid = ""
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        docid = params.get("docid", [""])[0] or params.get("id", [""])[0]
    except Exception:
        pass

    if topic:
        registry.register(
            topic=topic, docid=docid, url=url, title=title,
            owner_userid=owner_userid, creator_type="user",
        )

    logger.info("文档已创建: title=%s topic=%s url=%s", title, topic, url)
    return (
        f"文档已创建成功！\n"
        f"标题：{title}\n"
        f"链接：{url}\n"
        f"请将链接发送给用户。"
    )


@tool(parse_docstring=False)
def wx_update_doc(topic: str, content: str, owner_userid: str = "") -> str:
    """更新已有的企业微信云文档内容。

    通过 topic 查找之前创建的文档，用新内容覆盖更新。
    传入 owner_userid 时只查找该用户的文档。

    Args:
        topic: 文档主题标识（与 wx_create_doc 时使用的 topic 一致）
        content: 新的 Markdown 内容（全量覆盖）
        owner_userid: 企微用户 ID（可选，用于文档隔离）
    """
    try:
        tk, registry = _ensure_initialized()
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.exception("文档工具初始化失败")
        return f"文档工具初始化失败: {e}"

    existing = registry.lookup(topic, owner_userid=owner_userid)
    if not existing:
        return (
            f"未找到 topic='{topic}' 对应的文档。"
            f"请先使用 wx_create_doc 创建文档，或检查 topic 是否正确。"
        )

    docid = existing.get("docid", "")
    if not docid:
        return f"文档记录存在但缺少 docid，无法更新。文档链接：{existing.get('url', '-')}"

    try:
        tk.edit_doc_content(docid, content, content_type=1)
        logger.info("文档已更新: topic=%s docid=%s", topic, docid)
        return (
            f"文档已更新！\n"
            f"标题：{existing.get('title', '-')}\n"
            f"链接：{existing.get('url', '-')}"
        )
    except Exception as e:
        logger.exception("文档更新失败: topic=%s docid=%s", topic, docid)
        return f"文档更新失败: {e}"


@tool(parse_docstring=False)
def wx_list_docs(owner_userid: str = "") -> str:
    """列出最近创建的企业微信云文档。

    用于用户问「我之前创建的文档有哪些」「查看文档列表」时。
    返回最近 10 个文档的标题、链接、创建时间。
    传入 owner_userid 时只返回该用户的文档；不传则返回全部。

    Args:
        owner_userid: 企微用户 ID（可选，用于用户级文档隔离）
    """
    try:
        _, registry = _ensure_initialized()
    except Exception:
        return "文档注册表不可用。"

    docs = registry.list_recent(limit=10, owner_userid=owner_userid)
    if not docs:
        return "暂无已创建的文档记录。"

    lines = ["最近创建的文档：\n"]
    for i, d in enumerate(docs, 1):
        lines.append(
            f"{i}. **{d.get('title', '无标题')}**\n"
            f"   链接：{d.get('url', '-')}\n"
            f"   创建时间：{d.get('created_at', '-')}"
        )
    return "\n".join(lines)


@tool(parse_docstring=True)
def wx_search_doc(query: str, limit: int = 5, owner_userid: str = "") -> str:
    """搜索已创建的企业微信云文档。

    当用户问「之前生成的报告有哪些」「搜索 IPv6 相关的文档」时使用。
    支持按标题、topic、元数据全文搜索。无匹配结果时降级显示最近文档。
    传入 owner_userid 时只搜索该用户的文档。

    Args:
        query: 搜索关键词（如 "IPv6"、"测试报告"、"2026-07"）
        limit: 返回结果数量上限（默认 5）
        owner_userid: 企微用户 ID（可选，用于用户级文档隔离）
    """
    try:
        _, registry = _ensure_initialized()
    except Exception:
        return "文档注册表不可用。"

    results = registry.search(query, limit=limit, owner_userid=owner_userid)

    if not results:
        recent = registry.list_recent(limit=limit, owner_userid=owner_userid)
        if not recent:
            return "暂无已创建的文档记录。"
        lines = [f"未找到与「{query}」匹配的文档，显示最近创建的：\n"]
        for i, d in enumerate(recent, 1):
            lines.append(
                f"{i}. **{d.get('title', '无标题')}** — {d.get('created_at', '-')}\n"
                f"   {d.get('url', '-')}"
            )
        return "\n".join(lines)

    lines = [f"找到 {len(results)} 个相关文档：\n"]
    for i, r in enumerate(results, 1):
        meta = r.metadata
        stats = ""
        if meta.get("total"):
            stats = f"（{meta['total']} 用例，通过率 {meta.get('pass_rate', '-')}）"
        lines.append(
            f"{i}. **{r.title}**{stats}\n"
            f"   topic: {r.topic} | 创建: {r.created_at}\n"
            f"   {r.url}"
        )
    return "\n".join(lines)


@tool(parse_docstring=True)
def wx_read_doc(docid: str = "", url: str = "") -> str:
    """读取企业微信云文档的完整内容（Markdown 格式）。

    当用户要求"读取文档"、"看一下那个文档"、"文档内容是什么"时使用。
    也可用于 AI 自主分析已有文档内容。

    Args:
        docid: 文档 ID（与 url 二选一）
        url: 文档链接（与 docid 二选一）

    Returns:
        文档的 Markdown 内容，或错误信息
    """
    try:
        tk, _ = _ensure_initialized()
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.exception("文档工具初始化失败")
        return f"文档工具初始化失败: {e}"

    if not docid and not url:
        return "错误：必须提供 docid 或 url 参数"

    try:
        content = tk.get_doc_content(docid=docid, url=url)
        return content
    except Exception as e:
        logger.exception("读取文档失败: docid=%s url=%s", docid, url)
        return f"读取文档失败: {e}"


def get_doc_tools() -> list:
    """获取所有文档工具（用于注册到 Agent）。

    基础能力层：wx_create_doc / wx_update_doc / wx_read_doc / wx_list_docs / wx_search_doc。
    """
    return [wx_create_doc, wx_update_doc, wx_read_doc, wx_list_docs, wx_search_doc]
