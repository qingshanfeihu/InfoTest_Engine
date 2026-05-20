"""项目 knowledge 目录约定（v2，2026-05-19 重组）。

新分层（agent runtime 视野只看 ``data/``，``.intermediate/`` 被 file_tools denylist 拦截）::

    knowledge/
    ├── data/                     ← agent 可见
    │   ├── orgin/                ← 源文档（管线默认从此读取）
    │   ├── features/             ← 最终 *.feature.json
    │   ├── scenarios/            ← scenario sidecar
    │   ├── architecture/         ← architecture sidecar
    │   ├── defects/              ← bugzilla / zentao 清洗结果
    │   └── baselines/            ← 测试基线规则
    └── .intermediate/            ← agent 不可见（由 /kms 命令维护）
        ├── mineru/               ← MinerU 解析输出
        ├── data/                 ← preset / *.input_data.json 清洗中间态
        ├── merged/               ← *.trunk.json 装箱中间态
        ├── cli_graph/
        ├── qa_raw/ qa_data/ qa_merged/
        └── .cache.json

历史 ``main_legacy`` 的 ``KNOWLEDGE_MINERU/DATA/MERGED`` 都重定向到
``knowledge/.intermediate/``；``KNOWLEDGE_FEATURES`` 重定向到 ``knowledge/data/features``。

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

# Agent 可见区（最终产物 + 源文档）
KNOWLEDGE_ORGIN = KNOWLEDGE_DATA_ROOT / "orgin"
KNOWLEDGE_FEATURES = KNOWLEDGE_DATA_ROOT / "features"
KNOWLEDGE_SCENARIOS = KNOWLEDGE_DATA_ROOT / "scenarios"
KNOWLEDGE_ARCHITECTURE = KNOWLEDGE_DATA_ROOT / "architecture"
KNOWLEDGE_DEFECTS = KNOWLEDGE_DATA_ROOT / "defects"
KNOWLEDGE_BASELINES = KNOWLEDGE_DATA_ROOT / "baselines"

# Agent 直读的 markdown 输出（KMS 简化管线产物）
KNOWLEDGE_MARKDOWN = KNOWLEDGE_DATA_ROOT / "markdown"
KNOWLEDGE_MARKDOWN_PRODUCT = KNOWLEDGE_MARKDOWN / "product"
KNOWLEDGE_MARKDOWN_QA = KNOWLEDGE_MARKDOWN / "qa"

# Agent 不可见区（由 /kms 命令维护的中间产物）
KNOWLEDGE_MINERU = KNOWLEDGE_INTERMEDIATE / "mineru"
KNOWLEDGE_DATA = KNOWLEDGE_INTERMEDIATE / "data"
KNOWLEDGE_MERGED = KNOWLEDGE_INTERMEDIATE / "merged"
KNOWLEDGE_CLI_GRAPH = KNOWLEDGE_INTERMEDIATE / "cli_graph"

KNOWLEDGE_QA_RAW = KNOWLEDGE_INTERMEDIATE / "qa_raw"
KNOWLEDGE_QA_DATA = KNOWLEDGE_INTERMEDIATE / "qa_data"
KNOWLEDGE_QA_MERGED = KNOWLEDGE_INTERMEDIATE / "qa_merged"

PRESET_INPUT_DATA = KNOWLEDGE_DATA / "preset_input_data.json"
CACHE_JSON = KNOWLEDGE_INTERMEDIATE / ".cache.json"

# ---------------------------------------------------------------------------
# 源文档权威度（L5）
# ---------------------------------------------------------------------------

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
        KNOWLEDGE_DATA,
        KNOWLEDGE_MERGED,
        KNOWLEDGE_CLI_GRAPH,
        KNOWLEDGE_QA_RAW,
        KNOWLEDGE_QA_DATA,
        KNOWLEDGE_QA_MERGED,
    ):
        d.mkdir(parents=True, exist_ok=True)


def ensure_data_dirs() -> None:
    """初始化 ``knowledge/data/`` 子目录。"""
    for d in (
        KNOWLEDGE_DATA_ROOT,
        KNOWLEDGE_ORGIN,
        KNOWLEDGE_FEATURES,
        KNOWLEDGE_SCENARIOS,
        KNOWLEDGE_ARCHITECTURE,
        KNOWLEDGE_DEFECTS,
        KNOWLEDGE_BASELINES,
        KNOWLEDGE_MARKDOWN,
        KNOWLEDGE_MARKDOWN_PRODUCT,
        KNOWLEDGE_MARKDOWN_QA,
    ):
        d.mkdir(parents=True, exist_ok=True)
