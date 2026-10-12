from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class GraphSummarizationTask(BaseMaintenanceTask):
    """第三层任务：图摘要 - 将琐碎的日常记忆压缩成摘要节点"""

    @property
    def name(self) -> str:
        return "graph_summarization"

    @property
    def layer(self) -> int:
        return 3

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.HARD_WRITE

    @property
    def required_capabilities(self) -> List[str]:
        return ["summarize", "hierarchical_clustering"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        summary_result = topology.summarize(target_groups=5)
        super_nodes = summary_result.get("super_nodes", [])

        changes_count = 0
        changes_made = {}
        merged_topics = []

        import uuid
        now_ts = topology.clock.now_ts() if hasattr(topology, 'clock') else None
        for super_node in super_nodes:
            members = super_node.get("members", [])
            size = super_node.get("size", 0)
            if size >= 3:
                label = super_node.get("label", "")
                merged_topics.append(f"{label} ({size}条)")
                summary_id = f"summary_{uuid.uuid4().hex[:8]}"
                contents = []
                for m in members:
                    nid = m.get("node_id", "")
                    if topology.graph.has_node(nid):
                        nd = topology.graph.nodes[nid]
                        contents.append(str(nd.get("data", {}).get("content", ""))[:80])
                        topology.graph.remove_node(nid)
                        changes_count += 1
                topology.graph.add_node(summary_id, node_type="summary", label=label,
                    summary="；".join(contents[:10]), member_count=size,
                    born_at=now_ts)
                changes_count -= size - 1

        changes_made["merged_groups"] = merged_topics

        return TaskResult(
            success=True,
            changes_count=changes_count,
            changes_made=changes_made,
            message=f"完成图摘要，合并 {len(merged_topics)} 组琐碎记忆，减少 {changes_count} 个节点"
        )