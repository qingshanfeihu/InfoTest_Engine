r"""文档/智能表格 MCP 工具客户端。

协议基于官方文档 https://developer.work.weixin.qq.com/document/path/101468

授权流程:
    1. 工作台 → 智能机器人 → 编辑 →「可使用权限」→ 授权（有效期 7 天）
    2. 点击「streamableHTTP URL」复制 MCP 端点地址
    3. 配置 WECOM_SMART_MCP_DOC_URL 到 environment 文件
    4. 机器人通过 MCP 协议调用 list_tools / invoke_tool

工具列表:
    - create_doc           新建文档（doc_type=3）或智能表格（doc_type=10）
    - edit_doc_content     编辑文档 Markdown 内容（content_type=1）
    - smartsheet_add_sheet 添加子表
    - smartsheet_get_sheet 查询子表
    - smartsheet_get_fields查询字段
    - smartsheet_update_fields 更新字段标题
    - smartsheet_add_fields添加字段
    - smartsheet_add_records 追加记录行
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("wecom_bot_smart.tools")

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])


# ============================================================================
# MCP 协议常量
# ============================================================================

MCP_JSONRPC = "2.0"
MCP_LIST_TOOLS = "tools/list"
MCP_CALL_TOOL = "tools/call"

# ============================================================================
# 智能表格字段类型（企微文档 §3.4.1 FieldType）
# ============================================================================

FIELD_TEXT = "FIELD_TYPE_TEXT"                  # 文本
FIELD_NUMBER = "FIELD_TYPE_NUMBER"              # 数字
FIELD_SINGLE_SELECT = "FIELD_TYPE_SINGLE_SELECT" # 单选
FIELD_DATE_TIME = "FIELD_TYPE_DATE_TIME"        # 日期时间


# ============================================================================
# MCP JSON-RPC 客户端
# ============================================================================

class DocMcpClient:
    """企业微信文档 MCP 客户端。

    通过 streamableHTTP URL 与 MCP server 通信，
    执行 list_tools / invoke_tool 等标准 MCP 方法。

    用法::

        client = DocMcpClient(mcp_url)
        client.initialize()
        # 创建文档
        result = client.invoke_tool("create_doc", {"doc_type": 3, "doc_name": "报告"})
        docid = result["docid"]
        # 写入内容
        client.invoke_tool("edit_doc_content", {"docid": docid, "content": "...", "content_type": 1})
    """

    def __init__(self, mcp_url: str) -> None:
        if not mcp_url:
            raise ValueError("MCP URL 未配置 (WECOM_SMART_MCP_DOC_URL)")
        self._url = mcp_url.rstrip("/")
        self._session_id: str | None = None
        self._protocol_version: str = "2024-11-05"

    # ------------------------------------------------------------------
    # MCP 协议方法
    # ------------------------------------------------------------------

    def _rpc(self, method: str, params: dict | None = None) -> dict[str, Any]:
        """发送 JSON-RPC 请求，返回 result。"""
        rid = uuid.uuid4().hex[:8]
        body: dict[str, Any] = {
            "jsonrpc": MCP_JSONRPC,
            "id": rid,
            "method": method,
        }
        if params is not None:
            body["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = requests.post(self._url, json=body, headers=headers, timeout=120)
        if resp.status_code == 204:
            return {}

        data = resp.json()

        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"MCP error: {err.get('message', str(err))}")

        # 提取 session_id
        sid = resp.headers.get("Mcp-Session-Id", "")
        if sid:
            self._session_id = sid

        return data.get("result", {})

    def initialize(self) -> dict[str, Any]:
        """MCP initialize 握手。

        某些 MCP 服务端（如企微）不要求 initialize，直接调工具也能工作。
        握手失败时记录 warning 但不阻断。
        """
        try:
            result = self._rpc("initialize", {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "ist-core-bot", "version": "1.0.0"},
            })
            # 发送 initialized 通知
            self._rpc("notifications/initialized")
            logger.info("MCP 初始化完成: url=%.60s…", self._url)
            return result
        except Exception as e:
            logger.warning("MCP initialize 失败（非阻断）: %s", e)
            return {}

    def list_tools(self) -> list[dict[str, Any]]:
        """获取可用工具列表。"""
        result = self._rpc(MCP_LIST_TOOLS)
        tools = result.get("tools", [])
        logger.info("MCP 工具列表: %s", [t.get("name") for t in tools])
        return tools

    def invoke_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具。

        MCP 标准返回格式：
        {"content": [{"type": "text", "text": "{...json...}"}], "isError": false}

        本方法自动解包 content 包装，返回内层 JSON。
        """
        logger.info("MCP 调用工具: name=%s args=%s", name, arguments)
        result = self._rpc(MCP_CALL_TOOL, {"name": name, "arguments": arguments})

        # 解包 MCP content 包装
        if "content" in result and isinstance(result["content"], list):
            if result.get("isError"):
                text = result["content"][0].get("text", "") if result["content"] else ""
                raise RuntimeError(f"MCP tool error: {text}")
            for item in result["content"]:
                if item.get("type") == "text":
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, KeyError):
                        return {"text": item.get("text", "")}

        return result


# ============================================================================
# 文档操作封装
# ============================================================================

class DocToolKit:
    """基于 MCP 的文档/智能表格操作工具集。

    封装了完整的报告生成流程：
    1. 创建文档 → 2. 写入内容 → 返回访问链接
    """

    def __init__(self, client: DocMcpClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # 创建文档
    # ------------------------------------------------------------------

    def create_doc(self, doc_name: str, doc_type: int = 3) -> dict[str, Any]:
        """新建文档。

        Args:
            doc_name: 文档名（≤255 字符）
            doc_type: 3=文档, 10=智能表格

        Returns:
            ``{"docid": ..., "url": ...}``
        """
        result = self._client.invoke_tool("create_doc", {
            "doc_type": doc_type,
            "doc_name": doc_name[:255],
        })
        logger.info("文档已创建: docid=%s url=%s",
                     result.get("docid", ""), result.get("url", ""))
        return result

    def edit_doc_content(self, docid: str, content: str,
                         content_type: int = 1) -> dict[str, Any]:
        """编辑文档内容（Markdown）。

        Args:
            docid: 文档 ID
            content: Markdown 原文（直接传，不要额外 JSON 转义或用引号包裹）
            content_type: 固定 1（markdown）
        """
        result = self._client.invoke_tool("edit_doc_content", {
            "docid": docid,
            "content": content,
            "content_type": content_type,
        })
        logger.info("文档内容已写入: docid=%s", docid)
        return result

    def create_doc_with_content(self, title: str, markdown: str) -> str:
        """一步创建文档并写入内容，返回文档链接。"""
        r = self.create_doc(title, doc_type=3)
        docid = r.get("docid", "")
        url = r.get("url", "")
        if docid and markdown:
            self.edit_doc_content(docid, markdown, content_type=1)
        return url

    # ------------------------------------------------------------------
    # 智能表格操作
    # ------------------------------------------------------------------

    def create_smartsheet(self, title: str) -> dict[str, Any]:
        """创建智能表格（含默认子表）。"""
        r = self._client.invoke_tool("create_doc", {
            "doc_type": 10,
            "doc_name": title[:255],
        })
        logger.info("智能表格已创建: docid=%s", r.get("docid", ""))
        return r

    def get_sheet(self, docid: str) -> str:
        """获取第一个子表的 sheet_id。"""
        result = self._client.invoke_tool("smartsheet_get_sheet", {"docid": docid})
        sheets = result.get("sheet_list", [])
        if not sheets:
            raise RuntimeError("智能表格无子表")
        return sheets[0].get("sheet_id", "")

    def setup_sheet_headers(self, docid: str, sheet_id: str,
                            columns: list[tuple[str, str]]) -> None:
        """设置智能表格列标题。

        流程（按官方文档 WARNING）:
          1. get_fields 获取默认字段
          2. update_fields 将默认字段重命名为第一列
          3. add_fields 添加剩余列

        Args:
            columns: [(标题, 字段类型), ...]，如 [("用例", FIELD_TEXT), ("状态", FIELD_TEXT)]
        """
        if not columns:
            return

        # 1. 获取默认字段
        fields_result = self._client.invoke_tool("smartsheet_get_fields", {
            "docid": docid, "sheet_id": sheet_id,
        })
        default_fields = fields_result.get("fields", [])
        if not default_fields:
            raise RuntimeError("表格无默认字段")

        default_id = default_fields[0].get("field_id", "")

        # 2. 重命名默认字段为第一列
        self._client.invoke_tool("smartsheet_update_fields", {
            "docid": docid,
            "sheet_id": sheet_id,
            "fields": [{"field_id": default_id, "title": columns[0][0]}],
        })

        # 3. 添加剩余列
        if len(columns) > 1:
            self._client.invoke_tool("smartsheet_add_fields", {
                "docid": docid,
                "sheet_id": sheet_id,
                "fields": [
                    {"title": col[0], "type": col[1]} for col in columns[1:]
                ],
            })

        logger.info("表格列已设置: docid=%s cols=%d", docid, len(columns))

    def add_records(self, docid: str, sheet_id: str,
                    rows: list[dict[str, str]]) -> dict[str, Any]:
        """追加记录行。

        Args:
            rows: [{"0": "值1", "1": "值2"}, ...]
                  键为列索引（字符串），值为单元格内容
        """
        result = self._client.invoke_tool("smartsheet_add_records", {
            "docid": docid,
            "sheet_id": sheet_id,
            "records": [{"values": row} for row in rows],
        })
        logger.info("已追加 %d 行: docid=%s", len(rows), docid)
        return result

    # ------------------------------------------------------------------
    # 文档读取
    # ------------------------------------------------------------------

    def get_doc_content(self, docid: str = "", url: str = "",
                        max_polls: int = 5, poll_interval: float = 2.0) -> str:
        """读取企微云文档内容（Markdown 格式）。

        MCP 采用异步轮询：首次调用返回 task_id，需携带 task_id 再次调用
        直到 task_done=true 时返回完整内容。

        Args:
            docid: 文档 ID（与 url 二选一）
            url: 文档链接（与 docid 二选一）
            max_polls: 最大轮询次数（默认 5）
            poll_interval: 轮询间隔秒数（默认 2）

        Returns:
            文档 Markdown 内容
        """
        import time as _time

        args: dict[str, Any] = {"type": 2}
        if docid:
            args["docid"] = docid
        elif url:
            args["url"] = url
        else:
            return "错误：必须提供 docid 或 url"

        for attempt in range(max_polls):
            result = self._client.invoke_tool("get_doc_content", args)

            # 检查是否完成
            task_done = result.get("task_done", True)
            content = result.get("content", "")

            if task_done and content:
                logger.info("文档内容已获取: docid=%s len=%d", docid or url[:30], len(content))
                return content

            # 未完成，取 task_id 继续轮询
            task_id = result.get("task_id", "")
            if not task_id:
                # 没有 task_id 也没有内容，返回空
                if content:
                    return content
                return "文档内容为空或获取失败"

            args["task_id"] = task_id
            logger.debug("文档内容轮询中: attempt=%d task_id=%s", attempt + 1, task_id)
            _time.sleep(poll_interval)

        return f"文档内容获取超时（已轮询 {max_polls} 次）"

    # ------------------------------------------------------------------
    # 文档管理（扩展）
    # ------------------------------------------------------------------

    def share_document(self, docid: str, user_ids: list[str] | None = None,
                       department_ids: list[int] | None = None) -> dict[str, Any]:
        """设置文档分享权限。

        注意：企微 MCP 当前未提供 share 权限工具，此方法为占位实现。
        实际使用时需通过企微后台手动设置权限或等待官方 MCP 扩展。

        Args:
            docid: 文档 ID
            user_ids: 可访问的用户 ID 列表
            department_ids: 可访问的部门 ID 列表
        """
        logger.warning(
            "share_document: 企微 MCP 暂无权限管理工具，docid=%s "
            "请手动在企微后台设置文档权限", docid,
        )
        # 占位——等企微 MCP 扩展后替换为实际调用
        return {"docid": docid, "status": "manual_required"}


# ============================================================================
# IST-Core 结果 → 表格数据转换
# ============================================================================

def ist_result_to_rows(
    result: dict[str, Any], final_answer: str
) -> list[dict[str, str]]:
    """将 IST-Core 结果转为智能表格行数据。

    每行格式: {"0": "时间", "1": "用例ID", "2": "状态", "3": "检查点", ...}
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    findings = result.get("findings") or []

    if not findings:
        return [{"0": ts, "1": "-", "2": "COMPLETED",
                 "3": "-", "4": final_answer[:500]}]

    rows = []
    for f in findings:
        rows.append({
            "0": ts,
            "1": str(f.get("case_id", f.get("id", "-"))),
            "2": str(f.get("status", f.get("verdict", "-"))),
            "3": str(f.get("check_point", f.get("title", "-")))[:300],
            "4": str(f.get("summary", f.get("notes", "")))[:500],
        })
    return rows


_TABLE_COLUMNS = [
    ("时间", FIELD_TEXT),
    ("用例ID", FIELD_TEXT),
    ("状态", FIELD_TEXT),
    ("检查点", FIELD_TEXT),
    ("摘要", FIELD_TEXT),
]

# DocRegistry 已迁移至 registry.py（SQLite 方案）。
# 如需引用，请使用：from .registry import DocumentRegistry
