from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class NarrativeConsistencyTask(BaseMaintenanceTask):
    """第三层任务：叙事一致性校验 - 检查自传体叙事与图结构是否一致"""

    @property
    def name(self) -> str:
        return "narrative_consistency"

    @property
    def layer(self) -> int:
        return 3

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.READ_ONLY

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        issues_found = []

        # 找到根节点（自我节点）
        root_id = topology.find_root_node()
        if not root_id:
            return TaskResult(success=True, changes_count=0, message="未找到根叙事节点")

        # 检查身份状态一致性
        root_data = topology.graph.nodes[root_id]
        identity_state = root_data.get("identity_state", {})

        if identity_state:
            self_name = identity_state.get("self_name")
            other_name = identity_state.get("other_name")

            # 检查是否有矛盾的身份声明
            if self_name and identity_state.get("self_conf", 0) < 0.5:
                issues_found.append(f"自我名称「{self_name}」置信度不足，需要更多对话确认")

            if other_name and identity_state.get("other_conf", 0) < 0.5:
                issues_found.append(f"对方名称「{other_name}」置信度不足，需要更多对话确认")

        # 检查叙事连贯性：根节点到叶子节点是否存在路径
        out_edges = list(topology.graph.out_edges(root_id))
        if len(out_edges) == 0:
            issues_found.append("自传体叙事结构不完整，根节点没有出边")

        return TaskResult(
            success=True,
            changes_count=0,
            issues_found=issues_found,
            message=f"检查完成，发现 {len(issues_found)} 个叙事一致性问题"
        )