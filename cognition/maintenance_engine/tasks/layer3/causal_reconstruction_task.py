from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class CausalReconstructionTask(BaseMaintenanceTask):
    """第三层任务：因果网络重构 - 重新分析全图因果关系"""

    @property
    def name(self) -> str:
        return "causal_reconstruction"

    @property
    def layer(self) -> int:
        return 3

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.SOFT_WRITE

    @property
    def required_capabilities(self) -> List[str]:
        return ["causal_inference"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        result = topology.causal_inference()
        causal_pairs = result.get("causal_pairs", [])
        updated_count = 0

        for pair in causal_pairs:
            if pair.get("confidence", 0) > 0.6:
                direction = pair["direction"]
                confidence = pair["confidence"]

                if " → " in direction:
                    source, target = direction.split(" → ", 1)
                elif " ↔ " in direction:
                    parts = direction.split(" ↔ ", 1)
                    source, target = parts[0], parts[1]
                else:
                    continue

                if topology.graph.has_node(source) and topology.graph.has_node(target):
                    if topology.graph.has_edge(source, target):
                        old_conf = topology.graph[source][target].get("causal_confidence", 0.5)
                        if abs(confidence - old_conf) > 0.1:
                            topology.graph[source][target]["causal_confidence"] = confidence
                            updated_count += 1
                    else:
                        topology.connect(source, target, weight=confidence * 0.6,
                            relation="causes", confidence=confidence, status="pending_validation")
                        updated_count += 1

        return TaskResult(
            success=True,
            changes_count=updated_count,
            message=f"重构因果网络，更新/创建了 {updated_count} 条因果边"
        )