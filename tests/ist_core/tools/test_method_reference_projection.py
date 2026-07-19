# -*- coding: utf-8 -*-
"""#58 method_reference.json 投影漂移守门(FINDING #1 修法·方案 a PROJECT)。

投影 = worker 可达的框架方法数据面(mirror 不在 worker 沙箱、contracts.md 在 main/ 不可达,
故方法签名/动作注册表投影进 knowledge/data/compile_ref/)。机械部分生成式,本测锁"投影 ==
现场重解析 mirror"(漂移即红,防手改投影脱离 mirror 真相)。
"""
from __future__ import annotations

import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_PROJECTION = _ROOT / "knowledge/data/compile_ref/method_reference.json"


def _load():
    return json.loads(_PROJECTION.read_text(encoding="utf-8"))


def test_projection_exists_and_sandbox_reachable():
    """投影必须落在 worker 可达根 knowledge/data/(非 main/ 等 _PLATFORM_DENIED)。"""
    assert _PROJECTION.exists(), "method_reference.json 投影缺失(跑 gen_method_reference.py)"
    rel = _PROJECTION.relative_to(_ROOT).as_posix()
    assert rel.startswith("knowledge/data/"), \
        f"投影必须在 worker 沙箱可达根 knowledge/data/,实为 {rel}"


def test_cert_methods_match_mirror_no_drift():
    """cert 方法签名 == 现场重解析 ssl_comm.py(生成式零漂移)。"""
    from scripts.gen_method_reference import _parse_cert_methods
    assert _load()["cert_methods"] == _parse_cert_methods(), \
        "cert_methods 与 mirror ssl_comm.py 漂移——重跑 gen_method_reference.py"


def test_execute_actions_match_registry_no_drift():
    """execute 动作名 == 现场重解析注册表(复用 #56 parser,零漂移)。"""
    from scripts.gen_method_reference import _execute_actions
    assert _load()["execute_actions"]["exact_action_names"] == \
        _execute_actions()["exact_action_names"], \
        "execute_actions 与 mirror 注册表漂移——重跑 gen_method_reference.py"


def test_cc_findings_locked():
    """#50 CC1/CC2 finding 经投影保真(RSA 2 参 / SM2 3 参含 keyType 首参)。"""
    cm = _load()["cert_methods"]
    assert cm["importKey"]["required"] == ["vhost", "keyfile"], "CC1:RSA importKey 2 必需参"
    assert cm["sm2ImportKey"]["required"] == ["keyType", "vhost", "keyFile"], \
        "CC2:SM2 3 必需参、首参 keyType(国密双证书)"


def test_silent_failure_faces_complete():
    """S1-S5 静默失败面齐(归因分 harness-silent vs 真设备行为的依据)。"""
    ids = {f["id"] for f in _load()["silent_failure_faces"]}
    assert ids == {"S1", "S2", "S3", "S4", "S5"}, f"S 面不全:{ids}"
    for f in _load()["silent_failure_faces"]:
        assert f.get("source"), f"S 面 {f['id']} 缺 source 锚"
