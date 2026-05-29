"""TuiSink —— EventBus → MessageReducer → MessageSnapshot 的薄适配器。

历史背景：旧版 TuiSink (376 行) 直接把 ``IstCoreEvent`` 翻译成 17 类 IstUiEvent
分发给 UI；导致双源去重靠字符串前缀指纹（``_last_final_thought_prefix``），
长 + 短 final_thought 序列下指纹被覆盖、长报告渲染 2 次。

重构后：sink 只做事件转发，状态聚合 / 业务规则 / 去重统统下沉到
``MessageReducer``。订阅者收到的是不可变 ``MessageSnapshot``——可以直接渲染，
不需要再追历史 / 算 diff（diff 由 Transcript 按 ``message.uuid`` 处理）。

架构说明：``handleMessageFromStream`` 等价于本模块 + reducer 之和；
我们拆成两层是因为 Python 没有 React 的批处理 setState，需要一个不可变快照
作为跨线程载荷。
"""

from __future__ import annotations

import logging
from typing import Callable

from main.ist_core.events import IstCoreEvent
from main.ist_core.tui.message_model import MessageSnapshot
from main.ist_core.tui.reducer import MessageReducer

logger = logging.getLogger(__name__)


class TuiSink:
    """订阅 EventBus 的薄适配器；把事件灌进 reducer，订阅 snapshot 转发到 UI。

    用法::

        sink = TuiSink(post=app.on_snapshot)  # post 必须线程安全 / 跨线程投递
        bus.subscribe(sink)

    sink 是同步回调，``__call__`` 在 graph worker 线程被调；reducer 内部 Lock
    保护可变状态；快照通过 ``post`` 投递到 UI 线程（IstApp 用
    ``self.call_from_thread`` 包一层）。
    """

    def __init__(self, *, post: Callable[[MessageSnapshot], None]) -> None:
        self._post = post
        self._reducer = MessageReducer()
        self._reducer.subscribe(self._post)

    @property
    def reducer(self) -> MessageReducer:
        """暴露 reducer 给 bridge——run_done/run_error 时调
        ``set_run_status`` 切换 UI 状态。"""
        return self._reducer

    def __call__(self, event: IstCoreEvent) -> None:
        try:
            self._reducer.dispatch(event)
        except Exception:  # noqa: BLE001
            logger.exception("TuiSink dispatch error")

    def reset(self) -> None:
        """新 run 开始前重置（保留同一订阅者）。"""
        self._reducer = MessageReducer()
        self._reducer.subscribe(self._post)


__all__ = ["TuiSink"]
