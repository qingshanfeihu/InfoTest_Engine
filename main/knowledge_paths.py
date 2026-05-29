"""项目 knowledge 目录约定（v3，2026-05-20 KMS 简化收口）。

新分层（agent runtime 视野只看 ``data/``，``.intermediate/`` 与 ``backup/``
被 file_tools denylist 拦截）::

    knowledge/
    ├── data/                     ← agent 可见
    │   ├── orgin/                ← 源文档（KMS 命令的输入）
    │   ├── markdown/             ← KMS 直出的 markdown（agent 直读）
    │   │   ├── product/          ← /kms product update 的产物
    │   │   └── qa/               ← /kms qa update 的产物
    │   └── defects/              ← bugzilla / zentao 抓取 cache（运行时按需重建）
    └── .intermediate/            ← agent 不可见（由 /kms 命令维护）
        └── mineru/               ← MinerU 解析输出 + zip 缓存

本模块还注册 **源文档权威度**（L5）：CLI 手册 > 应用手册 > 方案规格 > 设计文档。
"""

from __future__ import annotations

import re
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MAIN_DIR.parent

KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
KNOWLEDGE_DATA_ROOT = KNOWLEDGE_ROOT / "data"
KNOWLEDGE_INTERMEDIATE = KNOWLEDGE_ROOT / ".intermediate"


KNOWLEDGE_ORGIN = KNOWLEDGE_DATA_ROOT / "orgin"


KNOWLEDGE_MARKDOWN = KNOWLEDGE_DATA_ROOT / "markdown"
KNOWLEDGE_MARKDOWN_PRODUCT = KNOWLEDGE_MARKDOWN / "product"
KNOWLEDGE_MARKDOWN_QA = KNOWLEDGE_MARKDOWN / "qa"


WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
WORKSPACE_INPUTS = WORKSPACE_ROOT / "inputs"
WORKSPACE_OUTPUTS = WORKSPACE_ROOT / "outputs"
WORKSPACE_DEFECTS = WORKSPACE_ROOT / "defects"


KNOWLEDGE_MINERU = KNOWLEDGE_INTERMEDIATE / "mineru"

CACHE_JSON = KNOWLEDGE_INTERMEDIATE / ".cache.json"





_SOURCE_AUTHORITY_RULES: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^cli_", re.IGNORECASE), 100),
    (re.compile(r"^app_", re.IGNORECASE), 80),
    (re.compile(r"phaseII|phase_II", re.IGNORECASE), 35),
    (re.compile(r"^APV_.*spec", re.IGNORECASE), 40),
    (re.compile(r"Design_Doc", re.IGNORECASE), 20),
    (re.compile(r"Project_Status", re.IGNORECASE), 15),
]

DEFAULT_SOURCE_AUTHORITY = 50


def source_authority(source_file_or_stem: str) -> int:
    """根据 ``source_file`` 或 ``stem`` 返回权威度整数。

    高权威：CLI 参考手册 (``cli_*.pdf``) = 100 > 应用手册 (``app_*.pdf``) = 80
            > 方案规格 (``APV_*_spec*``) = 40 > phaseII 规格 = 35 > 设计文档 = 20。
    """
    if not source_file_or_stem:
        return DEFAULT_SOURCE_AUTHORITY
    key = source_file_or_stem.strip()
    for pattern, score in _SOURCE_AUTHORITY_RULES:
        if pattern.search(key):
            return score
    return DEFAULT_SOURCE_AUTHORITY


def evidence_authority(evidence: dict) -> int:
    """从 evidence dict 读 ``source_file`` / ``stem`` 并返回权威度。"""
    if not isinstance(evidence, dict):
        return DEFAULT_SOURCE_AUTHORITY
    src = evidence.get("source_file") or evidence.get("stem") or ""
    return source_authority(str(src))


def ensure_intermediate_dirs() -> None:
    """初始化 ``knowledge/.intermediate/`` 子目录，供 /kms 命令调用。"""
    for d in (
        KNOWLEDGE_INTERMEDIATE,
        KNOWLEDGE_MINERU,
    ):
        d.mkdir(parents=True, exist_ok=True)


def ensure_data_dirs() -> None:
    """初始化 ``knowledge/data/`` 子目录。"""
    for d in (
        KNOWLEDGE_DATA_ROOT,
        KNOWLEDGE_ORGIN,
        KNOWLEDGE_MARKDOWN,
        KNOWLEDGE_MARKDOWN_PRODUCT,
        KNOWLEDGE_MARKDOWN_QA,
    ):
        d.mkdir(parents=True, exist_ok=True)


def ensure_workspace_dirs() -> None:
    """初始化 ``workspace/`` 子目录。"""
    for d in (WORKSPACE_ROOT, WORKSPACE_INPUTS, WORKSPACE_OUTPUTS, WORKSPACE_DEFECTS):
        d.mkdir(parents=True, exist_ok=True)
