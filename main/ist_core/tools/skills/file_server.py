"""qa_file_server tool: 通过 HTTP 操作远程文件服务器。

支持上传、下载、查看、编辑、删除、文件夹管理等操作。
服务器地址和凭据通过环境变量 IST_FILE_SERVER_URL / IST_FILE_SERVER_USER / IST_FILE_SERVER_PASS 配置。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _get_user_output_dir() -> Path:
    """获取当前用户专属的 outputs 目录。

    从 IST_SSH_USER 环境变量获取用户名，创建并返回 workspace/outputs/{username}/ 目录。
    """
    username = os.environ.get("IST_SSH_USER", "").strip()
    if not username:
        username = os.environ.get("IST_USERNAME", "").strip()
    if not username:
        username = "default"
    user_dir = _PROJECT_ROOT / "workspace" / "outputs" / username
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

_VALID_ACTIONS = frozenset({
    "upload", "upload-folder",
    "download", "download-folder",
    "view", "save",
    "delete", "delete-folder",
    "new-folder", "list",
})

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 300
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
_MAX_SAVE_BYTES = 1 * 1024 * 1024
_VIEW_TRUNCATE = 50 * 1024
_CHUNK = 65536


def _resolve_url(server_url: str) -> str:
    base = (server_url or os.environ.get("IST_FILE_SERVER_URL", "")).rstrip("/")
    if not base:
        raise ValueError("server_url is empty; set IST_FILE_SERVER_URL or pass server_url")
    return base


def _auth(username: str, password: str) -> tuple[str, str]:
    user = username or os.environ.get("IST_FILE_SERVER_USER", "admin")
    pwd = password or os.environ.get("IST_FILE_SERVER_PASS", "admin")
    return (user, pwd)


def _resolve_local_read(raw: str) -> Path:
    text = raw.strip()
    if not text:
        raise FileNotFoundError("local_path is required")
    p = Path(text)
    if not p.is_absolute():
        for root in [
            _PROJECT_ROOT / "workspace",
            _PROJECT_ROOT / "knowledge" / "data",
        ]:
            candidate = (root / p).resolve()
            if candidate.exists():
                p = candidate
                break
        else:
            p = (_PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()

    try:
        rel = p.relative_to(_PROJECT_ROOT)
    except ValueError:
        raise PermissionError(f"path outside project: {p}")
    parts = rel.parts
    if parts and parts[0].lower() in {"main", "tests", "scripts", ".git", ".venv", "runtime", "memory", "environment"}:
        raise PermissionError(f"path in denied directory: {parts[0]}/")
    return p


def _resolve_local_write(raw: str) -> Path:
    text = raw.strip()
    if not text:
        raise FileNotFoundError("local_path is required")
    user_dir = _get_user_output_dir()
    p = Path(text)
    if not p.is_absolute():
        if text.startswith("workspace/outputs/"):
            # 已经包含完整前缀，插入 username
            relative_part = text[len("workspace/outputs/"):]
            p = (user_dir / relative_part).resolve()
        elif text.startswith("workspace/"):
            p = (_PROJECT_ROOT / p).resolve()
        elif text.startswith("outputs/"):
            # outputs/file.txt -> outputs/{username}/file.txt
            relative_part = text[len("outputs/"):]
            p = (user_dir / relative_part).resolve()
        else:
            # 裸路径，默认写入到 outputs/{username}/ 下
            p = (user_dir / p).resolve()
    else:
        p = p.resolve()
    try:
        rel = p.relative_to(_PROJECT_ROOT)
    except ValueError:
        raise PermissionError(f"path outside project: {p}")
    parts = rel.parts
    if parts and parts[0].lower() in {"main", "tests", "scripts", ".git", ".venv", "runtime", "memory", "environment"}:
        raise PermissionError(f"path in denied directory: {parts[0]}/")
    return p


def _fmt(result: dict[str, Any]) -> str:
    lines = [
        "=== qa_file_server ===",
        f"action={result['action']}  server={result.get('server', '?')}",
    ]
    if result.get("detail"):
        lines.append(result["detail"])
    lines.append(f"status: {result['status']}")
    if result.get("body"):
        lines.append("--- response ---")
        lines.append(result["body"])
    elif result.get("error"):
        lines.append("--- error ---")
        lines.append(result["error"])
    return "\n".join(lines)


# ── action handlers ─────────────────────────────────────────────────

def _do_list(base: str, auth_t: tuple, timeout: int, remote_path: str = "") -> dict[str, Any]:
    params = {"path": remote_path} if remote_path else {}
    resp = requests.get(base, auth=auth_t, timeout=timeout, params=params)
    if resp.status_code == 401:
        return {"action": "list", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "list", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    entries = _parse_list_html(resp.text)
    if not entries:
        body = "(empty directory)"
    else:
        body = "\n".join(
            f"{'[DIR] ' if e['is_dir'] else ''}{e['name']}"
            + (f"  ({e['size']})" if e.get('size') else "")
            + (f"  {e['mtime']}" if e.get('mtime') else "")
            for e in entries
        )
    detail = f"remote_path={remote_path or '/'}"
    return {"action": "list", "status": "success", "detail": detail, "body": body}


def _parse_list_html(html: str) -> list[dict[str, Any]]:
    """从 File Manager HTML 页面提取文件/文件夹列表。"""
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
        soup = BeautifulSoup(html, "html.parser")
    except ImportError:
        return _parse_list_html_regex(html)
    entries: list[dict[str, Any]] = []
    for tr in soup.select("tr"):
        name_td = tr.select_one("td.filename")
        if not name_td:
            continue
        title = (name_td.get("title") or "").strip()
        if not title:
            link = name_td.select_one("a.folder-link, a[href]")
            title = link.get_text(strip=True) if link else name_td.get_text(strip=True)
        if not title:
            continue
        is_dir = "📂" in (name_td.get_text() or "")
        entry: dict[str, Any] = {"name": title, "is_dir": is_dir}
        size_td = tr.select_one("td.size")
        if size_td:
            entry["size"] = size_td.get_text(strip=True)
        mtime_td = tr.select_one("td.mtime")
        if mtime_td:
            entry["mtime"] = mtime_td.get_text(strip=True)
        entries.append(entry)
    return entries


def _parse_list_html_regex(html: str) -> list[dict[str, Any]]:
    """BeautifulSoup 不可用时的正则降级。"""
    import re
    entries: list[dict[str, Any]] = []
    for m in re.finditer(r'title="([^"]+)"', html):
        name = m.group(1)
        if name in ("", "File Manager"):
            continue
        entries.append({"name": name, "is_dir": False})
    return entries


def _do_upload(base: str, auth_t: tuple, timeout: int, local_path: Path, remote_path: str) -> dict[str, Any]:
    if not local_path.exists():
        return {"action": "upload", "status": "error", "error": f"local file not found: {local_path}"}
    if not local_path.is_file():
        return {"action": "upload", "status": "error", "error": f"not a file: {local_path}"}
    size = local_path.stat().st_size
    if size > _MAX_UPLOAD_BYTES:
        return {"action": "upload", "status": "error", "error": f"file too large: {size} bytes (max {_MAX_UPLOAD_BYTES})"}
    data: dict[str, Any] = {}
    if remote_path:
        data["path"] = remote_path
    with open(local_path, "rb") as f:
        files = {"files": (local_path.name, f)}
        resp = requests.post(f"{base}/upload", auth=auth_t, files=files, data=data, timeout=timeout)
    if resp.status_code == 401:
        return {"action": "upload", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "upload", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    return {"action": "upload", "status": "success", "detail": f"local={local_path.name} → remote={remote_path or '(root)'}", "body": resp.content.decode("utf-8", errors="replace")[:1000]}


def _do_upload_folder(base: str, auth_t: tuple, timeout: int, local_path: Path) -> dict[str, Any]:
    if not local_path.exists() or not local_path.is_dir():
        return {"action": "upload-folder", "status": "error", "error": f"local directory not found: {local_path}"}
    files_data = []
    file_handles = []
    try:
        for f in sorted(local_path.rglob("*")):
            if f.is_file():
                rel = f.relative_to(local_path)
                fh = open(f, "rb")
                file_handles.append(fh)
                files_data.append(("folder_files", (str(rel), fh)))
        if not files_data:
            return {"action": "upload-folder", "status": "error", "error": f"no files in {local_path}"}
        resp = requests.post(f"{base}/upload-folder", auth=auth_t, files=files_data, timeout=timeout)
    finally:
        for fh in file_handles:
            fh.close()
    if resp.status_code == 401:
        return {"action": "upload-folder", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "upload-folder", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    return {"action": "upload-folder", "status": "success", "detail": f"local_dir={local_path}", "body": resp.content.decode("utf-8", errors="replace")[:1000]}


def _do_download(base: str, auth_t: tuple, timeout: int, filename: str, local_path: Path) -> dict[str, Any]:
    if not filename:
        return {"action": "download", "status": "error", "error": "filename is required"}
    resp = requests.get(f"{base}/download/{filename}", auth=auth_t, timeout=timeout, stream=True)
    if resp.status_code == 401:
        return {"action": "download", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "download", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    ct = (resp.headers.get("content-type") or "").lower()
    if "text/html" in ct:
        return {"action": "download", "status": "error", "error": f"server returned HTML (file not found?): {filename}. Use qa_file_server(action='list', remote_path='<dir>') to find the correct path."}
    local_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(_CHUNK):
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                f.close()
                local_path.unlink(missing_ok=True)
                return {"action": "download", "status": "error", "error": f"download too large: >{total} bytes (max {_MAX_DOWNLOAD_BYTES})"}
            f.write(chunk)
    return {"action": "download", "status": "success", "detail": f"remote={filename} → local={local_path} ({total} bytes)", "body": f"saved {total} bytes to {local_path}"}


def _do_download_folder(base: str, auth_t: tuple, timeout: int, foldername: str, local_path: Path) -> dict[str, Any]:
    if not foldername:
        return {"action": "download-folder", "status": "error", "error": "foldername is required"}
    resp = requests.get(f"{base}/download-folder/{foldername}", auth=auth_t, timeout=timeout, stream=True)
    if resp.status_code == 401:
        return {"action": "download-folder", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "download-folder", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    local_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(_CHUNK):
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                f.close()
                local_path.unlink(missing_ok=True)
                return {"action": "download-folder", "status": "error", "error": f"download too large: >{total} bytes (max {_MAX_DOWNLOAD_BYTES})"}
            f.write(chunk)
    return {"action": "download-folder", "status": "success", "detail": f"remote_dir={foldername} → local={local_path} ({total} bytes)", "body": f"saved {total} bytes to {local_path}"}


def _do_view(base: str, auth_t: tuple, timeout: int, filename: str) -> dict[str, Any]:
    if not filename:
        return {"action": "view", "status": "error", "error": "filename is required"}
    resp = requests.get(f"{base}/view/{filename}", auth=auth_t, timeout=timeout)
    if resp.status_code == 401:
        return {"action": "view", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "view", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    text = resp.content.decode("utf-8", errors="replace")
    truncated = len(text.encode("utf-8", errors="replace")) > _VIEW_TRUNCATE
    if truncated:
        text = text[:_VIEW_TRUNCATE] + "\n... (truncated)"
    return {"action": "view", "status": "success", "detail": f"file={filename}", "body": text}


def _do_save(base: str, auth_t: tuple, timeout: int, filename: str, content: str) -> dict[str, Any]:
    if not filename:
        return {"action": "save", "status": "error", "error": "filename is required"}
    if len(content.encode("utf-8")) > _MAX_SAVE_BYTES:
        return {"action": "save", "status": "error", "error": f"content too large (max {_MAX_SAVE_BYTES} bytes)"}
    resp = requests.post(
        f"{base}/save/{filename}",
        auth=auth_t,
        json={"content": content},
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    if resp.status_code == 401:
        return {"action": "save", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "save", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    return {"action": "save", "status": "success", "detail": f"file={filename}", "body": resp.content.decode("utf-8", errors="replace")[:1000]}


def _do_delete(base: str, auth_t: tuple, timeout: int, filename: str) -> dict[str, Any]:
    if not filename:
        return {"action": "delete", "status": "error", "error": "filename is required"}
    resp = requests.post(f"{base}/delete/{filename}", auth=auth_t, timeout=timeout)
    if resp.status_code == 401:
        return {"action": "delete", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "delete", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    return {"action": "delete", "status": "success", "detail": f"file={filename}", "body": resp.content.decode("utf-8", errors="replace")[:1000]}


def _do_delete_folder(base: str, auth_t: tuple, timeout: int, foldername: str) -> dict[str, Any]:
    if not foldername:
        return {"action": "delete-folder", "status": "error", "error": "foldername is required"}
    resp = requests.post(f"{base}/delete-folder/{foldername}", auth=auth_t, timeout=timeout)
    if resp.status_code == 401:
        return {"action": "delete-folder", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "delete-folder", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    return {"action": "delete-folder", "status": "success", "detail": f"folder={foldername}", "body": resp.content.decode("utf-8", errors="replace")[:1000]}


def _do_new_folder(base: str, auth_t: tuple, timeout: int, foldername: str) -> dict[str, Any]:
    if not foldername:
        return {"action": "new-folder", "status": "error", "error": "foldername is required"}
    resp = requests.post(f"{base}/new-folder", auth=auth_t, data={"foldername": foldername}, timeout=timeout)
    if resp.status_code == 401:
        return {"action": "new-folder", "status": "error", "error": "authentication failed (HTTP 401)"}
    if resp.status_code != 200:
        return {"action": "new-folder", "status": "error", "error": f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:500]}"}
    return {"action": "new-folder", "status": "success", "detail": f"folder={foldername}", "body": resp.content.decode("utf-8", errors="replace")[:1000]}


# ── main tool ───────────────────────────────────────────────────────

@tool(parse_docstring=True)
def qa_file_server(
    action: str,
    filename: str = "",
    local_path: str = "",
    content: str = "",
    remote_path: str = "",
    foldername: str = "",
    server_url: str = "",
    username: str = "",
    password: str = "",
    timeout: int = 30,
) -> str:
    """Upload, download, view, edit, delete, and manage files on a remote HTTP file server.

    Uses HTTP Basic Auth. Server URL and credentials default to environment
    variables IST_FILE_SERVER_URL / IST_FILE_SERVER_USER / IST_FILE_SERVER_PASS.
    Upload/download single file limit: 500 MB.

    Supported actions:
    - ``upload``: Upload a local file. Set ``local_path`` (sandbox path) and ``filename`` (remote name).
      Optionally set ``remote_path`` for a server subdirectory.
    - ``upload-folder``: Upload all files under ``local_path`` as a folder.
    - ``download``: Download ``filename`` from server to ``local_path`` (default: workspace/outputs/<filename>).
    - ``download-folder``: Download ``foldername`` as a zip to ``local_path``.
    - ``view``: View text content of ``filename`` on the server.
    - ``save``: Create or overwrite ``filename`` with ``content`` (JSON body).
    - ``delete``: Delete ``filename`` on the server.
    - ``delete-folder``: Delete ``foldername`` on the server.
    - ``new-folder``: Create ``foldername`` on the server.
    - ``list``: List files on the server. Use ``remote_path`` to browse subdirectories (e.g. ``remote_path="yzg/inputs"``).

    Args:
        action: One of upload, upload-folder, download, download-folder, view,
            save, delete, delete-folder, new-folder, list.
        filename: Remote filename (for download, view, save, delete).
        local_path: Local file path. Upload source or download destination.
        content: File content for the ``save`` action.
        remote_path: Server subdirectory. Used by upload (target dir) and list (browse dir).
        foldername: Remote folder name (for download-folder, delete-folder, new-folder).
        server_url: Server base URL. Defaults to env IST_FILE_SERVER_URL.
        username: Basic Auth username. Defaults to env IST_FILE_SERVER_USER.
        password: Basic Auth password. Defaults to env IST_FILE_SERVER_PASS.
        timeout: HTTP timeout in seconds (1-300, default 30).

    Returns:
        Structured output with action, status, and server response or error.
    """
    action = (action or "").strip().lower()
    if action not in _VALID_ACTIONS:
        return f"error: unknown action {action!r}. Must be one of: {', '.join(sorted(_VALID_ACTIONS))}"

    try:
        base = _resolve_url(server_url)
    except ValueError as e:
        return f"error: {e}"

    auth_t = _auth(username, password)
    timeout = max(1, min(int(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))

    common: dict[str, Any] = {"server": base}

    try:
        if action == "list":
            result = _do_list(base, auth_t, timeout, remote_path)

        elif action == "upload":
            lp = _resolve_local_read(local_path)
            result = _do_upload(base, auth_t, timeout, lp, remote_path)

        elif action == "upload-folder":
            lp = _resolve_local_read(local_path)
            result = _do_upload_folder(base, auth_t, timeout, lp)

        elif action == "download":
            dest = _resolve_local_write(local_path) if local_path else (
                _PROJECT_ROOT / "workspace" / "outputs" / filename
            ).resolve()
            result = _do_download(base, auth_t, timeout, filename, dest)

        elif action == "download-folder":
            dest = _resolve_local_write(local_path) if local_path else (
                _PROJECT_ROOT / "workspace" / "outputs" / f"{foldername}.zip"
            ).resolve()
            result = _do_download_folder(base, auth_t, timeout, foldername, dest)

        elif action == "view":
            result = _do_view(base, auth_t, timeout, filename)

        elif action == "save":
            result = _do_save(base, auth_t, timeout, filename, content)

        elif action == "delete":
            result = _do_delete(base, auth_t, timeout, filename)

        elif action == "delete-folder":
            result = _do_delete_folder(base, auth_t, timeout, foldername)

        elif action == "new-folder":
            result = _do_new_folder(base, auth_t, timeout, foldername)

        else:
            return f"error: unhandled action {action!r}"

    except FileNotFoundError as e:
        return f"error: {e}"
    except PermissionError as e:
        return f"error: permission denied: {e}"
    except requests.exceptions.Timeout:
        return f"error: request to {base} timed out after {timeout}s"
    except requests.exceptions.ConnectionError as e:
        return f"error: connection to {base} failed: {e}"
    except Exception as e:
        return f"error: {e}"

    result.update(common)
    return _fmt(result)
