"""三层 Provenance IR（V3 步骤1，论文 §3.5 定义3.6/3.7 的带来源 G⊔E⊔V 分解）。

draft 产出 steps 的同时，为**每一步**标注它属于哪一层、来源是什么：
- G 层（骨架/文法）：source = footprint feature_id / 先例 xlsx 名
- E 层（环境常量）：source = env_facts 拓扑行（可达子网/服务 IP）
- V 层（业务语义）：source = 先例链 / 手册行号 / 作者意图

这是 draft↔grade↔verify↔writeback 的公共契约：
- grade（步骤2）验 provenance 而非重新 grep；
- verify（步骤5）按 layer 把 fail 路由到 G/E/V；
- writeback（步骤4）只把已验证的 G/E 段事实写回 footprint。

设计红线（§3.7ter）：provenance 只**记录** draft 已做的来源决策，
不替代骨架选择——layer/source 是 draft 自己标的语义注解，不是确定性规则。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Literal

Layer = Literal["G", "E", "V"]
_VALID_LAYERS = ("G", "E", "V")

# source.kind 取值：来源类型，供 writeback/verify 按类型路由。
_VALID_SOURCE_KINDS = (
    "footprint",      # G：footprint 节点（feature_id）
    "precedent",      # G/V：先例 xlsx
    "env_facts",      # E：拓扑事实源
    "manual",         # V：手册行
    "intent",         # V：作者意图（脑图原文）
    "config_derived", # V_K：期望值是作者写的 config 的确定后果（池IP/超时/删后状态/协议固定响应）→ 编译期常量
    "captured_relation", # V_R：跨观测关系断言（会话保持/同-异），check_point 用 H 寄存器引用前序捕获做 found/not_found，无 <RUNTIME>
    "distribution_derived", # V_dist：分布类算法（rr/wrr）发 N 次后各后端**累计命中分布**的统计区间，
                            # 期望由算法语义+次数+权重离线推导（rr≈N/k、wrr≈N×w_i/Σw）、守恒 Σ==N 可验，
                            # 经 distribution_assertion 展开成区间正则 found（非恒真、非 <RUNTIME>）。
                            # ⚠ 单次命中哪个成员是运行时落点（captured_relation 或 device_runtime），不归此类。
    "membership_derived", # V_mem：命中归属锚点——"这次输出是否落在某 pool 的成员 IP 集合里"，
                          # 期望值（成员集合）是该 pool 配置的静态确定后果（sdns pool service 写死了
                          # 哪些成员），不是运行时不可知；经 membership_assertion 展开成 found/not_found
                          # (成员1|成员2|...)。用于 pool 内多成员场景的命中判定、new_member_last 的
                          # 有序轨迹（新增 pool 的成员集合前段 not_found、覆盖原 pool 一轮后 found）。
                          # ⚠ 与 captured_relation 的区别：这里期望值是**配置已知的常量**（成员集合），
                          # 不是"运行时首次捕获的值"；与 device_runtime 的区别：命中归属可离线判定，
                          # 不是"落点不可知只能占位"。
    "skeleton",       # G：族骨架（步骤3 族首产出，族内复用）
    "device_runtime", # V：期望值离线不可知（落点依赖探活/哈希/会话/脚本运行时），值填 <RUNTIME> 占位
    "device_verified",# V：device_runtime 槽位已由 ist_verify 上机回填真实值并锁死（不再含 <RUNTIME>）
    "unknown",        # 兜底：draft 没标来源（应尽量避免）
)

# 离线不可知占位符：device_runtime 类断言的期望值统一用它，标识"该值上机才知道、编译期不许编"。
RUNTIME_PLACEHOLDER = "<RUNTIME>"


@dataclass
class StepSource:
    """一步的来源。kind 决定路由类型，ref 是具体定位（feature_id/行号/xlsx名）。"""
    kind: str = "unknown"
    ref: str = ""

    def __post_init__(self):
        if self.kind not in _VALID_SOURCE_KINDS:
            self.kind = "unknown"


@dataclass
class StepIR:
    """一个编译步骤 + 三层来源标注。E/F/G 与 xlsx 列语义一致（见 compile_emit）。"""
    E: str
    F: str
    G: str
    layer: Layer = "V"
    source: StepSource = field(default_factory=StepSource)

    def __post_init__(self):
        if self.layer not in _VALID_LAYERS:
            self.layer = "V"


@dataclass
class CaseProvenance:
    """一个 case 的完整 provenance：autoid + 逐步来源 + 族骨架引用（步骤3）。"""
    autoid: str
    steps: list[StepIR] = field(default_factory=list)
    skeleton_ref: str = ""   # 步骤3：本 case 复用的族骨架 id（族内 case 非空）
    provisional: bool = True  # 步骤4：未上机前为 True（结构门+grade代理门）；上机PASS后置 False

    def to_dict(self) -> dict:
        return {
            "autoid": self.autoid,
            "skeleton_ref": self.skeleton_ref,
            "provisional": self.provisional,
            "steps": [
                {"E": s.E, "F": s.F, "G": s.G, "layer": s.layer,
                 "source": {"kind": s.source.kind, "ref": s.source.ref}}
                for s in self.steps
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def layer_steps(self, layer: Layer) -> list[StepIR]:
        return [s for s in self.steps if s.layer == layer]

    @classmethod
    def from_dict(cls, d: dict) -> "CaseProvenance":
        steps = []
        for raw in d.get("steps", []):
            src = raw.get("source") or {}
            steps.append(StepIR(
                E=str(raw.get("E", "")), F=str(raw.get("F", "")), G=str(raw.get("G", "")),
                layer=raw.get("layer", "V"),
                source=StepSource(kind=src.get("kind", "unknown"), ref=str(src.get("ref", ""))),
            ))
        return cls(
            autoid=str(d.get("autoid", "")),
            steps=steps,
            skeleton_ref=str(d.get("skeleton_ref", "")),
            provisional=bool(d.get("provisional", True)),
        )

    @classmethod
    def from_json(cls, text: str) -> "CaseProvenance":
        return cls.from_dict(json.loads(text))


def parse_provenance(provenance_json: str) -> CaseProvenance | None:
    """容错解析 provenance_json；空/坏返回 None（调用方据此回退 V2 行为）。"""
    if not provenance_json or not provenance_json.strip():
        return None
    try:
        return CaseProvenance.from_json(provenance_json)
    except Exception:  # noqa: BLE001
        return None


def steps_match(provenance: CaseProvenance, steps: list[dict]) -> bool:
    """校验 provenance 的步骤与实际 emit 的 steps 在 E/F/G 上一致（防 draft 标注与产物脱节）。"""
    if len(provenance.steps) != len(steps):
        return False
    for ps, st in zip(provenance.steps, steps):
        if ps.E != str(st.get("E", "")) or ps.F != str(st.get("F", "")) or ps.G != str(st.get("G", "")):
            return False
    return True


def backfill_efg(provenance: CaseProvenance, steps: list[dict]) -> bool:
    """按位置把 emit steps 的 E/F/G 回填进 provenance——draft 只标 layer/source、不必手抄 E/F/G。
    （手抄一长串 E/F/G 极易错位，一错位 steps_match 就失败、旁挂跳过、draft 就重 emit 空转。）
    步骤数一致即逐位回填并返回 True；数目对不上才返回 False（旁挂跳过）。"""
    if len(provenance.steps) != len(steps):
        return False
    for ps, st in zip(provenance.steps, steps):
        ps.E = str(st.get("E", ""))
        ps.F = str(st.get("F", ""))
        ps.G = str(st.get("G", ""))
    return True


def check_runtime_consistency(provenance: CaseProvenance) -> list[str]:
    """不瞎写硬契约：device_runtime 来源 ⟺ G 值是 <RUNTIME> 占位，双向自洽。

    抓三类骗过门的写法（纯结构自洽，不判值对错——离线本就判不了对错）：
    - 标了 device_runtime 却填了具体值（假装弃权、实则编数）；
    - 填了 <RUNTIME> 占位却把来源标成 footprint/precedent 等（占位却谎称有源）；
    - 标了 device_verified（上机回填锁死）却仍含 <RUNTIME>（谎称已回填、实则没填）。

    含 <RUNTIME> 子串即视为占位（兼容部分模式 "前缀<RUNTIME>"），不只看整串相等。
    返回违规说明列表（空＝自洽）。只看 check_point（断言点）步骤——占位只对期望值有意义。
    """
    problems: list[str] = []
    for i, s in enumerate(provenance.steps):
        if s.E.strip() != "check_point":
            continue
        has_placeholder = RUNTIME_PLACEHOLDER in s.G
        is_runtime_kind = s.source.kind == "device_runtime"
        is_verified_kind = s.source.kind == "device_verified"
        if is_runtime_kind and not has_placeholder:
            problems.append(
                f"step[{i}] 来源标 device_runtime（离线不可知）却填了具体值 {s.G!r}"
                f"——离线不可知就不许编数，期望值应含 {RUNTIME_PLACEHOLDER} 占位。"
            )
        elif has_placeholder and not (is_runtime_kind or is_verified_kind):
            problems.append(
                f"step[{i}] 期望值含 {RUNTIME_PLACEHOLDER} 占位却把来源标成 {s.source.kind!r}"
                f"——占位即声明离线不可知，来源必须标 device_runtime。"
            )
        elif is_verified_kind and has_placeholder:
            problems.append(
                f"step[{i}] 来源标 device_verified（声称已上机回填）却仍含 {RUNTIME_PLACEHOLDER} 占位"
                f"——回填未完成就不许标 verified，未填的留 device_runtime。"
            )
    return problems
