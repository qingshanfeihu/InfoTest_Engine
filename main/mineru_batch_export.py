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
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

BASE = "https://mineru.net"
FILE_URLS_BATCH = f"{BASE}/api/v4/file-urls/batch"
EXTRACT_RESULTS_BATCH = f"{BASE}/api/v4/extract-results/batch"

# 精准解析支持的扩展名（小写，不含点）
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
    """列 input_dir 下的待摄入文件。

    若设置 ``KMS_PRODUCT_FILES`` env（逗号分隔的文件名清单，由 ``/kms product update``
    传入），仅保留命中的产品桶文件——把测试用例 xlsx / Test Strategy doc 挡在 mineru
    链外，避免污染 features/scenarios/architecture。
    """
    raw_whitelist = (os.environ.get("KMS_PRODUCT_FILES") or "").strip()
    whitelist = {n.strip() for n in raw_whitelist.split(",") if n.strip()} if raw_whitelist else None
    files: list[Path] = []
    skipped = 0
    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        ext = p.suffix.lower().lstrip(".")
        if ext not in SUPPORTED_EXT:
            continue
        if whitelist is not None and p.name not in whitelist:
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


# MinerU 单 PDF 上限 200 页；超出则自动切分成 parts 后并入批次
MINERU_PDF_PAGE_LIMIT = 200


def _split_large_pdf_if_needed(p: Path, work_dir: Path, limit: int = MINERU_PDF_PAGE_LIMIT) -> list[Path]:
    """若 PDF 页数超 limit 则按 limit 切成 parts 落到 work_dir，否则原样返回。

    输出文件名 ``<stem>__part<N>_pSTART-END.pdf``，便于 _safe_stem 后产出独立 stem，
    下游清洗 / trunk / 索引按 part 各自成档（不强制合并，避免 mineru.code_format 跨文件合并复杂度）。

    非 PDF 一律原样返回。失败时也原样返回（让 MinerU 自己再失败一次便于诊断）。
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
    parts: list[Path] = []
    idx = 0
    for start in range(0, n, limit):
        end = min(start + limit, n)
        idx += 1
        out_name = f"{base}__part{idx}_p{start + 1}-{end}.pdf"
        out_path = work_dir / out_name
        if not out_path.is_file():
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            with out_path.open("wb") as fh:
                writer.write(fh)
        parts.append(out_path)
    print(f"  ✓ 切分 {p.name} ({n} 页) → {len(parts)} parts (limit={limit})")
    return parts


def _expand_input_with_pdf_split(file_paths: list[Path], work_dir: Path) -> list[Path]:
    """对超 200 页 PDF 自动切分；返回展开后的 file_paths。"""
    expanded: list[Path] = []
    for p in file_paths:
        parts = _split_large_pdf_if_needed(p, work_dir)
        expanded.extend(parts)
    return expanded


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
            "data_id": _safe_stem(p.name)[:128],
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
        # 文档：上传时不要设置 Content-Type；requests 默认可能带 octet-stream，需去掉以匹配预签名
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
        r = session.get(
            f"{EXTRACT_RESULTS_BATCH}/{batch_id}",
            headers=_headers(token),
            timeout=120,
        )
        r.raise_for_status()
        last = r.json()
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
        r = session.get(
            f"{EXTRACT_RESULTS_BATCH}/{batch_id}",
            headers=_headers(token),
            timeout=120,
        )
        r.raise_for_status()
        last = r.json()
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


def _download_zip(session: requests.Session, url: str) -> bytes:
    r = session.get(url, timeout=600)
    r.raise_for_status()
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


def main() -> None:
    from main import knowledge_paths as kp
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

    # 缓存跳过：{stem}.mineru.zip 已存在则不调 MinerU API，仅从 zip 解 full.md
    md_dir = _resolve_markdown_dir()
    cached_paths: list[Path] = []
    fresh_paths: list[Path] = []
    for p in file_paths:
        stem = _safe_stem(p.name)
        zip_path = output_dir / f"{stem}.mineru.zip"
        if zip_path.exists():
            cached_paths.append(p)
        else:
            fresh_paths.append(p)

    for p in cached_paths:
        stem = _unique_output_stem(p, used_stems)
        zip_path = output_dir / f"{stem}.mineru.zip"
        fo = FileOutcome(
            source=p.name,
            stem=stem,
            state="cached",
            mineru_zip_path=str(zip_path),
            code_format_path=str(output_dir / f"{stem}.code_format.json"),
            raw_data_path=str(output_dir / f"{stem}.raw_data.json"),
        )
        try:
            with zipfile.ZipFile(zip_path) as z:
                md_name = _find_in_zip(z, lambda n: n.endswith("full.md") or n == "full.md")
                if md_name and md_dir is not None:
                    md_text = _read_zip_text(z, md_name)
                    md_path = md_dir / f"{stem}.md"
                    md_path.write_text(md_text, encoding="utf-8")
                    fo.markdown_path = str(md_path)
                elif not md_name:
                    fo.warnings.append("cached zip 中未找到 full.md")
            print(f"  [cache] {p.name} → {fo.markdown_path or '(no markdown_dir env)'}", flush=True)
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

    # MinerU 单 PDF 200 页上限：自动切分 → __part1_p1-200.pdf / __part2_p201-400.pdf ...
    pdf_split_dir = input_dir / "_pdf_splits"
    file_paths = _expand_input_with_pdf_split(file_paths, pdf_split_dir)

    # 若混用 html 与非 html，需分批（少见）
    def split_by_model_version(paths: list[Path]) -> list[list[Path]]:
        buckets: dict[str, list[Path]] = {}
        for p in paths:
            mv = _model_version_for_path(p, args.model_version if args.model_version != "auto" else None)
            buckets.setdefault(mv, []).append(p)
        return list(buckets.values())

    batches = split_by_model_version(file_paths)
    session = requests.Session()

    for group in batches:
        mv_arg = args.model_version
        # 对该组使用统一 model_version
        effective_mv = _model_version_for_path(group[0], mv_arg if mv_arg != "auto" else None)
        print(f"提交批次：{len(group)} 个文件，model_version={effective_mv}")

        batch_id, upload_urls = _post_batch(
            session,
            token,
            group,
            effective_mv=effective_mv,
            language=args.language,
            enable_formula=args.enable_formula,
            enable_table=args.enable_table,
            is_ocr=args.is_ocr,
        )
        print(f"batch_id={batch_id}，开始上传…")
        _upload_files(session, group, upload_urls)
        print("上传完成，轮询解析结果…")

        # 并发下载 + 解压 + 写盘：同一文件一变 terminal 就立刻 submit。
        by_source_name = {p.name: p for p in group}
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
                zb = _download_zip(session, fo.full_zip_url)
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
                for info in _poll_batch_stream(
                    session,
                    token,
                    batch_id,
                    poll_interval=args.poll_interval_sec,
                    max_wait_sec=args.max_wait_min * 60,
                ):
                    print(f"  → {info.get('file_name')} {info.get('state')}，下发下载")
                    futures.append(pool.submit(_finalize, info))
                for fut in as_completed(futures):
                    fo = fut.result()
                    with outcomes_lock:
                        batch_outcomes.append(fo)
                        if fo.code_format_path:
                            print(f"  ✓ {fo.source} -> {Path(fo.code_format_path).name}")
                        elif fo.state == "failed":
                            print(f"  ✗ {fo.source}: {fo.err_msg}")
        except Exception as e:
            for p in group:
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

    ok = sum(1 for o in all_outcomes if o.state == "done" and o.code_format_path)
    print(f"完成：成功写出 {ok}/{len(all_outcomes)} 组 JSON，manifest: {output_dir / 'manifest.json'}")
    if ok < len(all_outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()
