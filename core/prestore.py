"""
预存储池 —— 新数据源引擎的入口。
只存不解析：时间 + 说话人 + 原话。
不做任何语义判断。只是接住。
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class PreStoreEntry:
    timestamp: str
    speaker: str
    content: str
    stored_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "speaker": self.speaker,
            "content": self.content,
            "stored_at": self.stored_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "PreStoreEntry":
        return cls(
            timestamp=d["timestamp"],
            speaker=d["speaker"],
            content=d["content"],
            stored_at=d.get("stored_at", time.time()),
        )

class PreStorePool:
    """预存储池：只存不解析。容量有限，只追加，不修改。"""

    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self.entries: List[PreStoreEntry] = []

    def append(self, timestamp: str, speaker: str, content: str) -> PreStoreEntry:
        entry = PreStoreEntry(timestamp=timestamp, speaker=speaker, content=content)
        self.entries.append(entry)
        self._trim()
        return entry

    def _trim(self):
        while len(self.entries) > self.max_entries:
            self.entries.pop(0)

    def get_recent(self, n: int = 10) -> List[PreStoreEntry]:
        return self.entries[-n:]

    def export_for_digestion(self) -> str:
        lines = []
        for entry in self.entries:
            name = "用户" if entry.speaker == "user" else "藤蔓"
            lines.append(f"[{entry.timestamp}] {name}: {entry.content}")
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "max_entries": self.max_entries,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "PreStorePool":
        pool = cls(max_entries=d.get("max_entries", 200))
        pool.entries = [PreStoreEntry.from_dict(e) for e in d.get("entries", [])]
        return pool

    def __len__(self):
        return len(self.entries)
