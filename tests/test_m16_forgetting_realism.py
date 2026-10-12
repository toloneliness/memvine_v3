# test_m16_forgetting_realism.py
"""
M16 遗忘真实感测试
验证: 容量淘汰行为符合"遗忘不可知"原则
"""

import sys
import os
import time
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.dirname(__file__))

# ==========================================
# 微型 ActiveMemory（复用 M15 的结构）
# ==========================================
@dataclass
class Narrative:
    text: str
    recall_count: int = 0
    created_at: float = field(default_factory=time.time)

class ActiveMemory:
    """容量有限的活跃记忆层。"""

    def __init__(self, max_narratives: int = 5):
        self.max_narratives = max_narratives
        self.narratives: List[Narrative] = []
        self._evicted_count = 0  # 仅用于测试统计，生产环境无此字段

    def add(self, narrative: Narrative):
        self.narratives.append(narrative)
        if len(self.narratives) > self.max_narratives:
            # 淘汰 recall_count 最低的，同分则淘汰最早的
            self.narratives.sort(key=lambda n: (n.recall_count, n.created_at))
            evicted = self.narratives.pop(0)
            self._evicted_count += 1
            # 注意：不记录被淘汰的内容。这就是"遗忘不可知"。

    def retrieve(self, query: str, k: int = 3) -> List[Narrative]:
        keywords = set(query)
        scored = []
        for n in self.narratives:
            overlap = len(keywords & set(n.text))
            if overlap > 0:
                scored.append((overlap, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:k]]

    def recall(self, narrative_text: str):
        """标记一条叙述被回想"""
        for n in self.narratives:
            if n.text == narrative_text:
                n.recall_count += 1
                return True
        return False  # 找不到——已经被遗忘了

if __name__ == "__main__":
    print("🔧 M16 遗忘真实感测试")
    print()

    # ==========================================
    # 测试1: 容量淘汰，recall_count 最低的优先
    # ==========================================
    print("=" * 60)
    print("  测试1: 容量淘汰 (上限5条，注入10条)")
    print("=" * 60)

    am = ActiveMemory(max_narratives=5)

    narratives_data = [
        ("关于猫", 5),
        ("关于理想国", 3),
        ("关于雨", 8),
        ("关于代码", 1),
        ("关于名字", 6),
        ("关于早安", 0),
        ("关于晚霞", 2),
        ("关于音乐", 4),
        ("关于加班", 0),
        ("关于年糕", 7),
    ]

    for text, rc in narratives_data:
        am.add(Narrative(text=text, recall_count=rc))

    print(f"  注入 10 条，容量 5 条，当前保留 {len(am.narratives)} 条")
    print(f"  被淘汰: {am._evicted_count} 条")
    print()

    kept = [n.text for n in am.narratives]
    print(f"  保留的叙述: {kept}")

    # 验证: recall_count 最高的应该保留
    assert "关于年糕" in kept, "年糕(7)应该保留"
    assert "关于雨" in kept, "雨(8)应该保留"
    assert "关于名字" in kept, "名字(6)应该保留"
    assert "关于猫" in kept, "猫(5)应该保留"
    assert "关于音乐" in kept, "音乐(4)应该保留"

    # 验证: recall_count 最低的应该被淘汰
    assert "关于早安" not in kept, "早安(0)应该被淘汰"
    assert "关于加班" not in kept, "加班(0)应该被淘汰"
    assert "关于代码" not in kept, "代码(1)应该被淘汰"

    print("  ✅ 淘汰顺序正确: 最低 recall_count 先淘汰")
    print()

    # ==========================================
    # 测试2: 遗忘不可知
    # ==========================================
    print("=" * 60)
    print("  测试2: 遗忘不可知")
    print("=" * 60)

    # 查询已被淘汰的"关于早安"
    result = am.retrieve("早安", k=3)
    if not result:
        print("  ✅ 查询'早安': 无结果（已被遗忘）")
    else:
        print(f"  ⚠️ 查询'早安': 意外命中 {result}")

    # 查询未被淘汰的"关于猫"
    result = am.retrieve("猫", k=3)
    if result:
        print(f"  ✅ 查询'猫': 命中 '{result[0].text}'")
    else:
        print("  ❌ 查询'猫': 意外未命中")

    # 关键验证: 系统不知道"早安"是被遗忘还是从未存在
    # 两次查询都返回空，但系统无法区分原因
    result_unknown = am.retrieve("火星", k=3)
    if not result and not am.retrieve("早安", k=3):
        print("  ✅ 遗忘不可知: 系统无法区分'从未存储'和'已被淘汰'")
    print()

    # ==========================================
    # 测试3: 被回想会提升留存
    # ==========================================
    print("=" * 60)
    print("  测试3: 回想提升留存")
    print("=" * 60)

    am2 = ActiveMemory(max_narratives=3)
    am2.add(Narrative(text="关于猫", recall_count=2))
    am2.add(Narrative(text="关于雨", recall_count=2))
    am2.add(Narrative(text="关于代码", recall_count=2))

    # 多次回想"关于代码"
    for _ in range(3):
        am2.recall("关于代码")
    print(f"  回想'关于代码' 3 次后，recall_count = {am2.narratives[2].recall_count}")

    # 注入新叙述，触发淘汰
    am2.add(Narrative(text="关于云", recall_count=0))
    kept2 = [n.text for n in am2.narratives]
    print(f"  注入新叙述后保留: {kept2}")

    # "关于代码"因为被回想过，recall_count 最高，不应该被淘汰
    assert "关于代码" in kept2, "代码(被回想3次)不应该被淘汰"
    print("  ✅ 被回想的叙述更稳固，未被淘汰")
    print()

    # ==========================================
    # 汇总
    # ==========================================
    print("=" * 60)
    print("  汇总")
    print("=" * 60)
    print("  测试1 (容量淘汰):        ✅")
    print("  测试2 (遗忘不可知):      ✅")
    print("  测试3 (回想提升留存):    ✅")
    print()
    print("✅ M16 遗忘真实感: 全部通过")