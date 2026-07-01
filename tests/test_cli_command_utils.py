"""Tests for main.cli_command_utils — CLI command string utilities."""

from __future__ import annotations

from main.cli_command_utils import (
    collect_allowlist_tokens,
    command_matches_text,
    extract_command_tokens,
    feature_command_allowlist,
    find_command_traceability,
    has_onoff_switch,
    is_reverse_symmetric,
    line_contains_allowlisted_command,
    normalize_syntax_brackets,
    strip_cli_prompt_prefix,
    verify_command_against_evidences,
)


class TestExtractCommandTokens:
    def test_basic(self):
        assert extract_command_tokens("http2 virtual {on|off} <vs>") == ["http2", "virtual"]

    def test_all_keywords(self):
        assert extract_command_tokens("http2 flow-control window-size <size>") == [
            "http2", "flow-control", "window-size"
        ]

    def test_no_placeholder(self):
        assert extract_command_tokens("http2 enable") == ["http2", "enable"]

    def test_no_prefix(self):
        assert extract_command_tokens("no http2 virtual <vs>") == ["no", "http2", "virtual"]

    def test_empty(self):
        assert extract_command_tokens("") == []
        assert extract_command_tokens(None) == []

    def test_only_placeholder(self):
        assert extract_command_tokens("<size>") == []

    def test_bracket_types(self):
        assert extract_command_tokens("foo [bar]") == ["foo"]
        assert extract_command_tokens("foo (bar)") == ["foo"]


class TestNormalizeSyntaxBrackets:
    def test_square_to_curly(self):
        assert normalize_syntax_brackets("[on|off]") == "{on|off}"

    def test_angle_to_curly(self):
        assert normalize_syntax_brackets("<on|off>") == "{on|off}"

    def test_paren_to_curly(self):
        assert normalize_syntax_brackets("(on|off)") == "{on|off}"

    def test_empty(self):
        assert normalize_syntax_brackets("") == ""

    def test_no_brackets(self):
        assert normalize_syntax_brackets("hello") == "hello"


class TestCommandMatchesText:
    def test_tokens_in_order(self):
        assert command_matches_text("http2 virtual", "config http2 virtual on") is True

    def test_tokens_not_in_order(self):
        assert command_matches_text("virtual http2", "http2 virtual on") is False

    def test_empty_cmd(self):
        assert command_matches_text("", "some text") is False

    def test_empty_text(self):
        assert command_matches_text("http2 virtual", "") is False

    def test_partial_match(self):
        assert command_matches_text("slb virtual http", "slb virtual http vs1 10.0.0.1") is True


class TestHasOnoffSwitch:
    def test_curly_onoff(self):
        assert has_onoff_switch("http2 virtual {on|off}") is True

    def test_square_onoff(self):
        assert has_onoff_switch("http2 virtual [on|off]") is True

    def test_angle_onoff(self):
        assert has_onoff_switch("http2 virtual <on|off>") is True

    def test_paren_offon(self):
        assert has_onoff_switch("http2 virtual (off|on)") is True

    def test_no_switch(self):
        assert has_onoff_switch("http2 enable") is False

    def test_empty(self):
        assert has_onoff_switch("") is False


class TestIsReverseSymmetric:
    def test_empty_reverse(self):
        ok, reason = is_reverse_symmetric("http2 virtual {on|off}", "")
        assert ok is True
        assert reason is None

    def test_no_prefix(self):
        ok, reason = is_reverse_symmetric("http2 enable", "no http2 enable")
        assert ok is True
        assert reason is None

    def test_scope_mismatch(self):
        ok, reason = is_reverse_symmetric("http2 enable", "slb disable")
        assert ok is False
        assert "scope_mismatch" in reason

    def test_onoff_switch_allowed(self):
        ok, reason = is_reverse_symmetric("http2 virtual {on|off}", "http2 virtual off")
        assert ok is True

    def test_foreign_token_rejected(self):
        ok, reason = is_reverse_symmetric("http2 enable", "http2 banana")
        assert ok is False
        assert "foreign_token" in reason

    def test_enable_without_disable(self):
        ok, reason = is_reverse_symmetric("http2 virtual", "http2 virtual disable")
        assert ok is False

    def test_both_empty(self):
        ok, reason = is_reverse_symmetric("", "")
        assert ok is True


class TestStripCliPromptPrefix:
    def test_config_prompt(self):
        assert strip_cli_prompt_prefix("Demo(config)# show running") == "show running"

    def test_hash_prompt(self):
        assert strip_cli_prompt_prefix("AN# show version") == "show version"

    def test_no_prompt(self):
        assert strip_cli_prompt_prefix("show version") == "show version"

    def test_empty(self):
        assert strip_cli_prompt_prefix("") == ""


class TestLineContainsAllowlistedCommand:
    def test_match(self):
        seqs = [["http2", "virtual"]]
        assert line_contains_allowlisted_command("http2 virtual on myvs", seqs) is True

    def test_non_adjacent_no_match(self):
        seqs = [["http2", "virtual"]]
        assert line_contains_allowlisted_command("http2 maxstream virtual myvs", seqs) is False

    def test_empty_line(self):
        assert line_contains_allowlisted_command("", [["http2"]]) is False

    def test_empty_seqs(self):
        assert line_contains_allowlisted_command("http2 virtual", []) is False

    def test_with_prompt_prefix(self):
        seqs = [["show", "version"]]
        assert line_contains_allowlisted_command("Demo(config)# show version", seqs) is True


class TestFeatureCommandAllowlist:
    def test_basic(self):
        f = {"cli": {"commands": [{"command": "http2 enable"}, {"command": "http2 disable"}]}}
        assert feature_command_allowlist(f) == ["http2 enable", "http2 disable"]

    def test_empty_feature(self):
        assert feature_command_allowlist({}) == []
        assert feature_command_allowlist(None) == []

    def test_skip_empty_commands(self):
        f = {"cli": {"commands": [{"command": ""}, {"command": "http2 enable"}]}}
        assert feature_command_allowlist(f) == ["http2 enable"]


class TestCollectAllowlistTokens:
    def test_basic(self):
        result = collect_allowlist_tokens(["http2 enable", "slb virtual <vs>"])
        assert result == [["http2", "enable"], ["slb", "virtual"]]

    def test_empty(self):
        assert collect_allowlist_tokens([]) == []


class TestFindCommandTraceability:
    def test_quoted_text_match(self):
        evs = [{"quoted_text": "Configure http2 virtual on", "source_file": "doc.md"}]
        result = find_command_traceability("http2 virtual", evs)
        assert result["matched"] is True
        assert result["match_field"] == "quoted_text"

    def test_section_title_match(self):
        evs = [{"quoted_text": "", "section_title": "http2 virtual config", "source_file": "doc.md"}]
        result = find_command_traceability("http2 virtual", evs)
        assert result["matched"] is True
        assert result["match_field"] == "section_title"

    def test_no_match(self):
        evs = [{"quoted_text": "slb real server", "source_file": "doc.md"}]
        result = find_command_traceability("http2 virtual", evs)
        assert result["matched"] is False

    def test_empty_cmd(self):
        result = find_command_traceability("", [])
        assert result["matched"] is False

    def test_cli_reference_context_only(self):
        evs = [{"quoted_text": "", "section_title": "虚拟服务配置",
                "role": "cli_reference", "source_file": "cli.md"}]
        result = find_command_traceability("slb virtual-server", evs)
        assert result["context_only"] is True
        assert result["context_reason"] == "cli_reference_context_only"


class TestVerifyCommandAgainstEvidences:
    def test_match(self):
        evs = [{"quoted_text": "http2 virtual on"}]
        matched, src = verify_command_against_evidences("http2 virtual", evs)
        assert matched is True

    def test_no_match(self):
        matched, src = verify_command_against_evidences("http2 virtual", [])
        assert matched is False
        assert src is None
