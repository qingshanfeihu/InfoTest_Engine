"""needs_decision/user_decision 原子落盘(item3 回归:tmp+os.replace 无半写窗口)。

实证:96 份交付中 1 份 needs_decision.json 截断损坏——裸 write_text 被 Ctrl-C/崩溃打断会留
截断文件,下轮读崩或凭据失效。os.replace 原子、内容与旧 write_text 逐字节等价。
"""
import json

from main.ist_core.tools.device.verifiability_tool import _write_json_atomic


def test_atomic_write_valid_json_and_no_tmp_residue(tmp_path):
    p = tmp_path / "needs_decision.json"
    obj = {"autoid": "203031753342778041", "claims": [{"claim_kind": "distribution"}]}
    _write_json_atomic(p, obj)
    assert json.loads(p.read_text(encoding="utf-8")) == obj      # 有效 JSON
    assert not (tmp_path / "needs_decision.json.tmp").exists()    # 无 .tmp 残留


def test_atomic_overwrite_replaces_content(tmp_path):
    p = tmp_path / "user_decision.json"
    _write_json_atomic(p, {"decision": "confirm", "claims": ["a"]})
    _write_json_atomic(p, {"decision": "correct", "claims": []})   # 覆盖写
    got = json.loads(p.read_text(encoding="utf-8"))
    assert got == {"decision": "correct", "claims": []}
    assert not (tmp_path / "user_decision.json.tmp").exists()


def test_atomic_write_content_byte_identical_to_write_text(tmp_path):
    # 与旧 write_text(json.dumps(..., ensure_ascii=False, indent=2)) 逐字节等价(仅崩溃安全性变化)
    obj = {"k": "中文", "n": 3, "claims": [{"x": 1}]}
    p = tmp_path / "a.json"
    _write_json_atomic(p, obj)
    expected = json.dumps(obj, ensure_ascii=False, indent=2)
    assert p.read_text(encoding="utf-8") == expected
