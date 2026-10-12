"""发现存储 —— 消化产物的读写"""
from __future__ import annotations
import json
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

@dataclass
class Finding:
    id: str = ""
    type: str = "fact"      # fact / pattern / shift / rule / barren
    content: str = ""
    evidence: list = field(default_factory=list)
    timescale: str = "day"
    status: str = "active"  # active / retired

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "evidence": self.evidence,
            "timescale": self.timescale,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(
            id=d.get("id", ""),
            type=d.get("type", "fact"),
            content=d.get("content", ""),
            evidence=d.get("evidence", []),
            timescale=d.get("timescale", "day"),
            status=d.get("status", "active"),
        )

class FindingStore:
    def __init__(self, data_dir: str = "memvine_data/findings"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"f_{ts}_{self._counter:04d}"

    def _path_for(self, finding_type: str) -> Path:
        return self.data_dir / f"{finding_type}s.json"

    def add_many(self, findings: List[Finding], dedup: bool = True) -> int:
        if dedup:
            findings = self._deduplicate(findings)
        count = 0
        for f in findings:
            self.add(f)
            count += 1
        return count

    def _deduplicate(self, new_findings: List[Finding]) -> List[Finding]:
        active = self.get_active()
        if not active:
            return new_findings

        kept = []
        for nf in new_findings:
            is_dup = False
            for af in active:
                sim = self._content_similarity(nf.content, af.content)

                if nf.type == "fact" and af.type == "fact" and sim > 0.85:
                    af.content = nf.content if len(nf.content) > len(af.content) else af.content
                    is_dup = True
                    break

                if nf.type == "fact" and af.type == "pattern" and sim > 0.6:
                    pass

                if nf.type == "pattern" and af.type == "pattern" and sim > 0.85:
                    is_dup = True
                    break

            if not is_dup:
                kept.append(nf)

        return kept

    @staticmethod
    def _content_similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        words_a = set(a)
        words_b = set(b)
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def add(self, finding: Finding) -> Finding:
        if not finding.id:
            finding.id = self._next_id()
        path = self._path_for(finding.type)
        existing = self._read_all(finding.type)
        existing.append(finding.to_dict())
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return finding

    def _read_all(self, finding_type: str) -> list:
        path = self._path_for(finding_type)
        if not path.exists():
            return []
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_active(self, finding_type: str = None) -> List[Finding]:
        types = [finding_type] if finding_type else ["fact", "pattern", "shift", "rule"]
        results = []
        for t in types:
            for d in self._read_all(t):
                f = Finding.from_dict(d)
                if f.status == "active":
                    results.append(f)
        return results

    def get_relevant(self, query: str, limit: int = 5) -> List[Finding]:
        active = self.get_active()
        if not query:
            return active[:limit]
        scored = []
        for f in active:
            score = sum(1 for word in query if word in f.content)
            if score > 0:
                scored.append((score, f))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:limit]]

    def retire(self, finding_id: str):
        for t in ["fact", "pattern", "shift", "rule"]:
            path = self._path_for(t)
            if not path.exists():
                continue
            data = self._read_all(t)
            modified = False
            for d in data:
                if d["id"] == finding_id:
                    d["status"] = "retired"
                    modified = True
            if modified:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return

    @property
    def stats(self) -> dict:
        result = {}
        for t in ["fact", "pattern", "shift", "rule", "barren"]:
            data = self._read_all(t)
            active = sum(1 for d in data if d.get("status") == "active")
            result[t] = {"total": len(data), "active": active}
        return result