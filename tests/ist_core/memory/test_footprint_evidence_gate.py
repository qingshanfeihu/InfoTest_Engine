"""evidence 门 normalize：硬换行/软换行 quote 对齐手册连续句，但不放过编造。

手册中文正文按列宽硬换行(`类型的DNS\n解析`)，`" ".join(split())` 把 `\n` 归一成空格
(`DNS 解析`)，而 LLM 引的是连续句(`DNS解析`)→ 长 quote 跨换行点被切两段、均 <60% 覆盖率
→ rule/behavior 被证据门假阴性丢弃(实测 sdns.pool.cname 主描述 behavior 含双路文字被拒)。
修复：normalize 删除 CJK 相邻空白(中文换行非词边界)，英文词间空格(show version)保留。
"""
from __future__ import annotations

from main.ist_core.memory.footprint.merger import _evidence_supports, _normalize
from main.ist_core.memory.footprint.schema import RawFact


def _behavior(quote: str, evidence_file: str) -> RawFact:
    return RawFact(
        fact_kind="behavior", feature_path=["sdns", "pool", "cname"],
        fact_key="k", content="x",
        evidence_file=evidence_file, evidence_quote=quote,
    )


def test_hard_wrapped_chinese_quote_passes(tmp_path):
    """手册中文正文硬换行(DNS\\n解析)，LLM 引连续句应放行(核心修复)。"""
    manual = tmp_path / "ch.md"
    manual.write_text(
        "该命令用于定义一个SDNS别名（Canonical\n"
        "Name，CNAME）池。SDNS别名池仅包含一个别名。当系统收到CNAME类型的DNS\n"
        "解析请求并且该别名池被命中时，系统将该别名返回给本地DNS服务器。",
        encoding="utf-8",
    )
    quote = ("该命令用于定义一个SDNS别名（Canonical Name，CNAME）池。"
             "SDNS别名池仅包含一个别名。当系统收到CNAME类型的DNS解析请求")
    assert _evidence_supports(_behavior(quote, str(manual)))


def test_fabricated_quote_rejected(tmp_path):
    """编造的 quote(手册里没有)仍被拒，防伪未破。"""
    manual = tmp_path / "ch.md"
    manual.write_text("该命令用于显示全部SDNS别名池。", encoding="utf-8")
    fake = "该命令支持配置一个虚构参数并自动同步到云端控制台审计日志系统"
    assert not _evidence_supports(_behavior(fake, str(manual)))


def test_normalize_drops_cjk_newline_space():
    """归一化：CJK 相邻换行空白删除(中文换行非词边界)。"""
    assert _normalize("类型的DNS\n解析请求") == "类型的DNS解析请求"


def test_normalize_keeps_english_word_spacing():
    """英文词间空格(show version)不能被粘成 showversion。"""
    assert _normalize("show\nversion detail") == "show version detail"
    assert _normalize("（Canonical\nName，CNAME）") == "（Canonical Name，CNAME）"
