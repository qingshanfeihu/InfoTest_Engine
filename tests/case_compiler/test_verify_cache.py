"""上机 pass 缓存：内容哈希键控 + 通过不重跑 + 内容变自动失效。"""

from __future__ import annotations

from main.case_compiler import verify_cache as vc
from main.case_compiler.provenance_ir import RUNTIME_PLACEHOLDER


def test_content_hash_stable_and_sensitive():
    rows = [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"},
            {"E": "check_point", "F": "found", "G": "172.16.34.70"}]
    h1 = vc.case_content_hash(rows)
    assert h1 == vc.case_content_hash(list(rows))          # 稳定
    rows2 = [dict(rows[0]), {**rows[1], "G": "172.16.34.71"}]
    assert vc.case_content_hash(rows2) != h1               # 内容变→哈希变


def test_has_unfilled_runtime():
    assert vc.has_unfilled_runtime([{"E": "check_point", "F": "found", "G": RUNTIME_PLACEHOLDER}])
    assert vc.has_unfilled_runtime([{"E": "check_point", "F": "found", "G": r"Hits:\s*<RUNTIME>"}])
    assert not vc.has_unfilled_runtime([{"E": "check_point", "F": "found", "G": "42"}])


def test_cache_roundtrip_and_pass_logic(tmp_path):
    cache = vc.load_cache(tmp_path)
    assert cache == {}
    vc.record_pass(cache, "a1", "hashA", build="b", task_id="t")
    vc.save_cache(tmp_path, cache)
    reloaded = vc.load_cache(tmp_path)
    assert vc.is_cached_pass(reloaded, "a1", "hashA")       # 命中
    assert not vc.is_cached_pass(reloaded, "a1", "hashB")   # 内容变(哈希不符)→不命中
    assert not vc.is_cached_pass(reloaded, "a2", "hashA")   # 没记过→不命中


def test_invalidate():
    cache = {}
    vc.record_pass(cache, "a1", "h")
    vc.invalidate(cache, "a1")
    assert not vc.is_cached_pass(cache, "a1", "h")


def test_recompile_changes_hash_invalidates_cache():
    """重编译改了 case 内容 → 哈希变 → 旧 pass 失效（不会拿旧 pass 蒙混）。"""
    rows_v1 = [{"E": "APV_0", "F": "cmds_config", "G": "sdns on\nsdns listener 172.16.34.70"},
               {"E": "check_point", "F": "found", "G": "172.16.35.231"}]
    cache = {}
    vc.record_pass(cache, "a1", vc.case_content_hash(rows_v1))
    # 重编译后 init 多了一步
    rows_v2 = [{"E": "APV_0", "F": "cmds_config", "G": "sdns on\nsdns dc name dc1\nsdns listener 172.16.34.70"},
               {"E": "check_point", "F": "found", "G": "172.16.35.231"}]
    assert vc.is_cached_pass(cache, "a1", vc.case_content_hash(rows_v1))      # 原内容仍命中
    assert not vc.is_cached_pass(cache, "a1", vc.case_content_hash(rows_v2))  # 新内容失效→需重跑
