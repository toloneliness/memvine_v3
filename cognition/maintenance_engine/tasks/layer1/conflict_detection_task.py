from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class ConflictDetectionTask(BaseMaintenanceTask):
    """第一层任务：冲突检测 - 发现自相矛盾的记忆"""

    @property
    def name(self) -> str:
        return "conflict_detection"

    @property
    def layer(self) -> int:
        return 1

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.READ_ONLY

    @property
    def required_capabilities(self) -> List[str]:
        return ["detect_anomalies"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        result = topology.detect_anomalies(z_threshold=2.0)
        suspicious = result.get("suspicious_nodes", [])

        issues_found = []
        for node in suspicious[:10]:
            content = node.get("content", "")[:60]
            score = node.get("anomaly_score", 0)
            issues_found.append(f"发现异常节点：「{content}...」(异常得分 {score:.2f})")

        return TaskResult(
            success=True,
            changes_count=0,
            issues_found=issues_found,
            message=f"检测到 {len(suspicious)} 个异常节点"
        )