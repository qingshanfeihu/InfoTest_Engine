"""Read-only generic filesystem tools for the phase-one QA agent surface."""

from __future__ import annotations

import fnmatch
import html
import re
import zipfile
from pathlib import Path
from typing import Iterable

from langchain_core.tools import tool


_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DENIED_TOP_LEVEL = {
    ".env",
    ".git",
    ".langgraph_data",
    ".venv",
    ".venv311",
    "environment",
    "postgres_storage",
    "qdrant_storage",
}
_DENIED_PREFIXES = (
    "logs/reviewer_evidence",
    "logs/reviewer_jobs",
)
_TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".jsonc",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".text",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
_SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm"}
_DOCX_SUFFIXES = {".docx"}


def _project_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_inside_root(raw_path: str | None, *, must_exist: bool = False) -> Path:
    path_text = (raw_path or ".").strip() or "."
    path = Path(path_text)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(_PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {raw_path}") from exc
    rel_parts = rel.parts
    if rel_parts:
        first = rel_parts[0]
        if first in _DENIED_TOP_LEVEL:
            raise PermissionError(f"path is denied for generic read-only tools: {first}")
        rel_posix = rel.as_posix()
        if any(rel_posix == p or rel_posix.startswith(p + "/") for p in _DENIED_PREFIXES):
            raise PermissionError(f"path is denied for generic read-only tools: {rel_posix}")
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"path not found: {raw_path}")
    return resolved


def _normalise_pattern(pattern: str, base: Path) -> str:
    pattern = (pattern or "*").strip() or "*"
    pattern_path = Path(pattern)
    if pattern_path.is_absolute():
        try:
            return pattern_path.resolve().relative_to(base).as_posix()
        except ValueError:
            return pattern_path.name
    return pattern


def _is_probably_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except Exception:
        return True
    return b"\x00" in chunk


def _iter_candidate_files(base: Path, glob_pattern: str, *, max_files: int = 5000) -> Iterable[Path]:
    pattern = _normalise_pattern(glob_pattern, base)
    count = 0
    for path in base.glob(pattern):
        try:
            resolved = _resolve_inside_root(path.as_posix(), must_exist=True)
        except Exception:
            continue
        if not resolved.is_file():
            continue
        count += 1
        if count > max_files:
            break
        yield resolved


def _format_page(lines: list[str], *, offset: int, limit: int) -> str:
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 200), 1000))
    total = len(lines)
    page = lines[offset : offset + limit]
    header = f"total_lines={total}, offset={offset}, returned={len(page)}"
    if offset + limit < total:
        header += f", next_offset={offset + limit}"
    return header + "\n" + "\n".join(page)


def _read_text_file(path: Path, *, offset: int, limit: int) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    numbered = [f"{i + 1}: {line}" for i, line in enumerate(lines)]
    return _format_page(numbered, offset=offset, limit=limit)


def _clean_xml_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _read_docx(path: Path, *, offset: int, limit: int) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.startswith("word/") and n.endswith(".xml")]
            parts: list[str] = []
            for name in names:
                if name != "word/document.xml" and not name.startswith("word/header") and not name.startswith("word/footer"):
                    continue
                raw = zf.read(name).decode("utf-8", errors="replace")
                cleaned = _clean_xml_text(raw)
                if cleaned:
                    parts.append(f"=== {name} ===\n{cleaned}")
    except Exception as exc:  # noqa: BLE001
        return f"error: unable to read docx as generic document: {exc}"
    lines = "\n\n".join(parts).splitlines()
    numbered = [f"{i + 1}: {line}" for i, line in enumerate(lines)]
    return _format_page(numbered, offset=offset, limit=limit)


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return re.sub(r"\s+", " ", text)


def _read_spreadsheet(path: Path, *, offset: int, limit: int) -> str:
    try:
        import openpyxl  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        return f"error: openpyxl is required to read spreadsheet files: {exc}"

    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        return f"error: unable to read spreadsheet: {exc}"

    lines: list[str] = [f"workbook={_project_rel(path)} sheets={len(wb.sheetnames)}"]
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        lines.append(
            f"=== Sheet: {sheet_name} dims={ws.calculate_dimension()} "
            f"max_row={ws.max_row} max_col={ws.max_column} ==="
        )
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            values = [_cell_text(v) for v in row]
            if not any(values):
                continue
            trimmed = values[:20]
            suffix = " || ..." if len(values) > len(trimmed) else ""
            lines.append(f"{sheet_name}!{row_idx}: " + " || ".join(trimmed) + suffix)
    return _format_page(lines, offset=offset, limit=limit)


@tool(parse_docstring=True)
def qa_deepagent_ls(path: str = ".", max_entries: int = 200) -> str:
    """List files and directories under the project root.

    This is a generic DeepAgents-style ``ls`` tool for phase-one static review.
    It is read-only, concurrency-safe, and does not run project code. Use it
    to inspect the repository layout or a known evidence directory before
    narrowing to ``qa_deepagent_read_file`` / ``qa_deepagent_grep``.

    Boundaries:
    - Generic read-only project exploration tool.
    - Does not write files, start processes, access vector stores, or call
      language models.
    - Safe to call concurrently with other generic read tools.
    - Denies secret/runtime directories such as environment, .env, .git,
      virtualenvs, local vector storage, and internal run logs.

    Args:
        path: Project-relative or absolute path inside this repository.
        max_entries: Maximum directory entries to return.

    Returns:
        Text lines with type, relative path, size, and child count when useful.
    """
    try:
        target = _resolve_inside_root(path, must_exist=True)
        if target.is_file():
            return f"file {_project_rel(target)} size={target.stat().st_size}"
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        max_entries = max(1, min(int(max_entries or 200), 1000))
        out = [f"path={_project_rel(target) or '.'} entries={len(entries)} returned={min(len(entries), max_entries)}"]
        for child in entries[:max_entries]:
            try:
                _resolve_inside_root(child.as_posix(), must_exist=True)
            except Exception:
                continue
            stat = child.stat()
            if child.is_dir():
                try:
                    child_count = len(list(child.iterdir()))
                except Exception:
                    child_count = -1
                out.append(f"dir  {_project_rel(child)}/ children={child_count}")
            else:
                out.append(f"file {_project_rel(child)} size={stat.st_size}")
        if len(entries) > max_entries:
            out.append(f"... truncated; increase max_entries or narrow path")
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


@tool(parse_docstring=True)
def qa_deepagent_glob(pattern: str, path: str = ".", max_results: int = 200) -> str:
    """Find files by glob pattern under the project root.

    This is a generic DeepAgents-style ``glob`` tool for locating candidate
    source documents, test lists, JSON features, markdown notes, or code files.

    Boundaries:
    - Generic read-only tool for locating candidate files.
    - Concurrency-safe.
    - Does not read file contents; use ``qa_deepagent_read_file`` for that.
    - Denies secret/runtime directories.

    Args:
        pattern: Glob pattern such as ``knowledge/orgin/*.xlsx`` or
            ``**/*Cookie*.md``.
        path: Optional base directory inside the project.
        max_results: Maximum paths returned.

    Returns:
        Matching project-relative paths, one per line.
    """
    try:
        base = _resolve_inside_root(path, must_exist=True)
        if base.is_file():
            base = base.parent
        pattern = _normalise_pattern(pattern, base)
        max_results = max(1, min(int(max_results or 200), 1000))
        matches: list[str] = []
        for match in base.glob(pattern):
            try:
                resolved = _resolve_inside_root(match.as_posix(), must_exist=True)
            except Exception:
                continue
            matches.append(_project_rel(resolved) + ("/" if resolved.is_dir() else ""))
            if len(matches) >= max_results:
                break
        return "\n".join(matches) if matches else "(no matches)"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


@tool(parse_docstring=True)
def qa_deepagent_grep(
    pattern: str,
    path: str = ".",
    glob: str = "**/*",
    case_sensitive: bool = False,
    max_results: int = 100,
) -> str:
    """Search text patterns across project files.

    This is a generic DeepAgents-style ``grep`` tool. Use it for broad local
    evidence discovery, such as finding product terms, CLI strings, bug ids,
    or existing review documents. It is intentionally simple and read-only.

    Boundaries:
    - Generic read-only search tool.
    - Concurrency-safe.
    - Searches text-like files only; binary files are skipped.
    - Does not infer conclusions. The agent must reason from matched
      lines and cited files.

    Args:
        pattern: Regex pattern. Invalid regex is treated as literal text.
        path: Project-relative directory or file to search.
        glob: Glob filter under path, for example ``**/*.md``.
        case_sensitive: Whether matching is case-sensitive.
        max_results: Maximum matching lines returned.

    Returns:
        ``path:line:text`` matches with truncation notice when applicable.
    """
    try:
        base = _resolve_inside_root(path, must_exist=True)
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            rx = re.compile(pattern, flags)
        except re.error:
            rx = re.compile(re.escape(pattern), flags)
        files = [base] if base.is_file() else list(_iter_candidate_files(base, glob))
        max_results = max(1, min(int(max_results or 100), 1000))
        out: list[str] = []
        for file_path in files:
            if file_path.suffix.lower() not in _TEXT_SUFFIXES and _is_probably_binary(file_path):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for line_no, line in enumerate(lines, start=1):
                if rx.search(line):
                    snippet = line.strip()
                    if len(snippet) > 400:
                        snippet = snippet[:397] + "..."
                    out.append(f"{_project_rel(file_path)}:{line_no}: {snippet}")
                    if len(out) >= max_results:
                        out.append("... truncated; narrow path/glob or increase max_results")
                        return "\n".join(out)
        return "\n".join(out) if out else "(no matches)"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


@tool(parse_docstring=True)
def qa_deepagent_read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    """Read a project file with line-oriented pagination.

    This is the phase-one generic equivalent of DeepAgents ``read_file``. It
    reads text files directly and renders ``.xlsx`` / ``.xlsm`` spreadsheets as
    plain text sheet rows so an analysis task can inspect a test list without
    invoking any non-read-only flow.

    Boundaries:
    - Generic read-only file inspection tool.
    - Concurrency-safe.
    - Does not write derived files, update caches, run commands, call language
      models, or index anything.
    - Spreadsheet reading is structural only: it returns workbook/sheet/row
      content for analysis.

    Args:
        path: Project-relative or absolute path inside this repository.
        offset: Zero-based line offset for pagination.
        limit: Number of rendered lines to return, capped to 1000.

    Returns:
        Text with ``total_lines`` metadata and numbered/paged content.
    """
    try:
        target = _resolve_inside_root(path, must_exist=True)
        if target.is_dir():
            return qa_deepagent_ls.invoke({"path": _project_rel(target), "max_entries": limit})
        suffix = target.suffix.lower()
        if suffix in _SPREADSHEET_SUFFIXES:
            return _read_spreadsheet(target, offset=offset, limit=limit)
        if suffix in _DOCX_SUFFIXES:
            return _read_docx(target, offset=offset, limit=limit)
        if suffix not in _TEXT_SUFFIXES and _is_probably_binary(target):
            return f"error: unsupported binary file for generic read_file: {_project_rel(target)}"
        return _read_text_file(target, offset=offset, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
