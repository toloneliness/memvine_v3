from ...base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from physics.topology import TopologyEngine
from typing import Dict, List

class PatternRecognitionTask(BaseMaintenanceTask):
    """第二层任务：模式识别 - 发现重复出现的子图模式，固化为认知脚本"""

    @property
    def name(self) -> str:
        return "pattern_recognition"

    @property
    def layer(self) -> int:
        return 2

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.SOFT_WRITE

    @property
    def required_capabilities(self) -> List[str]:
        return ["detect_motifs"]

    def execute(self, topology: TopologyEngine, config: Dict[str, any]) -> TaskResult:
        result = topology.detect_motifs()
        patterns = result.get("frequent_patterns", [])
        interpretations = result.get("interpretation", [])

        changes_count = 0
        issues_found = []

        for pattern in patterns:
            if pattern.get("count", 0) >= 2:
                pattern_relations = pattern.get("pattern", [])
                count = pattern.get("count", 0)
                pattern_key = " → ".join(pattern_relations)
                issues_found.append(
                    f"识别出重复模式：{pattern_key}，出现 {count} 次，已标记为认知脚本候选"
                )
                # 真正写入认知脚本
                topology.register_cognitive_script(
                    pattern=pattern_relations,
                    count=count,
                    interpretation=interpretations[0] if interpretations and len(interpretations) > 0 else "",
                )
                changes_count += 1

        for interp in interpretations:
            issues_found.append(interp)

        return TaskResult(
            success=True,
            changes_count=changes_count,
            issues_found=issues_found,
            message=f"识别出 {len(patterns)} 个重复认知脚本模式"
        )