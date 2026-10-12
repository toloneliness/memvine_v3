# core/graph_tools.py
"""图查询工具集 —— 为 LLM 提供标准化图查询接口，是图的"SQL"层"""

import networkx as nx
import time

class GraphTools:
    def __init__(self, topology, vector_store=None):
        self.topology = topology
        self.vector_store = vector_store
        self.clock = getattr(topology, 'clock', None)
        self._name_index: dict = {}
        self._rebuild_index()
        self._centrality_cache = None
        self._centrality_ts: float = 0

    def get_tool_definitions(self) -> list[dict]:
        """返回工具定义 —— 以 Cypher 语法表达，供 LLM 理解图查询协议"""
        return [
            {
                "cypher": "MATCH (n:entity {name: $entity})-[r]-(m) RETURN m.name AS neighbor, type(r) AS relation, r.weight AS weight LIMIT $top_k",
                "parameters": {"entity": "实体名称", "top_k": 10},
                "description": "查询指定实体的邻居节点和关系",
            },
            {
                "cypher": "MATCH p=shortestPath((a:entity {name: $entity_a})-[*]-(b:entity {name: $entity_b})) RETURN nodes(p) AS path, length(p) AS distance",
                "parameters": {"entity_a": "起始实体", "entity_b": "目标实体"},
                "description": "查找两个实体之间的最短路径",
            },
            {
                "cypher": "OPTIONAL MATCH (n:entity {name: $entity}) RETURN n.entity_name AS name, n.entity_type AS type, n.pagerank AS pagerank",
                "parameters": {"entity": "实体名称"},
                "description": "获取实体的完整画像（类型、PageRank、连接数）",
            },
            {
                "cypher": "MATCH (n) WHERE n.name CONTAINS $keyword OR n.content CONTAINS $keyword RETURN n.name AS name, n.type AS type LIMIT $top_k",
                "parameters": {"keyword": "搜索关键词", "top_k": 5},
                "description": "按关键词模糊搜索节点",
            },
            {
                "cypher": "MATCH (n:entity) WHERE n.entity_type = $type RETURN n.entity_name AS name, n.pagerank AS rank ORDER BY rank DESC LIMIT $top_k",
                "parameters": {"type": "实体类型", "top_k": 10},
                "description": "按类型列出所有实体，按 PageRank 排序",
            },
            {
                "cypher": "MATCH (n:entity) WHERE n.constraint > $threshold RETURN n.entity_name AS name, n.constraint AS constraint ORDER BY constraint DESC LIMIT $top_k",
                "parameters": {"threshold": 0.5, "top_k": 10},
                "description": "检测结构洞：查找约束度高的孤立实体",
            },
            {
                "cypher": "MATCH (a:entity)-[r]->(b:entity) WHERE r.relation CONTAINS $keyword RETURN a.entity_name AS from, type(r) AS relation, b.entity_name AS to, r.weight AS weight LIMIT $top_k",
                "parameters": {"keyword": "关系关键词", "top_k": 10},
                "description": "按关系类型搜索三元组",
            },
            {
                "cypher": "MATCH (n:event) WHERE n.temporal_at CONTAINS $date RETURN n.summary AS summary, n.status AS status, n.temporal_at AS time ORDER BY n.temporal_at DESC LIMIT $top_k",
                "parameters": {"date": "日期（如 2025-01）", "top_k": 5},
                "description": "按时间搜索事件",
            },
            {
                "cypher": "MATCH (n) RETURN count(n) AS total_nodes, count{(n)-[]-()}/2 AS total_edges",
                "parameters": {},
                "description": "获取图的全局统计：节点总数和边总数",
            },
            {
                "cypher": "DOC_SEARCH(query: $query, top_k: $top_k)",
                "parameters": {"query": "搜索查询", "top_k": 5},
                "description": "在用户导入的文档中搜索原文（向量语义检索，返回精确文本）",
            },
        ]

    def _rebuild_index(self):
        self._name_index.clear()
        for nid, attrs in self.topology.graph.nodes(data=True):
            for key in ("entity_name", "name_text", "label"):
                val = attrs.get(key, "") or attrs.get("data", {}).get(key, "")
                if not val:
                    continue
                existing = self._name_index.get(val)
                if existing is None:
                    self._name_index[val] = nid
                else:
                    existing_type = self.topology.graph.nodes[existing].get("node_type", "")
                    current_type = attrs.get("node_type", "")
                    if current_type == "entity" and existing_type != "entity":
                        self._name_index[val] = nid

    def _find_node_by_name(self, name: str) -> str | None:
        """根据实体名查找节点 ID（使用索引）"""
        if len(self._name_index) != self.topology.graph.number_of_nodes():
            self._rebuild_index()
        return self._name_index.get(name)


    def explore_neighbors(self, entity: str) -> dict:
        nid = self._find_node_by_name(entity)
        if not nid:
            return {"error": f"未找到实体 '{entity}'", "neighbors": []}
        neighbors = self.topology.get_neighbors(nid)
        result = []
        for nb in neighbors:
            label = self.topology._short_label(nb)
            edge_data = self.topology.graph.get_edge_data(nid, nb) or self.topology.graph.get_edge_data(nb, nid) or {}
            result.append({
                "name": label or nb[:20],
                "relation": edge_data.get("relation", "associated_with"),
                "weight": round(edge_data.get("weight", 0), 2),
            })
        return {"entity": entity, "neighbor_count": len(result), "neighbors": result}

    def find_path(self, entity_a: str, entity_b: str) -> dict:
        nid_a = self._find_node_by_name(entity_a)
        nid_b = self._find_node_by_name(entity_b)
        if not nid_a or not nid_b:
            return {"error": f"未找到 '{entity_a}' 或 '{entity_b}'", "path": []}
        undirected = self.topology.graph.to_undirected()
        try:
            path = nx.shortest_path(undirected, source=nid_a, target=nid_b)
            labels = [self.topology._short_label(n) or n[:16] for n in path]
            return {
                "entity_a": entity_a, "entity_b": entity_b,
                "path_length": len(path) - 1,
                "path": labels,
            }
        except nx.NetworkXNoPath:
            return {
                "entity_a": entity_a, "entity_b": entity_b,
                "path_length": -1,
                "path": [],
                "note": "两者之间不存在任何路径，这是一个结构洞",
            }

    def get_entity_profile(self, entity: str) -> dict:
        nid = self._find_node_by_name(entity)
        if not nid:
            return {"error": f"未找到实体 '{entity}'"}
        nd = self.topology.graph.nodes[nid]
        neighbors = self.topology.get_neighbors(nid)
        neighbor_labels = [self.topology._short_label(n) or n[:16] for n in neighbors[:8]]

        now = self.clock.now_ts() if self.clock else time.time()
        if not self._centrality_cache or now - self._centrality_ts > 300:
            self._centrality_cache = self.topology.centrality_analysis(top_k=50)
            self._centrality_ts = now

        pagerank_map = {p["node_id"]: p["pagerank"] for p in self._centrality_cache.get("pagerank", [])}

        return {
            "entity": entity,
            "node_type": nd.get("node_type", ""),
            "connection_count": len(neighbors),
            "top_neighbors": neighbor_labels,
            "pagerank": round(pagerank_map.get(nid, 0), 5),
            "created_at": str(nd.get("created_at", "")),
        }

    def search_related(self, keyword: str, top_k: int = 5) -> dict:
        keyword_lower = keyword.lower()
        matches = []
        for nid, attrs in self.topology.graph.nodes(data=True):
            label = self.topology._short_label(nid)
            if keyword_lower in (label or "").lower():
                matches.append({"name": label, "node_id": nid})
            data = attrs.get("data", {})
            content = data.get("content", "")
            if keyword_lower in content.lower()[:200]:
                if not any(m["node_id"] == nid for m in matches):
                    matches.append({"name": label or content[:30], "node_id": nid})
        return {"keyword": keyword, "match_count": len(matches), "matches": matches[:top_k]}

    def execute(self, cypher: str, params: dict) -> dict:
        """Cypher 模板子串匹配 → 工具调度 → 参数透传。
        params 优先，cypher 字面值兜底。"""
        X = self._extract_from_cypher
        dispatch = {
            # ⚠️ shortestPath 必须在 )-[r]-(m) 之前（更具体的签名优先）
            "shortestPath": lambda: self.find_path(
                params.get("entity_a") or X(cypher, "entity_a"),
                params.get("entity_b") or X(cypher, "entity_b"),
            ),
            ")-[r]-(m)": lambda: self.explore_neighbors(
                params.get("entity") or X(cypher, "name")
            ),
            "OPTIONAL MATCH": lambda: self.get_entity_profile(
                params.get("entity") or X(cypher, "name")
            ),
            "CONTAINS": lambda: self.search_related(
                params.get("keyword") or X(cypher, "CONTAINS"),
                int(params.get("top_k", 5)),
            ),
            "entity_type =": lambda: self._list_by_type(
                params.get("type") or X(cypher, "entity_type"),
                int(params.get("top_k", 10)),
            ),
            "constraint >": lambda: self._structural_holes_simple(
                float(params.get("threshold", 0.5)),
                int(params.get("top_k", 10)),
            ),
            "relation CONTAINS": lambda: self._search_relations(
                params.get("keyword") or X(cypher, "relation"),
                int(params.get("top_k", 10)),
            ),
            "temporal_at CONTAINS": lambda: self._search_events(
                params.get("date") or X(cypher, "temporal_at"),
                int(params.get("top_k", 5)),
            ),
            "count(n) AS total_nodes": lambda: self._global_stats(),
            "DOC_SEARCH": lambda: self.search_documents(
                params.get("query") or X(cypher, "query"),
                int(params.get("top_k", 5)),
            ),
        }
        for signature, fn in dispatch.items():
            if signature in cypher:
                return {"cypher": cypher, "result": fn()}
        return {"error": f"无法匹配 Cypher 查询: {cypher}"}

    def _extract_from_cypher(self, cypher: str, key: str) -> str:
        """从 Cypher 字面值中提取参数值。params 为空时的兜底机制。
        支持 {key: '值'} 和 key '值' 两种格式。"""
        import re
        patterns = [
            rf"{re.escape(key)}:\s*'([^']*)'",
            rf'{re.escape(key)}:\s*"([^"]*)"',
            rf"{re.escape(key)}\s+'([^']*)'",
            rf'{re.escape(key)}\s+"([^"]*)"',
        ]
        for p in patterns:
            m = re.search(p, cypher)
            if m:
                return m.group(1)
        return ""

    def _list_by_type(self, entity_type: str, top_k: int = 10) -> dict:
        results = []
        for nid, attrs in self.topology.graph.nodes(data=True):
            if attrs.get("node_type") == "entity" and attrs.get("entity_type", "").lower() == entity_type.lower():
                results.append({
                    "name": attrs.get("entity_name", ""),
                })
        return {"type": entity_type, "count": len(results), "entities": results[:top_k]}

    def _structural_holes_simple(self, threshold: float = 0.5, top_k: int = 10) -> dict:
        holes = self.topology.structural_holes() if hasattr(self.topology, 'structural_holes') else []
        filtered = [
            {"name": h.get("content", ""), "constraint": h.get("constraint", 0)}
            for h in holes if h.get("constraint", 0) > threshold
        ]
        return {"threshold": threshold, "count": len(filtered), "holes": filtered[:top_k]}

    def _search_relations(self, keyword: str, top_k: int = 10) -> dict:
        results = []
        for u, v, d in self.topology.graph.edges(data=True):
            rel = d.get("relation", "")
            if keyword.lower() in rel.lower():
                u_label = self.topology._short_label(u) or u[:16]
                v_label = self.topology._short_label(v) or v[:16]
                results.append({
                    "from": u_label, "relation": rel,
                    "to": v_label, "weight": d.get("weight", 0),
                })
        return {"keyword": keyword, "count": len(results), "triples": results[:top_k]}

    def _search_events(self, date: str, top_k: int = 5) -> dict:
        results = []
        for nid, nd in self.topology.graph.nodes(data=True):
            if nd.get("node_type") == "event":
                temporal = str(nd.get("temporal_at", ""))
                if date in temporal:
                    results.append({
                        "summary": nd.get("summary", ""),
                        "status": nd.get("status", ""),
                        "time": temporal,
                    })
        return {"date": date, "count": len(results), "events": results[:top_k]}

    def _global_stats(self) -> dict:
        nodes = self.topology.graph.number_of_nodes()
        edges = self.topology.graph.number_of_edges()
        entity_count = sum(1 for nid, nd in self.topology.graph.nodes(data=True) if nd.get("node_type") == "entity")
        event_count = sum(1 for nid, nd in self.topology.graph.nodes(data=True) if nd.get("node_type") == "event")
        return {
            "total_nodes": nodes,
            "total_edges": edges,
            "entity_count": entity_count,
            "event_count": event_count,
        }

    def search_documents(self, query: str, top_k: int = 5) -> dict:
        if not self.vector_store:
            return {"query": query, "count": 0, "results": [], "note": "向量库未初始化"}
        results = self.vector_store.search_documents(query, top_k=top_k)
        return {
            "query": query,
            "count": len(results),
            "results": [
                {"doc_id": r["doc_id"], "text": r["text"][:2000],
                 "similarity": r["similarity"],
                 "source": r.get("metadata", {}).get("source", ""),
                 "imported_at": r.get("metadata", {}).get("imported_at", ""),
                }
                for r in results
            ],
        }