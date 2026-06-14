"""技能库基建（Phase 0 自进化技能库的"一个中心"）。

把"技能作为一等制品"的格式 / 索引 / 版本化 / A-B 闸 / 质量契约建起来，全程
**不碰** pipeline.py / rr_stats.py / assertion_fix.py / settle.py（回归安全不变量：
850 离线测试在任何节点不无故变红）。

模块分工：
  - schema.py          归纳技能 frontmatter 扩展字段（SkillSpec + 校验）。所有模块的依赖根。
  - registry.py        技能库索引（内容寻址 sha256 + diff + realpath dedup），落 runtime/skill_lib/。
  - verify_runner.py   离线执行技能附带的 verify.py 纯函数（verify(payload)->dict）。
  - quality_contract.py 归纳技能质量契约静态门（拦逐 case 硬编码 / 缺 TRIGGER / 无溯源）。
  - ab_gate.py         A-B 闸（held-out 被试选取 + with/without 首跑对比裁决）。
  - health.py          技能首跑通过率趋势 + 劣化降级判定（纯函数）。

设计溯源见 plan：cc-haha 字段语义（version/effort/source/paths/realpath dedup）+
同事手写技能纪律（TRIGGER+SKIP / 证据接地）+ 已记录反模式护栏（no-per-case-hardcoding）。
"""

from __future__ import annotations

from main.case_compiler.skill_lib.schema import (
    SkillSpec,
    ParamSlot,
    Evidence,
    ABTestRecord,
    VALID_EFFORTS,
    VALID_SOURCES,
)

__all__ = [
    "SkillSpec",
    "ParamSlot",
    "Evidence",
    "ABTestRecord",
    "VALID_EFFORTS",
    "VALID_SOURCES",
]
