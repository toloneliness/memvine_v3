# f:\memvine_v3.3\tests\test_m13_decay.py
"""
M13 P3 遗忘与衰减 - 三层差异化衰减策略
验证：时间链快速衰减、知识网引用衰减、身份关系稳定
"""

import json
import os
import sys
import time
from typing import List, Dict, Optional
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from test_m10_multiday_graph import (
    ThreeLayerTopology, ThreeLayerRecall, ThreeLayerParser,
    MemoryFragment, LogLoader, LLM_URL, LLM_KEY, LLM_MODEL
)
from test_m12_identity import save_graph, load_graph, CACHE_DIR, CACHE_FILE

class DecayEngine:
    """遗忘引擎 —— 三层差异化衰减"""

    def __init__(self, topology: ThreeLayerTopology):
        self.topo = topology

    def apply_timeline_decay(self, current_day: str, half_life_days: float = 3.0) -> Dict:
        """
        时间链衰减：越远的事件权重越低。
        半衰期 3 天 → 3 天前的权重 × 0.5，6 天前的 × 0.25
        """
        decayed = 0
        removed = 0
        keys_to_remove = []

        for key, t in self.topo.traces.items():
            if t.edge_type != "timeline":
                continue
            ts = t.metadata.get("timestamp", "")
            if not ts:
                continue
            # 简化：假设当前是 7月16日，计算天数差
            try:
                day = int(ts[8:10])
                current = int(current_day[8:10])
                days_ago = current - day
            except:
                days_ago = 0

            if days_ago <= 0:
                continue

            decay_factor = 0.5 ** (days_ago / half_life_days)
            new_weight = t.weight * decay_factor

            if new_weight < 0.1:
                keys_to_remove.append(key)
                removed += 1
            else:
                t.weight = new_weight
                decayed += 1

        for key in keys_to_remove:
            del self.topo.traces[key]

        return {"decayed": decayed, "removed": removed}

    def apply_knowledge_ref_decay(self, recall_counts: Dict[str, int],
                                   decay_rate: float = 0.2) -> Dict:
        """
        知识网引用衰减：被回想越多越稳固，从不被回想的慢慢消失。
        """
        decayed = 0
        removed = 0
        keys_to_remove = []

        for key, t in self.topo.traces.items():
            if t.edge_type != "knowledge":
                continue
            # 统计该节点被"想起"的次数
            refs = max(recall_counts.get(t.target_id, 0),
                        recall_counts.get(t.source_id, 0))

            if refs == 0:
                # 从未被想起 → 衰减
                t.weight -= decay_rate
                if t.weight <= 0:
                    keys_to_remove.append(key)
                    removed += 1
                else:
                    decayed += 1
            elif refs >= 3:
                # 高频回想 → 巩固
                t.weight = min(t.weight + 0.1, 10.0)

        for key in keys_to_remove:
            del self.topo.traces[key]

        return {"decayed": decayed, "removed": removed}

    def apply_identity_slow_decay(self, decay_rate: float = 0.01) -> Dict:
        """身份关系最慢衰减"""
        decayed = 0
        for key, t in self.topo.traces.items():
            if t.edge_type != "identity":
                continue
            if t.weight > 1.0:
                t.weight -= decay_rate
                decayed += 1
        return {"decayed": decayed, "removed": 0}

    def decay_all(self, current_day: str, recall_counts: Dict[str, int] = None) -> Dict:
        """执行全部三层衰减"""
        if recall_counts is None:
            recall_counts = {}

        results = {
            "timeline": self.apply_timeline_decay(current_day),
            "knowledge": self.apply_knowledge_ref_decay(recall_counts),
            "identity": self.apply_identity_slow_decay(),
        }
        return results

    def get_timeline_snapshot(self) -> List[Dict]:
        """时间链快照：按时间排列"""
        timeline = []
        for t in self.topo.traces.values():
            if t.edge_type == "timeline":
                timeline.append({
                    "target": t.target_id,
                    "weight": t.weight,
                    "timestamp": t.metadata.get("timestamp", ""),
                    "raw": t.metadata.get("raw_text", ""),
                })
        timeline.sort(key=lambda x: x["timestamp"])
        return timeline

# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "memvine_logs")
    DAYS = ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]

    print("=" * 60)
    print("M13 P3 遗忘与衰减 - 三层差异化衰减")
    print("=" * 60)

    # 加载图（缓存）
    topo = load_graph()
    if topo is None:
        print("请先运行 test_m12_identity.py 生成缓存")
        sys.exit(1)

    print(f"\n[加载] 从缓存: {topo.stats['node_count']}节点 {topo.stats['edge_count']}边")
    print(f"  按类型: {topo.stats['by_type']}")

    engine = DecayEngine(topo)

    # ==========================================
    # 测试 1: 衰减前时间链快照
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 1: 衰减前 - 时间链快照")
    print("=" * 60)

    timeline = engine.get_timeline_snapshot()
    print(f"\n  时间链事件: {len(timeline)} 条")
    for t in timeline[:10]:
        print(f"    {t['timestamp']} | w={t['weight']:.1f} | {t['target'][:30]}")

    # ==========================================
    # 测试 2: 执行衰减（模拟以 7月16日 为"现在"）
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 2: 执行三层衰减 (当前=7月16日)")
    print("=" * 60)

    # 模拟回想计数：某些查询被频繁使用
    recall_counts = {
        "小砂锅": 5,
        "我是小砂锅": 5,
        "百年孤独": 3,
        "阅读《百年孤独》": 3,
        "云": 4,
        "窗外云硕大洁白柔软": 4,
        "零": 3,
        "你是零": 3,
        "晚安": 1,
    }

    print(f"\n  模拟回想计数: {len(recall_counts)} 个节点被想起过")
    results = engine.decay_all("2026-07-16", recall_counts)

    print(f"\n  衰减结果:")
    print(f"    时间链: {results['timeline']['decayed']} 条衰减, {results['timeline']['removed']} 条删除")
    print(f"    知识网: {results['knowledge']['decayed']} 条衰减, {results['knowledge']['removed']} 条删除")
    print(f"    身份关系: {results['identity']['decayed']} 条衰减, {results['identity']['removed']} 条删除")

    # ==========================================
    # 测试 3: 衰减后时间链快照
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 3: 衰减后 - 时间链对比")
    print("=" * 60)

    timeline_after = engine.get_timeline_snapshot()
    print(f"\n  时间链事件: {len(timeline_after)} 条 (删除了 {len(timeline) - len(timeline_after)} 条)")
    for t in timeline_after[:10]:
        print(f"    {t['timestamp']} | w={t['weight']:.1f} | {t['target'][:30]}")

    # ==========================================
    # 测试 4: 衰减后检索对比
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 4: 衰减后检索对比")
    print("=" * 60)

    recall_engine = ThreeLayerRecall(topo)

    test_queries = [
        ("晚安", "时间链：7月13日的道别，应大幅衰减"),
        ("小砂锅", "身份：高频回想，应保持稳固"),
        ("百年孤独", "知识网：被想起过，应保持"),
        ("天气", "知识网：未被想起，应衰减"),
        ("时间", "时间链：7月15-16日，较近应保持"),
    ]

    for query, desc in test_queries:
        result = recall_engine.recall(query)
        bl = result["by_layer"]
        print(f"\n'{query}' ({desc})")
        print(f"  K={bl['knowledge']} I={bl['identity']} T={bl['timeline']}")

        for f in result["fragments"][:5]:
            if f.weight > 0:
                layer_tag = {"knowledge": "K", "identity": "I", "timeline": "T"}.get(f.recall_layer, "?")
                bar = "█" * min(int(f.weight), 10)
                print(f"  [{layer_tag}] {f.target[:35]} (w={f.weight:.1f}) {bar}")

    # ==========================================
    # 测试 5: 衰减后图统计
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 5: 衰减后图统计")
    print("=" * 60)

    stats = topo.stats
    print(f"\n  节点: {stats['node_count']}  边: {stats['edge_count']}")
    print(f"  按类型: {stats['by_type']}")

    # 权重分布
    weights = [t.weight for t in topo.traces.values()]
    print(f"\n  权重分布:")
    print(f"    w<0.5: {sum(1 for w in weights if w < 0.5)} 条")
    print(f"    0.5≤w<1: {sum(1 for w in weights if 0.5 <= w < 1)} 条")
    print(f"    1≤w<3: {sum(1 for w in weights if 1 <= w < 3)} 条")
    print(f"    w≥3: {sum(1 for w in weights if w >= 3)} 条")

    print(f"\n✅ M13 P3 遗忘与衰减 - 测试完成")