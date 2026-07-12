# -*- coding: utf-8 -*-
"""版本专属 CLI 命令清单加载与成员判定(S6 命令存在性呈报门的数据面)。

数据源: `knowledge/data/compile_ref/command_inventory_<ver>.json`
(由 scripts/maintenance/build_command_inventory.py 从版本专属 CLI 手册机械解析,
带 provenance 与覆盖率自检——机械闭集从源解析、不手抄,红线不变)。

判定语义(理论 (33) 版本参数化;DESIGN §15-S6/§16.2-F):
「命令 ∈ S(build) 的命令集」经最长前缀词匹配近似——手册记载有已知截断上限
(MinerU,infra §7.5 信任根),故本模块只产**判定事实**,消费门形态必须是
「呈报不硬拒」(D5:未命中→needs_decision 携检索证明,不拒绝产出)。

匹配规则(2026-07-12 对 yzg 交付卷全量反扫校准,误报=0 见测试):
- 最长前缀命中多词头(≥2 token) → 通过(余量视为参数);
- 命中单 token 头:余量首词 ∈ 该头枚举词(`sdns {on|off}` → `sdns on`)
  或该头有参数位(`ping <ip>`) → 通过;否则不通过——余量是漏记的子关键字
  (`sdns fulldns on` 不得经裸 `sdns` 假通过,668059 三轮设备学费的病根);
- 未命中时剥前导 no/show/clear 重试(手册多数分立记载,此为宽松兜底——
  宽松方向=少误报呈报,漏检由上机 oracle 兜底,方向安全)。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_INV_DIR = _ROOT / "knowledge" / "data" / "compile_ref"
_CACHE: dict[str, dict] = {}

# 单 token 头有参数位时,允许的余量上界=pmax+松弛(可选参数/截断容差)
_PARAM_SLACK = 2
# 命令行最大取头长度(手册最长命令头实测 <= 7 词)
_MAX_HEAD_TOKENS = 8


def inventory_path(version: str) -> Path:
    return _INV_DIR / f"command_inventory_{version}.json"


def available_versions() -> list[str]:
    return sorted(p.stem.replace("command_inventory_", "")
                  for p in _INV_DIR.glob("command_inventory_*.json"))


def load_inventory(version: str = "") -> dict | None:
    """加载清单(进程内缓存)。version 空时:env IST_COMMAND_INVENTORY_VERSION →
    盘上恰有一份则用之 → 否则 None(门 fail-open,如实不判)。"""
    ver = (version or os.getenv("IST_COMMAND_INVENTORY_VERSION", "")).strip()
    if not ver:
        vs = available_versions()
        if len(vs) != 1:
            return None
        ver = vs[0]
    if ver in _CACHE:
        return _CACHE[ver]
    p = inventory_path(ver)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.debug("command inventory 读取失败: %s", p, exc_info=True)
        return None
    if not isinstance(data.get("heads"), dict):
        return None
    _CACHE[ver] = data
    return data


def _norm_tokens(cmd: str) -> list[str]:
    return re.sub(r"\s+", " ", (cmd or "").strip().lower()).split(" ") if (cmd or "").strip() else []


def _try_match(tokens: list[str], heads: dict) -> tuple[str, dict] | None:
    for k in range(min(len(tokens), _MAX_HEAD_TOKENS), 0, -1):
        head = " ".join(tokens[:k])
        entry = heads.get(head)
        if entry is None:
            continue
        rem = tokens[k:]
        if not rem or k >= 2:
            return head, entry
        # 单 token 头:余量须可解释为枚举值或参数
        if rem[0] in set(entry.get("enums") or ()):
            return head, entry
        pmax = int(entry.get("pmax") or 0)
        if pmax > 0 and len(rem) <= pmax + _PARAM_SLACK:
            return head, entry
        # 命中但余量无法解释——继续尝试更短前缀无意义(已是最长),判不通过
        return None
    return None


def match_command(cmd: str, version: str = "") -> dict:
    """判定单条命令是否落在版本命令集内。

    Returns: {"decided": bool, "hit": bool, "head": str, "src": str, "version": str}
      decided=False = 清单不可用,门应 fail-open。
    """
    inv = load_inventory(version)
    if inv is None:
        return {"decided": False, "hit": False, "head": "", "src": "", "version": ""}
    heads = inv["heads"]
    tokens = _norm_tokens(cmd)
    if not tokens or not re.match(r"^[a-z\[]", tokens[0]):
        # 非命令形态(空/注释/提示符残片)不判——门只管命令行
        return {"decided": False, "hit": False, "head": "", "src": "",
                "version": inv.get("version", "")}
    m = _try_match(tokens, heads)
    if m is None and tokens[0] in ("no", "show", "clear") and len(tokens) > 1:
        m = _try_match(tokens[1:], heads)
    if m is None:
        return {"decided": True, "hit": False, "head": "", "src": "",
                "version": inv.get("version", "")}
    head, entry = m
    return {"decided": True, "hit": True, "head": head,
            "src": str(entry.get("src", "")), "version": inv.get("version", "")}


def nearest_heads(cmd: str, k: int = 3, version: str = "") -> list[str]:
    """呈报辅助:按前缀词重合度取最近似的已记载命令头(帮用户分辨 typo vs 版本缺失)。"""
    inv = load_inventory(version)
    if inv is None:
        return []
    tokens = _norm_tokens(cmd)
    if not tokens:
        return []
    scored: list[tuple[int, int, str]] = []
    for head in inv["heads"]:
        ht = head.split(" ")
        n = 0
        while n < len(ht) and n < len(tokens) and ht[n] == tokens[n]:
            n += 1
        if n:
            scored.append((-n, len(ht), head))
    scored.sort()
    return [h for _, _, h in scored[:k]]
