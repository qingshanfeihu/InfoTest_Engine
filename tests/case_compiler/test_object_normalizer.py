"""Tests for main.case_compiler.object_normalizer — E column name normalization."""

from __future__ import annotations

from main.case_compiler.object_normalizer import ObjectNameNormalizer, get_object_normalizer


class TestCanonObject:
    def setup_method(self):
        self.norm = ObjectNameNormalizer()

    def test_none_returns_none(self):
        assert self.norm.canon_object(None) is None

    def test_empty_returns_none(self):
        assert self.norm.canon_object("") is None
        assert self.norm.canon_object("  ") is None

    def test_check_point_keyword(self):
        assert self.norm.canon_object("check_point") == "check_point"
        assert self.norm.canon_object("checkpoint") == "check_point"
        assert self.norm.canon_object("check") == "check_point"

    def test_test_env_keyword(self):
        assert self.norm.canon_object("test_env") == "test_env"
        assert self.norm.canon_object("testenv") == "test_env"
        assert self.norm.canon_object("env") == "test_env"

    def test_time_keyword(self):
        assert self.norm.canon_object("time") == "time"
        assert self.norm.canon_object("sleep") == "time"
        assert self.norm.canon_object("wait") == "time"

    def test_apv_device_variants(self):
        assert self.norm.canon_object("APV0") == "APV_0"
        assert self.norm.canon_object("apv_0") == "APV_0"
        assert self.norm.canon_object("APV1") == "APV_1"
        assert self.norm.canon_object("apv_1") == "APV_1"
        assert self.norm.canon_object("APV") == "APV_0"

    def test_segment_device(self):
        assert self.norm.canon_object("Seg0") == "APV_0"
        assert self.norm.canon_object("segment1") == "APV_1"

    def test_dut_device(self):
        assert self.norm.canon_object("DUT0") == "APV_0"
        assert self.norm.canon_object("dut1") == "APV_1"

    def test_hostname_becomes_test_env(self):
        assert self.norm.canon_object("routera") == "test_env"
        assert self.norm.canon_object("clientc") == "test_env"

    def test_non_alphanumeric_returns_none(self):
        assert self.norm.canon_object("192.168.1.1") is None

    def test_quoted_string_stripped(self):
        assert self.norm.canon_object("'check_point'") == "check_point"
        assert self.norm.canon_object('"apv_0"') == "APV_0"

    def test_case_insensitive(self):
        assert self.norm.canon_object("CHECK_POINT") == "check_point"
        assert self.norm.canon_object("TEST_ENV") == "test_env"
        assert self.norm.canon_object("TIME") == "time"


class TestDeviceAliases:
    def test_alias_override(self):
        norm = ObjectNameNormalizer(device_aliases={"routera": "APV_0"})
        assert norm.canon_object("routera") == "APV_0"

    def test_alias_case_insensitive(self):
        norm = ObjectNameNormalizer(device_aliases={"RouterA": "APV_0"})
        assert norm.canon_object("routera") == "APV_0"


class TestGetObjectNormalizer:
    def test_returns_singleton(self):
        n1 = get_object_normalizer()
        n2 = get_object_normalizer()
        assert n1 is n2
