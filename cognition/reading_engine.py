# cognition/reading_engine.py
"""
阅读引擎 —— 将外部文本存入向量库，图只记录导入事件

设计原则：
  1. 内容存向量库（ChromaDB），图只存事件和话题关联
  2. 分块交给 langchain-text-splitters，不手写截断逻辑
  3. 一次 LLM 调用只提取话题标签，不逐 chunk 消化
  4. 不再创建 entity/fact 节点（世界知识不入图）

依赖：
  - topology: TopologyEngine（图操作）
  - llm: LLMEngine（话题提取）
  - vector_store: VectorStore（向量检索 + 文档存储）
  - clock: SystemClock（时间戳）
  - _find_anchor（实体锚点查找，由 cortex 注入）
"""
from __future__ import annotations

import uuid
import hashlib
import json
import re

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    RecursiveCharacterTextSplitter = None


class ReadingEngine:
    """阅读引擎：将外部文本存入向量库，图只记录导入事件和话题关联"""

    def __init__(self, topology, llm, vector_store, clock):
        self.topology = topology
        self.llm = llm
        self.vector_store = vector_store
        self.clock = clock

        # 外部回调：由 cortex 注入
        self._find_anchor = None       # fn(name: str) -> node_id | None
        self._log = print
        self.proactive = None          # 新增：ProactiveEngine 引用

        # 好奇心系统
        self.curiosity_log: list[dict] = []
        # 去重：已导入文档的内容指纹
        self._ingested_hashes: set[str] = set()

    # ══════════════════════════════════════════════
    # 公开接口
    # ══════════════════════════════════════════════

    def read(self, text: str, source_label: str = "外部文档",
             user_id: str = "") -> dict:
        """导入文本：分块存入 ChromaDB，图只记录事件 + 话题关联。

        一次 LLM 调用（只提取话题标签），不逐 chunk 消化。
        """
        if not text or len(text.strip()) < 50:
            return {"success": False, "doc_id": "", "chunks": 0}

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if content_hash in self._ingested_hashes:
            self._log(f"📖 [阅读] 内容已存在，跳过重复导入")
            return {"success": True, "doc_id": "cached", "chunks": 0,
                    "topics": [], "cached": True}

        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        now_ts = self.clock.now_ts()

        # ── 步骤 1: 分块（langchain-text-splitters，≤2500 字短路） ──
        units = self._split_document(text)
        self._log(f"📖 [阅读] {source_label} → {len(units)} 个语义单元")

        # ── 步骤 2: 内容存入 ChromaDB（不入图） ──
        for i, unit in enumerate(units):
            chunk_id = f"{doc_id}_c{i}"
            self.vector_store.add_document(
                doc_id=chunk_id,
                text=unit["text"],
                metadata={
                    "doc_id": doc_id,
                    "source": source_label,
                    "imported_by": user_id,
                    "chunk_index": i,
                    "char_count": len(unit["text"]),
                    "imported_at": now_ts,
                },
            )

        # ── 步骤 3: 一次 LLM 调用提取话题标签 + 摘要 ──
        topics, summary = self._analyze_document(text[:3000])
        unique_themes = topics[:5]

        # ── 步骤 4: 图记录导入事件（不存内容） ──
        self.topology.graph.add_node(doc_id, **{
            "node_type": "doc_event",
            "source": source_label,
            "imported_by": user_id,
            "summary": summary,
            "chunk_count": len(units),
            "char_count": len(text),
            "born_at": now_ts,
        })

        if user_id and self._find_anchor:
            user_nid = self._find_anchor("entity_user")
            if user_nid:
                self.topology.connect(user_nid, doc_id, relation="imported", weight=2.0)

        # ── 步骤 5: 话题节点 + 引力中心关联 ──
        ai_nid = self._find_anchor("entity_ai") if self._find_anchor else None
        user_nid = self._find_anchor("entity_user") if self._find_anchor else None
        for theme in unique_themes:
            safe = re.sub(r'[^\w]', '_', theme)
            topic_id = f"topic_{safe}"
            if not self.topology.graph.has_node(topic_id):
                self.topology.graph.add_node(topic_id, **{
                    "node_type": "topic",
                    "topic_name": theme,
                    "born_at": now_ts,
                })
            self.topology.connect(doc_id, topic_id, relation="about", weight=1.0)
            if ai_nid:
                self.topology.connect(ai_nid, topic_id, relation="knows_about", weight=1.5)
            if user_nid:
                self.topology.connect(user_nid, topic_id, relation="discussed", weight=1.5)

        self._ingested_hashes.add(content_hash)
        self._log(f"📖 [阅读] 完成: {len(units)} 单元, 话题: {unique_themes}")
        return {"success": True, "doc_id": doc_id, "chunks": len(units),
                "topics": unique_themes}

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """在已导入文档中搜索原文（直接查 ChromaDB，不走图）"""
        results = self.vector_store.search_documents(query, top_k=top_k, threshold=0.5)
        return [
            {
                "doc_id": r["metadata"].get("doc_id", r["doc_id"]),
                "chunk_id": r["doc_id"],
                "text": r["text"][:800],
                "similarity": r["similarity"],
                "source": r["metadata"].get("source", ""),
            }
            for r in results
        ]

    # ══════════════════════════════════════════════
    # 好奇心系统
    # ══════════════════════════════════════════════

    def curiosity_scan(self) -> dict | None:
        """TODO: 重写为基于 ChromaDB 覆盖度的知识空白检测。
        旧实现依赖图中的 entity/chunk 节点（已移除），当前返回空。
        """
        self._log("🔍 [好奇心] 旧实现已废弃，待基于 ChromaDB 重写")
        return None

    def curiosity_report(self) -> list[dict]:
        return self.curiosity_log

    # ══════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════

    def _split_document(self, text: str) -> list[dict]:
        """使用 langchain-text-splitters 进行语义分块。

        - 短文本（≤2500 字）：不分块，整体作为一个单元
        - 长文本：RecursiveCharacterTextSplitter，在中文标点边界切分
        """
        if len(text) <= 2500:
            return [{"text": text}]

        if RecursiveCharacterTextSplitter is None:
            raise ImportError(
                "langchain-text-splitters 未安装，长文本分块不可用。"
                "请执行: pip install langchain-text-splitters"
            )
        splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
            chunk_size=2000,
            chunk_overlap=200,
        )
        docs = splitter.create_documents([text])
        return [{"text": d.page_content} for d in docs]

    def _analyze_document(self, text: str) -> tuple[list[str], str]:
        """一次 LLM 调用产出话题标签 + 文档摘要。
        失败时静默返回 ([], "")，不阻塞主流程。
        """
        prompt = f"""分析这段文本，输出 JSON：

1. topics: 核心话题标签，每标签 2-6 字，最多 5 个
2. summary: 50 字以内的内容摘要

文本: {text[:3000]}

输出格式: {{"topics": ["话题1", "话题2"], "summary": "50字摘要"}}"""
        try:
            response = self.llm.client.chat.completions.create(
                model=self.llm.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=256,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            topics = data.get("topics", []) if isinstance(data, dict) else []
            summary = data.get("summary", "") if isinstance(data, dict) else ""
            return topics[:5], summary[:100]
        except Exception:
            return [], ""