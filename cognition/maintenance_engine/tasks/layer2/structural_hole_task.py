from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class StructuralHoleTask(BaseMaintenanceTask):
    """第二层任务：结构洞填补 - 发现应该连接但缺失连接的节点，建立弱关联"""

    @property
    def name(self) -> str:
        return "structural_hole"

    @property
    def layer(self) -> int:
        return 2

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.SOFT_WRITE

    @property
    def required_capabilities(self) -> List[str]:
        return ["structural_holes", "link_prediction"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        holes = topology.structural_holes()
        if not holes:
            return TaskResult(success=True, changes_count=0, message="未发现结构洞")

        holes_sorted = sorted(holes, key=lambda h: h.get("constraint", 0), reverse=True)
        max_new_edges = config.get("max_new_edges_per_run", 10)
        confidence_threshold = config.get("link_prediction_threshold", 0.1)

        changes_count = 0
        changes_made = {}
        added_edges = []

        for hole in holes_sorted[:max_new_edges]:
            for bridge in hole.get("missing_bridges", []):
                if changes_count >= max_new_edges:
                    break
                u, v = bridge["between"][0], bridge["between"][1]

                pred = topology.link_prediction(u, v)
                score = pred.get("adamic_adar", 0)

                if score > confidence_threshold:
                    weight = score * 0.5
                    topology.connect(u, v, weight=weight,
                                     relation="predicted_association",
                                     confidence=score,
                                     status="pending_validation")
                    changes_count += 1

                    u_data = topology.get_node_data(u) or {}
                    v_data = topology.get_node_data(v) or {}
                    u_content = u_data.get("content", u)[:30]
                    v_content = v_data.get("content", v)[:30]
                    added_edges.append(f"{u_content} - {v_content} (score={score:.3f})")

        changes_made["added_edges"] = added_edges

        return TaskResult(
            success=True,
            changes_count=changes_count,
            changes_made=changes_made,
            message=f"填补了 {changes_count} 个结构洞，建立{changes_count}条弱关联"
        )