"""将 G 列内容写入 xlsx，输出到 outputs/filled_<原名>.xlsx。

用法: python scripts/write_g_column.py <xlsx_path> <g_updates_json> [--overwrite]
  g_updates_json: '{"5": "G列内容", "8": "G列内容", ...}'
  --overwrite: 覆盖已有内容的 G 列单元格（用于验证修正）
"""
import json
import sys
from pathlib import Path

import openpyxl


def write_g_column(xlsx_path: str, g_updates: dict[str, str], overwrite: bool = False) -> str:
    src = Path(xlsx_path).resolve()
    out_dir = Path('workspace/outputs').resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Already a filled file → overwrite in place; otherwise add filled_ prefix
    if src.parent == out_dir and src.name.startswith('filled_'):
        out_path = src
    else:
        out_path = out_dir / f'filled_{src.name}'

    # Only block if source is in inputs/ and output would collide
    if src.parent != out_dir and src == out_path:
        print(json.dumps({"error": f"refuse to overwrite source file: {src}"}, ensure_ascii=False))
        sys.exit(1)

    wb = openpyxl.load_workbook(str(src))
    ws = wb.active
    skipped = 0
    written = 0
    for row_num_str, value in g_updates.items():
        row_num = int(row_num_str)
        cell = ws.cell(row=row_num, column=7)
        if cell.value and str(cell.value).strip():
            if overwrite:
                cell.value = value
                written += 1
            else:
                skipped += 1
            continue
        cell.value = value
        written += 1

    wb.save(str(out_path))
    print(json.dumps({
        "output": str(out_path),
        "written": written,
        "skipped": skipped,
        "overwrite": overwrite,
    }, ensure_ascii=False, indent=2))
    return str(out_path)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: write_g_column.py <xlsx_path> <g_updates_json> [--overwrite]"}, ensure_ascii=False))
        sys.exit(1)
    updates = json.loads(sys.argv[2])
    overwrite = '--overwrite' in sys.argv
    write_g_column(sys.argv[1], updates, overwrite=overwrite)
