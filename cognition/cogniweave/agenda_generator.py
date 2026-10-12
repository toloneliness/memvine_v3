# cognition/cogniweave/agenda_generator.py
"""Layer 1: 认知议程设置 —— LLM 驱动的查询规划"""

import json
import time
import hashlib
from typing import Optional
from .models import QueryAgenda, QueryItem, Priority
from prompts import AGENDA_SYSTEM_PROMPT, AGENDA_USER_PROMPT, IDENTITY_SUBSYSTEM

class AgendaGenerator:
    def __init__(self, llm_engine, graph_tools, state_observer=None, proactive_engine=None):
        self.llm = llm_engine
        self.graph_tools = graph_tools
        self.state_observer = state_observer
        self.proactive = proactive_engine
        self._last_agenda: Optional[QueryAgenda] = None
        self._agenda_cache: dict[str, tuple[float, QueryAgenda]] = {}

    def generate(
        self,
        user_input: str,
        history_summary: str = "",
        force: bool = False,
        self_name: str = "MemVine",
        user_name: str = "对方",
    ) -> QueryAgenda:
        cache_key = hashlib.sha256(
            (user_input[:200] + history_summary[:100]).encode("utf-8")
        ).hexdigest()[:16]
        cached = self._agenda_cache.get(cache_key)
        cache_ttl = getattr(self, '_cache_ttl', 30)
        if cached and not force and time.time() - cached[0] < cache_ttl:
            return cached[1]

        tool_defs = self._format_tool_definitions()
        state_summary = self._build_state_summary()
        proactive_signals = self._build_proactive_signals()

        identity = IDENTITY_SUBSYSTEM.format(self_name=self_name, user_name=user_name)
        system = AGENDA_SYSTEM_PROMPT.format(
            identity=identity,
            self_name=self_name,
            tool_definitions=tool_defs,
            state_summary=state_summary,
            proactive_signals=proactive_signals,
        )
        user = AGENDA_USER_PROMPT.format(
            user_input=user_input,
            history_summary=history_summary or "（无历史）",
        )

        try:
            raw = self.llm.call(user, system=system, temperature=0.2)
            agenda = self._parse_agenda(raw)
            if agenda:
                self._last_agenda = agenda
                self._agenda_cache[cache_key] = (time.time(), agenda)
                return agenda
        except Exception as e:
            print(f"   [CogniWeave] 议程生成失败: {e}")

        return self._default_agenda(user_input)

    def _format_tool_definitions(self) -> str:
        tools = self.graph_tools.get_tool_definitions()
        lines = []
        for i, t in enumerate(tools):
            lines.append(f"模板{i+1}: {t['description']}")
            lines.append(f"  Cypher: {t['cypher']}")
            lines.append(f"  参数: {json.dumps(t['parameters'], ensure_ascii=False)}")
            lines.append("")
        return "\n".join(lines)

    def _build_state_summary(self) -> str:
        if not self.state_observer:
            return "状态观测器不可用"
        try:
            obs = self.state_observer.observe(last_talk_ts=0)
        except Exception:
            obs = {}
        nodes = self.graph_tools.topology.graph.number_of_nodes()
        edges = self.graph_tools.topology.graph.number_of_edges()
        return (
            f"节点总数: {nodes}, 边总数: {edges}, "
            f"认知负载: {obs.get('load', 'unknown')}, "
            f"负载等级: {obs.get('load_level', 'unknown')}"
        )

    def _build_proactive_signals(self) -> str:
        if not self.proactive:
            return "无活跃信号"
        signals = []
        try:
            hotspots = self.proactive.tension.get_hotspots(threshold=0.5)
            for hs in hotspots[:3]:
                for t in hs.tensions[:2]:
                    signals.append(f"张力: {t.tension_type} on {hs.entity} ({t.description[:60]})")
        except Exception:
            pass
        try:
            current_topic = self.proactive._current_topic
            if current_topic:
                round_count = self.proactive._topic_rounds
                signals.append(f"当前话题: {current_topic} (已持续{round_count}轮)")
        except Exception:
            pass
        return "\n".join(signals) if signals else "无活跃信号"

    def _parse_agenda(self, raw: str) -> Optional[QueryAgenda]:
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                return QueryAgenda.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"   [CogniWeave] 议程解析失败: {e}")
        return None

    def _default_agenda(self, user_input: str) -> QueryAgenda:
        return QueryAgenda(
            agenda=[
                QueryItem(
                    id="q_default",
                    intent="默认搜索",
                    cypher="MATCH (n) WHERE n.name CONTAINS $keyword OR n.content CONTAINS $keyword RETURN n.name AS name, n.type AS type LIMIT $top_k",
                    params={"keyword": user_input[:20], "top_k": 5},
                    priority=Priority.HIGH,
                ),
            ],
            max_concurrency=1,
            reasoning="议程生成失败，使用默认搜索",
        )