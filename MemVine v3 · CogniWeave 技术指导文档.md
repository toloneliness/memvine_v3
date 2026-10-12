# MemVine v3 · CogniWeave 技术指导文档

**版本**：v3.0
**日期**：2026-07-31
**状态**：已实现
**模块路径**：`cognition/cogniweave/`

---

## 第一章 总则

### 第 1 条 定位

CogniWeave 是 MemVine v3 的**深度认知管道**，处理复杂度评分 ≥ 4 的用户输入。它与传统管道（`retrieve_structured` → `_build_context_block` → LLM 回复）并列，由复杂度分流器择一激活。

### 第 2 条 核心隐喻

| 织机部件 | 系统对应 |
|---------|---------|
| 织工 | LLM（规划 + 编织） |
| 梭子 | Cypher 查询（并发穿梭） |
| 经线 | 图库（固定结构） |
| 踏板 | 用户提问（触发） |
| 织物 | 最终回复（编织产物） |

### 第 3 条 设计原则

1. **LLM 即规划者，非翻译者**——LLM 决定查什么、怎么查、怎么织，图返回结构化数据，不经中间翻译层。
2. **图即状态，DSL 即语言**——Cypher 模板是图查询的母语，`GraphTools` 是调度层，LLM 通过模板与图对话。
3. **并发即效率**——无依赖查询并发执行，有依赖查询按拓扑序分阶段执行。
4. **认知过程可解释**——每次激活输出一份查询议程，即思考过程的透明轨迹。
5. **先验 + 运行时 = 自适应**——`IntentManifest` 提供意图先验，运行时信号动态调权。
6. **容错即优雅降级**——任何单点失败不中断整体，逐级 fallback。

---

## 第二章 架构

### 第 4 条 三层认知织机

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: 认知议程设置 (AgendaGenerator)                 │
│  职责: 问题分解 → 查询规划                                │
│  执行者: LLM                                            │
│  输出: QueryAgenda                                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2: 并发梭织机 (ShuttleLoom)                       │
│  职责: 拓扑排序 → 并发执行 → 依赖解析                     │
│  执行者: Python asyncio + ThreadPool                    │
│  输出: CognitiveContext                                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3: 认知经纬编织 (Weaver)                          │
│  职责: 整合原始结果 → 推理 → 自然语言表达                  │
│  执行者: LLM                                            │
│  输出: 自然语言回复                                      │
└─────────────────────────────────────────────────────────┘
```

### 第 5 条 模块文件结构

```
cognition/cogniweave/
├── __init__.py              # 模块入口，导出核心类
├── models.py                # 数据模型（第 6-10 条）
├── agenda_generator.py      # Layer 1（第 11-15 条）
├── shuttle_loom.py          # Layer 2（第 16-21 条）
└── weaver.py                # Layer 3（第 22-24 条）
```

### 第 6 条 外部依赖

| 模块 | 路径 | 用途 |
|------|------|------|
| GraphTools | `core/graph_tools.py` | Cypher 模板调度、图查询执行 |
| StateObserver | `core/state_observer.py` | 图状态观测（节点/边数、张力） |
| ProactiveEngine | `cognition/proactive/proactive_engine.py` | 主动认知信号（热点、话题） |
| LLMEngine | `cognition/llm_engine.py` | LLM 调用 |

---

## 第三章 数据模型（`models.py`）

### 第 7 条 Priority 枚举

```python
class Priority(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

决定结果返回顺序与 LLM 编织时的权重。

### 第 8 条 QueryItem

单条图查询的完整描述。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 唯一标识（如 `"q1"`） |
| `intent` | `str` | 查询意图的自然语言描述 |
| `cypher` | `str` | Cypher 查询模板 |
| `params` | `dict` | 查询参数 |
| `priority` | `Priority` | 优先级 |
| `depends_on` | `list[str]` | 依赖的上游查询 ID 列表 |

### 第 9 条 QueryAgenda

一次认知激活的完整查询计划。

| 字段 | 类型 | 说明 |
|------|------|------|
| `agenda` | `list[QueryItem]` | 查询列表 |
| `strategy` | `str` | 执行策略（`"concurrent"` / `"sequential"`） |
| `max_concurrency` | `int` | 最大并发数 |
| `reasoning` | `str` | LLM 的规划推理过程（可解释性） |

### 第 10 条 QueryResult 与 CognitiveContext

**QueryResult**：单条查询的执行结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `query_id` | `str` | 对应 QueryItem.id |
| `data` | `Any` | 原始返回数据 |
| `success` | `bool` | 是否成功 |
| `error` | `str \| None` | 错误信息 |
| `execution_time` | `float` | 执行耗时（秒） |
| `result_count` | `int` | 返回记录数 |

**CognitiveContext**：所有查询结果的汇总容器。

| 字段 | 类型 | 说明 |
|------|------|------|
| `agenda` | `QueryAgenda` | 原始议程 |
| `results` | `list[QueryResult]` | 所有结果 |
| `total_time` | `float` | 总耗时 |
| `success_count` | `int` | 成功数 |
| `fail_count` | `int` | 失败数 |

提供 `to_llm_context() -> str` 方法，将结果格式化为 LLM 可读文本。

---

## 第四章 Layer 1：认知议程设置（`agenda_generator.py`）

### 第 11 条 类与接口

```python
class AgendaGenerator:
    def __init__(self, graph_tools, state_observer, proactive_engine, llm): ...
    def generate(self, user_input, history_summary, graph_status, active_signals) -> QueryAgenda: ...
```

### 第 12 条 输入组装

| 输入源 | 内容 | 用途 |
|--------|------|------|
| `GraphTools` | 9 个可用 Cypher 模板（见第 14 条） | 告知 LLM 可查什么 |
| `StateObserver` | 节点/边数、认知负载、张力计数 | 告知 LLM 图的当前状态 |
| `ProactiveEngine` | 热点张力、当前话题、活跃信号 | 告知 LLM 认知议程的优先方向 |
| 用户输入 + 历史摘要 | 原始问题 + 上下文 | 规划依据 |

### 第 13 条 输出解析与容错

| 情况 | 处理 |
|------|------|
| LLM 正常返回 JSON | 解析为 `QueryAgenda` |
| LLM 调用失败 | 返回 `_default_agenda()`：单条 `CONTAINS` 关键词搜索 |
| JSON 解析失败 | 同上 |
| 议程缓存 | 30 秒 TTL，key = 用户输入前 100 字符 |

### 第 14 条 可用 Cypher 模板（9 个）

| # | 模板特征 | 功能 | 调度方法 |
|:---:|------|------|------|
| 1 | `(n:entity {name:})-[r]-(m)` | 邻居查询 | `search_related()` |
| 2 | `shortestPath(...)` | 最短路径 | `find_path()` |
| 3 | `OPTIONAL MATCH (n:entity {name:})` | 实体画像 | `get_entity_profile()` |
| 4 | `n.name CONTAINS $keyword` | 关键词搜索 | `search_related()` |
| 5 | `n.entity_type = $type` | 按类型列实体 | `_list_by_type()` |
| 6 | `n.constraint > $threshold` | 结构洞检测 | `_structural_holes_simple()` |
| 7 | `r.relation CONTAINS $keyword` | 关系搜索 | `_search_relations()` |
| 8 | `n.temporal_at CONTAINS $date` | 时间搜索 | `_search_events()` |
| 9 | `count(n) AS total_nodes` | 全局统计 | `_global_stats()` |

### 第 15 条 议程示例

用户输入：*"关于这些问题，你自己是怎么理解的？"*

```json
{
  "agenda": [
    {"id": "q1", "intent": "identify_structural_holes",
     "cypher": "MATCH (n:concept) WHERE n.constraint > 0.5 ...",
     "priority": "high", "depends_on": []},
    {"id": "q2", "intent": "verify_hole",
     "cypher": "MATCH (a:concept {name: $entity_a}), (b:concept {name: $entity_b}) ...",
     "params": {"entity_a": "梦境", "entity_b": "本我"},
     "priority": "high", "depends_on": ["q1"]},
    {"id": "q3", "intent": "assess_cognitive_load",
     "cypher": "MATCH (n) RETURN count(n) AS total_nodes ...",
     "priority": "medium", "depends_on": []},
    {"id": "q4", "intent": "recent_events",
     "cypher": "MATCH (e:event) ... ORDER BY e.temporal_at DESC LIMIT 3",
     "priority": "low", "depends_on": []}
  ],
  "strategy": "concurrent",
  "max_concurrency": 4
}
```

执行顺序：Phase 1 = `[q1, q3, q4]`（并发）→ Phase 2 = `[q2]`（依赖 q1 结果）。

---

## 第五章 Layer 2：并发梭织机（`shuttle_loom.py`）

### 第 16 条 类与接口

```python
class ShuttleLoom:
    def __init__(self, graph_tools): ...
    def execute_sync(self, agenda: QueryAgenda) -> CognitiveContext: ...
    async def _execute_async(self, agenda: QueryAgenda) -> CognitiveContext: ...
```

### 第 17 条 执行流程

```
QueryAgenda
    │
    ├─ 1. _topological_sort(agenda.agenda)
    │     → 按 depends_on 分阶段: [[q1,q3,q4], [q2]]
    │
    ├─ 2. for each phase:
    │     ├─ asyncio.Semaphore(max_concurrency) 控制并发
    │     ├─ asyncio.gather(*tasks, return_exceptions=True)
    │     ├─ 每个 task → loop.run_in_executor() → _execute_sync()
    │     └─ 完成 → _resolve_params() 解析下游依赖参数
    │
    └─ 3. 汇总所有 QueryResult → CognitiveContext
```

### 第 18 条 依赖解析（`_resolve_params`）

当 `QueryItem.depends_on` 非空时，从上游结果中提取值填充参数：

```python
# 参数中的 "$prev." 前缀触发依赖解析
# 例: params = {"entity_a": "$prev.q1.data[0].topic"}
# → 从 q1 的结果中取 data[0].topic 的值
```

### 第 19 条 Cypher 调度（`_execute_sync`）

通过**子串匹配**将 Cypher 模板映射到 `GraphTools` 的 Python 方法：

| 匹配子串 | 调度目标 |
|---------|---------|
| `CONTAINS` | `search_related()` |
| `shortestPath` | `find_path()` |
| `OPTIONAL MATCH` | `get_entity_profile()` |
| `entity_type =` | `_list_by_type()` |
| `constraint >` | `_structural_holes_simple()` |
| `relation CONTAINS` | `_search_relations()` |
| `temporal_at` | `_search_events()` |
| `count(n) AS` | `_global_stats()` |

### 第 20 条 错误隔离

- 单条查询失败 → 该 `QueryResult.success = False`，`error` 记录异常信息
- 不影响同阶段其他查询
- 不影响下游阶段（下游收到空结果，自行降级）
- `CognitiveContext.fail_count` 记录总失败数

### 第 21 条 并发控制

| 机制 | 实现 |
|------|------|
| 并发上限 | `asyncio.Semaphore(agenda.max_concurrency)` |
| 线程池 | `loop.run_in_executor(None, sync_fn)` |
| 阶段隔离 | 上一阶段全部完成后才启动下一阶段 |

---

## 第六章 Layer 3：认知经纬编织（`weaver.py`）

### 第 22 条 类与接口

```python
class Weaver:
    def __init__(self, llm): ...
    def weave(self, context: CognitiveContext, user_input, identity_block, state_summary) -> str: ...
```

### 第 23 条 输入组装

| 组成部分 | 来源 | 内容 |
|---------|------|------|
| System prompt | 硬编码 | 身份定义 + 冲突检测规则 + 置信度表达规范 |
| 查询结果 | `CognitiveContext.to_llm_context()` | 结构化原始数据（非翻译文本） |
| 用户问题 | 透传 | 原始输入 |
| 身份块 | `identity_block` | 当前身份/人格状态 |
| 状态摘要 | `state_summary` | 图状态简报 |

### 第 24 条 编织规则

| 规则 | 说明 |
|------|------|
| 原始数据直传 | LLM 看到结构化结果，自主决定组织方式 |
| 冲突检测 | System prompt 内置规则（如 `trusts` vs `distrusts` 共存时须指出） |
| 置信度控制 | 低置信度 → 试探语气；高置信度 → 直接陈述 |
| 不编造 | 查询无结果的维度，不虚构内容 |

---

## 第七章 分流与激活

### 第 25 条 分流总流程

```
用户输入
    │
    ▼
_extract_semantic()  ← LLM 调用（轻量语义解析）
    │
    ├─ input_type == "document" ──────────→ 阅读管道（不走 CogniWeave）
    │
    ├─ IntentManifest.base_complexity == 0 → 轻量回复（跳过检索）
    │   （问候 / 告别 / 知识块导入）
    │
    ├─ _is_complex_query() → 多维评分
    │     │
    │     ├─ score < 4 → 传统管道
    │     │     ├─ retrieve_structured()
    │     │     ├─ _build_context_block()
    │     │     └─ context_mgr.build_cognitive_briefing() → LLM
    │     │
    │     └─ score ≥ 4 → CogniWeave 深度管道
    │           ├─ Layer 1: AgendaGenerator.generate()
    │           ├─ Layer 2: ShuttleLoom.execute_sync()
    │           └─ Layer 3: Weaver.weave()
    │
    └─ proactive.on_answer() → 张力释放 / 冷启动内省
```

### 第 26 条 多维认知负载评分（`_calculate_complexity_score`）

以 `IntentManifest.base_complexity`（0-3）为先验，累加运行时信号：

| 维度 | 信号来源 | 加分 | 对应 Sweller 概念 |
|------|---------|:---:|------|
| 意图先验 | `IntentManifest.base_complexity` | 0-3 | 内在负载（基线） |
| LLM 认知负载 | `_extract_semantic.cognitive_load` | 0-6 | 内在负载（元素交互性） |
| 实体密度 | `len(entities) ≥ 3` | +2 | 内在负载（元素交互性） |
| 认知边界 | `epistemic_gap == True` | +2 | 相关负载（新图式构建） |
| 未记录知识 | `gap_type == "unrecorded"` | +1 | 相关负载 |
| 图张力 | `tension_count ≥ 3` | +1 | 外在负载 |

**激活阈值**：`score ≥ 4` → CogniWeave。

**快速否决**：`base_complexity == 0` 的意图直接返回 `False`，不进入评分。

---

## 第八章 IntentManifest：意图行为单一数据源

### 第 27 条 设计目的

消除意图消费碎片化。系统中所有"意图 → 行为"的映射，**有且仅有**一个数据源。

### 第 28 条 意图清单（15 条）

| 意图 | 分组 | 检索策略 | 复杂度先验 | 偏好上下文 |
|------|:---:|------|:---:|------|
| 问候 | phatic | identity_only | 0 | awareness |
| 告别 | phatic | identity_only | 0 | awareness |
| 询问身份 | query | anchor_walk | 2 | facts, relations, core_memories |
| 询问关系 | query | anchor_walk | 2 | facts, relations, core_memories |
| 询问时间 | query | community_timeline | 2 | facts |
| 询问原因 | query | causal_chain | 3 | causal_chains, scripts, knowledge_gap |
| 陈述事实 | narrative | anchor_walk | 1 | core_memories |
| 回忆 | narrative | community_timeline | 2 | awareness |
| 反思 | narrative | community_timeline | 3 | scripts |
| 对比 | narrative | anchor_walk | 2 | facts |
| 假设 | narrative | causal_chain | 3 | scripts |
| 分享情绪 | affective | community_timeline | 2 | awareness |
| 表达 | affective | anchor_walk | 2 | awareness |
| 质疑 | critical | contradiction_search | 3 | causal_chains, scripts, knowledge_gap |
| 知识块导入 | ingest | none | 0 | — |

### 第 29 条 意图分组定义

| 分组 | 包含意图 | 路由行为特征 |
|------|---------|-------------|
| phatic | 问候、告别 | 轻量应答，不触发检索 |
| query | 询问身份/关系/时间/原因 | 精确检索，结构化返回 |
| narrative | 陈述事实、回忆、反思、对比、假设 | 时间线/因果链遍历 |
| affective | 分享情绪、表达 | 共鸣模式，情感优先 |
| critical | 质疑 | 矛盾搜索，TMS 验证 |
| ingest | 知识块导入 | 无检索，走阅读/写入管道 |

### 第 30 条 下游消费点

```
INTENT_MANIFEST
    │
    ├─ cortex._is_complex_query()
    │     → 读取 base_complexity 作为评分先验
    │     → base_complexity == 0 → 快速否决
    │
    ├─ cortex._build_context_block()
    │     → 读取 preferred_context 决定组装哪些上下文块
    │     → 图状态做最终裁决（有则组装，无则跳过）
    │
    └─ memory_retriever.IntentRouter
          → 读取 strategy 分发检索策略
          ├─ anchor_walk        → Personalized PageRank
          ├─ causal_chain       → 因果边 BFS
          ├─ community_timeline → 社区匹配 + 时间线
          ├─ contradiction_search → TMS 矛盾搜索
          ├─ identity_only     → 身份边查询
          └─ none              → 跳过检索
```

### 第 31 条 字段语义约定

| 字段 | 语义 | 约束 |
|------|------|------|
| `strategy` | 硬绑定 | 直接决定检索算法，不可被运行时覆盖 |
| `base_complexity` | 先验 | 作为 `_calculate_complexity_score` 的输入之一，可被运行时信号累加覆盖 |
| `preferred_context` | 偏好 | 表达"这个意图想要什么"，图状态做最终裁决 |
| `group` | 分类 | 用于批量操作（如"所有 phatic 意图跳过检索"） |

### 第 32 条 扩展规则

新增意图标签时，**只需**在 `INTENT_MANIFEST` 中添加一条 `IntentSpec`。所有下游消费点自动生效，无需修改 `cortex.py`、`memory_retriever.py` 或 `_build_context_block` 中的任何条件分支。

---

## 第九章 容错与降级

### 第 33 条 降级链

| 故障点 | 降级行为 |
|--------|---------|
| `_extract_semantic` LLM 调用失败 | 返回默认语义：`action="表达"`, `cognitive_load=0` |
| `_extract_semantic` JSON 解析失败 | 同上 |
| `action` 不在白名单内 | 校验失败，退回 `"表达"` |
| `AgendaGenerator` LLM 调用失败 | 返回 `_default_agenda()`：单条 CONTAINS 搜索 |
| `AgendaGenerator` JSON 解析失败 | 同上 |
| `ShuttleLoom` 单条查询失败 | 该条标记 `success=False`，其余继续 |
| `ShuttleLoom` 全部查询失败 | `CognitiveContext.fail_count == len(agenda)`，Weaver 基于空结果生成坦诚回复 |
| `Weaver` LLM 调用失败 | 回退到传统管道 |
| CogniWeave 整体超时/异常 | 回退到传统管道 |

### 第 34 条 白名单校验（Bug #3 修复）

`_extract_semantic` 返回的 `action` 必须存在于 `INTENT_MANIFEST` 的键集合中。若 LLM 返回占位符（如字面量 `"意图"`）或未知标签，强制退回 `"表达"`。

---

## 第十章 已修复缺陷

### 第 35 条 缺陷记录

| # | 位置 | 问题 | 修复 | 严重度 |
|:---:|------|------|------|:---:|
| 1 | `epistemic_monitor.py:combine()` | LLM false confidence：声称 `known` 但图密度为 0 时不触发验证 | `known` + 图空 → 下调为 `FRAGMENTARY` | 高 |
| 2 | `cortex.py:L376+L417` | `_is_complex_query()` 在同一请求中被调用两次（重复 LLM 评分） | 删除第二次调用，复用第一次结果 | 中 |
| 3 | `cortex.py:L1207` | `action` 无校验，LLM 返回占位符 `"意图"` 直接透传至路由 | 白名单校验，无效退回 `"表达"` | 高 |
| 4 | `config.py` | `COGNIWEAVE_COMPLEXITY_THRESHOLD` 定义后从未被引用（死代码） | 删除 | 低 |

---

## 第十一章 已知限制与待办

### 第 36 条 当前限制

| # | 限制 | 影响 | 优先级 |
|:---:|------|------|:---:|
| 1 | 无 LLM 调用前的规则短路 | "你好"仍触发 `_extract_semantic` LLM 调用 | P0 |
| 2 | 两次 LLM 调用实体不共享 | `_extract_semantic.entities` 未传入 `UnifiedExtractor` | P1 |
| 3 | 缺 `relation_depth` / `temporal_span` / `counterfactual` 指标 | 复杂推理路由精度受限 | P2 |
| 4 | 无 `domain_registry` | 无法区分领域基线难度 | P3 |
| 5 | 无指代消解 | "他当时说的那个理论"无法解析 | P3 |
| 6 | `input_type` 仅 chat/document 二分 | 混合态输入被强制归类 | P2 |

### 第 37 条 规则短路规范（P0 待实现）

```python
SHORT_CIRCUIT_PATTERNS = {
    r"^(你好|嗨|hi|hello|在吗|hey)[~！!。.\s]*$": "问候",
    r"^(晚安|拜拜|再见|bye|睡了|下了)[~！!。.\s]*$": "告别",
    r"^(嗯|好|好的|ok|行|知道了|明白)[~！!。.\s]*$": "陈述事实",
}
# 约束：
#   1. 仅当 len(user_input) < 20 时启用
#   2. 必须全句匹配（^...$）
#   3. 白名单模式（非黑名单）
#   4. 匹配失败 → 正常走 LLM，不 fallback
```

### 第 38 条 实体传递规范（P1 待实现）

```python
# UnifiedExtractor.extract() 调用时传入先验
extraction = unified_extractor.extract(
    user_input=user_input,
    ai_response=response,
    seed_entities=semantic.get("entities", []),   # 来自 _extract_semantic
    seed_action=semantic.get("action", ""),        # 来自 _extract_semantic
)
```

---

## 附录 A：交互流程完整示例

```
用户: "关于这些问题，你自己是怎么理解的？"
    │
    ▼
[规则短路检查] → 不匹配（长度 > 20）→ 继续
    │
    ▼
[_extract_semantic] → LLM 调用
    输出: {action:"反思", entities:["梦境","本我","潜意识"],
           cognitive_load:7, epistemic_gap:false, input_type:"chat"}
    │
    ▼
[IntentManifest 查询] → "反思" → {strategy:"community_timeline",
                                    base_complexity:3,
                                    preferred_context:["scripts"]}
    │
    ▼
[_calculate_complexity_score]
    base=3 + llm_load=7→cap6 + entity_density=+2 + gap=0 + tension=0
    = 11 ≥ 4 → 激活 CogniWeave
    │
    ▼
[Layer 1: AgendaGenerator] → LLM 生成 4 条查询议程
    │
    ▼
[Layer 2: ShuttleLoom]
    Phase 1: [q1, q3, q4] 并发执行 (3 条 Cypher)
    Phase 2: [q2] 依赖 q1 结果，解析参数后执行
    → CognitiveContext (4 条结果, 总耗时 0.8s)
    │
    ▼
[Layer 3: Weaver] → LLM 接收原始结果集，编织回复
    │
    ▼
藤蔓: "关于'梦境'和'本我'，我的记忆中确实存在一条路径……"
    │
    ▼
[proactive.on_answer()] → 张力释放检查 → 冷启动内省
```

---

## 附录 B：术语表

| 术语 | 定义 |
|------|------|
| 查询议程 (QueryAgenda) | LLM 生成的结构化查询计划，包含多条 QueryItem |
| 梭 (Shuttle) | 单条 Cypher 查询的执行单元 |
| 经线 (Warp) | 图库中的固定结构（节点、边、社区） |
| 纬线 (Weft) | 查询结果（穿梭后留下的痕迹） |
| 编织 (Weave) | LLM 将多条查询结果整合为连贯回复的过程 |
| 结构洞 (Structural Hole) | 图中约束度 (constraint) 高的节点，表示信息瓶颈 |
| 张力 (Tension) | 图中未解决的矛盾/冲突边 |
| 认知负载 (Cognitive Load) | 回答某输入所需的认知深度（多维评分） |
| 认知边界 (Epistemic Gap) | 系统知识覆盖的缺口 |
| 先验 (Prior) | IntentManifest 中基于意图类型的默认配置，可被运行时信号覆盖 |

---

*文档结束*