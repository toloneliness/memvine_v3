import os
import json
import uuid
import time
import random
import requests
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

# ==========================================
# 配置文件 (请在这里填入你的 API 信息)
# ==========================================
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api-inference.modelscope.cn/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "你的API_KEY写在这里") # ⚠️ 请替换为你的真实 Key
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")

# ==========================================
# 第一部分：微观分子层 (Trace)
# ==========================================
@dataclass
class Trace:
    source_id: str
    target_id: str
    weight: float = 1.0
    emotion_snapshot: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_activated: float = field(default_factory=time.time)

# ==========================================
# 第二部分：介观拓扑层 (Topology)
# ==========================================
class Topology:
    def __init__(self):
        self.traces: Dict[str, Trace] = {}
        self.node_activation: Dict[str, float] = {}

    def get_trace_key(self, source_id: str, target_id: str) -> str:
        return f"{source_id}->{target_id}"

    def strengthen_or_create(self, source_id: str, target_id: str, snapshot: Dict[str, Any]):
        key = self.get_trace_key(source_id, target_id)
        if key in self.traces:
            self.traces[key].weight += 1.0
            self.traces[key].emotion_snapshot = snapshot
        else:
            self.traces[key] = Trace(source_id, target_id, 1.0, snapshot)
        self.traces[key].last_activated = time.time()

    def decay(self, rate=0.99):
        for trace in self.traces.values():
            trace.weight *= rate

    def activate_node(self, node_id: str, energy: float = 1.0):
        self.node_activation[node_id] = self.node_activation.get(node_id, 0) + energy

    def spread_activation(self, start_node: str, depth: int = 2):
        """扩散激活：模拟人类联想"""
        if start_node not in self.node_activation:
            return
        current_frontier = {start_node}
        for _ in range(depth):
            next_frontier = set()
            for node in current_frontier:
                for key, trace in self.traces.items():
                    if trace.source_id == node:
                        next_frontier.add(trace.target_id)
                        trace.weight += 0.2  # 联想到的记忆，权重微增
            current_frontier = next_frontier

# ==========================================
# 第三部分：宏观认知层 (Shell) - 提取与注入
# ==========================================
class Shell:
    def __init__(self):
        self.api_key = LLM_API_KEY
        self.base_url = LLM_BASE_URL
        self.model = LLM_MODEL

    def analyze_memory(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        【升级版】：支持多事件提取 + 动作本体归一化 + Few-Shot 引导
        """
        # 1. 定义有限的动作本体（Action Ontology）
        allowed_actions = [
            "告知", "询问", "表达情绪", "评价", "回忆", "转移",
            "拒绝", "请求", "命令", "观察", "思考", "其他"
        ]
        actions_str = ", ".join(allowed_actions)

        # 2. Few-Shot 示例（教 LLM 怎么拆分多事件和归一化动作）
        few_shot_examples = """
示例1:
记忆: "我早上错过了公交车，中午吃外卖吃坏了肚子，下午又被老板批评。"
输出: [
  {"agent": "用户", "action": "观察", "target": "错过公交车", "complexity": 0.2, "expressiveness": 0.9},
  {"agent": "用户", "action": "表达情绪", "target": "吃坏肚子", "complexity": 0.4, "expressiveness": 0.8},
  {"agent": "老板", "action": "评价", "target": "用户", "complexity": 0.6, "expressiveness": 0.7}
]

示例2:
记忆: "那个沉重的秘密压在心底，每次想起来都觉得窒息。"
输出: [
  {"agent": "用户", "action": "回忆", "target": "秘密", "complexity": 0.9, "expressiveness": 0.2}
]
"""

        prompt = f"""你是一个高级记忆解析器。请将人类记忆拆解为多个独立的JSON事件对象（数组格式）。
规则：
1. action 必须从以下标准标签中选择：[{actions_str}]。
2. 如果一句话包含多个独立事件，必须拆分成数组中的多个对象。
3. complexity(0.0-1.0，越复杂/不可说越高)，expressiveness(0.0-1.0，越容易表达越高)。

{few_shot_examples}

现在，请解析以下记忆（只返回JSON数组，不要任何废话）：
记忆: "{raw_text}"
JSON输出:"""

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2
                }
            )
            content = response.json()['choices'][0]['message']['content']
            json_str = content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(json_str)

            if isinstance(parsed, dict):
                return [parsed]
            return parsed
        except Exception as e:
            print(f"[LLM 警告] 解析失败: {e}")
            return [{"agent": "用户", "action": "其他", "target": raw_text, "complexity": 0.5, "expressiveness": 0.8}]

# ==========================================
# 第四部分：主控大脑 (Brain)
# ==========================================
class Brain:
    def __init__(self):
        self.topology = Topology()
        self.shell = Shell()

    def ingest(self, seed_id: str, target_id: str, complexity: float, expressiveness: float, emotion: Dict[str, Any]):
        snapshot = {
            **emotion,
            "complexity": complexity,
            "expressiveness": expressiveness,
            "timestamp": time.time()
        }
        self.topology.strengthen_or_create(seed_id, target_id, snapshot)

    def ingest_natural_language(self, raw_text: str):
        print(f"\n[LLM 解析中] 正在分析记忆: '{raw_text}'...")
        events = self.shell.analyze_memory(raw_text)
        print(f"[LLM 解析完成] 提取到 {len(events)} 个事件分子。")

        for parsed in events:
            if not isinstance(parsed, dict):
                continue

            agent = parsed.get("agent", "用户")
            target = parsed.get("target", raw_text)
            action = parsed.get("action", "其他")
            complexity = float(parsed.get("complexity", 0.5))
            expressiveness = float(parsed.get("expressiveness", 0.8))

            rich_snapshot = {
                "raw_text": raw_text,
                "agent": agent,
                "action": action,
                "target": target,
            }

            self.ingest(
                seed_id=agent,
                target_id=target,
                complexity=complexity,
                expressiveness=expressiveness,
                emotion=rich_snapshot
            )

        # 潜意识漫游 (保留原逻辑)
        if random.random() < 0.3:
            print("[潜意识] 正在漫游...")
            all_nodes = set([t.source_id for t in self.topology.traces.values()] +
                           [t.target_id for t in self.topology.traces.values()])
            if all_nodes:
                random_node = random.choice(list(all_nodes))
                self.topology.activate_node(random_node, 0.5)
                self.topology.spread_activation(random_node, 1)

    def decay(self):
        self.topology.decay(0.99)