# cognition/proactive/bootstrapper.py
"""冷启动内省引擎 —— 在图稀疏时，用 LLM 参数知识构建骨架。

不是定时器。触发条件是图密度不足。
与 Catalyst 的分工：
  - Catalyst：发现图库中的空洞，生成假设让用户验证
  - Bootstrapper：在图还不够时，用 LLM 内置知识填充骨架，标记为"内省"
"""

import json, re

class IntrospectiveBootstrapper:
    def __init__(self, topology, llm, clock):
        self.topology = topology
        self.llm = llm
        self.clock = clock
        self._bootstrapped_domains: set = set()
        self._min_density = 0.05
        self._max_topics_per_session = 3
        self._max_llm_calls_per_run = 6

    # ── 触发判断 ──

    def should_bootstrap(self, recent_topics: list[str]) -> bool:
        g = self.topology.graph
        n = g.number_of_nodes()
        if n == 0:
            return True
        e = g.number_of_edges()
        density = e / (n * (n - 1)) if n > 1 else 0
        if density < self._min_density:
            return True
        for topic in recent_topics:
            if topic in self._bootstrapped_domains:
                continue
            count = sum(1 for nid in g.nodes()
                        if topic.lower() in str(g.nodes[nid].get("data", {}).get("content", "")).lower())
            if count < 3:
                return True
        return False

    # ── 主流程 ──

    def bootstrap(self, seed_topics: list[str], depth: int = 2, context_feed: dict = None) -> int:
        written = 0
        call_count = 0
        for topic in seed_topics[:self._max_topics_per_session]:
            if topic in self._bootstrapped_domains:
                continue
            if call_count >= self._max_llm_calls_per_run:
                break
            print(f"[内省] 开始构建「{topic}」的知识骨架...")
            questions = self._generate_introspective_questions(topic, depth, context_feed)
            call_count += min(depth, 3)
            for q in questions[:3]:
                if call_count >= self._max_llm_calls_per_run:
                    break
                answer = self._introspective_answer(q, topic)
                call_count += 1
                entities, relations = self._extract_structure(q, answer, topic)
                call_count += 1
                self._write_to_graph(entities, relations, topic)
                written += len(entities) + len(relations)
            self._bootstrapped_domains.add(topic)
            self._self_audit(topic)
        print(f"[内省] 完成，写入 {written} 项，LLM 调用 {call_count} 次")
        return written

    # ── 第一步：生成内省问题 ──

    def _generate_introspective_questions(self, topic: str, depth: int, context_feed: dict = None) -> list[dict]:
        feed_hint = ""
        if context_feed:
            gaps = context_feed.get("knowledge_gap", {})
            if gaps and gaps.get("missing_edges"):
                samples = gaps["missing_edges"][:3]
                feed_hint = "\n当前图库已知缺口：\n" + "\n".join(
                    f"  - {e.get('from','')} ↔ {e.get('to','')} ({e.get('reason','')})"
                    for e in samples
                )
        from prompts import (BOOTSTRAPPER_CONCEPT_PROMPT, BOOTSTRAPPER_RELATION_PROMPT,
                             BOOTSTRAPPER_MISCONCEPTION_PROMPT)
        prompts = {
            1: BOOTSTRAPPER_CONCEPT_PROMPT.format(topic=topic, feed_hint=feed_hint),
            2: BOOTSTRAPPER_RELATION_PROMPT.format(topic=topic),
            3: BOOTSTRAPPER_MISCONCEPTION_PROMPT.format(topic=topic)
        }
        questions = []
        for level in range(1, min(depth + 1, 4)):
            try:
                resp = self.llm.call(prompts[level], temperature=0.3)
                parsed = self._parse_structured_lines(resp, level)
                questions.extend(parsed)
            except Exception as e:
                print(f"[内省] 问题生成失败 L{level}: {e}")
        return questions

    def _parse_structured_lines(self, resp: str, level: int) -> list[dict]:
        result = []
        for line in resp.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if level == 1 and len(parts) >= 2:
                result.append({"type": "concept", "name": parts[0], "definition": parts[1]})
            elif level == 2 and len(parts) >= 4:
                result.append({"type": "relation", "from": parts[0], "rel": parts[1], "to": parts[2], "desc": parts[3]})
            elif level == 3 and len(parts) >= 3:
                result.append({"type": "misconception", "claim": parts[0], "why_wrong": parts[1], "correct": parts[2]})
        return result

    # ── 第二步：内省回答 ──

    def _introspective_answer(self, question: dict, topic: str) -> dict:
        qtype = question.get("type", "")
        if qtype == "concept":
            question_text = f"请详细解释概念「{question.get('name', '')}」的定义、背景和重要性。定义参考：{question.get('definition', '')}"
        elif qtype == "relation":
            question_text = f"请解释「{question.get('from', '')}」和「{question.get('to', '')}」之间的{question.get('rel', '')}关系。说明：{question.get('desc', '')}"
        elif qtype == "misconception":
            question_text = f"关于「{question.get('claim', '')}」这个常见误解，请详细说明为什么是错的，以及正确的理解是什么。"
        else:
            question_text = json.dumps(question, ensure_ascii=False)

        from prompts import BOOTSTRAPPER_ANSWER_PROMPT
        prompt = BOOTSTRAPPER_ANSWER_PROMPT.format(question_text=question_text)
        try:
            resp = self.llm.call(prompt, temperature=0.2)
            if not resp:
                return {"answer": "", "confidence": 0.0, "uncertain_parts": [], "source_type": "unknown"}
            s = resp.find("{"); e = resp.rfind("}") + 1
            if s >= 0 and e > s:
                return json.loads(resp[s:e])
        except Exception:
            pass
        return {"answer": "", "confidence": 0.0, "uncertain_parts": [], "source_type": "unknown"}

    # ── 第三步：提取图结构 ──

    def _extract_structure(self, question: dict, answer: dict, topic: str) -> tuple:
        if not answer.get("answer"):
            return [], []
        from prompts import BOOTSTRAPPER_EXTRACT_PROMPT
        prompt = BOOTSTRAPPER_EXTRACT_PROMPT.format(
            question=json.dumps(question, ensure_ascii=False),
            answer=answer['answer'])
        try:
            resp = self.llm.call(prompt, temperature=0.1)
            s = resp.find("{"); e = resp.rfind("}") + 1
            if s >= 0 and e > s:
                data = json.loads(resp[s:e])
                return data.get("entities", []), data.get("relations", [])
        except Exception:
            pass
        return [], []

    # ── 第四步：写入图 ──

    def _write_to_graph(self, entities: list, relations: list, topic: str):
        g = self.topology.graph
        now_ts = self.clock.now_ts()
        for entity in entities:
            node_id = self._normalize_id(entity["name"])
            if g.has_node(node_id):
                continue
            g.add_node(node_id, data={
                "content": entity["name"],
                "mem_type": "introspection",
                "node_type": entity.get("type", "concept"),
                "definition": entity.get("definition", ""),
                "source": "introspective",
                "confidence": 0.4,
                "born_at": now_ts,
                "last_active": now_ts,
                "last_activated": now_ts,
                "mention_count": 1,
                "needs_validation": True,
                "domain": topic,
            })
        for rel in relations:
            u = self._normalize_id(rel["from"])
            v = self._normalize_id(rel["to"])
            if g.has_node(u) and g.has_node(v) and not g.has_edge(u, v):
                self.topology.connect(u, v,
                    weight=0.35, relation=rel.get("type", "related"),
                    confidence=0.35, status="pending_validation",
                )

    # ── 第五步：自审 ──

    def _self_audit(self, topic: str):
        g = self.topology.graph
        topic_nodes = [nid for nid in g.nodes()
                       if g.nodes[nid].get("data", {}).get("domain") == topic]
        if len(topic_nodes) <= 20:
            return
        sorted_nodes = sorted(topic_nodes,
                              key=lambda n: g.nodes[n].get("data", {}).get("confidence", 0))
        for nid in sorted_nodes[:len(sorted_nodes) - 15]:
            g.remove_node(nid)
        self._bootstrapped_domains.discard(topic)
        print(f"[内省审计] 「{topic}」节点过多({len(topic_nodes)})，削减至 15 个，已解锁重新内省")

    def _normalize_id(self, name: str) -> str:
        cleaned = re.sub(r'[^\w\u4e00-\u9fff]', '_', name.strip())
        base = cleaned[:50].lower()
        h = abs(hash(base)) % 10000
        return f"{base}_{h:04d}"