# f:\memvine_v3\cognition\unified_extractor.py
"""统一提取器 —— 一轮对话一次 LLM 调用"""

import json
from openai import OpenAI
from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL


class UnifiedExtractor:
    def __init__(self):
        self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self.model = LLM_MODEL

    def extract(self, user_msg: str, ai_msg: str = "", seed_entities: list = None) -> dict:
        seed_hint = ""
        if seed_entities:
            seed_hint = f"\n【先验实体（来自上游语义解析，请优先关注）】\n{', '.join(seed_entities[:5])}\n"
        from prompts import UNIFIED_EXTRACTOR_PROMPT
        prompt = UNIFIED_EXTRACTOR_PROMPT.format(
            seed_hint=seed_hint, user_msg=user_msg, ai_msg=ai_msg[:300])

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            content = response.choices[0].message.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()
            return self._sanitize(json.loads(content))
        except Exception as e:
            print(f"   [统一提取] 失败: {e}")
            return self._fallback(user_msg)

    def _sanitize(self, raw: dict) -> dict:
        return {
            "is_event": bool(raw.get("is_event", True)),
            "summary": str(raw.get("summary", "") or ""),
            "events": raw.get("events") or [],
            "candidate_entities": raw.get("candidate_entities") or [],
            "facts": raw.get("facts") or [],
            "mem_type": raw.get("mem_type") or "daily_chat",
            "identity_claims": raw.get("identity_claims") or [],
            "corrections": raw.get("corrections") or [],
            "resonance_keys": raw.get("resonance_keys") or [],
            "missing_links": raw.get("missing_links") or [],

        }

    def _fallback(self, user_msg: str) -> dict:
        return {
            "is_event": False,
            "summary": user_msg[:40],
            "events": [],
            "candidate_entities": [],
            "facts": [],
            "mem_type": "daily_chat",
            "identity_claims": [],
            "corrections": [],
            "resonance_keys": [],
            "missing_links": [],
        }