"""KMS slash command helpers（Ink 进度回写、product update 校验）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from main.qa_agent.tui.kms_command import (
    _dispatch_product,
    _flush_log_to_ui,
    _post_kms_status,
    _should_echo_log_line,
)


def test_should_echo_log_line_batch_and_cache():
    assert _should_echo_log_line("[batch 2/8] 提交 30 个文件") is True
    assert _should_echo_log_line("  [cache] foo.docx → /path/a.md") is True
    assert _should_echo_log_line("random debug noise") is False


def test_flush_log_to_ui_updates_thinking_and_transcript(tmp_path):
    log = tmp_path / "t.log"
    log.write_text("--- kms start ---\n[batch 1/2] hello\n", encoding="utf-8")
    app = MagicMock()
    app.append_transcript_info = MagicMock()
    app.set_background_status = MagicMock()
    offset = _flush_log_to_ui(app, log, 0, "[/kms product update]")
    assert offset > 0
    app.set_background_status.assert_called()
    app.append_transcript_info.assert_called()


def test_post_kms_status_uses_append_transcript_info():
    app = MagicMock()
    app.append_transcript_info = MagicMock()
    _post_kms_status(app, "hello")
    app.append_transcript_info.assert_called_once_with("hello")


def test_dispatch_product_update_requires_mineru_only():
    app = MagicMock()
    app.append_transcript_info = MagicMock()
    with patch.dict("os.environ", {"MINERU_TOKEN": "tok"}, clear=False):
        import os

        os.environ.pop("DASHSCOPE_API_KEY", None)
        os.environ.pop("BAILIAN_API_KEY", None)
        with patch("main.qa_agent.tui.kms_command._orgin_buckets") as mock_bucket:
            mock_bucket.return_value = {"product": ["a.pdf"], "test_case_list": [], "test_strategy": [], "unclassified": []}
            with patch("main.qa_agent.tui.kms_command._kick_product_update") as mock_kick:
                from main.qa_agent.tui.slash_commands import InfoResult

                result = _dispatch_product("update", "", app)
                assert isinstance(result, InfoResult)
                assert "mineru_batch_export" in result.text
                assert "DASHSCOPE" not in result.text
                mock_kick.assert_called_once()
                assert mock_kick.call_args.kwargs.get("product_files") == "a.pdf"


def test_dispatch_product_update_missing_mineru_token():
    app = MagicMock()
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("MINERU_TOKEN", None)
        os.environ.pop("MINERU_API_TOKEN", None)
        from main.qa_agent.tui.slash_commands import ErrorResult

        result = _dispatch_product("update", "", app)
        assert isinstance(result, ErrorResult)
        assert "MINERU_TOKEN" in result.text
