r"""测试资产数据模型。

定义 ArtifactRegistry 使用的类型枚举和数据类。
独立于 DocumentRegistry——后者只管企微云文档，
前者管所有测试产出物（文档、日志、截图、trace、报告等）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArtifactType(str, Enum):
    """测试资产类型。"""

    DOCUMENT = "document"       # 企微云文档 / 报告
    REPORT = "report"           # 结构化测试报告
    LOG = "log"                 # Robot 日志 / CLI 输出
    IMAGE = "image"             # 流量截图 / 拓扑图
    TRACE = "trace"             # pcap / 抓包文件
    CONFIG = "config"           # 配置文件 / 快照
    EXCEL = "excel"             # 用例表 / 结果表
    OTHER = "other"


class TaskStatus(str, Enum):
    """测试任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"         # 部分通过
    CANCELLED = "cancelled"


class DocumentScope(str, Enum):
    """文档可见范围。"""

    PRIVATE = "private"         # 仅创建者可见
    GROUP = "group"             # 同群聊可见
    ENTERPRISE = "enterprise"   # 企业全员可见


class CreatorType(str, Enum):
    """创建来源类型。"""

    USER = "user"               # 用户主动创建
    AGENT = "agent"             # AI agent 代为创建（如 document-author）
    SYSTEM = "system"           # 系统/定时任务创建


@dataclass
class TaskRecord:
    """测试任务记录。"""

    id: int = 0
    task_id: str = ""
    name: str = ""
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ArtifactRecord:
    """测试资产记录。"""

    id: int = 0
    artifact_type: str = ""
    name: str = ""
    url: str = ""
    docid: str = ""
    related_task_id: str = ""
    related_case_id: str = ""
    version: int = 1
    status: str = "active"
    owner_userid: str = ""
    scope: str = "private"
    chat_id: str = ""
    creator_type: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class DocumentVersionRecord:
    """文档版本记录（关联 Artifact ↔ DocumentRegistry）。"""

    id: int = 0
    artifact_id: int = 0
    topic: str = ""
    content_hash: str = ""
    version: int = 1
    created_at: str = ""
