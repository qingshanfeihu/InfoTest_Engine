"""将 G 列内容写入 xlsx，已有内容的行自动跳过，输出到 outputs/filled_<原名>.xlsx。

用法: python scripts/write_g_column.py <xlsx_path> <g_updates_json>
  g_updates_json: '{"5": "G列内容", "8": "G列内容", ...}'
"""
import json
import sys
from pathlib import Path

import openpyxl


def write_g_column(xlsx_path: str, g_updates: dict[str, str]) -> str:
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    skipped = 0
    written = 0
    for row_num_str, value in g_updates.items():
        row_num = int(row_num_str)
        cell = ws.cell(row=row_num, column=7)
        if cell.value and str(cell.value).strip():
            skipped += 1
            continue
        cell.value = value
        written += 1

    out_dir = Path('workspace/outputs')
    out_dir.mkdir(parents=True, exist_ok=True)
    src_name = Path(xlsx_path).name
    out_path = str(out_dir / f'filled_{src_name}')
    wb.save(out_path)
    print(json.dumps({
        "output": out_path,
        "written": written,
        "skipped": skipped,
    }, ensure_ascii=False, indent=2))
    return out_path


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: write_g_column.py <xlsx_path> <g_updates_json>"}, ensure_ascii=False))
        sys.exit(1)
    updates = json.loads(sys.argv[2])
    write_g_column(sys.argv[1], updates)
