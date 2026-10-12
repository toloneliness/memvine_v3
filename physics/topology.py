import time
import threading
import math
import re
import networkx as nx
from collections import defaultdict
from core.molecules import Trace
from config import (
    TOPOLOGY_CAPACITY, TRACE_DECAY_DAYS, TRACE_IDLE_DAYS,
    IDENTITY_EDGE_WEIGHT
)
from core.clock import SystemClock

class TopologyEngine:
    def __init__(self, capacity: int = None, clock: SystemClock = None):
        if clock is None:
            from core.clock import SystemClock
            clock = SystemClock()
        self.clock = clock
        self.graph = nx.DiGraph()
        self.capacity = capacity or TOPOLOGY_CAPACITY
        self.traces: dict[str, Trace] = {}
        self._cached_root_id = None
        self.cognitive_scripts: dict[str, dict] = {}
        self._lock = threading.RLock()

    def discover_self(self):
        if self.graph.number_of_nodes() == 0:
            self._cached_root_id = None
            return None

        best = None
        best_conf = -1.0
        for node_id, attrs in self.graph.nodes(data=True):
            state = attrs.get("identity_state", {})
            conf = state.get("self_name_conf", 0.0)
            if conf > best_conf:
                best_conf = conf
                best = node_id

        if best and best_conf > 0:
            self._cached_root_id = best
        else:
            scores = {}
            for node_id in self.graph.nodes():
                out_degree = self.graph.out_degree(node_id)
                in_degree = self.graph.in_degree(node_id)
                emotion_intensity = abs(
                    self.graph.nodes[node_id].get("data", {}).get("valence", 0.0)
                )
                scores[node_id] = (out_degree * 0.4) + (in_degree * 0.3) + (emotion_intensity * 0.05)
            self._cached_root_id = max(scores, key=scores.get)

        print(f"🧠 [自我认知] 确认自我身份为: {self._cached_root_id}")
        return self._cached_root_id

    def find_root_node(self):
        return self._cached_root_id

    def add_node(self, node_id: str, data: dict, created_at):
        with self._lock:
            self.graph.add_node(node_id, data=data, created_at=created_at)
            if self.graph.number_of_nodes() == 1:
                self._cached_root_id = node_id
                print(f"✨ [降生] 第一个记忆节点 {node_id} 成为初始自我。")

    def connect(self, source_id: str, target_id: str, weight: float = 1.0,
                relation: str = "associated_with",
                confidence: float = 1.0, status: str = ""):
        with self._lock:
            if not (self.graph.has_node(source_id) and self.graph.has_node(target_id)):
                return

        trace_key = f"{source_id}->{target_id}"
        existing_trace = self.traces.get(trace_key)

        if existing_trace:
            existing_trace.rewrite()
            if existing_trace.relation == "associated_with":
                existing_trace.relation = relation
        else:
            new_trace = Trace(source_id, target_id, relation=relation,
                              confidence=confidence, status=status)
            self.traces[trace_key] = new_trace

        if self.graph.has_edge(source_id, target_id):
            self.graph[source_id][target_id]["weight"] = self.traces[trace_key].get_weight(self.clock.now_ts())
            self.graph[source_id][target_id]["confidence"] = confidence
            self.graph[source_id][target_id]["status"] = status
        else:
            self.graph.add_edge(source_id, target_id,
                                weight=self.traces[trace_key].get_weight(self.clock.now_ts()),
                                relation=relation, confidence=confidence, status=status)

    def touch_trace(self, source_id: str, target_id: str, emotion: dict | None = None):
        with self._lock:
            trace_key = f"{source_id}->{target_id}"
        trace = self.traces.get(trace_key)
        if trace:
            trace.rewrite(emotion)
            if self.graph.has_edge(source_id, target_id):
                self.graph[source_id][target_id]["weight"] = trace.get_weight(self.clock.now_ts())

    def connect_with_tms(self, source_id: str, target_id: str, weight: float = 1.0, relation: str = "associated_with") -> str:
        """带真值维护的连接：冲突时自动修正"""
        if not hasattr(self, 'tms') or self.tms is None:
            self.connect(source_id, target_id, weight, relation)
            return "direct"

        conflict = self.tms.check(source_id, target_id, relation, weight)
        if conflict is None:
            self.connect(source_id, target_id, weight, relation)
            return "direct"

        resolution = self.tms.resolve(conflict)
        self.tms.apply(conflict)

        if resolution == "keep_new":
            print(f" ⚡ [TMS] 修正: {source_id} --[{conflict.old_relation}]--> {target_id} → --[{relation}]-->")
        elif resolution == "keep_old":
            print(f" 🔒 [TMS] 保留旧信念: {source_id} --[{conflict.old_relation}]--> {target_id} (权重不足以推翻)")
        elif resolution == "ask_llm":
            print(f" ❓ [TMS] 冲突待定: {source_id} --[{conflict.old_relation} vs {relation}]--> {target_id}")

        return resolution

    def get_trace(self, source_id: str, target_id: str) -> Trace | None:
        return self.traces.get(f"{source_id}->{target_id}")

    def get_all_traces_from(self, node_id: str) -> list[Trace]:
        return [t for t in self.traces.values() if t.source_id == node_id]

    def calculate_gravity_to_root(self, node_data: dict) -> float:
        root = self._cached_root_id
        if not root or not self.graph.has_node(root):
            return 0.0
        root_data = self.graph.nodes[root].get("data", {})
        root_keywords = set(root_data.get("concept", "").lower().split())
        node_content = node_data.get("content", "").lower()
        if not root_keywords:
            return 0.5
        overlap = len(root_keywords & set(node_content.split()))
        valence = abs(node_data.get("valence", 0.0)) / 10.0
        gravity = (overlap * 0.15) + min(valence, 0.85)
        return min(gravity, 1.0)

    def decay(self, now_ts: float):
        with self._lock:
            decayed = 0
        to_remove = []
        for node_id, attrs in self.graph.nodes(data=True):
            if node_id == self._cached_root_id:
                continue
            node_data = attrs.get("data", {})
            last_activated = node_data.get("last_activated", now_ts)
            days_idle = (now_ts - last_activated) / 86400.0
            if days_idle > TRACE_DECAY_DAYS:
                to_remove.append(node_id)
            elif days_idle > TRACE_IDLE_DAYS:
                node_data["last_activated"] = now_ts
                decayed += 1

        for node_id in to_remove:
            traces_to_remove = [
                k for k, t in self.traces.items()
                if t.source_id == node_id or t.target_id == node_id
            ]
            for k in traces_to_remove:
                del self.traces[k]
            self.graph.remove_node(node_id)

        if decayed or to_remove:
            print(f"[熵减] 风化 {decayed} 个节点，移除 {len(to_remove)} 个过期记忆。")

        self._passive_elimination()

        return len(to_remove)

    def _passive_elimination(self):
        if len(self.traces) <= self.capacity:
            return

        sorted_traces = sorted(
            self.traces.items(),
            key=lambda x: x[1].get_weight(self.clock.now_ts())
        )

        evict_count = max(1, int(len(sorted_traces) * 0.05))
        evicted = 0

        for i in range(evict_count):
            if i >= len(sorted_traces):
                break
            trace_key, trace = sorted_traces[i]

            if trace.relation.startswith("identity"):
                continue

            has_source = self.graph.has_node(trace.source_id)
            has_target = self.graph.has_node(trace.target_id)

            if has_source and has_target and self.graph.has_edge(trace.source_id, trace.target_id):
                self.graph.remove_edge(trace.source_id, trace.target_id)

            del self.traces[trace_key]
            evicted += 1

        if evicted > 0:
            print(f"[熵减] 淘汰 {evicted} 条低磁性轨迹。")

    def find_resonant_traces(self, keywords: list[str]) -> list[tuple[str, Trace]]:
        results = []
        for trace_key, trace in self.traces.items():
            if trace.emotion_snapshot.get("raw_text") is None:
                continue
            text = trace.emotion_snapshot["raw_text"]
            match_count = sum(1 for kw in keywords if kw in text)
            if match_count >= 2:
                results.append((trace_key, trace))
        return sorted(results, key=lambda x: x[1].flow_count, reverse=True)

    def boost_trace(self, trace_key: str, amount: int = 3):
        trace = self.traces.get(trace_key)
        if trace:
            trace.flow_count += amount
            print(f"⚡ [共振] 轨迹 {trace_key} 磁性增强 +{amount}")

    def get_node_data(self, node_id: str) -> dict | None:
        if self.graph.has_node(node_id):
            return self.graph.nodes[node_id]
        return None

    def get_neighbors(self, node_id: str) -> list:
        if self.graph.has_node(node_id):
            successors = list(self.graph.successors(node_id))
            predecessors = list(self.graph.predecessors(node_id))
            return list(dict.fromkeys(successors + predecessors))
        return []

    def get_timeline(self, limit: int = 50) -> list[dict]:
        root = self.find_root_node()
        if not root:
            return []

        timeline = []
        visited = set()
        queue = [root]

        while queue and len(timeline) < limit:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            node_data = self.graph.nodes[current].get("data", {})
            if isinstance(node_data, dict) and node_data.get("content"):
                timeline.append({
                    "node_id": current,
                    "content": node_data.get("content", "")[:200],
                    "agent": node_data.get("agent", ""),
                    "action": node_data.get("action", ""),
                    "target": node_data.get("target", ""),
                    "source": node_data.get("source", ""),
                    "valence": node_data.get("valence", 0.0),
                    "born_at": node_data.get("born_at", 0),
                    "mem_type": node_data.get("mem_type", ""),
                })

            for _, target, data in self.graph.out_edges(current, data=True):
                if data.get("relation") == "happened_before" and target not in visited:
                    queue.append(target)

        timeline.sort(key=lambda x: x.get("born_at", 0))
        return timeline


    def query_relationship(self, entity_a: str, entity_b: str, max_hops: int = 3) -> list[dict]:
        if not (self.graph.has_node(entity_a) and self.graph.has_node(entity_b)):
            return []
        try:
            paths = list(nx.all_simple_paths(self.graph, entity_a, entity_b, cutoff=max_hops))
        except nx.NetworkXNoPath:
            return []
        results = []
        for path in paths:
            path_edges = []
            for i in range(len(path) - 1):
                edge_data = self.graph.get_edge_data(path[i], path[i+1])
                if edge_data:
                    path_edges.append({
                        "from": path[i],
                        "to": path[i+1],
                        "relation": edge_data.get("relation", "unknown"),
                        "weight": edge_data.get("weight", 1.0),
                    })
            results.append({"path": path, "edges": path_edges})
        return results

    def query_correction_history(self, entity_name: str, max_depth: int = 3) -> list[dict]:
        """查询实体的修正历史链。"""
        target_nid = None
        for nid, attrs in self.graph.nodes(data=True):
            if attrs.get("entity_name") == entity_name:
                target_nid = nid
                break
        if not target_nid:
            return []

        events = []
        for src, dst, data in self.graph.in_edges(target_nid, data=True):
            if data.get("relation") != "corrects":
                continue
            node = self.graph.nodes.get(src, {})
            if node.get("node_type") == "correction_event":
                events.append({
                    "event_id": src,
                    "old_value": node.get("old_value", ""),
                    "new_value": node.get("new_value", ""),
                    "action": node.get("action", ""),
                    "born_at": node.get("born_at", 0),
                    "summary": node.get("summary", ""),
                })

        events.sort(key=lambda e: e["born_at"], reverse=True)
        return events[:max_depth]

    def transitive_inference(self, relation: str = "trusts", max_hops: int = 3) -> list[dict]:
        inferences = []
        for src in self.graph.nodes:
            for mid in self.graph.nodes:
                edge1 = self.graph.get_edge_data(src, mid)
                if not edge1 or edge1.get("relation") != relation:
                    continue
                for dst in self.graph.nodes:
                    if dst == src:
                        continue
                    edge2 = self.graph.get_edge_data(mid, dst)
                    if not edge2 or edge2.get("relation") != relation:
                        continue
                    if self.graph.has_edge(src, dst):
                        continue
                    w1 = edge1.get("weight", 1.0)
                    w2 = edge2.get("weight", 1.0)
                    inferred_weight = min(w1, w2) * 0.7
                    self.graph.add_edge(src, dst, weight=inferred_weight,
                                        relation=relation, inferred=True)
                    inferences.append({
                        "path": f"{src} --[{relation}]--> {mid} --[{relation}]--> {dst}",
                        "inferred_weight": inferred_weight,
                    })
        return inferences

    def community_detect(self) -> list[dict]:
        try:
            from networkx.algorithms.community import louvain_communities
            undirected = self.graph.to_undirected()
            communities = louvain_communities(undirected, seed=42)
        except Exception:
            return []
        result = []
        for i, comm in enumerate(communities):
            members = []
            for nid in comm:
                nd = self.graph.nodes[nid].get("data", {})
                if isinstance(nd, dict):
                    members.append({
                        "node_id": nid,
                        "content": nd.get("content", "")[:60],
                        "agent": nd.get("agent", ""),
                        "action": nd.get("action", ""),
                    })
            result.append({"community_id": i, "size": len(members), "members": members})
        return result

    def spreading_activation(self, seed_nodes: list[str], max_iterations: int = 3, decay: float = 0.5) -> dict[str, float]:
        activation = {nid: (1.0 if nid in seed_nodes else 0.0) for nid in self.graph.nodes}
        for _ in range(max_iterations):
            new_activation = dict(activation)
            for src, dst, data in self.graph.edges(data=True):
                w = data.get("weight", 1.0)
                flow = activation[src] * w * decay
                new_activation[dst] = min(new_activation.get(dst, 0) + flow, 10.0)
            activation = new_activation
        return {k: round(v, 4) for k, v in activation.items() if v > 0.01}

    def link_prediction(self, node_a: str, node_b: str) -> dict:
        if self.graph.has_edge(node_a, node_b) or self.graph.has_edge(node_b, node_a):
            return {"score": 1.0, "exists": True}
        neighbors_a = set(self.graph.predecessors(node_a)) | set(self.graph.successors(node_a))
        neighbors_b = set(self.graph.predecessors(node_b)) | set(self.graph.successors(node_b))
        common = neighbors_a & neighbors_b
        union = neighbors_a | neighbors_b
        jaccard = len(common) / len(union) if union else 0.0
        adamic_adar = 0.0
        for n in common:
            degree = self.graph.degree(n)
            if degree > 1:
                import math
                adamic_adar += 1.0 / math.log(degree)
        return {"score": round(jaccard, 4), "adamic_adar": round(adamic_adar, 4),
                "common_neighbors": len(common), "exists": False}

    def find_missing_edges(self, context: str) -> dict | None:
        keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}', context)
        relevant_nodes = []
        for node, data in self.graph.nodes(data=True):
            if any(kw.lower() in str(node).lower() or kw.lower() in str(data).lower() for kw in keywords):
                relevant_nodes.append(node)
        if len(relevant_nodes) < 2:
            return None
        for i in range(len(relevant_nodes)):
            for j in range(i + 1, len(relevant_nodes)):
                node_a, node_b = relevant_nodes[i], relevant_nodes[j]
                if not self.graph.has_edge(node_a, node_b):
                    return {"node_a": node_a, "node_b": node_b, "target_concept": f"{node_a} 与 {node_b} 的关联"}
        return None

    def calculate_hunger(self, missing_edges: dict | None) -> float:
        if not missing_edges:
            return 0.0
        hunger = 0.5
        concept = missing_edges.get("target_concept", "").lower()
        if any(word in concept for word in ["情绪", "感觉", "为什么", "记忆", "小砂锅"]):
            hunger += 0.3
        return min(hunger, 1.0)

    # ══════════════════════════════════════════════
    # 第二层：10 项纯图操作方法
    # ══════════════════════════════════════════════

    def detect_anomalies(self, z_threshold: float = 2.0) -> dict:
        """异常检测：发现图中不符合局部模式的节点/边。"""
        if self.graph.number_of_nodes() < 3:
            return {"suspicious_nodes": [], "suspicious_edges": []}

        degrees = dict(self.graph.degree())
        in_degrees = dict(self.graph.in_degree())
        out_degrees = dict(self.graph.out_degree())
        clustering = nx.clustering(self.graph.to_undirected())

        def _z_scores(values):
            vals = list(values.values())
            mu = sum(vals) / len(vals)
            sigma = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
            if sigma == 0:
                return {k: 0.0 for k in values}
            return {k: abs(v - mu) / sigma for k, v in values.items()}

        z_deg = _z_scores(degrees)
        z_in = _z_scores(in_degrees)
        z_out = _z_scores(out_degrees)
        z_cc = _z_scores(clustering)

        suspicious_nodes = []
        for n in self.graph.nodes:
            score = z_deg.get(n, 0) + z_in.get(n, 0) + z_out.get(n, 0) + z_cc.get(n, 0)
            if score / 4 > z_threshold:
                nd = self.graph.nodes[n].get("data", {})
                suspicious_nodes.append({
                    "node_id": n, "anomaly_score": round(score / 4, 3),
                    "content": str(nd.get("content", ""))[:80],
                    "reason": f"度偏离={z_deg.get(n,0):.1f}σ 聚类偏离={z_cc.get(n,0):.1f}σ"
                })
        suspicious_nodes.sort(key=lambda x: x["anomaly_score"], reverse=True)

        edge_weights = {(u, v): d.get("weight", 1.0) for u, v, d in self.graph.edges(data=True)}
        z_edge = _z_scores({f"{u}→{v}": w for (u, v), w in edge_weights.items()})
        suspicious_edges = []
        for (u, v), w in edge_weights.items():
            key = f"{u}→{v}"
            if z_edge.get(key, 0) > z_threshold:
                suspicious_edges.append({"from": u, "to": v, "weight": w, "z_score": round(z_edge[key], 3)})
        suspicious_edges.sort(key=lambda x: x["z_score"], reverse=True)

        return {"suspicious_nodes": suspicious_nodes, "suspicious_edges": suspicious_edges}

    def belief_propagation(self, seeds: dict, iterations: int = 5, damping: float = 0.85) -> dict:
        """信念传播：概率在图节点间传递，更新置信度。"""
        beliefs = {n: seeds.get(n, 0.5) for n in self.graph.nodes}
        if not seeds:
            return beliefs

        for _ in range(iterations):
            new_beliefs = dict(beliefs)
            for u, v, data in self.graph.edges(data=True):
                w = data.get("weight", 1.0)
                influence = beliefs[u] * min(w * 0.3, 0.5)
                new_beliefs[v] = damping * new_beliefs[v] + (1 - damping) * influence
            for v, u, data in self.graph.edges(data=True):
                w = data.get("weight", 1.0)
                influence = beliefs[v] * min(w * 0.3, 0.5)
                new_beliefs[u] = damping * new_beliefs[u] + (1 - damping) * influence
            beliefs = new_beliefs

        return {k: round(v, 4) for k, v in beliefs.items()}

    def causal_inference(self) -> dict:
        """因果推理：检测 v-structure (A→C←B)，区分相关和因果。"""
        v_structures = []
        for c in self.graph.nodes:
            parents = list(self.graph.predecessors(c))
            for i in range(len(parents)):
                for j in range(i + 1, len(parents)):
                    a, b = parents[i], parents[j]
                    if not self.graph.has_edge(a, b) and not self.graph.has_edge(b, a):
                        v_structures.append({
                            "collider": c, "cause_a": a, "cause_b": b,
                            "interpretation": f"{a} 和 {b} 通过 {c} 产生虚假相关"
                        })

        causal_pairs = []
        for u, v, data in self.graph.edges(data=True):
            w = data.get("weight", 1.0)
            if self.graph.has_edge(v, u):
                rev_w = self.graph[v][u].get("weight", 1.0)
                if w > rev_w * 2:
                    causal_pairs.append({"direction": f"{u} → {v}", "confidence": round(w / (w + rev_w), 3), "type": "单向因果"})
                else:
                    causal_pairs.append({"direction": f"{u} ↔ {v}", "confidence": round(max(w, rev_w) / (w + rev_w), 3), "type": "双向相关"})
            else:
                causal_pairs.append({"direction": f"{u} → {v}", "confidence": round(min(w / 3.0, 1.0), 3), "type": "潜在因果"})

        return {"v_structures": v_structures, "causal_pairs": causal_pairs}

    def structural_similarity(self, node_a: str, node_b: str) -> float:
        """计算两个节点的结构相似度（邻居 Jaccard 系数）。"""
        nbrs_a = set(self.graph.predecessors(node_a)) | set(self.graph.successors(node_a))
        nbrs_b = set(self.graph.predecessors(node_b)) | set(self.graph.successors(node_b))
        if not nbrs_a and not nbrs_b:
            return 0.0
        inter = nbrs_a & nbrs_b
        union = nbrs_a | nbrs_b
        return len(inter) / len(union) if union else 0.0

    def find_analogous_patterns(self, pattern_nodes: list, top_k: int = 5) -> list[dict]:
        """结构类比：找到与给定模式结构相似的子图 (VF2 子图同构)。"""
        if len(pattern_nodes) < 2:
            return []
        pattern = self.graph.subgraph(pattern_nodes).copy()
        if pattern.number_of_nodes() == 0:
            return []
        matches = []
        try:
            from networkx.algorithms.isomorphism import DiGraphMatcher
            matcher = DiGraphMatcher(
                self.graph, pattern,
                node_match=lambda n1, n2: True,
                edge_match=lambda e1, e2: e1.get("relation") == e2.get("relation")
            )
            for i, mapping in enumerate(matcher.subgraph_isomorphisms_iter()):
                if i >= top_k:
                    break
                rev = {v: k for k, v in mapping.items()}
                matches.append({
                    "pattern_nodes": pattern_nodes,
                    "matched_nodes": [rev.get(p, "?") for p in pattern_nodes],
                    "mapping": {k: v for k, v in list(mapping.items())[:10]}
                })
        except Exception:
            pass
        return matches

    def centrality_analysis(self, top_k: int = 10) -> dict:
        """中心性分析：介数中心性 + 特征向量中心性 + PageRank。"""
        if self.graph.number_of_nodes() == 0:
            return {"betweenness": [], "eigenvector": [], "pagerank": []}

        betweenness = nx.betweenness_centrality(self.graph, weight="weight")
        bc_sorted = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:top_k]

        try:
            eigenvector = nx.eigenvector_centrality_numpy(self.graph, weight="weight")
        except Exception:
            eigenvector = {n: 0.0 for n in self.graph.nodes}
        ec_sorted = sorted(eigenvector.items(), key=lambda x: x[1], reverse=True)[:top_k]

        pagerank = nx.pagerank(self.graph, alpha=0.85, weight="weight", max_iter=100, tol=1e-6)
        pr_sorted = sorted(pagerank.items(), key=lambda x: x[1], reverse=True)[:top_k]

        def _fmt(ranking, key):
            return [{"node_id": nid, key: round(s, 5),
                     "content": str(self.graph.nodes[nid].get("data", {}).get("content", ""))[:60],
                     "mem_type": self.graph.nodes[nid].get("data", {}).get("mem_type", "daily_chat")}
                    for nid, s in ranking]

        return {"betweenness": _fmt(bc_sorted, "betweenness"),
                "eigenvector": _fmt(ec_sorted, "eigenvector"),
                "pagerank": _fmt(pr_sorted, "pagerank")}

    def find_core_memories(self, limit: int = 5) -> dict:
        """按内容质量筛选核心记忆：内容长度 > 10 且非系统消息，按时间倒序。"""
        if self.graph.number_of_nodes() == 0:
            return {}

        candidates = []
        now_ts = self.clock.now_ts()

        for nid in self.graph.nodes:
            nd = self.graph.nodes[nid]
            data = nd.get("data", {}) if isinstance(nd.get("data"), dict) else {}
            content = data.get("content", "") or nd.get("content", "")
            mem_type = data.get("mem_type", "") or nd.get("mem_type", "")
            born_at = data.get("born_at", 0) or nd.get("born_at", 0)

            # 过滤：太短、系统消息、epoch 0、daily_chat 闲聊
            if len(content) < 10:
                continue
            if mem_type in ("system_event", "structured"):
                continue
            if born_at <= 1:  # epoch 0 或接近 0
                continue
            if content in ("你好", "AI实体", "大脑过载"):
                continue

            # 时效性权重：最近30天内的记忆优先
            age_days = max(0, (now_ts - born_at) / 86400)
            recency = 1.0 / (1.0 + age_days / 7.0)

            # 内容质量：长度适中（20-200字）最好
            if 20 <= len(content) <= 200:
                quality = 1.0
            elif len(content) > 200:
                quality = 0.7
            else:
                quality = 0.4

            score = recency * 0.6 + quality * 0.4
            candidates.append((nid, score, content[:200], born_at))

        candidates.sort(key=lambda x: -x[1])
        top = candidates[:limit]

        return {
            "core_memories": [
                {"node_id": nid, "score": round(s, 4),
                 "content": content,
                 "time": self.clock.format_local(born_at) if born_at else ""}
                for nid, s, content, born_at in top
            ]
        }

    def _short_label(self, nid: str) -> str:
        """从节点提取简短标签，优先 entity_name > name_text > label > content"""
        if not self.graph.has_node(nid):
            return ""
        nd = self.graph.nodes[nid]
        data = nd.get("data", {})
        for key in ("entity_name", "name_text", "label"):
            val = nd.get(key, "") or data.get(key, "")
            if val and len(val.strip()) <= 20:
                return val.strip()
        content = data.get("content", "")
        if content:
            clean = content.replace("\n", " ").strip()
            # 过滤：非概念类节点不返回 content 片段（避免聊天消息被当实体名）
            node_type = nd.get("node_type", "") or data.get("node_type", "")
            if node_type in ("document", "chunk", "summary"):
                return ""
            if not node_type and len(clean) > 50:
                return ""
            first_char = clean[0] if clean else ""
            if first_char and ('\u4e00' <= first_char <= '\u9fff' or first_char.isalpha()):
                return clean[:16]
        return ""

    def structural_holes(self) -> list[dict]:
        """结构洞：发现图中缺失的关键连接 —— 两个话题从未关联但应该有关联。"""
        if self.graph.number_of_nodes() < 3:
            return []
        undirected = self.graph.to_undirected()
        try:
            constraint = nx.constraint(undirected)
        except Exception:
            constraint = {n: 1.0 for n in undirected.nodes}

        low_constraint = sorted(constraint.items(), key=lambda x: x[1])[:10]
        candidates = []
        for nid, c_val in low_constraint:
            if c_val > 0.5:
                continue
            nbrs = list(undirected.neighbors(nid))
            missing = [(nbrs[i], nbrs[j]) for i in range(len(nbrs)) for j in range(i + 1, len(nbrs))
                       if not undirected.has_edge(nbrs[i], nbrs[j])]
            if missing:
                label = self._short_label(nid)
                bridges = []
                for a, b in missing[:3]:
                    bridges.append({"between": [a, b]})
                if bridges:
                    candidates.append({
                        "node_id": nid, "constraint": round(c_val, 4),
                        "content": label,
                        "missing_bridges": bridges
                    })
        return candidates

    def summarize(self, target_groups: int = 5) -> dict:
        """图摘要：压缩大规模图，提取核心结构为超节点。"""
        if self.graph.number_of_nodes() < target_groups:
            return {"super_nodes": [], "message": "节点数不足，无需压缩"}

        nodes = list(self.graph.nodes)
        groups = {n: n for n in nodes}

        for _ in range(min(self.graph.number_of_nodes() - target_groups, 50)):
            best_pair, best_sim = None, -1
            checked = set()
            for u, v in self.graph.edges:
                if groups[u] == groups[v]:
                    continue
                pair = tuple(sorted([groups[u], groups[v]]))
                if pair in checked:
                    continue
                checked.add(pair)
                sim = self.structural_similarity(u, v)
                if sim > best_sim:
                    best_sim, best_pair = sim, (u, v)
            if best_pair is None or best_sim < 0.1:
                break
            a, b = best_pair
            target = groups[b]
            for n in nodes:
                if groups[n] == target:
                    groups[n] = groups[a]

        clusters = defaultdict(list)
        for n in nodes:
            clusters[groups[n]].append(n)

        super_nodes = []
        for rep, members in clusters.items():
            contents = [str(self.graph.nodes[m].get("data", {}).get("content", ""))[:50]
                        for m in members if self.graph.nodes[m].get("data", {}).get("content", "")]
            super_nodes.append({"representative": rep, "size": len(members),
                                "members": members[:5], "sample_contents": contents[:3],
                                "label": f"记忆簇({len(members)}条)"})
        super_nodes.sort(key=lambda x: x["size"], reverse=True)

        return {"super_nodes": super_nodes[:target_groups],
                "original_nodes": self.graph.number_of_nodes(),
                "compressed_groups": len(super_nodes),
                "compression_ratio": round(len(super_nodes) / max(self.graph.number_of_nodes(), 1), 3)}

    def detect_motifs(self) -> dict:
        """模式发现：发现重复出现的三元组子图模式，识别典型对话模式。"""
        if self.graph.number_of_nodes() < 3:
            return {"triads": {}, "frequent_patterns": [], "interpretation": []}

        triad_labels = {
            "003": "完全孤立", "012": "单边连接", "102": "双向+单向",
            "021D": "反馈-主导", "021U": "反馈-从属", "021C": "反馈-共栖",
            "111D": "传递链-主导", "111U": "传递链-从属", "030T": "三角平衡",
            "030C": "三角循环", "201": "双重传递", "120D": "星型-主导",
            "120U": "星型-从属", "120C": "星型-对称", "210": "混合星型", "300": "完全连接"
        }

        try:
            from networkx.algorithms.triads import triad_census
            census = triad_census(self.graph)
            labeled = {k: {"count": v, "meaning": triad_labels.get(k, k)}
                       for k, v in census.items() if v > 0}
        except Exception:
            labeled = {}

        relation_sequences = []
        for u, v, d in self.graph.edges(data=True):
            for w in self.graph.successors(v):
                if w != u and self.graph.has_edge(u, w):
                    seq = (self.graph[u][v].get("relation", ""),
                           self.graph[v][w].get("relation", ""),
                           self.graph[u][w].get("relation", ""))
                    relation_sequences.append(seq)

        seq_counts = defaultdict(int)
        for seq in relation_sequences:
            seq_counts[seq] += 1

        frequent = sorted([{"pattern": list(k), "count": v} for k, v in seq_counts.items() if v >= 2],
                          key=lambda x: x["count"], reverse=True)[:10]

        interpretations = []
        for p in frequent:
            seq = p["pattern"]
            if "trusts" in seq and "distrusts" in seq:
                interpretations.append(f"先质疑再信任：{seq} (出现{p['count']}次)")
            elif seq.count("happened_before") >= 2:
                interpretations.append(f"时序传递链：{seq} (出现{p['count']}次)")
            elif "angry_at" in seq and "trusts" in seq:
                interpretations.append(f"愤怒-信任交替：{seq} (出现{p['count']}次)")

        return {"triads": labeled, "frequent_patterns": frequent, "interpretation": interpretations}


    def register_cognitive_script(self, pattern: list, count: int, interpretation: str):
        """将高频关系模式固化为认知脚本"""
        key = " → ".join(pattern)
        if key in self.cognitive_scripts:
            self.cognitive_scripts[key]["count"] = count
            self.cognitive_scripts[key]["updated_at"] = self.clock.now_ts()
        else:
            self.cognitive_scripts[key] = {
                "pattern": pattern,
                "count": count,
                "interpretation": interpretation,
                "registered_at": self.clock.now_ts(),
            }

    def graph_similarity(self, nodes_a: list, nodes_b: list) -> dict:
        """图编辑距离：衡量两个子图的相似度。"""
        if not nodes_a or not nodes_b:
            return {"similarity": 0.0, "error": "空子图"}
        sub_a = self.graph.subgraph(nodes_a).copy()
        sub_b = self.graph.subgraph(nodes_b).copy()
        na, nb = sub_a.number_of_nodes(), sub_b.number_of_nodes()
        ea, eb = sub_a.number_of_edges(), sub_b.number_of_edges()
        if na == 0 or nb == 0:
            return {"similarity": 0.0, "error": "空子图"}

        max_possible = na + nb + ea + eb
        try:
            gen = nx.optimize_graph_edit_distance(
                sub_a, sub_b,
                node_match=lambda n1, n2: True,
                edge_match=lambda e1, e2: e1.get("relation") == e2.get("relation")
            )
            edit_distance = next(gen)
        except Exception:
            edit_distance = abs(na - nb) + abs(ea - eb)

        similarity = 1.0 - (edit_distance / max_possible) if max_possible > 0 else 1.0
        return {"similarity": round(similarity, 4), "edit_distance": edit_distance,
                "nodes_a": na, "nodes_b": nb, "edges_a": ea, "edges_b": eb,
                "summary": f"两段记忆的相似度是 {similarity:.2f}"}

    def pairwise_similarity_matrix(self, node_groups: list[list]) -> list[list]:
        """多组节点之间的两两相似度矩阵。"""
        n = len(node_groups)
        matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            matrix[i][i] = 1.0
            for j in range(i + 1, n):
                sim = self.graph_similarity(node_groups[i], node_groups[j])["similarity"]
                matrix[i][j] = sim
                matrix[j][i] = sim
        return matrix

    def hierarchical_clustering(self, max_clusters: int = 8) -> dict:
        """层次聚类：多尺度记忆组织 —— 话题 → 子话题 → 具体事件。"""
        if self.graph.number_of_nodes() < 3:
            return {"levels": [], "dendrogram": [], "message": "节点数不足"}

        nodes = list(self.graph.nodes)
        n = len(nodes)

        sim = {}
        for i in range(n):
            for j in range(i + 1, n):
                s = self.structural_similarity(nodes[i], nodes[j])
                if s > 0:
                    sim[(i, j)] = s

        clusters = {i: [nodes[i]] for i in range(n)}
        next_id = n
        merge_history = []

        for (i, j), s in sorted(sim.items(), key=lambda x: x[1], reverse=True):
            if i not in clusters or j not in clusters or clusters[i] is clusters[j]:
                continue
            merged = clusters[i] + clusters[j]
            merge_history.append({"step": len(merge_history), "similarity": round(s, 4),
                                  "merged": [clusters[i][:3], clusters[j][:3]], "size": len(merged)})
            clusters[next_id] = merged
            del clusters[i], clusters[j]
            next_id += 1
            if len(clusters) <= max_clusters:
                break

        levels = []
        for cid, members in clusters.items():
            if isinstance(members, list):
                contents = [str(self.graph.nodes[m].get("data", {}).get("content", ""))[:40]
                            for m in members if self.graph.nodes[m].get("data", {}).get("content", "")]
                levels.append({"cluster_id": str(cid), "size": len(members),
                               "sample_contents": contents[:5], "label": f"话题簇({len(members)}条)"})
        levels.sort(key=lambda x: x["size"], reverse=True)

        return {"levels": levels, "dendrogram": merge_history[-20:],
                "total_nodes": n, "total_clusters": len(levels)}

    def get_last_interaction_gap(self) -> float:
        latest_timestamp = 0
        for node, attrs in self.graph.nodes(data=True):
            node_data = attrs.get("data", {})
            ts = node_data.get("last_activated", 0)
            if ts > latest_timestamp:
                latest_timestamp = ts
        if latest_timestamp == 0:
            return float('inf')
        return self.clock.now_ts() - latest_timestamp

    def to_save_dict(self) -> dict:
        graph_data = nx.node_link_data(self.graph)
        traces_data = {k: v.to_dict() for k, v in self.traces.items()}
        return {"graph": graph_data, "traces": traces_data}

    @classmethod
    def from_save_dict(cls, data: dict) -> "TopologyEngine":
        import networkx as nx
        from networkx.readwrite import json_graph

        engine = cls()
        engine.graph = json_graph.node_link_graph(data.get("graph", {}))
        engine.traces = {
            k: Trace.from_dict(v) for k, v in data.get("traces", {}).items()
        }
        engine.discover_self()
        return engine