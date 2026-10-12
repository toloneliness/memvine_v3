from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List
import networkx as nx

class EntityCrackDetectionTask(BaseMaintenanceTask):
    """第一层任务：实体裂痕检测 - 发现指向同一实体但未合并的节点"""

    @property
    def name(self) -> str:
        return "entity_crack_detection"

    @property
    def layer(self) -> int:
        return 1

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.READ_ONLY

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        issues_found = []
        entity_nodes = []

        # 找出所有实体节点
        for node_id in topology.graph.nodes():
            node_data = topology.get_node_data(node_id)
            if node_data.get("node_type") == "entity":
                entity_nodes.append((node_id, node_data))

        # 两两比较相似性
        checked = set()
        for i, (id_a, data_a) in enumerate(entity_nodes):
            content_a = data_a.get("content", "").lower()
            for j, (id_b, data_b) in enumerate(entity_nodes[i+1:], i+1):
                pair = tuple(sorted([id_a, id_b]))
                if pair in checked:
                    continue
                checked.add(pair)

                content_b = data_b.get("content", "").lower()
                similarity = topology.structural_similarity(id_a, id_b)

                # 高相似度说明可能是同一个实体
                if similarity > 0.85 and content_a != content_b:
                    name_a = data_a.get("target", id_a)
                    name_b = data_b.get("target", id_b)
                    issues_found.append(
                        f"疑似重复实体：「{name_a}」和「{name_b}」(相似度 {similarity:.2f})，待合并"
                    )

        return TaskResult(
            success=True,
            changes_count=0,
            issues_found=issues_found,
            message=f"发现 {len(issues_found)} 组疑似重复实体"
        )