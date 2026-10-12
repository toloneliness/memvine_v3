from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional

from .base_task import TaskResult


@dataclass
class Issue:
    """发现的待处理问题"""
    task_name: str
    issue_type: str
    description: str
    node_ids: List[str] = None

    def __post_init__(self):
        if self.node_ids is None:
            self.node_ids = []


@dataclass
class Change:
    """已执行的变更"""
    task_name: str
    change_type: str
    description: str
    node_ids: List[str] = None

    def __post_init__(self):
        if self.node_ids is None:
            self.node_ids = []


@dataclass
class MaintenanceReport:
    """完整维护报告"""
    executed_at: datetime
    layer_executed: int
    tasks_executed: List[str]
    task_results: Dict[str, TaskResult]
    total_changes: int
    pending_issues: List[Issue]
    natural_language_summary: str = ""

    def to_cognitive_brief_entry(self) -> dict:
        """生成认知简报中的条目"""
        return {
            "layer": self.layer_executed,
            "tasks": self.tasks_executed,
            "pending_issues_count": len(self.pending_issues),
            "total_changes": self.total_changes,
            "summary": self.natural_language_summary,
        }

    def to_natural_text(self) -> str:
        """生成自然语言描述"""
        parts = []
        layer_names = {1: "快速检查", 2: "轻度整理", 3: "深度反思"}
        parts.append(f"[维护] 执行{layer_names.get(self.layer_executed, '')}，"
                    f"共{len(self.tasks_executed)}项任务，{self.total_changes}处变更，"
                    f"发现{len(self.pending_issues)}个待处理问题。")

        if self.pending_issues:
            parts.append("\n待处理：")
            for issue in self.pending_issues[:5]:
                parts.append(f"  - [{issue.issue_type}] {issue.description}")

        if self.natural_language_summary:
            parts.append(f"\n{self.natural_language_summary}")

        return "\n".join(parts)


class MaintenanceReportSerializer:
    """维护报告序列化器 - 将结构化报告转为自然语言"""

    def serialize(self, report: MaintenanceReport) -> str:
        """将报告转为结构化文本片段"""
        parts = []

        for task_name, result in report.task_results.items():
            # 收集问题
            for issue_desc in result.issues_found:
                parts.append(f"- {issue_desc}")

            # 收集变更
            for change_type, change_desc in result.changes_made.items():
                if isinstance(change_desc, str):
                    parts.append(f"- 已{change_type}：{change_desc}")
                elif isinstance(change_desc, list):
                    if change_desc:
                        count = len(change_desc)
                        examples = ", ".join(str(c) for c in change_desc[:3])
                        if count > 3:
                            examples += f" 等{count}项"
                        parts.append(f"- 已{change_type}：{examples}")

        return "\n".join(parts)

    def to_natural_language(self, structured_text: str, llm_client, self_name: str = "藤蔓") -> str:
        """用 LLM 润色为自然语言"""
        if not structured_text:
            return "我在空闲时间整理了一下记忆，没有发现需要特别说明的问题。"

        from prompts import MAINTENANCE_REPORT_PROMPT, IDENTITY_VOICE
        identity = IDENTITY_VOICE.format(self_name=self_name, user_name="用户")
        prompt = MAINTENANCE_REPORT_PROMPT.format(identity=identity, structured_text=structured_text)

        try:
            response = llm_client.chat.completions.create(
                model=llm_client.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return structured_text