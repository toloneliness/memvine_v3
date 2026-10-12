"""
自主维护引擎 (Autonomous Maintenance Engine)
三层循环结构：
  Layer 1: 快速健康检查 - 每次苏醒执行
  Layer 2: 轻度整理 - 空闲时每天1-2次
  Layer 3: 深度反思 - 休眠时每周1-2次
"""

from .scheduler import MaintenanceScheduler
from .task_registry import TaskRegistry
from .base_task import BaseMaintenanceTask, TaskResult, ExecutionMode

__all__ = [
    "MaintenanceScheduler",
    "TaskRegistry",
    "BaseMaintenanceTask",
    "TaskResult",
    "ExecutionMode",
]