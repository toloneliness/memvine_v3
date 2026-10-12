# core/graph_awareness.py
"""图感知引擎 —— 从图结构中提取多维认知上下文，为 LLM 提供立体的内部视角"""


class GraphAwareness:
    """9 维认知感知，从图结构直接提取，不走原文"""

    def __init__(self, topology, state_observer, maintenance_scheduler):
        self.topology = topology
        self.state = state_observer
        self.scheduler = maintenance_scheduler

    # ── 主入口 ──

    def build(self, last_talk_ts: float = 0.0, light: bool = False) -> dict:
        if self.topology.graph.number_of_nodes() == 0:
            return {}

        identity = self._read_identity()
        ai = identity.get("self_name") or "我"
        user = identity.get("other_name") or "对方"

        result = {}

        id_core = self._dim_identity(identity, ai)
        if id_core:
            result["identity"] = id_core

        portrait = self._dim_user(identity, user)
        if portrait:
            result["user"] = portrait

        bond = self._dim_bond(ai, user)
        if bond:
            result["bond"] = bond

        const = self._dim_constellation()
        if const:
            result["constellation"] = const

        timeline = self._dim_timeline()
        if timeline:
            result["timeline"] = timeline

        mem = self._dim_memory()
        if mem:
            result["memory"] = mem

        kn = self._dim_knowledge(identity)
        if kn:
            result["knowledge"] = kn

        mood = self._dim_mood(last_talk_ts)
        if mood:
            result["mood"] = mood

        rhythm = self._dim_rhythm(last_talk_ts)
        if rhythm:
            result["rhythm"] = rhythm

        health = self._dim_health(last_talk_ts)
        if health:
            result["health"] = health

        if light:
            # light 模式：只返回最精简的身份信息，不含 cypher 和计数
            light_result = {}
            if "identity" in result:
                id_data = result["identity"]
                light_result["identity"] = {
                    "self_name": id_data.get("self_name", ""),
                    "confidence": id_data.get("confidence", 0),
                }
            if "user" in result:
                user_data = result["user"]
                light_result["user"] = {
                    "name": user_data.get("name", ""),
                }
            if "bond" in result:
                bond_data = result["bond"]
                light_result["bond"] = {
                    "dialog_count": bond_data.get("dialog_count", 0),
                }
            return light_result

    def _fallback_name(self, entity_id: str) -> str:
        if not self.topology.graph.has_node(entity_id):
            return ""
        for _, target, data in self.topology.graph.out_edges(entity_id, data=True):
            if data.get("relation") in ("SELF_CLAIM", "LABELED_BY", "name_of"):
                nd = self.topology.graph.nodes[target]
                name = nd.get("name_text", "") or nd.get("label", "")
                if name and name != "MemVine":
                    return name
        return ""

    # ── 身份读取 ──

    def _read_identity(self) -> dict:
        result = {"self_name": None, "other_name": None,
                  "self_conf": 0, "other_conf": 0,
                  "self_counts": {}, "other_counts": {}}

        if self.topology.graph.has_node("entity_ai"):
            candidates = {}
            for _, target, data in self.topology.graph.out_edges("entity_ai", data=True):
                if data.get("relation") in ("SELF_CLAIM", "LABELED_BY"):
                    nd = self.topology.graph.nodes[target]
                    name = nd.get("name_text", "")
                    if name:
                        candidates[name] = candidates.get(name, 0) + data.get("weight", 1)
            if candidates:
                best = max(candidates, key=candidates.get)
                result["self_name"] = best
                result["self_conf"] = candidates[best] / sum(candidates.values())
                result["self_counts"] = candidates

        if self.topology.graph.has_node("entity_user"):
            candidates = {}
            for _, target, data in self.topology.graph.out_edges("entity_user", data=True):
                if data.get("relation") in ("SELF_CLAIM", "LABELED_BY"):
                    nd = self.topology.graph.nodes[target]
                    name = nd.get("name_text", "")
                    if name:
                        candidates[name] = candidates.get(name, 0) + data.get("weight", 1)
            if candidates:
                best = max(candidates, key=candidates.get)
                result["other_name"] = best
                result["other_conf"] = candidates[best] / sum(candidates.values())
                result["other_counts"] = candidates

        return result
    # ── 维度 1: 身份内核 ──

    def _dim_identity(self, identity: dict, ai: str) -> dict:
        return {
            "self_name": ai or "",
            "confidence": identity.get("self_conf", 0),
        }

    # ── 维度 2: 用户画像 ──

    def _dim_user(self, identity: dict, user: str) -> dict:
        if not user or user == "对方":
            user = self._fallback_name("entity_user") or "对方"
        return {
            "name": user,
        }

    # ── 维度 3: 关系拓扑 ──

    def _dim_bond(self, ai: str, user: str) -> dict:
        user_memories = sum(1 for nid, nd in self.topology.graph.nodes(data=True)
                            if nd and (nd.get("source", "") or "").startswith("user"))
        return {
            "dialog_count": user_memories,
        }

    def _read_edges_raw(self, src: str, dst: str) -> list:
        result = []
        if not self.topology.graph.has_edge(src, dst):
            return result
        edge = self.topology.graph.get_edge_data(src, dst)
        if edge:
            result.append({
                "relation": edge.get("relation", ""),
                "weight": edge.get("weight", 0),
            })
        return result

    def _read_edges(self, src: str, dst: str) -> list:
        result = []
        if not self.topology.graph.has_edge(src, dst):
            return result
        edge = self.topology.graph.get_edge_data(src, dst)
        if edge:
            rel = edge.get("relation", "")
            w = edge.get("weight", 0)
            cn = {"trusts": "信任", "likes": "喜欢", "admires": "敬佩",
                  "curious_about": "好奇", "grateful_to": "感激",
                  "dislikes": "不悦", "angry_at": "不满"}
            if rel in cn:
                score = min(1.0, w / 50)
                result.append(f"{cn[rel]}({score:.0%})")
        return result

    def _compute_cognitive_boundary(self, max_hops: int = 3) -> dict[str, list]:
        STRUCTURAL = {"contains", "part_of", "related_to", "mentioned_in", "records"}
        graph = self.topology.graph
        starts = [n for n in ("entity_ai", "entity_user") if graph.has_node(n)]
        if not starts:
            return {}

        now_ts = self.topology.clock.now_ts()
        visited = set(starts)
        frontier = list(starts)
        groups: dict[str, list] = {}

        for hop in range(max_hops):
            next_frontier = []
            for node in frontier:
                for neighbor in graph.neighbors(node):
                    if neighbor in visited:
                        continue
                    edge = graph.get_edge_data(node, neighbor) or {}
                    rel = edge.get("relation", "")
                    if hop > 0 and rel not in STRUCTURAL:
                        continue
                    last_flow = edge.get("last_flow_time", 0)
                    hours = (now_ts - last_flow) / 3600 if last_flow else 999
                    activity = 1.0 / (1.0 + hours / 24.0)
                    if activity < 0.3:
                        continue
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
                    nd = graph.nodes[neighbor]
                    if nd.get("node_type") == "entity":
                        etype = nd.get("entity_type", "")
                        ename = nd.get("entity_name", "")
                        if etype and ename:
                            groups.setdefault(etype, []).append(ename)
                    elif nd.get("node_type") == "event":
                        groups.setdefault("events", []).append({
                            "summary": nd.get("summary", ""),
                            "status": nd.get("status", ""),
                            "temporal_at": nd.get("temporal_at"),
                        })
            frontier = next_frontier

        return groups

    # ── 维度 4: 实体星座 ──

    def _dim_constellation(self) -> dict:
        groups = self._compute_cognitive_boundary(max_hops=3)
        result = {}
        for etype in ("person", "concept", "book", "organization", "location"):
            if etype in groups:
                result[etype] = groups[etype][:3]

        return {
            "cypher": (
                "MATCH (a)-[*1..3]-(e:entity) "
                "RETURN e.entity_type AS type, collect(DISTINCT e.entity_name)[..3] AS top"
            ),
            "result": result,
        }

    def _dim_timeline(self) -> dict:
        groups = self._compute_cognitive_boundary(max_hops=3)
        events = groups.get("events", [])
        events.sort(key=lambda e: e.get("temporal_at") or "", reverse=True)

        return {
            "cypher": (
                "MATCH (e:event) "
                "RETURN e.status AS status, e.temporal_at AS time, e.summary AS summary "
                "ORDER BY e.temporal_at DESC LIMIT 5"
            ),
            "result": [
                {"status": e.get("status", ""), "time": e.get("temporal_at", "") or "",
                 "summary": (e.get("summary", "") or "")[:40]}
                for e in events[:5]
            ],
        }

    # ── 维度 5: 记忆架构 ──

    def _dim_memory(self) -> dict:
        communities: dict[int, dict] = {}
        for nid in self.topology.graph.nodes:
            nd = self.topology.graph.nodes[nid]
            cid = nd.get("community_id")
            if cid is None:
                continue
            if cid not in communities:
                communities[cid] = {"count": 0, "types": {}}
            communities[cid]["count"] += 1
            data = nd.get("data", {})
            if isinstance(data, dict):
                mt = data.get("mem_type", "other")
                communities[cid]["types"][mt] = communities[cid]["types"].get(mt, 0) + 1

        total = self.topology.graph.number_of_nodes()
        sorted_comms = sorted(communities.items(), key=lambda x: -x[1]["count"])
        comm_list = []
        for cid, info in sorted_comms[:3]:
            dominant = max(info["types"], key=info["types"].get) if info["types"] else "?"
            comm_list.append({"id": cid, "count": info["count"], "dominant_type": dominant})

        return {
            "cypher": (
                "MATCH (n) "
                "RETURN n.community_id AS cid, n.data.mem_type AS mem_type, count(*) AS cnt "
                "ORDER BY cnt DESC"
            ),
            "result": {
                "total_nodes": total,
                "community_count": len(communities),
                "top_communities": comm_list,
            },
        }

    # ── 维度 6: 认知地图 ──
    def _dim_knowledge(self, identity: dict) -> dict:
        sc = identity.get("self_counts", {})
        oc = identity.get("other_counts", {})
        self_name = identity.get("self_name", "")
        other_name = identity.get("other_name", "")

        certain = []
        if self_name and sc.get(self_name, 0) >= 5:
            certain.append({"name": self_name, "count": sc[self_name]})
        if other_name and oc.get(other_name, 0) >= 5:
            certain.append({"name": other_name, "count": oc[other_name]})

        uncertain = []
        for name, count in sc.items():
            if name != self_name and 1 <= count < 5:
                uncertain.append({"name": name, "count": count})

        return {
            "cypher": (
                "MATCH (a:AI)-[r:SELF_CLAIM|LABELED_BY]->(n) "
                "WITH n.name_text AS name, count(r) AS cnt "
                "RETURN name, cnt, CASE WHEN cnt >= 5 THEN 'certain' ELSE 'uncertain' END AS status"
            ),
            "result": {
                "certain": certain[:3],
                "uncertain": uncertain[:2],
            },
        }
    # ── 维度 7: 情绪地形 ──

    def _dim_mood(self, last_talk_ts: float = 0.0) -> dict:
        load = self.state._assess_load(last_talk_ts)
        pending = len(self.scheduler.schedule.pending_issues)
        return {
            "level": load["level"],
            "pending_issues": pending,
        }

    def _dim_rhythm(self, last_talk_ts: float = 0.0) -> dict:
        now = self.topology.clock.now_ts()
        timestamps = []
        for nid in self.topology.graph.nodes:
            data = self.topology.graph.nodes[nid].get("data", {})
            if isinstance(data, dict):
                bt = data.get("born_at", 0)
                if bt:
                    timestamps.append(bt)

        if not timestamps:
            return {}

        oldest = min(timestamps)
        newest = max(timestamps)
        span_days = max(1, (newest - oldest) / 86400)
        recent_5m = sum(1 for t in timestamps if now - t < 300)
        gap_min = (now - last_talk_ts) / 60 if last_talk_ts and last_talk_ts > 0 else None

        return {
            "cypher": (
                "MATCH (n) WHERE n.data.born_at IS NOT NULL "
                "RETURN min(n.data.born_at) AS oldest, max(n.data.born_at) AS newest, count(*) AS total"
            ),
            "result": {
                "span_days": span_days,
                "last_gap_minutes": gap_min,
                "recent_5min_count": recent_5m,
            },
        }

    def _dim_health(self, last_talk_ts: float = 0.0) -> dict:
        n_nodes = self.topology.graph.number_of_nodes()
        n_edges = self.topology.graph.number_of_edges()
        load = self.state._assess_load(last_talk_ts)

        return {
            "cypher": "MATCH (n) RETURN count(n) AS nodes UNION MATCH ()-[r]->() RETURN count(r) AS edges",
            "result": {
                "nodes": n_nodes,
                "edges": n_edges,
                "load_level": load["level"],
            },
        }
    # ── 维度 9: 结构健康 ──

    def _dim_health(self, last_talk_ts: float = 0.0) -> str:
        n_nodes = self.topology.graph.number_of_nodes()
        n_edges = self.topology.graph.number_of_edges()

        parts = [f"{n_nodes}节点/{n_edges}边"]

        load = self.state._assess_load(last_talk_ts)
        if load["level"] == "drowsy":
            parts.append("认知休眠")
        elif load["level"] == "burdened":
            parts.append("认知过载")
        else:
            parts.append("认知正常")

        return "，".join(parts)