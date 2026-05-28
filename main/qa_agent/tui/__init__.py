"""IST-Core TUI package.

数据模型：``messages[]`` + ``streamingText`` 单源 reducer。

- ``message_model``: ContentBlock / Message / MessageSnapshot 不可变数据类
- ``reducer``: QaAgentEvent → MessageSnapshot 翻译器（含双源去重根治）
- ``sink``: 30 行薄适配器，连接 EventBus 与 reducer
- ``bridge``: 后台线程跑 LangGraph，订阅 reducer 把快照投到 UI
"""

from main.qa_agent.tui.message_model import (
    ContentBlock,
    Message,
    MessageSnapshot,
)

__all__ = ["ContentBlock", "Message", "MessageSnapshot"]
