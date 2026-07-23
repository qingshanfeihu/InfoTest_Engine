"""mirror 同步锚(§18.3;公式审计 D 级最危险项——恒真门/found 语义门全族的单点假设)。

恒真断言六门、窗口语义、H 名字空间、IP 恢复契约、per-case 清理辖区(τ 责任集的 F2)
全部从盘上 mirror 源码推导——若 mirror ≠ 真机框架,整族门的推导前提静默失效。
本模块做一件事:关键文件 sha256 与跳板机真机框架对账。

失败语义(INV-11):mismatch=呈报 needs_ask(用户确认框架升级后更新 mirror);
remote 不可达=unknown,告警+入 findings 不拦批(SSH 抖动不该挡上机;锚未验证的
事实入账,连续未验证的风险由用户在报告里看见)。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 推导消费方在册的关键文件(相对 mirror 根;新增消费面时同步扩表)
ANCHOR_FILES = [
    "lib/test_xlsx.py",      # found/not_found 窗口语义、H 名字空间、执行序——恒真门六族
    "lib/check_point.py",    # PASS/FAIL 计分、断言判定——(2) oracle 解析
    "lib/ssh_server.py",     # IP 恢复契约、read_until——框架 IP 契约门
    "smoke_test/conftest.py",  # per-case 清理辖区(τ 责任集 F2)、abort 语义
]


def _mirror_root() -> Path:
    from main.knowledge_paths import KNOWLEDGE_ROOT
    return Path(KNOWLEDGE_ROOT) / "framework" / "mirror"


def local_hashes(root: Path | None = None) -> dict[str, str]:
    root = root or _mirror_root()
    out: dict[str, str] = {}
    for rel in ANCHOR_FILES:
        p = root / rel
        if p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def remote_hashes(remote_exec, apv_src: str = "") -> dict[str, str]:
    """跳板机真机框架 hash。remote_exec(cmd)->str 注入(shell 执行,失败抛/返 error)。"""
    import os
    src = apv_src or os.environ.get("IST_APV_SRC", "/home/test/apv_src")
    paths = " ".join(f"{src}/{rel}" for rel in ANCHOR_FILES)
    out = str(remote_exec(f"sha256sum {paths} 2>/dev/null") or "")
    hashes: dict[str, str] = {}
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            for rel in ANCHOR_FILES:
                if parts[1].endswith(rel):
                    hashes[rel] = parts[0]
    return hashes


def check_sync(remote_exec, root: Path | None = None) -> dict:
    """对账:{status: match|mismatch|unknown, diffs, missing_local, missing_remote}。

    M-14:missing_local=ANCHOR_FILES 在本地不存在的子集——旧实现只 hash 已存在文件,
    缺文件时仍可对剩余子集判 match,承诺的 missing_local 字段永不计算。
    """
    root = root or _mirror_root()
    missing_local = [rel for rel in ANCHOR_FILES if not (root / rel).is_file()]
    loc = local_hashes(root)
    if not loc:
        return {"status": "unknown", "reason": "mirror files missing locally",
                "missing_local": missing_local, "missing_remote": [], "diffs": []}
    try:
        rem = remote_hashes(remote_exec)
    except Exception as e:  # noqa: BLE001
        logger.warning("mirror 锚远端探测失败", exc_info=True)
        return {"status": "unknown", "reason": f"remote unreachable: {e}"[:200],
                "missing_local": missing_local, "missing_remote": [], "diffs": []}
    if not rem:
        return {"status": "unknown", "reason": "remote returned no hashes",
                "missing_local": missing_local, "missing_remote": [], "diffs": []}
    diffs = [rel for rel in ANCHOR_FILES
             if rel in loc and rel in rem and loc[rel] != rem[rel]]
    missing_remote = [rel for rel in loc if rel not in rem]
    # 本地缺锚文件=推导前提不完整,不得报 match(R075)
    status = "mismatch" if (diffs or missing_local) else "match"
    rep = {"status": status, "diffs": diffs,
           "missing_local": missing_local, "missing_remote": missing_remote,
           "checked": sorted(set(loc) & set(rem))}
    try:  # 基线留痕(供离线对照与漂移历史)
        anchor = root / ".sync_anchor.json"
        anchor.write_text(json.dumps({"local": loc, "remote": rem, "status": status,
                                      "missing_local": missing_local},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("锚基线落盘失败(不阻断,漂移历史缺一笔)", exc_info=True)
    return rep
