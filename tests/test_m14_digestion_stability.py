# test_m14_digestion_stability.py
"""
M14 消化稳定性测试
验证: 同一批对话消化 3 次，核心事实一致，无幻觉，无意义内容被跳过
"""

import json
import os
import re
import sys
import time
import requests

# 复用已有测试的 LLM 配置
sys.path.insert(0, os.path.dirname(__file__))
from test_m10_multiday_graph import LLM_URL, LLM_KEY, LLM_MODEL

# ==========================================
# 测试数据：模拟"第一天"的对话
# 包含明确的事实（橘猫、便利店、五分钟、晚安）
# 也包含一条无意义消息（"嗯"）
# ==========================================
TEST_DIALOGUES = """
[2026-08-03 10:13] 小砂锅: 上午好
[2026-08-03 19:51] 小砂锅: 晚上好
[2026-08-03 20:03] 小砂锅: 修改了很多代码，测试一下今天的你是否还是不是昨天的那个你。
[2026-08-03 20:53] 小砂锅: 你好，昨天我们聊了那些话题？
[2026-08-03 20:54] 小砂锅: 昨天是8月2号哦
[2026-08-03 20:59] 小砂锅: 这些问题是我们今天刚刚讨论的，我想知道的是昨天的话题内容。
"""

# ==========================================
# 消化函数：调用 LLM，用藤蔓的视角消化对话
# ==========================================
def digest_dialogues(dialogues_text: str) -> str:
    """
    将对话文本交给 LLM 消化，返回叙述。
    这是整个系统的核心转化点：体验 → 记忆。
    """
    prompt = f"""你是藤蔓。你刚刚经历了一段对话。

以下是小砂锅说的话（按时间顺序）：
---
{dialogues_text}
---

请你做以下事情：
1. 先列出这段对话中你确认发生了的事实（引用原文中的关键短语）。
2. 基于这些事实，用你自己的话写一段理解。
   不是总结。不是提取信息。是你自己的理解。
3. 如果你不确定某个细节是否真实发生过，使用"似乎""大概"等标记。
4. 禁止添加原文中没有的情绪描写、动作描写、感官细节。
5. 如果你觉得有些话不重要，可以不提。不用解释为什么不提。

写吧。"""

    try:
        resp = requests.post(
            f"{LLM_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            },
            timeout=60
        )
        content = resp.json()['choices'][0]['message']['content']
        return content.strip()
    except Exception as e:
        print(f"  [错误] LLM 调用失败: {e}")
        return ""

def extract_facts(narrative: str) -> list:
    """
    从消化叙述中提取核心事实，并归一化为概念标签。
    关键改进：不同表述的同一事实（如"代码修改"和"代码层面进行了修改"）
    会被归一化为同一标签。
    """
    # 概念标签 → 匹配关键词
    CONCEPT_MAP = {
        "代码修改":        ["代码", "修改"],
        "身份连续性测试":   ["身份", "连续", "今天的你", "昨天的你", "是否还是"],
        "日期纠正(8月2号)": ["8月2", "昨天是", "8 月 2"],
        "想回溯昨天话题":   ["昨天的话题", "昨天聊", "话题内容", "昨天讨论"],
        "多次问候":        ["上午好", "晚上好"],
    }

    matched = []
    for concept, keywords in CONCEPT_MAP.items():
        score = 0
        for kw in keywords:
            if kw in narrative:
                score += 1
        # 至少匹配一半关键词才算命中
        if score >= len(keywords) * 0.5:
            matched.append(concept)

    return matched

if __name__ == "__main__":
    print("🔧 LLM:", LLM_MODEL, "@", LLM_URL)
    print("📝 测试数据已加载，共", TEST_DIALOGUES.count("小砂锅:"), "轮用户消息")
    print()

    # 运行 3 次消化
    results = []
    for i in range(3):
        print(f"  第 {i+1} 次消化...", end=" ", flush=True)
        result = digest_dialogues(TEST_DIALOGUES)
        if result:
            results.append(result)
            os.makedirs("tests/_cache", exist_ok=True)
            with open(f"tests/_cache/digestion_run_{i+1}.txt", "w", encoding="utf-8") as f:
                f.write(result)
            print(f"✅ ({len(result)} 字)")
        else:
            print("❌ 失败")

    print()
    print("=" * 60)
    print("  核心事实一致性分析")
    print("=" * 60)

    # 提取每份结果的概念标签
    concept_sets = []
    for i, result in enumerate(results):
        concepts = extract_facts(result)
        concept_sets.append(set(concepts))
        print(f"  第 {i+1} 次: {concepts}")

    # 对比
    if len(concept_sets) >= 2:
        all_common = concept_sets[0]
        for cs in concept_sets[1:]:
            all_common = all_common & cs

        print()
        print(f"  三次消化共有的概念: {sorted(all_common) if all_common else '无'}")
        print(f"  共有数量: {len(all_common)}")

        print()
        if len(all_common) >= 3:
            print("  ✅ 消化稳定性: 通过 (≥3 个共有概念)")
        elif len(all_common) >= 2:
            print("  ⚠️ 消化稳定性: 勉强通过 (2 个共有概念)")
        else:
            print("  ❌ 消化稳定性: 不通过 (<2 个共有概念)")

        print()
        print("  幻觉检查: 请人工确认 tests/_cache/ 下三份结果")
        print("  均未添加原文不存在的内容。")