"""HTML 抽取器契约层。

每个 backend 提供一个 ``DefectExtractor`` 实现，按 ``selectors.yaml`` 配置的
CSS 选择器解析 HTML → ``DefectTicket`` Pydantic 模型。

- ``bugzilla`` → ``BugzillaExtractor``
- ``zentao`` / ``plm``（别名）→ ``ZentaoExtractor``
- ``zentao_story`` → ``ZentaoStoryExtractor``（默认 doc_type=plm_ticket）
"""

from __future__ import annotations

from typing import Protocol

from main.ingest.html_extractors.schema import DefectTicket

__all__ = ["DefectExtractor", "DefectTicket", "get_extractor", "canonical_backend"]


class DefectExtractor(Protocol):
    backend: str
    version: str

    def extract(self, html: str) -> DefectTicket: ...


def canonical_backend(backend: str) -> str:
    """把 ``plm`` 归一成 ``zentao``；其它保持原样。"""
    b = (backend or "").strip().lower()
    if b == "plm":
        return "zentao"
    return b


def get_extractor(backend: str) -> DefectExtractor:
    """根据 backend 名获取对应 extractor 实例。

    - ``bugzilla`` → BugzillaExtractor
    - ``zentao`` / ``plm`` → ZentaoExtractor
    - ``zentao_story`` → ZentaoStoryExtractor
    """
    b = (backend or "").strip().lower()
    if b == "bugzilla":
        from main.ingest.html_extractors.bugzilla import BugzillaExtractor

        return BugzillaExtractor()
    if b in ("zentao", "plm"):
        from main.ingest.html_extractors.zentao import ZentaoExtractor

        return ZentaoExtractor()
    if b == "zentao_story":
        from main.ingest.html_extractors.zentao import ZentaoStoryExtractor

        return ZentaoStoryExtractor()
    raise ValueError(f"未知 backend: {backend}")
