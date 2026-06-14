#!/usr/bin/env python3
"""
MinerU 精准解析：本地上传批量接口 → 轮询结果 → 解压 ZIP → 写出 code_format / raw_data JSON。

认证：环境变量 MINERU_TOKEN 或 MINERU_API_TOKEN（Bearer Token，勿提交到仓库）；
或写入项目根目录 **environment** 文件（`KEY=value` 格式，见 `environment.example`）。

用法示例：
  export MINERU_TOKEN='你的token'
  python main/mineru_batch_export.py \\
    --input-dir knowledge/orgin \\
    --output-dir knowledge/mineru

说明：默认另存 {stem}.mineru.zip，并在 code_format.json 中写入 zip_inventory、content_list_v2、
embedded_binary（图片、*_origin.pdf 等），以便与 markdown 联用完整还原 MinerU 包内资源。
若仅需小体积 JSON，可加 --no-embed-binary-in-json（仍保留 .mineru.zip）。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import socket
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from main.mineru_source_index import SourceIndex

# Watchdog：进程级硬保险。卡死 5 次的根因是 macOS+SSL+OSS 慢连接环境顽疾，
# requests/urllib3/socket 各层 timeout 均不可靠。watchdog 监控"最后进展时间"，
# 超过 MINERU_WATCHDOG_SEC（默认 240s）无任何进展就 os._exit 强制退出，
# 由外层循环重启续跑（zip 缓存 + 内容寻址让已完成的秒过，不丢进度）。
_LAST_PROGRESS = [0.0]


def _mark_progress() -> None:
    _LAST_PROGRESS[0] = time.monotonic()


def _start_watchdog() -> None:
    # 默认关闭：早先以为是 SSL 挂死才加 watchdog，实际是 MinerU 限速排队
    # （连接存活、服务端慢慢放行），watchdog 会误杀正常排队。仅在显式设置
    # MINERU_WATCHDOG_SEC>0 时启用，作为真·挂死的兜底。
    try:
        limit = float(os.environ.get("MINERU_WATCHDOG_SEC") or "0")
    except ValueError:
        limit = 0.0
    if limit <= 0:
        return
    _mark_progress()

    def _watch() -> None:
        while True:
            time.sleep(15)
            idle = time.monotonic() - _LAST_PROGRESS[0]
            if idle > limit:
                print(
                    f"\n[watchdog] {idle:.0f}s 无进展（疑似 SSL/下载挂死），"
                    f"强制退出让外层重启续跑。",
                    file=sys.stderr, flush=True,
                )
                os._exit(2)

    t = threading.Thread(target=_watch, daemon=True, name="mineru-watchdog")
    t.start()


BASE = "https://mineru.net"
FILE_URLS_BATCH = f"{BASE}/api/v4/file-urls/batch"
EXTRACT_RESULTS_BATCH = f"{BASE}/api/v4/extract-results/batch"


def _load_dotenv_if_present() -> None:
    """加载项目根目录 ``environment``（dotenv 兼容语法；不覆盖已存在的环境变量）。

    部分系统对以 ``.`` 开头的 ``.env`` 有限制，故统一使用无点文件名 ``environment``。
    """
    from main.langchain_env import langchain_load_dotenv_if_present

    langchain_load_dotenv_if_present()


SUPPORTED_EXT = frozenset(
    {
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "jp2",
        "webp",
        "gif",
        "bmp",
        "doc",
        "docx",
        "ppt",
        "pptx",
        "html",
        "htm",
    }
)


def _token() -> str:
    t = (os.environ.get("MINERU_TOKEN") or os.environ.get("MINERU_API_TOKEN") or "").strip()
    if not t:
        print(
            "错误：请设置环境变量 MINERU_TOKEN 或 MINERU_API_TOKEN。",
            file=sys.stderr,
        )
        sys.exit(2)
    return t


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }


def _safe_stem(name: str) -> str:
    """用于输出文件名的 stem：保留可读性，去掉路径不安全字符。"""
    base = Path(name).stem
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    s = s.strip(" .")
    return s or "document"


def _truncate_bytes(s: str, max_bytes: int) -> str:
    """按 UTF-8 字节上限安全截断（不切断多字节字符）。

    MinerU data_id 上限按字节计；中文名 [:128] 字符截断会超 128 字节致整批失败。
    """
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    return encoded[:max_bytes].decode("utf-8", "ignore")


def _unique_output_stem(p: Path, used: set[str]) -> str:
    """同一目录下 stem 冲突时追加短 hash（基于完整文件名）。"""
    base = _safe_stem(p.name)
    if base not in used:
        used.add(base)
        return base
    h = hashlib.sha256(p.name.encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}_{h}"
    if candidate in used:
        h2 = hashlib.sha256(str(p.resolve()).encode("utf-8")).hexdigest()[:12]
        candidate = f"{base}_{h2}"
    used.add(candidate)
    return candidate


def _model_version_for_path(p: Path, override: str | None) -> str:
    if override:
        return override
    ext = p.suffix.lower().lstrip(".")
    if ext in ("html", "htm"):
        return "MinerU-HTML"
    return "vlm"


def _list_input_files(input_dir: Path) -> list[Path]:
    """列 input_dir 下的待摄入文件（递归含子目录）。

    若设置 ``KMS_PRODUCT_FILES`` env（逗号分隔的标识符清单，由 ``/kms product update``
    传入），仅保留命中的产品桶文件——把测试用例 xlsx / Test Strategy doc 挡在 mineru
    链外，避免污染 features/scenarios/architecture。

    白名单标识符是相对 ``input_dir`` 的 POSIX 路径（顶层文件即 basename），与
    ``kms_classifier.bucketize_orgin_dir`` 产出的 key 对齐。为兼容历史只含 basename
    的白名单，命中时同时接受 rel_key 与 basename。

    隐藏文件 / 隐藏目录 / ``_pdf_splits`` 工作目录由 ``iter_orgin_files`` 统一跳过。
    """
    from main import knowledge_paths as kp

    raw_whitelist = (os.environ.get("KMS_PRODUCT_FILES") or "").strip()
    whitelist = {n.strip() for n in raw_whitelist.split(",") if n.strip()} if raw_whitelist else None
    files: list[Path] = []
    skipped = 0
    for p in kp.iter_orgin_files(input_dir):
        ext = p.suffix.lower().lstrip(".")
        if ext not in SUPPORTED_EXT:
            continue
        if whitelist is not None:
            rel_key = kp.orgin_rel_key(p, input_dir)
            if rel_key not in whitelist and p.name not in whitelist:
                skipped += 1
                continue
        files.append(p)
    if whitelist is not None:
        print(
            f"[KMS_PRODUCT_FILES] whitelist active: {len(files)} kept, {skipped} skipped "
            f"(non-product files filtered before mineru upload)",
            flush=True,
        )
    return files



MINERU_PDF_PAGE_LIMIT = 200


def _split_pdf_pikepdf(src: Path, ranges: list[tuple[int, int]], names: list[Path]) -> bool:
    """用 pikepdf(qpdf C++ 后端) 切分，对大型复杂 PDF 比 pypdf 快几个数量级。

    pypdf 的 PdfWriter.add_page 对超大 PDF(>600 页)是累积式深拷贝，单 part 可耗时数分钟
    甚至挂起；pikepdf 同样操作仅毫秒级。成功返回 True，不可用/失败返回 False（让调用方回退）。
    """
    try:
        import pikepdf  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return False
    try:
        with pikepdf.open(str(src)) as pdf:
            for (start, end), out_path in zip(ranges, names, strict=True):
                if out_path.is_file() and out_path.stat().st_size > 0:
                    continue
                out = pikepdf.new()
                for i in range(start, end):
                    out.pages.append(pdf.pages[i])
                # 先写临时文件再原子改名，避免中断留下 0 字节半成品被后续误当成已完成。
                tmp = out_path.with_suffix(".pdf.part")
                out.save(str(tmp))
                out.close()
                tmp.replace(out_path)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ! pikepdf 切分失败，回退 pypdf {src.name}: {exc}", file=sys.stderr)
        return False


def _split_large_pdf_if_needed(p: Path, work_dir: Path, limit: int = MINERU_PDF_PAGE_LIMIT) -> list[Path]:
    """若 PDF 页数超 limit 则按 limit 切成 parts 落到 work_dir，否则原样返回。

    输出文件名 ``<stem>__part<N>_pSTART-END.pdf``，便于 _safe_stem 后产出独立 stem，
    下游清洗 / trunk / 索引按 part 各自成档（不强制合并，避免 mineru.code_format 跨文件合并复杂度）。

    切分优先用 pikepdf(qpdf)，不可用时回退 pypdf。非 PDF 一律原样返回。
    失败时也原样返回（让 MinerU 自己再失败一次便于诊断）。
    """
    if p.suffix.lower() != ".pdf":
        return [p]
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"  ! pypdf 不可用，跳过切分 {p.name}: {exc}", file=sys.stderr)
        return [p]
    try:
        reader = PdfReader(str(p))
        n = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 无法读取 PDF 页数，跳过切分 {p.name}: {exc}", file=sys.stderr)
        return [p]
    if n <= limit:
        return [p]
    work_dir.mkdir(parents=True, exist_ok=True)
    base = _safe_stem(p.name)
    ranges: list[tuple[int, int]] = []
    parts: list[Path] = []
    for start in range(0, n, limit):
        end = min(start + limit, n)
        ranges.append((start, end))
        idx = len(ranges)
        parts.append(work_dir / f"{base}__part{idx}_p{start + 1}-{end}.pdf")

    # 优先 pikepdf；失败回退 pypdf（同样跳过已存在的非空 part）。
    if not _split_pdf_pikepdf(p, ranges, parts):
        for (start, end), out_path in zip(ranges, parts, strict=True):
            if out_path.is_file() and out_path.stat().st_size > 0:
                continue
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            tmp = out_path.with_suffix(".pdf.part")
            with tmp.open("wb") as fh:
                writer.write(fh)
            tmp.replace(out_path)
    print(f"  ✓ 切分 {p.name} ({n} 页) → {len(parts)} parts (limit={limit})")
    return parts


def _expand_input_with_pdf_split(file_paths: list[Path], work_dir: Path) -> list[Path]:
    """对超 200 页 PDF 自动切分；返回展开后的 file_paths。"""
    expanded: list[Path] = []
    for p in file_paths:
        parts = _split_large_pdf_if_needed(p, work_dir)
        expanded.extend(parts)
    return expanded


def _large_pdf_parts_all_cached(p: Path, output_dir: Path, limit: int = MINERU_PDF_PAGE_LIMIT) -> bool:
    """大 PDF（>limit 页）的全部切分 part zip 是否都已存在。

    用于缓存判定：原始大 PDF 的内容 hash 从不入 index（只记 part），导致原始 PDF 永远
    cache-miss → 被当 fresh → 重新切分 + 从 part zip 重新出 markdown，**覆盖已人工修订的
    markdown**（如 cli/app 手册）。本函数让「parts 已全部转好」的大 PDF 被识别为已缓存而跳过。
    """
    if p.suffix.lower() != ".pdf":
        return False
    try:
        from pypdf import PdfReader  # noqa: PLC0415
        n = len(PdfReader(str(p)).pages)
    except Exception:  # noqa: BLE001
        return False
    if n <= limit:
        return False
    base = _safe_stem(p.name)
    for start in range(0, n, limit):
        end = min(start + limit, n)
        idx = start // limit + 1
        part_stem = f"{base}__part{idx}_p{start + 1}-{end}"
        if not (output_dir / f"{part_stem}.mineru.zip").exists():
            return False
    return True


def _post_batch(
    session: requests.Session,
    token: str,
    file_paths: list[Path],
    effective_mv: str,
    language: str,
    enable_formula: bool,
    enable_table: bool,
    is_ocr: bool,
) -> tuple[str, list[str]]:
    """返回 (batch_id, 与 files 顺序一致的 file_urls 用于 PUT)。"""
    files_payload: list[dict[str, Any]] = []
    for p in file_paths:
        item: dict[str, Any] = {
            "name": p.name,
            # data_id 上限是 128 **字节**（非字符）；中文名 UTF-8 每字按 3 字节，
            # [:128] 字符截断会超限（曾致整批提交失败 code -10002）。按字节安全截断。
            "data_id": _truncate_bytes(_safe_stem(p.name), 128),
        }
        if effective_mv in ("pipeline", "vlm"):
            item["is_ocr"] = is_ocr
        files_payload.append(item)

    body: dict[str, Any] = {
        "files": files_payload,
        "model_version": effective_mv,
        "language": language,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }

    r = session.post(FILE_URLS_BATCH, headers=_headers(token), json=body, timeout=120)

    # MinerU 限流较激进，单纯 3 次短退避不够。用更多次、更长的退避（可经
    # MINERU_429_BACKOFFS 配置，逗号分隔秒数），覆盖持续限流窗口。
    backoffs_raw = (os.environ.get("MINERU_429_BACKOFFS") or "15,30,60,120,120,180").strip()
    try:
        backoffs = [int(x) for x in backoffs_raw.split(",") if x.strip()]
    except ValueError:
        backoffs = [15, 30, 60, 120, 120, 180]
    if r.status_code == 429:
        for wait in backoffs:
            print(f"  ⏳ 429 限流，等待 {wait}s 后重试…", flush=True)
            time.sleep(wait)
            r = session.post(FILE_URLS_BATCH, headers=_headers(token), json=body, timeout=120)
            if r.status_code != 429:
                break
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"file-urls/batch 失败: {data}")
    batch_id = data["data"]["batch_id"]
    urls = data["data"]["file_urls"]
    if len(urls) != len(file_paths):
        raise RuntimeError("返回的上传 URL 数量与文件数不一致")
    return batch_id, urls


def _upload_files(
    session: requests.Session,
    file_paths: list[Path],
    upload_urls: list[str],
) -> None:
    for p, url in zip(file_paths, upload_urls, strict=True):
        data = p.read_bytes()
        
        req = requests.Request("PUT", url, data=data)
        prep = session.prepare_request(req)
        prep.headers.pop("Content-Type", None)
        put = session.send(prep, timeout=600)
        if put.status_code not in (200, 201, 204):
            raise RuntimeError(f"上传失败 {p.name}: HTTP {put.status_code} {put.text[:500]}")


def _poll_batch(
    session: requests.Session,
    token: str,
    batch_id: str,
    poll_interval: float,
    max_wait_sec: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max_wait_sec
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        r = _http_get_with_retry(
            session,
            f"{EXTRACT_RESULTS_BATCH}/{batch_id}",
            headers=_headers(token),
            read_timeout=60.0,
            max_retries=3,
        )
        last = r.json()
        _mark_progress()
        if last.get("code") != 0:
            raise RuntimeError(f"extract-results/batch 错误: {last}")
        results = last.get("data", {}).get("extract_result") or []
        if not results:
            time.sleep(poll_interval)
            continue
        terminal = frozenset({"done", "failed"})
        pending = [x for x in results if x.get("state") not in terminal]
        if not pending:
            return last
        time.sleep(poll_interval)
    raise TimeoutError(f"轮询超时 batch_id={batch_id}，最后响应: {json.dumps(last, ensure_ascii=False)[:2000]}")


def _poll_batch_stream(
    session: requests.Session,
    token: str,
    batch_id: str,
    poll_interval: float,
    max_wait_sec: float,
):
    """Generator: 每轮查 extract-results/batch，把**新变成 terminal** 的文件逐条 yield。

    yield 的是单个 ``extract_result`` 条目（含 ``file_name``、``state``、``full_zip_url``）。
    所有文件都终态或超时后退出。
    """
    deadline = time.monotonic() + max_wait_sec
    terminal = frozenset({"done", "failed"})
    seen: set[str] = set()
    last: dict[str, Any] = {}
    total_known: int | None = None
    while time.monotonic() < deadline:
        r = _http_get_with_retry(
            session,
            f"{EXTRACT_RESULTS_BATCH}/{batch_id}",
            headers=_headers(token),
            read_timeout=60.0,
            max_retries=3,
        )
        last = r.json()
        _mark_progress()
        if last.get("code") != 0:
            raise RuntimeError(f"extract-results/batch 错误: {last}")
        results = last.get("data", {}).get("extract_result") or []
        if results and total_known is None:
            total_known = len(results)

        newly_done: list[dict[str, Any]] = []
        for info in results:
            key = info.get("file_name") or ""
            if not key or key in seen:
                continue
            if info.get("state") in terminal:
                seen.add(key)
                newly_done.append(info)
        for info in newly_done:
            yield info

        if total_known is not None and len(seen) >= total_known:
            return
        if not results:
            time.sleep(poll_interval)
            continue
        pending = [x for x in results if x.get("state") not in terminal]
        if not pending:
            return
        time.sleep(poll_interval)
    raise TimeoutError(
        f"轮询超时 batch_id={batch_id}，最后响应: "
        f"{json.dumps(last, ensure_ascii=False)[:2000]}"
    )


def _http_get_with_retry(
    session: requests.Session,
    url: str,
    *,
    headers: dict | None = None,
    connect_timeout: float = 30.0,
    read_timeout: float = 120.0,
    max_retries: int = 4,
    stream: bool = False,
) -> requests.Response:
    """带 (connect, read) 双超时 + 指数退避重试的 GET。

    根治"连接已建立但服务端慢速/挂起"导致的无限阻塞：requests 的 read_timeout
    限制两次数据块之间的最大间隔，超时即抛 → 外层重试换新连接。
    之前用单一 timeout=600 在某些网络栈状态下不生效，曾导致进程挂死 90+ 分钟。
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = session.get(
                url,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
                stream=stream,
            )
            r.raise_for_status()
            return r
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                socket.timeout,
                OSError) as e:
            last_exc = e
            wait = min(2 ** attempt * 5, 60)
            print(f"  ⏳ GET 超时/中断(第{attempt+1}次)，{wait}s 后重试: {type(e).__name__}",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
    raise last_exc if last_exc else RuntimeError(f"GET 失败: {url}")


def _download_zip(url: str) -> bytes:
    """下载 zip。每次用**独立** requests.Session——requests.Session 非线程安全，
    多个下载线程共享同一 session 会在连接池争用时死锁（曾导致整批下载线程全部挂死、
    CPU 0%、无网络连接、且 timeout 不触发）。download URL 是预签名的，无需复用连接。"""
    with requests.Session() as s:
        # read_timeout=180s（两块数据间隔上限），整体可重试 4 次。
        r = _http_get_with_retry(s, url, read_timeout=180.0, max_retries=4)
        return r.content


def _find_in_zip(z: zipfile.ZipFile, predicate) -> str | None:
    for name in z.namelist():
        if predicate(name):
            return name
    return None


def _read_zip_text(z: zipfile.ZipFile, member: str) -> str:
    with z.open(member) as f:
        return f.read().decode("utf-8", errors="replace")


def _read_zip_json(z: zipfile.ZipFile, member: str) -> Any:
    raw = z.read(member)
    return json.loads(raw.decode("utf-8"))


def _is_structural_json_member(name: str) -> bool:
    """已在 markdown / content_list / model / middle 中体现的 zip 成员，不再 base64 嵌入。"""
    bn = Path(name).name
    if bn == "full.md" or name.endswith("/full.md"):
        return True
    if bn == "content_list_v2.json":
        return True
    if bn.endswith("_content_list.json"):
        return True
    if bn.endswith("_model.json") or "_model.json" in name:
        return True
    if bn == "layout.json" or name.endswith("/layout.json"):
        return True
    if "_middle.json" in name or bn.endswith("middle.json"):
        return True
    return False


def _extract_outputs_from_zip(
    zip_bytes: bytes,
    *,
    embed_binary_in_json: bool,
    embed_max_bytes_per_file: int | None,
) -> dict[str, Any]:
    """
    从 MinerU 返回的 zip 解析文本/JSON，并可选将 zip 内其余二进制（images/、*_origin.pdf 等）
    以 base64 写入 embedded_binary，便于仅凭 JSON 还原 Markdown 引用的资源与 MinerU 提供的 origin 副本。
    """
    warnings: list[str] = []
    md: str | None = None
    content_list: Any | None = None
    content_list_v2: Any | None = None
    model: Any | None = None
    middle: Any | None = None
    embedded_binary: dict[str, str] = {}
    embedded_binary_omitted: list[dict[str, Any]] = []
    zip_inventory: list[dict[str, Any]] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            raw = z.read(name)
            digest = hashlib.sha256(raw).hexdigest()
            zip_inventory.append(
                {
                    "path": name,
                    "size_bytes": len(raw),
                    "sha256": digest,
                }
            )

        md_name = _find_in_zip(z, lambda n: n.endswith("full.md") or n == "full.md")
        if md_name:
            md = _read_zip_text(z, md_name)
        else:
            warnings.append("zip 中未找到 full.md")

        cl = _find_in_zip(z, lambda n: str(n).endswith("_content_list.json"))
        if cl:
            try:
                content_list = _read_zip_json(z, cl)
            except json.JSONDecodeError as e:
                warnings.append(f"content_list JSON 解析失败: {e}")
        else:
            warnings.append("zip 中未找到 *_content_list.json")

        cl2 = _find_in_zip(z, lambda n: str(n).endswith("_content_list_v2.json") or Path(n).name == "content_list_v2.json")
        if cl2:
            try:
                content_list_v2 = _read_zip_json(z, cl2)
            except json.JSONDecodeError as e:
                warnings.append(f"content_list_v2 JSON 解析失败: {e}")

        mj = _find_in_zip(z, lambda n: "_model.json" in n or str(n).endswith("_model.json"))
        if mj:
            try:
                model = _read_zip_json(z, mj)
            except json.JSONDecodeError as e:
                warnings.append(f"model JSON 解析失败: {e}")
        else:
            warnings.append("zip 中未找到 _model.json")

        mid = _find_in_zip(
            z,
            lambda n: "_middle.json" in n
            or Path(n).name == "layout.json"
            or str(n).endswith("middle.json"),
        )
        if mid:
            try:
                middle = _read_zip_json(z, mid)
            except json.JSONDecodeError as e:
                warnings.append(f"middle/layout JSON 解析失败: {e}")
        else:
            warnings.append("zip 中未找到 middle/layout json")

        if embed_binary_in_json:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if _is_structural_json_member(name):
                    continue
                raw = z.read(name)
                if embed_max_bytes_per_file is not None and len(raw) > embed_max_bytes_per_file:
                    embedded_binary_omitted.append(
                        {
                            "path": name,
                            "size_bytes": len(raw),
                            "reason": f"超过 embed_max_bytes_per_file ({embed_max_bytes_per_file})",
                        }
                    )
                    warnings.append(f"未嵌入过大文件（仅用 sidecar zip 保留）: {name} ({len(raw)} bytes)")
                    continue
                embedded_binary[name] = base64.b64encode(raw).decode("ascii")

    return {
        "markdown": md,
        "content_list": content_list,
        "content_list_v2": content_list_v2,
        "model": model,
        "middle": middle,
        "zip_inventory": zip_inventory,
        "embedded_binary": embedded_binary if embed_binary_in_json else {},
        "embedded_binary_omitted": embedded_binary_omitted,
        "warnings_extra": warnings,
    }


@dataclass
class FileOutcome:
    source: str
    stem: str
    state: str
    err_msg: str = ""
    full_zip_url: str | None = None
    mineru_zip_path: str | None = None
    code_format_path: str | None = None
    raw_data_path: str | None = None
    markdown_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    source_sha256: str | None = None  # 解析成功后回填，供主线程登记内容寻址索引


def _is_success(outcome: FileOutcome) -> bool:
    """``done`` + JSON，或 ``cached`` + markdown 直出，均视为成功。"""
    if outcome.state == "done" and outcome.code_format_path:
        return True
    return outcome.state == "cached" and bool(outcome.markdown_path)


def _mineru_batch_size() -> int:
    raw = (os.environ.get("MINERU_BATCH_SIZE") or "30").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 30
    return max(1, n)


def _chunk_paths(paths: list[Path], size: int) -> list[list[Path]]:
    return [paths[i : i + size] for i in range(0, len(paths), size)]


def _should_exit_error(outcomes: list[FileOutcome]) -> bool:
    if not outcomes:
        return True
    ok = sum(1 for o in outcomes if _is_success(o))
    failed = sum(1 for o in outcomes if o.state in ("failed", "error"))
    return ok == 0 or failed > 0


def _resolve_markdown_dir() -> Path | None:
    """KMS_OUTPUT_BUCKET=product|qa 时返回对应 markdown 子目录，否则 None。

    由 ``/kms product update`` / ``/kms qa update`` 设置。其他直接调用本模块的入口
    （比如手动 CLI）不传 env，markdown 落地步骤跳过。
    """
    bucket = (os.environ.get("KMS_OUTPUT_BUCKET") or "").strip().lower()
    if bucket not in {"product", "qa"}:
        return None
    from main import knowledge_paths as kp
    target = kp.KNOWLEDGE_MARKDOWN_PRODUCT if bucket == "product" else kp.KNOWLEDGE_MARKDOWN_QA
    target.mkdir(parents=True, exist_ok=True)
    return target


def _backfill_source_index(
    index: SourceIndex, file_paths: list[Path], output_dir: Path
) -> int:
    """首次升级时把已存在的 ``{stem}.mineru.zip`` 按源内容 hash 灌进索引（纯本地，零 API）。

    没有这步，升级后索引为空会导致全部文件 cache-miss → 数百次 API 调用爆炸。
    只补「索引里没有、但磁盘上 zip 已存在」的条目；已在索引里的跳过。返回回填条数。
    """
    filled = 0
    for p in file_paths:
        stem = _safe_stem(p.name)
        zipname = f"{stem}.mineru.zip"
        if not (output_dir / zipname).exists():
            continue
        try:
            h = index.source_hash(p)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! backfill 跳过 {p.name}（哈希失败）: {exc}", file=sys.stderr)
            continue
        if index.has_hash(h):
            continue
        index.record(h, stem=stem, zipname=zipname, source_name=p.name)
        filled += 1
    if filled:
        index.save()
        print(f"[source-index] backfilled {filled} existing zip(s) by content hash", flush=True)
    return filled


def _emit_markdown_from_zip(
    zip_path: Path, md_dir: Path | None, stem: str
) -> tuple[str | None, list[str]]:
    """从 cached/复用 zip 里抽 full.md 写到 ``md_dir/{stem}.md``。返回 (md_path|None, warnings)。"""
    warnings: list[str] = []
    with zipfile.ZipFile(zip_path) as z:
        md_name = _find_in_zip(z, lambda n: n.endswith("full.md") or n == "full.md")
        if md_name and md_dir is not None:
            md_text = _read_zip_text(z, md_name)
            md_path = md_dir / f"{stem}.md"
            md_path.write_text(md_text, encoding="utf-8")
            return str(md_path), warnings
        if not md_name:
            warnings.append("cached zip 中未找到 full.md")
    return None, warnings


def main() -> None:
    from main import knowledge_paths as kp

    # 全局 socket 硬超时：最底层保险。requests/urllib3 的 read_timeout 在 macOS 上对
    # "连接存活但服务端静默"的 SSL read 不可靠（曾导致主线程轮询无限挂死、CPU 0%、
    # 1 个 ESTAB 连接冻结不动）。socket 层默认超时让任何 socket 操作（含 SSL read）
    # 超时即抛 socket.timeout，配合 _http_get_with_retry 的重试根治挂死。
    # 可经 MINERU_SOCKET_TIMEOUT 调整（默认 90s，需 > 单次轮询的合理响应时间）。
    try:
        sock_to = float(os.environ.get("MINERU_SOCKET_TIMEOUT") or "90")
    except ValueError:
        sock_to = 90.0
    socket.setdefaulttimeout(sock_to)
    _start_watchdog()

    ap = argparse.ArgumentParser(description="MinerU 精准解析批量导出 JSON")
    ap.add_argument("--input-dir", type=Path, default=kp.KNOWLEDGE_ORGIN,
                    help=f"源文件目录（默认 {kp.KNOWLEDGE_ORGIN}）")
    ap.add_argument("--output-dir", type=Path, default=kp.KNOWLEDGE_MINERU,
                    help=f"MinerU 解析输出目录（默认 {kp.KNOWLEDGE_MINERU}）")
    ap.add_argument(
        "--model-version",
        default="auto",
        help="vlm|pipeline|MinerU-HTML|auto（按首个文件推断，html 用 MinerU-HTML）",
    )
    ap.add_argument("--language", default="ch")
    ap.add_argument("--enable-formula", action="store_true", default=True)
    ap.add_argument("--no-enable-formula", action="store_false", dest="enable_formula")
    ap.add_argument("--enable-table", action="store_true", default=True)
    ap.add_argument("--no-enable-table", action="store_false", dest="enable_table")
    ap.add_argument("--is-ocr", action="store_true", default=False)
    ap.add_argument("--poll-interval-sec", type=float, default=5.0)
    ap.add_argument("--max-wait-min", type=float, default=120.0)
    ap.add_argument(
        "--save-mineru-zip",
        action="store_true",
        default=True,
        help="将 MinerU 返回的原始 zip 另存为 {stem}.mineru.zip，便于无损还原包内全部文件",
    )
    ap.add_argument(
        "--no-save-mineru-zip",
        action="store_false",
        dest="save_mineru_zip",
    )
    ap.add_argument(
        "--embed-binary-in-json",
        action="store_true",
        default=True,
        help="将 zip 内非结构化 JSON/Markdown 的成员（images/、*_origin.pdf 等）以 base64 写入 embedded_binary",
    )
    ap.add_argument(
        "--no-embed-binary-in-json",
        action="store_false",
        dest="embed_binary_in_json",
    )
    ap.add_argument(
        "--embed-max-mb-per-file",
        type=float,
        default=80.0,
        help="单文件超过该大小时不嵌入 JSON（仍保存在 .mineru.zip）；0 表示不限制",
    )
    args = ap.parse_args()
    _load_dotenv_if_present()

    token = _token()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    embed_max: int | None
    if args.embed_max_mb_per_file and args.embed_max_mb_per_file > 0:
        embed_max = int(args.embed_max_mb_per_file * 1024 * 1024)
    else:
        embed_max = None

    file_paths = _list_input_files(input_dir)
    if not file_paths:
        print(f"未在 {input_dir} 找到支持的文件。", file=sys.stderr)
        sys.exit(1)

    used_stems: set[str] = set()
    all_outcomes: list[FileOutcome] = []

    # 内容寻址缓存：命中键 = 源文件内容 sha256，而非文件名。
    # 首次升级先 backfill 已有 zip，避免索引为空导致全量重解析。
    source_index = SourceIndex.load(input_dir, output_dir)
    _backfill_source_index(source_index, file_paths, output_dir)

    md_dir = _resolve_markdown_dir()
    cached_paths: list[Path] = []
    fresh_paths: list[Path] = []
    # 记录每个命中文件复用的 zip 路径（按内容 hash 查到，可能与自身 stem 不同名）。
    reuse_zip: dict[str, Path] = {}
    for p in file_paths:
        try:
            h = source_index.source_hash(p)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 源哈希失败，按 fresh 处理 {p.name}: {exc}", file=sys.stderr)
            fresh_paths.append(p)
            continue
        entry = source_index.lookup(h)
        cached_zip = output_dir / entry["zip"] if entry else None
        if entry and cached_zip and cached_zip.exists():
            cached_paths.append(p)
            reuse_zip[str(p)] = cached_zip
        elif _large_pdf_parts_all_cached(p, output_dir):
            # 大 PDF：原始内容 hash 不入 index，但其切分 parts 已全部转好。
            # 跳过（不重切、不从 part zip 重出 markdown），避免覆盖已人工修订的手册 markdown。
            print(f"  [cache·split-parts] {p.name} 的全部切分 part 已转，跳过", flush=True)
        else:
            # 同名 zip 存在但内容 hash 对不上 → 内容已变，重新解析（修正确性）。
            stem_zip = output_dir / f"{_safe_stem(p.name)}.mineru.zip"
            if stem_zip.exists():
                print(
                    f"  ⟳ {p.name} 内容已变（同名 zip 命中失效），将重新解析并覆盖 markdown",
                    flush=True,
                )
            fresh_paths.append(p)
    source_index.save()

    for p in cached_paths:
        stem = _unique_output_stem(p, used_stems)
        zip_path = reuse_zip[str(p)]
        fo = FileOutcome(
            source=p.name,
            stem=stem,
            state="cached",
            mineru_zip_path=str(zip_path),
            code_format_path=str(output_dir / f"{stem}.code_format.json"),
            raw_data_path=str(output_dir / f"{stem}.raw_data.json"),
        )
        try:
            md_path, warns = _emit_markdown_from_zip(zip_path, md_dir, stem)
            fo.markdown_path = md_path
            fo.warnings.extend(warns)
            reused = zip_path.name != f"{_safe_stem(p.name)}.mineru.zip"
            tag = "[cache·reuse]" if reused else "[cache]"
            print(f"  {tag} {p.name} → {fo.markdown_path or '(no markdown_dir env)'}", flush=True)
        except Exception as exc:  # noqa: BLE001
            fo.state = "error"
            fo.err_msg = f"读取 cached zip 失败: {exc}"
        all_outcomes.append(fo)

    if not fresh_paths:
        print(f"全部 {len(cached_paths)} 个文件命中缓存，跳过 MinerU API。", flush=True)
        file_paths = []
    else:
        if cached_paths:
            print(f"{len(cached_paths)} 个命中缓存，{len(fresh_paths)} 个需调 MinerU API。", flush=True)
        file_paths = fresh_paths

    
    pdf_split_dir = input_dir / kp.ORGIN_WORKDIR_NAME
    file_paths = _expand_input_with_pdf_split(file_paths, pdf_split_dir)

    # 每日页数预算：MinerU 限速约 1000 页/天，超出排队（连接存活但久不返回，
    # 曾被误诊为 SSL 挂死）。受控提交——本次只提交累计 ≤ MINERU_PAGE_BUDGET 页的文件，
    # 其余留到次日续跑（zip 缓存 + 内容寻址保证不重复花配额）。0 = 不限。
    try:
        page_budget = int(os.environ.get("MINERU_PAGE_BUDGET") or "0")
    except ValueError:
        page_budget = 0
    if page_budget > 0 and file_paths:
        def _pages_of(p: Path) -> int:
            if p.suffix.lower() != ".pdf":
                return 1
            try:
                from pypdf import PdfReader
                return max(1, len(PdfReader(str(p)).pages))
            except Exception:
                return 1
        # 计算每个文件页数，按页数升序——小页数高价值文档（docx/ppt/小pdf）优先吃配额，
        # 大 PDF 手册（网卡 datasheet/Intel 手册/竞品手册）自然排到后面，分批跑完。
        paged = sorted(((p, _pages_of(p)) for p in file_paths), key=lambda t: t[1])
        kept: list[Path] = []
        acc = 0
        for p, pg in paged:
            if kept and acc + pg > page_budget:
                continue
            kept.append(p)
            acc += pg
        deferred = len(file_paths) - len(kept)
        print(f"[page-budget] 预算 {page_budget} 页：本次提交 {len(kept)} 个文件"
              f"（约 {acc} 页），推迟 {deferred} 个到次日续跑。", flush=True)
        file_paths = kept

    
    def split_by_model_version(paths: list[Path]) -> list[list[Path]]:
        buckets: dict[str, list[Path]] = {}
        for p in paths:
            mv = _model_version_for_path(p, args.model_version if args.model_version != "auto" else None)
            buckets.setdefault(mv, []).append(p)
        return list(buckets.values())

    batches = split_by_model_version(file_paths)
    batch_size = _mineru_batch_size()
    session = requests.Session()

    for group in batches:
        mv_arg = args.model_version
        
        effective_mv = _model_version_for_path(group[0], mv_arg if mv_arg != "auto" else None)
        chunks = _chunk_paths(group, batch_size)
        n_chunks = len(chunks)

        for chunk_idx, chunk in enumerate(chunks, start=1):
            # 批间节流：默认 8s，可经 MINERU_BATCH_INTERVAL_SEC 调大以缓解 429。
            if chunk_idx > 1:
                try:
                    iv = float(os.environ.get("MINERU_BATCH_INTERVAL_SEC") or "8")
                except ValueError:
                    iv = 8.0
                time.sleep(max(0.0, iv))
            print(
                f"[batch {chunk_idx}/{n_chunks}] 提交 {len(chunk)} 个文件，"
                f"model_version={effective_mv}",
                flush=True,
            )

            # 提交+上传失败（如 429 退避耗尽）不再让整个进程崩溃：记录该批为 error，
            # 继续下一批。已成功批次与 zip/markdown 缓存全部保留，下次断点续跑可补。
            try:
                batch_id, upload_urls = _post_batch(
                    session,
                    token,
                    chunk,
                    effective_mv=effective_mv,
                    language=args.language,
                    enable_formula=args.enable_formula,
                    enable_table=args.enable_table,
                    is_ocr=args.is_ocr,
                )
                print(f"batch_id={batch_id}，开始上传…", flush=True)
                _upload_files(session, chunk, upload_urls)
                print("上传完成，轮询解析结果…", flush=True)
            except Exception as submit_exc:  # noqa: BLE001
                print(
                    f"[batch {chunk_idx}/{n_chunks}] 提交/上传失败，跳过本批继续: "
                    f"{type(submit_exc).__name__}: {submit_exc}",
                    file=sys.stderr,
                    flush=True,
                )
                for p in chunk:
                    all_outcomes.append(
                        FileOutcome(
                            source=p.name,
                            stem=_unique_output_stem(p, used_stems),
                            state="error",
                            err_msg=f"batch submit failed: {submit_exc}",
                        )
                    )
                continue

            
            by_source_name = {p.name: p for p in chunk}
            download_workers = max(
                1, int(os.environ.get("MINERU_DOWNLOAD_WORKERS", "4"))
            )
            outcomes_lock = threading.Lock()
            batch_outcomes: list[FileOutcome] = []

            def _finalize(info: dict[str, Any]) -> FileOutcome:
                file_name = info.get("file_name") or ""
                p = by_source_name.get(file_name)
                if p is None:
                    return FileOutcome(
                        source=file_name,
                        stem=file_name,
                        state="error",
                        err_msg="file_name 不在本批次",
                    )
                stem = _unique_output_stem(p, used_stems)
                state = info.get("state") or "unknown"
                err_msg = info.get("err_msg") or ""
                fo = FileOutcome(
                    source=p.name,
                    stem=stem,
                    state=state,
                    err_msg=err_msg,
                    full_zip_url=info.get("full_zip_url"),
                )
                if state != "done" or not fo.full_zip_url:
                    return fo
                try:
                    zb = _download_zip(fo.full_zip_url)
                    pack = _extract_outputs_from_zip(
                        zb,
                        embed_binary_in_json=args.embed_binary_in_json,
                        embed_max_bytes_per_file=embed_max,
                    )
                    fo.warnings.extend(pack.get("warnings_extra") or [])

                    zip_sha256 = hashlib.sha256(zb).hexdigest()
                    mineru_zip_name = f"{stem}.mineru.zip"
                    mineru_zip_path = output_dir / mineru_zip_name
                    if args.save_mineru_zip:
                        mineru_zip_path.write_bytes(zb)
                        fo.mineru_zip_path = str(mineru_zip_path)
                        # 回填源内容 hash（主线程已在 by_path 快表里算过，这里命中快表零开销），
                        # 供主线程把 {hash → zip} 登记进内容寻址索引。
                        try:
                            fo.source_sha256 = source_index.source_hash(p)
                        except Exception:  # noqa: BLE001
                            fo.source_sha256 = None

                    code_obj = {
                        "source_file": p.name,
                        "mineru_model_version": effective_mv,
                        "task_meta": {
                            "file_name": info.get("file_name"),
                            "data_id": info.get("data_id"),
                            "batch_id": batch_id,
                            "full_zip_url": fo.full_zip_url,
                        },
                        "markdown": pack.get("markdown"),
                        "content_list": pack.get("content_list"),
                        "content_list_v2": pack.get("content_list_v2"),
                        "zip_inventory": pack.get("zip_inventory"),
                        "mineru_output_archive": {
                            "file": mineru_zip_name if args.save_mineru_zip else None,
                            "sha256": zip_sha256,
                            "size_bytes": len(zb),
                            "saved_locally": bool(args.save_mineru_zip),
                        },
                        "embedded_binary": pack.get("embedded_binary"),
                        "embedded_binary_omitted": pack.get("embedded_binary_omitted"),
                        "restore_note": (
                            "语义与版式以 MinerU 解析为准。embedded_binary 含 Markdown 引用的图片及 zip 内其余非 JSON 成员；"
                            "与 content_list / model / middle 共同可还原 MinerU 输出。原始 Office/PDF 二进制亦见 zip 内 *_origin.pdf（若存在）。"
                        ),
                        "warnings": fo.warnings,
                    }
                    raw_obj = {
                        "source_file": p.name,
                        "mineru_model_version": effective_mv,
                        "model": pack.get("model"),
                        "middle": pack.get("middle"),
                        "zip_inventory": pack.get("zip_inventory"),
                        "mineru_output_archive": code_obj["mineru_output_archive"],
                        "warnings": fo.warnings,
                    }

                    code_path = output_dir / f"{stem}.code_format.json"
                    raw_path = output_dir / f"{stem}.raw_data.json"
                    code_path.write_text(
                        json.dumps(code_obj, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    raw_path.write_text(
                        json.dumps(raw_obj, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    fo.code_format_path = str(code_path)
                    fo.raw_data_path = str(raw_path)

                    md_text = pack.get("markdown")
                    md_dir = _resolve_markdown_dir()
                    if md_dir is not None and md_text:
                        md_path = md_dir / f"{stem}.md"
                        md_path.write_text(str(md_text), encoding="utf-8")
                        fo.markdown_path = str(md_path)
                except Exception as e:  # noqa: BLE001
                    fo.state = "error"
                    fo.err_msg = str(e)
                return fo

            try:
                with ThreadPoolExecutor(max_workers=download_workers) as pool:
                    futures = []
                    fut_to_info = {}
                    for info in _poll_batch_stream(
                        session,
                        token,
                        batch_id,
                        poll_interval=args.poll_interval_sec,
                        max_wait_sec=args.max_wait_min * 60,
                    ):
                        print(
                            f"  → {info.get('file_name')} {info.get('state')}，下发下载",
                            flush=True,
                        )
                        _mark_progress()
                        f = pool.submit(_finalize, info)
                        futures.append(f)
                        fut_to_info[f] = info
                    # as_completed 整体超时兜底：_finalize 内部下载已有重试(≈十几分钟封顶)，
                    # 这里给一个宽松上限防止极端情况下主线程永久等待挂死(曾发生过)。
                    dl_deadline = max(600, len(futures) * 120)
                    try:
                        for fut in as_completed(futures, timeout=dl_deadline):
                            fo = fut.result()
                            with outcomes_lock:
                                batch_outcomes.append(fo)
                                _mark_progress()
                                if fo.code_format_path:
                                    print(
                                        f"  ✓ {fo.source} -> {Path(fo.code_format_path).name}",
                                        flush=True,
                                    )
                                elif fo.state == "failed":
                                    print(f"  ✗ {fo.source}: {fo.err_msg}", flush=True)
                    except TimeoutError:
                        done_srcs = {o.source for o in batch_outcomes}
                        for f, info in fut_to_info.items():
                            fn = info.get("file_name") or "?"
                            if fn not in done_srcs:
                                print(f"  ⏱ 下载超时未完成，记为 error: {fn}",
                                      file=sys.stderr, flush=True)
                                batch_outcomes.append(FileOutcome(
                                    source=fn, stem=_safe_stem(fn),
                                    state="error", err_msg="download timeout"))
            except Exception as e:
                for p in chunk:
                    if not any(o.source == p.name for o in batch_outcomes):
                        batch_outcomes.append(
                            FileOutcome(
                                source=p.name,
                                stem=_unique_output_stem(p, used_stems),
                                state="error",
                                err_msg=str(e),
                            )
                        )

            all_outcomes.extend(batch_outcomes)
            # 主线程登记本批新解析的「源内容 hash → zip」（_finalize 在子线程只回填 hash，
            # 不碰非线程安全的索引）。同名改内容会通过 record() 清掉旧悬空条目。
            recorded = 0
            for o in batch_outcomes:
                if o.state == "done" and o.source_sha256 and o.mineru_zip_path:
                    source_index.record(
                        o.source_sha256,
                        stem=o.stem,
                        zipname=Path(o.mineru_zip_path).name,
                        source_name=o.source,
                    )
                    recorded += 1
            if recorded:
                source_index.save()
            print(
                f"[batch {chunk_idx}/{n_chunks}] 完成，本批 {len(batch_outcomes)} 个结果",
                flush=True,
            )

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "files": [
            {
                "source": o.source,
                "stem": o.stem,
                "state": o.state,
                "err_msg": o.err_msg,
                "full_zip_url": o.full_zip_url,
                "mineru_zip": o.mineru_zip_path,
                "code_format": o.code_format_path,
                "raw_data": o.raw_data_path,
                "markdown": o.markdown_path,
                "warnings": o.warnings,
            }
            for o in all_outcomes
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ok = sum(1 for o in all_outcomes if _is_success(o))
    failed = sum(1 for o in all_outcomes if o.state in ("failed", "error"))
    print(
        f"完成：成功 {ok}/{len(all_outcomes)}（含 cached 直出 md），"
        f"失败 {failed}，manifest: {output_dir / 'manifest.json'}",
        flush=True,
    )
    if _should_exit_error(all_outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()
