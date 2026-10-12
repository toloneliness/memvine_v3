from typing import Dict, List, Type, Optional

from .base_task import BaseMaintenanceTask


class TaskRegistry:
    """任务注册表 - 支持动态注册"""

    def __init__(self):
        self._tasks: Dict[str, Type[BaseMaintenanceTask]] = {}

    def register(self, task_class: Type[BaseMaintenanceTask]) -> None:
        """注册一个任务类"""
        instance = task_class()
        self._tasks[instance.name] = task_class

    def get_by_layer(self, layer: int) -> List[BaseMaintenanceTask]:
        results = []
        for cls in self._tasks.values():
            instance = cls()
            if instance.layer == layer:
                results.append(instance)
        return results

    def get(self, name: str) -> Optional[Type[BaseMaintenanceTask]]:
        return self._tasks.get(name)

    def list_all(self) -> List[str]:
        return list(self._tasks.keys())