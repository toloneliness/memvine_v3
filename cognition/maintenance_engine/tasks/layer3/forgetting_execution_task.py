from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List
from config import TRACE_IDLE_DAYS
import time

class ForgettingExecutionTask(BaseMaintenanceTask):
    """第三层任务：遗忘策略执行 - 删除长期未激活、低重要性的冗余记忆"""

    @property
    def name(self) -> str:
        return "forgetting_execution"

    @property
    def layer(self) -> int:
        return 3

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.HARD_WRITE

    @property
    def required_capabilities(self) -> List[str]:
        return ["centrality_analysis"]

    def __init__(self):
        self.deleted_nodes = []

    def _score_forgetting_candidate(
        self,
        node_id: str,
        node_data: dict,
        pagerank: Dict[str, float],
        betweenness: Dict[str, float],
        now_ts: float
    ) -> float:
        """计算遗忘分数，分数越高越应该遗忘。
        综合考虑：PageRank 中心性、介数中心性、最后激活时间、权重衰减
        """
        pr = pagerank.get(node_id, 0.0)
        bt = betweenness.get(node_id, 0.0)

        # 时间因素：多久没激活了
        last_activated = node_data.get("last_activated", now_ts)
        days_idle = (now_ts - last_activated) / 86400.0

        # 权重因素：当前权重
        weight = node_data.get("weight", 1.0)

        # 记忆类型：日常对话更容易遗忘
        mem_type = node_data.get("mem_type", "daily_chat")
        type_weight = {
            "identity": 0.1,
            "core_fact": 0.2,
            "deep_emotion": 0.3,
            "daily_chat": 1.0,
            "system_event": 0.8,
        }.get(mem_type, 1.0)

        # 综合分数：
        # - 中心性越低 → 越容易忘 × 这里我们反过来说，分数越高越忘
        # - 闲置越久 → 越容易忘
        # - 权重越低 → 越容易忘
        # - 类型权重放大

        score = (
            (1.0 - min(pr * 10, 1.0)) * 0.4 +    # PageRank：越低分越高（越该忘）
            (1.0 - min(bt * 20, 1.0)) * 0.3 +    # 介数中心性：越低分越高（越该忘）
            (min(days_idle / TRACE_IDLE_DAYS, 1.0)) * 0.2 +  # 闲置天数：越久分越高
            (1.0 - weight) * 0.1                  # 权重：越低分越高
        ) * type_weight

        return score

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        now_ts = topology.clock.now_ts() if hasattr(topology, 'clock') else time.time()
        # 获取中心性分析
        centrality = topology.centrality_analysis(top_k=len(topology.graph.nodes()))
        # 将 list[dict] 转换为 {node_id: score} 字典
        pagerank = {entry["node_id"]: entry["pagerank"] for entry in centrality.get("pagerank", [])}
        betweenness = {entry["node_id"]: entry["betweenness"] for entry in centrality.get("betweenness", [])}

        threshold = config.get("forgetting_threshold", 0.7)
        max_delete_per_run = config.get("max_delete_per_run", int(len(topology.graph.nodes()) * 0.05))

        candidates = []

        for node_id in list(topology.graph.nodes()):
            # 不删实体节点和根节点
            if node_id.startswith("entity_") or node_id == "root":
                continue

            node_data = topology.get_node_data(node_id)
            if not node_data:
                continue

            score = self._score_forgetting_candidate(node_id, node_data, pagerank, betweenness, now_ts)

            if score >= threshold:
                candidates.append((score, node_id))

        # 按分数排序，删除分数最高的 N 个
        candidates.sort(reverse=True, key=lambda x: x[0])
        to_delete = candidates[:max_delete_per_run]

        deleted_contents = []
        for score, node_id in to_delete:
            if topology.graph.has_node(node_id):
                nd = topology.graph.nodes[node_id]
                content = str(nd.get("data", {}).get("content", node_id))[:40]
                deleted_contents.append(f"{node_id}:{content}")
                topology.graph.remove_node(node_id)
                self.deleted_nodes.append(node_id)

        return TaskResult(
            success=True,
            changes_count=len(to_delete),
            changes_made={"deleted_nodes": deleted_contents},
            message=f"执行遗忘策略，删除 {len(to_delete)} 条长期未激活的低权重记忆"
        )