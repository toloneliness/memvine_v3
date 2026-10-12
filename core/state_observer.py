# core/state_observer.py
"""状态观测器 —— 从真实系统指标派生认知状态，替代虚拟能量系统"""

class StateObserver:
    def __init__(self, topology, maintenance_scheduler, mention_buffer, clock,
                 tension_field=None, correction_tracer=None):
        self.topology = topology
        self.scheduler = maintenance_scheduler
        self.buffer = mention_buffer
        self.clock = clock
        self.tension_field = tension_field
        self.correction_tracer = correction_tracer

    def observe(self, last_talk_ts: float = 0,
                entity_names: list = None,
                fact_summaries: list = None,
                this_round_events: int = 0,
                energy_level: float = 1.0) -> dict:
        entity_names = entity_names or []
        fact_summaries = fact_summaries or []
        load = self._assess_load(last_talk_ts)
        metabolism = self._assess_metabolism(entity_names, fact_summaries)
        graph_status = self._derive_graph_status(load, metabolism, energy_level)
        return {
            "load": load["description"],
            "load_level": load["level"],
            "metabolism": metabolism,
            "graph_status": graph_status,
        }

    def _assess_load(self, last_talk_ts: float) -> dict:
        now = self.clock.now_ts()
        idle_hours = (now - last_talk_ts) / 3600 if last_talk_ts else 999
        nodes = self.topology.graph.number_of_nodes()
        edges = self.topology.graph.number_of_edges()
        density = edges / max(1, nodes * (nodes - 1))
        introspective = sum(1 for nid in self.topology.graph.nodes()
                            if self.topology.graph.nodes[nid].get("data", {}).get("source") == "introspective")
        if idle_hours > 4:
            return {"level": "drowsy", "description": f"距上次对话{idle_hours:.0f}小时",
                    "graph_sparse": density < 0.02, "introspective_count": introspective}
        if idle_hours > 1:
            return {"level": "waking", "description": f"距上次对话{idle_hours:.0f}小时",
                    "graph_sparse": density < 0.02, "introspective_count": introspective}
        if density < 0.02 and nodes > 100:
            return {"level": "heavy", "description": "记忆稀疏，存在知识空洞",
                    "graph_sparse": True, "introspective_count": introspective}
        return {"level": "clear", "description": "状态良好",
                "graph_sparse": False, "introspective_count": introspective}

    def _assess_metabolism(self, entity_names: list, fact_summaries: list) -> dict:
        result = {}
        if entity_names:
            result["entities"] = entity_names[:5]
        if fact_summaries:
            result["facts"] = fact_summaries[:5]
        return result if result else {}

    def _derive_graph_status(self, load: dict, metabolism: dict, energy_level: float = 1.0) -> dict:
        result = {}

        if load.get("graph_sparse"):
            result["self_diagnosis"] = self._collect_graph_status()
        return result

    def _collect_graph_status(self) -> dict:
        """图的简要自诊断 —— 返回精简摘要，供 CogniWeave 议程生成使用"""
        status = {
            "total_nodes": self.topology.graph.number_of_nodes(),
            "total_edges": self.topology.graph.number_of_edges(),
            "entity_count": 0,
            "event_count": 0,
            "structural_hole_count": 0,
            "tension_count": 0,
        }

        for nid, nd in self.topology.graph.nodes(data=True):
            if nd.get("node_type") == "entity":
                status["entity_count"] += 1
            elif nd.get("node_type") == "event":
                status["event_count"] += 1

        if self.topology and hasattr(self.topology, 'structural_holes'):
            holes = self.topology.structural_holes()
            status["structural_hole_count"] = len(holes)

        if self.tension_field:
            hot = self.tension_field.get_hotspots(threshold=0.5)
            status["tension_count"] = len(hot)

        return status