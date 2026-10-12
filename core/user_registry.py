# core/user_registry.py
"""用户注册表 —— 最小化身份管理，与 Cortex 解耦"""
import json
import time
import os
from pathlib import Path


class UserProfile:
    __slots__ = ("user_id", "first_seen", "last_seen", "message_count")

    def __init__(self, user_id: str, first_seen: float = None):
        self.user_id = user_id
        self.first_seen = first_seen or time.time()
        self.last_seen = self.first_seen
        self.message_count = 0

    def touch(self):
        self.last_seen = time.time()
        self.message_count += 1

    def to_dict(self) -> dict:
        return {
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "message_count": self.message_count,
        }

    @classmethod
    def from_dict(cls, user_id: str, d: dict) -> "UserProfile":
        p = cls(user_id, d.get("first_seen", time.time()))
        p.last_seen = d.get("last_seen", p.first_seen)
        p.message_count = d.get("message_count", 0)
        return p

    def __repr__(self):
        return f"UserProfile({self.user_id}, msgs={self.message_count})"


class UserRegistry:
    def __init__(self, save_dir: str = "memvine_saves"):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.save_path = self.save_dir / "users.json"
        self._profiles: dict[str, UserProfile] = {}
        self._load()

    def get_or_create(self, user_id: str) -> UserProfile:
        if not user_id or not user_id.strip():
            return self._stranger()

        uid = user_id.strip()

        if uid.lower() == "stranger":
            return self._stranger()

        if uid in self._profiles:
            p = self._profiles[uid]
            p.touch()
            self._save()
            return p

        p = UserProfile(uid)
        self._profiles[uid] = p
        self._save()
        return p

    def is_registered(self, user_id: str) -> bool:
        return user_id and user_id.strip() in self._profiles

    def get(self, user_id: str) -> UserProfile | None:
        if not user_id:
            return None
        return self._profiles.get(user_id.strip())

    def _stranger(self) -> UserProfile:
        if "stranger" not in self._profiles:
            self._profiles["stranger"] = UserProfile("stranger")
        p = self._profiles["stranger"]
        p.touch()
        self._save()
        return p

    def _load(self):
        if not self.save_path.exists():
            return
        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for uid, d in data.items():
                self._profiles[uid] = UserProfile.from_dict(uid, d)
            print(f"📋 [用户注册表] 已加载 {len(self._profiles)} 个用户")
        except Exception as e:
            print(f"⚠ [用户注册表] 加载失败: {e}")

    def _save(self):
        try:
            data = {uid: p.to_dict() for uid, p in self._profiles.items()}
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠ [用户注册表] 保存失败: {e}")

    def list_users(self) -> list[UserProfile]:
        return [p for p in self._profiles.values() if p.user_id != "stranger"]