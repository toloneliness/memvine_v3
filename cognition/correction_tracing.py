# cognition/correction_tracing.py
"""
修正追溯系统 (Correction Tracing)
- 将"修正"实例化为图中的 CorrectionEvent 节点
- 提供修正历史的 2 跳回溯查询
- 不做裁决，只做见证——保留错误的记忆作为"认知褶皱"
"""

import uuid
import time


class CorrectionTracer:
    """修正事件追踪器 —— 把每一次修正变成图中不可篡改的认知事件"""

    def __init__(self, topology):
        self.topology = topology

    # ── 创建修正事件 ──

    def record_correction(
        self,
        target_entity: str,
        old_value: str,
        new_value: str,
        action: str,          # "deny" | "update"
        now_ts: float = None,
        source_round: int = 0,
    ) -> str | None:
        """
        在图里创建一个 CorrectionEvent 节点，并连接到被修正的实体。
        返回事件节点 ID，失败返回 None。
        """
        if now_ts is None:
            now_ts = self.topology.clock.now_ts()

        target_nid = self._find_entity_node(target_entity)
        if not target_nid:
            return None

        event_id = f"corr_{uuid.uuid4().hex[:8]}"

        self.topology.graph.add_node(
            event_id,
            node_type="correction_event",
            correction_type="user_correction",
            target_entity=target_entity,
            old_value=old_value,
            new_value=new_value,
            action=action,
            born_at=now_ts,
            source_round=source_round,
            summary=f"「{target_entity}」从「{old_value}」修正为「{new_value}」",
        )

        self.topology.connect(
            event_id, target_nid,
            relation="corrects",
            weight=2.0,
        )

        print(f"   [修正追溯] 📝 {event_id}: {target_entity} {old_value} → {new_value}")
        return event_id

    # ── 查询修正历史 ──

    def query_history(self, entity_name: str, max_depth: int = 3) -> list[dict]:
        """
        查询某个实体的修正历史链。
        返回按时间排序的修正事件列表，最近的在前面。
        """
        target_nid = self._find_entity_node(entity_name)
        if not target_nid:
            return []

        events = []
        for src, dst, data in self.topology.graph.in_edges(target_nid, data=True):
            if data.get("relation") != "corrects":
                continue
            node = self.topology.graph.nodes.get(src, {})
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

    def get_current_with_trace(self, entity_name: str) -> dict:
        """
        获取实体的当前值 + 修正轨迹。
        返回格式适合直接注入 LLM 上下文。
        """
        history = self.query_history(entity_name)

        if not history:
            target_nid = self._find_entity_node(entity_name)
            if target_nid:
                nd = self.topology.graph.nodes[target_nid]
                return {
                    "entity": entity_name,
                    "current_value": nd.get("entity_name", entity_name),
                    "correction_count": 0,
                    "trace": [],
                    "narrative": f"关于「{entity_name}」，我没有记录到任何修正历史。",
                }
            return {"entity": entity_name, "current_value": None, "correction_count": 0, "trace": []}

        latest = history[0]
        narrative = self._build_narrative(entity_name, history)

        return {
            "entity": entity_name,
            "current_value": latest["new_value"],
            "correction_count": len(history),
            "trace": history,
            "narrative": narrative,
        }

    def _build_narrative(self, entity_name: str, history: list[dict]) -> str:
        """生成修正历史的自然语言叙述"""
        parts = [f"关于「{entity_name}」，我经历了 {len(history)} 次认知修正："]
        for i, h in enumerate(history):
            parts.append(
                f"  第{i+1}次：从「{h['old_value']}」修正为「{h['new_value']}」"
                f"（来源：用户主动纠正）"
            )
        parts.append(f"  当前确信值：{history[0]['new_value']}")
        return "\n".join(parts)

    # ── 内部工具 ──

    def _find_entity_node(self, name: str) -> str | None:
        if not name:
            return None
        for nid, attrs in self.topology.graph.nodes(data=True):
            if attrs.get("entity_name") == name:
                return nid
        return None