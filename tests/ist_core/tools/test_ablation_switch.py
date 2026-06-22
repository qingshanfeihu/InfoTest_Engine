"""消融实验开关回归测试:确保 Arm-L/Arm-E 切换正确且生产默认安全。"""
import importlib.util
import os
from pathlib import Path

import pytest

_AB_PATH = Path(__file__).resolve().parents[3] / "main/ist_core/tools/_shared/ablation.py"


def _load_ablation():
    spec = importlib.util.spec_from_file_location("ablation_test", _AB_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ab(monkeypatch):
    monkeypatch.delenv("IST_ABLATION_ARM", raising=False)
    return _load_ablation()


def test_default_is_layered(ab, monkeypatch):
    """无 env → 生产默认 Arm-L(分层),绝不进基线分支。"""
    monkeypatch.delenv("IST_ABLATION_ARM", raising=False)
    assert ab.current_arm() == "L"
    assert ab.is_baseline() is False


def test_explicit_baseline(ab, monkeypatch):
    monkeypatch.setenv("IST_ABLATION_ARM", "E")
    assert ab.current_arm() == "E"
    assert ab.is_baseline() is True


def test_case_insensitive(ab, monkeypatch):
    monkeypatch.setenv("IST_ABLATION_ARM", "e")
    assert ab.is_baseline() is True
    monkeypatch.setenv("IST_ABLATION_ARM", "L")
    assert ab.is_baseline() is False


@pytest.mark.parametrize("val", ["", "garbage", "X", "baseline", "1"])
def test_unknown_values_fall_back_to_layered(ab, monkeypatch, val):
    """任何非 'E' 取值都按 Arm-L 处理——生产永不被脏值误切到基线。"""
    monkeypatch.setenv("IST_ABLATION_ARM", val)
    assert ab.current_arm() == "L"
    assert ab.is_baseline() is False
