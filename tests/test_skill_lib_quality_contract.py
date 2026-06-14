"""quality_contract 静态门离线测试（零设备 / 零网络 / 零 LLM）。

覆盖 plan「归纳技能质量契约」第一批四项静态检查：

  ① 逐 case 硬编码（blocking）——AST 解析 verify.py：autoid 级长数字串字面量
     出现在分支比较 / match 模式即拒；**数据字面量（赋值 / dict 值）不误伤**。
  ② when_to_use 缺 TRIGGER / SKIP（blocking）。
  ③ 缺 verify_script 声明 / 文件不存在 / 不可解析（blocking）。
  ④ params 缺但 body 有疑似硬值（minor，不阻断）。

红线断言：
  - 反模式被拒绝：`if autoid == "778012"` 命中 BLOCKING（且判定不看具体 autoid 值，
    换一批用例规则仍成立——用 778012 与 593516 两批分别命中验证通用性）。
  - 不用正则猜语义：数据 dict `{"778012": 3}` 不被判硬编码（走 AST 上下文，非字符串匹配）。
  - 确定性：同输入同输出。

加载策略：quality_contract 鸭子类型、不 import skill_lib 包内其它模块，可直接 import；
SkillSpec 用于验证鸭子类型对带属性对象同样生效。
"""

from __future__ import annotations

import textwrap

import pytest

from main.case_compiler.skill_lib import quality_contract as qc
from main.case_compiler.skill_lib.quality_contract import (
    BLOCKING,
    MINOR,
    CODE_HARDCODED_CASE_ID,
    CODE_MISSING_TRIGGER,
    CODE_MISSING_SKIP,
    CODE_MISSING_VERIFY_SCRIPT,
    CODE_VERIFY_SCRIPT_NOT_FOUND,
    CODE_VERIFY_SCRIPT_UNPARSEABLE,
    CODE_UNPARAMETERIZED_HARDVALUE,
    Finding,
    check_contract,
    has_blocking,
    passes_contract,
)
from main.case_compiler.skill_lib.schema import SkillSpec


# ── helpers ──────────────────────────────────────────────────────────

def _codes(findings: list[Finding]) -> set[str]:
    return {f.code for f in findings}


def _by_code(findings: list[Finding], code: str) -> list[Finding]:
    return [f for f in findings if f.code == code]


# 一个干净、合规的 verify.py 源码（通用、无硬编码、可解析）。
_CLEAN_VERIFY = textwrap.dedent(
    """
    def verify(payload):
        method = payload.get("method")
        pool = payload.get("pool")
        expected = payload.get("expected_hits", {})
        # 纯通用逻辑：从 payload 自身配置算，绝不看具体 autoid
        total = sum(expected.values())
        return {"ok": total > 0, "method": method, "pool": pool}
    """
)


def _clean_skill(**overrides):
    """构造一条结构合规的技能 dict（默认全过门）。"""
    skill = {
        "name": "counter-distribution-assertion",
        "description": "rr/wrr 分布断言",
        "when_to_use": "TRIGGER: 轮询 权重 分布\nSKIP: 非分布类断言转交 settle-wait",
        "verify_script": "verify.py",
        "params": {"pool_name": {"description": "池名"}},
        "body": "对 $pool_name 做分布校验",
    }
    skill.update(overrides)
    return skill


# ── 正常路径 ─────────────────────────────────────────────────────────

def test_clean_skill_passes_contract():
    """合规技能：无 blocking，结构门通过。"""
    skill = _clean_skill()
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert not has_blocking(findings)
    assert passes_contract(skill, verify_source=_CLEAN_VERIFY)


def test_clean_skill_no_findings_at_all():
    """完全干净（含 params）应零 finding。"""
    skill = _clean_skill()
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert findings == []


# ── ① 逐 case 硬编码（反模式被拒绝）────────────────────────────────────

def test_hardcoded_autoid_in_compare_blocked():
    """`if autoid == "778012"` → BLOCKING（核心反模式）。"""
    src = textwrap.dedent(
        """
        def verify(p):
            if p["autoid"] == "778012":
                return {"ok": True}
            return {"ok": False}
        """
    )
    findings = check_contract(_clean_skill(), verify_source=src)
    hits = _by_code(findings, CODE_HARDCODED_CASE_ID)
    assert hits, "应命中逐 case 硬编码"
    assert hits[0].severity == BLOCKING
    assert hits[0].evidence == "778012"
    assert has_blocking(findings)


def test_hardcoded_rule_is_caseid_agnostic():
    """判定不看具体 autoid 值：换一批 autoid（593516）仍命中。

    守红线①：规则对任意 case 通用，从不写死某个 autoid。
    """
    for autoid in ("778012", "593516", "994957"):
        src = f"def verify(p):\n    return p['x'] == '{autoid}'\n"
        findings = check_contract(_clean_skill(), verify_source=src)
        hits = _by_code(findings, CODE_HARDCODED_CASE_ID)
        assert hits and hits[0].evidence == autoid, f"{autoid} 应命中"


def test_hardcoded_autoid_int_literal_in_compare_blocked():
    """整型 autoid 字面量（!= 778012）同样命中。"""
    src = "def verify(p):\n    return p['n'] != 778012\n"
    findings = check_contract(_clean_skill(), verify_source=src)
    assert CODE_HARDCODED_CASE_ID in _codes(findings)
    assert has_blocking(findings)


def test_hardcoded_autoid_in_match_pattern_blocked():
    """match/case 模式里的 autoid 字面量 → BLOCKING。"""
    src = textwrap.dedent(
        """
        def verify(p):
            match p["autoid"]:
                case "593573":
                    return {"ok": True}
                case _:
                    return {"ok": False}
        """
    )
    findings = check_contract(_clean_skill(), verify_source=src)
    hits = _by_code(findings, CODE_HARDCODED_CASE_ID)
    assert hits and hits[0].evidence == "593573"
    assert "match 模式" in hits[0].message


def test_hardcoded_autoid_in_membership_set_blocked():
    """`autoid in {"778012", "593516"}` → 比较上下文命中（两条都报）。"""
    src = 'def verify(p):\n    return p["a"] in {"778012", "593516"}\n'
    findings = check_contract(_clean_skill(), verify_source=src)
    evidences = {f.evidence for f in _by_code(findings, CODE_HARDCODED_CASE_ID)}
    assert evidences == {"778012", "593516"}


# ── ① 边界：不误伤合法数据字面量 / 短数字 ──────────────────────────────

def test_data_dict_literal_not_flagged():
    """期望映射 expected={"778012": 3} 是数据，不是分支条件 → 不命中。

    守红线②：不用字符串匹配猜，走 AST 上下文（赋值/dict 值不算硬编码）。
    """
    src = textwrap.dedent(
        """
        EXPECTED = {"778012": 3, "593516": 5}
        def verify(p):
            return {"hit": EXPECTED.get(p["id"], 0)}
        """
    )
    findings = check_contract(_clean_skill(), verify_source=src)
    assert CODE_HARDCODED_CASE_ID not in _codes(findings)
    assert not has_blocking(findings)


def test_short_numbers_not_flagged():
    """年份 2026 / 端口 80 / 8080 / 65535 等 ≤5 位不误报。"""
    src = textwrap.dedent(
        """
        def verify(p):
            if p["port"] == 8080:
                return {"y": 2026}
            return p["x"] == 65535 or p["p"] == 80
        """
    )
    findings = check_contract(_clean_skill(), verify_source=src)
    assert CODE_HARDCODED_CASE_ID not in _codes(findings)


def test_bool_literal_not_flagged():
    """True/False（int 子类）在比较里不被当 autoid。"""
    src = "def verify(p):\n    return p['flag'] == True\n"
    findings = check_contract(_clean_skill(), verify_source=src)
    assert CODE_HARDCODED_CASE_ID not in _codes(findings)


def test_dup_caseid_same_line_deduped():
    """同行同 caseid 去重，不重复报。"""
    src = 'def verify(p):\n    return p["a"] == "778012" or p["b"] == "778012"\n'
    findings = check_contract(_clean_skill(), verify_source=src)
    # 同 lineno + 同 caseid 去重 → 仅 1 条
    assert len(_by_code(findings, CODE_HARDCODED_CASE_ID)) == 1


# ── ② when_to_use TRIGGER/SKIP ───────────────────────────────────────

def test_missing_trigger_blocked():
    skill = _clean_skill(when_to_use="SKIP: 非分布类")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert CODE_MISSING_TRIGGER in _codes(findings)
    assert all(f.severity == BLOCKING for f in _by_code(findings, CODE_MISSING_TRIGGER))


def test_missing_skip_blocked():
    skill = _clean_skill(when_to_use="TRIGGER: 轮询 权重")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert CODE_MISSING_SKIP in _codes(findings)


def test_missing_both_trigger_and_skip():
    skill = _clean_skill(when_to_use="随便写点没有范式的说明")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert {CODE_MISSING_TRIGGER, CODE_MISSING_SKIP} <= _codes(findings)


def test_chinese_trigger_skip_accepted():
    """中文「触发 / 跳过」也算范式齐全。"""
    skill = _clean_skill(when_to_use="触发：含轮询/权重\n跳过：非分布场景")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert CODE_MISSING_TRIGGER not in _codes(findings)
    assert CODE_MISSING_SKIP not in _codes(findings)


def test_empty_when_to_use_blocked():
    skill = _clean_skill(when_to_use="")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert {CODE_MISSING_TRIGGER, CODE_MISSING_SKIP} <= _codes(findings)


# ── ③ verify_script 声明 / 存在 / 可解析 ─────────────────────────────

def test_missing_verify_script_blocked():
    """未声明 verify_script 且未传 source → BLOCKING。"""
    skill = _clean_skill(verify_script="")
    findings = check_contract(skill)  # 无 verify_source
    assert CODE_MISSING_VERIFY_SCRIPT in _codes(findings)
    assert has_blocking(findings)


def test_verify_script_file_not_found_blocked(tmp_path):
    """声明了相对路径但文件不存在 → BLOCKING。"""
    skill = _clean_skill(verify_script="verify.py")
    findings = check_contract(skill, skill_dir=tmp_path)
    assert CODE_VERIFY_SCRIPT_NOT_FOUND in _codes(findings)


def test_verify_script_unparseable_source_blocked():
    """直传不可解析源码 → BLOCKING（离线校验跑不通）。"""
    skill = _clean_skill()
    findings = check_contract(skill, verify_source="def verify(:\n  pass")
    assert CODE_VERIFY_SCRIPT_UNPARSEABLE in _codes(findings)
    assert has_blocking(findings)


def test_verify_script_read_from_disk(tmp_path):
    """从磁盘读取真实 verify.py 并 AST 扫描（含硬编码命中）。"""
    vf = tmp_path / "verify.py"
    vf.write_text(
        'def verify(p):\n    return p["a"] == "778012"\n', encoding="utf-8"
    )
    skill = _clean_skill(verify_script="verify.py")
    findings = check_contract(skill, skill_dir=tmp_path)
    assert CODE_VERIFY_SCRIPT_NOT_FOUND not in _codes(findings)
    assert CODE_HARDCODED_CASE_ID in _codes(findings)


def test_verify_script_clean_file_from_disk_passes(tmp_path):
    """磁盘上的干净 verify.py → 无 blocking。"""
    vf = tmp_path / "verify.py"
    vf.write_text(_CLEAN_VERIFY, encoding="utf-8")
    skill = _clean_skill(verify_script="verify.py")
    findings = check_contract(skill, skill_dir=tmp_path)
    assert not has_blocking(findings)


def test_verify_script_absolute_path_from_disk(tmp_path):
    """verify_script 为绝对路径时直接用，不拼 skill_dir。"""
    vf = tmp_path / "abs_verify.py"
    vf.write_text(_CLEAN_VERIFY, encoding="utf-8")
    skill = _clean_skill(verify_script=str(vf))
    findings = check_contract(skill)  # 不给 skill_dir
    assert CODE_VERIFY_SCRIPT_NOT_FOUND not in _codes(findings)
    assert not has_blocking(findings)


def test_skill_dir_from_attribute(tmp_path):
    """skill_dir 可由 skill 自带属性提供（鸭子类型）。"""
    vf = tmp_path / "verify.py"
    vf.write_text(_CLEAN_VERIFY, encoding="utf-8")

    class _S:
        when_to_use = "TRIGGER a\nSKIP b"
        verify_script = "verify.py"
        params = {"x": 1}
        body = "ok"
        skill_dir = tmp_path

    findings = check_contract(_S())
    assert not has_blocking(findings)


# ── ④ params 缺但 body 有疑似硬值（minor）─────────────────────────────

def test_unparameterized_ipv4_minor():
    """无 params + body 含 IPv4 → MINOR（不阻断）。"""
    skill = _clean_skill(params={}, body="配置 slb virtual http v1 192.168.1.5 80")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    hits = _by_code(findings, CODE_UNPARAMETERIZED_HARDVALUE)
    assert hits and hits[0].severity == MINOR
    assert "192.168.1.5" in hits[0].evidence
    # minor 不应阻断
    assert not has_blocking(findings)


def test_unparameterized_long_number_minor():
    skill = _clean_skill(params=None, body="autoid 778012 的回归")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert CODE_UNPARAMETERIZED_HARDVALUE in _codes(findings)


def test_params_declared_skips_body_sniff():
    """已声明 params → 不再嗅探 body 硬值（task 范围限定「params 缺但…」）。"""
    skill = _clean_skill(
        params={"ip": {"description": "地址"}},
        body="slb virtual http v1 192.168.1.5 80",
    )
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert CODE_UNPARAMETERIZED_HARDVALUE not in _codes(findings)


def test_no_params_clean_body_no_minor():
    """无 params 但 body 无魔法字面量 → 不报。"""
    skill = _clean_skill(params={}, body="对 pool 做分布校验，无硬值")
    findings = check_contract(skill, verify_source=_CLEAN_VERIFY)
    assert CODE_UNPARAMETERIZED_HARDVALUE not in _codes(findings)


# ── 鸭子类型：SkillSpec 对象输入 ──────────────────────────────────────

def test_skillspec_object_input(tmp_path):
    """check_contract 接受 schema.SkillSpec 对象（鸭子类型）。"""
    vf = tmp_path / "verify.py"
    vf.write_text(_CLEAN_VERIFY, encoding="utf-8")
    spec = SkillSpec.from_frontmatter(
        {
            "name": "demo",
            "description": "d",
            "when_to_use": "TRIGGER: x\nSKIP: y",
            "verify_script": "verify.py",
            "params": {"pool": "池名"},
        },
        body="对 $pool 校验",
        skill_dir=tmp_path,
    )
    findings = check_contract(spec)
    assert not has_blocking(findings)
    assert passes_contract(spec)


def test_skillspec_object_hardcoded_blocked(tmp_path):
    """SkillSpec 对象 + 硬编码 verify → 拒。"""
    vf = tmp_path / "verify.py"
    vf.write_text('def verify(p):\n    return p["a"] == "994899"\n', encoding="utf-8")
    spec = SkillSpec.from_frontmatter(
        {
            "name": "demo",
            "description": "d",
            "when_to_use": "TRIGGER: x\nSKIP: y",
            "verify_script": "verify.py",
            "params": {"a": "x"},
        },
        body="x",
        skill_dir=tmp_path,
    )
    findings = check_contract(spec)
    assert CODE_HARDCODED_CASE_ID in _codes(findings)
    assert not passes_contract(spec)


# ── 确定性 ───────────────────────────────────────────────────────────

def test_determinism_same_input_same_output():
    """同输入 → 同 Finding 序列（码 / 严重度 / 证据逐字相同）。"""
    skill = _clean_skill(when_to_use="只有说明无范式", params={})
    src = 'def verify(p):\n    return p["a"] == "778012"\n'
    runs = [
        [(f.code, f.severity, f.evidence) for f in check_contract(skill, verify_source=src)]
        for _ in range(5)
    ]
    assert all(r == runs[0] for r in runs)


# ── 组合：多 blocking 同时命中 ───────────────────────────────────────

def test_multiple_blocking_accumulate():
    """缺 TRIGGER/SKIP + 硬编码 + 缺 params 硬值 一次性全报。"""
    skill = _clean_skill(when_to_use="无范式", params={}, body="ip 10.0.0.1")
    src = 'def verify(p):\n    return p["a"] == "778012"\n'
    findings = check_contract(skill, verify_source=src)
    codes = _codes(findings)
    assert {CODE_MISSING_TRIGGER, CODE_MISSING_SKIP, CODE_HARDCODED_CASE_ID} <= codes
    assert CODE_UNPARAMETERIZED_HARDVALUE in codes  # minor
    assert has_blocking(findings)


def test_finding_str_and_is_blocking():
    """Finding.__str__ 含码与位置；is_blocking 与 severity 一致。"""
    f = Finding(code="X", severity=BLOCKING, message="m", location="verify.py:3", evidence="778012")
    assert f.is_blocking is True
    s = str(f)
    assert "X" in s and "verify.py:3" in s and "778012" in s
    assert Finding(code="Y", severity=MINOR, message="m").is_blocking is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
