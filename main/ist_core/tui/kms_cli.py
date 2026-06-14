"""CLI handler for ``infotest kms`` — foreground KMS operations.

Unlike the old TUI /kms command (daemon threads killed on exit), this runs
subprocesses in the foreground so output streams to the terminal in real time.

Usage::

    infotest kms                       # overall status
    infotest kms status                # overall status
    infotest kms product status        # product knowledge base status
    infotest kms product update        # run mineru_batch_export (foreground)
    infotest kms qa status             # test knowledge base status
    infotest kms qa update             # xlsx→md + mineru (foreground)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def run_kms_command(argv: list[str]) -> int:
    """Dispatch ``infotest kms [namespace] [action]``."""
    parts = [a.lower() for a in argv if a.strip()]

    if not parts or parts == ["status"]:
        return _print_overall_status()

    namespace = parts[0]
    action = parts[1] if len(parts) > 1 else "status"

    if namespace == "product":
        return _handle_product(action)
    if namespace == "qa":
        return _handle_qa(action)

    print(f"Unknown namespace: {namespace!r}. Use: status | product | qa",
          file=sys.stderr)
    return 1


def _print_overall_status() -> int:
    from main.ist_core.tui.kms_command import _format_overall_status
    print(_format_overall_status())
    return 0


def _handle_product(action: str) -> int:
    if action == "status":
        from main.ist_core.tui.kms_command import _format_product_status
        print(_format_product_status())
        return 0
    if action == "update":
        return _run_product_update()
    print(f"Unknown action: {action!r}. Use: status | update", file=sys.stderr)
    return 1


def _handle_qa(action: str) -> int:
    if action == "status":
        from main.ist_core.tui.kms_command import _format_qa_status
        print(_format_qa_status())
        return 0
    if action == "update":
        return _run_qa_update()
    print(f"Unknown action: {action!r}. Use: status | update", file=sys.stderr)
    return 1


def _run_product_update() -> int:
    """Run mineru_batch_export in foreground for product sources."""
    from main.ist_core.tui.kms_command import _orgin_buckets

    if not os.environ.get("MINERU_TOKEN"):
        print("Error: MINERU_TOKEN not set (check environment file)", file=sys.stderr)
        return 1

    buckets = _orgin_buckets()
    product_names = buckets.get("product", [])
    if not product_names:
        print("No product sources found in orgin/")
        return 0

    project_root = _project_root()
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)

    env = dict(os.environ)
    env["KMS_PRODUCT_FILES"] = ",".join(product_names)
    env["KMS_OUTPUT_BUCKET"] = "product"
    env["PYTHONUNBUFFERED"] = "1"

    batch_size = env.get("MINERU_BATCH_SIZE", "30")
    print(f"[kms product update] {len(product_names)} product sources, "
          f"batch_size={batch_size}")
    print(f"[kms product update] output → knowledge/data/markdown/product/")
    print()

    rc = subprocess.call(
        [str(venv_python), "-u", "-m", "main.mineru_batch_export"],
        cwd=str(project_root),
        env=env,
    )
    if rc != 0:
        print(f"\n[kms product update] FAILED (exit code {rc})", file=sys.stderr)
        return rc

    # 转换成功 → 自动后处理：命令手册语法修复 + product 去重 + 垃圾清理。
    # 全部幂等可逆(move 软删)，使一条 update 即产出干净、语法完整、已去重的 KMS。
    # 后处理失败不应推翻转换成果，故捕获异常仅告警。
    try:
        from main.kms_postprocess import run_postprocess, _print_report
        print("\n[kms product update] 转换完成，开始后处理(语法修复+去重)...")
        report = run_postprocess(apply=True)
        _print_report(report)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[kms product update] 后处理告警(转换已成功，不影响产物): {exc}",
              file=sys.stderr)

    print(f"\n[kms product update] done")
    return rc


def _run_qa_update() -> int:
    """Run xlsx→md + mineru for qa sources."""
    from main.ist_core.tui.kms_command import _orgin_buckets, _QA_XLSX_EXTS, _QA_MINERU_EXTS
    from main import knowledge_paths as kp

    buckets = _orgin_buckets()
    qa_files = (list(buckets.get("test_case_list", []))
                + list(buckets.get("test_strategy", [])))
    xlsx_files = [n for n in qa_files if Path(n).suffix.lower() in _QA_XLSX_EXTS]
    mineru_files = [n for n in qa_files if Path(n).suffix.lower() in _QA_MINERU_EXTS]
    skipped = [n for n in qa_files if n not in xlsx_files and n not in mineru_files]

    if not xlsx_files and not mineru_files:
        print("No qa sources found in orgin/")
        return 0

    if mineru_files and not os.environ.get("MINERU_TOKEN"):
        print("Error: MINERU_TOKEN needed for non-xlsx qa files", file=sys.stderr)
        return 1

    if xlsx_files:
        from main.xlsx_to_markdown import write_markdown
        kp.KNOWLEDGE_MARKDOWN_QA.mkdir(parents=True, exist_ok=True)
        print(f"[kms qa update] converting {len(xlsx_files)} xlsx files...")
        for name in xlsx_files:
            src = kp.KNOWLEDGE_ORGIN / name
            out = kp.KNOWLEDGE_MARKDOWN_QA / f"{Path(name).stem}.md"
            try:
                write_markdown(src, out)
                print(f"  ✓ {name} → {out.name}")
            except Exception as exc:
                print(f"  ✗ {name}: {exc}", file=sys.stderr)

    if mineru_files:
        project_root = _project_root()
        venv_python = project_root / ".venv" / "bin" / "python"
        if not venv_python.exists():
            venv_python = Path(sys.executable)

        env = dict(os.environ)
        env["KMS_PRODUCT_FILES"] = ",".join(mineru_files)
        env["KMS_OUTPUT_BUCKET"] = "qa"
        env["PYTHONUNBUFFERED"] = "1"

        print(f"\n[kms qa update] {len(mineru_files)} non-xlsx → mineru_batch_export")
        rc = subprocess.call(
            [str(venv_python), "-u", "-m", "main.mineru_batch_export"],
            cwd=str(project_root),
            env=env,
        )
        if rc != 0:
            print(f"\n[kms qa update] mineru FAILED (exit code {rc})", file=sys.stderr)
            return rc

    if skipped:
        print(f"\n[kms qa update] skipped (unsupported): {', '.join(skipped)}")

    # 转换完成 → qa 桶后处理：仅去重 + 垃圾清理(qa 无命令手册，跳过语法修复)。
    try:
        from main.kms_postprocess import run_postprocess, _print_report
        print("\n[kms qa update] 转换完成，开始后处理(去重)...")
        report = run_postprocess(apply=True, bucket="qa", do_syntax=False)
        _print_report(report)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[kms qa update] 后处理告警(转换已成功，不影响产物): {exc}",
              file=sys.stderr)

    print(f"\n[kms qa update] done")
    return 0
