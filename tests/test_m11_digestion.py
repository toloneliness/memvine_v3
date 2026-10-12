# f:\memvine_v3.3\tests\test_m11_digestion.py
"""
M11 Core 2 后台消化 - P1 编织知识网
从现有知识碎片中，让 LLM 发现节点间关联，建立知识网边
"""

import json
import os
import re
import sys
import time
import requests
from typing import List, Dict, Set, Tuple
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from test_m10_multiday_graph import (
    ThreeLayerTopology, ThreeLayerRecall, ThreeLayerParser,
    MemoryFragment, LogLoader, LLM_URL, LLM_KEY, LLM_MODEL
)

class DigestionEngine:
    """Core 2: 后台消化 —— 从碎片中织网"""

    def __init__(self, topology: ThreeLayerTopology):
        self.topo = topology

    def get_knowledge_fragments(self) -> List[str]:
        """提取所有知识网节点名（去重，排除用户）"""
        nodes = set()
        for t in self.topo.traces.values():
            if t.edge_type == "knowledge":
                if t.source_id != "用户":
                    nodes.add(t.source_id)
                if t.target_id != "用户":
                    nodes.add(t.target_id)
        return sorted(nodes)

    def digest_batch(self, fragments: List[str], batch_size: int = 15) -> List[Tuple[str, str, str]]:
        """
        让LLM消化一批知识碎片，发现关联。
        返回: [(source, target, relation), ...]
        """
        fragment_text = "\n".join(f"- {f}" for f in fragments)

        prompt = f"""你是记忆消化器。分析以下知识碎片，发现它们之间的语义关联。

知识碎片:
{fragment_text}

请找出有意义的关联对，输出JSON数组。每条关联包含:
- source: 来源碎片
- target: 目标碎片
- relation: 关系描述（简洁，如"同作者"、"因果"、"同类"、"对比"、"延续"等）

规则:
1. 只输出真正有语义关联的配对，不要勉强
2. 每个碎片最多关联3个其他碎片
3. 只返回JSON数组，不要其他文字

JSON输出示例:
[
  {{"source":"阅读《百年孤独》","target":"马尔克斯写了《百年孤独》","relation":"因果关系"}},
  {{"source":"窗外云朵","target":"风和云的关系","relation":"同类主题"}}
]

JSON输出:"""

        try:
            resp = requests.post(
                f"{LLM_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_KEY}"},
                json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.3},
                timeout=60
            )
            content = resp.json()['choices'][0]['message']['content']
            content = content.strip().replace("```json", "").replace("```", "")
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r'$$.*$$', content, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                else:
                    return []
            if isinstance(parsed, dict):
                parsed = [parsed]
            return parsed
        except:
            return []

    def weave(self) -> Dict:
        """执行完整消化：将所有知识碎片分批，让LLM发现关联，建边"""
        fragments = self.get_knowledge_fragments()
        print(f"\n  知识碎片总数: {len(fragments)}")

        all_links = []
        batch_size = 15
        batches = [fragments[i:i+batch_size] for i in range(0, len(fragments), batch_size)]

        print(f"  分批消化: {len(batches)} 批 (每批最多{batch_size}个碎片)")

        for bi, batch in enumerate(batches):
            print(f"\n  第 {bi+1}/{len(batches)} 批 ({len(batch)} 个碎片)...")
            links = self.digest_batch(batch)
            print(f"    发现 {len(links)} 条关联")
            for link in links:
                src = link.get("source", "")
                tgt = link.get("target", "")
                rel = link.get("relation", "")
                if src and tgt and src != tgt:
                    all_links.append((src, tgt, rel))
                    print(f"      '{src}' ←→ '{tgt}' ({rel})")
            time.sleep(0.5)

        # 将关联写入知识网
        woven_count = 0
        for src, tgt, rel in all_links:
            self.topo.strengthen_or_create(
                source=src, target=tgt, edge_type="knowledge",
                metadata={"action": "关联", "raw_text": f"消化产物: {rel}",
                           "digested": True}
            )
            woven_count += 1

        return {
            "fragments_total": len(fragments),
            "batches": len(batches),
            "links_found": len(all_links),
            "edges_woven": woven_count,
        }

# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "memvine_logs")
    DAYS = ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]

    print("=" * 60)
    print("M11 Core 2 后台消化 - P1 编织知识网")
    print("=" * 60)

    try:
        requests.get(f"{LLM_URL}/models", timeout=5)
    except:
        print("LM Studio 未启动！")
        sys.exit(1)

    # 加载并解析（复用 M10 的图）
    loader = LogLoader(LOG_DIR)
    all_msgs = loader.load_range(DAYS[0], DAYS[-1])
    user_msgs = loader.filter_by_speaker(all_msgs, "user")
    print(f"\n[加载] {len(user_msgs)} 条用户消息 ({len(DAYS)} 天)")

    parser = ThreeLayerParser()
    topo = ThreeLayerTopology()
    failed = 0

    print(f"\n[解析] 构建三层图...")
    for i, msg in enumerate(user_msgs):
        events = parser.parse(msg.content, msg.timestamp)
        if not events:
            failed += 1
        for e in events:
            topo.strengthen_or_create(
                source=e.get("agent", "用户"),
                target=e.get("target", msg.content),
                edge_type=e.get("edge_type", "knowledge"),
                metadata={"action": e.get("action", "其他"),
                           "raw_text": msg.content[:60]}
            )
        pct = (i + 1) / len(user_msgs) * 100
        print(f"\r  [{i+1}/{len(user_msgs)} {pct:.0f}%]", end="", flush=True)
        time.sleep(0.3)

    print(f"\n  解析完成! 失败: {failed}")
    stats_before = topo.stats
    print(f"  消前: {stats_before['node_count']}节点 {stats_before['edge_count']}边")
    print(f"  按类型: {stats_before['by_type']}")

    # ==========================================
    # 消化前：扩散测试
    # ==========================================
    print("\n" + "=" * 60)
    print("消化前: 知识网扩散测试")
    print("=" * 60)

    k_nodes = [t.target_id for t in topo.traces.values()
               if t.edge_type == "knowledge" and t.source_id == "用户"]
    k_weights = Counter(k_nodes).most_common(5)
    print(f"\n  核心节点:")
    for name, w in k_weights:
        print(f"    {name} (w={w})")

    for name, w in k_weights[:3]:
        activated = topo.spread_activation(name, "knowledge", depth=2)
        if activated:
            top_hits = sorted(activated.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"  '{name}' → {len(activated)} 个扩散节点")
            for node, energy in top_hits:
                print(f"    ↳ '{node}' (能量={energy:.2f})")
        else:
            print(f"  '{name}' → 无扩散（孤立）")

    # ==========================================
    # 执行消化
    # ==========================================
    print("\n" + "=" * 60)
    print("执行 Core 2 消化")
    print("=" * 60)

    digester = DigestionEngine(topo)
    result = digester.weave()

    print(f"\n  消化结果:")
    print(f"    碎片总数: {result['fragments_total']}")
    print(f"    分批: {result['batches']} 批")
    print(f"    发现关联: {result['links_found']} 条")
    print(f"    织入边: {result['edges_woven']} 条")

    stats_after = topo.stats
    print(f"\n  消后: {stats_after['node_count']}节点 {stats_after['edge_count']}边")
    print(f"  按类型: {stats_after['by_type']}")
    new_k_edges = stats_after['by_type'].get('knowledge', 0) - stats_before['by_type'].get('knowledge', 0)
    print(f"  知识网新增边: {new_k_edges}")

    # ==========================================
    # 消化后：扩散测试
    # ==========================================
    print("\n" + "=" * 60)
    print("消化后: 知识网扩散测试")
    print("=" * 60)

    for name, w in k_weights[:3]:
        activated = topo.spread_activation(name, "knowledge", depth=2)
        if activated:
            top_hits = sorted(activated.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"  '{name}' → {len(activated)} 个扩散节点")
            for node, energy in top_hits:
                print(f"    ↳ '{node}' (能量={energy:.2f})")
        else:
            print(f"  '{name}' → 无扩散（孤立）")

    # ==========================================
    # 消化后：检索对比
    # ==========================================
    print("\n" + "=" * 60)
    print("消化后: 检索对比")
    print("=" * 60)

    engine = ThreeLayerRecall(topo)
    test_queries = ["百年孤独", "云", "马尔克斯", "阅读", "记忆"]

    for query in test_queries:
        result = engine.recall(query)
        bl = result["by_layer"]
        print(f"\n'{query}': K={bl['knowledge']} I={bl['identity']} T={bl['timeline']}")
        for f in result["fragments"][:6]:
            layer_tag = {"knowledge": "K", "identity": "I", "timeline": "T"}.get(f.recall_layer, "?")
            path_short = f.recall_path.replace(f"'{query}'", "")
            print(f"  [{layer_tag}] {f.target[:40]} (w={f.weight:.0f}) {path_short[:30]}")

    print(f"\n✅ M11 Core 2 后台消化 - 测试完成")