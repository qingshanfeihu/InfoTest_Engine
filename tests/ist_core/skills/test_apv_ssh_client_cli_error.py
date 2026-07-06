"""apv_ssh_client 回退 _has_cli_error 与 device_errors 行为一致。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from main.ist_core.tools.device.device_errors import has_cli_error as shared_has_cli_error

_CLIENT_PATH = (
    Path(__file__).resolve().parents[3]
    / "main/ist_core/skills/device-verify/scripts/apv_ssh_client.py"
)


def _load_client_module():
    spec = importlib.util.spec_from_file_location("apv_ssh_client_test", _CLIENT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "text",
    [
        "Failed to execute the command",
        "Query type not support.\nFailed to execute the command",
        "show foo\n^",
    ],
)
def test_fallback_has_cli_error_positive(text):
    mod = _load_client_module()
    mod._has_cli_error_shared = None
    assert mod.APVSSHClient._has_cli_error(text) is True
    assert shared_has_cli_error(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Query type not support.",
        "not supported",
        "query type not found",
        "show sdns host persistence 3600 enable",
    ],
)
def test_fallback_matches_shared_negative_where_business_phrase_only(text):
    """业务措辞 alone 不进权威表；回退也不得比 shared 更严。"""
    mod = _load_client_module()
    mod._has_cli_error_shared = None
    assert mod.APVSSHClient._has_cli_error(text) == shared_has_cli_error(text)
