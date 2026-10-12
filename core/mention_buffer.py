# f:\memvine_v3\core\mention_buffer.py
"""候选实体缓冲区 —— 阈值升级 + 否定清理 + 弱关联"""

from datetime import datetime, timezone, timedelta


class MentionBuffer:
    def __init__(self):
        self._pool: dict[str, dict] = {}

    def add(self, name: str, entity_type: str, round_id: int, ts: float, context: str = ""):
        if not name or not name.strip():
            return
        name = name.strip()
        if name not in self._pool:
            self._pool[name] = {
                "mentions": [],
                "entity_type": entity_type,
                "negated": False,
                "first_seen": ts,
                "distinct_days": set(),
                "weak_links": set(),
                "promoted": False,
            }
        entry = self._pool[name]
        if entry["promoted"]:
            return
        entry["mentions"].append({"ts": ts, "round_id": round_id, "context": context[:80]})
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        entry["distinct_days"].add(day)
        entry["entity_type"] = entity_type or entry["entity_type"]

    def negate(self, name: str):
        if name and name.strip() in self._pool:
            self._pool[name.strip()]["negated"] = True

    def add_weak_link(self, a: str, b: str):
        if a and b and a.strip() in self._pool and b.strip() in self._pool:
            self._pool[a.strip()]["weak_links"].add(b.strip())
            self._pool[b.strip()]["weak_links"].add(a.strip())

    def check_promotion(self, name: str) -> bool:
        e = self._pool.get(name.strip())
        if not e or e["promoted"]:
            return False
        if e["negated"]:
            return False
        if len(e["mentions"]) < 3:
            return False
        if len(e["distinct_days"]) < 2:
            return False
        return True

    def promote(self, name: str):
        if name.strip() in self._pool:
            self._pool[name.strip()]["promoted"] = True

    def get_promotable(self) -> list[tuple[str, str, set]]:
        result = []
        for name, e in self._pool.items():
            if self.check_promotion(name):
                result.append((name, e["entity_type"], e["weak_links"]))
        return result

    def cleanup_expired(self, max_age_hours: int = 72, now_ts: float = None):
        if now_ts is None:
            now_ts = datetime.now(timezone.utc).timestamp()
        cutoff = now_ts - max_age_hours * 3600
        expired = [
            name for name, e in self._pool.items()
            if not e["promoted"] and e["first_seen"] < cutoff
        ]
        for name in expired:
            del self._pool[name]
        for e in self._pool.values():
            e["weak_links"] = {w for w in e["weak_links"] if w in self._pool}

    def snapshot(self) -> dict:
        return {
            name: {
                "mentions": len(e["mentions"]),
                "type": e["entity_type"],
                "negated": e["negated"],
                "days": len(e["distinct_days"]),
                "promoted": e["promoted"],
                "links": len(e["weak_links"]),
            }
            for name, e in self._pool.items()
        }

    def to_dict(self) -> dict:
        return {
            name: {
                "mentions": e["mentions"],
                "entity_type": e["entity_type"],
                "negated": e["negated"],
                "first_seen": e["first_seen"],
                "distinct_days": list(e["distinct_days"]),
                "weak_links": list(e["weak_links"]),
                "promoted": e["promoted"],
            }
            for name, e in self._pool.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MentionBuffer":
        buf = cls()
        for name, e in data.items():
            buf._pool[name] = {
                "mentions": e.get("mentions", []),
                "entity_type": e.get("entity_type", ""),
                "negated": e.get("negated", False),
                "first_seen": e.get("first_seen", 0),
                "distinct_days": set(e.get("distinct_days", [])),
                "weak_links": set(e.get("weak_links", [])),
                "promoted": e.get("promoted", False),
            }
        return buf