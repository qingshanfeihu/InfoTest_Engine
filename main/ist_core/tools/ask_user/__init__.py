"""ask_user: 问答/交互式辅助工具。

工具设计要点：
- 工具定位：当 agent 需要决策且答案改变后续行为时调用。**不要**用于"约定俗成的默认值"
  或"agent 自己能从代码里查到的事实"——这些情况直接选最合理选项推进。
- schema：questions[1-4 项]，每项 {question, header(≤12字), options[2-4 个], multiSelect}
- 每个 option：{label, description, preview(可选)}
- 用户始终可以选 "Other"（自由输入）
- 同步阻塞：agent 等用户选完才能继续
- 响应回喂：用 tool_result 文本格式 `User has answered your questions: "Q"="A"`

实现思路：
- 工具在后台 worker 线程跑（bridge.py 起的 threading.Thread）
- 用 threading.Event 跨线程阻塞等 TUI 回调
- TUI 渲染选项，用户响应后调 set_answers 唤醒工具
- 全程不动 graph 拓扑、不需要 LangGraph interrupt + Command(resume) 续跑

Plan-mode note：在 plan mode 下，本工具用于"在 ExitPlanMode 之前"澄清需求或选择方案；
不要用本工具问"plan 是否 OK"——那是 ExitPlanMode 自己做的事。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)



_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_LOCK = threading.Lock()


def get_pending_question(question_id: str) -> dict[str, Any] | None:
    """TUI 端用：根据 question_id 拿 pending question 详情（含 options / event）"""
    with _PENDING_LOCK:
        return _PENDING.get(question_id)


def list_pending_questions() -> list[dict[str, Any]]:
    """TUI 端用：列出所有 pending question 的元数据"""
    with _PENDING_LOCK:
        return [{"question_id": qid, **{k: v for k, v in q.items() if k != "_event"}}
                for qid, q in _PENDING.items()]


def cancel_all_pending(reason: str = "") -> int:
    """teardown 终结器(MiMo-Code question/index.ts 移植):TUI 退出/会话终结时把所有
    挂起问询以「无答案」唤醒——阻塞在 event.wait() 的引擎/工具线程立即收到取消并
    走自己的无答案路径(引擎侧=自动挂起带反馈),永不悬死。返回取消条数。"""
    with _PENDING_LOCK:
        items = list(_PENDING.values())
    n = 0
    for pending in items:
        evt = pending.get("_event")
        if pending.get("answers") is None and evt is not None and not evt.is_set():
            evt.set()
            n += 1
    if n:
        logger.info("ask_user teardown:取消 %d 个挂起问询%s", n,
                    f"({reason})" if reason else "")
    return n


def submit_answers(question_id: str, answers: dict[str, str]) -> bool:
    """TUI 端用：用户选完后回写答案，唤醒等待的工具调用。

    Args:
        question_id: 工具发起时分配的 ID
        answers: {question_text: answer_text}

    Returns:
        True 如果该 question_id 存在且首次提交答案，False 否则
    """
    with _PENDING_LOCK:
        pending = _PENDING.get(question_id)
        if pending is None or pending.get("answers") is not None:
            return False
        pending["answers"] = answers
        evt = pending.get("_event")
    if evt is not None:
        evt.set()
    # 生命周期回边:问询发起走 ask_user_request(reducer append 一条 BLOCK_ASK_USER 块),
    # 答复只 set threading.Event 唤醒工具线程、不回 reducer——那条块永无「已答」标记,全量
    # 重放(_replay_snapshot)会重新 _begin_ask_user 把答完的面板复活(答后残留根因)。补这条
    # ask_user_answered:reducer 据 question_id 把块标 answered,重放渲折叠态、不复活。
    try:
        from main.ist_core.events import get_default_bus
        get_default_bus().emit(
            "ask_user_answered",
            payload={"question_id": question_id, "answers": dict(answers or {})},
            tags={"name": "ask_user"},
        )
    except Exception:  # noqa: BLE001
        pass
    return True


@tool
def ask_user(questions: list[dict[str, Any]]) -> str:
    """Ask the user multiple choice questions to gather information, clarify ambiguity, understand preferences, or offer them choices.

    Use this tool when you need user input during execution, especially:
    1. To gather user preferences or requirements
    2. To clarify ambiguous instructions
    3. To get decisions on implementation choices
    4. To offer choices about direction (e.g. "Is this P0 a real bug or intentional?")

    Reserve this for decisions where the user's answer changes what you do next — not
    for choices with a conventional default or facts you can verify in the codebase
    yourself. In those cases pick the obvious option, mention it in your response,
    and proceed.

    Usage notes:
    - Users will always be able to select "Other" to provide custom text input
    - Use `multiSelect: true` to allow multiple answers to be selected for a question
    - If you recommend a specific option, make it the first option and add
      "(Recommended)" to its label

    `questions` is a list of 1-4 question dicts. Each question is a dict with:
      - `question` (str, required): the full question text, ending with `?`
      - `header` (str, required): a short label (≤ 12 chars) shown as a chip
      - `options` (list, required): 2-4 mutually exclusive options. Each option is
        `{label, description, preview?}`
      - `multiSelect` (bool, default false): allow multiple answers

    Returns plain-text summary `User has answered your questions: "Q1"="A1". "Q2"="A2"`.
    """
    if not questions or not isinstance(questions, list):
        return "error: 'questions' must be a non-empty list"

    
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            return f"error: question[{i}] must be a dict"
        if not q.get("question"):
            return f"error: question[{i}] missing 'question' field"
        opts = q.get("options")
        if not isinstance(opts, list) or not (2 <= len(opts) <= 4):
            return f"error: question[{i}] 'options' must be 2-4 items"


    import uuid
    question_id = uuid.uuid4().hex[:8]
    event = threading.Event()
    pending = {
        "question_id": question_id,
        "questions": questions,
        "answers": None,
        "_event": event,
    }
    with _PENDING_LOCK:
        _PENDING[question_id] = pending


    try:
        from main.ist_core.events import get_default_bus
        bus = get_default_bus()
        bus.emit(
            "ask_user_request",
            payload={
                "question_id": question_id,
                "questions": questions,
            },
            tags={"name": "ask_user"},
        )
    except Exception:  # noqa: BLE001
        pass

    # 非交互模式（仅测试用的 print 模式 `-p`，无 TUI 可应答）：绝不阻塞、绝不猜答案。
    # 生产接口只有 TUI；在非交互下命中 ask_user 一定是「测试输入缺信息」或「设计/bug」。
    # 立即返回明确错误把问题暴露出来——而不是 event.wait() 死等一个永不到来的应答。
    import os as _os
    if (_os.environ.get("IST_NON_INTERACTIVE") or "").strip() in ("1", "true", "True"):
        with _PENDING_LOCK:
            _PENDING.pop(question_id, None)
        _q_summary = " | ".join(str(q.get("question", "")) for q in questions)
        return (
            "error: 当前为非交互模式（无 TUI，无法向用户提问），ask_user 不可用。"
            "请改为：从用户请求原文中提取该信息；若请求确实未提供该必要信息，"
            "请停止并明确报告『缺少哪项信息、为何无法在不询问用户的情况下继续』，"
            "不要臆测或自行选默认值。"
            f" 你本想问的是：{_q_summary}"
        )

    # 诊断：把 agent 实际想问的问题打到 stderr，便于排查"为什么 ask_user"。
    try:
        import sys as _sys
        _qs = "; ".join(
            str(q.get("question", "")) + " ["
            + "/".join(str(o.get("label", "")) for o in (q.get("options") or []))
            + "]"
            for q in questions
        )
        print(f"[ask_user] agent 提问: {_qs}", file=_sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass


    event.wait()

    
    with _PENDING_LOCK:
        answers = pending.get("answers") or {}
        _PENDING.pop(question_id, None)

    if not answers:
        return "User cancelled the question (no answer)."

    # 机读问答台账(2026-07-05):每次真实问答落 runtime/ask_user_answers.jsonl——
    # compile_user_decision 的「先问后落」门靠它校验用户真的批过(orchestrator 曾
    # 在 ask_user 之前替用户拍板 8 个欠定 case,含放弃顺序语义;prompt 红线拦不住,
    # 落盘凭证才是 A 层)。追加失败不影响问答本身。
    try:
        import json as _json
        import time as _time
        from pathlib import Path as _Path
        _log = _Path(__file__).resolve().parents[4] / "runtime" / "ask_user_answers.jsonl"
        _log.parent.mkdir(parents=True, exist_ok=True)
        _rec = {"ts": _time.time(),
                "questions": [str(q.get("question", ""))[:500] for q in questions],
                "answers": {str(k)[:500]: (", ".join(map(str, v)) if isinstance(v, list) else str(v))[:500]
                            for k, v in answers.items()}}
        with _log.open("a", encoding="utf-8") as _f:
            _f.write(_json.dumps(_rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        logger.debug("ask_user 台账落盘失败(不影响问答)", exc_info=True)

    
    # 回传键 = header(短键,优先)/题干截短——旧版回显题干全文,多题时 transcript
    # 单行渲染必截断、后续题目被挤掉(2026-07-03 实证);agent 刚问过全部题目,短键
    # 足以映射,答案本身完整保留。
    header_by_q = {str(q.get("question", "")): str(q.get("header", "") or "")
                   for q in questions}
    parts = []
    for q_text, a in answers.items():
        if isinstance(a, list):
            a = ", ".join(str(x) for x in a)
        h = header_by_q.get(str(q_text), "")
        key = h if h else (str(q_text)[:40] + ("…" if len(str(q_text)) > 40 else ""))
        parts.append(f'"{key}"="{a}"')
    return "User has answered your questions: " + ". ".join(parts)
