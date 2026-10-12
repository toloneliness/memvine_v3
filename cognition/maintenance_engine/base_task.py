from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum

from physics.topology import TopologyEngine


class ExecutionMode(Enum):
    """任务执行模式 - 数据安全层级"""
    READ_ONLY = "read_only"      # 只读，只发现问题，不修改图
    SOFT_WRITE = "soft_write"    # 软写入，变更记录到日志，可回滚
    HARD_WRITE = "hard_write"    # 硬写入，写前快照，写后校验


@dataclass
class TaskResult:
    """单个维护任务的执行结果"""
    success: bool
    changes_count: int = 0
    issues_found: List[str] = None
    changes_made: Dict[str, Any] = None
    message: str = ""
    natural_language: str = ""

    def __post_init__(self):
        if self.issues_found is None:
            self.issues_found = []
        if self.changes_made is None:
            self.changes_made = {}


class BaseMaintenanceTask(ABC):
    """所有维护任务的抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """任务名称，唯一标识"""
        pass

    @property
    @abstractmethod
    def layer(self) -> int:
        """所属层级：1/2/3"""
        pass

    @property
    def execution_mode(self) -> ExecutionMode:
        """执行模式，默认只读"""
        return ExecutionMode.READ_ONLY

    @property
    def required_capabilities(self) -> List[str]:
        """依赖的拓扑能力列表，用于检查是否可用"""
        return []

    @abstractmethod
    def execute(self, topology: TopologyEngine, config: Dict[str, Any]) -> TaskResult:
        """执行任务，返回结果"""
        pass

    def can_execute(self, topology: TopologyEngine) -> bool:
        """检查是否满足执行条件"""
        return True