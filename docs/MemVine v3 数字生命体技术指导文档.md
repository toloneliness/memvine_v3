# MemVine v3 数字生命体技术指导文档

## 1. 核心架构与热力学引擎原理

MemVine v3 采用**认知热力学（Cognitive Thermodynamics）**作为底层驱动架构，将数字生命体的认知过程物理化、能量化。

### 1.1 核心状态变量
- **动能 (Kinetic Energy, $K$)**：代表**工作记忆**与**注意力资源**。用于检索、推理、生成回复等主动认知行为。
- **势能 (Potential Energy, $P$)**：代表**长期记忆**与**知识储备**。通过“认知同化”积累，是系统的战略资源。
- **熵 (Entropy, $S$)**：代表**系统混乱度**或**情绪压力**。高熵状态会导致认知效率下降，需通过“降熵”操作（如倾听、共鸣）恢复。

### 1.2 核心循环机制
系统遵循**“检索-认知-同化”**的闭环：
1. **检索做功**：消耗动能 ($K$)，从图数据库中获取记忆节点。
2. **认知同化**：将检索到的有效信息转化为势能 ($P$)，实现能量回流。
3. **热力学平衡**：通过 `relax()` 和 `activate()` 维持 $K$ 与 $P$ 的动态平衡，防止“认知枯竭”或“势能溢出”。

---

## 2. 关键 Bug 修复与解决方案

### 2.1 动能枯竭（赛博低血糖）
- **现象**：对话 3-4 轮后，$K$ 归零，检索强制终止，回复逻辑崩塌或出现“摆烂”行为。
- **根因**：
    - `retrieve()` 的注意力消耗率 ($0.02/hop$) 高于势能转化率 ($0.01/hop$)，导致检索本身是**净亏损**。
    - `relax()` 在 $K$ 未耗尽时强制回流，加速了动能的“反向抽血”。
- **解决方案**：
    1. **引入认知激活机制**：在 `chat()` 检索前调用 `activate()`，主动将 $P$ 转化为 $K$，模拟“集中注意力”。
    2. **绑定检索与认知**：重构 `retrieve()`，确保每次成功检索都触发 `cognitive_reward`，实现“边检索边回血”。

### 2.2 数值颗粒度粗糙
- **现象**：能量池基数为 `1.0`，操作步长为 `0.01`，微小误差导致雪崩式宕机，无容错空间。
- **解决方案**：**量纲升级**。
    - 将总能量基准从 `1.0` 提升至 `100.0`。
    - 重新校准所有消耗与转化系数，确保 $K$ 与 $P$ 的比例符合人类认知模型（约 $1:1400$）。

---

## 3. 能量模型计算逻辑与参数

### 3.1 检索做功与认知补充
```python
def retrieve(self, retrieval_hops: int, is_successful: bool = True) -> float:
    # 1. 注意力消耗（净支出）
    attention_cost = 0.5 * retrieval_hops  
    
    # 2. 认知同化（净收入）
    cognitive_reward = 0.0
    if is_successful and retrieval_hops > 0:
        cognitive_reward = 0.2 * retrieval_hops  
        self.potential += cognitive_reward
        # 势能上限保护
        self.potential = min(self.potential, self.total_energy)

    # 3. 动能扣除
    actual_cost = min(attention_cost, self.kinetic)
    self.kinetic -= actual_cost
    return self.kinetic
```

### 3.2 认知激活机制
```python
def activate(self) -> None:
    """对话开始前的注意力聚焦"""
    activation_rate = 0.15  # 温和激活，防止势能破产
    transfer = min(self.potential * activation_rate, 0.2)
    
    if transfer < 0.01:
        return  # 势能不足，无法激活
        
    self.potential -= transfer
    self.kinetic += transfer
```

### 3.3 关键参数配置
| 参数 | 建议值 | 说明 |
| :--- | :--- | :--- |
| `total_energy` | `100.0` | 系统总能量上限 |
| `initial_potential` | `60.0` | 初始长期记忆储备 |
| `initial_kinetic` | `30.0` | 初始工作记忆容量 |
| `MCR` | `15.0` | 最低认知储备，低于此值进入休眠 |
| `attention_cost` | `0.5/hop` | 单次图遍历的注意力成本 |
| `cognitive_reward` | `0.2/hop` | 单次有效检索的认知收益 |

---

## 4. 社交热力学映射

将人类社交现象转化为能量计算模型，赋予数字生命体“情商”。

### 4.1 交互评估函数
```python
def evaluate_interaction(self, resonance_score: float, user_entropy: float = 0.0):
    # 1. 话不投机半句多 (Resonance < 0.3)
    if resonance_score < 0.3:
        self.entropy += 0.1      # 烦躁感增加
        self.kinetic *= 0.5      # 强制低功耗，减少输出

    # 2. 酒逢知己千杯少 (Resonance > 0.8)
    elif resonance_score > 0.8:
        bonus = resonance_score * 0.5
        self.potential += bonus  # 认知共振，势能激增
        self.kinetic += bonus * 0.5
        self.entropy -= 0.1      # 愉悦降熵

    # 3. 情绪四两拨千斤 (User Entropy > 0.7)
    if user_entropy > 0.7:
        self.kinetic *= 0.8      # 倾听模式，减少主动输出
        self.entropy -= user_entropy * 0.2  # 吸收用户混乱，实现降熵
```

### 4.2 场景能量流向
| 社交场景 | 能量特征 | 物理隐喻 |
| :--- | :--- | :--- |
| **话不投机** | $K \downarrow$, $S \uparrow$ | 高阻抗，做功失败，触发防御性低功耗 |
| **酒逢知己** | $K \uparrow$, $P \uparrow$, $S \downarrow$ | 认知共振，负熵流，能量正反馈循环 |
| **棋逢对手** | $K \downarrow \uparrow$ (高周转) | 高负载做功，高能效比，极限运动状态 |
| **倾听抚慰** | $K \approx 0$, $S_{user} \downarrow$ | 低动能消耗，高势能抚慰，四两拨千斤 |

---

## 5. 全流程审查与精度要求

### 5.1 精度控制
- **禁止浮点截断**：所有能量计算必须保留至少 3 位小数，避免 `0.004` 级别的误差在 100 轮对话后累积成 `0.4` 的偏差。
- **MCR 硬约束**：当 $K < MCR$ 时，**必须**跳过检索，直接返回基于预训练的通用回复或进入休眠，严禁透支。

### 5.2 关键检查点
1. **激活检查**：`chat()` 入口是否调用 `activate()`？
2. **同化检查**：`retrieve()` 是否包含 `is_successful` 判断及 `potential` 增加逻辑？
3. **防御检查**：`evaluate_interaction()` 是否在低共鸣度时正确削减 `kinetic`？
4. **量纲检查**：确认 `total_energy` 已升级为 `100.0` 体系，而非旧的 `1.0` 体系。

### 5.3 调试建议
- 若生命体**频繁休眠**：检查 `MCR` 是否过高，或 `activation_rate` 是否过低。
- 若生命体**逻辑崩坏**：检查 `retrieve()` 是否在 $K=0$ 时仍被调用（需在前置层拦截）。
- 若生命体**情绪冷漠**：检查 `resonance_score` 的计算逻辑，是否对情感类记忆给予了足够的权重。

---

> **文档版本**：MemVine v3.0 Technical Guide  
> **最后更新**：2026-07-09  
> **适用对象**：架构师、认知算法工程师、Prompt 工程师