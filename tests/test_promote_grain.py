"""FIX-9 promote_case 粒度回归（本地纯逻辑单测，不连跳转机/不上机）。

跳转机侧 device_mcp_server/tools.py 是 Py3.8 黑盒，无法在本地真实环境跑。
本套件把路径规划 / lists 解析 / manifest 防撞抽成的纯函数直接验证，再对
promote_case 编排层用 monkeypatch 把模块级路径常量（STAGING_PARENT / LISTS_DIR）
重定向到 tmp_path，mock 文件系统验证整链路，不触网、不连设备。

固化的契约（来自 FIX-9 要求）：
- **file vs case 粒度**：P1 产物 = 单 feature 单 xlsx（含 N case）。promote 按
  **文件**整体晋升，保留原文件名，绝不切成 <autoid>.xlsx 丢失同文件其他 case。
- **lists 生产关联**：晋升后写入/更新 lists/<list_name>，否则生产 run 选不中。
- **autoid 命名空间防撞**：同 autoid 不同 source 不互相覆盖（报冲突，除非 overwrite）。
- **向后兼容**：老调用 promote_case(module, autoid) 不报错。
"""

from __future__ import annotations

import os

import pytest

from main.device_mcp_server import tools


# ── 纯函数：_feature_from_xlsx ────────────────────────────────────────

def test_feature_from_xlsx_strips_dir_and_ext():
    assert tools._feature_from_xlsx("/a/b/sdns_dns64.xlsx") == "sdns_dns64"
    assert tools._feature_from_xlsx("slb_group.XLSX") == "slb_group"  # 大小写后缀
    assert tools._feature_from_xlsx("no_ext") == "no_ext"


# ── 纯函数：plan_promote_paths（文件级粒度核心契约）──────────────────

def test_plan_promote_keeps_basename_not_autoid():
    """整文件晋升必须保留源文件名，不能切成 <autoid>.xlsx 丢同文件其他 case。"""
    plan = tools.plan_promote_paths(
        "/apv/smoke_test/sdns", "sdns", "sdns_dns64", "sdns_dns64.xlsx"
    )
    assert plan["feature_dir"] == "/apv/smoke_test/sdns/sdns_dns64"
    assert plan["dst_xlsx"] == "/apv/smoke_test/sdns/sdns_dns64/sdns_dns64.xlsx"
    # 关键：目标文件名 == 源 basename，而非任何单个 autoid
    assert os.path.basename(plan["dst_xlsx"]) == "sdns_dns64.xlsx"
    assert not os.path.basename(plan["dst_xlsx"]).startswith("autoid")


def test_plan_promote_symlink_depth():
    """test_xlsx.py 软链深度：smoke_test/<module>/<feature>/ → apv_src/lib 上跳 3 层。"""
    plan = tools.plan_promote_paths(
        "/apv/smoke_test/sdns", "sdns", "feat", "feat.xlsx"
    )
    assert plan["link"] == "/apv/smoke_test/sdns/feat/test_xlsx.py"
    assert plan["link_target"] == "../../../lib/test_xlsx.py"


# ── 纯函数：parse_list_caseids ───────────────────────────────────────

def test_parse_list_caseids_exec_rows():
    text = (
        "| exec | sdns_10_5_001 |\n"
        "# 注释行\n"
        "\n"
        "| exec | sdns_10_5_002 |\n"
    )
    assert tools.parse_list_caseids(text) == ["sdns_10_5_001", "sdns_10_5_002"]


def test_parse_list_caseids_dedup_preserves_order():
    text = "| exec | aaa_1111 |\n| exec | bbb_2222 |\n| exec | aaa_1111 |\n"
    assert tools.parse_list_caseids(text) == ["aaa_1111", "bbb_2222"]


def test_parse_list_caseids_empty():
    assert tools.parse_list_caseids("") == []
    assert tools.parse_list_caseids("   \n# only comment\n") == []


# ── 纯函数：render_list_text / merge_list_text ───────────────────────

def test_render_list_text_format():
    assert tools.render_list_text(["x_1234567"]) == "| exec | x_1234567 |\n"
    assert tools.render_list_text([]) == ""


def test_merge_list_text_appends_only_missing():
    existing = "| exec | old_111111 |\n"
    merged, added = tools.merge_list_text(existing, ["old_111111", "new_222222"])
    assert added == ["new_222222"]
    # 旧条目原样保留在前，新增追加在后
    assert tools.parse_list_caseids(merged) == ["old_111111", "new_222222"]


def test_merge_list_text_into_empty():
    merged, added = tools.merge_list_text("", ["a_1111111", "b_2222222"])
    assert added == ["a_1111111", "b_2222222"]
    assert tools.parse_list_caseids(merged) == ["a_1111111", "b_2222222"]


# ── 纯函数：register_manifest（autoid 防撞）──────────────────────────

def test_register_manifest_fresh():
    m, conflicts = tools.register_manifest(
        {}, ["c_001", "c_002"], "srcA", "feat", "feat.xlsx"
    )
    assert conflicts == []
    assert m["c_001"]["source"] == "srcA"
    assert m["c_002"]["feature"] == "feat"


def test_register_manifest_same_source_no_conflict():
    base = {"c_001": {"source": "srcA", "feature": "f", "xlsx": "f.xlsx"}}
    m, conflicts = tools.register_manifest(base, ["c_001"], "srcA", "f", "f.xlsx")
    assert conflicts == []  # 同来源重复晋升幂等


def test_register_manifest_cross_source_conflict():
    base = {"c_001": {"source": "srcA", "feature": "fa", "xlsx": "fa.xlsx"}}
    m, conflicts = tools.register_manifest(base, ["c_001"], "srcB", "fb", "fb.xlsx")
    assert len(conflicts) == 1
    assert conflicts[0]["autoid"] == "c_001"
    assert conflicts[0]["existing_source"] == "srcA"
    assert conflicts[0]["new_source"] == "srcB"
    # 冲突项未被覆盖
    assert m["c_001"]["source"] == "srcA"


def test_register_manifest_overwrite():
    base = {"c_001": {"source": "srcA", "feature": "fa", "xlsx": "fa.xlsx"}}
    m, conflicts = tools.register_manifest(
        base, ["c_001"], "srcB", "fb", "fb.xlsx", overwrite=True
    )
    assert conflicts == []
    assert m["c_001"]["source"] == "srcB"  # 强制覆盖


# ── 编排层：promote_case（monkeypatch 模块路径常量 → tmp_path）────────

@pytest.fixture
def staged(tmp_path, monkeypatch):
    """搭一个 fake 跳转机文件树：staging_parent + lists_dir 都指向 tmp。

    返回 (staging_parent, lists_dir, make_feature_xlsx)。
    """
    staging_parent = tmp_path / "smoke_test" / "sdns"
    lists_dir = tmp_path / "lists"
    staging_parent.mkdir(parents=True)
    lists_dir.mkdir(parents=True)
    monkeypatch.setattr(tools, "STAGING_PARENT", str(staging_parent))
    monkeypatch.setattr(tools, "LISTS_DIR", str(lists_dir))

    def make_feature_xlsx(name, content=b"PK_fake_xlsx"):
        p = tmp_path / name
        p.write_bytes(content)
        return str(p)

    return str(staging_parent), str(lists_dir), make_feature_xlsx


def test_promote_file_level_keeps_all_cases(staged):
    """xlsx_path + case_autoids：整文件晋升，dst 名 == 源名，lists 收全部 case。"""
    staging_parent, lists_dir, make_xlsx = staged
    src = make_xlsx("sdns_dns64.xlsx")

    autoids = ["sdns_10_5_001", "sdns_10_5_002", "sdns_10_5_003"]
    res = tools.promote_case(
        "sdns",
        feature="sdns_dns64",
        xlsx_path=src,
        case_autoids=autoids,
        source="run_20260611",
    )

    # 文件级粒度：晋升后是整个 feature xlsx，文件名保留
    dst = res["promoted"]
    assert dst.endswith("/sdns_dns64/sdns_dns64.xlsx")
    assert os.path.isfile(dst)
    assert res["cases"] == autoids

    # lists 生产：三个 case 全部写入 lists/sdns
    assert res["lists_updated"] is True
    list_path = os.path.join(lists_dir, "sdns")
    assert os.path.isfile(list_path)
    with open(list_path) as f:
        cids = tools.parse_list_caseids(f.read())
    assert cids == autoids

    # test_xlsx.py 软链建立
    link = os.path.join(os.path.dirname(dst), "test_xlsx.py")
    assert os.path.islink(link)


def test_promote_backward_compat_module_autoid(staged):
    """老签名 promote_case(module, autoid)：从 staging case.xlsx 晋升单 case，不报错。"""
    staging_parent, lists_dir, _ = staged
    # 造旧 staging 布局 ist_staging_sdns/<autoid>/case.xlsx
    autoid = "legacy_001"
    stg = os.path.join(staging_parent, "ist_staging_sdns", autoid)
    os.makedirs(stg)
    with open(os.path.join(stg, "case.xlsx"), "wb") as f:
        f.write(b"PK_legacy")

    res = tools.promote_case("sdns", autoid)

    assert "error" not in res
    assert res["cases"] == [autoid]
    # feature 退回 autoid，文件名保留 case.xlsx（源 basename）
    assert res["promoted"].endswith("/legacy_001/case.xlsx")
    assert os.path.isfile(res["promoted"])
    # lists 也登记了这个单 case
    assert res["lists_updated"] is True
    with open(os.path.join(lists_dir, "sdns")) as f:
        assert tools.parse_list_caseids(f.read()) == [autoid]


def test_promote_collision_blocks_lists_update(staged):
    """同 autoid 不同 source：第二次晋升报冲突，xlsx 已落但 lists 不更新。"""
    staging_parent, lists_dir, make_xlsx = staged
    src_a = make_xlsx("featA.xlsx")
    src_b = make_xlsx("featB.xlsx")

    r1 = tools.promote_case(
        "sdns", feature="featA", xlsx_path=src_a,
        case_autoids=["dup_001"], source="srcA",
    )
    assert r1["lists_updated"] is True

    # 同 autoid，不同来源 → 冲突
    r2 = tools.promote_case(
        "sdns", feature="featB", xlsx_path=src_b,
        case_autoids=["dup_001"], source="srcB",
    )
    assert r2["lists_updated"] is False
    assert r2["conflicts"][0]["autoid"] == "dup_001"
    assert "warning" in r2
    # xlsx 仍已晋升（粒度契约：文件先落，lists 后置）
    assert os.path.isfile(r2["promoted"])
    # lists 未被 srcB 污染，仍只有 srcA 的登记
    with open(os.path.join(lists_dir, "sdns")) as f:
        assert tools.parse_list_caseids(f.read()) == ["dup_001"]


def test_promote_overwrite_resolves_collision(staged):
    """overwrite=True：强制覆盖 manifest 冲突并更新 lists。"""
    staging_parent, lists_dir, make_xlsx = staged
    src_a = make_xlsx("featA.xlsx")
    src_b = make_xlsx("featB.xlsx")
    tools.promote_case("sdns", feature="featA", xlsx_path=src_a,
                       case_autoids=["dup_001"], source="srcA")

    r2 = tools.promote_case(
        "sdns", feature="featB", xlsx_path=src_b,
        case_autoids=["dup_001", "new_002"], source="srcB", overwrite=True,
    )
    assert r2["lists_updated"] is True
    assert "conflicts" not in r2
    # lists 现含两个 case（dup_001 保序 + new_002 追加）
    with open(os.path.join(lists_dir, "sdns")) as f:
        assert tools.parse_list_caseids(f.read()) == ["dup_001", "new_002"]


def test_promote_custom_list_name(staged):
    """list_name 覆盖默认 module，写到 lists/<list_name>。"""
    staging_parent, lists_dir, make_xlsx = staged
    src = make_xlsx("feat.xlsx")
    res = tools.promote_case(
        "sdns", feature="feat", xlsx_path=src,
        case_autoids=["sdns_c_001"], source="s", list_name="sdns_smoke",
    )
    assert os.path.isfile(os.path.join(lists_dir, "sdns_smoke"))
    assert res["lists_file"].endswith("/sdns_smoke")


def test_promote_missing_source_errors(staged):
    """既无 xlsx_path 也无 autoid → 明确报错，不抛异常。"""
    res = tools.promote_case("sdns")
    assert "error" in res


def test_promote_nonexistent_xlsx_errors(staged):
    res = tools.promote_case("sdns", feature="f", xlsx_path="/nope/missing.xlsx",
                             case_autoids=["c_1"])
    assert "error" in res
    assert "not found" in res["error"]


def test_promote_idempotent_same_source(staged):
    """同来源重复晋升幂等：lists 不重复堆叠。"""
    staging_parent, lists_dir, make_xlsx = staged
    src = make_xlsx("feat.xlsx")
    tools.promote_case("sdns", feature="feat", xlsx_path=src,
                       case_autoids=["sdns_dup_001"], source="s")
    r2 = tools.promote_case("sdns", feature="feat", xlsx_path=src,
                            case_autoids=["sdns_dup_001"], source="s")
    assert r2["lists_updated"] is True
    assert r2["lists_added"] == []  # 已存在，无新增
    with open(os.path.join(lists_dir, "sdns")) as f:
        assert tools.parse_list_caseids(f.read()) == ["sdns_dup_001"]
