"""词表单一源合流回归(2026-07-13):destructive_commands 与 persistence 的 py 内联
已合流到 grammar,消费方读同一源——防双源再漂移(合流前 shutdown/halt/poweroff 只在
emit py、clear config all 只在 grammar JSON,覆盖面不等)。"""
from __future__ import annotations

from main.ist_core.tools.device.emit_xlsx_tool import _gate_destructive_commands as gate
from main.case_compiler.tau_coverage import _is_persist


def _g(cmd):
    return gate("c", [{"E": "APV_0", "F": "cmd_config", "G": cmd}])


def test_emit_destructive_reads_grammar_full_set():
    """emit 自毁门覆盖 grammar 全集:生命周期动词(含 system 前缀)+ 整机清配。"""
    for c in ("system reboot", "reboot", "reload", "shutdown", "halt", "poweroff",
              "clear config all", "restore factory default"):
        assert _g(c) is not None, c
    # 对象级 clear 照常放行(范式要用)——不被合流误伤
    for c in ("clear sdns all", "clear slb all", "write memory", "config memory"):
        assert _g(c) is None, c


def test_tau_persist_reads_grammar_local_disk():
    """tau 持久面分流覆盖 grammar local_disk 全集(含合流并入的 segment 变体)。"""
    for c in ("write memory", "write file f1", "config all", "config net",
              "write segment", "config segment"):
        assert _is_persist(c), c
    for c in ("sdns on", "no vlan v1", "show sdns"):
        assert not _is_persist(c), c


def test_destructive_object_scoped_clear_not_matched():
    """grammar 单一源:整机 clear config all 拦、对象级 clear sdns/slb 不拦(护栏非误伤)。"""
    from main.ist_core.tools.device.emit_xlsx_tool import _destructive_res
    res = _destructive_res()
    assert any(r.search("clear config all") for r in res)
    assert not any(r.search("clear sdns all") for r in res)
    assert not any(r.search("clear slb all") for r in res)


# ── F4 执行器契约文法段(§18.11;句法门经审查不建,收敛为数据+知识) ──────────

def test_executor_contract_grammar_section():
    """domain_grammar 有 executor_contract 段,含 prompt/timeout kwarg + 出处。"""
    from main.case_compiler.domain_grammar import load_grammar
    ec = load_grammar().get("executor_contract") or {}
    keys = {k.get("key") for k in (ec.get("kwargs") or [])}
    assert "prompt" in keys and "timeout" in keys
    assert "get_parameter" in ec.get("_provenance", "")   # 出处=源码,非硬编码
    assert "不建" in ec.get("_provenance", "")             # 句法门不建的诚实记录
