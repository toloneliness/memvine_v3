# cognition/proactive/proactive_engine.py
"""主动认知总调度引擎 —— 基于当下对话的实时感知，决定是否、何时、如何主动表达"""

from dataclasses import dataclass, field
from typing import Optional
from collections import deque
import time

from .tension_field import TensionField
from .epistemic_monitor import EpistemicMonitor, EpistemicState

@dataclass
class TopicTrapResult:
    """话题陷阱检测结果"""
    trapped: bool
    entity: str
    epistemic_state: EpistemicState
    round_count: int
    density: float

@dataclass
class ProactiveAction:
    """主动行为：一个准备向用户表达的内容"""
    action_type: str          # "topic_trap" | "tension_hotspot" | "curiosity_find"
    priority: int             # 1=最高(话题陷阱), 2=中(相关张力), 3=低(好奇心)
    data: dict                # 纯数据描述，不包含行为指令
    createdAt: float = field(default_factory=time.time)

class ProactiveEngine:
    """主动认知总调度引擎"""

    def __init__(self, topology, llm_engine=None, clock=None):
        self.clock = clock
        self.tension = TensionField(clock=self.clock)
        self.epistemic = EpistemicMonitor()
        self.topology = topology
        self.llm = llm_engine

        self._topic_history: deque = deque(maxlen=10)
        self._current_topic: str = ""
        self._topic_rounds: int = 0

        self._recently_expressed: deque = deque(maxlen=30)
        self.validator = None
        from .stance_selector import StanceSelector
        self.stance_selector = StanceSelector()
    def assess_current_topic(self, user_input: str, semantic: dict) -> Optional[TopicTrapResult]:
        """评估当前话题：检测信息密度和话题陷阱"""
        target = semantic.get("target", "")
        if not target:
            return None

        # 追踪话题连续轮数
        if target == self._current_topic:
            self._topic_rounds += 1
        else:
            self._current_topic = target
            self._topic_rounds = 1

        self._topic_history.append({
            "topic": target, "rounds": self._topic_rounds, "ts": time.time()
        })

        # C路径：图密度推断
        graph_state = self.epistemic.assess_from_graph(target, self.topology)

        # B路径：LLM 认知评估（如果 semantic 有扩展字段）
        llm_assessment = self.epistemic.assess_from_llm(semantic)

        # B+C 融合
        combined_state = self.epistemic.combine(llm_assessment, graph_state)

        # D路径：内省知识检查（系统自己的知识结构）
        introspective_nodes = [
            nid for nid in self.topology.graph.nodes()
            if self.topology.graph.nodes[nid].get("data", {}).get("source") == "introspective"
            and target.lower() in str(self.topology.graph.nodes[nid].get("data", {}).get("content", "")).lower()
        ]
        if introspective_nodes:
            combined_state = EpistemicState.CONFIDENT

        # 检测话题陷阱
        trapped = self.epistemic.track_topic_stay(
            target, self._topic_rounds, combined_state
        )

        if trapped:
            return TopicTrapResult(
                trapped=True, entity=target,
                epistemic_state=combined_state,
                round_count=self._topic_rounds,
                density=graph_state.density,
            )

        return TopicTrapResult(
            trapped=False, entity=target,
            epistemic_state=combined_state,
            round_count=self._topic_rounds,
            density=graph_state.density,
        )

    def check_tension_hotspots(self) -> list[ProactiveAction]:
        """检查张力热点"""
        hotspots = self.tension.get_hotspots(threshold=0.7)
        actions = []
        for hs in hotspots:
            if hs.entity in self._recently_expressed:
                continue
            tension_type = hs.tensions[0].tension_type if hs.tensions else "unknown"
            desc = hs.tensions[0].description if hs.tensions else ""
            action = ProactiveAction(
                action_type="tension_hotspot",
                priority=2,
                data={
                    "entity": hs.entity,
                    "tension_type": tension_type,
                    "tension_value": round(hs.combined_tension, 2),
                    "description": desc,
                    "source": hs.tensions[0].source_task if hs.tensions else "",
                },
            )
            actions.append(action)
            self._recently_expressed.append(hs.entity)
        return actions

    def check_correlation(self, user_input: str, semantic: dict) -> list[ProactiveAction]:
        """检查当前话题与 pending 张力的相关性"""
        target = semantic.get("target", "")
        if not target:
            return []

        actions = []
        for nid in self.tension.needs_action(threshold=0.6):
            if nid in self._recently_expressed:
                continue
            if target in nid or nid in target:
                node = self.tension._nodes.get(nid)
                if node:
                    action = ProactiveAction(
                        action_type="correlation",
                        priority=2,
                        data={
                            "entity": nid,
                            "tension_type": node.tension_type,
                            "tension_value": round(node.tension, 2),
                            "description": node.description,
                            "source": node.source_task,
                        },
                    )
                    actions.append(action)
                    self._recently_expressed.append(nid)
        return actions

    def generate_actions(self, user_input: str, semantic: dict,
                         max_actions: int = 2) -> list[ProactiveAction]:
        """生成主动行为列表（每个对话轮次调用）"""
        actions: list[ProactiveAction] = []

        # 优先级1：话题陷阱
        trap = self.assess_current_topic(user_input, semantic)
        if trap and trap.trapped:
            trap_key = f"trap_{trap.entity}"
            if trap_key not in self._recently_expressed:
                actions.append(ProactiveAction(
                    action_type="topic_trap",
                    priority=1,
                    data={
                        "entity": trap.entity,
                        "epistemic_state": trap.epistemic_state.value,
                        "density": round(trap.density, 3),
                        "rounds": trap.round_count,
                    },
                ))
                self._recently_expressed.append(trap_key)
        # 优先级2：相关性触发
        actions.extend(self.check_correlation(user_input, semantic))

        # 优先级2：张力热点
        actions.extend(self.check_tension_hotspots())

        # 不确定审计：低置信度催化候选暴露给用户
        uncertain = self._check_uncertain_audits()
        for audit in uncertain[:1]:
            audit_key = f"audit_{audit['node_id']}"
            if audit_key not in self._recently_expressed:
                actions.append(ProactiveAction(
                    action_type="uncertain_audit",
                    priority=2,
                    data={
                        "node_id": audit["node_id"],
                        "content": audit["content"],
                        "confidence": audit["confidence"],
                        "reason": audit["reason"],
                    },
                ))
                self._recently_expressed.append(audit_key)

        # 检查是否有待验证的问题需要夹带给用户
        if self.validator:
            for ctx in self.validator.active_validations:
                if ctx.resolved or ctx.conversation_turn > 0:
                    continue
                v_key = f"val_{ctx.edge_key}"
                if v_key not in self._recently_expressed:
                    g = self.topology.graph
                    u_content = (g.nodes.get(ctx.edge_key[0], {}).get("data", {}) or {}).get("content", "")
                    actions.append(ProactiveAction(
                        action_type="validation_question",
                        priority=1,
                        data={
                            "content": u_content[:30],
                            "concept": (g.nodes.get(ctx.edge_key[1], {}).get("data", {}) or {}).get("content", "")[:30],
                            "question": ctx.question,
                        },
                    ))
                    self._recently_expressed.append(v_key)
                    ctx.conversation_turn = 0

        # 按优先级排序，限制数量
        actions.sort(key=lambda a: a.priority)
        return actions[:max_actions]

    def on_maintenance_issue(self, issue_type: str, description: str,
                             source_task: str = "", related_entity: str = ""):
        """维护任务完成后调用，向张力场注入"""
        node_id = related_entity or f"{source_task}_{issue_type}"
        self.tension.inject(
            node_id=node_id,
            tension_type=issue_type,
            description=description,
            source_task=source_task,
            initial_tension=0.4,
        )

    def on_curiosity_find(self, candidates: list[dict]):
        """好奇心扫描结果接入"""
        for c in candidates[:3]:
            entity = c.get("entity", "")
            question = c.get("question", "")
            if entity and question:
                self.tension.inject(
                    node_id=f"curiosity_{entity}",
                    tension_type="curiosity",
                    description=question,
                    source_task="curiosity_scan",
                    initial_tension=0.35,
                )

    def on_answer(self, user_input: str, semantic: dict):
        """用户回应后：释放相关张力"""
        self._last_user_input = user_input
        target = semantic.get("target", "")
        if target:
            for nid in list(self.tension._nodes.keys()):
                node = self.tension._nodes[nid]
                parts = nid.split("_", 1)
                entity_part = parts[1] if len(parts) > 1 else nid
                if target == entity_part or target == nid:
                    self.tension.release(nid, amount=0.6)

        # 重置话题追踪（如果话题变了）
        if target != self._current_topic:
            self._current_topic = target
            self._topic_rounds = 1
            # 话题切换时清理过时的验证问题
            if self.validator:
                self.validator.active_validations.clear()

        # 自然衰减
        self.tension.apply_natural_decay()

        # 验证闭环：用户回应后更新 pending_validation 边的置信度
        self._validate_edges(user_input, target)

    def build_proactive_data(self, actions: list[ProactiveAction]) -> dict:
        """将主动行为构建为纯数据描述，不包含任何行为指令"""
        if not actions:
            return {}

        result = {}
        first_action = actions[0] if actions else None
        stance = self.stance_selector.select(
            epistemic_state=getattr(first_action, 'epistemic_state', None) if first_action else None,
            topic_trap=any(a.action_type == "topic_trap" for a in actions)
        )
        result["stance"] = stance.stance.value
        for action in actions:
            if action.action_type == "topic_trap":
                d = action.data
                result["topic_trap"] = {
                    "cypher": (
                        f"MATCH (n {{name: '{d['entity']}'}})-[*1..2]-(m) "
                        "RETURN count(DISTINCT m) AS density"
                    ),
                    "result": {
                        "entity": d["entity"],
                        "epistemic_state": d["epistemic_state"],
                        "density": d["density"],
                        "rounds": d["rounds"],
                    },
                }
            elif action.action_type == "tension_hotspot":
                result.setdefault("tensions", []).append({
                    "cypher": (
                        f"MATCH (n {{name: '{action.data['entity']}'}})-[r]-(m) "
                        "WHERE r.tension > 0.7 RETURN n.name, type(r), r.tension"
                    ),
                    "result": {
                        "entity": action.data["entity"],
                        "description": action.data["description"],
                        "tension_value": action.data["tension_value"],
                        "source": action.data["source"],
                    },
                })
            elif action.action_type == "correlation":
                result.setdefault("tensions", []).append({
                    "cypher": (
                        f"MATCH (n {{name: '{action.data['entity']}'}})-[r]-(m) "
                        "RETURN n.name, type(r), m.name"
                    ),
                    "result": {
                        "entity": action.data["entity"],
                        "description": action.data["description"],
                        "tension_value": action.data["tension_value"],
                    },
                })
            elif action.action_type == "uncertain_audit":
                d = action.data
                result.setdefault("uncertain", []).append({
                    "cypher": (
                        f"MATCH (n) WHERE n.content CONTAINS '{d['content'][:30]}' "
                        "RETURN n.content, n.confidence"
                    ),
                    "result": {
                        "content": d["content"][:30],
                        "reason": d["reason"],
                    },
                })
            elif action.action_type == "validation_question":
                d = action.data
                result.setdefault("validation", []).append({
                    "cypher": (
                        f"MATCH (a)-[r]-(b) "
                        f"WHERE a.name CONTAINS '{d['content'][:30]}' "
                        f"AND b.name CONTAINS '{d['concept']}' "
                        "RETURN a.name AS entity_a, b.name AS entity_b, r.status AS status, r.question AS question"
                    ),
                    "result": {
                        "entity_a": d["content"][:30],
                        "entity_b": d["concept"],
                        "status": "pending_validation",
                        "question": d["question"],
                    },
                })

        return result

    def _check_uncertain_audits(self) -> list[dict]:
        if not getattr(self, 'catalyst', None):
            return []
        results = list(self.catalyst.last_audit_results)
        uncertain = [
            {"node_id": r["node_id"], "content": r["content"],
             "confidence": r["catalysis_confidence"],
             "reason": r["reason"]}
            for r in results
            if 0.2 < r.get("catalysis_confidence", 0.5) < 0.7
        ]
        uncertain.sort(key=lambda x: x["confidence"])
        return uncertain[:2]


    def _validate_edges(self, user_input: str, target: str):
        """委托给 EdgeValidator（不再全局扫描）"""
        if not hasattr(self, 'validator') or not self.validator:
            return
        self.validator.on_user_message(user_input, [])
