"""Tests for main.case_compiler.observe_ops — observation operator algebra."""

from __future__ import annotations

from main.case_compiler.observe_ops import (
    config_existence_check,
    is_observe_command,
    object_tokens,
    observe_kind,
)


class TestObjectTokens:
    def test_strips_leading_ops(self):
        assert object_tokens("show sdns listener") == ["sdns", "listener"]

    def test_strips_multiple_leading_ops(self):
        assert object_tokens("clear no sdns host") == ["sdns", "host"]

    def test_discards_ip_addresses(self):
        assert object_tokens("show sdns listener 192.168.1.1") == ["sdns", "listener"]

    def test_discards_numbers(self):
        assert object_tokens("show sdns 100") == ["sdns"]

    def test_discards_quoted_strings(self):
        assert object_tokens('show sdns "test.example.com"') == ["sdns"]

    def test_empty_input(self):
        assert object_tokens("") == []
        assert object_tokens(None) == []

    def test_no_leading_ops(self):
        assert object_tokens("sdns listener") == ["sdns", "listener"]

    def test_dig_leading_op(self):
        assert object_tokens("dig @10.0.0.1 example.com") == []


class TestObserveKind:
    def test_dig_is_behavior(self):
        assert observe_kind("dig @10.0.0.1 example.com") == "behavior"

    def test_curl_is_behavior(self):
        assert observe_kind("curl http://example.com") == "behavior"

    def test_nslookup_is_behavior(self):
        assert observe_kind("nslookup example.com") == "behavior"

    def test_ping_is_behavior(self):
        assert observe_kind("ping 10.0.0.1") == "behavior"

    def test_show_config_is_config_query(self):
        assert observe_kind("show sdns listener") == "config_query"

    def test_display_is_config_query(self):
        assert observe_kind("display sdns listener") == "config_query"

    def test_show_statistics_is_behavior(self):
        assert observe_kind("show statistics sdns pool") == "behavior"

    def test_show_session_is_behavior(self):
        assert observe_kind("show sdns session") == "behavior"

    def test_show_counter_is_behavior(self):
        assert observe_kind("show sdns counter") == "behavior"

    def test_show_counters_is_behavior(self):
        assert observe_kind("show sdns counters") == "behavior"

    def test_config_command_returns_empty(self):
        assert observe_kind("sdns listener 172.16.34.200") == ""

    def test_empty_returns_empty(self):
        assert observe_kind("") == ""
        assert observe_kind(None) == ""


class TestIsObserveCommand:
    def test_show_is_observe(self):
        assert is_observe_command("show running-config") is True

    def test_dig_is_observe(self):
        assert is_observe_command("dig example.com") is True

    def test_config_not_observe(self):
        assert is_observe_command("sdns listener 172.16.34.200") is False

    def test_empty_not_observe(self):
        assert is_observe_command("") is False


class TestConfigExistenceCheck:
    def test_config_existence_found(self):
        is_check, matched = config_existence_check(
            "show sdns listener",
            "sdns listener",
            ["sdns listener 172.16.34.200"],
            method="found",
        )
        assert is_check is True
        assert "sdns listener" in matched

    def test_not_found_is_not_existence_check(self):
        is_check, matched = config_existence_check(
            "show sdns listener",
            "sdns listener",
            ["sdns listener 172.16.34.200"],
            method="not_found",
        )
        assert is_check is False
        assert matched != ""

    def test_abs_found_is_not_existence_check(self):
        is_check, matched = config_existence_check(
            "show sdns listener",
            "sdns listener",
            ["sdns listener 172.16.34.200"],
            method="abs_found",
        )
        assert is_check is False

    def test_behavior_observe_not_config_check(self):
        is_check, matched = config_existence_check(
            "dig example.com",
            "example.com",
            ["sdns listener 172.16.34.200"],
            method="found",
        )
        assert is_check is False

    def test_empty_expect(self):
        is_check, matched = config_existence_check(
            "show sdns listener", "", ["sdns listener 172.16.34.200"]
        )
        assert is_check is False

    def test_no_matching_config(self):
        is_check, matched = config_existence_check(
            "show sdns listener",
            "health-check",
            ["sdns listener 172.16.34.200"],
            method="found",
        )
        assert is_check is False
        assert matched == ""
