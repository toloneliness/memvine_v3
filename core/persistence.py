import json
import os
import asyncio
import time
import uuid
import shutil
import threading
from pathlib import Path
import pendulum
from config import SYSTEM_TIMEZONE

class MemvineEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, pendulum.DateTime):
            return obj.isoformat()
        return super().default(obj)


class PersistenceEngine:
    def __init__(self, save_dir="memvine_saves", max_backups=3):
        self.save_dir = Path(save_dir)
        self.max_backups = max_backups
        self.current_save_path = self.save_dir / "memvine_active.json"
        self.temp_save_path = self.save_dir / "memvine_active.tmp"
        self.is_dirty = False
        self._auto_save_task = None
        self._save_lock = threading.Lock()
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def save_state(self, topology_data=None, prestore=None, birth_time=None, last_talk_ts=None, turn_count=0, **kwargs):
        with self._save_lock:
            state_snapshot = {
                "epoch": pendulum.now(SYSTEM_TIMEZONE).timestamp(),
                "topology_data": topology_data,
                "prestore": prestore,
                "birth_time": birth_time,
                "last_talk_ts": last_talk_ts,
                "turn_count": turn_count,
            }

            try:
                with open(self.temp_save_path, 'w', encoding='utf-8') as f:
                    json.dump(state_snapshot, f, ensure_ascii=False, indent=2, cls=MemvineEncoder)

                shutil.move(str(self.temp_save_path), str(self.current_save_path))
                self._rotate_backups()

                self.is_dirty = False
                print(f"[休眠成功] 生命体已安全沉睡于 {self.current_save_path}")
            except Exception as e:
                print(f"[休眠失败] 发生致命错误: {e}")
                if self.temp_save_path.exists():
                    self.temp_save_path.unlink()

    def load_state(self):
        with self._save_lock:
            if not self.current_save_path.exists():
                print("[苏醒] 未检测到历史存档，数字生命体初次降临！")
                return None
            try:
                with open(self.current_save_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                sleep_duration = pendulum.now(SYSTEM_TIMEZONE).timestamp() - state.get("epoch", pendulum.now(SYSTEM_TIMEZONE).timestamp())
                print(f"[苏醒成功] 生命体已苏醒，本次休眠时长: {sleep_duration:.2f}秒")
                # 恢复上次对话时间戳
                if state.get("last_talk_ts"):
                    print(f"   ⏰ 上次对话: {pendulum.from_timestamp(state['last_talk_ts'], tz=SYSTEM_TIMEZONE).to_datetime_string()}")
                return state
            except Exception as e:
                print(f"[苏醒警告] 存档损坏 ({e})，启动优雅降级：遗忘过去，重新出生。")
                return None

    def _rotate_backups(self):
        try:
            backups = sorted(self.save_dir.glob("memvine_backup_*.json"), key=os.path.getmtime)
            if len(backups) >= self.max_backups:
                backups[0].unlink()
            backup_name = self.save_dir / f"memvine_backup_{uuid.uuid4().hex[:8]}.json"
            shutil.copy2(self.current_save_path, backup_name)
        except Exception as e:
            print(f"[备份警告] 备份轮转失败: {e}")

    async def start_heartbeat(self, cortex_instance, interval=300):
        while True:
            await asyncio.sleep(interval)
            if self.is_dirty:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self.save_state,
                    topology_data=cortex_instance.topology.to_dict(),
                    prestore=cortex_instance.prestore.to_dict(),
                    birth_time=cortex_instance.birth_time,
                    last_talk_ts=cortex_instance._last_talk_ts,
                    turn_count=cortex_instance._turn_count,
                )
                await loop.run_in_executor(None, self._rotate_backups)

    def mark_dirty(self):
        self.is_dirty = True