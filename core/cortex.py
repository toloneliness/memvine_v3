"""
MemVine v3 数字皮层 —— 精简版
新数据源引擎：PreStorePool → DigestionEngine → ThreeLayerTopology
"""
import json
import threading
import pendulum
from config import LLM_URL, LLM_KEY, LLM_MODEL
from core.clock import SystemClock
from core.prestore import PreStorePool
from core.persistence import PersistenceEngine
from core.chat_logger import ChatLogger
from core.context_builder import ContextBuilder
from core.raw_log_store import RawLogStore
from core.finding_store import FindingStore
from core.user_registry import UserRegistry
from core.time_resolver import TimeResolver
from core.document_importer import DocumentImporter
from physics.three_layer_topology import ThreeLayerTopology
from cognition.llm_engine import LLMEngine
from cognition.vector_store import VectorStore
from cognition.digestion import DigestionEngine
from cognition.reading_engine import ReadingEngine
from cognition.intent_manifest import INTENT_MANIFEST, get_default_spec

class Cortex:
    def __init__(self, capacity: int = None):
        # ── 时间 ──
        self.clock = SystemClock()
        self.birth_time = self.clock.now_local().to_iso8601_string()
        self._last_talk_ts = None
        self._digestion_paused = threading.Event()
        self._digestion_done = threading.Event()
        self._digestion_done.set()

        # ── 数据源（新引擎核心） ──
        self.prestore = PreStorePool(max_entries=200)
        self.topology = ThreeLayerTopology()

        # ── 永久日志与发现存储 ──
        self.raw_logs = RawLogStore()
        self.finding_store = FindingStore()

        # ── 推理引擎 ──
        self.llm = LLMEngine(api_key=LLM_KEY, base_url=LLM_URL, model=LLM_MODEL)
        self.vector_store = VectorStore()
        self.digestion = DigestionEngine(llm=self.llm, finding_store=self.finding_store, topology=self.topology)

        # ── 上下文构建 ──
        self.context_builder = ContextBuilder(
            topology=self.topology,
            clock=self.clock,
            vector_store=self.vector_store,
            prestore=self.prestore,
            finding_store=self.finding_store,
        )

        # ── 基础设施 ──
        self.persistence = PersistenceEngine()
        self.chat_logger = ChatLogger(clock=self.clock)
        self.user_registry = UserRegistry()
        self.time_resolver = TimeResolver()
        self.reading_engine = ReadingEngine(
            topology=self.topology,
            llm=self.llm,
            vector_store=self.vector_store,
            clock=self.clock,
        )
        self.document_importer = DocumentImporter(self)

        # ── 对话计数 ──
        self._turn_count = 0
        self._digestion_interval = 10

        # ── 恢复存档 ──
        saved = self.persistence.load_state()
        if saved:
            self._load_saved_state(saved)

        print(f"🧠 数字皮层初始化完成。")

    # ═══════════════════════════════════════════════
    # 核心对话管线
    # ═══════════════════════════════════════════════

    def chat(self, user_input: str, user_id: str = None,
             source_channel: str = "", source_id: str = "") -> str:
        now_str = self.clock.now_local().to_iso8601_string()
        self._turn_count += 1

        # 暂停后台消化，优先对话管道
        self._digestion_paused.set()
        self._digestion_done.wait(timeout=20)

        # 1. 存入预存储池（不解析）
        self.prestore.append(now_str, "user", user_input)
        self.raw_logs.append("user", user_input, session_id=source_id or user_id or "")

        # 2. 构建上下文 JSON
        context_json = self.context_builder.build(user_input, self._last_talk_ts)

        # 3. 组装提示词
        prompt = self._build_chat_prompt(user_input, context_json)

        # 4. LLM 生成回复
        reply = self.llm.call(prompt, temperature=0.7)
        if not reply:
            reply = "……（思绪中断，请再说一次）"

        # 5. 存入预存储池
        self.prestore.append(now_str, "memvine", reply)
        self.raw_logs.append("vine", reply, session_id=source_id or user_id or "")

        # 6. 日志
        self.chat_logger.log_message("user", user_input)
        self.chat_logger.log_message("memvine", reply)
        self.chat_logger.log_prompt(user_input, prompt, reply)

        # 7. 更新状态
        self._last_talk_ts = self.clock.now_ts()

        # 9. 存档（消化异步后台执行）
        self.save()
        # 恢复消化，启动后台线程
        self._digestion_paused.clear()
        self._digestion_done.clear()
        threading.Thread(target=self._digest_background, daemon=True).start()
        return reply

    def _build_chat_prompt(self, user_input: str, context_json: str) -> str:
        return f"""你是藤蔓。以下是当前上下文（JSON）：

{context_json}

请根据上下文回应用户。如果记忆中有相关信息，自然地引用它。如果没有，诚实地说不确定。

用户说：{user_input}"""

    # ═══════════════════════════════════════════════
    # 后台消化
    # ═══════════════════════════════════════════════

    def _digest_background(self):
        try:
            self._trigger_digestion()
        finally:
            self._digestion_done.set()

    def _trigger_digestion(self):
        print("   🧠 [后台消化] 正在消化近期对话...")
        try:
            text = self.raw_logs.export_for_digestion(n_days=1)
            if not text.strip():
                print("   📭 无新对话，跳过消化")
                return
            existing = self.finding_store.get_active()
            if self._digestion_paused.is_set():
                print("   ⏸️  [后台消化] 有新消息，消化挂起")
                return
            bg = self.digestion.read_recent_narratives(n_days=1)
            new_findings = self.digestion.digest(text, existing_findings=existing,
                                                  background_narrative=bg)
            if new_findings:
                self.finding_store.add_many(new_findings)
                print(f"   📝 消化完成: {len(new_findings)} 条发现")
                for f in new_findings:
                    print(f"      [{f.type}] {f.content[:50]}")
            else:
                print("   📭 未发现新内容")
        except Exception as e:
            print(f"   ⚠️ 消化失败: {e}")
    def digest_manually(self):
        """手动触发消化，返回消化结果"""
        self._trigger_digestion()
        findings = self.finding_store.get_active()
        if findings:
            return "\n".join(f"[{f.type}] {f.content}" for f in findings)
        return "（暂无发现）"
    # ═══════════════════════════════════════════════
    # 持久化
    # ═══════════════════════════════════════════════

    def save(self):
        self.persistence.save_state(
            topology_data=self.topology.to_dict(),
            prestore=self.prestore.to_dict(),
            birth_time=self.birth_time,
            last_talk_ts=self._last_talk_ts,
            turn_count=self._turn_count,
        )

    def _load_saved_state(self, saved: dict):
        if "topology_data" in saved:
            self.topology = ThreeLayerTopology.from_dict(saved["topology_data"])
        elif "topology" in saved:
            topo_data = saved["topology"]
            if isinstance(topo_data, dict):
                self.topology = ThreeLayerTopology.from_dict(topo_data)
            else:
                print(" ⚠️ 无法识别的旧格式，从空图开始")

        if "prestore" in saved:
            self.prestore = PreStorePool.from_dict(saved["prestore"])

        raw_birth = saved.get("birth_time", self.birth_time)
        self.birth_time = pendulum.parse(raw_birth) if isinstance(raw_birth, str) else raw_birth
        if saved.get("last_talk_ts"):
            self._last_talk_ts = saved["last_talk_ts"]
        self._turn_count = saved.get("turn_count", 0)

        stats = self.topology.stats
        print(f" 📂 已恢复记忆: {stats['node_count']}节点 {stats['edge_count']}边")

    # ═══════════════════════════════════════════════
    # 状态查询
    # ═══════════════════════════════════════════════

    def get_stats(self) -> dict:
        stats = self.topology.stats
        return {
            **stats,
            "prestore_size": len(self.prestore),
            "turn_count": self._turn_count,
            "birth_time": self.birth_time,
            "last_talk": self.clock.format_local(self._last_talk_ts) if self._last_talk_ts else "无",
        }

    def get_identity_name(self) -> str | None:
        """从 identity 子图中提取最高置信度的 self_name。没有则返回 None。"""
        identity_edges = self.topology.subgraph("identity")
        best = None
        best_weight = 0
        for t in identity_edges:
            if t.metadata.get("role") == "self_name":
                if t.weight > best_weight:
                    best_weight = t.weight
                    best = t.target_id
        return best

    def get_context_for_debug(self, user_input: str = "") -> str:
        """调试用：查看当前构建的上下文 JSON"""
        return self.context_builder.build(user_input, self._last_talk_ts)
