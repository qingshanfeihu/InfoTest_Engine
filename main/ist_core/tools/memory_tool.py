"""qa_remember: agent 主动把"踩过的坑/验证过的洞察"记进长期记忆(MUSE .memory.md 的精神)。

为什么要它:agent 调查一个 case 时踩的坑(如"xlsx 的 G 列不是 Python 变量""sdns persistence
的 query_type 写法""APV 经跳转机访问"),下次跑同类 case 不该再踩。给 agent 一个工具,
让它**自己判断**哪条教训值得记、自己记下来——而不是系统替它记。

写入 long_term/project/<topic>.md(复用 IST-Core memory 子系统;MemoryInjection 中间件
下轮会把相关记忆自动注入,所以下次同类 case agent 起手就能看到)。与外层 dream 离线蒸馏
互补(两者都要:agent 主动记关键洞察 + 外层兜底防漏)。
"""

from __future__ import annotations

import logging
import re

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9一-鿿]+", "-", (text or "").lower()).strip("-")
    return (s or "lesson")[:40]


@tool(parse_docstring=True)
def qa_remember(lesson: str, topic: str = "") -> str:
    """把一条**验证过的教训/踩过的坑**记进长期记忆,下次同类任务自动看到,不再重踩。

    什么时候用:你在调查/上机过程中**确认**了一条非显而易见、且未来还会用到的事实——
    典型如:某个框架 DSL 语义("check_point 的 G 是字面文本不是变量")、某个命令的正确
    写法/坑("sdns host persistence 的参数顺序是…")、某个环境约束("APV 只能经跳转机")、
    某类断言的正确形态。**必须是你已验证为真的**(上机看到、手册查到),不是猜测。

    什么时候不用:还没验证的猜想;只对当前这一个 case 有效的临时细节;显而易见的常识。

    Args:
        lesson: 教训正文。写清"事实是什么 + 为什么(踩坑则写坑) + 怎么用"。一两句,具体。
        topic: 主题归类(如 "xlsx-dsl"/"sdns-persistence"/"device-topology"),便于检索;
            留空则自动从 lesson 取关键词。

    Returns:
        确认写入的提示(或失败说明)。
    """
    lesson = (lesson or "").strip()
    if not lesson:
        return "error: lesson 不能为空"
    topic = _slug(topic or lesson[:30])

    try:
        from main.ist_core.memory.backend import build_memory_backend, get_default_root
        from main.ist_core.memory.store import MemoryStore
        store = MemoryStore(build_memory_backend(), get_default_root())
        # 写 long_term/feedback/<topic>.md(踩坑/工作教训属 feedback 类;store 写白名单允许
        # feedback/，不允许 project/)。MemoryInjection 中间件下轮按关键词注入。
        rel = f"long_term/feedback/{topic}.md"
        store.upsert_long_term(rel, lesson, mode="append", keywords=topic.replace("-", " "))
    except Exception as exc:  # noqa: BLE001
        logger.warning("qa_remember 写入失败: %s", exc)
        return f"error: 记忆写入失败: {exc}"

    return (f"已记入长期记忆 long_term/feedback/{topic}.md:\n{lesson[:120]}\n"
            f"(下次同类任务会自动注入,不必重新踩这个坑)")
