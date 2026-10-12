from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class CommunityReorganizationTask(BaseMaintenanceTask):
    """第二层任务：社区重组 - 将新节点分配到对应社区，不触发全图重新聚类"""

    @property
    def name(self) -> str:
        return "community_reorganization"

    @property
    def layer(self) -> int:
        return 2

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.SOFT_WRITE

    @property
    def required_capabilities(self) -> List[str]:
        return ["community_detect"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        # 检查是否已有社区分配
        any_has_community = False
        unassigned_count = 0

        for node_id in topology.graph.nodes():
            data = topology.graph.nodes[node_id]
            if "community_id" in data:
                any_has_community = True
            else:
                # 跳过实体节点和根节点
                if not node_id.startswith("entity_") and node_id != "root":
                    unassigned_count += 1

        if not any_has_community:
            # 还没有任何社区分配，执行一次完整社区发现
            communities = topology.community_detect()
            changes_count = 0
            for comm in communities:
                for member in comm["members"]:
                    if "node_id" in member:
                        nid = member["node_id"]
                        if topology.graph.has_node(nid):
                            topology.graph.nodes[nid]["community_id"] = comm["community_id"]
                            changes_count += 1

            return TaskResult(
                success=True,
                changes_count=changes_count,
                message=f"首次社区分配：{len(communities)}个社区，{changes_count}个节点"
            )

        communities = topology.community_detect()
        changes_count = 0
        for nid in topology.graph.nodes():
            if topology.graph.nodes[nid].get("community_id") is not None:
                continue
            if nid.startswith("entity_") or nid == "root":
                continue
            neighbors = list(topology.graph.neighbors(nid))
            if not neighbors:
                continue
            neighbor_communities = {}
            for nb in neighbors:
                cid = topology.graph.nodes[nb].get("community_id")
                if cid is not None:
                    neighbor_communities[cid] = neighbor_communities.get(cid, 0) + 1
            if neighbor_communities:
                best_cid = max(neighbor_communities, key=neighbor_communities.get)
                topology.graph.nodes[nid]["community_id"] = best_cid
                changes_count += 1

        return TaskResult(
            success=True,
            changes_count=changes_count,
            message=f"增量分配 {changes_count} 个节点到已有社区，{unassigned_count - changes_count} 个仍待第三层处理"
        )