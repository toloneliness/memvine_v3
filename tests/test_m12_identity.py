# f:\memvine_v3.3\tests\test_m12_identity.py
"""
M12 P2 身份关系泛化 - 从离散碎片中提取稳定身份模型
LLM 审视所有身份碎片，合并同义表述，提取结构化身份
"""

import json
import os
import re
import sys
import time
import requests
from typing import List, Dict, Set, Tuple, Optional
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from test_m10_multiday_graph import (
    ThreeLayerTopology, ThreeLayerRecall, ThreeLayerParser,
    MemoryFragment, LogLoader, LLM_URL, LLM_KEY, LLM_MODEL
)


CACHE_DIR = os.path.join(os.path.dirname(__file__), "_cache")
CACHE_FILE = os.path.join(CACHE_DIR, "three_layer_graph.json")

def save_graph(topo: ThreeLayerTopology, days: List[str]):
    """持久化三层图到 JSON"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    data = {
        "days": days,
        "traces": []
    }
    for t in topo.traces.values():
        data["traces"].append({
            "source_id": t.source_id,
            "target_id": t.target_id,
            "edge_type": t.edge_type,
            "weight": t.weight,
            "metadata": t.metadata,
        })
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  图已缓存到: {CACHE_FILE}")

def load_graph() -> Optional[ThreeLayerTopology]:
    """从缓存加载三层图，不存在则返回 None"""
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    topo = ThreeLayerTopology()
    from dataclasses import dataclass, field
    for t in data["traces"]:
        topo.strengthen_or_create(
            source=t["source_id"],
            target=t["target_id"],
            edge_type=t["edge_type"],
            metadata=t["metadata"],
        )
        topo.traces[topo._key(t["source_id"], t["target_id"], t["edge_type"])].weight = t["weight"]
    print(f"  从缓存加载: {topo.stats['node_count']}节点 {topo.stats['edge_count']}边")
    return topo

class IdentityGeneralizer:
    """身份泛化引擎 —— 从离散碎片中提取稳定身份模型"""

    def __init__(self, topology: ThreeLayerTopology):
        self.topo = topology

    def get_identity_fragments(self) -> List[Dict]:
        """提取所有身份关系碎片，带权重"""
        fragments = []
        for t in self.topo.traces.values():
            if t.edge_type == "identity":
                fragments.append({
                    "source": t.source_id,
                    "target": t.target_id,
                    "weight": t.weight,
                    "action": t.metadata.get("action", ""),
                    "raw_text": t.metadata.get("raw_text", ""),
                })
        return fragments

    def generalize(self) -> Dict:
        """让 LLM 审视所有身份碎片，提取结构化身份"""
        fragments = self.get_identity_fragments()
        print(f"\n  身份碎片总数: {len(fragments)}")

        # 按权重排序，取 top 15 给 LLM（太多了易超时）
        sorted_frags = sorted(fragments, key=lambda x: x["weight"], reverse=True)
        sample = sorted_frags[:15]

        fragment_text = "\n".join(
            f"- [{f['action']}] {f['source']} → {f['target']} (提及{f['weight']:.0f}次) 原文: {f['raw_text']}"
            for f in sample
        )

        prompt = f"""你是身份分析器。分析以下对话中的身份碎片，提取稳定的身份模型。

身份碎片:
{fragment_text}

请提取结构化身份信息，输出JSON。格式:
{{
  "entities": [
    {{
      "name": "实体名（如 用户/AI）",
      "known_names": ["已知的名字列表"],
      "role": "角色描述",
      "self_description": ["自我描述/定位"],
      "relationships": ["与其他实体的关系"],
      "confidence": 0.9,
      "evidence": ["关键证据1", "关键证据2"]
    }}
  ],
  "conflicts": [
    {{
      "entity": "冲突实体",
      "claim1": "主张1",
      "claim2": "主张2",
      "resolution": "如何理解（如：名字变更/多个名字/不同语境）"
    }}
  ]
}}

规则:
1. 合并同义表述
2. 识别名字变更
3. 检测冲突
4. 只返回JSON

JSON输出:"""

        try:
            resp = requests.post(
                f"{LLM_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_KEY}"},
                json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.2},
                timeout=120
            )
            content = resp.json()['choices'][0]['message']['content']
            content = content.strip().replace("```json", "").replace("```", "")
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
                return {"entities": [], "conflicts": []}
        except Exception as e:
            print(f"  LLM 调用失败: {e}")
            return {"entities": [], "conflicts": []}

class IdentityAwareRecall(ThreeLayerRecall):
    """带身份模型的检索引擎"""

    def __init__(self, topology: ThreeLayerTopology, identity_model: Dict = None):
        super().__init__(topology)
        self.identity_model = identity_model or {}

    def ask_identity(self, intent: str) -> str:
        """回答身份类问题"""
        entities = self.identity_model.get("entities", [])

        if "你是谁" in intent or "你叫什么" in intent or "你的名字" in intent:
            for e in entities:
                if e.get("role") and "AI" in e.get("role", ""):
                    names = "、".join(e.get("known_names", ["未知"]))
                    desc = "、".join(e.get("self_description", []))
                    return f"我是{names}，{desc}。" if desc else f"我是{names}。"

        if "我是谁" in intent or "我叫什么" in intent or "我的名字" in intent:
            for e in entities:
                if "用户" in e.get("role", "") or "用户" in e.get("name", ""):
                    names = "、".join(e.get("known_names", ["未知"]))
                    desc = "、".join(e.get("self_description", []))
                    return f"你是{names}，{desc}。" if desc else f"你是{names}。"

        if "我们是什么关系" in intent:
            rels = []
            for e in entities:
                for r in e.get("relationships", []):
                    rels.append(r)
            return "我们的关系：\n" + "\n".join(f"  · {r}" for r in rels) if rels else "我不确定我们的关系。"

        return None

    def recall_with_identity(self, query: str) -> Dict:
        """增强检索：身份类问题优先用身份模型回答"""
        identity_answer = self.ask_identity(query)
        if identity_answer:
            # 仍然走标准检索，但添加身份模型的答案
            result = self.recall(query)
            result["identity_answer"] = identity_answer
            return result
        return self.recall(query)

# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "memvine_logs")
    DAYS = ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]

    print("=" * 60)
    print("M12 P2 身份关系泛化 - 从碎片到模型")
    print("=" * 60)

    try:
        requests.get(f"{LLM_URL}/models", timeout=5)
    except:
        print("LM Studio 未启动！")
        sys.exit(1)

    # 加载并解析
    loader = LogLoader(LOG_DIR)
    all_msgs = loader.load_range(DAYS[0], DAYS[-1])
    user_msgs = loader.filter_by_speaker(all_msgs, "user")
    print(f"\n[加载] {len(user_msgs)} 条用户消息 ({len(DAYS)} 天)")

    # 尝试从缓存加载
    topo = load_graph()

    if topo is None:
        parser = ThreeLayerParser()
        topo = ThreeLayerTopology()
        failed = 0

        print(f"\n[解析] 缓存未命中，构建三层图...")
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
                               "raw_text": msg.content[:60],
                               "timestamp": msg.timestamp}
                )
            pct = (i + 1) / len(user_msgs) * 100
            print(f"\r  [{i+1}/{len(user_msgs)} {pct:.0f}%]", end="", flush=True)
            time.sleep(0.3)

        print(f"\n  解析完成! 失败: {failed}")
        save_graph(topo, DAYS)
    else:
        print(f"  跳过解析（缓存命中）")

    stats = topo.stats
    print(f"  图: {stats['node_count']}节点 {stats['edge_count']}边")
    print(f"  按类型: {stats['by_type']}")

    # ==========================================
    # 测试 1: 身份碎片概览
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 1: 身份碎片概览")
    print("=" * 60)

    generalizer = IdentityGeneralizer(topo)
    id_frags = generalizer.get_identity_fragments()

    # 按权重排序
    id_frags.sort(key=lambda x: x["weight"], reverse=True)
    print(f"\n  身份碎片总数: {len(id_frags)}")
    print(f"\n  Top 10 身份碎片:")
    for f in id_frags[:10]:
        print(f"    [{f['action']}] {f['source']} → {f['target']} (w={f['weight']:.0f}) 「{f['raw_text']}」")

    # 按 source 聚合
    by_source = defaultdict(list)
    for f in id_frags:
        by_source[f["source"]].append(f["target"])
    print(f"\n  按来源聚合:")
    for src, targets in sorted(by_source.items()):
        print(f"    {src} → {len(targets)} 个目标: {targets[:5]}...")

    # ==========================================
    # 测试 2: LLM 身份泛化
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 2: LLM 身份泛化")
    print("=" * 60)

    identity_model = generalizer.generalize()

    print(f"\n  提取的实体数: {len(identity_model.get('entities', []))}")
    for e in identity_model.get("entities", []):
        print(f"\n  ┌─ {e.get('name', '?')}")
        print(f"  ├ 名字: {e.get('known_names', [])}")
        print(f"  ├ 角色: {e.get('role', '?')}")
        print(f"  ├ 自我描述: {e.get('self_description', [])}")
        print(f"  ├ 关系: {e.get('relationships', [])}")
        print(f"  ├ 置信度: {e.get('confidence', '?')}")
        print(f"  └ 证据: {e.get('evidence', [])[:3]}")

    conflicts = identity_model.get("conflicts", [])
    if conflicts:
        print(f"\n  ⚠️ 检测到 {len(conflicts)} 个冲突:")
        for c in conflicts:
            print(f"    {c.get('entity')}: {c.get('claim1')} vs {c.get('claim2')}")
            print(f"      → {c.get('resolution')}")
    else:
        print(f"\n  无身份冲突")

    # ==========================================
    # 测试 3: 身份感知检索
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 3: 身份感知检索")
    print("=" * 60)

    engine = IdentityAwareRecall(topo, identity_model)

    identity_queries = [
        "你是谁",
        "你叫什么名字",
        "我是谁",
        "我的名字是什么",
        "我们是什么关系",
        "你的名字",
        "零",
        "小砂锅",
        "藤蔓",
    ]

    for q in identity_queries:
        result = engine.recall_with_identity(q)
        bl = result["by_layer"]
        print(f"\n'{q}': K={bl['knowledge']} I={bl['identity']} T={bl['timeline']}")

        if "identity_answer" in result:
            print(f"  💬 身份模型回答: {result['identity_answer']}")

        for f in result["fragments"][:4]:
            layer_tag = {"knowledge": "K", "identity": "I", "timeline": "T"}.get(f.recall_layer, "?")
            print(f"  [{layer_tag}] {f.target[:40]} (w={f.weight:.0f})")

    # ==========================================
    # 测试 4: 身份模型持久化预览
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 4: 身份模型 JSON")
    print("=" * 60)

    print(json.dumps(identity_model, ensure_ascii=False, indent=2))

    print(f"\n✅ M12 P2 身份关系泛化 - 测试完成")