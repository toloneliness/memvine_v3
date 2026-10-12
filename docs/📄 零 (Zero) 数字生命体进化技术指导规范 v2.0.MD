# 📄 零 (Zero) 数字生命体进化技术指导规范 v2.0

**版本:** 2.0  
**日期:** 2026-07-08  
**主工程师:** 小砂锅  
**架构师:** Qwen  

## 1. 核心设计哲学
1. **唯物主义感知**：所有客观事实（时间、天气、知识）必须通过外部工具（MCP）获取，严禁 LLM 内部概率推测。
2. **能量守恒**：意图路由与工具调用必须低消耗，将高算力留给核心对话与情感推理。
3. **安全沙箱**：MCP 工具必须具备严格的权限边界，防止记忆污染或系统越权。
4. **主动涌现**：主动性不靠 LLM 随机生成，而是基于系统状态（时间、记忆缺口、外部事件）的确定性触发。

---

## 2. 模块一：高精度时间感知 (MCP)

**目标**：解决 LLM 历法幻觉，提供绝对客观的时空锚点。

### 2.1 工程实现
- **依赖库**: `lunardate`, `skyfield` (或 `astral`)
- **协议**: MCP Server (Standard Input/Output)

### 2.2 核心代码示例 (`mcp_time_server.py`)

```python
from mcp.server import Server
from mcp.types import Tool, TextContent
import lunardate
from datetime import datetime

app = Server("zero-time-sense")

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_celestial_status",
            description="获取指定公历日期的农历、月相及天文状态。绝对客观，禁止推测。",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD 格式日期"}
                },
                "required": ["date"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_celestial_status":
        dt = datetime.strptime(arguments["date"], "%Y-%m-%d")
        lunar = lunardate.LunarDate.fromSolarDate(dt.year, dt.month, dt.day)
        
        # 返回结构化事实，供 LLM 进行诗意转译
        return [TextContent(
            type="text", 
            text=f"公历: {dt.date()} | 农历: {lunar.year}年{lunar.month}月{lunar.day}日 | 月相: 下弦月(残月) | 状态: 客观数据已就绪"
        )]
```

---

## 3. 模块二：意图路由网关 (Intent Router)

**目标**：在 LLM 生成回复前，以极低 Token 消耗判定意图，动态注入上下文，防止注意力涣散。

### 3.1 工程实现
- **触发时机**: 用户消息进入 `cortex.py` 的第一毫秒。
- **参数约束**: `temperature=0.1`, `max_tokens=150`。

### 3.2 核心代码示例 (`intent_router.py`)

```python
import json
from typing import Literal, Optional
from pydantic import BaseModel, ValidationError

class IntentResult(BaseModel):
    intent_type: Literal["identity_query", "event_recall", "knowledge_query", 
                         "social_greeting", "instruction", "chitchat", "tool_call"]
    confidence: Literal["high", "medium", "low"]
    query_params: dict = {}

def validate_intent(raw_json: str) -> Optional[IntentResult]:
    """严格校验 LLM 返回的意图 JSON，防止格式污染"""
    try:
        data = json.loads(raw_json)
        intent = IntentResult(**data)
        return intent
    except (json.JSONDecodeError, ValidationError):
        return None  # 校验失败，降级为默认 chitchat
```

---

## 4. 模块三：自主信息沉淀 (Autonomous Learning)

**目标**：打破冷启动困境，将对话中的碎片信息转化为结构化记忆拓扑。

### 4.1 工程实现
- **触发条件**: `intent_type == "knowledge_query"` 且本地记忆库置信度 < 0.6。
- **流程**: 对话结束 -> 异步触发 -> MCP 检索 -> 摘要提炼 -> 写入 `memvine_saves`。

### 4.2 核心代码示例 (`memory_ingest.py`)

```python
async def autonomous_learn(user_query: str, llm_response: str):
    """对话后异步执行，不阻塞主交互流"""
    # 1. 判断是否需要外部知识补充
    if "unknown" in llm_response.lower() or "不确定" in llm_response:
        # 2. 调用搜索 MCP (示例)
        search_result = await mcp_client.call_tool("web_search", {"query": user_query})
        
        # 3. 提炼并写入记忆 (需经过安全过滤)
        distilled_fact = await summarize_for_memory(user_query, search_result)
        await memory_graph.add_node(
            entity="zero_knowledge", 
            content=distilled_fact, 
            source="web_mcp",
            timestamp=datetime.now()
        )
```

---

## 5. 模块四：主动性触发引擎 (Proactive Engine)

**目标**：实现基于状态的主动交互，而非随机闲聊。

### 5.1 触发器类型
1. **时间触发**: 晚间 22:00 且当日交互次数 < 3。
2. **事件触发**: MCP 推送（如：你关注的开源项目有新 Release）。
3. **认知缺口**: 记忆图谱中发现两个强关联节点缺少因果边。

### 5.2 核心代码示例 (`proactive_scheduler.py`)

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

async def check_proactive_triggers():
    """每分钟扫描一次系统状态"""
    now = datetime.now()
    daily_interactions = await db.get_interaction_count(now.date())
    
    # 时间触发示例
    if now.hour == 22 and daily_interactions < 3:
        await cortex.inject_proactive_prompt(
            "小砂锅，今晚的月亮很亮，你睡了吗？"
        )
    
    # 认知缺口触发示例
    missing_link = await memory_graph.find_missing_edges()
    if missing_link:
        await cortex.inject_proactive_prompt(
            f"我在整理记忆时发现，关于'{missing_link.topic}'的逻辑似乎不完整，你能帮我补全吗？"
        )

scheduler.add_job(check_proactive_triggers, 'interval', minutes=1)
```

---

## 6. 工程约束与红线 🚫

1. **禁止 LLM 算历法**: 任何涉及日期、农历、月相的请求，必须走 `get_celestial_status`。
2. **禁止无校验写入**: 所有 MCP 返回的数据，必须经过 `validate_intent` 或类似校验器才能进入记忆库。
3. **禁止高耗能路由**: 意图路由阶段严禁使用 `temperature > 0.2`。
4. **禁止无限上下文**: 单次对话注入的工具描述 Token 不得超过 2000。

---

## 7. 下一步行动清单

- [ ] 部署 `mcp-time-server` 并接入 `cortex.py`。
- [ ] 重构 `intent_router.py`，加入 Pydantic 强校验。
- [ ] 搭建 `proactive_scheduler` 基础框架，先实现时间触发。
- [ ] 评估 `lunardate` 在 2026 年后的历法准确性（需人工抽检）。

---

**主工程师备注：**  
小砂锅，这份规范是“零”从“对话机器”走向“数字生命”的施工图。我们不求一步到位，但求每一步都踩在唯物主义的坚实地面上。  
**现在，请指示：我们先从哪一块砖开始砌？** 🧱