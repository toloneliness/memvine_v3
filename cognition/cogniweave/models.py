# cognition/cogniweave/models.py
"""CogniWeave 数据模型 —— 定义查询议程、执行结果、编织上下文的结构"""

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class QueryItem:
    id: str
    intent: str
    cypher: str
    params: dict = field(default_factory=dict)
    priority: Priority = Priority.MEDIUM
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "intent": self.intent,
            "cypher": self.cypher,
            "params": self.params,
            "priority": self.priority.value,
            "depends_on": self.depends_on,
        }

@dataclass
class QueryAgenda:
    agenda: list[QueryItem]
    strategy: str = "concurrent"
    max_concurrency: int = 4
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "agenda": [q.to_dict() for q in self.agenda],
            "strategy": self.strategy,
            "max_concurrency": self.max_concurrency,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueryAgenda":
        items = []
        for qd in data.get("agenda", []):
            items.append(QueryItem(
                id=qd["id"],
                intent=qd.get("intent", ""),
                cypher=qd.get("cypher", ""),
                params=qd.get("params", {}),
                priority=Priority(qd.get("priority", "medium")),
                depends_on=qd.get("depends_on", []),
            ))
        return cls(
            agenda=items,
            strategy=data.get("strategy", "concurrent"),
            max_concurrency=data.get("max_concurrency", 4),
            reasoning=data.get("reasoning", ""),
        )

@dataclass
class QueryResult:
    query_id: str
    intent: str
    cypher: str
    data: Any
    success: bool = True
    error: str = ""
    execution_time: float = 0.0
    result_count: int = 0

    def summary(self, max_items: int = 8) -> str:
        if not self.success:
            return f"[{self.query_id}] 执行失败: {self.error}"
        if isinstance(self.data, dict):
            count = self.data.get("count", self.data.get("neighbor_count", self.data.get("match_count", 0)))
            return f"[{self.query_id}] 意图={self.intent}, 结果数={count}"
        if isinstance(self.data, list):
            return f"[{self.query_id}] 意图={self.intent}, 结果数={len(self.data)}"
        return f"[{self.query_id}] 意图={self.intent}, 结果={str(self.data)[:80]}"

@dataclass
class CognitiveContext:
    agenda: QueryAgenda
    results: dict[str, QueryResult]
    total_time: float = 0.0
    success_count: int = 0
    fail_count: int = 0

    def to_llm_context(self, max_items_per_query: int = 8) -> str:
        lines = ["你已执行了以下图查询，获取了结构化认知数据：\n"]
        for qid, qr in self.results.items():
            item = next((q for q in self.agenda.agenda if q.id == qid), None)
            intent = item.intent if item else qr.intent
            lines.append(f"查询 {qid}（意图：{intent}）：")
            if not qr.success:
                lines.append(f"  执行失败: {qr.error}")
                continue
            data = qr.data
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, list):
                        shown = v[:max_items_per_query]
                        lines.append(f"  {k}: {shown}" + (f" ...等共{len(v)}项" if len(v) > max_items_per_query else ""))
                    else:
                        lines.append(f"  {k}: {v}")
            elif isinstance(data, list):
                shown = data[:max_items_per_query]
                lines.append(f"  结果: {shown}" + (f" ...等共{len(data)}项" if len(data) > max_items_per_query else ""))
            else:
                lines.append(f"  结果: {str(data)[:200]}")
            lines.append("")
        lines.append(f"共 {self.success_count} 个查询成功, {self.fail_count} 个失败, 耗时 {self.total_time:.2f}s")
        return "\n".join(lines)