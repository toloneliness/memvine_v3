# MemVine v3

> 数字生命记忆系统 — CogniWeave 架构

## 项目简介

MemVine v3 是一个基于图神经网络和 LLM 的数字生命体记忆系统，采用三层记忆架构：

- **微观层（Trace）**：记忆痕迹与联想激活
- **介观层（Topology）**：图拓扑结构维护
- **宏观层（Shell）**：LLM 驱动的认知提取与注入

## 环境要求

- Python >= 3.11
- 依赖管理：[uv](https://github.com/astral-sh/uv) 或 pip

## 快速开始

```bash
# 安装依赖
pip install -e .

# 或使用 uv
uv sync

# 启动对话模式
python chat.py

# 启动 OpenAI 兼容 API 服务
python openai_server.py
```

## 项目结构

```
memvine_v3/
├── core/              # 核心模块（记忆皮层、持久化、用户管理等）
├── cognition/         # 认知模块（消化、演化、向量存储、CogniWeave 等）
│   ├── cogniweave/    # CogniWeave 编织引擎
│   ├── maintenance_engine/  # 图自主维护引擎
│   └── proactive/     # 主动推理模块
├── physics/           # 物理模拟层（拓扑、热力学）
├── tests/             # 测试用例
├── docs/              # 技术文档
├── chat.py            # 对话入口
├── openai_server.py   # OpenAI API 兼容服务
├── brain.py           # 大脑核心入口
└── prompts.py         # Prompt 模板
```

## 许可证

内部项目