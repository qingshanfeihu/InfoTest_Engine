"""F3 判例血统分层与防自指((45)/(45b),§18.11 五稿)。

- 血统由路径机械可导:mirror 根 verified_<autoid>.xlsx=engine_verified(机生,自指风险);
  子目录=human_suite(人源)。
- 配额保底:top 全机生但存在有效人源命中 → 置换末位为最高分人源(破自产血统垄断,
  log_backup 型「机制同构、词面遥远」检索不中的实证根治)。
- 血统外显:engine_verified 渲染带「structure only, not an authority」标注。
- 极性禁运文案:先例只供配置形态,断言极性溯源意图/手册(precedent-then-assert 禁)。
"""
from __future__ import annotations

import main.ist_core.tools.device.precedent_tools as pt


def _corpus():
    # 三个机生(cfg 与 query 完全一致→sim=1.0 垄断) + 一个人源(机制同构、词面较远)
    return [
        {"fn": "verified_1.xlsx", "autoid": "1", "intent_self": "写保存 write file",
         "cfg_tokens": {"write", "file", "config", "sdns", "listener"},
         "seq": [("APV_0", "cmd_config", "write file")], "lineage": "engine_verified"},
        {"fn": "verified_2.xlsx", "autoid": "2", "intent_self": "写保存 write file",
         "cfg_tokens": {"write", "file", "config", "sdns", "listener"},
         "seq": [("APV_0", "cmd_config", "write file")], "lineage": "engine_verified"},
        {"fn": "verified_3.xlsx", "autoid": "3", "intent_self": "写保存 write file",
         "cfg_tokens": {"write", "file", "config", "sdns", "listener"},
         "seq": [("APV_0", "cmd_config", "write file")], "lineage": "engine_verified"},
        {"fn": "log_backup_1.xlsx", "autoid": "9", "intent_self": "用户名错误",
         "cfg_tokens": {"write", "config", "sdns", "url"},  # 机制词重叠但少一些
         "seq": [("APV_0", "cmd_config", "write all ftp")], "lineage": "human_suite"},
    ]


def test_lineage_derived_from_path(tmp_path, monkeypatch):
    """路径机械判源:根 verified_ → engine_verified,子目录 → human_suite。"""
    import openpyxl
    monkeypatch.setattr(pt, "_MIRROR_CORPUS_CACHE", None)
    monkeypatch.setattr(pt, "_MIRROR", tmp_path)
    (tmp_path / "smoke_test" / "sdns").mkdir(parents=True)

    def _wb(p, rows):
        wb = openpyxl.Workbook(); ws = wb.active
        for _ in range(28):        # loader 从第 29 行起读(前 28 行是示例/表头区)
            ws.append([])
        for r in rows:
            ws.append(r)
        wb.save(p)
    _wb(tmp_path / "verified_203000000000000001.xlsx",
        [["203000000000000001", "P0", "1", "t", "APV_0", "cmd_config", "sdns on"]])
    _wb(tmp_path / "smoke_test" / "sdns" / "human_case.xlsx",
        [["203000000000000009", "P0", "1", "t", "APV_0", "cmd_config", "sdns on"]])
    corpus = pt._load_mirror_corpus()
    by_fn = {c["fn"]: c for c in corpus}
    assert by_fn["verified_203000000000000001.xlsx"]["lineage"] == "engine_verified"
    assert by_fn["human_case.xlsx"]["lineage"] == "human_suite"


def test_quota_floor_surfaces_human_precedent(monkeypatch):
    """机生垄断 top(limit=3 全机生) → 末位置换为人源命中(可见性保底)。"""
    monkeypatch.setattr(pt, "_load_mirror_corpus", _corpus)
    monkeypatch.setattr(pt, "_load_intent_index", lambda: {})
    hits, _, _ = pt._retrieve_precedent_hits(
        my_config="write file config sdns listener", intent="", limit=3)
    lineages = [h[6] for h in hits]
    assert "human_suite" in lineages          # 人源被保底进结果集
    assert lineages[:2] == ["engine_verified", "engine_verified"]  # 高分机生仍在前


def test_no_quota_swap_when_human_already_present(monkeypatch):
    """结果集已含人源 → 不置换(不破坏正常排序)。"""
    monkeypatch.setattr(pt, "_load_mirror_corpus",
                        lambda: _corpus()[:1] + _corpus()[3:])   # 1 机生 + 1 人源
    monkeypatch.setattr(pt, "_load_intent_index", lambda: {})
    hits, _, _ = pt._retrieve_precedent_hits(
        my_config="write file config sdns listener", intent="", limit=3)
    assert sum(1 for h in hits if h[6] == "human_suite") >= 1


def test_engine_lineage_shown_in_text(monkeypatch):
    monkeypatch.setattr(pt, "_load_mirror_corpus", _corpus)
    monkeypatch.setattr(pt, "_load_intent_index", lambda: {})
    monkeypatch.setattr(pt, "_load_precedent_annotations", lambda: {})
    _, text = pt.precedent_best_and_text(
        my_config="write file config sdns listener", intent="", limit=2)
    assert "not an authority" in text          # engine_verified 血统外显


def test_polarity_ban_wording_present(monkeypatch):
    monkeypatch.setattr(pt, "_load_mirror_corpus", _corpus)
    monkeypatch.setattr(pt, "_load_intent_index", lambda: {})
    monkeypatch.setattr(pt, "_load_precedent_annotations", lambda: {})
    _, text = pt.precedent_best_and_text(my_config="write file", intent="", limit=1)
    assert "polarity" in text and "precedent-then-assert" in text


def test_legacy_corpus_without_lineage_field(monkeypatch):
    """旧桩/存量语料无 lineage 字段 → get 兜底 human_suite,7 元组解包不崩。"""
    monkeypatch.setattr(pt, "_load_mirror_corpus", lambda: [
        {"fn": "x.xlsx", "autoid": "1", "intent_self": "t",
         "cfg_tokens": {"sdns", "host"}, "seq": [("APV_0", "cmd_config", "sdns on")]}])
    monkeypatch.setattr(pt, "_load_intent_index", lambda: {})
    hits, _, _ = pt._retrieve_precedent_hits(my_config="sdns host", intent="", limit=2)
    assert hits and hits[0][6] == "human_suite"
