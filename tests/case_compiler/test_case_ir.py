"""Tests for main.case_compiler.case_ir — IR data structures and validation."""

from __future__ import annotations

from main.case_compiler.case_ir import (
    CaseIR,
    FileIR,
    Row,
    Step,
    VALID_APV_METHODS,
    VALID_CHECK_METHODS,
    VALID_TEST_ENV_HOSTS,
    VALID_TEST_OBJECTS,
    _effective_whitelists,
    validate_case,
    validate_row,
)


class TestRow:
    def test_is_check_point_true(self):
        r = Row(test_object="check_point", method="found", data="expected")
        assert r.is_check_point() is True

    def test_is_check_point_false(self):
        r = Row(test_object="APV_0", method="cmd_config", data="sdns on")
        assert r.is_check_point() is False

    def test_default_values(self):
        r = Row()
        assert r.test_object == ""
        assert r.method == ""
        assert r.data == ""
        assert r.save_as is None
        assert r.input_var is None
        assert r.provenance is None


class TestStep:
    def test_construction(self):
        rows = [Row(test_object="APV_0", method="cmd_config")]
        s = Step(stmt_type=2, description="test step", rows=rows)
        assert s.stmt_type == 2
        assert s.description == "test step"
        assert len(s.rows) == 1


class TestCaseIR:
    def test_check_point_count_zero(self):
        c = CaseIR(autoid="t1", steps=[
            Step(stmt_type=2, description="config", rows=[
                Row(test_object="APV_0", method="cmd_config", data="sdns on"),
            ]),
        ])
        assert c.check_point_count() == 0

    def test_check_point_count_nonzero(self):
        c = CaseIR(autoid="t2", steps=[
            Step(stmt_type=2, description="verify", rows=[
                Row(test_object="APV_0", method="cmd_config", data="show sdns"),
                Row(test_object="check_point", method="found", data="sdns"),
            ]),
        ])
        assert c.check_point_count() == 1

    def test_check_point_count_multiple_steps(self):
        c = CaseIR(autoid="t3", steps=[
            Step(stmt_type=2, description="s1", rows=[
                Row(test_object="check_point", method="found", data="a"),
            ]),
            Step(stmt_type=3, description="s2", rows=[
                Row(test_object="check_point", method="not_found", data="b"),
                Row(test_object="check_point", method="abs_found", data="c"),
            ]),
        ])
        assert c.check_point_count() == 3

    def test_default_priority(self):
        c = CaseIR(autoid="t4")
        assert c.priority == "P1"

    def test_is_passthrough_default(self):
        c = CaseIR(autoid="t5")
        assert c.is_passthrough is False


class TestFileIR:
    def test_construction(self):
        f = FileIR(feature="sdns_listener", author="Tester")
        assert f.feature == "sdns_listener"
        assert f.author == "Tester"
        assert f.init_rows == []
        assert f.cases == []
        assert f.module == ""


class TestValidateRow:
    def test_valid_check_point_found(self):
        r = Row(test_object="check_point", method="found", data="expected")
        assert validate_row(r) == []

    def test_valid_check_point_abs_found(self):
        r = Row(test_object="check_point", method="abs_found", data="expected")
        assert validate_row(r) == []

    def test_invalid_check_point_method(self):
        r = Row(test_object="check_point", method="invalid_method", data="expected")
        errs = validate_row(r)
        assert len(errs) == 1
        assert "不是合法断言类型" in errs[0]

    def test_found_times_needs_input_var(self):
        r = Row(test_object="check_point", method="found_times", data="expected")
        errs = validate_row(r)
        assert any("found_times 需要 I 列" in e for e in errs)

    def test_found_times_with_input_var_ok(self):
        r = Row(test_object="check_point", method="found_times", data="expected", input_var="3")
        assert validate_row(r) == []

    def test_invalid_test_object(self):
        r = Row(test_object="INVALID_OBJ", method="cmd_config")
        errs = validate_row(r)
        assert len(errs) == 1
        assert "不是合法测试对象" in errs[0]

    def test_test_env_valid_host(self):
        r = Row(test_object="test_env", method="routera")
        assert validate_row(r) == []

    def test_test_env_invalid_host(self):
        r = Row(test_object="test_env", method="unknown_host")
        errs = validate_row(r)
        assert any("不是合法主机名" in e for e in errs)

    def test_time_valid_sleep(self):
        r = Row(test_object="time", method="sleep", data="5")
        assert validate_row(r) == []

    def test_time_invalid_method(self):
        r = Row(test_object="time", method="wait", data="5")
        errs = validate_row(r)
        assert any("F 必须为 sleep" in e for e in errs)

    def test_apv_0_cmd_config(self):
        r = Row(test_object="APV_0", method="cmd_config", data="sdns on")
        assert validate_row(r) == []


class TestValidateCase:
    def test_no_check_point_error(self):
        c = CaseIR(autoid="t1", steps=[
            Step(stmt_type=2, description="config only", rows=[
                Row(test_object="APV_0", method="cmd_config", data="sdns on"),
            ]),
        ])
        errs = validate_case(c)
        assert any("无 check_point" in e for e in errs)

    def test_valid_case_passes(self):
        c = CaseIR(autoid="t2", steps=[
            Step(stmt_type=2, description="config", rows=[
                Row(test_object="APV_0", method="cmd_config", data="sdns on"),
            ]),
            Step(stmt_type=3, description="verify", rows=[
                Row(test_object="APV_0", method="cmd_config", data="show sdns"),
                Row(test_object="check_point", method="found", data="sdns"),
            ]),
        ])
        errs = validate_case(c)
        assert errs == []

    def test_row_errors_propagated(self):
        c = CaseIR(autoid="t3", steps=[
            Step(stmt_type=2, description="bad row", rows=[
                Row(test_object="check_point", method="invalid_method", data="x"),
            ]),
        ])
        errs = validate_case(c)
        assert any("不是合法断言类型" in e for e in errs)


class TestEffectiveWhitelists:
    def test_default_whitelists(self):
        check, hosts, generic = _effective_whitelists()
        assert check == set(VALID_CHECK_METHODS)
        assert hosts == set(VALID_TEST_ENV_HOSTS)
        assert generic == set(VALID_APV_METHODS)

    def test_snapshot_overrides(self):
        class FakeSnapshot:
            check_methods = ["found", "custom_check"]
            test_env_hosts = ["host_a"]
            generic_methods = ["cmd_config"]

        check, hosts, generic = _effective_whitelists(FakeSnapshot())
        assert check == {"found", "custom_check"}
        assert hosts == {"host_a"}
        assert generic == {"cmd_config"}
