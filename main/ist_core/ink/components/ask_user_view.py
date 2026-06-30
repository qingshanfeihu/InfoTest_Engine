"""ask_user 的 TUI 交互式问答会话。

.. note:: 引入 logging 供异常记录。

把"渲染选项 + 键盘导航 + 提交答案"从 ist_app（已 2000 行）里拆出来，
ist_app 只在 _handle_key 顶部拦截、把按键委托给本模块。

数据流：
- 工具 emit ``ask_user_request`` → reducer 生成 ask_user 块 → ist_app
  _render_content_block 检测到 → ``AskUserSession.begin()`` 进入问答模式
- 用户按键 → ``handle_key()`` 更新高亮/选择 → 提交时调
  ``tools.ask_user.submit_answers(question_id, answers)`` 唤醒阻塞的工具线程
- 工具线程解阻塞，graph 继续跑

交互（单题）：
- ↑↓ / j k：移动高亮
- 1-9：数字直选
- space：multiSelect 下切换选中
- enter：单选=确认该项并进入下一题/提交；multiSelect=进入下一题/提交
- o：选 "Other"，转入自由文本输入（复用 PromptInput）
- esc：取消整个问答（工具收到空答案 → "User cancelled"）
"""

from __future__ import annotations

from typing import Any, Callable

_OTHER_VALUE = "__other__"


class AskUserSession:
    """单次 ask_user 调用的交互状态机。

    一次调用可含 1-4 个问题，逐题导航。每题维护高亮 index + 已选集合。
    """

    def __init__(
        self,
        question_id: str,
        questions: list[dict],
        *,
        render: Callable[[], None],
        on_finish: Callable[[], None],
    ) -> None:
        self._question_id = question_id
        self._questions = questions
        self._render = render          # 请求重绘 transcript 的回调
        self._on_finish = on_finish    # 问答结束（提交/取消）后清理回调
        self._q_idx = 0                # 当前问题索引
        # 每题的已选 label 集合（单选只留一个）
        self._selected: list[set[str]] = [set() for _ in questions]
        self._highlight = 0            # 当前题的高亮 option 索引
        self._other_text: dict[int, str] = {}  # q_idx -> Other 自由文本
        self._other_input = False      # 是否处于 Other 文本输入态

    # ── 渲染 ──────────────────────────────────────────────────────────

    @property
    def in_other_input(self) -> bool:
        return self._other_input

    def _cur_question(self) -> dict:
        return self._questions[self._q_idx]

    def _options(self) -> list[dict]:
        return self._cur_question().get("options", []) or []

    def render_lines(self) -> list[str]:
        """渲染当前问题为若干文本行（带 ANSI），供 transcript 显示。"""
        q = self._cur_question()
        opts = self._options()
        multi = bool(q.get("multiSelect"))
        sel = self._selected[self._q_idx]

        B, D, C, G, X = (
            "\x1b[1m", "\x1b[2m", "\x1b[36m", "\x1b[32m", "\x1b[0m",
        )
        lines: list[str] = []
        header = q.get("header", "")
        total = len(self._questions)
        nav = f" ({self._q_idx + 1}/{total})" if total > 1 else ""
        lines.append(f" {C}?{X} {B}{q.get('question', '')}{X}{D}{nav}{X}")
        if header:
            lines.append(f"   {D}[{header}]{X}")

        # Other 选项占位（始终作为最后一项，index = len(opts)）
        all_rows = list(opts) + [{"label": "Other", "description": "自定义输入", "_other": True}]
        for i, opt in enumerate(all_rows):
            label = opt.get("label", "")
            desc = opt.get("description", "")
            is_other = opt.get("_other")
            focused = (i == self._highlight)
            selected = (_OTHER_VALUE if is_other else label) in sel
            # 多选前置 [x]/[ ] 框（前置框可读性更好，保留）
            marker = ""
            if multi:
                marker = f"{G}[x]{X} " if selected else "[ ] "
            cursor = f"{C}❯{X}" if focused else " "
            num = f"{D}{i + 1}.{X}"
            # A2 颜色状态机：已选→绿(success) / 聚焦→加粗高亮 / 否则默认
            if selected:
                label_styled = f"{G}{label}{X}"
            elif focused:
                label_styled = f"{B}{label}{X}"
            else:
                label_styled = label
            line = f" {cursor} {num} {marker}{label_styled}"
            if desc:
                desc_color = G if selected else D
                line += f"  {desc_color}— {desc}{X}"
            lines.append(line)
            if is_other and self._other_text.get(self._q_idx):
                lines.append(f"       {G}→ {self._other_text[self._q_idx]}{X}")

        hint = "↑↓ 选择 · 数字直选 · "
        if multi:
            hint += "space 勾选 · "
        if total > 1:
            hint += "←→/Tab 切题 · "
        hint += "enter 确认 · o 自定义 · esc 取消"
        lines.append(f"   {D}{hint}{X}")
        return lines

    # ── 按键处理 ──────────────────────────────────────────────────────

    def handle_key(self, key: str, char: str) -> bool:
        """处理一个按键。返回 True 表示已消费（问答模式拦截）。"""
        if self._other_input:
            return False  # Other 文本输入交给 PromptInput，提交在 ist_app 侧处理

        opts_count = len(self._options())
        rows_count = opts_count + 1  # +1 for Other

        if key in ("up", "ctrl+p"):
            self._highlight = (self._highlight - 1) % rows_count
            self._render()
            return True
        if key in ("down", "ctrl+n"):
            self._highlight = (self._highlight + 1) % rows_count
            self._render()
            return True
        if key and key.isdigit():
            n = int(key)
            if 1 <= n <= rows_count:
                self._highlight = n - 1
                self._render()
                return True
        if key == "space":
            self._toggle_current()
            self._render()
            return True
        if key == "escape":
            self.cancel()
            return True
        # A4：多题双向导航（←→ / Tab / Shift+Tab），可回头改，已选状态保留
        if len(self._questions) > 1:
            if key in ("left", "shift+tab"):
                self._goto_question(self._q_idx - 1)
                return True
            if key in ("right", "tab"):
                self._goto_question(self._q_idx + 1)
                return True
        if key in ("o", "O") or (char in ("o", "O")):
            # 跳到 Other 行并进入文本输入
            self._highlight = rows_count - 1
            self._other_input = True
            self._render()
            return True
        if key in ("return", "enter"):
            self._on_enter()
            return True
        return True  # 问答模式下吞掉其他按键，避免漏到下层

    def _is_other_highlighted(self) -> bool:
        return self._highlight == len(self._options())

    def _toggle_current(self) -> None:
        q = self._cur_question()
        if not q.get("multiSelect"):
            return
        sel = self._selected[self._q_idx]
        if self._is_other_highlighted():
            key = _OTHER_VALUE
        else:
            key = self._options()[self._highlight].get("label", "")
        if key in sel:
            sel.discard(key)
        else:
            sel.add(key)

    def _on_enter(self) -> None:
        q = self._cur_question()
        if self._is_other_highlighted():
            self._other_input = True
            self._render()
            return
        if not q.get("multiSelect"):
            # 单选：enter 选中当前高亮项
            self._selected[self._q_idx] = {self._options()[self._highlight].get("label", "")}
        self._advance_or_submit()

    def submit_other_text(self, text: str) -> None:
        """Other 自由文本输入完成后由 ist_app 调用。"""
        self._other_text[self._q_idx] = text.strip()
        q = self._cur_question()
        if q.get("multiSelect"):
            self._selected[self._q_idx].add(_OTHER_VALUE)
        else:
            self._selected[self._q_idx] = {_OTHER_VALUE}
        self._other_input = False
        self._advance_or_submit()

    def cancel_other_input(self) -> None:
        self._other_input = False
        self._render()

    def _advance_or_submit(self) -> None:
        if self._q_idx < len(self._questions) - 1:
            self._q_idx += 1
            self._highlight = 0
            self._render()
        else:
            self._submit()

    def _goto_question(self, idx: int) -> None:
        """A4：切到第 idx 题（双向，越界忽略）。已选状态按题保留。"""
        if 0 <= idx < len(self._questions):
            self._q_idx = idx
            self._highlight = 0
            self._render()

    def result_summary(self) -> str:
        """A3：问答结束后给 transcript 的一行完成提示。"""
        answered = {
            q.get("question", ""): self._answer_text_for(i)
            for i, q in enumerate(self._questions)
        }
        if not any(answered.values()):
            return " \x1b[2m● 已取消\x1b[0m"
        parts = [f"{q} → {a}" for q, a in answered.items() if a]
        body = " · ".join(parts)
        return f" \x1b[32m●\x1b[0m \x1b[2m已回答 · {body}\x1b[0m"

    # ── 提交 / 取消 ───────────────────────────────────────────────────

    def _answer_text_for(self, q_idx: int) -> str:
        """把某题的已选 label 集合转成答案字符串（multi 用逗号连接）。"""
        sel = self._selected[q_idx]
        parts: list[str] = []
        for opt in self._options_at(q_idx):
            label = opt.get("label", "")
            if label in sel:
                parts.append(label)
        if _OTHER_VALUE in sel:
            parts.append(self._other_text.get(q_idx, "").strip())
        return ", ".join(p for p in parts if p)

    def _options_at(self, q_idx: int) -> list[dict]:
        return self._questions[q_idx].get("options", []) or []

    def _submit(self) -> None:
        answers: dict[str, str] = {}
        for i, q in enumerate(self._questions):
            answers[q.get("question", "")] = self._answer_text_for(i)
        self._deliver(answers)

    def cancel(self) -> None:
        self._deliver({})  # 空答案 → 工具返回 "User cancelled"

    def _deliver(self, answers: dict[str, str]) -> None:
        try:
            from main.ist_core.tools.ask_user import submit_answers
            submit_answers(self._question_id, answers)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "ask_user 提交答案失败: question_id=%s", self._question_id, exc_info=True,
            )
        self._on_finish()
