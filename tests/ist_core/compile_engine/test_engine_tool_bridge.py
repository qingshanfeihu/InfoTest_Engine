"""薄工具桥接门:interrupt payload ↔ ask_user 面板 ↔ Command(resume)。"""
from __future__ import annotations

from main.ist_core.tools.device.engine_tool import _bridge_ask


def test_bridge_maps_headers_to_autoids(monkeypatch):
    import main.ist_core.tools.ask_user as AU
    seen = []

    def fake_ask(questions):
        seen.append(questions)
        return ('User has answered your questions: '
                '"欠定·900601"="改过程（加请求次数）". "欠定·900602"="改预期"')
    monkeypatch.setattr(AU.ask_user, "func", staticmethod(fake_ask))
    qs = [{"header": "欠定·900601", "question": "q1", "_autoid": "203099999999900601",
           "options": [], "multiSelect": False},
          {"header": "欠定·900602", "question": "q2", "_autoid": "203099999999900602",
           "options": [], "multiSelect": False}]
    ans = _bridge_ask(qs)
    assert ans["203099999999900601"].startswith("改过程")
    assert ans["203099999999900602"] == "改预期"
    # 内部键(_autoid)不外发给面板
    assert all(not any(k.startswith("_") for k in q) for q in seen[0])


def test_bridge_non_interactive(monkeypatch):
    import main.ist_core.tools.ask_user as AU
    monkeypatch.setattr(AU.ask_user, "func",
                        staticmethod(lambda q: "error: 当前为非交互模式,ask_user 不可用"))
    ans = _bridge_ask([{"header": "h", "question": "q", "_autoid": "a", "options": [],
                        "multiSelect": False}])
    assert ans == {"_non_interactive": True}
