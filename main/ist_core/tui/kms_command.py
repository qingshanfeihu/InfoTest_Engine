"""Knowledge Management System (KMS) slash command — `/kms <namespace> <action>`

二级命令结构::

    /kms                                 等价 /kms status（总览）
    /kms status                          总览三档：product / qa / out-of-scope
    /kms product status                  产品知识库状态
    /kms product update                  跑 mineru_batch_export → knowledge/data/markdown/product/
    /kms product rebuild [stem]          phase 2
    /kms product delete <stem>           phase 2
    /kms qa status                       测试知识库状态
    /kms qa update                       xlsx → openpyxl，doc/pdf → mineru → markdown/qa/
    /kms qa rebuild [stem]               phase 2
    /kms qa delete <stem>                phase 2
    /kms footprint status                footprint 知识树状态（节点/命令/覆盖章节）
    /kms footprint update                手册 → footprint 增量补全（复用 existing，仅追加新事实）
    /kms footprint rebuild               备份现有 nodes 后全量重建（从空树重抽）

兼容性：
- 旧的 ``/kms update`` / ``/kms rebuild`` 等单层命令显式报错。

边界：
- ``defects/`` 与 ``baselines/`` 不属于任何 namespace，``/kms`` 不会动它们。
- KMS 简化管线：分桶 + markdown 直出备份。
- ``/kms footprint`` 把 ``knowledge/data/markdown/product/manual_10.5/`` 的 CLI 手册抽成
  ``knowledge/footprints/nodes/`` 已验证事实树（走 footprint_backfill，evidence 门防编造）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


KmsApp = Any







def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _post_kms_status(app: KmsApp, msg: str) -> None:
    """向 TUI transcript 追加 KMS 进度（Ink 线程安全；兼容 Textual）。"""
    if hasattr(app, "append_transcript_info"):
        app.append_transcript_info(msg)
        return
    if hasattr(app, "call_from_thread") and hasattr(app, "_append_info"):
        try:
            app.call_from_thread(app._append_info, msg)  # type: ignore[attr-defined]
        except Exception:
            pass


def _kms_update_timeout_sec() -> int:
    raw = (os.environ.get("KMS_UPDATE_TIMEOUT_SEC") or "7200").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 7200


def _kms_log_poll_interval_sec() -> float:
    raw = (os.environ.get("KMS_LOG_POLL_INTERVAL_SEC") or "2").strip()
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 2.0


_KMS_LOG_ECHO = re.compile(
    r"(\[batch\s+\d+/\d+\]|"
    r"\[KMS_PRODUCT_FILES\]|"
    r"\[cache\]|"
    r"提交批次|batch_id=|上传完成|轮询|"
    r"^\s*[✓✗→]|"
    r"完成：|"
    r"全部\s+\d+\s+个|"
    r"\d+\s+个命中缓存)",
)


def _should_echo_log_line(line: str) -> bool:
    """关键进度行写入 transcript；其余仅更新 thinking 行。"""
    return bool(_KMS_LOG_ECHO.search(line))


def _clear_background_status(app: KmsApp | None) -> None:
    if app is not None and hasattr(app, "set_background_status"):
        app.set_background_status(None)


def _push_log_progress(app: KmsApp | None, tag: str, line: str) -> None:
    if app is None:
        return
    display = line if len(line) <= 100 else line[:97] + "..."
    if hasattr(app, "set_background_status"):
        app.set_background_status(f"{tag} {display}")
    if _should_echo_log_line(line):
        _post_kms_status(app, f"{tag} {display}")


def _flush_log_to_ui(app: KmsApp | None, log_path: Path, offset: int, tag: str) -> int:
    """从 log_path 的 offset 起读取新行并刷新 TUI，返回新 offset。"""
    if not log_path.exists():
        return offset
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            chunk = f.read()
            new_offset = f.tell()
    except OSError:
        return offset
    if not chunk:
        return new_offset
    for raw in chunk.splitlines():
        line = raw.strip()
        if not line or line.startswith("--- kms"):
            continue
        _push_log_progress(app, tag, line)
    return new_offset


def _tail_log_lines(path: Path, n: int = 8) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-n:] if lines else []


def _run_module_subprocess(
    project_root: Path,
    venv_python: Path,
    env: dict[str, str],
    *,
    module_args: list[str],
    log_path: Path,
    timeout_sec: int,
    app: KmsApp | None = None,
    progress_tag: str = "[/kms]",
) -> tuple[int, list[str]]:
    """跑 `python -u -m <module_args>` 子进程；日志写 log_path，轮询 tail 到 TUI，返回 (rc, 日志尾部)。

    通用 module runner：product/qa 跑 mineru_batch_export，footprint 跑 footprint_backfill。
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    run_env = dict(env)
    run_env["PYTHONUNBUFFERED"] = "1"
    poll_iv = _kms_log_poll_interval_sec()
    deadline = time.monotonic() + timeout_sec
    log_offset = 0

    with log_path.open("w", encoding="utf-8") as log_f:
        log_f.write("--- kms mineru subprocess started ---\n")
        log_f.flush()
        proc = subprocess.Popen(
            [str(venv_python), "-u", *module_args],
            cwd=str(project_root),
            env=run_env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )

    while proc.poll() is None:
        if time.monotonic() >= deadline:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            log_offset = _flush_log_to_ui(app, log_path, log_offset, progress_tag)
            _clear_background_status(app)
            return -1, _tail_log_lines(log_path, 12)
        log_offset = _flush_log_to_ui(app, log_path, log_offset, progress_tag)
        time.sleep(poll_iv)

    log_offset = _flush_log_to_ui(app, log_path, log_offset, progress_tag)
    _clear_background_status(app)
    rc = proc.returncode if proc.returncode is not None else 1
    return rc, _tail_log_lines(log_path, 12)


def _count(path: Path, pattern: str = "*", *, recurse: bool = False) -> int:
    if not path.exists():
        return 0
    it = path.rglob(pattern) if recurse else path.glob(pattern)
    return sum(1 for p in it if p.is_file())


def _orgin_buckets() -> dict[str, list[str]]:
    from main.kms_classifier import bucketize_orgin_dir
    from main import knowledge_paths as kp
    return bucketize_orgin_dir(kp.KNOWLEDGE_ORGIN)


def _orgin_rows() -> list[dict]:
    """Return per-file rows with category + reason for status display."""
    from main.kms_classifier import list_orgin_with_reasons
    from main import knowledge_paths as kp
    return list_orgin_with_reasons(kp.KNOWLEDGE_ORGIN)


def _format_overall_status() -> str:
    from main import knowledge_paths as kp

    buckets = _orgin_buckets()
    rel = _project_root()

    lines = ["Knowledge base status:", ""]
    lines.append("== knowledge/data/ (mineru-managed: /kms product) ==")
    rows = [
        (f"product sources (orgin/)",  len(buckets.get("product", [])), kp.KNOWLEDGE_ORGIN),
        ("markdown/product (agent)",   _count(kp.KNOWLEDGE_MARKDOWN_PRODUCT, "*.md"), kp.KNOWLEDGE_MARKDOWN_PRODUCT),
    ]
    for label, n, path in rows:
        lines.append(f"  {label:30} {n:>4}  {path.relative_to(rel)}")

    lines.append("")
    lines.append("== knowledge/data/ (qa pipeline: /kms qa) ==")
    lines.append(
        f"  {'test case lists (xlsx)':30} {len(buckets.get('test_case_list', [])):>4}  "
        f"{kp.KNOWLEDGE_ORGIN.relative_to(rel)}"
    )
    lines.append(
        f"  {'test strategy docs':30} {len(buckets.get('test_strategy', [])):>4}  "
        f"{kp.KNOWLEDGE_ORGIN.relative_to(rel)}"
    )
    lines.append(
        f"  {'markdown/qa (agent)':30} {_count(kp.KNOWLEDGE_MARKDOWN_QA, '*.md'):>4}  "
        f"{kp.KNOWLEDGE_MARKDOWN_QA.relative_to(rel)}"
    )

    lines.append("")
    lines.append("== workspace/defects/ (bugzilla/plm cache) ==")
    lines.append(
        f"  {'defects (bugzilla/plm cache)':30} {_count(kp.WORKSPACE_DEFECTS, '*.json', recurse=True):>4}  "
        f"{kp.WORKSPACE_DEFECTS.relative_to(rel)}"
    )

    lines.append("")
    lines.append("== knowledge/.intermediate/ (agent hidden) ==")
    int_rows = [
        ("mineru parsed", kp.KNOWLEDGE_MINERU),
    ]
    for label, path in int_rows:
        n = sum(1 for _ in path.rglob("*") if _.is_file()) if path.exists() else 0
        lines.append(f"  {label:30} {n:>4}  {path.relative_to(rel)}")

    lines.append("")
    if kp.CACHE_JSON.exists():
        try:
            cache = json.loads(kp.CACHE_JSON.read_text(encoding="utf-8"))
            n = len(cache) if isinstance(cache, dict) else "?"
            lines.append(f"  cache entries: {n}    ({kp.CACHE_JSON.relative_to(rel)})")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"  cache file (unreadable): {exc}")
    else:
        lines.append("  cache: (none — never built)")

    lines.append("")
    lines.append("Subcommands:")
    lines.append("  infotest kms product status|update   — 产品知识库（mineru 链）")
    lines.append("  infotest kms qa      status|update   — 测试知识库（xlsx + mineru）")
    return "\n".join(lines)


def _format_product_status() -> str:
    from main import knowledge_paths as kp
    rows = _orgin_rows()
    rel = _project_root()
    product_rows = [r for r in rows if r["category"] == "product"]
    unclassified_rows = [r for r in rows if r["category"] == "unclassified"]

    lines = ["Product knowledge base (/kms product):", ""]
    lines.append(
        f"  product sources (orgin/)         {len(product_rows):>4}  "
        f"{kp.KNOWLEDGE_ORGIN.relative_to(rel)}"
    )
    lines.append(
        f"  markdown (agent 直读)            {_count(kp.KNOWLEDGE_MARKDOWN_PRODUCT, '*.md'):>4}  "
        f"{kp.KNOWLEDGE_MARKDOWN_PRODUCT.relative_to(rel)}"
    )

    if unclassified_rows:
        lines.append("")
        lines.append(f"  ⚠ unclassified                  {len(unclassified_rows):>4}  (LLM 无法判定，需要手工写 .classifier_overrides.json)")
        for r in unclassified_rows:
            lines.append(f"      {r['name']:55}  {r['reason']}")

    lines.append("")
    lines.append("classified product sources (LLM-judged):")
    for r in product_rows:
        src = r["source"][:5]
        conf = f"{r['confidence']:.2f}"
        lines.append(f"  [{src}] conf={conf}  {r['name']:55}  {r['reason'][:80]}")

    lines.append("")
    lines.append("Actions:")
    lines.append("  /kms product update             — mineru_batch_export → markdown/product/ 直出")
    lines.append("  /kms product rebuild [stem]     — force full or single-stem rebuild (phase 2)")
    lines.append("  /kms product delete <stem>      — drop a stem's derived products (phase 2)")
    lines.append("")
    lines.append("Note: defects/baselines/test-assets are NOT touched by /kms product.")
    return "\n".join(lines)


def _format_qa_status() -> str:
    rows = _orgin_rows()
    test_case_rows = [r for r in rows if r["category"] == "test_case_list"]
    test_strat_rows = [r for r in rows if r["category"] == "test_strategy"]

    lines = ["Test knowledge base (/kms qa):", ""]
    lines.append(f"  test case lists (xlsx):     {len(test_case_rows)}")
    for r in test_case_rows:
        src = r["source"][:5]
        conf = f"{r['confidence']:.2f}"
        lines.append(f"    [{src}] conf={conf}  {r['name']:55}  {r['reason'][:80]}")
    lines.append("")
    lines.append(f"  test strategy docs:         {len(test_strat_rows)}")
    for r in test_strat_rows:
        src = r["source"][:5]
        conf = f"{r['confidence']:.2f}"
        lines.append(f"    [{src}] conf={conf}  {r['name']:55}  {r['reason'][:80]}")
    lines.append("")
    lines.append("Actions:")
    lines.append("  /kms qa update              — qa_data_clean → qa_trunk_merged → test_assets (phase 2)")
    lines.append("  /kms qa rebuild [stem]      — phase 2")
    lines.append("  /kms qa delete <stem>       — phase 2")
    lines.append("")
    lines.append("Note: not yet implemented; status only.")
    return "\n".join(lines)







def _kick_product_update(app: KmsApp, *, product_files: str) -> None:
    """启 subprocess 跑产品链：仅 mineru_batch_export 一步出 markdown。"""
    from main import knowledge_paths as kp

    project_root = _project_root()
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)

    env = dict(os.environ)
    env["KMS_PRODUCT_FILES"] = product_files
    env["KMS_OUTPUT_BUCKET"] = "product"

    log_path = kp.KNOWLEDGE_INTERMEDIATE / ".kms_product_update.log"
    timeout_sec = _kms_update_timeout_sec()
    rel_log = log_path.relative_to(project_root)

    def _run() -> None:
        _post_kms_status(
            app,
            f"[/kms product update] starting mineru_batch_export (log: {rel_log})",
        )
        rc, tail = _run_module_subprocess(
            project_root,
            venv_python,
            env,
            module_args=["-m", "main.mineru_batch_export"],
            log_path=log_path,
            timeout_sec=timeout_sec,
            app=app,
            progress_tag="[/kms product update]",
        )
        if rc == -1:
            _post_kms_status(
                app,
                f"[/kms product update] TIMEOUT (>{timeout_sec}s). See {rel_log}",
            )
            return
        summary = " | ".join(tail) or "(see log)"
        if rc != 0:
            _post_kms_status(
                app,
                f"[/kms product update] FAILED rc={rc} | {summary}",
            )
            return
        _post_kms_status(
            app,
            f"[/kms product update] done | {summary}",
        )
        _post_kms_status(
            app,
            "[/kms product update] markdown ready in knowledge/data/markdown/product/",
        )

    threading.Thread(target=_run, daemon=True, name="kms-product-update").start()







_QA_XLSX_EXTS = {".xlsx", ".xlsm", ".xls"}
_QA_MINERU_EXTS = {".pdf", ".doc", ".docx", ".pptx", ".ppt", ".html", ".htm"}


def _kick_qa_update(
    app: KmsApp,
    *,
    xlsx_files: list[str],
    mineru_files: list[str],
    skipped: list[str],
) -> None:
    """启 subprocess 跑测试知识链：xlsx 用 xlsx_to_markdown，其他走 mineru。"""
    project_root = _project_root()
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)

    from main import knowledge_paths as kp

    log_path = kp.KNOWLEDGE_INTERMEDIATE / ".kms_qa_update.log"
    timeout_sec = _kms_update_timeout_sec()
    rel_log = log_path.relative_to(project_root)

    def _run() -> None:
        from main.xlsx_to_markdown import write_markdown

        kp.KNOWLEDGE_MARKDOWN_QA.mkdir(parents=True, exist_ok=True)
        for name in xlsx_files:
            src = kp.KNOWLEDGE_ORGIN / name
            out = kp.KNOWLEDGE_MARKDOWN_QA / f"{Path(name).stem}.md"
            try:
                write_markdown(src, out)
                msg = f"xlsx → md: {name} -> {out.name}"
            except Exception as exc:  # noqa: BLE001
                msg = f"xlsx FAILED {name}: {exc}"
            _post_kms_status(app, f"[/kms qa update] {msg}")

        if mineru_files:
            env = dict(os.environ)
            env["KMS_PRODUCT_FILES"] = ",".join(mineru_files)
            env["KMS_OUTPUT_BUCKET"] = "qa"
            _post_kms_status(
                app,
                f"[/kms qa update] starting mineru_batch_export "
                f"({len(mineru_files)} files, log: {rel_log})",
            )
            rc, tail = _run_module_subprocess(
                project_root,
                venv_python,
                env,
                module_args=["-m", "main.mineru_batch_export"],
                log_path=log_path,
                timeout_sec=timeout_sec,
                app=app,
                progress_tag="[/kms qa update]",
            )
            if rc == -1:
                _post_kms_status(
                    app,
                    f"[/kms qa update] mineru TIMEOUT (>{timeout_sec}s). See {rel_log}",
                )
            elif rc != 0:
                summary = " | ".join(tail) or "(see log)"
                _post_kms_status(
                    app,
                    f"[/kms qa update] mineru FAILED rc={rc} | {summary}",
                )
            else:
                summary = " | ".join(tail) or "(see log)"
                _post_kms_status(app, f"[/kms qa update] mineru done | {summary}")

        if skipped:
            _post_kms_status(
                app,
                f"[/kms qa update] skipped (unsupported ext): {', '.join(skipped)}",
            )

        _post_kms_status(
            app,
            "[/kms qa update] done; markdown ready in knowledge/data/markdown/qa/",
        )

    threading.Thread(target=_run, daemon=True, name="kms-qa-update").start()







def _dispatch_product(action: str, rest: str, app: KmsApp):  # noqa: ANN201
    from main.ist_core.tui.slash_commands import (
        ErrorResult, InfoResult, TextResult,
    )
    from main import knowledge_paths as kp

    if action in ("", "status"):
        return TextResult(text=_format_product_status())

    if action == "update":
        if not os.environ.get("MINERU_TOKEN"):
            return ErrorResult(text="/kms product update needs MINERU_TOKEN in environment file")
        buckets = _orgin_buckets()
        product_names = buckets.get("product", [])
        product_files = ",".join(product_names)
        _kick_product_update(app, product_files=product_files)
        rel_log = (kp.KNOWLEDGE_INTERMEDIATE / ".kms_product_update.log").relative_to(
            _project_root()
        )
        batch_size = (os.environ.get("MINERU_BATCH_SIZE") or "30").strip()
        return InfoResult(text=(
            f"[/kms product update] kicked off in background "
            f"({len(product_names)} product sources → mineru_batch_export → markdown/product/; "
            f"zip cache直出 + API 分批默认每批 {batch_size}). "
            f"进度见 transcript 与输入框上方状态行；完整日志: {rel_log}"
        ))

    if action in ("rebuild", "delete"):
        return InfoResult(text=f"/kms product {action}: not implemented yet (phase 2)")

    return ErrorResult(text=(
        f"unknown /kms product subcommand: {action!r}. "
        f"Try: status | update | rebuild | delete."
    ))


def _dispatch_qa(action: str, rest: str, app: KmsApp):  # noqa: ANN201
    from main.ist_core.tui.slash_commands import (
        ErrorResult, InfoResult, TextResult,
    )
    from main import knowledge_paths as kp

    if action in ("", "status"):
        return TextResult(text=_format_qa_status())

    if action == "update":
        buckets = _orgin_buckets()
        qa_files = list(buckets.get("test_case_list", [])) + list(
            buckets.get("test_strategy", [])
        )
        xlsx_files = [n for n in qa_files if Path(n).suffix.lower() in _QA_XLSX_EXTS]
        mineru_files = [n for n in qa_files if Path(n).suffix.lower() in _QA_MINERU_EXTS]
        skipped = [n for n in qa_files if n not in xlsx_files and n not in mineru_files]
        if mineru_files and not os.environ.get("MINERU_TOKEN"):
            return ErrorResult(text="/kms qa update needs MINERU_TOKEN to handle non-xlsx files")
        _kick_qa_update(
            app,
            xlsx_files=xlsx_files,
            mineru_files=mineru_files,
            skipped=skipped,
        )
        rel_log = (kp.KNOWLEDGE_INTERMEDIATE / ".kms_qa_update.log").relative_to(_project_root())
        return InfoResult(text=(
            f"[/kms qa update] kicked off in background "
            f"({len(xlsx_files)} xlsx via openpyxl, {len(mineru_files)} via mineru). "
            f"进度见 transcript 与输入框上方状态行；完整日志: {rel_log}"
        ))

    if action in ("rebuild", "delete"):
        return InfoResult(text=f"/kms qa {action}: not implemented yet (phase 2)")

    return ErrorResult(text=(
        f"unknown /kms qa subcommand: {action!r}. "
        f"Try: status | update | rebuild | delete."
    ))


def _format_footprint_status() -> str:
    """footprint 知识树状态：节点数 / level 分布 / 命令数 / 覆盖手册章节。"""
    import json as _json
    from main import knowledge_paths as kp

    rel = _project_root()
    nodes_dir = kp.KNOWLEDGE_FOOTPRINTS_NODES
    n_nodes = _count(nodes_dir, "*.json")

    n_cmds = 0
    levels = {"leaf": 0, "trunk": 0, "branch": 0}
    chapters: set[str] = set()
    if nodes_dir.exists():
        for f in nodes_dir.glob("*.json"):
            try:
                d = _json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — 坏节点不该挡住 status
                continue
            lv = d.get("level", "")
            if lv in levels:
                levels[lv] += 1
            for cmd in d.get("cli", {}).get("commands", []):
                n_cmds += 1
                sf = cmd.get("evidence", {}).get("source_file", "")
                if sf:
                    chapters.add(Path(sf).name)

    manual_dir = kp.KNOWLEDGE_MARKDOWN_PRODUCT / "manual_10.5"
    n_manual = _count(manual_dir, "cli_10.5_*.md")

    lines = ["Footprint knowledge tree (/kms footprint):", ""]
    lines.append(f"  nodes (已验证 CLI 事实树)     {n_nodes:>4}  {nodes_dir.relative_to(rel)}")
    lines.append(f"    leaf / trunk / branch       {levels['leaf']} / {levels['trunk']} / {levels['branch']}")
    lines.append(f"  cli commands                  {n_cmds:>4}")
    lines.append(f"  覆盖手册章节                  {len(chapters):>4} / {n_manual}  (manual_10.5/cli_10.5_*.md)")
    lines.append("")
    lines.append("Actions:")
    lines.append("  /kms footprint update     — 手册 → footprint 增量补全(复用 existing,仅追加新事实)")
    lines.append("  /kms footprint rebuild    — 备份现有 nodes 后全量重建(从空树重抽)")
    lines.append("")
    lines.append("知识源: knowledge/data/markdown/product/manual_10.5/  (adoc→md, 表1-1 粗体命令约定)")
    return "\n".join(lines)


def _kick_footprint_update(app: KmsApp, *, rebuild: bool = False) -> None:
    """启 subprocess 跑 footprint_backfill：手册 → footprint 树(增量 / 全量重建)。"""
    from main import knowledge_paths as kp

    project_root = _project_root()
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)

    log_path = kp.KNOWLEDGE_INTERMEDIATE / ".kms_footprint_update.log"
    timeout_sec = _kms_update_timeout_sec()
    rel_log = log_path.relative_to(project_root)
    tag = "[/kms footprint rebuild]" if rebuild else "[/kms footprint update]"
    module_args = ["-m", "scripts.maintenance.footprint_backfill"]
    if rebuild:
        module_args.append("--rebuild")

    def _run() -> None:
        _post_kms_status(app, f"{tag} starting footprint_backfill (log: {rel_log})")
        rc, tail = _run_module_subprocess(
            project_root,
            venv_python,
            dict(os.environ),
            module_args=module_args,
            log_path=log_path,
            timeout_sec=timeout_sec,
            app=app,
            progress_tag=tag,
        )
        if rc == -1:
            _post_kms_status(app, f"{tag} TIMEOUT (>{timeout_sec}s). See {rel_log}")
            return
        summary = " | ".join(tail) or "(see log)"
        if rc != 0:
            _post_kms_status(app, f"{tag} FAILED rc={rc} | {summary}")
            return
        _post_kms_status(app, f"{tag} done | {summary}")
        _post_kms_status(app, f"{tag} footprint tree ready in knowledge/footprints/nodes/")

    threading.Thread(target=_run, daemon=True, name="kms-footprint-update").start()


def _dispatch_footprint(action: str, rest: str, app: KmsApp):  # noqa: ANN201
    from main.ist_core.tui.slash_commands import (
        ErrorResult, InfoResult, TextResult,
    )
    from main import knowledge_paths as kp

    if action in ("", "status"):
        return TextResult(text=_format_footprint_status())

    if action in ("update", "rebuild"):
        from main.ist_core.agents._llm import resolve_llm_api_key
        if not resolve_llm_api_key():
            return ErrorResult(text=(
                "/kms footprint update 需要 LLM API key (OPENAI_API_KEY 或兼容端点 key) 在 environment 文件"
            ))
        rebuild = action == "rebuild"
        _kick_footprint_update(app, rebuild=rebuild)
        rel_log = (kp.KNOWLEDGE_INTERMEDIATE / ".kms_footprint_update.log").relative_to(_project_root())
        mode = "全量重建(备份+清空+重抽)" if rebuild else "增量补全(复用 existing,仅追加新事实)"
        return InfoResult(text=(
            f"[/kms footprint {action}] kicked off in background "
            f"(手册 manual_10.5 → footprint 树, {mode}). "
            f"进度见 transcript 与输入框上方状态行；完整日志: {rel_log}"
        ))

    if action == "delete":
        return InfoResult(text="/kms footprint delete: not implemented yet")

    return ErrorResult(text=(
        f"unknown /kms footprint subcommand: {action!r}. Try: status | update | rebuild."
    ))


_FLAT_ACTIONS = {"update", "rebuild", "delete", "ingest"}


def cmd_kms(args: str, app: KmsApp):  # noqa: ANN201
    """Top-level /kms dispatcher — see module docstring for grammar."""
    from main.ist_core.tui.slash_commands import (
        ErrorResult, TextResult,
    )

    parts = (args or "").strip().split(maxsplit=2)

    
    
    if not parts or (len(parts) == 1 and parts[0].lower() == "status"):
        return TextResult(text=_format_overall_status())

    head = parts[0].lower()

    
    if head in _FLAT_ACTIONS:
        return ErrorResult(text=(
            f"/kms {head} is no longer a flat command. "
            f"Use /kms product {head} (or /kms qa {head})."
        ))

    if head == "product":
        action = (parts[1].lower() if len(parts) > 1 else "")
        rest = parts[2] if len(parts) > 2 else ""
        return _dispatch_product(action, rest, app)

    if head == "qa":
        action = (parts[1].lower() if len(parts) > 1 else "")
        rest = parts[2] if len(parts) > 2 else ""
        return _dispatch_qa(action, rest, app)

    if head == "footprint":
        action = (parts[1].lower() if len(parts) > 1 else "")
        rest = parts[2] if len(parts) > 2 else ""
        return _dispatch_footprint(action, rest, app)

    return ErrorResult(text=(
        f"unknown /kms namespace: {head!r}. "
        f"Try: /kms status | /kms product <action> | /kms qa <action> | /kms footprint <action>."
    ))
