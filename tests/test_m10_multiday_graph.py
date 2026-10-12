"""
M10 多天三层记忆图 - P0 上规模验证
加载 7月13-16日（4天），构建完整三层图，验证跨天检索
"""

import json
import os
import re
import sys
import time
import requests
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass, field
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from test_m1_data_loader import LogLoader, ChatMessage

LLM_URL = "http://localhost:7777/v1"
LLM_KEY = "lm-studio"
LLM_MODEL = "qwen/qwen3.5-9b"

# ==========================================
# 数据结构（复用 M9）
# ==========================================
@dataclass
class TypedTrace:
    source_id: str
    target_id: str
    edge_type: str
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)

class ThreeLayerTopology:
    def __init__(self):
        self.traces: Dict[str, TypedTrace] = {}

    def _key(self, source: str, target: str, edge_type: str) -> str:
        return f"{source}->{target}::{edge_type}"

    def strengthen_or_create(self, source: str, target: str, edge_type: str,
                              metadata: Dict = None) -> TypedTrace:
        key = self._key(source, target, edge_type)
        if key in self.traces:
            self.traces[key].weight += 1.0
            if metadata:
                self.traces[key].metadata.update(metadata)
        else:
            self.traces[key] = TypedTrace(source, target, edge_type, 1.0,
                                           metadata=metadata or {})
        return self.traces[key]

    def spread_activation(self, start_node: str, edge_type: str, depth: int = 2,
                           exclude_nodes: Set[str] = None) -> Dict[str, float]:
        if exclude_nodes is None:
            exclude_nodes = {"用户"}
        activated: Dict[str, float] = {start_node: 1.0}
        visited: Set[str] = exclude_nodes | {start_node}
        for d in range(depth):
            new_frontier: Dict[str, float] = {}
            for node, energy in activated.items():
                for t in self.traces.values():
                    if t.edge_type != edge_type:
                        continue
                    if t.source_id == node and t.target_id not in visited:
                        new_energy = energy * 0.6 * t.weight
                        new_frontier[t.target_id] = new_frontier.get(t.target_id, 0) + new_energy
                        visited.add(t.target_id)
                    elif t.target_id == node and t.source_id not in visited:
                        new_energy = energy * 0.6 * t.weight
                        new_frontier[t.source_id] = new_frontier.get(t.source_id, 0) + new_energy
                        visited.add(t.source_id)
            activated = new_frontier
            if not activated:
                break
        return activated

    @property
    def stats(self) -> Dict:
        nodes = set()
        for t in self.traces.values():
            nodes.add(t.source_id)
            nodes.add(t.target_id)
        weights = [t.weight for t in self.traces.values()]
        type_counts = Counter(t.edge_type for t in self.traces.values())
        return {
            "node_count": len(nodes),
            "edge_count": len(self.traces),
            "total_weight": sum(weights),
            "by_type": dict(type_counts),
        }

@dataclass
class MemoryFragment:
    target: str
    action: str
    edge_type: str
    raw_text: str
    weight: float
    recall_layer: str
    recall_path: str

class ThreeLayerRecall:
    def __init__(self, topology: ThreeLayerTopology):
        self.topo = topology
        self._build_index()

    def _build_index(self):
        self.nodes: Dict[str, List[TypedTrace]] = {}
        for t in self.topo.traces.values():
            for nid in [t.source_id, t.target_id]:
                if nid not in self.nodes:
                    self.nodes[nid] = []
                self.nodes[nid].append(t)
        self.all_node_names = list(self.nodes.keys())

    def _find_nodes(self, query: str) -> List[str]:
        q = query.lower()
        q_chars = set(q)
        matches = []
        for name in self.all_node_names:
            if name == "用户":
                continue
            nl = name.lower()
            if q in nl:
                matches.append(name)
                continue
            matched = False
            for win in [2, 3, 4]:
                for i in range(len(nl) - win + 1):
                    if nl[i:i+win] in q:
                        matches.append(name)
                        matched = True
                        break
                if matched:
                    break
            if matched:
                continue
            n_chars = set(nl)
            overlap = len(q_chars & n_chars)
            if overlap >= max(2, len(q_chars) * 0.5):
                matches.append(name)
        return matches

    def recall_knowledge(self, query: str) -> List[MemoryFragment]:
        seeds = self._find_nodes(query)
        if not seeds:
            return []
        # 用 dict 去重：同一 target 只保留权重最高的
        frag_map: Dict[str, MemoryFragment] = {}
        for seed in seeds:
            for t in self.nodes.get(seed, []):
                if t.edge_type == "knowledge":
                    f = MemoryFragment(
                        target=seed, action=t.metadata.get("action", ""),
                        edge_type="knowledge", raw_text=t.metadata.get("raw_text", ""),
                        weight=t.weight, recall_layer="knowledge",
                        recall_path=f"知识网直接: '{query}' → '{seed}'"
                    )
                    if seed not in frag_map or f.weight > frag_map[seed].weight:
                        frag_map[seed] = f
        all_activated = {}
        for seed in seeds:
            activated = self.topo.spread_activation(seed, "knowledge", depth=2)
            for node, energy in activated.items():
                if node not in all_activated or energy > all_activated[node]:
                    all_activated[node] = energy
        for node, energy in sorted(all_activated.items(), key=lambda x: x[1], reverse=True):
            # 扩散结果可能在直接命中中已存在，跳过
            if node in frag_map:
                continue
            for t in self.nodes.get(node, []):
                if t.edge_type == "knowledge":
                    f = MemoryFragment(
                        target=node, action=t.metadata.get("action", ""),
                        edge_type="knowledge", raw_text=t.metadata.get("raw_text", ""),
                        weight=t.weight, recall_layer="knowledge",
                        recall_path=f"知识网扩散: '{query}' → '{node}' (能量={energy:.2f})"
                    )
                    if node not in frag_map or f.weight > frag_map[node].weight:
                        frag_map[node] = f
                    break  # 每个扩散节点只取第一条
        return sorted(frag_map.values(), key=lambda x: x.weight, reverse=True)

    def recall_identity(self, query: str) -> List[MemoryFragment]:
        seeds = self._find_nodes(query)
        if not seeds:
            return []
        frag_map = {}
        for seed in seeds:
            for t in self.nodes.get(seed, []):
                if t.edge_type == "identity":
                    f = MemoryFragment(
                        target=seed, action=t.metadata.get("action", ""),
                        edge_type="identity", raw_text=t.metadata.get("raw_text", ""),
                        weight=t.weight, recall_layer="identity",
                        recall_path=f"身份匹配: '{query}' → '{seed}'"
                    )
                    if seed not in frag_map or f.weight > frag_map[seed].weight:
                        frag_map[seed] = f
        return sorted(frag_map.values(), key=lambda x: x.weight, reverse=True)


    def recall_timeline(self, query: str) -> List[MemoryFragment]:
        seeds = self._find_nodes(query)
        if not seeds:
            return []
        frag_map = {}
        for seed in seeds:
            for t in self.nodes.get(seed, []):
                if t.edge_type == "timeline":
                    f = MemoryFragment(
                        target=seed, action=t.metadata.get("action", ""),
                        edge_type="timeline", raw_text=t.metadata.get("raw_text", ""),
                        weight=t.weight, recall_layer="timeline",
                        recall_path=f"时间链匹配: '{query}' → '{seed}'"
                    )
                    if seed not in frag_map or f.weight > frag_map[seed].weight:
                        frag_map[seed] = f
        return sorted(frag_map.values(), key=lambda x: x.weight, reverse=True)

    def recall(self, query: str) -> Dict:
        knowledge = self.recall_knowledge(query)
        identity = self.recall_identity(query)
        timeline = self.recall_timeline(query)
        # 跨层去重：同一 target 只保留第一次出现的层
        seen = set()
        all_fragments = []
        for f in knowledge + identity + timeline:
            if f.target not in seen:
                seen.add(f.target)
                all_fragments.append(f)
        all_fragments.sort(key=lambda x: x.weight, reverse=True)
        return {
            "query": query,
            "total": len(all_fragments),
            "by_layer": {"knowledge": len(knowledge), "identity": len(identity), "timeline": len(timeline)},
            "fragments": all_fragments,
        }

    def format_recall(self, result: Dict) -> str:
        fragments = result["fragments"]
        query = result["query"]
        by_layer = result["by_layer"]
        if not fragments:
            return f"关于'{query}'，没有任何记忆。"
        lines = [f"关于'{query}'："]
        lines.append(f"  (知识网:{by_layer['knowledge']} 身份:{by_layer['identity']} 时间链:{by_layer['timeline']})")
        lines.append("")
        layer_names = {"knowledge": "知识网", "identity": "身份关系", "timeline": "时间链"}
        layer_icons = {"knowledge": "🧠", "identity": "👤", "timeline": "⏱️"}
        current_layer = None
        for f in fragments[:12]:
            if f.recall_layer != current_layer:
                current_layer = f.recall_layer
                lines.append(f"  {layer_icons.get(current_layer, '')} {layer_names.get(current_layer, '')}：")
            action_phrases = {"告知": "说过", "询问": "问过", "表达情绪": "感慨过",
                              "回忆": "回忆起", "观察": "注意到", "思考": "思考过",
                              "评价": "评论过", "请求": "希望", "拒绝": "拒绝了"}
            phrase = action_phrases.get(f.action, "提到过")
            lines.append(f"    · {phrase}「{f.target}」(w={f.weight:.0f})")
        return "\n".join(lines)

# ==========================================
# LLM 解析器（带 edge_type）
# ==========================================
class ThreeLayerParser:
    def parse(self, raw_text: str, timestamp: str = "") -> List[Dict]:
        allowed_actions = [
            "告知", "询问", "表达情绪", "评价", "回忆", "转移",
            "拒绝", "请求", "命令", "观察", "思考", "其他"
        ]
        actions_str = ", ".join(allowed_actions)

        prompt = f"""你是高级记忆解析器。将人类记忆拆解为JSON事件数组，每个事件必须包含edge_type字段。

edge_type 三选一：
- "timeline": 时间顺序事件（问候、道别、时间相关陈述、日常叙述）
- "identity": 身份/关系（自我介绍、对方身份、角色关系、归属）
- "knowledge": 知识/概念（事实陈述、作品讨论、抽象思考、评价、观察）

action 从以下选择：[{actions_str}]。
complexity(0-1)，expressiveness(0-1)。

示例:
记忆: "你好，我是小砂锅，喜欢读书。昨天读了《百年孤独》，马尔克斯写的。"
JSON输出:
[
  {{"agent":"用户","action":"告知","target":"打招呼","edge_type":"timeline","complexity":0.1,"expressiveness":0.9}},
  {{"agent":"用户","action":"告知","target":"我是小砂锅","edge_type":"identity","complexity":0.1,"expressiveness":0.9}},
  {{"agent":"用户","action":"表达情绪","target":"喜欢读书","edge_type":"identity","complexity":0.2,"expressiveness":0.8}},
  {{"agent":"用户","action":"回忆","target":"阅读《百年孤独》","edge_type":"knowledge","complexity":0.3,"expressiveness":0.8}},
  {{"agent":"马尔克斯","action":"告知","target":"写了《百年孤独》","edge_type":"knowledge","complexity":0.2,"expressiveness":0.9}}
]

现在解析（只返回JSON数组）：
记忆: "{raw_text}"
JSON输出:"""

        try:
            resp = requests.post(
                f"{LLM_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_KEY}"},
                json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.2},
                timeout=30
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

# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "memvine_logs")
    DAYS = ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]

    print("=" * 60)
    print("M10 多天三层记忆图 - P0 上规模验证")
    print("=" * 60)

    try:
        requests.get(f"{LLM_URL}/models", timeout=5)
    except:
        print("LM Studio 未启动！")
        sys.exit(1)

    # 加载
    loader = LogLoader(LOG_DIR)
    print(f"\n[加载] {len(DAYS)} 天数据...")
    all_msgs = loader.load_range(DAYS[0], DAYS[-1])
    user_msgs = loader.filter_by_speaker(all_msgs, "user")
    print(f"  总消息: {len(all_msgs)}  用户消息: {len(user_msgs)}")

    # 按天统计
    day_counts = Counter()
    for m in user_msgs:
        day_counts[m.timestamp[:10]] += 1
    for d in DAYS:
        print(f"  {d}: {day_counts.get(d, 0)} 条")

    # 解析
    parser = ThreeLayerParser()
    topo = ThreeLayerTopology()
    type_counter = Counter()
    failed = 0
    day_events = defaultdict(int)

    print(f"\n[解析] {len(user_msgs)} 条消息，LLM 分类 edge_type...")
    for i, msg in enumerate(user_msgs):
        events = parser.parse(msg.content, msg.timestamp)
        if not events:
            failed += 1
        for e in events:
            et = e.get("edge_type", "knowledge")
            type_counter[et] += 1
            day_events[msg.timestamp[:10]] += 1
            topo.strengthen_or_create(
                source=e.get("agent", "用户"),
                target=e.get("target", msg.content),
                edge_type=et,
                metadata={"action": e.get("action", "其他"),
                           "raw_text": msg.content[:60],
                           "timestamp": msg.timestamp}
            )
        pct = (i + 1) / len(user_msgs) * 100
        print(f"\r  [{i+1}/{len(user_msgs)} {pct:.0f}%] "
              f"T={type_counter.get('timeline',0)} "
              f"I={type_counter.get('identity',0)} "
              f"K={type_counter.get('knowledge',0)}", end="", flush=True)
        time.sleep(0.3)

    print(f"\n\n  解析完成! 失败: {failed}")
    print(f"  事件分布: {dict(type_counter)}")

    stats = topo.stats
    print(f"\n[图统计]")
    print(f"  总节点: {stats['node_count']}  总边: {stats['edge_count']}")
    print(f"  按类型: {stats['by_type']}")

    # 按天的事件分布
    print(f"\n[按天事件分布]")
    for d in DAYS:
        print(f"  {d}: {day_events.get(d, 0)} 个事件")

    # 检索引擎
    engine = ThreeLayerRecall(topo)

    # ==========================================
    # 测试 1: 跨天查询
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 1: 跨天检索")
    print("=" * 60)

    cross_day_queries = [
        ("小砂锅", "身份：4天中反复出现的身份"),
        ("名字", "身份：多天多次问名字"),
        ("云", "知识：7月15日密集聊云"),
        ("百年孤独", "知识：7月15日聊书"),
        ("时间", "时间链：每天都有的时间陈述"),
        ("晚安", "时间链：每天都有的道别"),
        ("零", "身份：7月13日引入的身份"),
        ("记忆", "跨层：多天都有记忆相关"),
    ]

    for query, desc in cross_day_queries:
        result = engine.recall(query)
        bl = result["by_layer"]
        print(f"\n'{query}' ({desc})")
        print(f"  K={bl['knowledge']} I={bl['identity']} T={bl['timeline']} 总计={result['total']}")
        for f in result["fragments"][:5]:
            layer_tag = {"knowledge": "K", "identity": "I", "timeline": "T"}.get(f.recall_layer, "?")
            print(f"  [{layer_tag}] {f.target[:45]} (w={f.weight:.0f})")

    # ==========================================
    # 测试 2: 知识网扩散验证
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 2: 知识网扩散联想")
    print("=" * 60)

    # 找知识网中权重最高的节点，测试扩散
    k_edges = [(t.target_id, t.weight) for t in topo.traces.values()
               if t.edge_type == "knowledge" and t.source_id == "用户"]
    k_edges.sort(key=lambda x: x[1], reverse=True)
    print(f"\n  知识网核心节点 (top 10):")
    for name, w in k_edges[:10]:
        print(f"    {name} (w={w:.0f})")

    # 对核心节点做扩散
    print(f"\n  扩散测试（从核心节点出发，depth=2）:")
    for name, w in k_edges[:5]:
        activated = topo.spread_activation(name, "knowledge", depth=2)
        if activated:
            top_hits = sorted(activated.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"  '{name}' → {len(activated)} 个关联节点")
            for node, energy in top_hits:
                print(f"    ↳ '{node}' (能量={energy:.2f})")
        else:
            print(f"  '{name}' → 无扩散（节点孤立）")

    # ==========================================
    # 测试 3: 层命中率
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 3: 三层命中率统计")
    print("=" * 60)

    all_queries = [
        "百年孤独", "名字", "云", "时间", "AI", "量子力学",
        "记忆", "推荐", "晚安", "天气", "小砂锅", "晚霞",
        "阅读", "测试", "零", "马尔克斯", "雨", "理想国",
        "打招呼", "问候"
    ]
    layer_hits = Counter()
    total_hits = 0

    for q in all_queries:
        result = engine.recall(q)
        for layer, count in result["by_layer"].items():
            if count > 0:
                layer_hits[layer] += 1
        if result["total"] > 0:
            total_hits += 1

    print(f"\n  查询总数: {len(all_queries)}")
    print(f"  有结果查询: {total_hits}/{len(all_queries)}")
    print(f"  知识网命中:  {layer_hits.get('knowledge', 0)}/{len(all_queries)}")
    print(f"  身份关系命中: {layer_hits.get('identity', 0)}/{len(all_queries)}")
    print(f"  时间链命中:  {layer_hits.get('timeline', 0)}/{len(all_queries)}")

    # ==========================================
    # 测试 4: 自然语言回忆
    # ==========================================
    print("\n" + "=" * 60)
    print("测试 4: 自然语言回忆")
    print("=" * 60)

    for query in ["百年孤独", "云", "小砂锅", "零", "时间", "晚安"]:
        result = engine.recall(query)
        print(f"\n{engine.format_recall(result)}")

    print(f"\n✅ M10 多天三层记忆图 - 测试完成")