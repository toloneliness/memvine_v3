"""
上下文构建器 —— 构建交给 LLM 的唯一 JSON 上下文。
{ identity, time, memory }
identity 和 time 始终确定，memory 是检索结果。
"""
from __future__ import annotations
import json
from typing import Dict, List

class ContextBuilder:
    def __init__(self, topology, clock, vector_store, prestore, finding_store=None):
        self.topo = topology
        self.clock = clock
        self.vector_store = vector_store
        self.prestore = prestore
        self.finding_store = finding_store

    def build(self, user_input: str, last_talk_ts: float = None) -> str:
        context = {
            "identity": self._build_identity(),
            "time": self._build_time(last_talk_ts),
            "memory": self._search_memory(user_input),
        }
        return json.dumps(context, ensure_ascii=False, indent=2)

    def _build_identity(self) -> Dict:
        state = getattr(self.topo, "identity_state", {})
        self_name = state.get("self_name") or "藤蔓"
        other_name = state.get("other_name") or "用户"
        self_conf = state.get("self_name_conf", 0)
        other_conf = state.get("other_name_conf", 0)

        identity_edges = self.topo.subgraph("identity")
        relationships = []
        for t in identity_edges:
            relationships.append({
                "entity": t.target_id,
                "relation": t.metadata.get("action", t.metadata.get("relation", "关联")),
                "confidence": round(min(t.weight / 10, 1.0), 2),
            })
        return {
            "self": self_name,
            "user": other_name,
            "self_confidence": self_conf,
            "user_confidence": other_conf,
            "relationships": relationships,
        }

    def _build_time(self, last_talk_ts: float = None) -> Dict:
        now = self.clock.now_local()
        result = {
            "now": now.format("YYYY年MM月DD日 HH:mm"),
            "weekday": now.format("dddd"),
            "season": self._get_season(now.month),
        }
        if last_talk_ts:
            ago = now.timestamp() - last_talk_ts
            if ago < 60:
                result["last_talk"] = "刚刚"
            elif ago < 3600:
                result["last_talk"] = f"{int(ago // 60)}分钟前"
            elif ago < 86400:
                result["last_talk"] = f"{int(ago // 3600)}小时前"
            else:
                result["last_talk"] = f"{int(ago // 86400)}天前"
        else:
            result["last_talk"] = "首次对话"
        return result

    def _get_season(self, month: int) -> str:
        if month in (3, 4, 5):
            return "春"
        elif month in (6, 7, 8):
            return "夏"
        elif month in (9, 10, 11):
            return "秋"
        else:
            return "冬"

    def _search_memory(self, user_input: str) -> Dict:
        result = {"hit": [], "miss": [], "recent": [], "findings": []}

        # 已有发现
        if self.finding_store:
            relevant = self.finding_store.get_relevant(user_input, limit=5)
            result["findings"] = [
                {"type": f.type, "content": f.content}
                for f in relevant
            ]

        # 向量检索
        try:
            doc_results = self.vector_store.documents.query(
                query_texts=[user_input], n_results=5
            )
            if doc_results and doc_results.get("documents") and doc_results["documents"][0]:
                for i, doc in enumerate(doc_results["documents"][0]):
                    distance = doc_results.get("distances", [[0]] * 5)[0][i] if doc_results.get("distances") else 0
                    relevance = round(max(0, 1 - distance), 2) if distance else 0.5
                    result["hit"].append({
                        "narrative": doc,
                        "relevance": relevance,
                    })
        except Exception:
            pass

        # 近期对话
        recent = self.prestore.get_recent(6)
        result["recent"] = [
            {"speaker": e.speaker, "content": e.content[:100], "time": e.timestamp}
            for e in recent
        ]

        return result
