"""向后兼容 shim：``PlmExtractor`` 现为 ``ZentaoExtractor`` 的别名。

v1.5 起 PLM 后端统一命名为 ``zentao``（真实服务是禅道 ZenTao）。
旧代码仍可 ``from main.ingest.html_extractors.plm import PlmExtractor`` 使用。
"""

from __future__ import annotations

from main.ingest.html_extractors.zentao import ZentaoExtractor as PlmExtractor

__all__ = ["PlmExtractor"]
