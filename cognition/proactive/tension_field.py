# cognition/proactive/tension_field.py
"""认知张力场 —— 维护扫描结果在此沉淀为"不安"，达到阈值后触发主动行为"""

from dataclasses import dataclass, field
from collections import deque
import time

@dataclass
class TensionNode:
    """张力节点：一个认知上的"不安点" """
    node_id: str
    tension_type: str          # conflict / gap / decay / inconsistency / pattern
    description: str
    source_task: str           # 产生此张力的维护任务名
    tension: float = 0.3       # 当前张力值 [0.0, 1.0]
    triggered_count: int = 0   # 已触发主动行为的次数
    clock: object = None       # 由 TensionField 注入

    def __post_init__(self):
        if self.clock is None:
            self.created_at = time.time()
            self.last_updated = time.time()
        else:
            self.created_at = self.clock.now_ts()
            self.last_updated = self.clock.now_ts()

    def _now(self) -> float:
        return self.clock.now_ts() if self.clock else time.time()

    def escalate(self, delta: float = 0.1):
        """张力自然增长"""
        self.tension = min(1.0, self.tension + delta)
        self.last_updated = self._now()

    def release(self, amount: float = 0.5):
        """释放张力（用户回应后）"""
        self.tension = max(0.0, self.tension - amount)
        self.last_updated = self._now()
        self.triggered_count += 1

    def decay(self, factor: float):
        """自然衰减"""
        self.tension *= factor
        self.last_updated = self._now()

    def is_hot(self, threshold: float = 0.7) -> bool:
        return self.tension >= threshold

@dataclass
class Hotspot:
    """热点聚合：多个张力节点围绕同一实体的聚合视图"""
    entity: str
    tensions: list[TensionNode]
    combined_tension: float = 0.0

    def __post_init__(self):
        if self.tensions:
            self.combined_tension = sum(t.tension for t in self.tensions) / len(self.tensions)

class TensionField:
    """认知张力场：管理所有张力节点，提供 Hotspot 聚合"""

    def __init__(self, decay_half_life: float = 3600.0, max_nodes: int = 50, clock=None):
        self._nodes: dict[str, TensionNode] = {}
        self.decay_half_life = decay_half_life
        self.max_nodes = max_nodes
        self.clock = clock
        self._history: deque = deque(maxlen=100)

    def inject(self, node_id: str, tension_type: str, description: str,
               source_task: str = "", initial_tension: float = 0.3) -> TensionNode:
        """注入一个新张力或增强已有张力"""
        if node_id in self._nodes:
            existing = self._nodes[node_id]
            existing.escalate(0.15)
            existing.description = description
            existing.source_task = source_task
            return existing

        if len(self._nodes) >= self.max_nodes:
            self._evict_coldest()

        node = TensionNode(
            node_id=node_id,
            tension_type=tension_type,
            description=description,
            source_task=source_task,
            tension=initial_tension,
            clock=self.clock,
        )
        self._nodes[node_id] = node
        self._history.append(("inject", node_id, tension_type, initial_tension))
        return node

    def get_hotspots(self, threshold: float = 0.7) -> list[Hotspot]:
        """获取所有超过阈值的张力热点"""
        hot = [n for n in self._nodes.values() if n.is_hot(threshold)]
        if not hot:
            return []

        groups: dict[str, list[TensionNode]] = {}
        for n in hot:
            key = n.node_id.split("_")[0] if "_" in n.node_id else n.node_id
            groups.setdefault(key, []).append(n)

        return [Hotspot(entity=k, tensions=v) for k, v in groups.items()
                if len(v) > 0]

    def needs_action(self, threshold: float = 0.7) -> list[str]:
        """返回张力超过阈值、需要行动的节点ID列表"""
        return [nid for nid, n in self._nodes.items() if n.is_hot(threshold)]

    def release(self, node_id: str, amount: float = 0.5):
        if node_id in self._nodes:
            self._nodes[node_id].release(amount)
            self._history.append(("release", node_id, amount))

    def apply_natural_decay(self):
        """应用自然衰减"""
        now = self.clock.now_ts() if self.clock else time.time()
        to_remove = []
        for nid, node in self._nodes.items():
            elapsed = now - node.last_updated
            if elapsed > 0:
                factor = 0.5 ** (elapsed / self.decay_half_life)
                node.decay(factor)
            if node.tension < 0.05 and node.triggered_count > 0:
                to_remove.append(nid)
        for nid in to_remove:
            del self._nodes[nid]

    def _evict_coldest(self):
        if not self._nodes:
            return
        coldest = min(self._nodes, key=lambda k: self._nodes[k].tension)
        del self._nodes[coldest]

    def summary(self) -> dict:
        return {
            "total_nodes": len(self._nodes),
            "hotspots": len(self.get_hotspots()),
            "top_tensions": sorted(
                [{"id": nid, "type": n.tension_type, "tension": round(n.tension, 2),
                  "desc": n.description[:60]}
                 for nid, n in self._nodes.items()],
                key=lambda x: x["tension"], reverse=True
            )[:5],
        }