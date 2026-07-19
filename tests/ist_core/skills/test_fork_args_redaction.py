# -*- coding: utf-8 -*-
"""#58 Fix C 凭证键名脱敏(security,sec58 实证条件泄漏 → 硬红线代码强制)。

`_compact_args` 记 fork tool 全参供诊断(治 #54 unlogged-kwarg 死角)——但 sec58 实证:
`dev_ssh`(ssh.py:173)/`dev_rest`(restapi.py:46)收 `password`/`enable_password` 作输入参、在
dyn-agent 注册表非 `_ON_DEVICE_BLOCKED`,dyn-* agent 传 `password=` 会 verbatim 进 .events.jsonl。
故键名命中凭证模式的值必脱敏 → `***`。模式=sec58 精确版(无裸 key/pass,避免 keyword/路径误中)。
"""
from __future__ import annotations

from main.ist_core.skills.loader import _compact_args


def test_credential_keys_redacted():
    """凭证键(含 sec58 实证的 dev_ssh `password`/`enable_password`)值脱敏。"""
    for key in ("password", "enable_password", "passwd", "secret", "token",
                "credential", "api_key", "apikey", "api-key", "access_key"):
        out = _compact_args({key: "click1-real-secret-value", "command": "x"})
        assert "click1-real-secret-value" not in out, f"{key} 值应脱敏"
        assert "***" in out, f"{key} 应出现 *** 脱敏标记"


def test_no_false_hit_on_diagnostic_keys():
    """非凭证键不误中(keyword 曾是 \\bkey\\b 的误中风险,sec58 模式避开)——诊断参全留。"""
    for kv in ({"keyword": "loadbalance"}, {"command": "show slb"},
               {"version": "10.5.0.585"}, {"pattern": "updown"},
               {"query": "ssl"}, {"path": "workspace/x"}, {"autoid": "203601"},
               {"keyfile": "cert/a.key"}, {"keyType": "signkey"}, {"username": "test"}):
        out = _compact_args(kv)
        assert "***" not in out, f"非凭证键 {list(kv)[0]} 不应脱敏:{out}"
        assert list(kv.values())[0] in out, f"{list(kv)[0]} 值应保留供诊断"


def test_version_kwarg_preserved_for_diagnosis():
    """#58 修的诊断死角:version kwarg 必须可溯,不被脱敏误伤。"""
    out = _compact_args({"command": "ssl", "version": "10.5.0.585"})
    assert "10.5.0.585" in out and "ssl" in out


def test_empty_and_non_dict_safe():
    assert _compact_args({}) == ""
    assert _compact_args(None) == ""
    assert _compact_args("nope") == ""
