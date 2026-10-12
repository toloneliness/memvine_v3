# cognition/llm_engine.py

import json
import asyncio
import threading
from openai import OpenAI


class LLMEngine:
    def __init__(self, api_key, base_url=None, model="qwen-plus"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.system_prompt = ""
        self._interrupt_event = threading.Event()


    def call(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        """轻量级调用：发送 prompt，返回原始文本。用于意图识别等短任务。"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=temperature
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"   ⚠️ [LLM引擎] 轻量调用异常: {e}")
            return ""

    def request_interrupt(self):
        """用户说话时调用，通知后台 LLM 任务尽快结束"""
        self._interrupt_event.set()

    def clear_interrupt(self):
        """开始新一轮对话时清除中断标志"""
        self._interrupt_event.clear()

    async def call_async(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        """异步版 call：在 executor 中运行，支持中断检查"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.call, prompt, system, temperature)

    def call_json(self, prompt: str, system: str = "", temperature: float = 0.2) -> dict:
        """调用 LLM 并返回 JSON 解析结果，失败返回空字典"""
        try:
            raw = self.call(prompt, system=system, temperature=temperature)
            if not raw:
                return {}
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return {}

    def chat_with_messages(self, messages: list[dict], temperature: float = 0.7) -> dict:
        """通用多轮对话调用，返回 {'reply': str, 'valence': float}"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
            )
            reply_text = response.choices[0].message.content.strip()

            valence = 0.0
            if "{" in reply_text and "valence" in reply_text:
                try:
                    json_str = reply_text[reply_text.rfind("{"):]
                    parsed = json.loads(json_str)
                    valence = float(parsed.get("valence", 0.0))
                    reply_text = reply_text[:reply_text.rfind("{")].strip()
                except Exception:
                    pass

            return {"reply": reply_text, "valence": valence}
        except Exception as e:
            print(f"   [LLM引擎] 对话异常: {e}")
            return {"reply": "...（大脑过载，无法处理）", "valence": 0.0}

    def perceive_and_respond(self, assembled_prompt: str, current_time=None) -> dict:
        """
        接收由 ContextManager 预构建的完整 prompt，发送给 LLM。
        prompt 内已包含：系统设定 + 能量状态 + 记忆碎片 + 当前对话。
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": assembled_prompt}
                ],
                temperature=0.7
            )

            reply_text = response.choices[0].message.content.strip()

            valence = 0.0
            if "{" in reply_text and "valence" in reply_text:
                try:
                    json_str = reply_text[reply_text.rfind("{"):]
                    parsed = json.loads(json_str)
                    valence = float(parsed.get("valence", 0.0))
                    reply_text = reply_text[:reply_text.rfind("{")].strip()
                except:
                    pass

            return {"reply": reply_text, "valence": valence}

        except Exception as e:
            print(f"   ⚠️ [LLM引擎] 认知处理异常: {e}")
            return {"reply": "...（大脑过载，无法处理）", "valence": 0.0}

    async def perceive_and_respond_async(self, assembled_prompt: str, current_time=None) -> dict:
        """异步版 perceive_and_respond"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.perceive_and_respond, assembled_prompt, current_time)