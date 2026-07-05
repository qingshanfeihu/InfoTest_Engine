"""测试基座公共夹具。"""
import os

import pytest


@pytest.fixture(autouse=True)
def _provenance_optional_for_legacy_tests(monkeypatch):
    """存量测试聚焦各自的门/结构语义,不逐个补 provenance——统一走可选模式。

    provenance 必传门(V4 步骤0)的专项覆盖在 tests/ist_core/tools/
    test_provenance_mandatory.py:那里显式 delenv 后验证拒绝/放行两侧,
    本夹具不会稀释它。
    """
    if "IST_PROVENANCE_OPTIONAL" not in os.environ:
        monkeypatch.setenv("IST_PROVENANCE_OPTIONAL", "1")
