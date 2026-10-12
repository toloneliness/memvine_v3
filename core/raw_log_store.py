"""原始对话日志 —— JSONL 永久存储，只增不删"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import List

@dataclass
class RawMessage:
    id: str
    timestamp: str
    speaker: str              # "user" | "vine"
    content: str
    session_id: str = ""

class RawLogStore:
    def __init__(self, log_dir: str = "memvine_data/raw_logs", legacy_dir: str = "memvine_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_dir = Path(legacy_dir)
        self._checkpoint_path = self.log_dir / ".legacy_checkpoint"
        self._msg_counter = 0

    def _today_path(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{today}.jsonl"

    def _next_id(self) -> str:
        self._msg_counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"msg_{ts}_{self._msg_counter:04d}"

    def append(self, speaker: str, content: str, session_id: str = "") -> RawMessage:
        msg = RawMessage(
            id=self._next_id(),
            timestamp=datetime.now().isoformat(),
            speaker=speaker,
            content=content,
            session_id=session_id,
        )
        record = {
            "id": msg.id,
            "timestamp": msg.timestamp,
            "speaker": msg.speaker,
            "content": msg.content,
            "session_id": msg.session_id,
        }
        with open(self._today_path(), 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
        return msg

    def read_range(self, start_date: str, end_date: str = None) -> List[RawMessage]:
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        messages = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        while current <= end:
            path = self.log_dir / f"{current.strftime('%Y-%m-%d')}.jsonl"
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            d = json.loads(line)
                            messages.append(RawMessage(
                                id=d["id"],
                                timestamp=d["timestamp"],
                                speaker=d["speaker"],
                                content=d["content"],
                                session_id=d.get("session_id", ""),
                            ))
            current += timedelta(days=1)
        return messages

    def read_recent(self, n_days: int = 7) -> List[RawMessage]:
        start = (datetime.now() - timedelta(days=n_days)).strftime("%Y-%m-%d")
        return self.read_range(start)

    def export_for_digestion(self, n_days: int = 1, legacy_batch: int = 15) -> str:
        lines = []
        for m in self.read_recent(n_days):
            name = "用户" if m.speaker == "user" else "藤蔓"
            lines.append(f"[{m.timestamp[:19]}] {name}: {m.content}")
        legacy = self._read_legacy_batch(legacy_batch)
        if legacy:
            lines.extend(legacy)
        return "\n".join(lines)

    def _read_legacy_batch(self, batch_msgs: int) -> list:
        if not self.legacy_dir.exists():
            return []
        files = sorted(self.legacy_dir.glob("memvine_chat_*.jsonl"))
        if not files:
            return []
        cp = self._load_checkpoint()
        if cp.get("file") == "__DONE__":
            return []
        lines = []
        for f in files:
            fname = f.name
            if fname < cp["file"]:
                continue
            with open(f, 'r', encoding='utf-8') as fh:
                for i, line in enumerate(fh, 1):
                    if fname == cp["file"] and i <= cp["line"]:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    name = "用户" if d["speaker"] == "user" else "藤蔓"
                    ts = d["timestamp"][:19]
                    lines.append(f"[{ts}] {name}: {d['content']}")
                    if len(lines) >= batch_msgs:
                        self._save_checkpoint(fname, i)
                        print(f"   📜 [旧日志] 本批 {len(lines)} 条 (截止 {fname}:L{i})")
                        return lines
            cp = {"file": fname, "line": 0}
        self._save_checkpoint("__DONE__", 0)
        if lines:
            print(f"   📜 [旧日志] 最后一批 {len(lines)} 条")
        return lines

    def _load_checkpoint(self) -> dict:
        if self._checkpoint_path.exists():
            return json.loads(self._checkpoint_path.read_text(encoding='utf-8').strip())
        return {"file": "", "line": 0}

    def _save_checkpoint(self, file_name: str, line_num: int):
        self._checkpoint_path.write_text(
            json.dumps({"file": file_name, "line": line_num}), encoding='utf-8'
        )