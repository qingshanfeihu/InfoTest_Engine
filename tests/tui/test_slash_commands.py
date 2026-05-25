"""Stage 7-1 slash_commands tests.

Three tiers:
1. parse_slash_command: 端口正确性（对齐 utils/slashCommandParsing.ts）
2. dispatch_slash_command: 12 个内置命令路由 + unknown command 错误
3. filter_completions: 补全候选过滤
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from main.qa_agent.tui.slash_commands import (
    BUILTIN_COMMANDS,
    ClearResult,
    ErrorResult,
    ExitResult,
    InfoResult,
    InjectResult,
    InterceptResult,
    ParsedSlashCommand,
    TextResult,
    dispatch_slash_command,
    filter_completions,
    parse_slash_command,
)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_parse_simple_command():
    p = parse_slash_command("/search foo bar")
    assert p == ParsedSlashCommand(command_name="search", args="foo bar", is_mcp=False)


def test_parse_command_no_args():
    p = parse_slash_command("/help")
    assert p == ParsedSlashCommand(command_name="help", args="", is_mcp=False)


def test_parse_command_extra_whitespace_trimmed():
    p = parse_slash_command("   /clear   ")
    assert p == ParsedSlashCommand(command_name="clear", args="", is_mcp=False)


def test_parse_mcp_command():
    p = parse_slash_command("/mcp:tool (MCP) arg1 arg2")
    assert p == ParsedSlashCommand(command_name="mcp:tool (MCP)", args="arg1 arg2", is_mcp=True)


def test_parse_non_slash_input_returns_none():
    assert parse_slash_command("hello world") is None
    assert parse_slash_command("") is None
    assert parse_slash_command(None) is None  # type: ignore[arg-type]


def test_parse_just_a_slash_returns_none():
    """``/`` alone -> empty command name -> return None ."""
    assert parse_slash_command("/") is None
    assert parse_slash_command("/  ") is None


# ---------------------------------------------------------------------------
# Built-in command registry
# ---------------------------------------------------------------------------


def test_registry_has_expected_builtin_commands():
    names = {cmd.name for cmd in BUILTIN_COMMANDS}
    expected = {
        "help", "clear", "threads", "resume", "continue", "model",
        "cost", "compact", "plan", "init", "reset", "memory", "remember",
        "footprint", "version", "exit",
    }
    assert names == expected


def test_all_commands_have_description_and_handler():
    for cmd in BUILTIN_COMMANDS:
        assert cmd.name
        assert cmd.description
        assert callable(cmd.handler)
        assert cmd.source == "builtin"


# ---------------------------------------------------------------------------
# Dispatch handlers
# ---------------------------------------------------------------------------


def _mock_app():
    """Build a minimal app stub for handlers that don't touch real bridge/checkpoint."""
    from main.qa_agent.tui.state import TuiState

    app = MagicMock()
    # 真 dataclass，避免 MagicMock 拦截属性赋值
    app.tui_state = TuiState(tokens_used=0, tokens_budget=128000)
    return app


def test_dispatch_help_returns_text_result_with_all_commands():
    p = parse_slash_command("/help")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, TextResult)
    for name in ("help", "clear", "threads", "resume", "continue", "model",
                 "cost", "compact", "plan", "init", "version", "exit"):
        assert f"/{name}" in result.text, f"/{name} missing from /help output"


def test_dispatch_clear_returns_clear_result():
    p = parse_slash_command("/clear")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, ClearResult)


def test_dispatch_exit_returns_exit_result():
    p = parse_slash_command("/exit")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, ExitResult)


def test_dispatch_version_returns_info_result_with_version():
    p = parse_slash_command("/version")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, InfoResult)
    assert "infotest" in result.text
    assert "1.0.2" in result.text


def test_dispatch_resume_without_arg_returns_error():
    p = parse_slash_command("/resume")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, ErrorResult)
    assert "usage" in result.text.lower()


def test_dispatch_resume_calls_app_thread_selected():
    app = _mock_app()
    p = parse_slash_command("/resume run-abc123")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, InfoResult)
    app._on_thread_selected.assert_called_once_with("run-abc123")


def test_dispatch_continue_when_no_recent_thread():
    app = _mock_app()
    app._checkpoint_repo.most_recent_thread_id.return_value = None
    p = parse_slash_command("/continue")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, ErrorResult)


def test_dispatch_continue_uses_most_recent():
    app = _mock_app()
    app._checkpoint_repo.most_recent_thread_id.return_value = "run-recent"
    p = parse_slash_command("/continue")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, InfoResult)
    app._on_thread_selected.assert_called_once_with("run-recent")


def test_dispatch_model_with_arg_records_override(monkeypatch):
    """/model <name> 设置 override（name 必须在 IST_ALLOWED_MODELS 列表里）。"""
    monkeypatch.setenv("IST_ALLOWED_MODELS", "qwen-plus,gpt-4-turbo,claude-haiku")
    app = _mock_app()
    p = parse_slash_command("/model gpt-4-turbo")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, InfoResult)
    assert "gpt-4-turbo" in result.text
    assert app.tui_state.__dict__.get("override_model") == "gpt-4-turbo"


def test_dispatch_model_no_arg_lists_available(monkeypatch):
    """/model 无参 -> 列出可用模型 + 标 current。"""
    monkeypatch.setenv("IST_ALLOWED_MODELS", "qwen-plus,gpt-4-turbo")
    app = _mock_app()
    p = parse_slash_command("/model")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, TextResult)
    assert "Available models" in result.text
    assert "qwen-plus" in result.text
    assert "gpt-4-turbo" in result.text


def test_dispatch_model_unknown_returns_error(monkeypatch):
    """/model <unknown> 不在 allowed list -> ErrorResult。"""
    monkeypatch.setenv("IST_ALLOWED_MODELS", "qwen-plus")
    app = _mock_app()
    p = parse_slash_command("/model unknown-model")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, ErrorResult)
    assert "not in allowed" in result.text


def test_dispatch_cost_returns_text_with_token_breakdown():
    app = _mock_app()
    app.tui_state.tokens_used = 5000
    app.tui_state.tokens_budget = 100_000
    app.tui_state.llm_calls = 10
    p = parse_slash_command("/cost")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, TextResult)
    assert "5,000" in result.text
    assert "100,000" in result.text


def test_dispatch_plan_returns_intercept_result():
    p = parse_slash_command("/plan")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, InterceptResult)
    assert result.mode == "plan"


def test_dispatch_init_returns_inject_with_bootstrap_prompt():
    p = parse_slash_command("/init")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, InjectResult)
    assert "qa_deepagent_ls" in result.prompt
    assert "README.md" in result.prompt


def test_dispatch_unknown_command_returns_error():
    p = parse_slash_command("/foobar baz")
    result = dispatch_slash_command(p, _mock_app())
    assert isinstance(result, ErrorResult)
    assert "Unknown command" in result.text
    assert "/foobar" in result.text


def test_dispatch_compact_resets_tokens_and_clears():
    app = _mock_app()
    app.tui_state.tokens_used = 50000
    p = parse_slash_command("/compact")
    result = dispatch_slash_command(p, app)
    assert isinstance(result, ClearResult)
    assert app.tui_state.tokens_used == 0


# ---------------------------------------------------------------------------
# Completion filter
# ---------------------------------------------------------------------------


def test_filter_completions_empty_prefix_returns_all():
    """空前缀（用户刚敲 `/`）-> 全部命令。"""
    completions = filter_completions("")
    assert len(completions) >= 8  # capped at limit=8


def test_filter_completions_with_slash_prefix_strips_it():
    completions = filter_completions("/cl")
    names = {c.name for c in completions}
    assert "clear" in names
    assert "help" not in names


def test_filter_completions_partial_match():
    completions = filter_completions("co")
    names = {c.name for c in completions}
    assert names == {"continue", "compact", "cost"}


def test_filter_completions_no_match_returns_empty():
    completions = filter_completions("zzz")
    assert completions == []


def test_filter_completions_respects_limit():
    completions = filter_completions("", limit=3)
    assert len(completions) == 3
