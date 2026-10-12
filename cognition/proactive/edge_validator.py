# cognition/proactive/edge_validator.py
"""边验证器 — 绑定验证上下文，用户回应时才触发验证

核心原则：
  - 验证绑定到具体的验证事件（ValidationContext），不是全局扫描
  - 极性判断用 LLM + 退化方案（开头匹配，非子串匹配）
  - 置信度调整与 relevance 成正比，否定权重 > 肯定权重
  - 3 轮未回应 → 过期
"""

import time

class ValidationContext:
    """一次验证请求的完整上下文"""

    def __init__(self, edge_key: tuple, question: str, asked_at: float):
        self.edge_key = edge_key          # (u, v) 具体哪条边
        self.question = question          # 系统问了什么
        self.asked_at = asked_at          # 什么时候问的
        self.conversation_turn = 0        # 问完之后经过了几轮对话
        self.resolved = False

class EdgeValidator:

    def __init__(self, topology, llm, clock):
        self.topology = topology
        self.llm = llm
        self.clock = clock
        self.active_validations: list[ValidationContext] = []

    # ── 第一步：系统提问时，注册验证上下文 ──

    def register_validation(self, u: str, v: str, question: str):
        ctx = ValidationContext(
            edge_key=(u, v),
            question=question,
            asked_at=self.clock.now_ts()
        )
        self.active_validations.append(ctx)

        g = self.topology.graph
        if g.has_edge(u, v):
            g[u][v]["status"] = "pending_validation"
            g[u][v]["validation_question"] = question

    # ── 第二步：用户回复时，判断是否在回应验证 ──

    def on_user_message(self, user_input: str, conversation_history: list[str]):
        if not self.active_validations:
            return

        for ctx in self.active_validations:
            if ctx.resolved:
                continue

            ctx.conversation_turn += 1

            if ctx.conversation_turn > 3:
                self._expire(ctx)
                continue

            if ctx.conversation_turn == 1:
                continue

            relevance = self._assess_relevance(user_input, ctx, conversation_history)
            if relevance < 0.3:
                continue

            polarity = self._assess_polarity(user_input, ctx.question)
            self._apply_validation(ctx, polarity, relevance)

    # ── 相关性判断 ──

    def _assess_relevance(self, user_input: str, ctx: ValidationContext,
                          history: list[str]) -> float:
        question = getattr(ctx, 'question', '')
        try:
            prompt = f"""之前系统问用户：「{question}」
用户现在回复：「{user_input}」

请判断用户回复与该问题的相关程度，只输出一个数字：
0=完全无关  0.3=略有相关  0.6=部分相关  0.9=直接回答"""
            result = self.llm.call(prompt, temperature=0.0).strip()
            score = float(result)
            return max(0.0, min(score, 1.0))
        except Exception:
            pass
        return 0.3

    # ── 极性判断 ──

    def _assess_polarity(self, user_input: str, question: str) -> str:
        try:
            prompt = f"""用户之前被问到：「{question}」
用户现在回复：「{user_input}」

请判断用户的回复对这个问题表达的是什么态度：
- positive（同意/确认）
- negative（否定/拒绝）
- ambiguous（模糊/不确定/部分同意）
- irrelevant（根本没在回答这个问题）

只输出一个词。"""
            result = self.llm.call(prompt, temperature=0.0).strip().lower()
            if result in ("positive", "negative", "ambiguous", "irrelevant"):
                return result
        except Exception:
            pass
        return "ambiguous"
    # ── 执行验证 ──

    def _apply_validation(self, ctx: ValidationContext, polarity: str, relevance: float):
        g = self.topology.graph
        u, v = ctx.edge_key

        if not g.has_edge(u, v):
            ctx.resolved = True
            return

        data = g[u][v]
        old_conf = data.get("confidence", 0.5)

        if polarity == "positive":
            boost = 0.3 * relevance
            data["confidence"] = min(1.0, old_conf + boost)
            data["status"] = "validated"
            data["validated_at"] = self.clock.now_ts()
            data["validation_polarity"] = "positive"

        elif polarity == "negative":
            penalty = 0.4 * relevance
            data["confidence"] = max(0.0, old_conf - penalty)
            data["status"] = "rejected"
            data["validated_at"] = self.clock.now_ts()
            data["validation_polarity"] = "negative"

        elif polarity == "ambiguous":
            data["confidence"] = min(1.0, old_conf + 0.05)
            # 不改变 status，不标记 resolved
            return

        elif polarity == "irrelevant":
            return

        ctx.resolved = True

        u_content = (g.nodes[u].get("data", {}) or {}).get("content", "")[:20]
        v_content = (g.nodes[v].get("data", {}) or {}).get("content", "")[:20]
        print(f"[验证] {polarity} | {u_content} → {v_content} | "
              f"conf: {old_conf:.2f} → {data['confidence']:.2f} | "
              f"relevance: {relevance:.2f}")

    # ── 过期 ──
    def _expire(self, ctx: ValidationContext):
        g = self.topology.graph
        u, v = ctx.edge_key
        if g.has_edge(u, v):
            g[u][v]["status"] = "expired"
            g[u][v]["expired_at"] = self.clock.now_ts()
        ctx.resolved = True
        u_content = (g.nodes.get(u, {}).get("data", {}) or {}).get("content", u)[:20]
        v_content = (g.nodes.get(v, {}).get("data", {}) or {}).get("content", v)[:20]
        print(f"[验证] ⏰ 过期: {u_content} → {v_content}")