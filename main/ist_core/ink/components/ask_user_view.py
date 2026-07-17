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

防呆（2026-07-16 zhaiyq 实弹 7 题丢 2 答；只加黄字提示，不改任何按键语义）：
- 空 Other 提交（532862）：留在输入态 + 「不能为空」提示，绝不落空答案。
- 已选未提交切题/esc（516576）：数字/↑↓ 只动高亮，enter(单选)/space(多选) 才落
  ``_selected``——动过高亮但未落答就 ←→/Tab 切题或 esc，黄字告警一次；紧接着再次
  同类按键放行（不锁死用户），其他按键则清提示重新计。
- 多题带未答整体提交/关闭：末题 enter 提交或 esc 取消时仍有未答题 → 提示
  「还有 N 题未答，未答题将按挂起处理」，再次同类操作放行。
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
        self._other_empty_hint = False  # 空文本提交被拦→面板显「不能为空」提示(防呆)
        # 516576 防呆状态:数字/↑↓ 只动高亮不落答,动过高亮即视为「已选」意图
        self._touched: list[bool] = [False] * len(questions)  # 每题是否动过高亮
        self._leave_warn: str | None = None  # 黄字告警文案(切题/esc/整体提交防呆),None=不显示
        self._warned_op: str | None = None   # 已告警的操作类别(switch/cancel/submit)→同类再次操作放行

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
        # A1 o 输入态可见提示(F-TUI-5,Design 裁;Test-Eng 卡壳实证:进了文本输入态却不
        # 自知、文本打进全局框)。other 态时面板顶部醒目提示,明确"在输入自定义文本+如何
        # 提交/取消",消除"以为在选项态"的误操作。
        if self._other_input:
            lines.append(
                f" {C}✎{X} {B}正在输入自定义文本{X}{D}——在下方输入框打字,"
                f"enter 提交 · esc 取消{X}")
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
            if is_other and self._other_empty_hint:
                # 防呆提示(空文本提交被拦):黄字,仅在 Other 空提交后驻留,补内容/esc 后清
                lines.append("       \x1b[33m⚠ 自定义输入不能为空——请输入内容,或按 esc 取消\x1b[0m")

        # 提示文案对齐实际按键语义(2026-07-17 team4 审计 P1-5):数字/↑↓ 只移动高亮
        # 不落答——旧文案「数字直选」承诺了"按数字即选定",正是 run15/17 两次 3 题丢 2
        # 的用户心智模型根因;落答动作(enter/space)必须在文案里说清。
        last_q = self._q_idx == total - 1
        hint = "↑↓/数字 移动 · "
        if multi:
            hint += "space 勾选 · " + ("enter 提交 · " if last_q else "enter 下一题 · ")
        else:
            hint += "enter 选定 · "
        if total > 1:
            hint += "←→/Tab 切题 · "
        hint += "o 输入自定义文本 · esc 取消"   # A1(F-TUI-5):「自定义」→说清是文本输入
        lines.append(f"   {D}{hint}{X}")
        if self._leave_warn:
            # 防呆黄字(已选未提交切题/esc、带未答整体提交):告警一次,再次同类操作放行
            lines.append(f"   \x1b[33m⚠ {self._leave_warn}\x1b[0m")
        return lines

    # ── 按键处理 ──────────────────────────────────────────────────────

    def handle_key(self, key: str, char: str) -> bool:
        """处理一个按键。返回 True 表示已消费（问答模式拦截）。"""
        if self._other_input:
            return False  # Other 文本输入交给 PromptInput，提交在 ist_app 侧处理

        opts_count = len(self._options())
        rows_count = opts_count + 1  # +1 for Other

        if key in ("up", "ctrl+p"):
            self._clear_warn()
            self._touched[self._q_idx] = True
            self._highlight = (self._highlight - 1) % rows_count
            self._render()
            return True
        if key in ("down", "ctrl+n"):
            self._clear_warn()
            self._touched[self._q_idx] = True
            self._highlight = (self._highlight + 1) % rows_count
            self._render()
            return True
        if key and key.isdigit():
            n = int(key)
            if 1 <= n <= rows_count:
                # F-TUI-1 补点(Design 2026-07-18 必带):末题数字直选提交走数字键(非 enter),
                # 未答挡板 armed 后再次数字=确认提交(对齐 enter 二次放行)。治死锁——数字分支
                # 下方 _clear_warn 会清 submit armed,若不在此先放行,末题数字直选提交遇未答
                # 会永远卡在挡板首次告警(无法二次确认)。Design 担心的"末题数字直选过挡板",
                # 实测是死锁(挡板触发了但放行不了)而非后门,此处根治。
                if self._warned_op == "submit":
                    self._clear_warn()
                    self._submit()
                    return True
                self._clear_warn()
                self._touched[self._q_idx] = True
                self._highlight = n - 1
                # F-TUI-1 数字直选(Design 裁,治 run15/17 两次实弹丢答:数字只高亮违用户
                # 直觉——按 3 以为选了 3、实际没落答)。单选=直选落答+前进;多选=勾选/取消
                # (数字直选在多选有歧义,保 toggle 语义);Other 行=进文本输入(不能直选空 Other)。
                if self._is_other_highlighted():
                    self._other_input = True
                    self._render()
                    return True
                if self._cur_question().get("multiSelect"):
                    self._toggle_current()
                    self._render()
                else:
                    self._selected[self._q_idx] = {
                        self._options()[self._highlight].get("label", "")}
                    self._advance_or_submit()
                return True
        if key == "space":
            self._clear_warn()
            self._toggle_current()
            self._render()
            return True
        if key == "escape":
            if self._guard_cancel():
                self.cancel()
            return True
        # A4：多题双向导航（←→ / Tab / Shift+Tab），可回头改，已选状态保留
        if len(self._questions) > 1:
            if key in ("left", "shift+tab"):
                if self._guard_switch(self._q_idx - 1):
                    self._goto_question(self._q_idx - 1)
                return True
            if key in ("right", "tab"):
                if self._guard_switch(self._q_idx + 1):
                    self._goto_question(self._q_idx + 1)
                return True
        if key in ("o", "O") or (char in ("o", "O")):
            # 跳到 Other 行并进入文本输入
            self._clear_warn()
            self._highlight = rows_count - 1
            self._other_input = True
            self._render()
            return True
        if key in ("return", "enter"):
            if self._warned_op == "submit":
                # 「还有 N 题未答」告警后的再次 enter=确认提交。不走 _on_enter:
                # 高亮可能停在 Other 行(Other 文本刚提交的场景),重走会误入文本输入态。
                self._clear_warn()
                self._submit()
                return True
            self._on_enter()
            return True
        return True  # 问答模式下吞掉其他按键，避免漏到下层

    def _is_other_highlighted(self) -> bool:
        return self._highlight == len(self._options())

    # ── 防呆守卫（516576：已选未提交切题/esc 静默丢答）────────────────

    def _has_uncommitted_selection(self) -> bool:
        """当前题「已选未提交」判据：动过高亮(数字/↑↓)但 _selected 仍空。

        数字/↑↓ 只动高亮，enter(单选)/space(多选) 才落答——用户动过高亮
        大概率以为已作答（run15/17 两次 3 题丢 2 的实弹形态），此时切走/取消
        值得拦一次提示。"""
        return self._touched[self._q_idx] and not self._selected[self._q_idx]

    def _unanswered_count(self) -> int:
        return sum(1 for sel in self._selected if not sel)

    def _warn_once(self, op: str, msg: str) -> bool:
        """同类操作首次→黄字告警拦下(返回 False)；紧接着再次同类操作→放行(返回 True)。

        只提示不锁死：armed 状态被任何其他按键（_clear_warn）重置。"""
        if self._warned_op == op:
            self._clear_warn()
            return True
        self._warned_op = op
        self._leave_warn = msg
        self._render()
        return False

    def _clear_warn(self) -> None:
        self._leave_warn = None
        self._warned_op = None

    def _guard_switch(self, target_idx: int) -> bool:
        """←→/Tab 切题守卫：带未提交选择时告警一次，再次切题放行。"""
        if not (0 <= target_idx < len(self._questions)):
            return True  # 越界本就是 no-op，不告警
        if not self._has_uncommitted_selection():
            return True
        return self._warn_once(
            "switch", "当前题已选未提交——enter 落答后再切(再次切题将不落答直接切换)",
        )

    def _guard_cancel(self) -> bool:
        """esc 分级守卫(F-TUI-5/7,A2 Design 2026-07-18 裁):**用"有无已答内容"分流**——
        - 当前题已选未提交:拦一次(既有,enter 落答);
        - **有已答内容**(≥1 题已落答):esc 首次二次确认「已答 N 题,确认放弃全部?」,
          再次 esc 才真 cancel——大面板误触全丢是真损失(用户答了半天);
        - **空面板**(无任何已答):esc 秒退(正常逃生口,防呆保留)。
        均告警一次再放行(§14-R4 不死挡)。与 (41)④ 提交保真门互补(一防误提交、一防误放弃)。"""
        if self._has_uncommitted_selection():
            return self._warn_once(
                "cancel", "当前题已选未提交——enter 落答;再次 esc 确认取消整个问答",
            )
        n_answered = sum(1 for sel in self._selected if sel)
        if n_answered > 0:
            return self._warn_once(
                "cancel",
                f"已答 {n_answered} 题,确认放弃全部?(再按 esc 确认 / 任意键返回)",
            )
        return True

    def _toggle_current(self) -> None:
        q = self._cur_question()
        if not q.get("multiSelect"):
            return
        self._touched[self._q_idx] = True
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
            self._clear_warn()
            self._other_input = True
            self._render()
            return
        if not q.get("multiSelect"):
            # 单选：enter 选中当前高亮项
            self._selected[self._q_idx] = {self._options()[self._highlight].get("label", "")}
        elif self._has_uncommitted_selection():
            # multiSelect 的 enter 也是一种「离开当前题」(2026-07-17 team4 审计 P1-6):
            # 动过高亮未 space 勾选就 enter=静默空答案推进——与切题/esc 同款守卫,
            # 告警一次,再次 enter 放行(按未选继续)。
            if not self._warn_once(
                    "advance", "当前题动过高亮但未 space 勾选——space 落答后 enter;"
                               "再次 enter 将按未选继续"):
                return
        self._advance_or_submit()

    def submit_other_text(self, text: str) -> None:
        """Other 自由文本输入完成后由 ist_app 调用。

        空文本防呆(2026-07-16 532862 实弹):高亮 Other→enter→提交空文本曾落成空答案,
        而空答案与 esc 取消的空答案在下游无法区分→引擎判「已取消」→案被自动挂起。空文本
        不构成有效裁决:留在输入态并提示,让用户补内容或显式 esc 取消,绝不落空 Other。"""
        stripped = text.strip()
        if not stripped:
            self._other_empty_hint = True
            self._render()   # 面板重渲显提示;仍在 _other_input 态,继续收文本
            return
        self._other_empty_hint = False
        self._other_text[self._q_idx] = stripped
        q = self._cur_question()
        if q.get("multiSelect"):
            self._selected[self._q_idx].add(_OTHER_VALUE)
        else:
            self._selected[self._q_idx] = {_OTHER_VALUE}
        self._other_input = False
        self._advance_or_submit()

    def cancel_other_input(self) -> None:
        self._other_empty_hint = False
        self._other_input = False
        self._render()

    def _advance_or_submit(self) -> None:
        if self._q_idx < len(self._questions) - 1:
            self._q_idx += 1
            self._highlight = 0
            self._clear_warn()
            self._render()
        else:
            # 整体提交防呆：存在未答题时告警一次（未答题下游按挂起处理，静默提交=
            # 516576 同型丢答）。再次 enter 在 handle_key 顶部直接放行提交。
            # 单题空提交同样告警(2026-07-17 team4 审计 P1-6):旧条件 len>1 使单题
            # multiSelect 空提交无任何告警直通——空答案下游与取消语义模糊。
            n = self._unanswered_count()
            if n and not self._warn_once(
                "submit",
                (f"还有 {n} 题未答,未答题将按挂起处理——再次 enter 确认提交"
                 if len(self._questions) > 1
                 else "本题未选任何项,提交将视为空答案(按挂起处理)——再次 enter 确认"),
            ):
                return
            self._submit()

    def _goto_question(self, idx: int) -> None:
        """A4：切到第 idx 题（双向，越界忽略）。已选状态按题保留。"""
        if 0 <= idx < len(self._questions):
            self._q_idx = idx
            self._highlight = 0
            self._clear_warn()
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
