from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import time


@dataclass
class EventMolecule:
    id: str
    agent: str
    action: str
    target: str
    content: str
    source: str = ""
    valence: float = 0.0
    complexity: float = 0.5
    expressiveness: float = 0.8
    born_at: float = field(default_factory=time.time)
    last_activated: float = field(default_factory=time.time)

    knowledge: Optional[dict] = None

    def touch(self, now_ts: float = None):
        self.last_activated = now_ts if now_ts is not None else time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent": self.agent,
            "action": self.action,
            "target": self.target,
            "content": self.content,
            "source": self.source,
            "valence": self.valence,
            "complexity": self.complexity,
            "expressiveness": self.expressiveness,
            "born_at": self.born_at,
            "last_activated": self.last_activated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EventMolecule":
        return cls(
            id=d.get("id", ""),
            agent=d.get("agent", ""),
            action=d.get("action", ""),
            target=d.get("target", ""),
            content=d.get("content", ""),
            source=d.get("source", ""),
            valence=d.get("valence", 0.0),
            complexity=d.get("complexity", 0.5),
            expressiveness=d.get("expressiveness", 0.8),
            born_at=d.get("born_at", time.time()),
            last_activated=d.get("last_activated", time.time()),
            knowledge=d.get("knowledge", None),
        )


@dataclass
class Trace:
    source_id: str
    target_id: str
    relation: str = "associated_with"
    flow_count: int = 0
    last_flow_time: float = field(default_factory=time.time)
    emotion_snapshot: Dict[str, float] = field(default_factory=dict)
    confidence: float = 1.0
    status: str = ""

    def get_weight(self, now_ts: float = None) -> float:
        if now_ts is None:
            now_ts = time.time()
        time_elapsed = max(now_ts - self.last_flow_time, 1.0)
        base = max(1.0, self.flow_count)
        decay = 1.0 / (time_elapsed / 86400.0 + 1.0)
        return base * decay

    def rewrite(self, emotion: Dict[str, float] | None = None, now_ts: float = None):
        self.last_flow_time = now_ts if now_ts is not None else time.time()
        self.flow_count += 1
        if emotion:
            self.emotion_snapshot = emotion.copy()

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "flow_count": self.flow_count,
            "last_flow_time": self.last_flow_time,
            "emotion_snapshot": self.emotion_snapshot,
            "confidence": self.confidence,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        return cls(
            source_id=d.get("source_id", ""),
            target_id=d.get("target_id", ""),
            relation=d.get("relation", "associated_with"),
            flow_count=d.get("flow_count", 0),
            last_flow_time=d.get("last_flow_time", time.time()),
            emotion_snapshot=d.get("emotion_snapshot", {}),
            confidence=d.get("confidence", 1.0),
            status=d.get("status", ""),
        )