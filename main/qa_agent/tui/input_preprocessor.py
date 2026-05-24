"""TUI 输入预处理：检测用户消息中的本地文件路径，自动转换并替换为沙箱路径。

设计原则：
  - 对话是唯一界面，文件传输是对话的透明副作用
  - 客户说 "评审 D:\\xxx.xlsx" 或 "评审 /path/to/xxx.xlsx"，系统自动处理
  - 不引入 /upload 等 slash 命令

检测规则：
  - Windows 绝对路径：^[A-Za-z]:[\\/]
  - POSIX 绝对路径：^/ 且不在沙箱根内
  - Home 路径：^~/
  - 带引号的路径：'...' 或 "..."

处理流程：
  1. 正则扫描 user input 中的文件路径
  2. 路径存在且是支持的格式（xlsx/xls/pdf/docx/md/txt）→ 转换/复制到沙箱
  3. 替换 user message 中的路径为沙箱路径
  4. 返回 (modified_text, status_message)
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_WORKSPACE = _PROJECT_ROOT / "workspace"
_DEFAULT_INBOX = _WORKSPACE / "inputs"

# 路径正则：匹配引号包裹的路径 或 常见绝对路径模式
_PATH_PATTERNS = [
    # 单引号包裹
    re.compile(r"'([^']{3,})'"),
    # 双引号包裹
    re.compile(r'"([^"]{3,})"'),
    # Windows 绝对路径（无引号）
    re.compile(r'([A-Za-z]:[\\\/]\S+)'),
    # POSIX 绝对路径（无引号，非 http）
    re.compile(r'(?<!\w)(\/(?:Users|home|tmp|var|opt|mnt|media)[\/]\S+)'),
    # ~/xxx
    re.compile(r'(~\/\S+)'),
]

_CONVERTIBLE_SUFFIXES = {".xlsx", ".xls"}
_COPYABLE_SUFFIXES = {".md", ".txt", ".json", ".csv", ".pdf", ".docx", ".conf", ".cfg", ".ini", ".yaml", ".yml", ".xml", ".log"}


def _expand_path(raw: str) -> Path | None:
    """展开路径（~ 展开），返回 Path 或 None（不存在时）。"""
    try:
        p = Path(os.path.expanduser(raw.strip()))
        if p.exists():
            return p
    except Exception:  # noqa: BLE001
        pass
    return None


def _looks_like_file_path(raw: str) -> bool:
    """判断字符串是否看起来像文件路径（即使文件不存在于本地）。"""
    s = raw.strip()
    # Windows 绝对路径
    if len(s) > 3 and s[1] == ":" and s[2] in ("\\/"):
        return True
    # POSIX 绝对路径
    if s.startswith("/") and "/" in s[1:]:
        return True
    # ~/xxx
    if s.startswith("~/") and len(s) > 2:
        return True
    return False


def _extract_filename(raw: str) -> str:
    """从路径字符串中提取文件名（兼容 Windows 和 POSIX）。"""
    # 统一分隔符
    normalized = raw.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] if "/" in normalized else raw


def _is_in_sandbox(path: Path) -> bool:
    """路径是否已经在 agent 可访问的沙箱内（knowledge/data 或 workspace）。"""
    _knowledge_data = _PROJECT_ROOT / "knowledge" / "data"
    try:
        path.resolve().relative_to(_knowledge_data.resolve())
        return True
    except ValueError:
        pass
    try:
        path.resolve().relative_to(_WORKSPACE.resolve())
        return True
    except ValueError:
        return False


def _convert_xlsx(src: Path, dest_dir: Path) -> Path | None:
    """xlsx → GFM markdown，返回输出路径。"""
    try:
        from main.xlsx_to_markdown import convert_xlsx_to_markdown
        md_content = convert_xlsx_to_markdown(src)
        dest = dest_dir / f"{src.stem}.md"
        dest.write_text(md_content, encoding="utf-8")
        return dest
    except Exception as exc:  # noqa: BLE001
        logger.warning("xlsx conversion failed for %s: %s", src, exc)
        return None


def _copy_to_sandbox(src: Path, dest_dir: Path) -> Path | None:
    """直接复制文件到沙箱。"""
    try:
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        return dest
    except Exception as exc:  # noqa: BLE001
        logger.warning("file copy failed for %s: %s", src, exc)
        return None


def preprocess_file_paths(
    text: str,
    *,
    session_dir: Path | None = None,
) -> tuple[str, str | None]:
    """扫描 user input 中的文件路径，转换/复制到沙箱，替换路径。

    Args:
        text: 用户原始输入
        session_dir: per-session 目录（远程 TUI 时由 env 注入）；
                     不影响输出位置——转换后的文件始终放到 workspace/inputs/
                     以确保 agent 沙箱能读取。

    Returns:
        (modified_text, status_message)
        status_message 为 None 表示没有检测到需要处理的路径。
        status_message 以 "⬆ NEED_UPLOAD:" 开头表示需要用户上传文件内容。
    """
    dest_dir = _DEFAULT_INBOX
    dest_dir.mkdir(parents=True, exist_ok=True)

    modified = text
    processed: list[str] = []
    need_upload: list[tuple[str, str]] = []  # (raw_path, filename)
    seen_spans: set[tuple[int, int]] = set()  # 避免重复匹配

    for pattern in _PATH_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            # 跳过已被前面模式匹配过的区域
            if any(s <= span[0] and span[1] <= e for s, e in seen_spans):
                continue
            raw_path = match.group(1)
            path = _expand_path(raw_path)

            if path is not None and path.is_file():
                # 文件存在于本地——直接处理
                if _is_in_sandbox(path):
                    seen_spans.add(span)
                    continue
                suffix = path.suffix.lower()
                result_path: Path | None = None
                if suffix in _CONVERTIBLE_SUFFIXES:
                    result_path = _convert_xlsx(path, dest_dir)
                elif suffix in _COPYABLE_SUFFIXES:
                    result_path = _copy_to_sandbox(path, dest_dir)
                else:
                    continue
                if result_path is None:
                    continue
                try:
                    sandbox_rel = result_path.resolve().relative_to(
                        _WORKSPACE.resolve()
                    ).as_posix()
                except ValueError:
                    sandbox_rel = str(result_path)
                old_span = match.group(0)
                modified = modified.replace(old_span, sandbox_rel, 1)
                processed.append(f"{path.name} → {sandbox_rel}")
                seen_spans.add(span)
            elif _looks_like_file_path(raw_path):
                # 路径格式合法但本地不存在——可能是远程客户端路径，需要上传
                filename = _extract_filename(raw_path)
                need_upload.append((raw_path, filename))
                seen_spans.add(span)

    # 需要上传文件（远程 SSH 场景）
    if need_upload and not processed:
        filenames = ", ".join(fn for _, fn in need_upload)
        return text, f"⬆ NEED_UPLOAD:{filenames}"

    if not processed:
        return text, None

    status = "⬆ " + "；".join(processed)
    return modified, status
