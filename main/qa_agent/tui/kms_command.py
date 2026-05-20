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

兼容性：
- 旧的 ``/kms update`` / ``/kms rebuild`` 等单层命令显式报错。

边界：
- ``defects/`` 与 ``baselines/`` 不属于任何 namespace，``/kms`` 不会动它们。
- KMS 简化管线：分桶 + markdown 直出，不再跑 trunk/feature/scenario/architecture
  抽取（2026-05-20 收口，详见 ``/.claude/plans/toasty-foraging-shore.md``）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main.qa_agent.tui.app import IstApp


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


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
    lines.append("== knowledge/data/ (out of scope: not from orgin) ==")
    lines.append(
        f"  {'defects (bugzilla/plm cache)':30} {_count(kp.KNOWLEDGE_DEFECTS, '*.json', recurse=True):>4}  "
        f"{kp.KNOWLEDGE_DEFECTS.relative_to(rel)}"
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
    lines.append("  /kms product status|update|rebuild|delete   — 产品知识库（mineru 链）")
    lines.append("  /kms qa      status|update|rebuild|delete   — 测试知识库（xlsx 链, phase 2）")
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


# ---------------------------------------------------------------------------
# product update — runs mineru → clean → trunk → feature
# ---------------------------------------------------------------------------


def _kick_product_update(app: "IstApp") -> None:
    """启 subprocess 跑产品链：仅 mineru_batch_export 一步出 markdown。"""
    project_root = _project_root()
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)

    buckets = _orgin_buckets()
    product_files = ",".join(buckets.get("product", []))

    steps = [
        ("mineru_batch_export", [str(venv_python), "-m", "main.mineru_batch_export"]),
    ]

    env = dict(os.environ)
    env["KMS_PRODUCT_FILES"] = product_files       # 白名单：只摄入 product 桶文件
    env["KMS_OUTPUT_BUCKET"] = "product"           # 解出的 full.md 写到 markdown/product/

    def _run() -> None:
        for label, cmd in steps:
            try:
                app.call_from_thread(
                    app._append_info,  # type: ignore[attr-defined]
                    f"[/kms product update] starting: {label}",
                )
            except Exception:
                pass
            try:
                proc = subprocess.run(  # noqa: PLW1510
                    cmd,
                    cwd=str(project_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                tail = (proc.stdout or "").strip().splitlines()[-3:]
                err_tail = (proc.stderr or "").strip().splitlines()[-3:]
                summary = " | ".join(tail) or "(no stdout)"
                if proc.returncode != 0:
                    summary = f"FAILED rc={proc.returncode} | err: {' | '.join(err_tail)}"
                try:
                    app.call_from_thread(
                        app._append_info,  # type: ignore[attr-defined]
                        f"[/kms product update] {label}: {summary}",
                    )
                except Exception:
                    pass
                if proc.returncode != 0:
                    return
            except subprocess.TimeoutExpired:
                try:
                    app.call_from_thread(
                        app._append_info,  # type: ignore[attr-defined]
                        f"[/kms product update] {label}: TIMEOUT (>30min)",
                    )
                except Exception:
                    pass
                return
        try:
            app.call_from_thread(
                app._append_info,  # type: ignore[attr-defined]
                "[/kms product update] all steps completed; markdown ready in knowledge/data/markdown/product/",
            )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="kms-product-update").start()


# ---------------------------------------------------------------------------
# qa update — xlsx 直转 markdown，doc/pdf 走 mineru
# ---------------------------------------------------------------------------


_QA_XLSX_EXTS = {".xlsx", ".xlsm", ".xls"}
_QA_MINERU_EXTS = {".pdf", ".doc", ".docx", ".pptx", ".ppt", ".html", ".htm"}


def _kick_qa_update(app: "IstApp") -> None:
    """启 subprocess 跑测试知识链：xlsx 用 xlsx_to_markdown，其他走 mineru。"""
    project_root = _project_root()
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)

    from main import knowledge_paths as kp

    buckets = _orgin_buckets()
    qa_files = list(buckets.get("test_case_list", [])) + list(buckets.get("test_strategy", []))
    xlsx_files = [n for n in qa_files if Path(n).suffix.lower() in _QA_XLSX_EXTS]
    mineru_files = [n for n in qa_files if Path(n).suffix.lower() in _QA_MINERU_EXTS]
    skipped = [n for n in qa_files if n not in xlsx_files and n not in mineru_files]

    def _run() -> None:
        # 1. xlsx → md（不开 subprocess，本地直接调）
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
            try:
                app.call_from_thread(
                    app._append_info,  # type: ignore[attr-defined]
                    f"[/kms qa update] {msg}",
                )
            except Exception:
                pass

        # 2. doc/pdf → mineru
        if mineru_files:
            env = dict(os.environ)
            env["KMS_PRODUCT_FILES"] = ",".join(mineru_files)  # 借用白名单：让 batch_export 只跑这批
            env["KMS_OUTPUT_BUCKET"] = "qa"
            try:
                app.call_from_thread(
                    app._append_info,  # type: ignore[attr-defined]
                    f"[/kms qa update] starting mineru_batch_export ({len(mineru_files)} files)",
                )
            except Exception:
                pass
            try:
                proc = subprocess.run(  # noqa: PLW1510
                    [str(venv_python), "-m", "main.mineru_batch_export"],
                    cwd=str(project_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                tail = (proc.stdout or "").strip().splitlines()[-3:]
                err_tail = (proc.stderr or "").strip().splitlines()[-3:]
                summary = " | ".join(tail) or "(no stdout)"
                if proc.returncode != 0:
                    summary = f"FAILED rc={proc.returncode} | err: {' | '.join(err_tail)}"
                try:
                    app.call_from_thread(
                        app._append_info,  # type: ignore[attr-defined]
                        f"[/kms qa update] mineru_batch_export: {summary}",
                    )
                except Exception:
                    pass
            except subprocess.TimeoutExpired:
                try:
                    app.call_from_thread(
                        app._append_info,  # type: ignore[attr-defined]
                        "[/kms qa update] mineru_batch_export: TIMEOUT (>30min)",
                    )
                except Exception:
                    pass

        if skipped:
            try:
                app.call_from_thread(
                    app._append_info,  # type: ignore[attr-defined]
                    f"[/kms qa update] skipped (unsupported ext): {', '.join(skipped)}",
                )
            except Exception:
                pass

        try:
            app.call_from_thread(
                app._append_info,  # type: ignore[attr-defined]
                "[/kms qa update] done; markdown ready in knowledge/data/markdown/qa/",
            )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="kms-qa-update").start()


# ---------------------------------------------------------------------------
# dispatchers
# ---------------------------------------------------------------------------


def _dispatch_product(action: str, rest: str, app: "IstApp"):  # noqa: ANN201
    from main.qa_agent.tui.slash_commands import (
        ErrorResult, InfoResult, TextResult,
    )
    if action in ("", "status"):
        return TextResult(text=_format_product_status())

    if action == "update":
        if not os.environ.get("MINERU_TOKEN"):
            return ErrorResult(text="/kms product update needs MINERU_TOKEN in environment file")
        if not os.environ.get("DASHSCOPE_API_KEY"):
            return ErrorResult(text="/kms product update needs DASHSCOPE_API_KEY in environment file")
        _kick_product_update(app)
        n_product = len(_orgin_buckets().get("product", []))
        return InfoResult(text=(
            f"[/kms product update] kicked off in background "
            f"({n_product} product source files; mineru → clean → trunk → feature). "
            f"Watch transcript for per-step summaries; cache will skip unchanged sources."
        ))

    if action in ("rebuild", "delete"):
        return InfoResult(text=f"/kms product {action}: not implemented yet (phase 2)")

    return ErrorResult(text=(
        f"unknown /kms product subcommand: {action!r}. "
        f"Try: status | update | rebuild | delete."
    ))


def _dispatch_qa(action: str, rest: str, app: "IstApp"):  # noqa: ANN201
    from main.qa_agent.tui.slash_commands import (
        ErrorResult, InfoResult, TextResult,
    )
    if action in ("", "status"):
        return TextResult(text=_format_qa_status())

    if action == "update":
        rows = _orgin_rows()
        qa_rows = [r for r in rows if r["category"] in ("test_case_list", "test_strategy")]
        n_xlsx = sum(1 for r in qa_rows if Path(r["name"]).suffix.lower() in _QA_XLSX_EXTS)
        n_mineru = sum(1 for r in qa_rows if Path(r["name"]).suffix.lower() in _QA_MINERU_EXTS)
        if n_mineru and not os.environ.get("MINERU_TOKEN"):
            return ErrorResult(text="/kms qa update needs MINERU_TOKEN to handle non-xlsx files")
        _kick_qa_update(app)
        return InfoResult(text=(
            f"[/kms qa update] kicked off in background "
            f"({n_xlsx} xlsx via openpyxl, {n_mineru} via mineru). "
            f"Watch transcript for per-file summaries; output → knowledge/data/markdown/qa/"
        ))

    if action in ("rebuild", "delete"):
        return InfoResult(text=f"/kms qa {action}: not implemented yet (phase 2)")

    return ErrorResult(text=(
        f"unknown /kms qa subcommand: {action!r}. "
        f"Try: status | update | rebuild | delete."
    ))


_LEGACY_FLAT_ACTIONS = {"update", "rebuild", "delete", "ingest"}


def cmd_kms(args: str, app: "IstApp"):  # noqa: ANN201
    """Top-level /kms dispatcher — see module docstring for grammar."""
    from main.qa_agent.tui.slash_commands import (
        ErrorResult, TextResult,
    )

    parts = (args or "").strip().split(maxsplit=2)

    # /kms      ➜ overall status
    # /kms status
    if not parts or (len(parts) == 1 and parts[0].lower() == "status"):
        return TextResult(text=_format_overall_status())

    head = parts[0].lower()

    # 旧扁平命令拦截
    if head in _LEGACY_FLAT_ACTIONS:
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

    return ErrorResult(text=(
        f"unknown /kms namespace: {head!r}. "
        f"Try: /kms status | /kms product <action> | /kms qa <action>."
    ))
