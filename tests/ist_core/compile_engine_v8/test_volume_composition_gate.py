"""交付主卷组成对账门(item2 方案 b 回归):case.xlsx 实际组成 vs deliverable 集。

实证 778041:主卷 case.xlsx 23 案 ≠ engine_report 22 deliverable——failed_terminal 案止损后
未经新 merge 剔除、滞留物理卷(swallowed verdict)。设计承诺「deliverable N == case.xlsx 内容」,
本门核对实际组成、失配落事实 + outcome 如实降级。方案 b=纯加门,不碰 merge 元数据不变量。
"""
from main.ist_core.compile_engine_v8.nodes import _volume_composition_check


def _make_volume_xlsx(path, autoids: list[str]) -> None:
    """造一份 merged case.xlsx:A 列放 autoid(同 _xlsx_real_autoids 判定:≥15 位纯数字)。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for a in autoids:
        ws.append([a])
    wb.save(str(path))


_A = "203031753342778001"
_B = "203031753342778002"
_LEAK = "203031753342778041"   # 曾 pass 后被推翻→failed_terminal 的案(778041 型)


def test_leaked_failed_terminal_case_in_volume_is_reported(tmp_path):
    # 卷含 A/B/778041,但 deliverable 只有 A/B → 门必须报 leaked=[778041]
    xlsx = tmp_path / "case.xlsx"
    _make_volume_xlsx(xlsx, [_A, _B, _LEAK])
    leaked, absent = _volume_composition_check(xlsx, [_A, _B])
    assert leaked == [_LEAK], "failed_terminal 案在卷中,组成对账门必须报泄漏"
    assert absent == []


def test_clean_volume_matches_deliverable_no_mismatch(tmp_path):
    # 卷组成 == deliverable → 零失配(happy-path 零降级、零行为变化)
    xlsx = tmp_path / "case.xlsx"
    _make_volume_xlsx(xlsx, [_A, _B])
    assert _volume_composition_check(xlsx, [_A, _B]) == ([], [])


def test_deliverable_absent_from_volume_is_reported(tmp_path):
    # deliverable 含 A/B 但物理卷只有 A → 反向失配报 absent=[B]
    xlsx = tmp_path / "case.xlsx"
    _make_volume_xlsx(xlsx, [_A])
    leaked, absent = _volume_composition_check(xlsx, [_A, _B])
    assert leaked == []
    assert absent == [_B]


def test_unreadable_or_empty_volume_fails_open(tmp_path):
    # 卷读不出 autoid(不存在/空/非数字特殊卷)→ ([], []) 不误报(宁漏勿杀)
    assert _volume_composition_check(tmp_path / "nope.xlsx", [_A, _B]) == ([], [])
    empty = tmp_path / "empty.xlsx"
    _make_volume_xlsx(empty, ["not-a-digit", "999999999999999"])   # 哨兵+非数字
    assert _volume_composition_check(empty, [_A]) == ([], [])
