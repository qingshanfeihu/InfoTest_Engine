"""Stage 1 message-class smoke tests."""

from main.qa_agent.tui.messages import (
    AIFinalMessage,
    AIThinkingMessage,
    HumanInputMessage,
    IstMessage,
    PlatformTaskMessage,
    TOOL_NAME_TO_MESSAGE,
    ToolCallMessage,
)


def test_all_message_subclasses_inherit_base():
    for cls in [HumanInputMessage, AIThinkingMessage, AIFinalMessage, ToolCallMessage, PlatformTaskMessage]:
        assert issubclass(cls, IstMessage)


def test_dispatch_table_keys_are_known_tools():
    """Dispatch 表只包含我们声明过的通用工具名前缀。"""
    expected_prefixes = ("qa_", "python_exec", "bash_exec")
    for name in TOOL_NAME_TO_MESSAGE.keys():
        assert any(name.startswith(p) or name == p for p in expected_prefixes), name


def test_dispatch_table_values_are_subclasses():
    for cls in TOOL_NAME_TO_MESSAGE.values():
        assert issubclass(cls, IstMessage)


def test_message_has_default_run_id_seq_ts():
    m = HumanInputMessage(text="hi")
    assert m.run_id == "" and m.seq == 0 and m.ts == ""
    assert m.text == "hi"
    assert m.css_class == "ist-human-input"
