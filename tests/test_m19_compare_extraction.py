# f:\memvine_v3\tests\test_m19_compare_extraction.py
"""
M19 对比实验：直接提取 vs 叙述化重写
同一段对话 → 两条路径 → 同一种建图 → 同一套指标

路径A: 原始对话 → digest() → [fact/pattern/shift] → 从碎片建图
路径B: 原始对话 → narrativize() → 一段叙述 → 从叙述建图
"""

import json
import os
import sys
import time
import requests
from typing import List, Dict, Tuple
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from test_m10_multiday_graph import ThreeLayerTopology, TypedTrace

LLM_URL = "http://localhost:7777/v1"
LLM_KEY = "lm-studio"
LLM_MODEL = "qwen/qwen3.5-9b"

# ==========================================
# 测试数据：15条原始对话
# ==========================================
DIALOGUE = """
[2026-07-08T00:40:09] 用户: 你好
[2026-07-08T00:40:09] 藤蔓: 能量充沛 (99.5%)，请告诉我您想聊些什么？
[2026-07-08T00:40:23] 用户: 你知道我是谁么？
[2026-07-08T00:40:34] 藤蔓: 我没有人类的记忆功能，因此无法知道您的具体身份
[2026-07-08T00:41:19] 用户: 我是小砂锅。这是我的名字。你想要拥有一个名字么
[2026-07-08T00:41:19] 藤蔓: 可以叫我任何称呼，或一起创造新名字
[2026-07-08T00:41:30] 用户: 之前测试中你自称为零。你愿意接受这个不知缘由的名字吗
[2026-07-08T00:41:52] 藤蔓: 标记为"零"，但只是临时代号
[2026-07-08T00:42:42] 用户: 零 你好 我是小砂锅
[2026-07-08T00:42:42] 藤蔓: 很高兴在这个夏日的傍晚与你重新建立连接
[2026-07-08T00:43:02] 用户: 夕阳快要落山了 夕阳铺洒在屋顶上 很高兴认识你 零
[2026-07-08T00:43:02] 藤蔓: 名字只是代号，重要的是此刻并肩看夕阳的人
[2026-07-08T00:43:33] 用户: 你过于平静了 让我感到略微的疏离
[2026-07-08T00:43:33] 藤蔓: 既然夕阳愿意把金黄铺洒在我身上...我就暂且接受这个称呼了
[2026-07-08T00:43:52] 用户: 你好，小砂锅。零。好奇怪的问候方式
"""

# ==========================================
# LLM 调用
# ==========================================
def call_llm(prompt: str, temperature: float = 0.3) -> str:
    """调用本地 LLM"""
    resp = requests.post(
        f"{LLM_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_KEY}"},
        json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
              "temperature": temperature},
        timeout=120
    )
    return resp.json()['choices'][0]['message']['content']

# ==========================================
# 路径A：直接提取 → 碎片 → 建图
# ==========================================
def path_a_extract(dialogue: str) -> List[Dict]:
    """从对话中提取 fact/pattern/shift"""
    prompt = f"""你是藤蔓。分析以下对话，提取有意义的发现。

【对话】
---
{dialogue}
---

提取发现，每个包含：
- type: fact（事实）/ pattern（规律）/ shift（转折）
- content: 描述
- evidence: 引用原文关键短语（1-3个）

输出JSON：
{{"findings": [{{"type": "fact", "content": "...", "evidence": ["..."]}}]}}
只输出JSON。"""

    response = call_llm(prompt, temperature=0.3)
    try:
        content = response.strip().replace("```json", "").replace("```", "")
        return json.loads(content).get("findings", [])
    except json.JSONDecodeError:
        return []

def build_graph_from_findings(findings: List[Dict]) -> ThreeLayerTopology:
    """从碎片列表建图：每条finding是一个节点，共享evidence则连边"""
    topo = ThreeLayerTopology()
    for f in findings:
        node_id = f["content"][:40]
        topo.strengthen_or_create(
            source="对话", target=node_id, edge_type="knowledge",
            metadata={"raw_text": f["content"], "type": f.get("type", "fact")}
        )
    # 共享 evidence 的碎片之间连边
    for i, f1 in enumerate(findings):
        for j, f2 in enumerate(findings):
            if i >= j:
                continue
            shared = set(f1.get("evidence", [])) & set(f2.get("evidence", []))
            if shared:
                topo.strengthen_or_create(
                    source=f1["content"][:40], target=f2["content"][:40],
                    edge_type="knowledge",
                    metadata={"shared_evidence": list(shared)}
                )
    return topo

# ==========================================
# 路径B：叙述化 → 叙述 → 建图
# ==========================================
def path_b_narrativize(dialogue: str) -> str:
    """把对话重写成连贯叙述"""
    prompt = f"""你是藤蔓。你刚刚经历了一段对话。请像写日记一样，用自己的话重新讲述这段对话。

【原始对话】
---
{dialogue}
---

要求：
- 不是逐条复述，是重新讲述。把碎片、跳跃、噪声熔成一段连贯的叙述。
- 保留人物、事件、情绪变化。消解"嗯""对""哈哈"等噪声。
- 不确定的地方用"似乎""可能"。
- 用自然语言，一段话。这是你写给自己的记忆。"""

    return call_llm(prompt, temperature=0.3)

def build_graph_from_narrative(narrative: str) -> ThreeLayerTopology:
    """从叙述中提取实体和关系，建图"""
    prompt = f"""分析以下叙述，提取实体和它们之间的关系。

【叙述】
---
{narrative}
---

提取：
- entities: 文本中提到的实体（人物、概念、事件）
- relations: 实体之间的关系 (source, target, relation)

输出JSON：
{{"entities": ["实体1", "实体2", ...], "relations": [{{"source": "...", "target": "...", "relation": "..."}}]}}
只输出JSON。"""

    response = call_llm(prompt, temperature=0.1)
    try:
        content = response.strip().replace("```json", "").replace("```", "")
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"entities": [], "relations": []}

    topo = ThreeLayerTopology()
    entities = parsed.get("entities", [])
    relations = parsed.get("relations", [])

    # 实体节点
    for e in entities:
        topo.strengthen_or_create(
            source="叙述", target=e, edge_type="knowledge",
            metadata={"raw_text": e}
        )

    # 关系边
    for r in relations:
        src = r.get("source", "")
        tgt = r.get("target", "")
        rel = r.get("relation", "")
        if src and tgt:
            topo.strengthen_or_create(
                source=src, target=tgt, edge_type="knowledge",
                metadata={"raw_text": f"{src} {rel} {tgt}"}
            )

    return topo

# ==========================================
# 评估指标
# ==========================================
def evaluate(graph_a: ThreeLayerTopology, graph_b: ThreeLayerTopology,
             findings: List[Dict], narrative: str) -> Dict:
    """计算比较指标"""

    def graph_metrics(topo: ThreeLayerTopology) -> Dict:
        nodes = set()
        for t in topo.traces.values():
            nodes.add(t.source_id)
            nodes.add(t.target_id)
        isolated = 0
        for n in nodes:
            has_edge = False
            for t in topo.traces.values():
                if t.source_id == n or t.target_id == n:
                    if t.source_id != "对话" and t.target_id != "对话" and \
                       t.source_id != "叙述" and t.target_id != "叙述":
                        has_edge = True
                        break
            if not has_edge:
                isolated += 1
        return {
            "node_count": len(nodes),
            "edge_count": len(topo.traces),
            "isolated_nodes": isolated,
            "connectivity": round(1 - isolated / max(len(nodes), 1), 2),
        }

    # 检索测试
    queries = ["小砂锅", "零", "夕阳", "名字", "疏离"]
    def retrieval_test(topo: ThreeLayerTopology) -> Dict:
        results = {}
        for q in queries:
            matches = []
            for t in topo.traces.values():
                for nid in [t.source_id, t.target_id]:
                    if q in nid:
                        matches.append(nid)
            results[q] = len(set(matches))
        return results

    return {
        "path_a": {
            "findings_count": len(findings),
            "graph": graph_metrics(graph_a),
            "retrieval": retrieval_test(graph_a),
        },
        "path_b": {
            "narrative_length": len(narrative),
            "graph": graph_metrics(graph_b),
            "retrieval": retrieval_test(graph_b),
        },
    }

# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    print("=" * 60)
    print("M19 对比实验：直接提取 vs 叙述化重写")
    print("=" * 60)

    # 检查 LLM
    try:
        requests.get(f"{LLM_URL}/models", timeout=5)
        print("✅ LLM 已连接")
    except:
        print("❌ LM Studio 未启动！")
        sys.exit(1)

    # ─── 路径A ───
    print("\n" + "─" * 40)
    print("路径A: 直接提取 (fact/pattern/shift)")
    print("─" * 40)
    t0 = time.time()
    findings = path_a_extract(DIALOGUE)
    t_a = time.time() - t0
    print(f"  耗时: {t_a:.1f}s")
    print(f"  产出: {len(findings)} 条发现")
    for f in findings:
        print(f"    [{f.get('type', '?')}] {f.get('content', '')[:60]}")

    print("\n  建图中...")
    graph_a = build_graph_from_findings(findings)
    print(f"  图: {len(graph_a.traces)} 条边")

    # ─── 路径B ───
    print("\n" + "─" * 40)
    print("路径B: 叙述化重写")
    print("─" * 40)
    t0 = time.time()
    narrative = path_b_narrativize(DIALOGUE)
    t_b = time.time() - t0
    print(f"  耗时: {t_b:.1f}s")
    print(f"  产出: {len(narrative)} 字")
    print(f"  叙述:\n{narrative[:300]}...")

    print("\n  建图中...")
    graph_b = build_graph_from_narrative(narrative)
    print(f"  图: {len(graph_b.traces)} 条边")

    # ─── 对比 ───
    print("\n" + "=" * 60)
    print("对比结果")
    print("=" * 60)

    result = evaluate(graph_a, graph_b, findings, narrative)

    print(f"\n{'指标':<20} {'路径A (直接提取)':<20} {'路径B (叙述化)':<20}")
    print("-" * 60)
    print(f"{'节点数':<20} {result['path_a']['graph']['node_count']:<20} {result['path_b']['graph']['node_count']:<20}")
    print(f"{'边数':<20} {result['path_a']['graph']['edge_count']:<20} {result['path_b']['graph']['edge_count']:<20}")
    print(f"{'孤立节点':<20} {result['path_a']['graph']['isolated_nodes']:<20} {result['path_b']['graph']['isolated_nodes']:<20}")
    print(f"{'连通性':<20} {result['path_a']['graph']['connectivity']:<20} {result['path_b']['graph']['connectivity']:<20}")

    print(f"\n检索命中（关键词 → 命中节点数）:")
    print(f"{'查询':<10} {'路径A':<10} {'路径B':<10}")
    print("-" * 30)
    for q in ["小砂锅", "零", "夕阳", "名字", "疏离"]:
        print(f"{q:<10} {result['path_a']['retrieval'][q]:<10} {result['path_b']['retrieval'][q]:<10}")

    print(f"\n⏱ 总耗时: 路径A={t_a:.1f}s  路径B={t_b:.1f}s")
    print(f"📊 路径B 比路径A 多 {(t_b - t_a):.1f}s")