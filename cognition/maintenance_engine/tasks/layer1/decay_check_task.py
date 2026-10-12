from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class DecayCheckTask(BaseMaintenanceTask):
    """第一层任务：记忆流失检查 - 检查高重要性记忆是否快速衰减"""

    @property
    def name(self) -> str:
        return "decay_check"

    @property
    def layer(self) -> int:
        return 1

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.READ_ONLY

    @property
    def required_capabilities(self) -> List[str]:
        return ["centrality_analysis"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        centrality = topology.centrality_analysis(top_k=50)
        pagerank_list = centrality.get("pagerank", [])

        issues_found = []
        threshold = config.get("fast_decay_threshold", 0.3)

        for entry in pagerank_list[:20]:
            node_id = entry["node_id"]
            score = entry["pagerank"]

            if score < 0.02:
                continue

            node_data = topology.get_node_data(node_id)
            if not node_data:
                continue

            last_activated = node_data.get("last_activated", 0)
            born_at = node_data.get("born_at", last_activated)
            days_old = (last_activated - born_at) / (86400 * 30) if born_at > 0 else 0

            if days_old > 1:
                weight = node_data.get("weight", 1.0)
                initial_weight = node_data.get("initial_weight", weight)
                if initial_weight > weight:
                    decay_rate = (initial_weight - weight) / initial_weight / days_old
                    if decay_rate > threshold / 30:
                        content = node_data.get("content", "")[:50]
                        issues_found.append(
                            f"高重要性记忆快速衰减：「{content}...」，月衰减 {(decay_rate*30*100):.1f}%，待强化"
                        )

        return TaskResult(
            success=True,
            changes_count=0,
            issues_found=issues_found,
            message=f"发现 {len(issues_found)} 条快速衰减的重要记忆"
        )