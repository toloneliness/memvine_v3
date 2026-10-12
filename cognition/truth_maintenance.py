"""
真值维护系统 (Truth Maintenance System)
- 冲突检测：新关系与图中已有关系是否矛盾
- 信念修正：冲突时基于权重、时间决定保留哪个
- 级联标记：被推翻的信念下游依赖标记为待验证
"""


class ConflictType:
    CONTRADICTION = "contradiction"       # 同向互斥边
    REVERSAL = "reversal"                 # 反向边（A→B 变成 B→A）
    ATTRIBUTION = "attribution"           # 名字归属冲突
    FACT_CLASH = "fact_clash"             # 事实矛盾


CONTRADICTORY_PAIRS = {
    ("trusts", "distrusts"),
    ("likes", "dislikes"),
    ("loves", "hates"),
    ("admires", "despises"),
    ("grateful_to", "angry_at"),
    ("trusts", "angry_at"),
    ("likes", "angry_at"),
}


class Conflict:
    def __init__(self, source: str, target: str, new_relation: str,
                 old_relation: str, old_weight: float, new_weight: float,
                 conflict_type: str):
        self.source = source
        self.target = target
        self.new_relation = new_relation
        self.old_relation = old_relation
        self.old_weight = old_weight
        self.new_weight = new_weight
        self.conflict_type = conflict_type
        self.resolution = None  # "keep_new", "keep_old", "merge", "ask_llm"


class TruthMaintenance:
    def __init__(self, topology):
        self.topology = topology
        self.conflict_log = []

    def check(self, source: str, target: str, relation: str, weight: float) -> Conflict | None:
        """检查新边是否与已有边冲突"""
        if not self.topology.graph.has_node(source) or not self.topology.graph.has_node(target):
            return None

        existing = self.topology.graph.get_edge_data(source, target)
        if existing:
            old_rel = existing.get("relation", "")
            old_weight = existing.get("weight", 1.0)
            pair = tuple(sorted([old_rel, relation]))
            if pair in CONTRADICTORY_PAIRS and old_rel != relation:
                return Conflict(source, target, relation, old_rel, old_weight, weight,
                                ConflictType.CONTRADICTION)

        reverse = self.topology.graph.get_edge_data(target, source)
        if reverse:
            old_rel = reverse.get("relation", "")
            old_weight = reverse.get("weight", 1.0)
            return Conflict(source, target, relation, old_rel, old_weight, weight,
                            ConflictType.REVERSAL)

        return None

    def resolve(self, conflict: Conflict) -> str:
        """基于权重和时间自动决策"""
        if conflict.new_weight >= conflict.old_weight * 2:
            conflict.resolution = "keep_new"
        elif conflict.old_weight >= conflict.new_weight * 3:
            conflict.resolution = "keep_old"
        else:
            conflict.resolution = "ask_llm"
        return conflict.resolution

    def apply(self, conflict: Conflict):
        """执行修正"""
        if conflict.resolution == "keep_new":
            if self.topology.graph.has_edge(conflict.source, conflict.target):
                self.topology.graph.remove_edge(conflict.source, conflict.target)
            if self.topology.graph.has_edge(conflict.target, conflict.source):
                self.topology.graph.remove_edge(conflict.target, conflict.source)
            self.topology.connect(conflict.source, conflict.target,
                                  weight=conflict.new_weight,
                                  relation=conflict.new_relation)
            self._mark_downstream(conflict.source, conflict.target)

        elif conflict.resolution == "keep_old":
            pass

        elif conflict.resolution == "ask_llm":
            paradox_id = self._create_paradox_node(conflict)
            self.topology.graph.add_edge(
                conflict.source, conflict.target,
                weight=conflict.new_weight * 0.5,
                relation=conflict.new_relation,
                pending_resolution=True,
                paradox_ref=paradox_id,
            )

        self.conflict_log.append(conflict)

    def _mark_downstream(self, source: str, target: str):
        """标记被推翻边的下游节点为待验证"""
        for _, downstream, data in self.topology.graph.out_edges(target, data=True):
            data["needs_revalidation"] = True

    def _create_paradox_node(self, conflict: Conflict) -> str:
        """创建悖论节点：不裁决矛盾，而是保留张力作为高阶认知事件。"""
        import uuid
        paradox_id = f"paradox_{uuid.uuid4().hex[:8]}"

        self.topology.graph.add_node(
            paradox_id,
            node_type="paradox",
            source=conflict.source,
            target=conflict.target,
            relation_a=conflict.old_relation,
            relation_b=conflict.new_relation,
            weight_a=conflict.old_weight,
            weight_b=conflict.new_weight,
            conflict_type=conflict.conflict_type,
            summary=f"悖论: {conflict.source} --[{conflict.old_relation} vs {conflict.new_relation}]--> {conflict.target}",
        )

        self.topology.connect(paradox_id, conflict.source, relation="involves", weight=1.0)
        self.topology.connect(paradox_id, conflict.target, relation="involves", weight=1.0)

        print(f"   [悖论] 🔀 {paradox_id}: 保留矛盾而不裁决")
        return paradox_id