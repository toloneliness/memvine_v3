from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class BeliefPropagationTask(BaseMaintenanceTask):
    """第一层任务：信念传播 - 增量更新信念置信度"""

    @property
    def name(self) -> str:
        return "belief_propagation"

    @property
    def layer(self) -> int:
        return 1

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.SOFT_WRITE

    @property
    def required_capabilities(self) -> List[str]:
        return ["belief_propagation"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        # 找出所有标记为待验证的节点
        seeds = {}
        for node_id in topology.graph.nodes():
            node_data = topology.graph.nodes[node_id]
            if node_data.get("needs_revalidation", False):
                seeds[node_id] = 0.5  # 初始置信度

        if not seeds:
            return TaskResult(success=True, changes_count=0, message="没有待验证节点")

        # 增量信念传播
        result = topology.belief_propagation(seeds, iterations=3, damping=0.85)
        changes_count = 0

        for node_id, belief in result.items():
            node_data = topology.graph.nodes[node_id]
            old_conf = node_data.get("confidence", 0.5)
            if abs(belief - old_conf) > 0.1:
                node_data["confidence"] = belief
                changes_count += 1
                if belief < 0.2:
                    node_data["needs_revalidation"] = True  # 低置信度保持待验证

        return TaskResult(
            success=True,
            changes_count=changes_count,
            message=f"更新了 {changes_count} 个节点的置信度"
        )