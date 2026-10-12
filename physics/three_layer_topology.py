"""
三层记忆图拓扑引擎。
知识网 (knowledge) | 身份关系 (identity) | 时间链 (timeline)
三个子图共享节点，边类型不同，检索时互不污染。
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set

@dataclass
class TypedTrace:
    source_id: str
    target_id: str
    edge_type: str
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)

class ThreeLayerTopology:
    def __init__(self):
        self.traces: Dict[str, TypedTrace] = {}
        self.identity_state = {
            "self_name": None,
            "other_name": None,
            "self_name_counts": {},
            "other_name_counts": {},
            "self_name_conf": 0.0,
            "other_name_conf": 0.0,
        }

    def _key(self, source: str, target: str, edge_type: str) -> str:
        return f"{source}->{target}::{edge_type}"

    def strengthen_or_create(self, source: str, target: str, edge_type: str,
                              metadata: Dict = None) -> TypedTrace:
        key = self._key(source, target, edge_type)
        if key in self.traces:
            self.traces[key].weight += 1.0
            if metadata:
                self.traces[key].metadata.update(metadata)
        else:
            self.traces[key] = TypedTrace(source, target, edge_type, 1.0,
                                           metadata=metadata or {})
        return self.traces[key]

    def subgraph(self, edge_type: str) -> List[TypedTrace]:
        return [t for t in self.traces.values() if t.edge_type == edge_type]

    def get_neighbors(self, node_id: str, edge_type: str = None) -> List[Tuple[str, float, str]]:
        neighbors = []
        for t in self.traces.values():
            if edge_type and t.edge_type != edge_type:
                continue
            if t.source_id == node_id:
                neighbors.append((t.target_id, t.weight, t.edge_type))
            elif t.target_id == node_id:
                neighbors.append((t.source_id, t.weight, t.edge_type))
        neighbors.sort(key=lambda x: x[1], reverse=True)
        return neighbors

    def spread_activation(self, start_node: str, edge_type: str, depth: int = 2,
                           exclude_nodes: Set[str] = None) -> Dict[str, float]:
        if exclude_nodes is None:
            exclude_nodes = set()
        activated: Dict[str, float] = {start_node: 1.0}
        visited: Set[str] = exclude_nodes | {start_node}
        for d in range(depth):
            new_frontier: Dict[str, float] = {}
            for node, energy in activated.items():
                for t in self.traces.values():
                    if t.edge_type != edge_type:
                        continue
                    if t.source_id == node and t.target_id not in visited:
                        new_energy = energy * 0.6 * t.weight
                        new_frontier[t.target_id] = new_frontier.get(t.target_id, 0) + new_energy
                        visited.add(t.target_id)
                    elif t.target_id == node and t.source_id not in visited:
                        new_energy = energy * 0.6 * t.weight
                        new_frontier[t.source_id] = new_frontier.get(t.source_id, 0) + new_energy
                        visited.add(t.source_id)
            activated = new_frontier
        return activated

    def update_identity(self, self_claims: Dict[str, int] = None,
                        other_claims: Dict[str, int] = None):
        if self_claims:
            for name, cnt in self_claims.items():
                self.identity_state["self_name_counts"][name] = (
                    self.identity_state["self_name_counts"].get(name, 0) + cnt)
            total = sum(self.identity_state["self_name_counts"].values())
            if total > 0:
                best = max(self.identity_state["self_name_counts"],
                          key=self.identity_state["self_name_counts"].get)
                self.identity_state["self_name"] = best
                self.identity_state["self_name_conf"] = round(
                    self.identity_state["self_name_counts"][best] / total, 2)
        if other_claims:
            for name, cnt in other_claims.items():
                self.identity_state["other_name_counts"][name] = (
                    self.identity_state["other_name_counts"].get(name, 0) + cnt)
            total = sum(self.identity_state["other_name_counts"].values())
            if total > 0:
                best = max(self.identity_state["other_name_counts"],
                          key=self.identity_state["other_name_counts"].get)
                self.identity_state["other_name"] = best
                self.identity_state["other_name_conf"] = round(
                    self.identity_state["other_name_counts"][best] / total, 2)

    @property
    def stats(self) -> Dict:
        nodes = set()
        for t in self.traces.values():
            nodes.add(t.source_id)
            nodes.add(t.target_id)
        timeline = sum(1 for t in self.traces.values() if t.edge_type == "timeline")
        identity = sum(1 for t in self.traces.values() if t.edge_type == "identity")
        knowledge = sum(1 for t in self.traces.values() if t.edge_type == "knowledge")
        return {
            "node_count": len(nodes),
            "edge_count": len(self.traces),
            "timeline_edges": timeline,
            "identity_edges": identity,
            "knowledge_edges": knowledge,
        }

    def to_dict(self) -> Dict:
        return {
            "traces": [
                {
                    "source_id": t.source_id,
                    "target_id": t.target_id,
                    "edge_type": t.edge_type,
                    "weight": t.weight,
                    "metadata": t.metadata,
                }
                for t in self.traces.values()
            ],
            "identity_state": self.identity_state,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ThreeLayerTopology":
        topo = cls()
        if "identity_state" in d:
            topo.identity_state = d["identity_state"]
        traces_data = d.get("traces", {})
        if isinstance(traces_data, dict):
            traces_data = traces_data.values()
        for t in traces_data:
            source_id = t["source_id"]
            target_id = t["target_id"]
            edge_type = t.get("edge_type", t.get("relation", "knowledge"))
            weight = float(t.get("weight", t.get("flow_count", 1.0)))
            metadata = t.get("metadata") or {}
            key = topo._key(source_id, target_id, edge_type)
            if key in topo.traces:
                topo.traces[key].weight += weight
            else:
                topo.traces[key] = TypedTrace(source_id, target_id, edge_type, weight, metadata=metadata)
        return topo