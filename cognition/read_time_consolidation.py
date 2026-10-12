# cognition/read_time_consolidation.py

import time
from cognition.memory_retriever import MemoryNode
from config import MEMORY_TYPE_WEIGHTS
import numpy as np


class ReadTimeConsolidation:
    """
    读时整合 (Read-Time Consolidation)：
    在检索后、送入 ContextManager 前，对 MemoryNode 列表进行：
      ① 语义聚类去重：每组保留代表性 1 条
      ② 矛盾消解：TMS 在读时介入，保留最新/最可信
      ③ 叙事压缩：相关记忆合并为连贯叙述
      ④ 多维排序：query 相关性 × 时效性 × 因果权重
    """

    def __init__(self, topology, tms=None, clock=None, vector_store=None):
        self.topology = topology
        self.tms = tms
        self.clock = clock
        self.vector_store = vector_store

    def consolidate(
        self,
        memory_nodes: list[MemoryNode],
        query: str,
        current_time_ts: float = None
    ) -> list[MemoryNode]:
        if not memory_nodes:
            return []

        if current_time_ts is None:
            current_time_ts = self.clock.now_ts() if self.clock else time.time()

        nodes = self._deduplicate(memory_nodes)
        nodes = self._resolve_contradictions(nodes)
        nodes = self._narrative_compress(nodes)
        nodes = self._multidimensional_sort(nodes, query, current_time_ts)

        return nodes

    def _deduplicate(self, nodes: list[MemoryNode]) -> list[MemoryNode]:
        """语义聚类去重：内容高度相似的节点只保留得分最高的。"""
        if len(nodes) <= 1:
            return nodes

        clusters: list[list[MemoryNode]] = []
        used = set()

        for i, node in enumerate(nodes):
            if i in used:
                continue
            cluster = [node]
            used.add(i)
            for j in range(i + 1, len(nodes)):
                if j in used:
                    continue
                if self._is_similar(node.text, nodes[j].text):
                    cluster.append(nodes[j])
                    used.add(j)
            clusters.append(cluster)

        result = []
        for cluster in clusters:
            best = max(cluster, key=lambda n: n.score)
            if len(cluster) > 1:
                best.score = round(best.score * 1.1, 4)
            result.append(best)

        if len(result) < len(nodes):
            removed = len(nodes) - len(result)
            print(f"[读时整合] 🔄 去重: {len(nodes)}条 → {len(result)}条 (移除{removed}条相似)")

        return result

    def _is_similar(self, text_a: str, text_b: str) -> bool:
        """简单的字符级 Jaccard 相似度判断。"""
        if not text_a or not text_b:
            return False
        set_a = set(text_a)
        set_b = set(text_b)
        if not set_a or not set_b:
            return False
        jaccard = len(set_a & set_b) / len(set_a | set_b)
        return jaccard > 0.75

    def _resolve_contradictions(self, nodes: list[MemoryNode]) -> list[MemoryNode]:
        """矛盾消解：检查节点间是否存在 TMS 冲突，保留最新/最可信的。"""
        if not self.tms or len(nodes) <= 1:
            return nodes

        to_remove = set()

        for i, node_a in enumerate(nodes):
            if i in to_remove:
                continue
            for j, node_b in enumerate(nodes):
                if j <= i or j in to_remove:
                    continue

                if node_a.node_id and node_b.node_id:
                    edge_ab = self.topology.graph.get_edge_data(node_a.node_id, node_b.node_id) if self.topology else None
                    edge_ba = self.topology.graph.get_edge_data(node_b.node_id, node_a.node_id) if self.topology else None

                    if edge_ab and edge_ab.get("pending_resolution"):
                        newer = node_a if node_a.raw_data.get("data", {}).get("born_at", 0) > node_b.raw_data.get("data", {}).get("born_at", 0) else node_b
                        to_remove.add(j if newer == node_a else i)
                    elif edge_ba and edge_ba.get("pending_resolution"):
                        newer = node_a if node_a.raw_data.get("data", {}).get("born_at", 0) > node_b.raw_data.get("data", {}).get("born_at", 0) else node_b
                        to_remove.add(j if newer == node_a else i)

        if to_remove:
            result = [n for i, n in enumerate(nodes) if i not in to_remove]
            print(f"[读时整合] ⚡ 矛盾消解: 移除{len(to_remove)}条待验证冲突节点")
            return result

        return nodes

    def _narrative_compress(self, nodes: list[MemoryNode]) -> list[MemoryNode]:
        """叙事压缩：将同一说话者的连续短记忆合并为一条叙述。"""
        if len(nodes) <= 2:
            return nodes

        compressed = []
        i = 0
        merged_count = 0

        while i < len(nodes):
            current = nodes[i]
            current_source = getattr(current, 'source', '') or current.raw_data.get("data", {}).get("source", "")

            if len(current.text) > 50 or current.mem_type in ("identity", "core_fact"):
                compressed.append(current)
                i += 1
                continue

            group = [current]
            j = i + 1
            while j < len(nodes):
                next_node = nodes[j]
                next_source = getattr(next_node, 'source', '') or next_node.raw_data.get("data", {}).get("source", "")
                if next_source == current_source and len(next_node.text) <= 50:
                    group.append(next_node)
                    j += 1
                else:
                    break

            if len(group) > 2:
                merged_text = "；".join(n.text for n in group)
                best_score = max(n.score for n in group)
                merged = MemoryNode(
                    text=merged_text,
                    score=round(best_score * 0.95, 4),
                    hops=group[0].hops,
                    depth=group[0].depth,
                    mem_type=group[0].mem_type,
                    node_id=group[0].node_id,
                    raw_data=group[0].raw_data,
                    source=current_source
                )
                compressed.append(merged)
                merged_count += len(group) - 1
                i = j
            else:
                compressed.append(current)
                i += 1

        if merged_count > 0:
            print(f"[读时整合] 📝 叙事压缩: 合并{merged_count}条短记忆")

        return compressed

    def _multidimensional_sort(self, nodes: list[MemoryNode], query: str, current_time_ts: float) -> list[MemoryNode]:
        """多维排序：query 相关性 × 时效性 × 因果权重。"""

        for node in nodes:
            relevance = self._query_relevance(node.text, query)
            recency = self._recency_score(node, current_time_ts)
            causal = self._causal_weight(node)

            composite = node.score * (0.4 + relevance * 0.3) * (0.7 + recency * 0.3) * (0.8 + causal * 0.2)
            node.score = round(composite, 4)

        nodes.sort(key=lambda x: x.score, reverse=True)
        return nodes

    def _query_relevance(self, text: str, query: str) -> float:
        """query 相关性：语义向量相似度，降级为字符重叠度。"""
        if not text or not query:
            return 0.0
        if self.vector_store:
            try:
                q_vec = self.vector_store.embed(query[:500])
                t_vec = self.vector_store.embed(text[:500])
                sim = float(np.dot(q_vec, t_vec))
                return max(0.0, min(sim, 1.0))
            except Exception:
                pass
        query_chars = set(query.lower())
        text_chars = set(text.lower())
        overlap = len(query_chars & text_chars)
        return min(overlap / max(len(query_chars), 1), 1.0)

    def _recency_score(self, node: MemoryNode, current_time_ts: float) -> float:
        """时效性：越新越高，7天内线性衰减。"""
        node_data = node.raw_data.get("data", {}) if isinstance(node.raw_data, dict) else {}
        born_at = node_data.get("born_at", current_time_ts)
        days_old = (current_time_ts - born_at) / 86400.0
        if days_old < 1:
            return 1.0
        elif days_old < 7:
            return 1.0 - (days_old - 1) / 6.0
        else:
            return 0.3

    def _causal_weight(self, node: MemoryNode) -> float:
        """因果权重：有因果边的节点权重更高。"""
        if not self.topology or not node.node_id:
            return 0.0
        causal_count = 0
        for _, _, data in self.topology.graph.out_edges(node.node_id, data=True):
            if data.get("relation") in ("caused", "implies", "happened_before"):
                causal_count += 1
        for _, _, data in self.topology.graph.in_edges(node.node_id, data=True):
            if data.get("relation") in ("caused", "implies", "happened_before"):
                causal_count += 1
        return min(causal_count * 0.2, 1.0)