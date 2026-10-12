# cognition/memory_retriever.py

import time
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from config import (
    MEMORY_TYPE_WEIGHTS, RECENCY_BONUS_DAYS, RECENCY_BONUS_VALUE, BASE_RELEVANCE_DECAY
)
from cognition.intent_manifest import INTENT_MANIFEST as _MANIFEST

@dataclass(order=False)
class MemoryNode:
    """
    结构化记忆节点：携带认知元数据的记忆单元。
    检索器返回此对象，ContextManager 按 score 排序后进行漏斗过滤。
    """
    text: str
    score: float
    hops: int
    depth: int
    mem_type: str = "daily_chat"
    node_id: str = ""
    raw_data: dict = field(default_factory=dict)
    source: str = ""

    def __lt__(self, other):
        return self.score < other.score

class RetrievalStrategy(ABC):
    """图驱动检索策略基类：图算法即检索引擎。"""

    def __init__(self, topology, clock=None):
        self.topology = topology
        self.clock = clock

    @abstractmethod
    def retrieve(self, query: str, entities: list[str], kinetic_budget: float, current_time_ts: float) -> list[MemoryNode]:
        pass

    def _classify_memory(self, node_id: str, node_attrs: dict) -> str:
        node_data = node_attrs.get("data", {}) if isinstance(node_attrs, dict) else {}
        llm_type = node_data.get("mem_type", "")
        if llm_type and llm_type != "daily_chat":
            return llm_type
        for _, _, edge_data in self.topology.graph.in_edges(node_id, data=True):
            if edge_data.get("relation", "").startswith("identity_"):
                return "identity"
        for _, _, edge_data in self.topology.graph.out_edges(node_id, data=True):
            if edge_data.get("relation", "").startswith("identity_"):
                return "identity"
        source = node_data.get("source", "")
        if source == "identity":
            return "identity"
        valence = abs(node_data.get("valence", 0.0))
        if valence > 5.0:
            return "deep_emotion"
        return "daily_chat"

    def _calculate_score(self, node_id: str, node_attrs: dict, depth: int, current_time_ts: float) -> float:
        node_data = node_attrs.get("data", {}) if isinstance(node_attrs, dict) else {}
        base_relevance = max(BASE_RELEVANCE_DECAY, 1.0 - depth * 0.15)
        mem_type = self._classify_memory(node_id, node_attrs)
        type_weight = MEMORY_TYPE_WEIGHTS.get(mem_type, 0.8)
        last_activated = node_data.get("last_activated", current_time_ts)
        days_since_activation = (current_time_ts - last_activated) / 86400.0
        if days_since_activation < RECENCY_BONUS_DAYS:
            recency_multiplier = 1.0 + RECENCY_BONUS_VALUE * (1.0 - days_since_activation / RECENCY_BONUS_DAYS)
        else:
            recency_multiplier = 1.0
        valence = abs(node_data.get("valence", 0.0))
        valence_boost = min(valence / 20.0, 0.3)
        identity_boost = 0.0
        if self.topology:
            for _, neighbor, data in self.topology.graph.out_edges(node_id, data=True):
                rel = data.get("relation", "")
                if rel in ("SELF_CLAIM", "LABELED_BY", "has_name", "identity_of"):
                    identity_boost = 0.15
                    break
        final_score = base_relevance * type_weight * recency_multiplier + valence_boost + identity_boost
        return round(final_score, 4)

    def _to_memory_node(self, node_id: str, node_attrs: dict, depth: int, hops: int, current_time_ts: float) -> MemoryNode:
        node_type = node_attrs.get("node_type", "")
        if node_type == "entity":
            content = node_attrs.get("entity_name", str(node_attrs))
            mem_type = "entity"
            source = ""
        else:
            node_data = node_attrs.get("data", {}) if isinstance(node_attrs, dict) else {}
            content = node_data.get("content", "") if node_data else str(node_attrs)
            mem_type = self._classify_memory(node_id, node_attrs)
            source = node_data.get("source", "") if node_data else ""
        score = self._calculate_score(node_id, node_attrs, depth, current_time_ts)
        return MemoryNode(
            text=content, score=score, hops=hops, depth=depth,
            mem_type=mem_type, node_id=node_id, raw_data=node_attrs, source=source
        )

    def _locate_anchors(self, entities: list[str], max_anchors: int = 5) -> list[str]:
        anchors = []
        G = self.topology.graph
        for node_id in G.nodes:
            node_type = G.nodes[node_id].get("node_type", "")
            if node_type == "entity":
                continue
            node_data = G.nodes[node_id].get("data", {})
            if not isinstance(node_data, dict):
                continue
            source = (node_data.get("source") or "")
            if source.startswith("self"):
                continue
            content = (node_data.get("content") or "").lower()
            target = (node_data.get("target") or "").lower()
            action = (node_data.get("action") or "").lower()
            topic = (node_data.get("topic") or "").lower()
            for ent in entities:
                ent_low = ent.lower()
                if ent_low in content or ent_low in target or ent_low in action or ent_low in topic:
                    anchors.append(node_id)
                    break
            if len(anchors) >= max_anchors:
                break
        if not anchors:
            for node_id in G.nodes:
                node_type = G.nodes[node_id].get("node_type", "")
                if node_type == "entity":
                    ename = (G.nodes[node_id].get("entity_name") or "").lower()
                    for ent in entities:
                        if ent.lower() in ename:
                            anchors.append(node_id)
                            break
                if len(anchors) >= max_anchors or len(anchors) >= len(entities):
                    break
        # 子图感知：命中子图实体时，补拉同子图的其他实体
        expanded = []
        for aid in anchors:
            sg = G.nodes[aid].get("subgraph", "")
            if sg:
                for nid, attrs in G.nodes(data=True):
                    if attrs.get("subgraph") == sg and attrs.get("node_type") == "entity":
                        if nid not in anchors and nid not in expanded:
                            expanded.append(nid)
                        if len(expanded) >= 3:
                            break
        anchors.extend(expanded)

        return anchors


class AnchorWalkStrategy(RetrievalStrategy):
    """锚点游走策略：从 query 实体锚点出发，Personalized PageRank 扩散检索。"""

    def retrieve(self, query: str, entities: list[str], kinetic_budget: float, current_time_ts: float) -> list[MemoryNode]:
        anchors = self._locate_anchors(entities)
        if not anchors:
            root = self.topology.find_root_node()
            if root:
                anchors = [root]
            else:
                return []

        ppr_scores = self._personalized_pagerank(anchors, alpha=0.85, max_iter=20)

        top_k = min(int(kinetic_budget) + 5, 30)
        ranked = sorted(ppr_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        hops = 0
        for node_id, ppr_val in ranked:
            node_attrs = self.topology.get_node_data(node_id)
            if not node_attrs:
                continue
            depth = self._estimate_depth_from_ppr(ppr_val)
            mn = self._to_memory_node(node_id, node_attrs, depth, hops, current_time_ts)
            mn.score = round(mn.score * (0.5 + ppr_val), 4)
            results.append(mn)
            hops += 1
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _personalized_pagerank(self, seed_nodes: list[str], alpha: float = 0.85, max_iter: int = 20) -> dict[str, float]:
        G = self.topology.graph
        if G.number_of_nodes() == 0:
            return {}
        nodes = list(G.nodes)
        n = len(nodes)

        personalization = {}
        for seed in seed_nodes:
            if seed in G.nodes:
                personalization[seed] = 1.0
        if not personalization:
            return {nid: 1.0 / n for nid in nodes}
        total_p = sum(personalization.values())
        personalization = {k: v / total_p for k, v in personalization.items()}

        rank = {nid: personalization.get(nid, 0.0) for nid in nodes}

        for _ in range(max_iter):
            new_rank = {nid: (1 - alpha) * personalization.get(nid, 0.0) for nid in nodes}
            for u, v, data in G.edges(data=True):
                w = data.get("weight", 1.0)
                out_degree = G.out_degree(u)
                if out_degree > 0:
                    contribution = alpha * rank[u] * w / out_degree
                    new_rank[v] += contribution
            diff = sum(abs(new_rank[nid] - rank[nid]) for nid in nodes)
            rank = new_rank
            if diff < 1e-6:
                break

        total = sum(rank.values())
        if total > 0:
            rank = {k: v / total for k, v in rank.items()}
        return {k: round(v, 6) for k, v in rank.items() if v > 1e-5}

    def _estimate_depth_from_ppr(self, ppr_val: float) -> int:
        if ppr_val > 0.1:
            return 1
        elif ppr_val > 0.05:
            return 2
        elif ppr_val > 0.02:
            return 3
        else:
            return 4


class CausalChainStrategy(RetrievalStrategy):
    """因果链策略：沿因果/时序边回溯和前推，发现因果路径上的记忆。"""

    def retrieve(self, query: str, entities: list[str], kinetic_budget: float, current_time_ts: float) -> list[MemoryNode]:
        anchors = self._locate_anchors(entities, max_anchors=3)
        if not anchors:
            return []

        results = []
        visited = set()
        hops = 0

        for anchor in anchors:
            queue = [(anchor, 0)]
            while queue:
                current, depth = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                hops += 1

                node_attrs = self.topology.get_node_data(current)
                if node_attrs and current != self.topology.find_root_node():
                    mn = self._to_memory_node(current, node_attrs, depth, hops, current_time_ts)
                    mn.score = round(mn.score * 1.3, 4)
                    results.append(mn)

                for _, target, data in self.topology.graph.out_edges(current, data=True):
                    rel = data.get("relation", "")
                    if rel in ("caused", "happened_before", "implies") and target not in visited:
                        queue.append((target, depth + 1))
                for source, _, data in self.topology.graph.in_edges(current, data=True):
                    rel = data.get("relation", "")
                    if rel in ("caused", "happened_before", "implies") and source not in visited:
                        queue.append((source, depth + 1))

        results.sort(key=lambda x: x.score, reverse=True)
        return results


class CommunityTimelineStrategy(RetrievalStrategy):
    """社区时间线策略：找到 query 相关社区，提取社区内时间线。"""

    def retrieve(self, query: str, entities: list[str], kinetic_budget: float, current_time_ts: float) -> list[MemoryNode]:
        anchors = self._locate_anchors(entities, max_anchors=3)
        communities = self.topology.community_detect()
        if not communities:
            return []

        relevant_communities = self._find_relevant_communities(anchors, communities)

        results = []
        hops = 0
        for comm in relevant_communities:
            for member in comm.get("members", []):
                node_id = member.get("node_id", "")
                if not node_id:
                    continue
                node_attrs = self.topology.get_node_data(node_id)
                if node_attrs:
                    mn = self._to_memory_node(node_id, node_attrs, 1, hops, current_time_ts)
                    results.append(mn)
                    hops += 1

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _find_relevant_communities(self, anchors: list[str], communities: list[dict]) -> list[dict]:
        relevant = []
        for comm in communities:
            member_ids = {m.get("node_id", "") for m in comm.get("members", [])}
            overlap = len(set(anchors) & member_ids)
            if overlap > 0:
                relevant.append(comm)
        if not relevant and communities:
            relevant = sorted(communities, key=lambda c: c.get("size", 0), reverse=True)[:2]
        return relevant[:3]


class ContradictionSearchStrategy(RetrievalStrategy):
    """矛盾搜索策略：TMS 驱动，查找与 query 可能矛盾的记忆。"""

    CONTRADICTORY_RELATIONS = {
        "trusts": "distrusts", "likes": "dislikes", "loves": "hates",
        "admires": "despises", "grateful_to": "angry_at",
    }

    def retrieve(self, query: str, entities: list[str], kinetic_budget: float, current_time_ts: float) -> list[MemoryNode]:
        anchors = self._locate_anchors(entities, max_anchors=3)
        if not anchors:
            return []

        results = []
        visited = set()
        hops = 0

        for anchor in anchors:
            for _, target, data in self.topology.graph.out_edges(anchor, data=True):
                if target in visited:
                    continue
                visited.add(target)
                rel = data.get("relation", "")
                contradiction_of = self.CONTRADICTORY_RELATIONS.get(rel)
                if contradiction_of:
                    for _, t2, d2 in self.topology.graph.out_edges(anchor, data=True):
                        if d2.get("relation") == contradiction_of and t2 not in visited:
                            visited.add(t2)
                            node_attrs = self.topology.get_node_data(t2)
                            if node_attrs:
                                mn = self._to_memory_node(t2, node_attrs, 1, hops, current_time_ts)
                                mn.score = round(mn.score * 1.5, 4)
                                results.append(mn)
                                hops += 1

                node_attrs = self.topology.get_node_data(target)
                if node_attrs:
                    mn = self._to_memory_node(target, node_attrs, 1, hops, current_time_ts)
                    results.append(mn)
                    hops += 1

        results.sort(key=lambda x: x.score, reverse=True)
        return results


class IdentityOnlyStrategy(RetrievalStrategy):
    """身份策略：仅返回身份核心记忆，用于问候/告别等简单意图。"""

    def retrieve(self, query: str, entities: list[str], kinetic_budget: float, current_time_ts: float) -> list[MemoryNode]:
        root = self.topology.find_root_node()
        if not root:
            return []

        results = []
        hops = 0

        for _, target, data in self.topology.graph.out_edges(root, data=True):
            if data.get("relation", "").startswith("identity_"):
                node_attrs = self.topology.get_node_data(target)
                if node_attrs:
                    mn = self._to_memory_node(target, node_attrs, 0, hops, current_time_ts)
                    results.append(mn)
                    hops += 1

        for source, _, data in self.topology.graph.in_edges(root, data=True):
            if data.get("relation", "").startswith("identity_"):
                node_attrs = self.topology.get_node_data(source)
                if node_attrs:
                    mn = self._to_memory_node(source, node_attrs, 0, hops, current_time_ts)
                    results.append(mn)
                    hops += 1

        results.sort(key=lambda x: x.score, reverse=True)
        return results


# 从 IntentManifest 构建策略映射表
class IntentRouter:
    """意图路由器 v2.1：意图即路由，从 IntentManifest 读取策略映射。"""

    STRATEGY_TABLE = {
        label: {"strategy": "anchor_walk", "mode": spec.mode}
        for label, spec in _MANIFEST.items()
        if spec.intent_group != "ingest"
    }

    def __init__(self):
        self._strategies: dict[str, RetrievalStrategy] = {}

    def register_strategy(self, name: str, strategy: RetrievalStrategy):
        self._strategies[name] = strategy

    def route(self, semantic: dict, kinetic_budget: float) -> dict:
        action = semantic.get("action", "表达")
        matched = self.STRATEGY_TABLE.get(action, {"strategy": "anchor_walk", "mode": "简洁"})

        strategy_name = matched["strategy"]
        strategy = self._strategies.get(strategy_name)

        return {
            "strategy": strategy,
            "strategy_name": strategy_name,
            "response_mode": matched["mode"],
            "matched_action": action,
            "intent": action,
        }

class MemoryRetriever:
    """
    记忆检索器 v3.0：Query-Aware Graph Memory Pipeline。

    核心变革：图算法即检索引擎，意图即路由，不同意图触发不同图遍历策略。
    返回 list[MemoryNode]，每个节点携带：
      - score: 综合认知价值（用于 ContextManager 排序）
      - hops: 跳跃距离（用于热力学能量结算）
      - depth: 图遍历深度（基础相关性衰减）
      - mem_type: 记忆类型（影响权重系数）
    """

    def __init__(self, topology_engine, clock=None, vector_store=None):
        self.clock = clock
        self.topology = topology_engine
        self.router = IntentRouter()

        self.router.register_strategy("anchor_walk", AnchorWalkStrategy(topology_engine, clock))
        self.router.register_strategy("causal_chain", CausalChainStrategy(topology_engine, clock))
        self.router.register_strategy("community_timeline", CommunityTimelineStrategy(topology_engine, clock))
        self.router.register_strategy("contradiction_search", ContradictionSearchStrategy(topology_engine, clock))
        self.router.register_strategy("identity_only", IdentityOnlyStrategy(topology_engine, clock))
        self.vector = vector_store

    def extract_query_entities(self, query: str, semantic: dict) -> list[str]:
        """从语义解析结果中提取命中锚点实体。"""
        entities = []
        target = semantic.get("target", "")
        if target and len(target) > 1 and target not in ("说话者", "对方", "我", "你"):
            entities.append(target)
        action = semantic.get("action", "")
        if action and len(action) > 1 and action not in ("表达", "陈述", "感叹", "问候"):
            entities.append(action)
        entity_type = semantic.get("entity_type", "")
        if entity_type and entity_type not in entities:
            entities.append(entity_type)
        return entities[:5]

    def _classify_memory(self, node_id: str, node_attrs: dict) -> str:
        return AnchorWalkStrategy(self.topology, self.clock)._classify_memory(node_id, node_attrs)

    def _calculate_score(self, node_id: str, node_attrs: dict, depth: int, current_time_ts: float) -> float:
        return AnchorWalkStrategy(self.topology, self.clock)._calculate_score(node_id, node_attrs, depth, current_time_ts)

    def retrieve_relevant_memories(self, query: str, kinetic_budget: float) -> list[MemoryNode]:
        """Fallback: 基于动能预算的 BFS 图搜索（策略不可用时的降级路径）。"""
        if kinetic_budget <= 0:
            return []

        visited_nodes = set()
        start_node = self.topology.find_root_node()
        if not start_node:
            return []

        queue = [(start_node, 0)]
        hop_cost = 1.0
        hops_taken = 0
        current_time_ts = self.clock.now_ts() if self.clock else time.time()

        raw_results = []

        print(f"[检索] 🔍 BFS fallback 图搜索，初始动能预算: {kinetic_budget:.3f}")

        while queue and kinetic_budget > 0:
            current_node, depth = queue.pop(0)

            if current_node in visited_nodes:
                continue
            visited_nodes.add(current_node)

            kinetic_budget -= hop_cost
            hops_taken += 1

            node_data = self.topology.get_node_data(current_node)
            if node_data and current_node != start_node:
                score = self._calculate_score(current_node, node_data, depth, current_time_ts)
                mem_type = self._classify_memory(current_node, node_data)

                raw_results.append({
                    "node_id": current_node,
                    "node_data": node_data,
                    "score": score,
                    "depth": depth,
                    "mem_type": mem_type
                })

            neighbors = self.topology.get_neighbors(current_node)
            for neighbor in neighbors:
                if neighbor not in visited_nodes:
                    queue.append((neighbor, depth + 1))

        memory_nodes = []
        for res in raw_results:
            node_attrs = res["node_data"]
            inner_data = node_attrs.get("data", {}) if isinstance(node_attrs, dict) else {}
            content = inner_data.get("content", "") if inner_data else str(node_attrs)
            node = MemoryNode(
                text=content,
                score=res["score"],
                hops=hops_taken,
                depth=res["depth"],
                mem_type=res["mem_type"],
                node_id=res["node_id"],
                raw_data=node_attrs
            )
            memory_nodes.append(node)

        memory_nodes.sort(key=lambda x: x.score, reverse=True)

        # thermo 已移除，hops 仅用于日志

        if memory_nodes:
            top_score = memory_nodes[0].score
            avg_score = sum(m.score for m in memory_nodes) / len(memory_nodes)
            type_dist = {}
            for m in memory_nodes:
                t = m.mem_type
                type_dist[t] = type_dist.get(t, 0) + 1
            type_str = ", ".join(f"{k}:{v}" for k, v in type_dist.items())
            print(f"[检索] ✅ BFS fallback 完成：{len(memory_nodes)}条 | 最高分={top_score:.3f} | "
                  f"均分={avg_score:.3f} | 类型分布=[{type_str}]")

        return memory_nodes

    def retrieve_structured(self, user_input: str, kinetic_budget: float, semantic: dict) -> dict:
        """Query-Aware 结构化检索入口：意图路由 → 策略驱动图检索 → 图分析补充。"""
        instruction = self.router.route(semantic, kinetic_budget)
        current_time_ts = self.clock.now_ts() if self.clock else time.time()

        entities = self.extract_query_entities(user_input, semantic)

        strategy = instruction.get("strategy")
        if strategy:
            print(f"[检索] 🎯 策略路由: {instruction['strategy_name']} | 意图: {instruction['matched_action']} | 锚点实体: {entities}")
            memory_nodes = strategy.retrieve(user_input, entities, kinetic_budget, current_time_ts)
        # thermo 已移除
        else:
            print(f"[检索] ⚠️ 无可用策略或动能不足，降级为 BFS fallback")
            memory_nodes = self.retrieve_relevant_memories(user_input, kinetic_budget)

        graph_results = self._run_graph_analysis(instruction, memory_nodes)

        if memory_nodes:
            top_score = memory_nodes[0].score
            avg_score = sum(m.score for m in memory_nodes) / len(memory_nodes)
            type_dist = {}
            for m in memory_nodes:
                t = m.mem_type
                type_dist[t] = type_dist.get(t, 0) + 1
            type_str = ", ".join(f"{k}:{v}" for k, v in type_dist.items())
            print(f"[检索] ✅ 策略检索完成：{len(memory_nodes)}条 | 最高分={top_score:.3f} | "
                  f"均分={avg_score:.3f} | 类型分布=[{type_str}]")

        return {
            "memory_nodes": memory_nodes,
            "graph_results": graph_results,
            "instruction": instruction,
            "semantic": semantic,  # ← 新增，透传原始语义解析
        }

    def _run_graph_analysis(self, instruction: dict, memory_nodes: list[MemoryNode]) -> dict:
        """补充图分析（用于图洞察层，不驱动检索本身）。"""
        graph_results = {}
        analysis_funcs = ["centrality_analysis", "community_detect", "causal_inference", "detect_anomalies",
                          "structural_holes", "detect_motifs"]

        for func_name in analysis_funcs:
            try:
                func = getattr(self.topology, func_name, None)
                if func is None:
                    continue
                result = func()
                graph_results[func_name] = result
            except Exception as e:
                graph_results[func_name] = {"error": str(e)}

        return graph_results