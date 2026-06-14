"""skill_lib.registry 离线回归测试（Phase 0 技能库基建）。

覆盖：
  - 正常：扫描技能目录 → SkillSpec 解析 → 内容寻址 hash → 落盘 / 读回 round-trip。
  - 确定性：同输入同 catalog_hash / content_hash（守红线 3）。
  - diff：增 / 删 / 改正确识别。
  - realpath dedup：软链指向同一 SKILL.md 只收一次。
  - 同名裁决：source 优先级（induced > hand）胜出。
  - 边界：空目录 / 缺 SKILL.md / frontmatter 解析失败 / 结构非法跳过。
  - **反模式被拒绝**：结构非法（fork 缺 agent / 非法 context）的伪技能不入库。

纯离线（不依赖设备 / 网络 / runtime 现有快照），临时目录隔离。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.case_compiler.skill_lib.registry import SkillRegistry, RegistryEntry
from main.case_compiler.skill_lib.schema import SkillSpec


# ── 测试夹具：在 tmp 目录里造技能 ──────────────────────────────────────

def _write_skill(skills_dir: Path, name: str, frontmatter: str, body: str = "body") -> Path:
    """在 skills_dir/<name>/SKILL.md 写一条技能，返回目录。"""
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8"
    )
    return d


_GOOD_FM = """\
name: {name}
description: {desc}
when_to_use: |
  Use when 用户要做 {name}。
  TRIGGER: {name}, do-{name}
  SKIP when: 其他场景。
context: inline
source: {source}
effort: medium
"""


def _good(skills_dir: Path, name: str, desc: str = "demo skill",
          source: str = "hand", body: str = "body text") -> Path:
    return _write_skill(skills_dir, name,
                        _GOOD_FM.format(name=name, desc=desc, source=source), body)


# ── 正常路径 ─────────────────────────────────────────────────────────

def test_scan_parses_skills(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    _good(sk, "beta")
    reg = SkillRegistry.scan(sk)
    assert len(reg) == 2
    assert reg.names() == ["alpha", "beta"]
    entry = reg.get("alpha")
    assert isinstance(entry, RegistryEntry)
    assert entry.spec.name == "alpha"
    assert entry.content_hash == entry.spec.content_hash()


def test_content_hash_deterministic(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    _good(sk, "beta")
    h1 = SkillRegistry.scan(sk).catalog_hash()
    h2 = SkillRegistry.scan(sk).catalog_hash()
    assert h1 == h2
    assert len(h1) == 16  # sha256[:16]


def test_spec_content_hash_excludes_evidence(tmp_path):
    """A-B evidence 不进技能内容指纹（版本演进 hash 稳定）。"""
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    base = SkillRegistry.scan(sk).get("alpha").spec
    # 同名同 body，附不同 evidence → content_hash 不变
    fm = {
        "name": "alpha", "description": "demo skill",
        "when_to_use": "TRIGGER: alpha\nSKIP when: x",
        "context": "inline", "source": "hand",
        "evidence": {"induced_from": ["778012"], "version": 7,
                     "ab_test": {"with_pass": 3, "with_total": 3,
                                 "without_pass": 1, "without_total": 3}},
    }
    spec_with_ev = SkillSpec.from_frontmatter(fm, body=base.body)
    spec_no_ev = SkillSpec.from_frontmatter(
        {k: v for k, v in fm.items() if k != "evidence"}, body=base.body)
    assert spec_with_ev.content_hash() == spec_no_ev.content_hash()
    # 但 body 变 → hash 必变
    spec_diff_body = SkillSpec.from_frontmatter(fm, body=base.body + " more")
    assert spec_diff_body.content_hash() != spec_with_ev.content_hash()


# ── 落盘 / 读回 round-trip ───────────────────────────────────────────

def test_save_load_latest_roundtrip(tmp_path):
    sk = tmp_path / "skills"
    reg_dir = tmp_path / "registry"
    _good(sk, "alpha")
    _good(sk, "beta", body="beta body")
    reg = SkillRegistry.scan(sk)
    path = reg.save(reg_dir)
    assert path.is_file()
    assert (reg_dir / "latest.json").is_file()

    loaded = SkillRegistry.load_latest(reg_dir)
    assert loaded is not None
    assert loaded.names() == reg.names()
    assert loaded.catalog_hash() == reg.catalog_hash()
    # spec 内容指纹经序列化往返不变（body 一并落盘）
    for n in reg.names():
        assert loaded.get(n).spec.content_hash() == reg.get(n).spec.content_hash()


def test_load_missing_returns_none(tmp_path):
    reg_dir = tmp_path / "registry"
    assert SkillRegistry.load_latest(reg_dir) is None
    assert SkillRegistry.load("deadbeef", reg_dir) is None


def test_to_from_dict_roundtrip(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha", body="payload")
    reg = SkillRegistry.scan(sk)
    reg2 = SkillRegistry.from_dict(reg.to_dict())
    assert reg2.catalog_hash() == reg.catalog_hash()
    assert reg2.get("alpha").spec.body == "payload"


# ── diff ─────────────────────────────────────────────────────────────

def test_diff_added_removed_changed(tmp_path):
    sk1 = tmp_path / "skills_v1"
    _good(sk1, "alpha", desc="v1 desc")
    _good(sk1, "gamma")
    old = SkillRegistry.scan(sk1)

    sk2 = tmp_path / "skills_v2"
    _good(sk2, "alpha", desc="v2 changed desc")  # changed (desc → hash 变)
    _good(sk2, "beta")                            # added
    # gamma removed
    new = SkillRegistry.scan(sk2)

    report = SkillRegistry.diff(old, new)
    assert report["catalog_changed"] is True
    assert report["added"] == ["beta"]
    assert report["removed"] == ["gamma"]
    assert [c["name"] for c in report["changed"]] == ["alpha"]
    chg = report["changed"][0]
    assert chg["old_hash"] != chg["new_hash"]


def test_diff_none_old_is_all_added(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    new = SkillRegistry.scan(sk)
    report = SkillRegistry.diff(None, new)
    assert report["added"] == ["alpha"]
    assert report["removed"] == []
    assert report["old_catalog_hash"] == ""


def test_diff_identical_no_change(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    a = SkillRegistry.scan(sk)
    b = SkillRegistry.scan(sk)
    report = SkillRegistry.diff(a, b)
    assert report["catalog_changed"] is False
    assert report["added"] == report["removed"] == report["changed"] == []


# ── realpath dedup ───────────────────────────────────────────────────

def test_realpath_dedup_symlink(tmp_path):
    """软链指向同一 SKILL.md 的目录只收一次（cc-haha realpath dedup）。"""
    sk = tmp_path / "skills"
    real = _good(sk, "alpha")
    link = sk / "alpha-link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not supported on this platform")
    reg = SkillRegistry.scan(sk)
    # 同一真实 SKILL.md → 只一条
    assert len(reg) == 1
    assert reg.names() == ["alpha"]


# ── 同名裁决（source 优先级） ────────────────────────────────────────

def test_same_name_induced_beats_hand(tmp_path):
    """同名不同真实文件：induced 新归纳胜 hand 旧版本（plan 陷阱 4）。"""
    sk = tmp_path / "skills"
    # 两个不同目录、同 skill name、不同 source（hand 先扫到，induced 后扫到）
    _good(sk, "a_hand_dir", desc="hand version", source="hand", body="hand body")
    _good(sk, "z_induced_dir", desc="induced version", source="induced",
          body="induced body")
    # 把两者的 name 改成相同（frontmatter name 决定 registry key）
    for d, nm, src, body in [("a_hand_dir", "shared", "hand", "hand body"),
                             ("z_induced_dir", "shared", "induced", "induced body")]:
        (sk / d / "SKILL.md").write_text(
            f"---\nname: shared\ndescription: {src} version\n"
            f"when_to_use: |\n  TRIGGER: shared\n  SKIP when: x\n"
            f"context: inline\nsource: {src}\n---\n\n{body}\n",
            encoding="utf-8")
    reg = SkillRegistry.scan(sk)
    assert reg.names() == ["shared"]
    # induced 胜出
    assert reg.get("shared").spec.source == "induced"
    assert reg.get("shared").spec.body == "induced body"


# ── 边界 / 异常 ──────────────────────────────────────────────────────

def test_empty_dir(tmp_path):
    reg = SkillRegistry.scan(tmp_path / "nonexistent")
    assert len(reg) == 0
    assert reg.catalog_hash() == SkillRegistry({}).catalog_hash()


def test_missing_skill_md_skipped(tmp_path):
    sk = tmp_path / "skills"
    (sk / "no_md").mkdir(parents=True)   # 目录无 SKILL.md
    _good(sk, "alpha")
    reg = SkillRegistry.scan(sk)
    assert reg.names() == ["alpha"]


def test_malformed_frontmatter_skipped(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    # 非法 YAML frontmatter（无法 safe_load）
    bad = sk / "broken"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\nname: broken\n  bad: : indent: :\n---\nbody\n", encoding="utf-8")
    reg = SkillRegistry.scan(sk)
    # broken 被跳过，alpha 仍在
    assert reg.names() == ["alpha"]


def test_non_dict_frontmatter_skipped(tmp_path):
    """合法 YAML 但 frontmatter 非 mapping（bare list / scalar）→ 只跳过该技能。

    回归：此前 scan() 把 list/str frontmatter 传给 from_frontmatter，
    `or {}` 对 truthy 的 list 不生效，首个 fm.get(...) 抛 AttributeError，
    整库扫描连带崩溃（whole-catalog blast radius）。修复后单技能跳过 + warning，
    其余合法技能不受影响。
    """
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    # frontmatter 是 bare list → yaml.safe_load 产出 list
    bad_list = sk / "listfm"
    bad_list.mkdir()
    (bad_list / "SKILL.md").write_text(
        "---\n- a\n- b\n---\n\nbody\n", encoding="utf-8")
    # frontmatter 是 scalar string → yaml.safe_load 产出 str
    bad_scalar = sk / "scalarfm"
    bad_scalar.mkdir()
    (bad_scalar / "SKILL.md").write_text(
        "---\njust a bare string\n---\n\nbody\n", encoding="utf-8")
    reg = SkillRegistry.scan(sk)
    # 两个非法 frontmatter 被跳过，alpha 幸存（整库未崩）
    assert reg.names() == ["alpha"]


def test_non_dict_frontmatter_from_frontmatter_coerces(tmp_path):
    """防御纵深：from_frontmatter 直接收到 list/str 也不崩，coerce 成空 dict。"""
    spec_from_list = SkillSpec.from_frontmatter(["a", "b"], body="x")  # type: ignore[arg-type]
    spec_from_str = SkillSpec.from_frontmatter("bare", body="x")        # type: ignore[arg-type]
    spec_from_none = SkillSpec.from_frontmatter(None, body="x")         # type: ignore[arg-type]
    # 非 mapping → 字段取默认（name 空 → basic_errors 会拦，但构造本身不抛）
    assert spec_from_list.name == ""
    assert spec_from_str.name == ""
    assert spec_from_none.name == ""


# ── 反模式 / 结构非法被拒绝 ──────────────────────────────────────────

def test_fork_skill_missing_agent_rejected(tmp_path):
    """fork 技能缺 agent → 结构非法，不入库（basic_errors 拦截）。"""
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    _write_skill(sk, "forky",
                 "name: forky\ndescription: fork no agent\n"
                 "when_to_use: 'TRIGGER: forky'\ncontext: fork\nsource: hand")
    reg = SkillRegistry.scan(sk)
    assert "forky" not in reg.names()
    assert reg.names() == ["alpha"]


def test_invalid_context_rejected(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    _write_skill(sk, "weird",
                 "name: weird\ndescription: bad ctx\n"
                 "when_to_use: 'TRIGGER: weird'\ncontext: telepathy\nsource: hand")
    reg = SkillRegistry.scan(sk)
    assert "weird" not in reg.names()


def test_missing_name_rejected(tmp_path):
    sk = tmp_path / "skills"
    _good(sk, "alpha")
    _write_skill(sk, "noname",
                 "description: has no name field\n"
                 "when_to_use: 'TRIGGER: x'\ncontext: inline")
    reg = SkillRegistry.scan(sk)
    assert reg.names() == ["alpha"]


def test_per_case_hardcoded_skill_rejected_by_contract(tmp_path):
    """逐 case 硬编码（autoid 字面量分支）的伪技能：结构层不拦，但内容寻址保留可审计。

    本测试断言「红线意识」：registry 是发现/索引层，反模式语义拦截归 quality_contract.py
    （未在本模块）。这里验证含 autoid 硬编码的 body 仍被忠实内容寻址（不臆造、不静默改写），
    其内容 hash 与去掉硬编码后的版本不同 —— 为后续静态门提供可比对的确定性指纹。
    """
    sk = tmp_path / "skills"
    _write_skill(sk, "rewrite778012",
                 "name: rewrite778012\ndescription: rewrite case\n"
                 "when_to_use: 'TRIGGER: rewrite'\ncontext: inline\nsource: hand",
                 body='if autoid == "778012":\n    do_special()')
    reg = SkillRegistry.scan(sk)
    # 结构合法 → 入库（发现层不做语义拦截），但 body 被忠实保留供质量契约审计
    assert "rewrite778012" in reg.names()
    spec = reg.get("rewrite778012").spec
    assert 'autoid == "778012"' in spec.body
    # 去掉硬编码后内容指纹不同（为静态门提供确定性对比锚点）
    clean = SkillSpec.from_frontmatter(
        {"name": "rewrite778012", "description": "rewrite case",
         "when_to_use": "TRIGGER: rewrite", "context": "inline", "source": "hand"},
        body="if matches_pool(case):\n    do_special()")
    assert clean.content_hash() != spec.content_hash()


# ── 真实技能目录冒烟（不依赖外部，仅确认能扫真实库且确定性） ──────────

def test_scan_real_skills_dir_deterministic():
    reg1 = SkillRegistry.scan()      # 默认 main/ist_core/skills
    reg2 = SkillRegistry.scan()
    assert reg1.catalog_hash() == reg2.catalog_hash()
    assert len(reg1) >= 1
    # 落盘+读回确定性（用 to_dict/from_dict 避免触碰 runtime/）
    reg3 = SkillRegistry.from_dict(reg1.to_dict())
    assert reg3.catalog_hash() == reg1.catalog_hash()


def test_real_skill_save_isolated_dir(tmp_path):
    """真实库落盘到隔离 tmp 目录，确认 <hash>.json + latest.json 结构。"""
    reg = SkillRegistry.scan()
    reg_dir = tmp_path / "reg"
    path = reg.save(reg_dir)
    assert path.name == f"{reg.catalog_hash()}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["catalog_hash"] == reg.catalog_hash()
    assert "skills" in payload
    ptr = json.loads((reg_dir / "latest.json").read_text(encoding="utf-8"))
    assert ptr["catalog_hash"] == reg.catalog_hash()
