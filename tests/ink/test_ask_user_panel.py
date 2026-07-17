"""AskUserPanel 单元测试 — 隐藏/显示 + 长选项行软换行(不再被单行行盒截断)。

2026-07-02 实测:决策面板的长选项(label+description 超终端宽)被 height=1 行盒
截成半句(「用 show stat」)。修复=TextNode 直挂面板 + auto 高度,布局引擎按
软换行真实行数估高、渲染层原生折行。本测试锁定该行为。
"""

from __future__ import annotations

from main.ist_core.ink.components.ask_user_panel import AskUserPanel
from main.ist_core.ink.dom import NodeType, create_element
from main.ist_core.ink.layout.engine import compute_layout


def test_initial_hidden() -> None:
    panel = AskUserPanel()
    assert panel.node.style.height == 0
    assert panel.is_visible is False


def test_clear_hides() -> None:
    panel = AskUserPanel()
    panel.update(["line"])
    assert panel.is_visible is True
    panel.clear()
    assert panel.node.style.height == 0
    assert panel.is_visible is False


def test_long_option_line_wraps_instead_of_truncating() -> None:
    panel = AskUserPanel()
    long_line = " 1. 改过程 (Recommended) — " + "请求数加到覆盖完整一轮并用统计命令验证分布," * 6
    short_line = " 2. 改预期"
    panel.update([long_line, short_line])

    # auto 高度:不再是 len(lines)+1 的固定值
    assert panel.node.style.height is None

    # 窄终端下布局:长行应折成多行,面板总高 > 行数+1(顶部空行)
    root = create_element(NodeType.BOX)
    root.style.flex_direction = "column"
    root.append_child(panel.node)
    width = 60
    compute_layout(root, width, 40)
    assert panel.node.rect.height > 3  # 1 空行 + 长行折出的多行 + 短行

    # 行内容原样保留(未被 [:N] 截断)
    values = [getattr(c, "value", "") for c in panel.node.children]
    assert long_line in values and short_line in values


def test_tab_bearing_sides_quote_renders_complete_and_tab_free() -> None:
    """P1-9 端到端(2026-07-17 team4 实弹 035413):ask_panel.json 的 sides 引文携带
    dig 回显原样 TAB(www.a.com.\\t\\t60\\tIN\\tCNAME\\t…)——verbatim 契约使其直通题干。
    渲染核 char_width('\\t')=1 与终端 8 列制表位背离,造成两个症状:跳过区残留=粘连
    碎片(「www.local.co0.md」),列偏移+终端硬折行被下行覆盖=中段丢显(手册文件名
    整段不可见,用户裁决时看不到完整证据)。dom 层 TextNode 值规格化后两症状同根同修:
    面板节点值必须零 TAB 且引文关键子串全部可见。"""
    from main.ist_core.compile_engine_v8.questions import build_ask_question
    from main.ist_core.ink.components.ask_user_view import AskUserSession

    # 035413 真实 panel 形态(sides 引文含 5 个真实 TAB)
    case = {"autoid": "204651759025035413", "kind": "panel",
            "title": "本地域名命中回退池情况",
            "panel": {
                "conflict_shape": "manual_vs_device",
                "sides": [
                    {"source_ref": "device_context",
                     "quote": "www.a.com.\t\t60\tIN\tCNAME\twww.local.com."},
                    {"source_ref": "knowledge/data/markdown/product/manual_10.5/cli_10.5_Chapter20.md",
                     "quote": "当指定的SDNS服务池中没有可用的SDNS服务时，系统将采用SDNS回退池。"},
                ],
                "hypothesis": "主池 disable 时 A 查询只返回 CNAME 未解析到回退池 IP。",
                "ask": "应返回回退池的 IP，还是只返回 CNAME？"}}
    q = build_ask_question(case)
    # 双侧防御第一侧(2026-07-17 补做批,questions._display_clean):题干在拼装期已
    # 剥 TAB——前提自检从「TAB 直通(单侧时代现状)」翻转为「零 TAB 直达」。渲染侧
    # dom 规格化(第二侧)独立成立:下方 panel.update 断言不依赖输入携 TAB,任何未来
    # 漏标源(不经 questions 拼装的文本)仍由 dom 层兜底。verbatim 契约边界不变:
    # 剥离只在题面展示投影,落盘 ask_panel.json 与 LLM 载荷仍逐字。
    assert "\t" not in q["question"], "拼装侧 _display_clean 应已剥题干 TAB(双侧防御第一侧)"

    session = AskUserSession("qid", [q], render=lambda: None, on_finish=lambda: None)
    panel = AskUserPanel()
    panel.update(session.render_lines())

    texts = [ch.value for ch in panel.node.children if hasattr(ch, "value")]
    joined = "\n".join(texts)
    assert "\t" not in joined, "TextNode 值必须零 TAB(dom 层规格化,否则终端跳列叠影/丢显)"
    # 引文两侧关键子串全部可见(丢显面:实机回显尾 + 手册文件名此前整段不可见)
    for frag in ("www.a.com.", "60", "IN", "CNAME", "www.local.com.",
                 "cli_10.5_Chapter20.md", "SDNS回退池"):
        assert frag in joined, f"证据子串「{frag}」必须完整可见(用户凭它裁决)"
