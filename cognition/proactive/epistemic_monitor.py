# cognition/proactive/epistemic_monitor.py
"""认知边界感知（B+C路径）—— LLM 评估 + 图密度推断，感知"我懂不懂" """

from dataclasses import dataclass, field
from enum import Enum
import time

class EpistemicState(Enum):
    VOID = "void"               # 完全未知：图中无节点，LLM 也无相关知识
    FRAGMENTARY = "fragmentary" # 碎片：有少量节点，但密度极低
    AWARE = "aware"             # 有感知：有一定节点，但未形成社区
    COHERENT = "coherent"       # 连贯：有社区，边密度中等
    CONFIDENT = "confident"     # 自信：高密度多社区

    @classmethod
    def from_density(cls, density: float, community_count: int) -> "EpistemicState":
        """根据图密度和社区数推断认知状态"""
        if density == 0.0:
            return cls.VOID
        if density < 0.15:
            return cls.FRAGMENTARY
        if community_count == 0:
            return cls.AWARE
        if density < 0.4:
            return cls.COHERENT
        return cls.CONFIDENT

@dataclass
class DomainState:
    domain_label: str
    state: EpistemicState
    node_count: int
    edge_count: int
    community_count: int
    density: float
    last_assessed: float = field(default_factory=time.time)

class EpistemicMonitor:
    """认知边界感知：结合 LLM 判断 + 图密度推断"""

    def __init__(self):
        self._domains: dict[str, DomainState] = {}
        self._recent_assessments: list[dict] = []

    def assess_from_llm(self, llm_result: dict) -> dict:
        """从 LLM 的 _extract_semantic 扩展结果中提取认知状态"""
        epistemic_gap = llm_result.get("epistemic_gap", False)
        gap_domain = llm_result.get("gap_domain", "")
        gap_confidence = llm_result.get("gap_confidence", 0.0)
        gap_type = llm_result.get("gap_type", "unrecorded")

        return {
            "has_gap": epistemic_gap,
            "domain": gap_domain,
            "confidence": gap_confidence,
            "gap_type": gap_type,  # "unrecorded" | "ignorant" | "known"
        }

    def assess_from_graph(self, entity: str, topology) -> DomainState:
        """从图密度推断认知状态（C路径）"""
        nid = None
        for node_id, attrs in topology.graph.nodes(data=True):
            if attrs.get("entity_name") == entity:
                nid = node_id
                break

        if not nid:
            return DomainState(
                domain_label=entity, state=EpistemicState.VOID,
                node_count=0, edge_count=0, community_count=0, density=0.0,
            )

        # 获取 2 跳子图
        neighbors = set()
        for u, v in topology.graph.edges(nid):
            neighbors.add(v if u == nid else u)
        for nb in list(neighbors):
            for u, v in topology.graph.edges(nb):
                neighbors.add(v if u == nb else u)

        sub_nodes = {nid} | neighbors
        sub_nodes = {n for n in sub_nodes if topology.graph.has_node(n)}
        subgraph = topology.graph.subgraph(list(sub_nodes))

        node_count = subgraph.number_of_nodes()
        edge_count = subgraph.number_of_edges()
        max_possible = node_count * (node_count - 1) / 2
        density = edge_count / max_possible if max_possible > 0 else 0.0

        communities = topology.community_detect()
        community_count = sum(
            1 for c in communities
            if any(m["node_id"] in sub_nodes for m in c.get("members", []))
        )

        state = EpistemicState.from_density(density, community_count)

        ds = DomainState(
            domain_label=entity, state=state,
            node_count=node_count, edge_count=edge_count,
            community_count=community_count, density=density,
        )
        self._domains[entity] = ds
        return ds

    def combine(self, llm_assessment: dict, graph_state: DomainState) -> EpistemicState:
        """融合 LLM 判断和图密度推断

        修正两条路径：
        - LLM 悲观 (ignorant/unrecorded) + 图丰富 → 上调（原逻辑）
        - LLM 乐观 (known) + 图贫瘠 → 下调（新增，修补 false confidence）
        """
        gap_type = llm_assessment.get("gap_type", "known")

        if gap_type == "ignorant":
            return EpistemicState.VOID
        if gap_type == "unrecorded":
            if graph_state.state == EpistemicState.VOID:
                return EpistemicState.FRAGMENTARY
            return graph_state.state

        # LLM 说 known → 不信任：如果图密度为 0，下调为 FRAGMENTARY
        if gap_type == "known":
            if graph_state.state in (EpistemicState.VOID, EpistemicState.FRAGMENTARY):
                return EpistemicState.FRAGMENTARY

        return graph_state.state

    def track_topic_stay(self, entity: str, round_count: int, state: EpistemicState) -> bool:
        """判断是否陷入话题陷阱"""
        if round_count >= 3 and state in (EpistemicState.VOID, EpistemicState.FRAGMENTARY):
            return True
        if round_count >= 5 and state == EpistemicState.AWARE:
            return True
        return False

    def get_domain_summary(self) -> list[dict]:
        return [
            {"domain": d.domain_label, "state": d.state.value,
             "nodes": d.node_count, "density": round(d.density, 3)}
            for d in sorted(self._domains.values(),
                          key=lambda x: x.density)
        ]