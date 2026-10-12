import os

LLM_URL = os.getenv("MEMVINE_LLM_URL", "http://localhost:7777/v1")
LLM_KEY = os.getenv("MEMVINE_LLM_KEY", "lm-studio")
LLM_MODEL = os.getenv("MEMVINE_LLM_MODEL", "qwen/qwen3.5-9b")

# EMBEDDING_MODEL = os.getenv("MEMVINE_EMBED_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_MODEL = os.getenv("MEMVINE_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")

SYSTEM_TIMEZONE = "Asia/Shanghai"
