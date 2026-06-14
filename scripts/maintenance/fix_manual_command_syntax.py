#!/usr/bin/env python
"""CLI/app 手册命令语法行定点修复 — 用本地 pypdf 重抽覆盖 MinerU 截断的语法行。

MinerU 对"命令名独占一行 + 参数另起行"的跨行语法块系统性丢参数
（CLI 手册截断率 98.8%、app 手册约 61-63%）。本工具：

  1. pypdf 重建 PDF 的 {命令名: 完整语法行}（含 < > [ ] { } 参数，连字归一）。
  2. 在对应 md 里用**反向锚定法**定位语法定义行（不是示例行）：
       找以「该命令/此命令/该参数」开头的中文说明行 → 向上跳空行 → 上一行
       若为「行首小写英文 + 无 CJK + 非 <table> + 非 # + 不在代码块内」即语法定义行。
     —— 关键：语法定义行多数**不含** <>[] 符号（被截断吃掉了），故绝不能用
        "含参数符号" 或 "全文 startswith 命令名"(会命中示例行) 定位。
  3. 命令头(前 2-4 token，去符号 + \\_→_)二次校验一致后，替换为本地完整版，
     保留 md 的 `_`→`\_` 转义风格。
  4. patch 前备份原 md 到 .intermediate/.md_backup/<时间无关的固定名>/。

默认 ``--dry-run`` 打印将改的行；``--apply`` 真写（含备份）。

用法::

    python -m scripts.maintenance.fix_manual_command_syntax --manual cli_74          # dry-run
    python -m scripts.maintenance.fix_manual_command_syntax --manual cli_74 --apply
    python -m scripts.maintenance.fix_manual_command_syntax --all --apply            # 4 套全跑
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from pypdf import PdfReader  # noqa: E402

_ORGIN = _ROOT / "knowledge/data/orgin"
_MD_DIR = _ROOT / "knowledge/data/markdown/product"
_BACKUP_DIR = _ROOT / "knowledge/.intermediate/.md_backup"

# 手册配置：stem → (PDF 文件名, [md 分卷名])
_MANUALS: dict[str, tuple[str, list[str]]] = {
    "cli_74": ("cli_74.pdf",
               ["cli_74__part1_p1-200.md", "cli_74__part2_p201-400.md",
                "cli_74__part3_p401-525.md"]),
    "10.5_cli": ("10.5_cli.pdf",
                 ["10.5_cli__part1_p1-200.md", "10.5_cli__part2_p201-400.md",
                  "10.5_cli__part3_p401-528.md"]),
    "app_21": ("app_21.pdf",
               ["app_21__part1_p1-200.md", "app_21__part2_p201-364.md"]),
    "10.5_app": ("10.5_app.pdf",
                 ["10.5_app__part1_p1-200.md", "10.5_app__part2_p201-365.md"]),
}

# app 手册无 "该命令" 中文锚点（反向锚定命中 0），改用形态锚定 + 纯截断守卫。
_FORM_ANCHOR_MANUALS = {"app_21", "10.5_app"}

_CMD_NAME = re.compile(r"^[a-z][a-z0-9 _\-]+$")
_PARAM_LINE = re.compile(r"[<>\[\]{}|]")
_CJK = re.compile(r"[一-鿿]")
_DESC_START = ("该命令", "此命令", "该参数")
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
              "ﬅ": "st", "ﬆ": "st"}


def _delig(s: str) -> str:
    for lig, rep in _LIGATURES.items():
        s = s.replace(lig, rep)
    return s


def _is_param_continuation(line: str) -> bool:
    s = line.strip()
    if not s or _CJK.search(s):
        return False
    return bool(_PARAM_LINE.search(s))


def _fix_underscore_artifact(s: str) -> str:
    """修 pypdf 把参数名下划线拆成带空格的伪影：``<timeout _ minutes>`` → ``<timeout_minutes>``。

    仅在 <>[]{} 包裹的参数 token 内部合并 ``词 _ 词`` / ``词_ 词`` / ``词 _词``，
    不动命令头与正常空格分隔的 token。
    """
    # 仅处理 ` _ ` / ` _` / `_ ` 这种被空格隔开的下划线（真实参数名里 _ 两侧无空格）
    return re.sub(r"(?<=\w)\s*_\s*(?=\w)", "_", s)


def reconstruct_blocks(pdf_path: Path) -> dict[str, str]:
    """pypdf 重建 {命令名: 完整语法行}。"""
    reader = PdfReader(str(pdf_path))
    blocks: dict[str, str] = {}
    for pg in reader.pages:
        lines = [ln.rstrip() for ln in (pg.extract_text() or "").splitlines()]
        i = 0
        while i < len(lines):
            name = lines[i].strip()
            if _CMD_NAME.match(name) and 2 <= len(name) <= 60:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                params: list[str] = []
                k = j
                while k < len(lines) and _is_param_continuation(lines[k]):
                    params.append(lines[k].strip())
                    k += 1
                if params:
                    full = _delig(re.sub(r"\s+", " ", name + " " + " ".join(params)).strip())
                    full = _fix_underscore_artifact(full)
                    blocks[name] = full
                    i = k
                    continue
            i += 1
    return blocks


def _cmd_head(s: str, n: int = 4) -> str:
    """取语法行的命令头（前 n 个不含符号的小写词），去 \\_、归一。"""
    s = _delig(s.replace("\\_", "_"))
    toks: list[str] = []
    for t in s.split():
        if _PARAM_LINE.search(t) or t.startswith("<"):
            break
        if not re.fullmatch(r"[a-z0-9_\-]+", t):
            break
        toks.append(t)
        if len(toks) >= n:
            break
    return " ".join(toks)


def _full_head(s: str) -> str:
    """完整命令头：到第一个含 <>[]{}| 的 token 前的全部小写命令词（无 token 数上限）。

    用前 4 token 做匹配键会把共享前缀的不同子命令(slb group method rr/grr/sr...)
    折叠到同一 PDF 块、互相覆盖(2026-06-11 曾误改 619 行)。完整头在 PDF 块里唯一
    (实测 cli_74 2180 块 0 歧义)，是正确的匹配键。
    """
    s = _delig(s.replace("\\_", "_"))
    toks: list[str] = []
    for t in s.split():
        if _PARAM_LINE.search(t) or t.startswith("<"):
            break
        if not re.fullmatch(r"[a-z0-9_\-]+", t):
            break
        toks.append(t)
    return " ".join(toks)


def _escape_underscores(s: str) -> str:
    """把参数名里的 _ 还原成 md 的 \\_ 转义风格（仅在 <>[]{} 内或参数 token）。"""
    # 简单稳妥：整行非命令头部分的 _ 转义。这里直接对全行的 _ 转义（md 渲染等价）。
    return s.replace("_", "\\_")


def _mark_code_blocks(lines: list[str]) -> list[bool]:
    in_code = [False] * len(lines)
    flag = False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            flag = not flag
            in_code[i] = True
            continue
        in_code[i] = flag
    return in_code


def find_syntax_lines(md_lines: list[str]) -> list[tuple[int, str]]:
    """反向锚定：返回 [(行号, 命令头)]，定位语法定义行（非示例行）。"""
    in_code = _mark_code_blocks(md_lines)
    targets: list[tuple[int, str]] = []
    for di, ln in enumerate(md_lines):
        if not ln.strip().startswith(_DESC_START):
            continue
        j = di - 1
        while j >= 0 and not md_lines[j].strip():
            j -= 1
        if j < 0:
            continue
        prev = md_lines[j].strip()
        if not re.match(r"^[a-z]", prev):
            continue
        if "<table>" in prev or prev.startswith("#"):
            continue
        if _CJK.search(prev):
            continue
        if in_code[j]:
            continue
        head = _cmd_head(prev)
        if head:
            targets.append((j, head))
    return targets


# app 手册无 "该命令" 锚点（反向锚定命中 0），命令以已截断的**语法形态行**散落正文。
# 改用形态识别：行已含 <>[]{}| 元字符（=语法行而非中文说明），且不含引号字面值 /
# IPv4 字面量（那是示例行，绝不能动）。配合 fix_manual 的纯截断守卫，只补不改写。
_LITERAL_QUOTE = re.compile(r"\"[^\"]+\"")
_LITERAL_IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")


def _is_syntax_form(s: str) -> bool:
    if not re.match(r"^[a-z]", s):
        return False
    if _CJK.search(s):
        return False
    if not _PARAM_LINE.search(s):
        return False
    if _LITERAL_QUOTE.search(s) or _LITERAL_IPV4.search(s):
        return False
    return True


def find_syntax_form_lines(md_lines: list[str]) -> list[tuple[int, str]]:
    """形态锚定：返回 [(行号, 命令头)]，定位**已是语法形态但可能被截断**的行。"""
    targets: list[tuple[int, str]] = []
    for i, ln in enumerate(md_lines):
        s = ln.strip()
        if not _is_syntax_form(s):
            continue
        head = _cmd_head(s)
        if head:
            targets.append((i, head))
    return targets


def _norm_for_prefix(s: str) -> str:
    """归一化用于纯截断前缀判定：去 \\_ 转义、去下划线拆分伪影、压空白。"""
    s = _delig(s.replace("\\_", "_"))
    s = re.sub(r"(?<=\w)\s*_\s*(?=\w)", "_", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_pure_truncation(old_line: str, new_line: str) -> bool:
    """纯截断补全判定：旧行（归一化）必须是新行（归一化）的**前缀**。

    保证只是「补上被截断的后续参数」，而非参数改名（real_name→real_service）或
    必选/可选翻转（<port>→[port]）等语义改写。前缀不成立则拒改。
    """
    o, n = _norm_for_prefix(old_line), _norm_for_prefix(new_line)
    return len(n) > len(o) and n.startswith(o)


def fix_manual(stem: str, apply: bool) -> dict:
    pdf_name, md_names = _MANUALS[stem]
    pdf_path = _ORGIN / pdf_name
    blocks = reconstruct_blocks(pdf_path)
    # 用**完整命令头**索引 PDF 块（实测唯一、0 歧义）。绝不用前 N token，
    # 否则共享前缀的不同子命令会折叠互相覆盖。
    pdf_by_full_head: dict[str, str] = {}
    for full in blocks.values():
        pdf_by_full_head[_full_head(full)] = full

    stats = {"manual": stem, "pdf_blocks": len(blocks),
             "md_targets": 0, "matched": 0, "patched": 0,
             "no_local": 0, "already_ok": 0, "corrupt_blocked": 0,
             "not_truncation": 0, "samples": []}

    # cli 手册有 "该命令" 中文锚点 → 反向锚定；app 手册无锚点 → 形态锚定 + 纯截断守卫。
    use_form = stem in _FORM_ANCHOR_MANUALS

    for md_name in md_names:
        md_path = _MD_DIR / md_name
        if not md_path.exists():
            continue
        text = md_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        targets = find_syntax_form_lines(lines) if use_form else find_syntax_lines(lines)
        stats["md_targets"] += len(targets)
        changed = False

        for lineno, _head in targets:
            old_line = lines[lineno]
            mh = _full_head(old_line)
            if not mh:
                stats["no_local"] += 1
                continue
            # 完整头**精确匹配** PDF 块；匹配不上(命令头被截断/残缺)就跳过，绝不猜测
            local = pdf_by_full_head.get(mh)
            if not local:
                stats["no_local"] += 1
                continue
            stats["matched"] += 1
            new_line = _escape_underscores(local)
            if old_line.strip() == new_line.strip():
                stats["already_ok"] += 1
                continue
            # 防折叠铁律：新行完整头必须与旧行完整头逐字一致，否则拒改
            if _full_head(new_line) != mh:
                stats["corrupt_blocked"] += 1
                continue
            # 形态锚定模式额外守卫：只接受纯截断补全（旧行是新行前缀），
            # 拒绝参数改名 / 必选可选翻转等语义改写（防误伤）。
            if use_form and not _is_pure_truncation(old_line, new_line):
                stats["not_truncation"] += 1
                continue
            if len(stats["samples"]) < 15:
                stats["samples"].append({
                    "md": md_name, "line": lineno + 1,
                    "old": old_line.strip()[:90],
                    "new": new_line.strip()[:120],
                })
            lines[lineno] = new_line
            stats["patched"] += 1
            changed = True

        if apply and changed:
            # 备份
            bak = _BACKUP_DIR / stem / md_name
            bak.parent.mkdir(parents=True, exist_ok=True)
            if not bak.exists():
                bak.write_text(text, encoding="utf-8")
            md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="CLI/app 手册命令语法行定点修复")
    ap.add_argument("--manual", choices=list(_MANUALS), help="单个手册 stem")
    ap.add_argument("--all", action="store_true", help="处理全部 4 套手册")
    ap.add_argument("--apply", action="store_true", help="真写（默认 dry-run）")
    args = ap.parse_args()

    if args.all:
        manuals = list(_MANUALS)
    elif args.manual:
        manuals = [args.manual]
    else:
        ap.error("需指定 --manual <stem> 或 --all")

    print(f"[mode] {'APPLY' if args.apply else 'DRY-RUN'}\n")
    for stem in manuals:
        s = fix_manual(stem, args.apply)
        print(f"=== {stem} ===")
        print(f"  PDF重建块: {s['pdf_blocks']}  md语法行: {s['md_targets']}  "
              f"匹配: {s['matched']}  {'已改' if args.apply else '将改'}: {s['patched']}  "
              f"无本地源(跳过不猜): {s['no_local']}  已正确: {s['already_ok']}  "
              f"防折叠拦截: {s['corrupt_blocked']}  非纯截断跳过: {s['not_truncation']}")
        for ex in s["samples"][:6]:
            print(f"    L{ex['line']} ({ex['md']}):")
            print(f"      旧: {ex['old']}")
            print(f"      新: {ex['new']}")
        print()
    if not args.apply:
        print("(dry-run，未改任何文件。确认后加 --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
