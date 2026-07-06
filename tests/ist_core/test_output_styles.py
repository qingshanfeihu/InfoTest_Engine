"""Tests for main.ist_core.output_styles — output style system."""

from __future__ import annotations

from main.ist_core.output_styles import (
    OUTPUT_STYLES,
    get_active_style,
    get_active_style_prompt,
    get_output_style,
    get_style_prompt,
    set_active_style,
)


class TestOutputStyles:
    def test_default_style_exists(self):
        cfg = get_output_style("default")
        assert cfg is not None
        assert cfg.name == "default"
        assert cfg.prompt == ""

    def test_explanatory_style_exists(self):
        cfg = get_output_style("explanatory")
        assert cfg is not None
        assert cfg.name == "Explanatory"
        assert "Insight" in cfg.prompt

    def test_learning_style_exists(self):
        cfg = get_output_style("learning")
        assert cfg is not None
        assert cfg.name == "Learning"
        assert "Learn by Doing" in cfg.prompt

    def test_case_insensitive(self):
        assert get_output_style("DEFAULT") is not None
        assert get_output_style("Explanatory") is not None
        assert get_output_style("LEARNING") is not None

    def test_unknown_style_returns_none(self):
        assert get_output_style("nonexistent") is None

    def test_style_count(self):
        assert len(OUTPUT_STYLES) == 3


class TestGetStylePrompt:
    def test_default_returns_empty(self):
        assert get_style_prompt("default") == ""

    def test_explanatory_returns_prompt(self):
        prompt = get_style_prompt("explanatory")
        assert "Explanatory" in prompt

    def test_unknown_returns_empty(self):
        assert get_style_prompt("nonexistent") == ""


class TestActiveStyle:
    def setup_method(self):
        set_active_style("default")

    def test_default_active_style(self):
        assert get_active_style() == "default"

    def test_set_and_get(self):
        set_active_style("explanatory")
        assert get_active_style() == "explanatory"

    def test_set_case_insensitive(self):
        set_active_style("LEARNING")
        assert get_active_style() == "learning"

    def test_set_invalid_style_ignored(self):
        set_active_style("explanatory")
        set_active_style("nonexistent")
        assert get_active_style() == "explanatory"

    def test_active_prompt_default(self):
        set_active_style("default")
        assert get_active_style_prompt() == ""

    def test_active_prompt_explanatory(self):
        set_active_style("explanatory")
        prompt = get_active_style_prompt()
        assert "Insight" in prompt

    def teardown_method(self):
        set_active_style("default")
