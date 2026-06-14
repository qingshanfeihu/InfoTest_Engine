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
from collections.abc import Iterator
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MAIN_DIR.parent

KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
KNOWLEDGE_DATA_ROOT = KNOWLEDGE_ROOT / "data"
KNOWLEDGE_INTERMEDIATE = KNOWLEDGE_ROOT / ".intermediate"


KNOWLEDGE_ORGIN = KNOWLEDGE_DATA_ROOT / "orgin"


# mineru_batch_export 在 orgin/ 下自建的 PDF 切分工作目录；枚举源文件时必须排除，
# 否则切片会被当成新源文件重复摄入。以 ``.`` 开头的隐藏目录同样跳过。
ORGIN_WORKDIR_NAME = "_pdf_splits"


def _is_skipped_dir(name: str) -> bool:
    """递归遍历 orgin/ 时应跳过的目录名（隐藏目录 + mineru 工作目录）。"""
    return name.startswith(".") or name == ORGIN_WORKDIR_NAME


def iter_orgin_files(orgin_dir: Path | str | None = None) -> Iterator[Path]:
    """递归枚举 orgin/ 下的源文件（含任意层级子目录），结果路径稳定排序。

    跳过隐藏文件 / 隐藏目录 / ``_pdf_splits`` 工作目录。返回绝对/原样 ``Path``，
    调用方可用 ``path.relative_to(orgin_dir)`` 取得贯穿 KMS 全链的相对标识符。
    """
    root = Path(orgin_dir) if orgin_dir is not None else KNOWLEDGE_ORGIN
    if not root.exists():
        return

    def _walk(d: Path) -> Iterator[Path]:
        for child in sorted(d.iterdir(), key=lambda p: p.name):
            if child.is_dir():
                if _is_skipped_dir(child.name):
                    continue
                yield from _walk(child)
            elif child.is_file():
                if child.name.startswith("."):
                    continue
                yield child

    yield from _walk(root)


def orgin_rel_key(path: Path | str, orgin_dir: Path | str | None = None) -> str:
    """把 orgin/ 下的文件路径转成贯穿 KMS 全链的相对标识符（POSIX 斜杠）。

    顶层文件返回的就是 basename，保证与旧链路（按 ``p.name``）行为一致；
    嵌套文件返回 ``subdir/file.ext`` 形式，避免跨子目录同名冲突。
    """
    root = Path(orgin_dir) if orgin_dir is not None else KNOWLEDGE_ORGIN
    p = Path(path)
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.name



KNOWLEDGE_MARKDOWN = KNOWLEDGE_DATA_ROOT / "markdown"
KNOWLEDGE_MARKDOWN_PRODUCT = KNOWLEDGE_MARKDOWN / "product"
KNOWLEDGE_MARKDOWN_QA = KNOWLEDGE_MARKDOWN / "qa"


WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
WORKSPACE_INPUTS = WORKSPACE_ROOT / "inputs"
WORKSPACE_OUTPUTS = WORKSPACE_ROOT / "outputs"
WORKSPACE_DEFECTS = WORKSPACE_ROOT / "defects"


KNOWLEDGE_MINERU = KNOWLEDGE_INTERMEDIATE / "mineru"

CACHE_JSON = KNOWLEDGE_INTERMEDIATE / ".cache.json"


# footprint 知识库：从产品文档提炼的 CLI 命令知识（slb.virtual.http.json 等），
# 属 knowledge 资产而非用户私有记忆，故锚定项目 knowledge 根。
# 注意：历史上 footprint/index.py 与 dream.py 用 ``get_default_root().parent``
# 拼此路径——仅在 IST_MEMORY_ROOT 未设时才碰巧等于此处；统一到这里消除该耦合。
KNOWLEDGE_FOOTPRINTS = KNOWLEDGE_ROOT / "footprints"
KNOWLEDGE_FOOTPRINTS_NODES = KNOWLEDGE_FOOTPRINTS / "nodes"


# auto_env：设备自动化环境资产（网络拓扑 RAG 等），历史上在 5 处文件各自硬编码。
KNOWLEDGE_AUTO_ENV = KNOWLEDGE_DATA_ROOT / "auto_env"
KNOWLEDGE_AUTO_ENV_TOPOLOGY = KNOWLEDGE_AUTO_ENV / "network_topology_rag.md"





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
