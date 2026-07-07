"""消融实验开关:论文 §5 双臂对照(Arm-L 分层 vs Arm-E 基线裸生成)。

唯一用途:对照实验。生产默认 Arm-L(完整分层),本模块不改变任何默认行为。

通过环境变量 `IST_ABLATION_ARM` 切换:
  - 'L'(默认/缺省):完整分层流水线。compile_precedent 正常检索先例(G 段)、
    compile_emit 正常做可达性校验(E 段)。
  - 'E':基线裸生成。模拟"业界默认的 LLM 自由整写":
    * G 段:compile_precedent 不返回先例(模拟无先例约束)
    * E 段:compile_emit 跳过可达性校验门(模拟无拓扑查表)

设计红线:
  - 默认 'L',任何非 'E' 取值都按 'L' 处理——生产永不受影响。
  - 只读 env,不写状态;两臂共用同一代码路径,仅在三个注入点按 arm 分叉,保证对照公平。
  - 每次调用现读 env(不缓存),便于同进程内切换臂跑对照。
"""
from __future__ import annotations

import os

ARM_LAYERED = "L"
ARM_BASELINE = "E"


def current_arm() -> str:
    """返回当前实验臂。非 'E' 一律视为 'L'(分层,生产默认)。"""
    v = (os.environ.get("IST_ABLATION_ARM") or "").strip().upper()
    return ARM_BASELINE if v == ARM_BASELINE else ARM_LAYERED


def is_baseline() -> bool:
    """是否处于基线裸生成臂(Arm-E)。"""
    return current_arm() == ARM_BASELINE


def arm_tag() -> str:
    """供采集脚本/日志标注用的臂标签。"""
    return current_arm()
