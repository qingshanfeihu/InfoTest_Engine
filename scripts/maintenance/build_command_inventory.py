# -*- coding: utf-8 -*-
"""构建版本专属 CLI 命令清单(S1 类型图管道第一件交付物;消费方=S6 命令存在性呈报门)。

从 `knowledge/data/markdown/product/manual_<ver>/cli_<ver>_*.md` 全分册解析粗体
命令签名行,产出 `knowledge/data/compile_ref/command_inventory_<ver>.json`
(git tracked 数据文件,含 provenance 与覆盖率自检)。

签名行形态(2026-07-12 预言2 反扫实测,29 分册 3585 粗体行解析覆盖 99.64%):
  **command tokens** _<req> [opt]_     # 同行斜体参数
  **command tokens**                    # 无参数
  **command tokens**\\n_<param>_        # 斜体参数折行(可多行,不跨空行)
  粗体内可含 {on|off} 枚举与 [show|clear] 可选动词。

信任根声明(infra §7.5):本清单无条件信任 ①手册目录版本纯度 ②MinerU 抽取完备性
(已知截断上限)——故消费门形态必须是「呈报不硬拒」(DESIGN §15 D5)。

用法: ~/.venvs/infotest-engine/bin/python scripts/maintenance/build_command_inventory.py [--version 10.5]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BOLD_LINE = re.compile(r"^\*\*(?P<bold>[^*]+(?:\*[^*]+)*?)\*\*\s*(?P<rest>.*)$")
NOISE_BOLD = re.compile(r"^(注意|说明|警告|提示|例如|Note|Caution|Warning|示例)\s*[:：]?\s*$")
PLACEHOLDER = re.compile(r"[<\[]([^<>\[\]]+)[>\]]")
ENUM = re.compile(r"\{([^{}]+)\}")
ITALIC_CONT = re.compile(r"^_[^_]*_?\s*$")


def _register(heads: dict, head: str, src: str, pmax: int, enums: set[str]) -> None:
    """同头多签名取并:pmax 取最大、enums 取并集(匹配规则的宽松方向=少误报呈报)。"""
    e = heads.get(head)
    if e is None:
        heads[head] = {"src": src, "pmax": pmax, "enums": sorted(enums)}
    else:
        e["pmax"] = max(e["pmax"], pmax)
        e["enums"] = sorted(set(e["enums"]) | enums)


def parse_heads(manual_dir: Path, glob: str) -> tuple[dict[str, dict], dict]:
    """全分册解析 → {命令头: {src, pmax, enums}} + 覆盖率统计。

    pmax=签名参数占位符数(同头取最大);enums=粗体内与参数区 {a|b} 枚举词并集——
    消费侧匹配规则依赖两者区分「单 token 头的余量是参数/枚举」vs「是漏记的子关键字」
    (裸 `sdns` 来自 `**sdns {on|off}**`:`sdns on` 合法而 `sdns fulldns on` 不是)。
    """
    heads: dict[str, dict] = {}
    total_bold = n_sigs = n_noise = 0
    for f in sorted(manual_dir.glob(glob)):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, raw in enumerate(lines):
            m = BOLD_LINE.match(raw.rstrip())
            if not m:
                continue
            total_bold += 1
            bold = m.group("bold").strip()
            if NOISE_BOLD.match(bold) or not re.match(
                    r"^([A-Za-z]|\[[a-z|]+\]\s+[A-Za-z])", bold):
                n_noise += 1
                continue
            # 参数区 = 同行剩余 + 紧随的斜体续行(不跨空行,防吸下条命令的孤立斜体)
            zone = m.group("rest").strip()
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt and ITALIC_CONT.match(nxt) and not BOLD_LINE.match(nxt):
                    zone += " " + nxt
                    j += 1
                else:
                    break
            pmax = len(PLACEHOLDER.findall(zone))
            enums: set[str] = set()
            for grp in ENUM.findall(bold) + ENUM.findall(zone):
                for tok in grp.split("|"):
                    tok = tok.strip().strip("_").lower()
                    if tok and re.match(r"^[a-z0-9\-]+$", tok):
                        enums.add(tok)
            # 命令头:剥 {..} 枚举与 <..>[..] 占位,留关键字序列
            head = re.sub(r"\{[^}]*\}", " ", bold)
            head = re.sub(r"[<\[][^<>\[\]]*[>\]]", " ", head)
            head = re.sub(r"\s+", " ", head).strip().lower().rstrip("_ ").strip()
            if not head:
                continue
            n_sigs += 1
            src = f"{f.name}:{i + 1}"
            _register(heads, head, src, pmax, enums)
            # [show|clear] mnet 类可选动词开头:同时登记展开形
            om = re.match(r"^\[([a-z|]+)\]\s+(.+)$", bold.lower())
            if om:
                base = re.sub(r"\s+", " ", re.sub(r"[<\[{][^<>\[\]{}]*[>\]}]", " ",
                                                  om.group(2))).strip()
                for verb in om.group(1).split("|"):
                    _register(heads, f"{verb.strip()} {base}".strip(), src, pmax, enums)
    stats = {"bold_lines": total_bold, "signatures": n_sigs, "noise": n_noise,
             "unique_heads": len(heads),
             "coverage_excl_noise": round(n_sigs / (total_bold - n_noise), 4)
             if total_bold > n_noise else 0.0}
    return heads, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="10.5")
    args = ap.parse_args()
    ver = args.version
    manual_dir = ROOT / "knowledge" / "data" / "markdown" / "product" / f"manual_{ver}"
    if not manual_dir.is_dir():
        raise SystemExit(f"manual dir not found: {manual_dir}")
    heads, stats = parse_heads(manual_dir, f"cli_{ver}_*.md")
    out = ROOT / "knowledge" / "data" / "compile_ref" / f"command_inventory_{ver}.json"
    out.write_text(json.dumps({
        "version": ver,
        "source_dir": str(manual_dir.relative_to(ROOT)),
        "source_glob": f"cli_{ver}_*.md",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generator": "scripts/maintenance/build_command_inventory.py",
        "stats": stats,
        "heads": dict(sorted(heads.items())),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out.relative_to(ROOT)), **stats}, ensure_ascii=False))


if __name__ == "__main__":
    main()
