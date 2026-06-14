"""框架镜像层：把跳转机 apv_src 的实证用例 + 能力源增量同步到本地 mirror/。

设计（计划 todo `framework-sync`）：
- **实证用例是准确性的最强证据源**：跳转机 smoke_test/ 下数百个在目标设备目标版本上
  真实跑通的 xlsx，挖成 idiom 模式库 + 命令实证语法 + check_point 写法（specification
  mining），优先级高于 OCR 失真的手册。
- **内容寻址增量同步**（抄 [[mineru_source_index]] 模式）：远端逐文件 sha256（在跳转机算，
  一次 find+sha256sum 批量取），与本地 meta.json 对比，只拉变化的；跳转机零写入。
- **白名单**：只同步 smoke_test/（用例）+ lists/（run 清单，case_id↔autoid 关联）+
  lib/apv/（能力源 apv_action.py/apv_synonyms，KP2 用）。不抄整个 apv_src。
- mirror/ 进 .gitignore（量大、可重建）；derived/（idiom 库等挖掘产物）git 跟踪。

凭据复用 device_mcp_client（env IST_JUMPHOST_PASS，不落盘）。同步纯 SFTP 只读拉取。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from main.case_compiler.device_mcp_client import _connect, JUMPHOST

_ROOT = Path(__file__).resolve().parent.parent
_MIRROR = _ROOT / "knowledge" / "framework" / "mirror"
_META = _MIRROR / ".sync_meta.json"
_APV_SRC = "/home/test/apv_src"

# 同步白名单：(远端相对 apv_src 的子树, 文件名 glob 列表)
# 注：_remote_hashes 用 `find -type f` 拉取，天然排除 test_xlsx.py 符号链接（-type l）。
# .py 用例是跨模块只读先例弹药（ssl/slb/system 等零 xlsx 模块的唯一已验证来源）：
# 全产品 ~1.3 万 .py 此前被"只抓 xlsx"挡在门外。corpus._parse_py_case 只收数字命名用例，
# conftest.py 也一并拉下供 ef_spec 采集设备 fixture 别名（Seg0 等）。
_SYNC_SPEC = [
    ("smoke_test", ["*.xlsx", "*.py"]),         # 实证用例（xlsx 可直转 + .py 跨模块先例）
    ("lists", ["*"]),                           # run 清单（case_id↔autoid）
    ("lib/apv", ["apv_action.py", "apv_synonyms"]),  # KP2 能力源
]


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_meta() -> dict:
    if _META.is_file():
        try:
            return json.loads(_META.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "by_path": {}, "synced_at": None}


def _save_meta(meta: dict) -> None:
    _META.parent.mkdir(parents=True, exist_ok=True)
    tmp = _META.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_META)


def _remote_hashes(ssh, subtree: str, globs: list) -> dict:
    """在跳转机一次性算子树下白名单文件的 sha256，返回 {相对apv_src路径: sha256}。

    远端用 find + sha256sum 批量，避免逐文件往返。
    """
    name_expr = " -o ".join("-name '%s'" % g for g in globs)
    cmd = (
        "cd %s && find %s \\( %s \\) -type f -print0 2>/dev/null "
        "| xargs -0 sha256sum 2>/dev/null"
    ) % (_APV_SRC, subtree, name_expr)
    _si, so, _se = ssh.exec_command(cmd, timeout=120)
    out = so.read().decode("utf-8", "replace")
    result = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            h, rel = parts
            result[rel.strip()] = h
    return result


def sync(verbose: bool = True) -> dict:
    """增量同步白名单子树到本地 mirror/。返回 {pulled, skipped, removed, total}。"""
    meta = _load_meta()
    by_path = meta.get("by_path", {})
    ssh = _connect()
    pulled, skipped = [], []
    seen = set()
    try:
        sftp = ssh.open_sftp()
        for subtree, globs in _SYNC_SPEC:
            remote = _remote_hashes(ssh, subtree, globs)
            if verbose:
                print("[%s] 远端 %d 个文件" % (subtree, len(remote)))
            for rel, rhash in sorted(remote.items()):
                seen.add(rel)
                local_path = _MIRROR / rel
                if by_path.get(rel) == rhash and local_path.is_file():
                    skipped.append(rel)
                    continue
                local_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = local_path.with_suffix(local_path.suffix + ".tmp")
                sftp.get("%s/%s" % (_APV_SRC, rel), str(tmp))
                tmp.replace(local_path)
                by_path[rel] = rhash
                pulled.append(rel)
                if verbose:
                    print("  pulled %s" % rel)
        sftp.close()
    finally:
        ssh.close()
    # 清理：本地有但远端已不在白名单结果里的（被删的用例）
    removed = []
    for rel in list(by_path.keys()):
        if rel not in seen:
            p = _MIRROR / rel
            if p.is_file():
                p.unlink()
            del by_path[rel]
            removed.append(rel)
    meta["by_path"] = by_path
    meta["synced_at"] = _utc_now()
    meta["source"] = JUMPHOST
    _save_meta(meta)
    summary = {
        "pulled": len(pulled), "skipped": len(skipped),
        "removed": len(removed), "total": len(by_path),
    }
    if verbose:
        print("同步完成：拉取 %d / 跳过 %d / 删除 %d / 共 %d"
              % (summary["pulled"], summary["skipped"], summary["removed"], summary["total"]))
    return summary


if __name__ == "__main__":
    sync()
