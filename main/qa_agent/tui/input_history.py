"""InputHistory：query 历史栈 + Ctrl+R 搜索。


+ shell history 搜索行为。

设计：
- 持久化到 ``~/.config/infotest/history``（每次 append；启动时 load 最近 N 条）
- 内存里按用户输入顺序追加（不去重，但相邻同条合并）
- ↑ 向后翻（older），↓ 向前翻（newer）
- Ctrl+R 进搜索模式：当前输入作 prefix，substring 搜索（不区分大小写），多次按 Ctrl+R
  跳下一个匹配
- Esc 退出搜索 -> 恢复输入框为搜索前内容
"""

from __future__ import annotations

import os
from pathlib import Path


_HISTORY_PATH = Path(os.environ.get(
    "INFOTEST_HISTORY_PATH",
    str(Path.home() / ".config" / "infotest" / "history"),
))
_MAX_HISTORY = 1000


class InputHistory:
    """方向键历史 + Ctrl+R 搜索状态机。"""

    def __init__(self, *, path: Path | None = None, max_items: int = _MAX_HISTORY) -> None:
        self._path = path if path is not None else _HISTORY_PATH
        self._max = max_items
        self._items: list[str] = self._load()
        # ``cursor`` 指向当前查看的历史项（None 表示未在翻历史）
        self._cursor: int | None = None
        # 翻历史前用户的输入（按 ↑ 之前的草稿），↓ 翻回时恢复
        self._draft: str = ""
        # Ctrl+R 搜索模式
        self._search_mode = False
        self._search_query: str = ""
        self._search_matches: list[int] = []  # 当前 query 的命中 idx 序列
        self._search_idx: int = -1            # 在 _search_matches 中的位置

    # -- Persistence --------------------------------------------------------

    def _load(self) -> list[str]:
        try:
            if not self._path.exists():
                return []
            lines = self._path.read_text(encoding="utf-8").splitlines()
            return [ln.rstrip("\n") for ln in lines if ln.strip()][-self._max:]
        except Exception:
            return []

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                "\n".join(self._items[-self._max:]) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass  # 历史持久化失败不应阻塞 TUI

    # -- Core API -----------------------------------------------------------

    def add(self, text: str) -> None:
        """提交一条 query 后调用。空 / 与最近一条相同 -> 跳过（仿 bash dedupe）。"""
        text = (text or "").rstrip()
        if not text:
            return
        if self._items and self._items[-1] == text:
            return
        self._items.append(text)
        if len(self._items) > self._max:
            self._items = self._items[-self._max :]
        self._persist()
        self._cursor = None
        self._draft = ""

    def up(self, current_input: str) -> str | None:
        """↑ 翻 older。第一次按时记录 current_input 为 draft。返回新输入框内容。"""
        if not self._items:
            return None
        if self._cursor is None:
            self._draft = current_input
            self._cursor = len(self._items) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._items[self._cursor]

    def down(self, current_input: str) -> str | None:
        """↓ 翻 newer。到底了恢复 draft。"""
        if self._cursor is None:
            return None
        if self._cursor < len(self._items) - 1:
            self._cursor += 1
            return self._items[self._cursor]
        # 到最新一条之后再 ↓ -> 恢复 draft
        self._cursor = None
        return self._draft

    def reset_navigation(self) -> None:
        self._cursor = None
        self._draft = ""

    # -- Search mode (Ctrl+R) ----------------------------------------------

    def start_search(self, current_input: str) -> str | None:
        """进入搜索模式。``current_input`` 作初始 query；返回当前最近匹配项（或 None）。"""
        self._search_mode = True
        self._search_query = current_input
        self._search_idx = -1
        self._draft = current_input
        return self.search_next()

    def update_search_query(self, query: str) -> str | None:
        """搜索模式下用户继续输入字符 -> 重新过滤。"""
        if not self._search_mode:
            return None
        self._search_query = query
        self._search_idx = -1
        return self.search_next()

    def search_next(self) -> str | None:
        """跳下一个匹配（再按 Ctrl+R）。"""
        if not self._search_mode:
            return None
        q = (self._search_query or "").lower()
        if not q:
            return None
        # 重新计算匹配（数据可能动了），从最新到最旧
        self._search_matches = [
            i for i, item in enumerate(reversed(self._items))
            if q in item.lower()
        ]
        if not self._search_matches:
            return None
        self._search_idx = (self._search_idx + 1) % len(self._search_matches)
        # _search_matches 是反向索引；转回正向 idx
        reverse_idx = self._search_matches[self._search_idx]
        return self._items[len(self._items) - 1 - reverse_idx]

    def exit_search(self, *, restore: bool = True) -> str:
        """退出搜索模式。``restore=True`` 恢复进搜索前的 draft。"""
        self._search_mode = False
        self._search_query = ""
        self._search_matches = []
        self._search_idx = -1
        if restore:
            return self._draft
        return self._search_query  # 已清空

    @property
    def in_search_mode(self) -> bool:
        return self._search_mode

    @property
    def search_query(self) -> str:
        return self._search_query

    # -- Diagnostics --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list[str]:
        return list(self._items)
