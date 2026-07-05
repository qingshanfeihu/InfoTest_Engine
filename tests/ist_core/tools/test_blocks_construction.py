"""组合子构造层回归(V4 步骤2,命题3.18 correct-by-construction)。

文法实证:34 个已验证成品卷反解 5 组合子 round-trip 33/34 字节级等价(2026-07-04,
唯一失败卷=上机 fail 的坏形态卷)。展开器把寄存器分配/捕获比较三步式/E-F-H 列
全部代码化——必崩形态在组合子语言下不可表达,fuzz 任意合法组合子的展开产物
必过成品 lint。
"""
from __future__ import annotations

import random

from main.case_compiler.blocks import expand_blocks


def _norm(steps):
    return [(s.get("E", ""), s.get("F", ""), s.get("G", ""), s.get("H", "") or "")
            for s in steps]


def parse_blocks_from_steps(steps):
    """成品步骤表 → 组合子(round-trip 的反解侧;调研 E 消解器的正式化)。"""
    blocks, i = [], 0
    reg_seen = 0
    while i < len(steps):
        E, F, G, H = steps[i]
        if E == "APV_0" and F in ("cmds_config", "cmd_config") and (
                i + 1 >= len(steps) or steps[i + 1][0] != "check_point"):
            cmds = [ln for ln in G.split("\n") if ln.strip()] if F == "cmds_config" else [G]
            blocks.append({"kind": "CONFIG", "cmds": cmds})
            i += 1
        elif E == "time" and F == "sleep":
            blocks.append({"kind": "SLEEP", "seconds": int(G)})
            i += 1
        elif E in ("test_env", "APV_0") and H:
            j = i + 1
            mids = []
            while j < len(steps) and steps[j][0] in ("test_env", "APV_0") and not steps[j][3]:
                mids.append(steps[j]); j += 1
            assert j < len(steps) and steps[j][0] == "check_point" and steps[j][3] == H, "异形capture"
            assert len(mids) == 1, "非三步式capture(隔多步)"
            reg_seen += 1
            host = F if E == "test_env" else "APV_0"
            relation = "differs" if steps[j][1] == "not_found" else "same"
            blocks.append({"kind": "CAPTURE_COMPARE", "host": host, "capture_cmd": G,
                           "cmd": mids[0][2], "relation": relation})
            i = j + 1
        elif E in ("test_env", "APV_0"):
            j = i + 1
            asserts = []
            while j < len(steps) and steps[j][0] == "check_point" and not steps[j][3]:
                asserts.append({"op": steps[j][1], "pattern": steps[j][2]}); j += 1
            host = F if E == "test_env" else "APV_0"
            if asserts:
                blocks.append({"kind": "OBSERVE_ASSERT", "host": host, "cmd": G, "asserts": asserts})
            else:
                blocks.append({"kind": "OBSERVE_ONLY", "host": host, "cmd": G})
            i = j
        else:
            raise AssertionError(f"文法外形态@{i}: {E}.{F}")
    return blocks


def test_roundtrip_on_verified_volumes():
    """34 已验证卷:反解组合子 → expand_blocks → 与原步骤 E/F/G/H 等价(容许
    found(H引用)与 abs_found 的既有自动转换差异——emit 侧门语义)。"""
    import pathlib
    import openpyxl
    HEADER = ("case描述", "可以有很多行", "如：a=1", "测试对象")
    total = ok = 0
    for d in sorted(pathlib.Path("workspace/outputs").iterdir()):
        if not (d.name.startswith("20303175") and len(d.name) == 18
                and (d / "case.xlsx").exists()):
            continue
        ws = openpyxl.load_workbook(d / "case.xlsx").active
        steps = []
        for r in ws.iter_rows(min_row=2):
            E, F, G, H = (str(r[i].value or "") for i in (4, 5, 6, 7))
            if E and not any(E.startswith(h) for h in HEADER):
                # 空配置占位步(G 全空白)是合法无害步(框架 splitlines 零循环),
                # 组合子语言不表达它——round-trip 两侧同步剔除
                if E == "APV_0" and F in ("cmds_config", "cmd_config") and not G.strip():
                    continue
                steps.append((E, F, G.strip(), H.strip()))
        total += 1
        try:
            blocks = parse_blocks_from_steps(steps)
        except AssertionError:
            continue  # 已知坏形态卷(实证=上机 fail 卷)不参与
        expanded, _, err = expand_blocks(blocks)
        assert err is None, err
        got = [(s.get("E"), s.get("F"), s.get("G"), s.get("H", "") or "") for s in expanded]
        # 表示等价归一:①found(H引用) 被 emit 自动转 abs_found;②单条配置 cmds_config 与
        # cmd_config 框架行为一致;③寄存器名是 alpha 可重命名的(v1 vs first_hit 语义同),
        # 按首现顺序统一映射。
        def canon(rows):
            reg_map = {}
            out = []
            for e, f, g, h in rows:
                if h:
                    h = reg_map.setdefault(h, f"R{len(reg_map)+1}")
                if e == "APV_0" and f in ("cmds_config", "cmd_config") and "\n" not in g:
                    f = "cfg1"
                if e == "check_point" and h and f in ("found", "abs_found"):
                    f = "H_REF"
                out.append((e, f, g, h))
            return out
        if canon(got) == canon(steps):
            ok += 1
    assert total >= 3, "盘上成品卷不足,round-trip 无法验证"
    assert ok / total >= 0.9, f"round-trip {ok}/{total}"


def test_fuzz_expansion_always_passes_crash_gates():
    """200 个随机合法组合子序列:展开产物必过必崩门全集(悬空/寄存器/载荷)。"""
    from main.ist_core.tools.device.structural_gate import check_crash_gates_mandatory
    rng = random.Random(42)
    hosts = ["routera", "routerb", "APV_0"]
    for trial in range(200):
        blocks = []
        for _ in range(rng.randint(1, 8)):
            k = rng.choice(["CONFIG", "OBSERVE_ASSERT", "CAPTURE_COMPARE", "OBSERVE_ONLY", "SLEEP"])
            if k == "CONFIG":
                blocks.append({"kind": k, "cmds": [f"cmd {rng.randint(1,99)}" for _ in range(rng.randint(1, 4))]})
            elif k == "OBSERVE_ASSERT":
                blocks.append({"kind": k, "host": rng.choice(hosts), "cmd": f"show x{trial}",
                               "asserts": [{"op": rng.choice(["found", "not_found"]),
                                            "pattern": f"p{rng.randint(1,9)}"}
                                           for _ in range(rng.randint(1, 3))]})
            elif k == "CAPTURE_COMPARE":
                blocks.append({"kind": k, "host": rng.choice(hosts), "capture_cmd": f"dig y{trial}",
                               "relation": rng.choice(["same", "differs"])})
            elif k == "OBSERVE_ONLY":
                blocks.append({"kind": k, "host": rng.choice(hosts), "cmd": f"dig z{trial}"})
            else:
                blocks.append({"kind": k, "seconds": rng.randint(1, 30)})
        steps, _, err = expand_blocks(blocks)
        assert err is None, err
        res = check_crash_gates_mandatory(steps)
        assert res.ok, f"trial{trial}: {[v.code for v in res.violations]}"


def test_invalid_blocks_rejected_with_actionable_error():
    for bad, needle in [
        ([{"kind": "CAPTURE_COMPARE", "host": "r", "capture_cmd": "d", "relation": "equal"}], "same"),
        ([{"kind": "OBSERVE_ASSERT", "host": "r", "cmd": "d", "asserts": []}], "OBSERVE_ONLY"),
        ([{"kind": "CONFIG", "cmds": "sdns on"}], "列表"),
        ([{"kind": "SLEEP", "seconds": 0}], "1..300"),
        ([{"kind": "WAT"}], "kind"),
    ]:
        _, _, err = expand_blocks(bad)
        assert err and needle in err, (bad, err)


def test_provenance_expanded_per_block():
    blocks = [
        {"kind": "CONFIG", "cmds": ["a", "b"]},
        {"kind": "CAPTURE_COMPARE", "host": "routera", "capture_cmd": "dig t", "relation": "differs"},
    ]
    prov = [{"layer": "G", "source": {"kind": "manual", "ref": "x"}},
            {"layer": "V", "source": {"kind": "captured_relation", "ref": "y"}}]
    steps, prov_out, err = expand_blocks(blocks, prov)
    assert err is None
    assert len(steps) == 4 and len(prov_out) == 4        # 1 + 3
    assert prov_out[0]["layer"] == "G" and all(p["layer"] == "V" for p in prov_out[1:])
    # 数量不匹配 → 拒
    _, _, err2 = expand_blocks(blocks, prov[:1])
    assert err2 and "等于" in err2
