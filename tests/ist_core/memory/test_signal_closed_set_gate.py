"""emit_signal 字面量信号名闭集守门(静态 AST 扫描)。

起因(2026-07-20 team4 Py-Eng 审计):`command_existence_miss` /
`command_existence_evidence_accepted` 两个调用点的信号名从未入 SIGNALS 闭集——
落盘时被 emit_signal 降级改写成 `_unknown:<name>`,于是按**原名** fs_grep
runtime/logs/k_signals.jsonl 恒零命中。台账里有痕迹、检索却查不到,是假阴性,
与 #54「signal 查错文件」同型:观测设施自身静默走样,比没有观测更坏。

本门静态扫全仓 emit_signal(...) 调用点的首个字面量实参,断言 ∈ SIGNALS。
非字面量(变量/f-string)首参跳过——那类由调用方自证,静态判不了。

不覆盖 `_unknown:` 降级机制本身:它是兜底(宁可留走样痕迹也不吞),保留。
"""
from __future__ import annotations

import ast
from pathlib import Path

from main.ist_core.memory.footprint.signals import SIGNALS

_MAIN = Path(__file__).resolve().parents[3] / "main"


def _literal_signal_names() -> list[tuple[str, str, int]]:
    """→ [(signal_name, 相对路径, 行号)];只收首参是字符串字面量的调用点。"""
    found: list[tuple[str, str, int]] = []
    for py in _MAIN.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover — 仓内应恒可解析
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name != "emit_signal" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((first.value, str(py.relative_to(_MAIN.parent)), node.lineno))
    return found


def test_call_sites_found_at_all():
    """扫描器自身的活性门:扫不到调用点=断言恒真的假绿(信号只授权它实际量到的)。"""
    sites = _literal_signal_names()
    assert len(sites) >= 10, f"emit_signal 字面量调用点仅扫到 {len(sites)} 处,扫描器可能失效"


def test_every_literal_signal_is_registered():
    orphans = [(n, f, ln) for n, f, ln in _literal_signal_names() if n not in SIGNALS]
    assert not orphans, (
        "以下 emit_signal 信号名不在 SIGNALS 闭集,落盘会被改写成 `_unknown:<name>`,"
        "按原名检索恒零命中(假阴性)——补进闭集并写清信号语义:\n"
        + "\n".join(f"  - {n!r}  @ {f}:{ln}" for n, f, ln in orphans)
    )
