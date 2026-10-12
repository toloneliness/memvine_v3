# cognition/proactive/catalyst.py
"""火种生成器 — 图方法驱动发现 + 置信度审计 + 共生反馈

管线：
  1. 4 个图方法并行扫描 → 候选节点
  2. 4 个审计函数返回置信度（非布尔值）→ 综合催化置信度
  3. 废弃区过滤（衰减度 > 0.8 → 休眠）
  4. 根据历史验证率调整策略参数
  5. LLM 在结构上下文中生成假设 → 写入带 confidence 的边
"""

import time, json, math, uuid
from typing import Optional

class Catalyst:
    """火种生成器"""

    def __init__(self, topology, llm, clock, validator=None):
        self.topology = topology
        self.llm = llm
        self.clock = clock
        self.validator = validator
        self._last_scan: float = 0
        self._min_interval: float = 600
        self._scanned: set = set()
        self.last_audit_results: list[dict] = []
        self.config = {
            "max_hypotheses_per_run": 3,
            "prompt_temperature": 0.5,
        }

    # ═══════════════════════════════════════════════
    # 入口
    # ═══════════════════════════════════════════════

    def run(self) -> int:
        now = self.clock.now_ts()
        if now - self._last_scan < self._min_interval:
            return 0
        self._last_scan = now

        self._adjust_strategy_from_feedback()

        candidates = self._find_candidates()
        if not candidates:
            return 0

        candidates = self._audit_candidates(candidates)

        for c in candidates:
            if c["audit"]["topic_decay"] > 0.8:
                c["priority"] = "dormant"
                nid = c["node_id"]
                if self.topology.graph.has_node(nid):
                    self.topology.graph.nodes[nid].setdefault("data", {})["dormant_since"] = self.clock.now_ts()
                print(f"[Catalyst] 💤 休眠: {c['content'][:30]} (衰减度 {c['audit']['topic_decay']:.2f})")

        active = [c for c in candidates if c.get("priority") != "dormant"]
        active.sort(key=lambda c: c.get("catalysis_confidence", 0.5), reverse=True)
        active = active[:self.config["max_hypotheses_per_run"]]

        written = 0
        for c in active:
            hypothesis = self._generate_hypothesis(c)
            if hypothesis and self._solidify(c, hypothesis):
                self._scanned.add(c["node_id"])
                written += 1

        return written

    # ═══════════════════════════════════════════════
    # 阶段 1: 图方法扫描
    # ═══════════════════════════════════════════════

    def _find_candidates(self) -> list[dict]:
        candidates = []
        candidates.extend(self._thin_community())
        candidates.extend(self._structural_holes())
        candidates.extend(self._peripheral())
        candidates.extend(self._sparse_branch())
        seen = set()
        unique = []
        for c in candidates:
            nid = c["node_id"]
            if nid not in seen and nid not in self._scanned:
                seen.add(nid)
                unique.append(c)
        return unique[:8]

    def _node_ok(self, nid):
        if not self.topology.graph.has_node(nid):
            return False
        data = self.topology.graph.nodes[nid].get("data", {})
        source = data.get("source", "")
        content = data.get("content", "")
        return source.startswith("user") and len(content) > 5

    def _thin_community(self) -> list[dict]:
        communities = self.topology.community_detect()
        if not communities:
            return []
        candidates = []
        for comm in sorted(communities, key=lambda c: c["size"])[:3]:
            for m in comm.get("members", []):
                if self._node_ok(m["node_id"]):
                    candidates.append({
                        "node_id": m["node_id"],
                        "content": m.get("content", "")[:80],
                        "reason": f"社区大小 {comm['size']}（最薄之一）",
                        "context": {
                            "community_size": comm["size"],
                            "neighbor_samples": [
                                x.get("content", "")[:40] for x in comm["members"][:3]
                                if x["node_id"] != m["node_id"]
                            ],
                        },
                    })
        return candidates

    def _structural_holes(self) -> list[dict]:
        holes = self.topology.structural_holes()
        if not holes:
            return []
        candidates = []
        for hole in sorted(holes, key=lambda h: h.get("constraint", 1.0))[:3]:
            for bridge in hole.get("missing_bridges", []):
                for nid in bridge.get("between", []):
                    if self._node_ok(nid):
                        candidates.append({
                            "node_id": nid,
                            "content": self.topology.graph.nodes[nid]["data"]["content"][:80],
                            "reason": f"结构洞: 节点{nid}存在未连接邻居",
                            "context": {
                                "constraint": hole.get("constraint", 1.0),
                                "missing_bridge": bridge.get("between", []),
                            },
                        })
        return candidates

    def _peripheral(self) -> list[dict]:
        centrality = self.topology.centrality_analysis(top_k=20)
        pagerank_map = {p["node_id"]: p["pagerank"] for p in centrality.get("pagerank", [])}
        if not pagerank_map:
            return []
        pr_values = sorted(pagerank_map.values())
        if len(pr_values) >= 10:
            threshold = pr_values[int(len(pr_values) * 0.2)]
        else:
            threshold = pr_values[min(3, len(pr_values) - 1)]
        candidates = []
        for nid, pr in pagerank_map.items():
            if pr > threshold or not self._node_ok(nid):
                continue
            candidates.append({
                "node_id": nid,
                "content": self.topology.graph.nodes[nid]["data"]["content"][:80],
                "reason": f"PageRank 极低 ({pr:.4f})",
                "context": {"pagerank": pr},
            })
        return candidates

    def _sparse_branch(self) -> list[dict]:
        clusters = self.topology.hierarchical_clustering(max_clusters=8)
        levels = clusters.get("levels", [])
        candidates = []
        for level in sorted(levels, key=lambda l: l["size"]):
            if level["size"] > 3:
                continue
            for sample in level.get("sample_contents", [])[:2]:
                for nid in self.topology.graph.nodes():
                    data = self.topology.graph.nodes[nid].get("data", {})
                    content = data.get("content", "")
                    if content[:20] in sample and data.get("source", "").startswith("user") and len(content) > 5:
                        candidates.append({
                            "node_id": nid,
                            "content": content[:80],
                            "reason": f"稀疏分支: {level.get('label','')} (仅 {level['size']} 条)",
                            "context": {"branch_size": level["size"]},
                        })
        return candidates

    # ═══════════════════════════════════════════════
    # 阶段 2: 置信度审计（返回置信度，非布尔值）
    # ═══════════════════════════════════════════════

    def _audit_candidates(self, candidates: list[dict]) -> list[dict]:
        centrality = self.topology.centrality_analysis(top_k=15)
        communities = self.topology.community_detect()
        for c in candidates:
            nid = c["node_id"]
            data = self.topology.graph.nodes[nid].get("data", {})
            sprout = self._sprout_confidence(nid, data)
            bridge = self._bridge_confidence(nid, centrality)
            merge = self._community_merge_confidence(communities)
            decay = self._topic_decay_score(nid, data)
            c["audit"] = {
                "sprout_confidence": round(sprout, 2),
                "bridge_confidence": round(bridge, 2),
                "merge_risk": round(merge, 2),
                "topic_decay": round(decay, 2),
            }
            c["catalysis_confidence"] = round(1.0 - max(sprout, decay, bridge), 2)
        self.last_audit_results = candidates
        return candidates

    def _sprout_confidence(self, nid: str, data: dict) -> float:
        born_at = data.get("born_at", 0)
        if born_at == 0 or self.clock.now_ts() == 0:
            return 0.0
        age_hours = (self.clock.now_ts() - born_at) / 3600
        mention_count = data.get("mention_count", 1)
        last_active = data.get("last_active", 0) or data.get("last_activated", 0) or born_at
        hours_since = max(0, (self.clock.now_ts() - last_active) / 3600) if last_active else 0
        youth = max(0.0, 1.0 - age_hours / 72)
        activity = min(1.0, mention_count / 5)
        recency = max(0.0, 1.0 - hours_since / 24) if hours_since > 0 else 1.0
        return youth * activity * recency

    def _bridge_confidence(self, nid: str, centrality: dict = None) -> float:
        if centrality is None:
            centrality = self.topology.centrality_analysis(top_k=15)
        bw_list = centrality.get("betweenness", [])
        if not bw_list:
            return 0.0
        max_bw = bw_list[0]["betweenness"]
        if max_bw == 0:
            return 0.0
        for b in bw_list:
            if b["node_id"] == nid:
                return min(1.0, b["betweenness"] / max_bw)
        return 0.0

    def _community_merge_confidence(self, communities: list = None) -> float:
        if communities is None:
            communities = self.topology.community_detect()
        if not communities:
            return 0.0
        small = sum(1 for c in communities if c["size"] <= 3)
        return min(1.0, small / len(communities))

    def _topic_decay_score(self, nid: str, data: dict) -> float:
        last_active = data.get("last_active", 0) or data.get("last_activated", 0)
        if last_active == 0:
            return 0.5
        days = (self.clock.now_ts() - last_active) / 86400
        if days < 30:
            return 0.0
        return 1.0 / (1.0 + math.exp(-(days - 60) / 10))

    # ═══════════════════════════════════════════════
    # 阶段 3: LLM 生成假设
    # ═══════════════════════════════════════════════

    def _generate_hypothesis(self, candidate: dict) -> Optional[dict]:
        content = candidate["content"]
        reason = candidate["reason"]
        ctx = candidate.get("context", {})
        bot_name = self._get_bot_name()
        introspection = self._build_introspection_context()

        neighbor_text = ""
        if "neighbor_samples" in ctx and ctx["neighbor_samples"]:
            neighbor_text = "\n同一社区其他记忆：\n" + "\n".join(f"  - {s}" for s in ctx["neighbor_samples"])

        from prompts import CATALYST_HYPOTHESIS_PROMPT, IDENTITY_SUBSYSTEM
        identity = IDENTITY_SUBSYSTEM.format(self_name=bot_name, user_name="用户")
        prompt = CATALYST_HYPOTHESIS_PROMPT.format(
            identity=identity, content=content, reason=reason,
            neighbor_text=neighbor_text, introspection=introspection)

        try:
            text = self.llm.call(prompt, temperature=self.config["prompt_temperature"])
            if not text:
                return None
            s = text.find("{"); e = text.rfind("}") + 1
            if s >= 0 and e > s:
                return json.loads(text[s:e])
        except Exception as e:
            print(f"[Catalyst] LLM 失败: {e}")
        return None

    # ═══════════════════════════════════════════════
    # 阶段 4: 写入图谱
    # ═══════════════════════════════════════════════

    def _solidify(self, candidate: dict, hypothesis: dict) -> bool:
        concept = hypothesis.get("concept", "")
        relation = hypothesis.get("relation", "associated_with")
        confidence = max(0.0, min(1.0, hypothesis.get("confidence", 0.5)))
        if not concept or len(concept) < 2:
            return False

        concept_id = f"catalyst_{uuid.uuid4().hex[:8]}"
        now_ts = self.clock.now_ts()
        self.topology.add_node(concept_id, {
            "content": concept, "mem_type": "introspection",
            "source": "catalyst", "node_type": "concept",
            "born_at": now_ts,
            "last_active": now_ts,
            "last_activated": now_ts,
            "mention_count": 1,
        }, now_ts)

        self.topology.connect(
            candidate["node_id"], concept_id,
            weight=confidence * 0.5, relation=relation,
            confidence=confidence, status="pending_validation",
        )
        print(f"[Catalyst] 🔥 {candidate['reason'][:40]} → «{concept}» (c={confidence:.2f})")

        if self.validator:
            self.validator.register_validation(
                candidate["node_id"], concept_id,
                question=f"关于「{candidate['content'][:30]}」和「{concept}」的关联，你觉得对吗？"
            )

        return True

    # ═══════════════════════════════════════════════
    # 共生反馈
    # ═══════════════════════════════════════════════

    def _adjust_strategy_from_feedback(self):
        recent = self._get_recent_validated_edges(7)
        if len(recent) < 3:
            return
        v = sum(1 for e in recent if e["status"] == "validated")
        r = sum(1 for e in recent if e["status"] == "rejected")
        total = v + r
        if total == 0:
            return
        rate = v / total
        if rate < 0.3:
            self.config["max_hypotheses_per_run"] = max(1, int(3 * rate))
            self.config["prompt_temperature"] = max(0.2, 0.5 * rate)
            print(f"[Catalyst] 📉 接受率 {rate:.0%}，收缩: max={self.config['max_hypotheses_per_run']} T={self.config['prompt_temperature']:.2f}")
        elif rate > 0.8:
            self.config["max_hypotheses_per_run"] = min(5, int(5 * rate))
            self.config["prompt_temperature"] = min(0.9, 0.5 + 0.5 * rate)
            print(f"[Catalyst] 📈 接受率 {rate:.0%}，扩张: max={self.config['max_hypotheses_per_run']} T={self.config['prompt_temperature']:.2f}")

    def _get_recent_validated_edges(self, days: int = 7) -> list[dict]:
        g = self.topology.graph
        cutoff = self.clock.now_ts() - days * 86400
        recent = []
        for u, v, data in g.edges(data=True):
            status = data.get("status", "")
            if status in ("validated", "rejected"):
                ts = data.get("validated_at", 0) or data.get("born_at", 0)
                if ts >= cutoff:
                    recent.append({"status": status, "confidence": data.get("confidence", 0.5)})
        return recent

    def _build_introspection_context(self) -> str:
        g = self.topology.graph
        nodes = g.number_of_nodes()
        edges = g.number_of_edges()
        density = edges / max(1, nodes * (nodes - 1))
        communities = self.topology.community_detect()
        community_count = len(communities) if communities else 0
        scanned = len(self._scanned)
        acceptance = self._get_acceptance_rate()

        parts = []
        if density < 0.02:
            parts.append(f"图库稀疏（{nodes}节点，密度{density:.4f}），优先寻找跨区域连接")
        elif density > 0.1:
            parts.append(f"图库稠密（{nodes}节点，密度{density:.4f}），优先发现矛盾或冗余")
        else:
            parts.append(f"图库中等（{nodes}节点，密度{density:.4f}）")

        if community_count > 5:
            parts.append(f"图库碎片化（{community_count}个社区），需要跨社区桥梁")

        if scanned > 0:
            parts.append(f"本轮已扫描 {scanned} 个薄弱区域，避免重复")

        if acceptance is not None:
            if acceptance < 0.4:
                parts.append(f"近期假设接受率仅 {acceptance:.0%}，请生成更保守的关联")
            elif acceptance > 0.7:
                parts.append(f"近期假设接受率 {acceptance:.0%}，可以尝试更大胆的关联")

        return "\n".join(parts) if parts else "图库状态正常，自由探索"

    def _get_acceptance_rate(self) -> Optional[float]:
        recent = self._get_recent_validated_edges(7)
        v = sum(1 for e in recent if e["status"] == "validated")
        r = sum(1 for e in recent if e["status"] == "rejected")
        total = v + r
        return v / total if total > 0 else None

    def _get_bot_name(self) -> str:
        try:
            root = self.topology.find_root_node()
            if root:
                data = self.topology.graph.nodes[root].get("data", {})
                name = data.get("content", "藤蔓")
                return name if len(name) <= 10 else "藤蔓"
        except:
            pass
        return "藤蔓"