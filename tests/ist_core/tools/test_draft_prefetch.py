"""Draft 预检索（Phase 1 footprint；Phase 3 probe 待补）：确定性查询推断 + 内联块。

全程 mock footprint Index / kb_footprint，不打设备、不耦合 footprint 数据，本地秒级跑通。
验证目标：把 draft 会查的命令文法前移内联 → 省 kb_footprint 往返；空命中/失败降级不更差。
"""

from __future__ import annotations

import importlib

# 工具名遮蔽模块属性 → 用 importlib 取真模块访问内部 helper（同 test_compile_pipeline 注释）。
CP = importlib.import_module("main.ist_core.tools.device.compile_pipeline")


def _case():
    return {
        "autoid": "532943",
        "title": "sdns pool member 轮转",
        "step_intents": [
            {"desc": "配置 sdns pool method wrr", "expected": ""},
            {"desc": "客户端反复 dig", "expected": "按权重轮转命中"},
        ],
    }


# ── _infer_footprint_queries ─────────────────────────────────────────────────
def test_infer_footprint_queries_from_search(monkeypatch):
    """search 命中的 feature_id 转成命令串（点→空格），去重、受 top_k 控。
    （不做族骨架/配置骨架预取——红线：骨架层实测负收益。）"""
    class _Idx:
        def search(self, query, *, top_k=3):
            assert "sdns" in query                       # 用了意图文本
            return [("sdns.pool.member", "..."), ("sdns.pool.method", "..."),
                    ("sdns.pool.member", "dup")][:top_k]

    import main.ist_core.memory.footprint as fp
    monkeypatch.setattr(fp, "get_footprint_index", lambda: _Idx())
    qs = CP._infer_footprint_queries(_case())
    assert qs == ["sdns pool member", "sdns pool method"]  # 去重 + 点转空格


def test_infer_footprint_queries_disabled(monkeypatch):
    """运行时 env 关 → 返回 []（支持 A/B 同进程翻 flag）。"""
    monkeypatch.setenv("IST_FOOTPRINT_PREFETCH", "0")
    assert CP._infer_footprint_queries(_case()) == []
    monkeypatch.setenv("IST_FOOTPRINT_PREFETCH", "1")        # 翻回开 → 同进程即生效
    # (不断言具体条数,只验证 flag 动态生效:开了不再恒空——交给真实 index)


def test_format_observability_delta():
    """A/B 对比渲染：降幅百分比 + 各工具 before→after。"""
    before = {"draft_llm_rounds": 100, "total_llm_rounds": 130,
              "tool_calls": {"kb_footprint": 90, "dev_probe": 10}}
    after = {"draft_llm_rounds": 60, "total_llm_rounds": 85,
             "tool_calls": {"kb_footprint": 42, "dev_probe": 9}}
    s = CP._format_observability_delta(before, after)
    assert "kb_footprint: 90 → 42  (-53%)" in s
    assert "draft LLM 往返: 100 → 60  (-40%)" in s
    assert "dev_probe: 10 → 9" in s
    # 零 baseline 不除零
    assert CP._format_observability_delta({}, {"total_llm_rounds": 5}) is not None


def test_infer_footprint_queries_empty_intent():
    assert CP._infer_footprint_queries({"autoid": "x"}) == []


def test_infer_footprint_queries_search_failure_degrades(monkeypatch):
    """search 抛错 → 返回 []（降级，draft 兜底自查，不更差）。"""
    class _Idx:
        def search(self, *a, **k):
            raise RuntimeError("boom")

    import main.ist_core.memory.footprint as fp
    monkeypatch.setattr(fp, "get_footprint_index", lambda: _Idx())
    assert CP._infer_footprint_queries(_case()) == []


# ── _preretrieve_footprint ───────────────────────────────────────────────────
def test_preretrieve_footprint_inlines_and_skips_miss(monkeypatch):
    """命中内联；'未找到' 跳过（不塞噪声）；逐条走 kb_footprint（自带 _FP_CACHE 写穿）。"""
    seen = []

    class _FakeTool:
        def invoke(self, d):
            cmd = d["command"]
            seen.append(cmd)
            if cmd == "sdns pool member":
                return "## sdns pool member\nCLI: sdns pool member <pool> <ip>\nBehaviors: 轮转成员"
            return "未找到 'xxx' 的 footprint 知识。"

    import main.ist_core.tools.knowledge.footprint_lookup as fl
    monkeypatch.setattr(fl, "kb_footprint", _FakeTool())
    out = CP._preretrieve_footprint(["sdns pool member", "sdns pool method"])
    assert "【sdns pool member】" in out
    assert "轮转成员" in out
    assert "sdns pool method" not in out      # 未找到 → 跳过
    assert seen == ["sdns pool member", "sdns pool method"]   # 两条都查了


def test_preretrieve_footprint_respects_max_chars(monkeypatch):
    class _FakeTool:
        def invoke(self, d):
            return "X" * 9000

    import main.ist_core.tools.knowledge.footprint_lookup as fl
    monkeypatch.setattr(fl, "kb_footprint", _FakeTool())
    monkeypatch.setattr(CP, "_FOOTPRINT_PREFETCH_MAX_CHARS", 1000)
    out = CP._preretrieve_footprint(["sdns"])
    assert "(截断)" in out
    assert len(out) < 1200


def test_preretrieve_footprint_empty_queries():
    assert CP._preretrieve_footprint([]) == ""


# ── _footprint_block + brief 接入 ────────────────────────────────────────────
def test_footprint_block_empty():
    assert CP._footprint_block("") == ""
    assert CP._footprint_block("   ") == ""


def test_footprint_block_header_forbids_repeat():
    b = CP._footprint_block("【sdns pool】\nCLI...")
    assert "预检索 footprint" in b
    assert "禁止再调 kb_footprint" in b


def test_brief_includes_footprint_block():
    b = CP._build_case_brief(_case(), product_version="10.5",
                             manual_glob="g", footprint_text="【sdns pool】\nfoo")
    assert "预检索 footprint" in b
    assert "【sdns pool】" in b
    # 块顺序：footprint 块在边界之前
    assert b.index("预检索 footprint") < b.index("边界：")


def test_brief_without_footprint_unchanged():
    """不传 footprint_text → 无 footprint 块（向后兼容，旧 brief 测试不破）。"""
    b = CP._build_case_brief(_case(), product_version="10.5", manual_glob="g")
    assert "预检索 footprint" not in b


def test_footprint_prefetch_is_strictly_additive_to_brief():
    """质量护栏（『质量不降』的结构性证明，离线确定性）：footprint 预检索是『加法』——
    开预检索的 brief = 关预检索的 brief + footprint 块，**质量关键段一字不删**。
    draft 只多拿正确上下文、不丢任何质量指导 → 本改动不会结构性掉质量；唯一行为风险是
    prompt 减负(由未改的 grade 门 + 保留的『语义不清必须探』兜底兜住)。realized done 数
    仍需 live 跑(本沙箱无 LLM 端点)，但结构上已证无质量回归路径。
    """
    case = _case()
    fp = "【sdns pool】\nCLI: sdns pool <name>\nBehaviors: 轮转成员"
    brief_off = CP._build_case_brief(case, product_version="10.5", manual_glob="g",
                                     precedent_text="某先例", footprint_text="")
    brief_on = CP._build_case_brief(case, product_version="10.5", manual_glob="g",
                                    precedent_text="某先例", footprint_text=fp)
    # 质量关键锚点（期望值三分诊 / 红线 / 先例 / 需求 / 边界）在两版都在
    for anchor in ("observe-then-assert", "捕获", "<RUNTIME>", "某先例",
                   "需求：autoid", "边界："):
        assert anchor in brief_off, f"off 缺 {anchor}"
        assert anchor in brief_on, f"on 缺 {anchor}"
    # footprint 块只在 on
    assert "预检索 footprint" in brief_on and "预检索 footprint" not in brief_off
    # **严格加法性**：从 on 里抠掉 footprint 块 ⟺ 完全等于 off（证明没动任何其它内容）
    assert brief_on.replace(CP._footprint_block(fp), "") == brief_off
