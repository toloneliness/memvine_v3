from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import threading
import time
from contextlib import contextmanager

from physics.topology import TopologyEngine
from core.clock import SystemClock
from cognition.llm_engine import LLMEngine


from .base_task import BaseMaintenanceTask, TaskResult, ExecutionMode
from .task_registry import TaskRegistry
from .maintenance_report import MaintenanceReport, MaintenanceReportSerializer, Issue, Change


@dataclass
class MaintenanceSchedule:
    """维护计划记录 - 记录各层级上次执行时间"""
    last_layer1: Optional[datetime] = None
    last_layer2: Optional[datetime] = None
    last_layer3: Optional[datetime] = None
    pending_issues: List[Issue] = None

    def __post_init__(self):
        if self.pending_issues is None:
            self.pending_issues = []


@dataclass
class SystemState:
    """系统当前状态 - 用于决定执行哪一层"""
    is_sleeping: bool = False
    sleep_duration: Optional[timedelta] = None
    idle_duration: timedelta = timedelta(0)


class MaintenanceScheduler:
    """自主维护调度器 - 三层循环调度"""

    def __init__(
        self,
        registry: TaskRegistry,
        topology: TopologyEngine,
        clock: SystemClock,
        llm: LLMEngine,
        config: Optional[Dict] = None,
        proactive=None,  # 新增：ProactiveEngine 引用
    ):
        self.registry = registry
        self.topology = topology
        self.clock = clock
        self.llm = llm
        self.proactive = proactive  # 新增
        self.schedule = MaintenanceSchedule()
        self.config = config or self._default_config()

        self._maintenance_lock = threading.Lock()
        self._is_running = False
        self._interrupt_requested = False

        self.serializer = MaintenanceReportSerializer()

    def _default_config(self) -> Dict:
        from config import (
            MAINTENANCE_LAYER1_INTERVAL_MINUTES,
            MAINTENANCE_LAYER2_INTERVAL_HOURS,
            MAINTENANCE_LAYER3_INTERVAL_DAYS,
            MAINTENANCE_LAYER2_BUDGET,
            MAINTENANCE_SLEEP_THRESHOLD_HOURS,
            MAINTENANCE_IDLE_THRESHOLD_MINUTES,
            MAINTENANCE_ENABLE_LLM_REWRITE,
        )
        return {
            'layer1_interval_minutes': MAINTENANCE_LAYER1_INTERVAL_MINUTES,
            'layer2_interval_hours': MAINTENANCE_LAYER2_INTERVAL_HOURS,
            'layer3_interval_days': MAINTENANCE_LAYER3_INTERVAL_DAYS,
            'layer2_budget': MAINTENANCE_LAYER2_BUDGET,
            'sleep_threshold_hours': MAINTENANCE_SLEEP_THRESHOLD_HOURS,
            'idle_threshold_minutes': MAINTENANCE_IDLE_THRESHOLD_MINUTES,
            'enable_llm_rewrite': MAINTENANCE_ENABLE_LLM_REWRITE,
        }

    def determine_layer(self, state: SystemState) -> int:
        """根据系统状态和上次执行时间，决定本次执行哪一层"""
        now = self.clock.now_local()

        # 如果长时间休眠，直接执行第三层（包含一、二层）
        if (state.is_sleeping and
            state.sleep_duration and
            state.sleep_duration > timedelta(hours=self.config['sleep_threshold_hours'])):
            return 3

        # 检查是否需要执行第二层
        if not self.schedule.last_layer2 or \
           (now - self.schedule.last_layer2) > timedelta(hours=self.config['layer2_interval_hours']):
            # 空闲时间足够才执行第二层
            if state.idle_duration > timedelta(minutes=self.config['idle_threshold_minutes']):
                return 2

        # 默认只执行第一层
        return 1

    def select_tasks(self, layer: int) -> List[BaseMaintenanceTask]:
        """选择本次要执行的任务"""
        if layer in (1, 3):
            # 第一层和第三层全执行
            return [t for t in self.registry.get_by_layer(layer) if t.can_execute(self.topology)]

        if layer == 2:
            # 第二层按优先级选预算内任务
            all_tasks = [t for t in self.registry.get_by_layer(2) if t.can_execute(self.topology)]
            # 优先级：结构洞填补 > 社区重组 > 模式识别
            priority_map = {
                'structural_hole': 1,
                'community_reorganization': 2,
                'pattern_recognition': 3,
            }
            prioritized = sorted(all_tasks, key=lambda t: priority_map.get(t.name, 99))
            budget = self.config['layer2_budget']
            return prioritized[:budget]

        return []

    @contextmanager
    def _acquire_lock(self):
        """非阻塞锁获取"""
        acquired = self._maintenance_lock.acquire(blocking=False)
        if not acquired:
            yield False
        else:
            try:
                self._is_running = True
                self._interrupt_requested = False
                yield True
            finally:
                self._is_running = False
                self._maintenance_lock.release()

    def request_interrupt(self):
        """请求中断维护（用户说话时调用）"""
        self._interrupt_requested = True

    def execute_maintenance(self, state: SystemState) -> MaintenanceReport:
        """执行维护"""
        started_at = self.clock.now_local()
        layer = self.determine_layer(state)
        tasks = self.select_tasks(layer)

        report = MaintenanceReport(
            executed_at=started_at,
            layer_executed=layer,
            tasks_executed=[],
            task_results={},
            total_changes=0,
            pending_issues=[],
        )

        with self._acquire_lock() as acquired:
            if not acquired:
                print(f"[维护调度] 🚫 已有维护正在进行，跳过本轮")
                return report

            print(f"[维护调度] 开始执行层级 {layer}，共 {len(tasks)} 个任务")

            for task in tasks:
                if self._interrupt_requested:
                    print(f"[维护调度] ⚡ 用户唤醒，中断维护")
                    break

                print(f"  [执行] {task.name}...")

                if task.execution_mode == ExecutionMode.HARD_WRITE:
                    checkpoint = self.topology.to_save_dict()
                    old_nodes = self.topology.graph.number_of_nodes()
                    old_edges = self.topology.graph.number_of_edges()

                result = task.execute(self.topology, self.config)

                if task.execution_mode == ExecutionMode.HARD_WRITE:
                    new_nodes = self.topology.graph.number_of_nodes()
                    new_edges = self.topology.graph.number_of_edges()
                    if new_nodes < old_nodes * 0.5:
                        print(f"  [回滚] ❌ 节点数骤降 {old_nodes}→{new_nodes}，恢复快照")
                        self._restore_checkpoint(checkpoint)
                        result = TaskResult(success=False, message=f"校验失败，节点数骤降，已回滚")
                    elif new_edges < old_edges * 0.3:
                        print(f"  [回滚] ❌ 边数骤降 {old_edges}→{new_edges}，恢复快照")
                        self._restore_checkpoint(checkpoint)
                        result = TaskResult(success=False, message=f"校验失败，边数骤降，已回滚")

                report.tasks_executed.append(task.name)
                report.task_results[task.name] = result
                report.total_changes += result.changes_count

                # 收集问题
                for issue_desc in result.issues_found:
                    report.pending_issues.append(Issue(
                        task_name=task.name,
                        issue_type=task.name,
                        description=issue_desc,
                    ))

                # 合并自然语言
                if result.natural_language:
                    report.natural_language_summary += result.natural_language + "\n"

        # 生成自然语言摘要
        if self.config['enable_llm_rewrite'] and self.llm and (report.pending_issues or report.total_changes > 0):
            structured = self.serializer.serialize(report)
            report.natural_language_summary = self.serializer.to_natural_language(
                structured, self.llm.client
            )

        # 更新计划记录
        now = self.clock.now_local()
        if layer >= 1:
            self.schedule.last_layer1 = now
        if layer >= 2:
            self.schedule.last_layer2 = now
        if layer >= 3:
            self.schedule.last_layer3 = now
        elapsed = (self.clock.now_local() - started_at).total_seconds()
        print(f"[维护调度] ✅ 完成，耗时 {elapsed:.2f}s，变更 {report.total_changes}，"
              f"待处理问题 {len(report.pending_issues)}")

        # 将维护发现注入主动引擎的张力场
        if self.proactive and report.pending_issues:
            for issue in report.pending_issues:
                self.proactive.on_maintenance_issue(
                    issue_type=issue.issue_type,
                    description=issue.description,
                    source_task=issue.task_name,
                )
            print(f"[主动] 🔥 已向张力场注入 {len(report.pending_issues)} 个维护发现")

        # 去重：相同描述的问题只保留一个
        existing_descs = {i.description for i in self.schedule.pending_issues}
        for issue in report.pending_issues:
            if issue.description not in existing_descs:
                self.schedule.pending_issues.append(issue)
                existing_descs.add(issue.description)
        total = len(self.schedule.pending_issues)
        if total > 0:
            print(f"[维护] 待办事项: {total}条")
            for issue in self.schedule.pending_issues[:3]:
                print(f"  - [{issue.issue_type}] {issue.description}")
            if total > 3:
                print(f"  ... 还有 {total - 3} 条")

        # 写入维护日志到文件，每日一个
        import os
        log_dir = os.path.join("memvine_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"maintenance_{datetime.now().strftime('%Y-%m-%d')}.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{report.executed_at.isoformat()}] layer={report.layer_executed} "
                    f"tasks={len(report.tasks_executed)} changes={report.total_changes} "
                    f"issues={len(report.pending_issues)}\n")
            for issue in report.pending_issues:
                f.write(f"  - [{issue.task_name}:{issue.issue_type}] {issue.description}\n")
            if report.total_changes > 0:
                for task_name, result in report.task_results.items():
                    if result.changes_count > 0:
                        f.write(f"    ✅ {task_name}: {result.changes_count} 处变更\n")
            f.write("\n")

        return report

    def update_cognitive_brief(self, report: MaintenanceReport, cognitive_brief: Dict):
        """将报告更新到认知简报"""
        if 'maintenance' not in cognitive_brief:
            cognitive_brief['maintenance'] = []
        cognitive_brief['maintenance'].append(report.to_cognitive_brief_entry())
        return cognitive_brief
    def _restore_checkpoint(self, checkpoint: dict):
        """从快照恢复图状态"""
        restored = TopologyEngine.from_save_dict(checkpoint)
        self.topology.graph = restored.graph
        self.topology.traces = restored.traces