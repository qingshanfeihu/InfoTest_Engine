"""gap② 写回签名保真:S1 kwarg 剥离 + S3 build 取数源。

起因(docs/forensics/team4_knowledge_fidelity_gaps.md,#54 校准批取证):
- S1:`ssl activate certificate vh1,prompt=YES` 整条被当 CLI 语法写进
  footprint 的 cli.commands——`,prompt=YES` 是 xlsx 执行器 kwarg(mirror
  get_parameter),不是设备语法。每个 PASS case 的每条 G 段命令都复制这类污染,
  与交付规模同增。
- S3:台账 build 位取 config.py 硬编码默认(568),设备实测是 585——K 锚静默失真
  整个 #54 批无人察觉。兜底值必须自报出处(build_source),不得冒充实测。
"""
from __future__ import annotations

from main.ist_core.memory.compile_writeback import _strip_executor_kwargs


# ---------------------------------------------------------------- S1 kwarg 剥离
def test_strips_trailing_executor_kwarg():
    assert _strip_executor_kwargs(
        "ssl activate certificate vh1,prompt=YES") == "ssl activate certificate vh1"


def test_strips_multiple_kwargs():
    assert _strip_executor_kwargs(
        "ssl import key vh1,timeout=60,prompt=YES") == "ssl import key vh1"


def test_keeps_positional_args_that_are_not_kwargs():
    """引号外逗号切出的**位置参**属命令本体,不能剥(get_parameter 同样当位置参)。"""
    assert _strip_executor_kwargs(
        "importKey vh1, cert/rsaca/1024rsa.key") == "importKey vh1,cert/rsaca/1024rsa.key"


def test_segment_with_spaced_key_is_positional_not_kwarg():
    """get_parameter(test_xlsx.py:75-77):`=` 左侧含空格 → 退回位置参,不是 kwarg。"""
    out = _strip_executor_kwargs("slb policy vh1,match host = www.a.com")
    assert "match host = www.a.com" in out, out


def test_no_comma_and_multiline_untouched():
    assert _strip_executor_kwargs("show ssl certificate vh1") == "show ssl certificate vh1"
    multi = "line one,prompt=YES\nline two"
    assert _strip_executor_kwargs(multi) == multi.strip()   # 含换行框架整段单参,不切


def test_not_a_keyname_whitelist():
    """判据是机械形态而非 {prompt,timeout} 白名单——未知键名同样剥(键集随框架版本增长)。"""
    assert _strip_executor_kwargs(
        "ssl activate certificate vh1,some_future_kwarg=1") == "ssl activate certificate vh1"


def test_rawfact_keeps_original_in_raw_invocation():
    """剥离后原文不丢:cli_syntax/fact_key 为语法位,raw_invocation 存设备实发原文。"""
    from main.case_compiler.provenance_ir import StepIR, StepSource
    from main.ist_core.memory.compile_writeback import _g_step_to_rawfacts

    step = StepIR(
        E="APV_0", F="cmd_config", layer="G",
        G="ssl activate certificate vh1,prompt=YES",
        source=StepSource(kind="manual", ref="cli_10.5_Chapter11:1234"),
    )
    facts = _g_step_to_rawfacts(step, autoid="205400000000000003", manual_glob="")
    assert len(facts) == 1
    f = facts[0]
    assert f.fact_key == "ssl activate certificate vh1", f.fact_key
    assert f.cli_syntax == "ssl activate certificate vh1"
    assert f.raw_invocation == "ssl activate certificate vh1,prompt=YES"
    # evidence_quote 是证据门的针(须在手册命中),必须是剥净的语法位而非原文
    assert f.evidence_quote == "ssl activate certificate vh1"


def test_evidence_surfaces_raw_invocation_only_when_it_differs():
    from main.ist_core.memory.footprint.merger import _evidence
    from main.ist_core.memory.footprint.schema import RawFact

    dirty = RawFact(fact_kind="cli_command", feature_path=["ssl", "activate"],
                    fact_key="ssl activate certificate vh1",
                    cli_syntax="ssl activate certificate vh1",
                    evidence_file="m.md", evidence_quote="ssl activate certificate vh1",
                    raw_invocation="ssl activate certificate vh1,prompt=YES")
    assert _evidence(dirty)["raw_invocation"] == "ssl activate certificate vh1,prompt=YES"

    clean = RawFact(fact_kind="cli_command", feature_path=["ssl", "activate"],
                    fact_key="show ssl certificate vh1", cli_syntax="show ssl certificate vh1",
                    evidence_file="m.md", evidence_quote="show ssl certificate vh1",
                    raw_invocation="show ssl certificate vh1")
    assert "raw_invocation" not in _evidence(clean), "健康路径不该多出冗余键"


# ------------------------------------------------------------- S3 build 取数源
def test_ledger_records_build_source_probe(tmp_path, monkeypatch):
    """探针实测 build 下传 → 台账 build_source=probe。"""
    import main.ist_core.tools.device.batch_tools as bt
    monkeypatch.setattr(bt, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(bt, "_xlsx_apv_lines", lambda p: {})
    xlsx = tmp_path / "case.xlsx"
    xlsx.write_bytes(b"x")
    bt._append_verified_runs(xlsx, [{"autoid": "1", "verdict": "pass"}], 0, 1.0,
                             build="..._585", build_source="probe")
    import json
    rec = json.loads((tmp_path / "runtime" / "logs" / "verified_runs.jsonl").read_text().strip())
    assert rec["build"] == "..._585" and rec["build_source"] == "probe"


def test_engine_run_passes_probed_build_down(monkeypatch):
    """引擎 run 节点把 state.device_build 下传给 digest——不传即退 config 兜底(S3 根因)。"""
    import main.ist_core.compile_engine_v8.nodes as nodes
    seen = {}

    def _fake(xlsx_path, autoids_json="", module="", build="", **kw):
        seen["build"] = build
        return "ok"

    class _Tool:
        func = staticmethod(_fake)

    import main.ist_core.tools.device.batch_tools as bt
    monkeypatch.setattr(bt, "dev_run_batch_digest", _Tool)
    nodes._digest_fn("/tmp/x.xlsx", ["1"], "InfosecOS_Beta_APV_HG_K_10_5_0_585")
    assert seen["build"] == "InfosecOS_Beta_APV_HG_K_10_5_0_585"


# ---------------------------------------- P1-D:出处由调用方声明,函数内不许猜
def test_build_without_declared_source_records_unspecified(tmp_path, monkeypatch):
    """「入参非空」只证明有人传了值,不证明它来自探针(凭据≠事实)。未声明 → unspecified。"""
    import main.ist_core.tools.device.batch_tools as bt
    monkeypatch.setattr(bt, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(bt, "_xlsx_apv_lines", lambda p: {})
    xlsx = tmp_path / "case.xlsx"
    xlsx.write_bytes(b"x")
    bt._append_verified_runs(xlsx, [{"autoid": "1", "verdict": "pass"}], 0, 1.0,
                             build="..._585", build_source="")
    import json
    rec = json.loads((tmp_path / "runtime" / "logs" / "verified_runs.jsonl").read_text().strip())
    assert rec["build_source"] == "", "台账字段原样落调用方声明"


def test_digest_tool_exposes_build_source_param():
    """工具签名必须有 build_source 形参——出处是调用方的声明,不是函数的推断。"""
    import inspect
    import main.ist_core.tools.device.batch_tools as bt
    sig = inspect.signature(bt.dev_run_batch_digest.func)
    assert "build_source" in sig.parameters


def test_engine_run_declares_probe_source(monkeypatch):
    """引擎主路的 build 来自 bed 探针 → 显式声明 probe;空 build 不得谎称 probe。"""
    import main.ist_core.compile_engine_v8.nodes as nodes
    import main.ist_core.tools.device.batch_tools as bt
    seen = {}

    class _Tool:
        @staticmethod
        def func(xlsx_path, autoids_json="", module="", build="", build_source="", **kw):
            seen["build"], seen["src"] = build, build_source
            return "ok"

    monkeypatch.setattr(bt, "dev_run_batch_digest", _Tool)
    nodes._digest_fn("/tmp/x.xlsx", ["1"], "InfosecOS_..._585")
    assert seen == {"build": "InfosecOS_..._585", "src": "probe"}
    nodes._digest_fn("/tmp/x.xlsx", ["1"], "")
    assert seen["src"] == "", "无 build 时不得声明 probe"
