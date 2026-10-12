# cognition/cogniweave/weaver.py
"""Layer 3: 认知经纬编织 —— 将原始查询结果编织为 LLM 可理解的上下文"""

import json
from typing import Optional
from .models import CognitiveContext, QueryAgenda, QueryResult
from prompts import WEAVE_SYSTEM_PROMPT, WEAVE_USER_PROMPT

class Weaver:
    def __init__(self, llm_engine):
        self.llm = llm_engine

    def weave(
        self,
        cognitive_context: CognitiveContext,
        user_input: str,
        identity_block: str = "",
        state_summary: str = "",
        conflict_rules: str = "",
        voice_priority: str = "",
        tension_rules: str = "",
    ) -> dict:
        findings = cognitive_context.to_llm_context(max_items_per_query=6)

        system = WEAVE_SYSTEM_PROMPT.format(
            identity_block=identity_block or "（身份尚未建立）",
            voice_priority=voice_priority or "回答时区分'我记得'、'我了解'、'据我所知'。",
            conflict_rules=conflict_rules or "trusts vs distrusts, likes vs dislikes, loves vs hates",
            tension_rules=tension_rules or "如果节点存在结构洞且未被验证，存在认知张力。",
        )
        user = WEAVE_USER_PROMPT.format(
            raw_findings=findings,
            user_input=user_input,
            state_summary=state_summary or "状态正常",
        )

        try:
            result = self.llm.chat_with_messages(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
            )
            return result
        except Exception as e:
            print(f"   [CogniWeave] 编织异常: {e}")
            return {"reply": "（认知编织暂时中断，请稍后再试）", "valence": 0.0}