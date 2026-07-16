r"""结构化测试报告数据模型。

定义 ``ReportSchema`` 及其组成部分（``TestCaseResult``、``Defect``），
提供 ``to_markdown()`` 方法生成企微云文档兼容的 Markdown。

替代旧 ``tools.build_report_markdown`` / ``tools.build_test_report`` 的
无类型字符串拼接方式。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TestStatus(str, Enum):
    """测试用例执行状态。"""

    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class Severity(str, Enum):
    """缺陷严重程度。"""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


_STATUS_ICON: dict[TestStatus, str] = {
    TestStatus.PASSED: "✅",
    TestStatus.FAILED: "❌",
    TestStatus.BLOCKED: "🚫",
    TestStatus.SKIPPED: "⏭️",
    TestStatus.ERROR: "⚠️",
}


@dataclass
class TestCaseResult:
    """单条测试用例结果。"""

    case_id: str
    description: str
    status: TestStatus
    evidence: str = ""
    duration_s: float = 0.0
    device_info: str = ""
    traffic_result: str = ""
    defect_id: str = ""
    notes: str = ""


@dataclass
class Defect:
    """缺陷条目。"""

    defect_id: str
    description: str
    severity: Severity
    case_id: str = ""
    root_cause: str = ""
    status: str = "open"
    owner: str = ""


@dataclass
class ReportSchema:
    """结构化测试报告。

    ``to_markdown()`` 输出的 Markdown 可直接传给企微云文档 API。

    用法::

        report = ReportSchema(
            title="2026-07-13 IPv6 测试报告",
            summary="本次测试覆盖 34 个用例，通过率 91.2%。",
            test_cases=[TestCaseResult(case_id="1", description="...", status=TestStatus.PASSED)],
        )
        md = report.to_markdown()
    """

    title: str
    summary: str
    environment: dict[str, str] = field(default_factory=dict)
    test_cases: list[TestCaseResult] = field(default_factory=list)
    defects: list[Defect] = field(default_factory=list)
    conclusions: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    generated_by: str = "InfoTest Engine (IST-Core)"

    # --- 计算属性 ---

    @property
    def total_count(self) -> int:
        return len(self.test_cases)

    @property
    def passed_count(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == TestStatus.PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == TestStatus.FAILED)

    @property
    def blocked_count(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == TestStatus.BLOCKED)

    @property
    def pass_rate(self) -> float:
        if not self.test_cases:
            return 0.0
        return self.passed_count / self.total_count

    # --- 序列化 ---

    def to_dict(self) -> dict[str, object]:
        """转为 JSON 可序列化字典。"""
        return {
            "title": self.title,
            "summary": self.summary,
            "environment": self.environment,
            "test_cases": [
                {
                    "case_id": tc.case_id,
                    "description": tc.description,
                    "status": tc.status.value,
                    "evidence": tc.evidence,
                    "duration_s": tc.duration_s,
                    "device_info": tc.device_info,
                    "defect_id": tc.defect_id,
                    "notes": tc.notes,
                }
                for tc in self.test_cases
            ],
            "defects": [
                {
                    "defect_id": d.defect_id,
                    "description": d.description,
                    "severity": d.severity.value,
                    "case_id": d.case_id,
                    "root_cause": d.root_cause,
                    "status": d.status,
                    "owner": d.owner,
                }
                for d in self.defects
            ],
            "conclusions": self.conclusions,
            "recommendations": self.recommendations,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "total": self.total_count,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "pass_rate": f"{self.pass_rate:.1%}",
        }

    def to_markdown(self) -> str:
        """转为企微云文档兼容的 Markdown。"""
        lines: list[str] = [
            f"# {self.title}",
            "",
            f"**生成时间**: {self.generated_at}",
            f"**生成工具**: {self.generated_by}",
            "",
            "## 执行摘要",
            self.summary or "（待补充）",
            "",
        ]

        # 统计概览
        if self.test_cases:
            lines += [
                "## 测试概览",
                "",
                f"- 总用例数：{self.total_count}",
                f"- 通过：{self.passed_count} ✅",
                f"- 失败：{self.failed_count} ❌",
                f"- 阻塞：{self.blocked_count} 🚫",
                f"- 通过率：{self.pass_rate:.1%}",
                "",
            ]

        # 环境信息
        if self.environment:
            lines += ["## 测试环境", "", "| 项目 | 值 |", "|------|-----|"]
            for k, v in self.environment.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")

        # 测试结果表
        if self.test_cases:
            lines += [
                "## 测试结果明细",
                "",
                "| 用例编号 | 描述 | 状态 | 用时 | 证据 |",
                "|----------|------|------|------|------|",
            ]
            for tc in self.test_cases:
                icon = _STATUS_ICON.get(tc.status, "❓")
                lines.append(
                    f"| {tc.case_id} "
                    f"| {tc.description[:60]} "
                    f"| {icon} {tc.status.value} "
                    f"| {tc.duration_s:.0f}s "
                    f"| {tc.evidence[:100]} |"
                )
            lines.append("")

        # 缺陷清单
        if self.defects:
            lines += [
                "## 缺陷清单",
                "",
                "| 编号 | 描述 | 严重程度 | 关联用例 | 根因 |",
                "|------|------|----------|----------|------|",
            ]
            for d in self.defects:
                lines.append(
                    f"| {d.defect_id} "
                    f"| {d.description[:80]} "
                    f"| {d.severity.value} "
                    f"| {d.case_id} "
                    f"| {d.root_cause[:100]} |"
                )
            lines.append("")

        # 结论
        if self.conclusions:
            lines += ["## 结论", ""]
            for i, c in enumerate(self.conclusions, 1):
                lines.append(f"{i}. {c}")
            lines.append("")

        # 建议
        if self.recommendations:
            lines += ["## 建议", ""]
            for i, r in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {r}")
            lines.append("")

        lines += ["---", f"*本报告由 {self.generated_by} 自动生成*"]
        return "\n".join(lines)
