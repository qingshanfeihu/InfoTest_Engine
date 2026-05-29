"""Tests for /skill slash command (Anthropic skillOverrides 四态)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from main.ist_core.skills.state import (
    cycle_skill_state,
    get_skill_state,
    set_skill_state,
)
from main.ist_core.tui.skill_command import cmd_skill


@pytest.fixture(autouse=True)
def _redirect_settings(tmp_path, monkeypatch):
    """每个测试隔离 settings 文件。"""
    import main.ist_core.skills.state as mod
    settings_file = tmp_path / "settings.local.json"
    monkeypatch.setattr(mod, "_SETTINGS_PATH", settings_file)
    yield


class _FakeApp:
    pass


def test_default_state_is_on():
    assert get_skill_state("any-skill") == "on"


def test_set_and_get_state():
    set_skill_state("foo", "off")
    assert get_skill_state("foo") == "off"
    set_skill_state("foo", "name-only")
    assert get_skill_state("foo") == "name-only"


def test_set_state_on_removes_entry(tmp_path, monkeypatch):
    """state == 'on' 是默认值，写入应该删除条目而不是写 'on'。"""
    import main.ist_core.skills.state as mod
    settings_file = tmp_path / "settings.local.json"
    monkeypatch.setattr(mod, "_SETTINGS_PATH", settings_file)
    set_skill_state("foo", "off")
    set_skill_state("foo", "on")
    if settings_file.exists():
        data = json.loads(settings_file.read_text())
        overrides = data.get("skillOverrides") or {}
        assert "foo" not in overrides


def test_cycle_state():
    assert cycle_skill_state("foo") == "name-only"
    assert cycle_skill_state("foo") == "user-invocable-only"
    assert cycle_skill_state("foo") == "off"
    assert cycle_skill_state("foo") == "on"


def test_set_invalid_state_raises():
    with pytest.raises(ValueError):
        set_skill_state("foo", "bogus")


def test_persists_to_settings_file(tmp_path, monkeypatch):
    import main.ist_core.skills.state as mod
    settings_file = tmp_path / "settings.local.json"
    monkeypatch.setattr(mod, "_SETTINGS_PATH", settings_file)
    set_skill_state("foo", "off")
    data = json.loads(settings_file.read_text())
    assert data["skillOverrides"]["foo"] == "off"


class TestCmdSkill:
    """Test /skill slash command dispatch."""

    @patch("main.ist_core.tui.skill_command._scan_all_skills")
    def test_default_shows_all_skills(self, mock_scan):
        """裸 /skill 等同 all，显示全部 skill。"""
        mock_scan.return_value = [
            {"name": "test-list-review", "context": "inline"},
            {"name": "review-verification", "context": "fork"},
        ]
        result = cmd_skill("", _FakeApp())
        assert "test-list-review" in result.text
        assert "review-verification" in result.text
        assert "[on]" in result.text

    @patch("main.ist_core.tui.skill_command._scan_all_skills")
    def test_list_all_shows_off_skills(self, mock_scan):
        """/skill all 显示全部，含 off。"""
        mock_scan.return_value = [
            {"name": "test-list-review", "context": "inline"},
            {"name": "off-skill", "context": "inline"},
        ]
        set_skill_state("off-skill", "off")
        result = cmd_skill("all", _FakeApp())
        assert "test-list-review" in result.text
        assert "off-skill" in result.text
        assert "[off]" in result.text

    @patch("main.ist_core.tui.skill_command._skill_exists")
    def test_set_state(self, mock_exists):
        mock_exists.return_value = {"name": "foo", "context": "inline"}
        result = cmd_skill("set foo off", _FakeApp())
        assert "off" in result.text
        assert get_skill_state("foo") == "off"

    @patch("main.ist_core.tui.skill_command._skill_exists")
    def test_set_invalid_state(self, mock_exists):
        mock_exists.return_value = {"name": "foo", "context": "inline"}
        result = cmd_skill("set foo bogus", _FakeApp())
        assert "invalid state" in result.text.lower()

    @patch("main.ist_core.tui.skill_command._skill_exists")
    def test_cycle(self, mock_exists):
        mock_exists.return_value = {"name": "foo", "context": "inline"}
        result = cmd_skill("cycle foo", _FakeApp())
        assert "name-only" in result.text
        assert get_skill_state("foo") == "name-only"

    @patch("main.ist_core.tui.skill_command._skill_exists")
    def test_set_nonexistent_skill(self, mock_exists):
        mock_exists.return_value = None
        result = cmd_skill("set nope off", _FakeApp())
        assert "not found" in result.text

    def test_set_missing_args(self):
        result = cmd_skill("set", _FakeApp())
        assert "usage" in result.text.lower()

    def test_unknown_subcommand(self):
        result = cmd_skill("bogus", _FakeApp())
        assert "unknown" in result.text.lower()

    @patch("main.ist_core.tui.skill_command._skill_exists")
    def test_on_off(self, mock_exists):
        mock_exists.return_value = {"name": "test-list-review", "context": "inline"}
        result = cmd_skill("off test-list-review", _FakeApp())
        assert get_skill_state("test-list-review") == "off"
        result = cmd_skill("on test-list-review", _FakeApp())
        assert get_skill_state("test-list-review") == "on"

    def test_off_without_name_shows_usage(self):
        result = cmd_skill("off", _FakeApp())
        assert "usage" in result.text.lower()
        assert "/skill off" in result.text
