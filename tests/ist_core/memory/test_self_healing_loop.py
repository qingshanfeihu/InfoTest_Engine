"""自愈环演练(P1 核心验收,2026-07-08)。

用户判据:后续出现类似问题时,若仍要人追加代码,就不是自愈合系统。
本测试用真实历史坑(pe1 608 R1:CNAME 域名状态门控观察卡在知识断层外)做
"新坑模拟",断言整条响应路径——

    fail 轮 behavior 候选 → closing uncertain 入库 → kb_footprint 渲染出
    带 uncertain|语境 的观察 → 第二语境到达自动成观察组 → PASS 实证升级

——全程 main/ 下 .py 文件零变化:自愈 = 数据演化,不是代码追加。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.memory.footprint.merger import merge_fact, _append_behavior
from main.ist_core.memory.footprint.router import route_facts
from main.ist_core.memory.footprint.schema import RawFact
from main.ist_core.tools.knowledge.footprint_lookup import _format_node

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _py_snapshot() -> dict[str, tuple[int, int]]:
    """main/ 下全部 .py 的 (size, mtime_ns) 快照——零代码变化的机器断言。"""
    return {
        str(p): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in (PROJECT_ROOT / "main").rglob("*.py")
    }


class _StubLedger:
    """closing._ingest_uncertain_observations 的适配器替身(A2′ 观察级判据轴):
    observation_cases 给 (aid, 语境标签),extra_candidates 给 attributor 观察兜底。"""

    def __init__(self, failed: list[str], escalated: list[str] | None = None,
                 cases: list[tuple[str, str]] | None = None,
                 extra: dict[str, list[dict]] | None = None):
        self._cases = cases if cases is not None else (
            [(a, "fail/escalated 轮观察") for a in failed]
            + [(a, "升级轮观察") for a in (escalated or [])])
        self._extra = extra or {}
        self.data = {"audit": {"notes": []}}

    def observation_cases(self):
        return list(self._cases)

    def extra_candidates(self, aid: str):
        return list(self._extra.get(aid) or [])


@pytest.fixture()
def drill_env(tmp_path, monkeypatch):
    """隔离演练场:outputs 根 + footprint 根都指向 tmp,不碰真实知识库。"""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    fp_root = tmp_path / "footprints"
    fp_root.mkdir()
    import main.knowledge_paths as kp
    from main.ist_core.compile_engine_v8 import _shared as sh

    monkeypatch.setattr(kp, "KNOWLEDGE_FOOTPRINTS", fp_root)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.setattr(sh, "emit", lambda text: None)
    monkeypatch.delenv("FOOTPRINT_UNCERTAIN_WRITEBACK", raising=False)
    return outputs, fp_root


# pe1 608 R1 真实观察形态(fail 轮最有信息量的 episode,此前被整体丢弃)
_AID = "204651759025035608"
_CAND = {
    "observe_cmd": "show sdns host status",
    "content": "成员未注册为本地域名时 GA 视其恒可用,disable pool member 不影响 CNAME 返回",
    "note": "成员域名未配 sdns host name(非本地域名),仅 pool member 挂接",
}


def _ingest(outputs: Path, aid: str, cands: list[dict], led=None):
    (outputs / aid).mkdir(exist_ok=True)
    (outputs / aid / "behavior_candidates.json").write_text(
        json.dumps(cands, ensure_ascii=False), encoding="utf-8")
    from main.ist_core.compile_engine_v8.uncertain import _ingest_uncertain_observations
    _ingest_uncertain_observations(led or _StubLedger([aid]))


def _load_nodes(fp_root: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in fp_root.rglob("*.json")]


def test_self_healing_drill_zero_code_change(drill_env):
    """主演练:新坑观察走完 入库→渲染→观察组,响应路径纯数据、零 .py 变化。"""
    outputs, fp_root = drill_env
    before = _py_snapshot()

    # ① fail 轮候选入库(uncertain 级)
    _ingest(outputs, _AID, [_CAND])
    nodes = _load_nodes(fp_root)
    assert nodes, "fail 观察应落 footprint 节点(此前被整体丢弃)"
    behaviors = [b for n in nodes for b in n.get("behaviors", [])]
    assert len(behaviors) == 1
    obs = behaviors[0]
    assert obs["validity"] == "uncertain", "fail 观察不得冒充 verified"
    assert obs["observed_under"] == _CAND["note"], "语境短句必须随观察入库"
    assert _AID in json.dumps(nodes, ensure_ascii=False), "autoid 锚必须可追溯"

    # ②a uncertain 入库不累计 verified_count(节点头 `verified Nx` 是权威度信号,
    #    未实证观察计入=冒充——红线评审中危项)
    node = next(n for n in nodes if n.get("behaviors"))
    assert node["footprint_meta"]["verified_count"] == 0

    # ②b 拉式渲染(kb_footprint):单条观察带 uncertain|context 前缀
    text = _format_node(node)
    assert "uncertain" in text and "context:" in text

    # ②c 推式渲染(reminder 注入通道)同样必须带标——漏标即冒充 verified
    from main.ist_core.memory.footprint.index import _format_footprint
    push_text = _format_footprint(node)
    assert "[uncertain" in push_text
    assert "verified 0x" in push_text

    # ③ 第二语境观察到达 → 自动观察组(纯计数触发,零语义判定)
    cand2 = {
        "observe_cmd": "show sdns host status",
        "content": "成员注册为本地域名且健康检查 DOWN 时,GA 跳过该成员,CNAME 不返回",
        "note": "成员配 sdns host name 为本地域名+健康检查指向不可达 IP",
    }
    _ingest(outputs, _AID, [cand2])
    node = next(n for n in _load_nodes(fp_root) if len(n.get("behaviors", [])) == 2)
    text = _format_node(node)
    assert "multi-context observation" in text, "互异语境 ≥2 应自动出组头"
    assert "device experiment can arbitrate" in text
    # 观察组免配额:两条语境都必须完整可见(截断会隐藏语境分支)
    assert cand2["note"] in text and _CAND["note"] in text

    # ④ 判据本体:全程零 .py 变化——自愈是数据演化,不是代码追加
    assert _py_snapshot() == before, "响应新坑不得改任何 .py"


def test_uncertain_upgrade_on_pass_no_downgrade():
    """演化端:同 fact_key 后续 PASS 实证 → 就地升级 verified;反向不降级。"""
    fp = {"behaviors": [{
        "fact_key": "sdns.host.status:abc123",
        "content": "旧观察",
        "evidence": {},
        "validity": "uncertain",
        "observed_under": "旧语境",
    }]}
    verified = RawFact(fact_kind="behavior", feature_path=["sdns"],
                       fact_key="sdns.host.status:abc123",
                       content="实证后的结论", observed_under="钉死的分辨条件")
    assert _append_behavior(fp, verified) == "update"
    entry = fp["behaviors"][0]
    assert entry["validity"] == "verified"
    assert entry["content"] == "实证后的结论"
    assert entry["observed_under"] == "钉死的分辨条件"

    # 反向:verified 已在,uncertain 又来 → skip,不降级不覆盖
    again = RawFact(fact_kind="behavior", feature_path=["sdns"],
                    fact_key="sdns.host.status:abc123",
                    content="另一次 fail 观察", validity="uncertain")
    assert _append_behavior(fp, again) == "skip"
    assert fp["behaviors"][0]["validity"] == "verified"
    assert fp["behaviors"][0]["content"] == "实证后的结论"


def test_uncertain_gate_requires_anchor(tmp_path):
    """merger 门:uncertain 放行需 autoid 锚+观测命令,缺一即拒(不是无门直通)。"""
    def _merge(fact):
        routed = route_facts([fact], tmp_path)
        assert routed
        return merge_fact(routed[0], tmp_path)

    ok = RawFact(fact_kind="behavior", feature_path=["sdns", "host"],
                 fact_key="k1", cli_syntax="show sdns host status", content="观察",
                 device_evidence={"autoid": _AID}, validity="uncertain")
    assert _merge(ok).action == "create"

    no_anchor = RawFact(fact_kind="behavior", feature_path=["sdns", "host"],
                        fact_key="k2", cli_syntax="show sdns host status", content="观察",
                        device_evidence={"autoid": ""}, validity="uncertain")
    assert _merge(no_anchor).action == "skip"


def test_env_kill_switch(drill_env, monkeypatch):
    """FOOTPRINT_UNCERTAIN_WRITEBACK=0 → 不入库(逃生口)。"""
    outputs, fp_root = drill_env
    monkeypatch.setenv("FOOTPRINT_UNCERTAIN_WRITEBACK", "0")
    _ingest(outputs, _AID, [_CAND])
    assert not _load_nodes(fp_root)


# ── A2′ 观察级判据换轴(2026-07-16):门键不再按案终态枚举 ────────────────────────


def test_suspended_case_observations_ingested(drill_env):
    """挂起案观察入库(zhaiyq 532862 实证驱动:defect_candidate 级观察曾因案态
    suspended 不在 {failed_terminal, escalated} 白名单而整体丢弃)。案态只作语境。"""
    outputs, fp_root = drill_env
    cand = {"observe_cmd": "show sdns host status",
            "content": "IPv6 会话保持超时条目不清除,Timeout=0 仍在表中", "note": ""}
    led = _StubLedger([], cases=[(_AID, "挂起轮观察")])
    _ingest(outputs, _AID, [cand], led=led)
    nodes = _load_nodes(fp_root)
    behaviors = [b for n in nodes for b in n.get("behaviors", [])]
    assert len(behaviors) == 1
    assert behaviors[0]["validity"] == "uncertain"
    assert "挂起轮观察" in behaviors[0]["observed_under"]   # 语境=案态标注,非准入条件


def test_attribution_observation_fallback_no_candidates(drill_env):
    """无 behavior_candidates 案(777976/593516 型)经 extra_candidates 通道入库
    (attributor 结构化观察机械转候选,C5 生产侧兜底)。"""
    outputs, fp_root = drill_env
    (outputs / _AID).mkdir(exist_ok=True)   # 无 behavior_candidates.json
    extra = {_AID: [{"observe_cmd": "show sdns host pool",
                     "content": "show sdns host pool 只列池名不列成员 IP",
                     "note": "defect-candidate 轮观察:成员IP需另查"}]}
    led = _StubLedger([], cases=[(_AID, "挂起轮观察")], extra=extra)
    from main.ist_core.compile_engine_v8.uncertain import _ingest_uncertain_observations
    _ingest_uncertain_observations(led)
    behaviors = [b for n in _load_nodes(fp_root) for b in n.get("behaviors", [])]
    assert len(behaviors) == 1
    assert "只列池名" in behaviors[0]["content"]


def test_timestamp_variant_dedup(drill_env):
    """内容归一化去重:同一观察携不同时间戳 → 同 fact_key,不伪造多语境观察组。"""
    outputs, fp_root = drill_env
    c1 = {"observe_cmd": "show sdns host status",
          "content": "2026-07-14 11:47:00 条目仍在表中", "note": "x"}
    c2 = {"observe_cmd": "show sdns host status",
          "content": "2026-07-15 09:03:21 条目仍在表中", "note": "x"}
    _ingest(outputs, _AID, [c1, c2])
    behaviors = [b for n in _load_nodes(fp_root) for b in n.get("behaviors", [])]
    assert len(behaviors) == 1, "时间戳变体必须归一化撞同键,不得伪造第二条观察"


def test_uncertain_led_axis_and_attribution_observations(tmp_path, monkeypatch):
    """nodes._UncertainLed:deliverable/broken 三态排除,其余全入源带语境;
    extra_candidates 从 attribution 事实机械合成(锚=断言来源观测步)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import views as V

    vw = {"cases": {
        "1" * 18: {"status": V.S_DELIVERABLE},
        "2" * 18: {"status": V.S_BROKEN},
        "3" * 18: {"status": V.S_BROKEN_ERRORED},
        "4" * 18: {"status": V.S_SUSPENDED},
        "5" * 18: {"status": V.S_TERMINAL},
        "6" * 18: {"status": V.S_FAILED},
    }}
    led = N._UncertainLed(vw, [])
    got = dict(led.observation_cases())
    assert "1" * 18 not in got and "2" * 18 not in got and "3" * 18 not in got
    assert got["4" * 18] == "挂起轮观察"
    assert got["5" * 18] == "止损收尾轮观察"
    assert got["6" * 18] == "fail 轮观察"

    aid = "4" * 18
    monkeypatch.setattr(N, "_load_case_rows", lambda a: [
        {"E": "APV_0", "F": "cmds_config", "G": "sdns on"},
        {"E": "APV_0", "F": "cmd", "G": "show sdns host status"},   # 观测步(锚)
        {"E": "check_point", "F": "found", "G": r"Timeout"},
    ])
    fs = [
        {"ev": "verdict", "aid": aid, "run_id": "r1", "result": "fail",
         "ctx": "delivery", "artifact": "a1", "volume": "v", "signatures": []},
        {"ev": "attribution", "aid": aid, "round": 1, "run_id": "r1", "layer": "V",
         "disposition": "defect_candidate", "fix_direction": "超时条目不清除",
         "evidence": "Timeout=0 entry still present",
         "defect_candidate": {"repro": "步骤", "expected_with_source": "手册:应清除",
                              "actual": "Timeout=0 条目跨超时存活"}},
        # broken 轮的归因观察必须被源窗口判据排除
        {"ev": "verdict", "aid": aid, "run_id": "r2", "result": "broken",
         "ctx": "delivery", "artifact": "a1", "volume": "v", "signatures": []},
        {"ev": "attribution", "aid": aid, "round": 2, "run_id": "r2", "layer": "E",
         "disposition": "reflow", "fix_direction": "x", "evidence": "broken window echo"},
        # 用户裁决记账行不是设备观察
        {"ev": "attribution", "aid": aid, "round": 99, "layer": "E",
         "disposition": "env_blocked", "fix_direction": "user decision: 停",
         "evidence": "user", "user_stop": True},
    ]
    cands = N._attribution_observations(fs, aid)
    assert len(cands) == 1, "dc 表单观察入;broken 窗口与 user 记账行排除"
    assert cands[0]["observe_cmd"] == "show sdns host status"
    assert "Timeout=0 条目跨超时存活" in cands[0]["content"]

    # 无 check_point 的卷面=无锚,如实 no-op(不猜锚)
    monkeypatch.setattr(N, "_load_case_rows", lambda a: [
        {"E": "APV_0", "F": "cmds_config", "G": "sdns on"}])
    assert N._attribution_observations(fs, aid) == []


def test_promote_env_flag_regression(tmp_path, monkeypatch):
    """回归锚(2026-07-16 抓获):sh.env_flag V8 迁移漏带 → _promote 首行
    AttributeError 被静默吞,PASS 行为晋升从未生效。断言:函数存在且 _promote
    在开关关/无台账两条路都干净返回(不再异常)。"""
    from main.ist_core.compile_engine_v8 import _shared as sh2
    from main.ist_core.compile_engine_v8.uncertain import _promote_behavior_candidates

    assert sh2.env_flag("FOOTPRINT_BEHAVIOR_WRITEBACK") is True   # 默认开
    monkeypatch.setenv("FOOTPRINT_BEHAVIOR_WRITEBACK", "0")
    assert sh2.env_flag("FOOTPRINT_BEHAVIOR_WRITEBACK") is False
    _promote_behavior_candidates(_AID, None)          # 开关关:no-op
    monkeypatch.delenv("FOOTPRINT_BEHAVIOR_WRITEBACK")
    monkeypatch.setattr(sh2, "outputs_root", lambda: tmp_path)
    monkeypatch.setattr(sh2, "project_root", lambda: tmp_path)
    _promote_behavior_candidates(_AID, None)          # 无候选/无台账:干净返回


def test_verified_entries_stay_clean():
    """旧形态兼容:verified 且无语境的条目不写观察级字段,节点保持原样干净。"""
    fp: dict = {"behaviors": []}
    rf = RawFact(fact_kind="behavior", feature_path=["sdns"],
                 fact_key="k3", content="常规 PASS 行为")
    assert _append_behavior(fp, rf) == "append"
    assert "validity" not in fp["behaviors"][0]
    assert "observed_under" not in fp["behaviors"][0]


def test_observation_group_formed_signal_fires_once(tmp_path, monkeypatch):
    """入库端观察组信号:互异语境数首次跨过 2 的那次合并发一次,再加语境不重发。"""
    import json as _json
    from main.ist_core.memory.footprint import signals as _sig
    sig_log = tmp_path / "k_signals.jsonl"
    monkeypatch.setattr(_sig, "_LOG", sig_log)

    def _merge(key: str, content: str, ctx: str):
        fact = RawFact(fact_kind="behavior", feature_path=["sdns", "host"],
                       fact_key=key, cli_syntax="show sdns host status",
                       content=content, device_evidence={"autoid": _AID},
                       validity="uncertain", observed_under=ctx)
        routed = route_facts([fact], tmp_path)
        assert routed
        return merge_fact(routed[0], tmp_path)

    def _group_signals():
        if not sig_log.is_file():
            return []
        return [_json.loads(l) for l in sig_log.read_text(encoding="utf-8").splitlines()
                if _json.loads(l).get("signal") == "observation_group_formed"]

    assert _merge("g1", "语境甲下的行为", "ipv4 members only").action == "create"
    assert not _group_signals()                      # 1 个语境,未成组
    assert _merge("g2", "语境乙下的行为", "mixed v4/v6 members").action == "append"
    fired = _group_signals()
    assert len(fired) == 1                           # 跨过 2 的瞬间发一次
    assert fired[0]["subject"]                       # subject=节点 feature_id
    assert len((fired[0].get("payload") or {}).get("contexts") or []) == 2
    assert _merge("g3", "语境丙下的行为", "single member pool").action == "append"
    assert len(_group_signals()) == 1                # 第 3 语境不重发
