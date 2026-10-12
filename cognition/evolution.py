# cognition/evolution.py

import pendulum
from config import (
    SILENCE_DURATION_SECONDS, NEGATIVE_VALENCE_THRESHOLD
)


class EvolutionEngine:
    """
    进化引擎：掌管数字生命体的内观收敛（反刍）、静默期与自我重塑。
    """
    def __init__(self, clock=None):
        self.clock = clock
        self.is_silent = False
        self.silence_end_time = None
        self.silence_start_ts = None
        self.silence_end_ts = None

        self.SILENCE_DURATION_TICKS = SILENCE_DURATION_SECONDS
        self.NEGATIVE_VALENCE_THRESHOLD = NEGATIVE_VALENCE_THRESHOLD

    def tick_silence(self):
        if self.is_silent and self.silence_end_ts:
            if self.clock.now_ts() >= self.silence_end_ts:
                self.is_silent = False
                self.silence_end_time = None
                return True
        return False

    def start_convergence(self, cortex):
        if self.is_silent:
            return

        print("🌌 [内观收敛] 感知闭锁。开始系统级重组...")

        self.is_silent = True
        self.silence_start_ts = self.clock.now_ts()
        self.silence_end_ts = self.clock.now_ts() + self.SILENCE_DURATION_TICKS

        topology = cortex.topology

        nodes_to_remove = []
        ego_id = topology.find_root_node()

        for node_id, attrs in topology.graph.nodes(data=True):
            if node_id == ego_id:
                continue
            node_data = attrs.get("data", {})
            valence = node_data.get("valence", 0.0)
            if valence < self.NEGATIVE_VALENCE_THRESHOLD:
                nodes_to_remove.append(node_id)

        for node_id in nodes_to_remove:
            topology.graph.remove_node(node_id)

        if nodes_to_remove:
            print(f"   🗑️ [拓扑修剪] 消化 {len(nodes_to_remove)} 个脆弱记忆。")

        catalyst_count = cortex.catalyst.run()
        if catalyst_count > 0:
            print(f"   🔥 [内观] 火种生成 {catalyst_count} 条假设")

        bootstrapped = 0
        if cortex.bootstrapper.should_bootstrap([]):
            communities = topology.community_detect()
            topics = [c.get("label", "") for c in communities[:3] if c.get("label")]
            if topics:
                bootstrapped = cortex.bootstrapper.bootstrap(topics, depth=1)
                print(f"   🌱 [内观] 知识骨架填充 {bootstrapped} 项")

        if not nodes_to_remove and catalyst_count == 0 and bootstrapped == 0:
            print("   [保底] 未找到可优化点，静默状态将自动解除。")
        print("🌌 [内观收敛] 重组完成。进入静默冷却期...")