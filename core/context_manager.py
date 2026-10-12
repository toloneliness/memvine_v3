from config import CONTEXT_WINDOW_TOKENS, RESERVED_TOKENS, MIN_MEMORY_BUDGET, BASE_MEMORY_BUDGET
import json

class ContextManager:
    def __init__(self, max_context_tokens=4096):
        self.max_context_tokens = max_context_tokens
        self.reserved_tokens = RESERVED_TOKENS

    def _extract_memory_info(self, memory) -> tuple[str, float, str]:
        if hasattr(memory, 'text') and hasattr(memory, 'score'):
            tag = self._build_tag(memory)
            return memory.text, memory.score, tag

        if isinstance(memory, dict):
            node_data = memory.get("data", {}) if isinstance(memory.get("data"), dict) else {}
            content = node_data.get("content", str(memory.get("text", memory)))
            valence = abs(node_data.get("valence", 0.0))
            score = memory.get("score", valence)
            tag = self._build_tag_from_dict(memory, node_data)
            return content, score, tag

        return str(memory), 0.0, ""

    def _build_tag(self, memory) -> str:
        parts = []
        raw_data = getattr(memory, 'raw_data', {})
        node_data = raw_data.get("data", {}) if isinstance(raw_data, dict) else {}

        source = node_data.get("source", "")
        if source == "self":
            parts.append('我')
        elif source.startswith("user"):
            parts.append('对方')
        elif source == "identity":
            parts.append('身份')

        agent = node_data.get("agent", "")
        if agent and agent not in parts:
            parts.append(agent)

        action = node_data.get("action", "")
        if action and action != "表达":
            parts.append(action)

        mem_type = node_data.get("mem_type", getattr(memory, 'mem_type', ''))
        if mem_type and mem_type not in ("daily_chat",):
            parts.append(mem_type)

        valence = node_data.get("valence", 0.0)
        if isinstance(valence, (int, float)) and abs(valence) > 3.0:
            parts.append(f'情绪{valence:+.0f}')

        return '/'.join(parts) if parts else ''

    def _build_tag_from_dict(self, memory: dict, node_data: dict) -> str:
        parts = []

        source = node_data.get("source", "")
        if source == "self":
            parts.append('我')
        elif source.startswith("user"):
            parts.append('对方')
        elif source == "identity":
            parts.append('身份')

        agent = node_data.get("agent", "")
        if agent and agent not in parts:
            parts.append(agent)

        action = node_data.get("action", "")
        if action and action != "表达":
            parts.append(action)

        mem_type = node_data.get("mem_type", "")
        if mem_type and mem_type not in ("daily_chat",):
            parts.append(mem_type)

        valence = node_data.get("valence", 0.0)
        if isinstance(valence, (int, float)) and abs(valence) > 3.0:
            parts.append(f'情绪{valence:+.0f}')

        return '/'.join(parts) if parts else ''

    def _estimate_tokens(self, text: str) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.6 + other_chars * 0.4)

    def build_cognitive_briefing(
        self,
        state_block: dict,
        context_block: dict,
        recent_block: list,
        user_input: str,
        intent: str,
        response_mode: str,
    ) -> tuple[str, int]:

        from prompts import VOICE_PRIORITY_PROMPT, PROTOCOL_PROMPT, RULES_BLOCK, ACTION_META

        # ── 分层策略：复用 ACTION_META（与 Router 输出一致，避免硬编码错位） ──
        meta = ACTION_META.get(intent, ACTION_META["share"])
        is_trivial = meta["trivial"]
        is_complex = meta["load"] >= 5

        # ── 基础层：所有查询都需要 ──
        briefing = {
            "identity": state_block.get("identity", {}),
            "time": state_block.get("time", {}),
            "state": state_block.get("state", {}),
        }

        # ── 扩展层：非 trivial 才注入 ──
        if not is_trivial:
            briefing["voice_priority"] = VOICE_PRIORITY_PROMPT
            briefing["context"] = context_block
            briefing["recent"] = recent_block

        # ── 工具层：仅 complex 才注入 ──
        if is_complex:
            briefing["tools"] = state_block.get("tools", [])
            briefing["rules"] = RULES_BLOCK
            briefing["protocol"] = PROTOCOL_PROMPT

        briefing_json = json.dumps(briefing, ensure_ascii=False, indent=2)
        user_section = f"\n\n[用户输入]: {user_input}"
        final_prompt = briefing_json + user_section
        total_estimated = self._estimate_tokens(final_prompt)

        max_allowed = self.max_context_tokens - self.reserved_tokens
        if total_estimated > max_allowed:
            overflow = total_estimated - max_allowed
            chars_to_remove = int(overflow * 0.4)
            if len(briefing_json) > chars_to_remove + 500:
                cut_at = len(briefing_json) - chars_to_remove
                last_comma = briefing_json.rfind('\n', 0, cut_at)
                if last_comma > 0:
                    briefing_json = briefing_json[:last_comma] + "\n  ...\n}"
                else:
                    briefing_json = briefing_json[:cut_at] + "\n...}"
                final_prompt = briefing_json + user_section
                total_estimated = self._estimate_tokens(final_prompt)

        tier = "trivial" if is_trivial else ("complex" if is_complex else "simple")
        print(f"[认知简报] 🧪 意图={intent} | 层级={tier} | "
              f"模式={response_mode} | recent={len(recent_block)}条 | 预估≈{total_estimated} tokens")

        return final_prompt, total_estimated