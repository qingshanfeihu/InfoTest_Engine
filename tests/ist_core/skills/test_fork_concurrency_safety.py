"""P0-S1 并发安全验证：fork skill 多线程并发执行的隔离性。

批量并行编译的地基。draft/grade 子流程要被线程池并发 fan-out，前提是
``execute_fork_skill`` 并发调用同一个缓存的 subagent runnable 时各自隔离、
不串话。本测试用可控的 fake runnable（绕过真 LLM/网络）验证核心隔离契约：

1. LangGraph compiled graph 无状态——每次 invoke 传全新 state，同一 runnable
   对象被多线程并发 invoke，输出必须对应各自的 input，零交叉污染。
2. ``execute_fork_skill`` 全程局部变量 + 纯函数 ``_render_skill_body``，brief
   在并发下各自独立渲染。

不安全的兜底（若本测试失败）：execute_fork_skill 改 per-call 构造 runnable
或对 invoke 加锁退化串行。
"""

from __future__ import annotations

import concurrent.futures as cf
import threading
import time

from langchain_core.messages import AIMessage, HumanMessage

import main.ist_core.skills.loader as loader


class _FakeRunnable:
    """模拟 subagent runnable：从 input 的 HumanMessage 读 brief，原样回显。

    刻意制造交错：先记录 input、sleep 一会儿（让其它线程插进来）、再用
    *当初记录的* input 构造返回值。如果实现有共享可变状态串话，回显的 brief
    就会对应到别的线程的 input，测试即捕获。
    """

    def __init__(self) -> None:
        self.invoke_count = 0
        self.concurrent_peak = 0
        self._active = 0
        self._lock = threading.Lock()

    def invoke(self, state: dict, config=None) -> dict:
        with self._lock:
            self.invoke_count += 1
            self._active += 1
            self.concurrent_peak = max(self.concurrent_peak, self._active)
        try:
            # 读 *本次* input —— 局部变量，绝不存到 self
            human = state["messages"][0].content
            time.sleep(0.05)  # 制造线程交错窗口
            # 用本次 input 构造返回；串话会在这里暴露
            return {"messages": [HumanMessage(content=human),
                                 AIMessage(content=f"echo::{human}")]}
        finally:
            with self._lock:
                self._active -= 1


def _seed_fake_subagent(monkeypatch, fake: _FakeRunnable) -> None:
    """把 fake runnable 塞进缓存，并让 execute_fork_skill 找到一个 fork skill。

    通过 monkeypatch 让 get_subagent_runnable 返回 fake，避免真 create_agent /
    真 LLM。SKILL.md 解析走真实路径（验证真实的 fork skill 渲染链）。
    """
    monkeypatch.setattr(loader, "get_subagent_runnable", lambda name: fake)


def test_concurrent_fork_invocations_do_not_cross_talk(monkeypatch):
    """N 个不同 brief 并发派发同一 fork skill，每个返回值对应自己的 brief。"""
    fake = _FakeRunnable()
    _seed_fake_subagent(monkeypatch, fake)

    # 用真实存在的 fork skill（ist-compile-draft 是 context: fork）
    skill = "ist-compile-draft"
    briefs = [f"BRIEF-{i}-autoid-{1000 + i}" for i in range(12)]

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(loader.execute_fork_skill, skill, b): b
                   for b in briefs}
        results = {futures[f]: f.result(timeout=30) for f in futures}

    # 每个 brief 的返回必须回显它自己的内容（brief 被渲染进 body 再传入）
    for brief, out in results.items():
        assert brief in out, f"brief {brief!r} 串话/丢失，实际返回: {out[:200]}"
        # 不能回显到别的 brief
        for other in briefs:
            if other != brief:
                assert other not in out, (
                    f"brief {brief!r} 的返回里混入了 {other!r} —— 并发串话!")

    assert fake.invoke_count == len(briefs)
    # 确认确实发生了并发（峰值 > 1），否则测试没验到并发
    assert fake.concurrent_peak > 1, (
        f"并发峰值={fake.concurrent_peak}，未真正并发，测试无效")


def test_render_skill_body_is_pure():
    """_render_skill_body 是纯函数:同 body 不同 brief 互不影响。

    2026-07-05 起 brief 以 <brief_from_caller> 标签包裹(交互面 XML 分节:
    调用方数据与 skill 指令不混排),断言按标签契约。"""
    body = "do the thing with $ARGUMENTS now"
    out_a = loader._render_skill_body(body, "AAA")
    out_b = loader._render_skill_body(body, "BBB")
    assert out_a == "do the thing with <brief_from_caller>\nAAA\n</brief_from_caller> now"
    assert out_b == "do the thing with <brief_from_caller>\nBBB\n</brief_from_caller> now"
    # 原 body 未被污染
    assert "$ARGUMENTS" in body


def test_concurrent_render_isolation():
    """并发渲染同一 body、不同 brief，各自结果独立。"""
    body = "compile $ARGUMENTS"
    briefs = [f"case-{i}" for i in range(50)]

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        outs = list(ex.map(lambda b: loader._render_skill_body(body, b), briefs))

    for brief, out in zip(briefs, outs):
        assert out == f"compile <brief_from_caller>\n{brief}\n</brief_from_caller>"
        assert brief in out
