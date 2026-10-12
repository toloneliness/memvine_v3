# cognition/vector_store.py
"""ChromaDB 向量存储 —— Collection 隔离的三层索引

  - system_events: 事件摘要，用于语义记忆检索
  - entity_names:  实体名索引，用于实体消歧
  - documents:     用户导入的文档原文，用于引用检索
"""

import numpy as np
import chromadb
from chromadb.utils import embedding_functions
from config import EMBEDDING_MODEL

class VectorStore:
    _ef = None

    def __init__(self, persist_path: str = "./memvine_data/chroma"):
        self._ensure_ef()
        self.client = chromadb.PersistentClient(path=persist_path)
        self.events = self.client.get_or_create_collection(
            name="system_events",
            embedding_function=self._ef,
            metadata={"description": "事件摘要，用于语义记忆检索"},
        )
        self.entities = self.client.get_or_create_collection(
            name="entity_names",
            embedding_function=self._ef,
            metadata={"description": "实体名索引，用于实体消歧"},
        )
        self.documents = self.client.get_or_create_collection(
            name="documents",
            embedding_function=self._ef,
            metadata={"description": "用户导入的文档原文，用于引用检索"},
        )

    @classmethod
    def _ensure_ef(cls):
        if cls._ef is None:
            # 优先本地缓存，避免无意义的远程重试（5次×8秒=40秒阻塞）
            try:
                cls._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=EMBEDDING_MODEL,
                    local_files_only=True,
                )
                print(f"[VectorStore] ✅ 从本地缓存加载 {EMBEDDING_MODEL}")
            except Exception:
                print(f"[VectorStore] ⚠️ 本地缓存未命中，尝试远程下载 {EMBEDDING_MODEL}...")
                cls._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=EMBEDDING_MODEL,
                )

    def embed(self, text: str) -> np.ndarray:
        return np.array(self._ef([text[:6000]])[0], dtype=np.float32)

    # ── 兼容旧 API ──

    def add(self, node_id: str, text: str):
        if not text:
            return
        if node_id.startswith("entity_"):
            self.entities.upsert(ids=[node_id], documents=[text])
        elif node_id.startswith("event_"):
            self.events.upsert(ids=[node_id], documents=[text])
        elif node_id.startswith("doc_"):
            self.documents.upsert(ids=[node_id], documents=[text])
        else:
            self.events.upsert(ids=[node_id], documents=[text])

    def search(self, query_vec: np.ndarray, top_k: int = 5,
               threshold: float = 0.75) -> list[dict]:
        results = []
        try:
            r = self.events.query(query_embeddings=[query_vec.tolist()], n_results=top_k,
                                  include=["distances"])
            ids = r.get("ids", [[]])[0]
            distances = r.get("distances", [[]])[0]
            for nid, dist in zip(ids, distances):
                sim = 1.0 - dist
                if sim >= threshold:
                    results.append({"node_id": nid, "similarity": round(sim, 4)})
        except Exception:
            pass
        try:
            r = self.entities.query(query_embeddings=[query_vec.tolist()], n_results=top_k,
                                    include=["distances"])
            ids = r.get("ids", [[]])[0]
            distances = r.get("distances", [[]])[0]
            for nid, dist in zip(ids, distances):
                sim = 1.0 - dist
                if sim >= threshold:
                    results.append({"node_id": nid, "similarity": round(sim, 4)})
        except Exception:
            pass
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    # ── 文档级 API（新增） ──

    def add_document(self, doc_id: str, text: str, metadata: dict = None):
        self.documents.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )

    def search_documents(self, query: str, top_k: int = 5,
                         threshold: float = 0.35) -> list[dict]:
        try:
            r = self.documents.query(query_texts=[query], n_results=top_k,
                                     include=["documents", "distances", "metadatas"])
        except Exception:
            return []
        ids = r.get("ids", [[]])[0]
        documents = r.get("documents", [[]])[0]
        distances = r.get("distances", [[]])[0]
        metadatas = r.get("metadatas", [[]])[0]
        results = []
        for nid, text, dist, meta in zip(ids, documents, distances, metadatas):
            sim = 1.0 - dist
            if sim >= threshold:
                results.append({
                    "doc_id": nid,
                    "text": text,
                    "similarity": round(sim, 4),
                    "metadata": meta or {},
                })
        return results

    @property
    def node_ids(self) -> list[str]:
        """兼容旧代码：返回所有 events collection 中的 id"""
        try:
            return self.events.get()["ids"]
        except Exception:
            return []

    def to_dict(self) -> dict:
        """ChromaDB 自动持久化，此方法仅保留兼容性"""
        return {"persist_path": "./memvine_data/chroma"}

    @classmethod
    def from_dict(cls, d: dict) -> "VectorStore":
        """ChromaDB 自动加载，此方法仅保留兼容性"""
        return cls(persist_path=d.get("persist_path", "./memvine_data/chroma"))