# cognition/cogniweave/shuttle_loom.py
"""Layer 2: 并发梭织机 —— 异步并发执行图查询议程"""

import asyncio
import time
import threading
from collections import deque
from typing import Any

from .models import QueryAgenda, QueryItem, QueryResult, CognitiveContext

class ShuttleLoom:
    def __init__(self, graph_tools):
        self.graph_tools = graph_tools

    async def weave(self, agenda: QueryAgenda) -> CognitiveContext:
        if not agenda.agenda:
            return CognitiveContext(
                agenda=agenda, results={}, total_time=0,
                success_count=0, fail_count=0,
            )

        t0 = time.time()
        phases = self._topological_sort(agenda.agenda)
        all_results: dict[str, QueryResult] = {}
        semaphore = asyncio.Semaphore(agenda.max_concurrency)

        for phase in phases:
            tasks = [
                self._execute_one(q, all_results, semaphore)
                for q in phase
            ]
            phase_results = await asyncio.gather(*tasks, return_exceptions=True)
            for q, r in zip(phase, phase_results):
                if isinstance(r, Exception):
                    all_results[q.id] = QueryResult(
                        query_id=q.id, intent=q.intent,
                        cypher=q.cypher, data=None,
                        success=False, error=str(r),
                    )
                else:
                    all_results[q.id] = r

        elapsed = time.time() - t0
        success = sum(1 for r in all_results.values() if r.success)
        fail = len(all_results) - success

        return CognitiveContext(
            agenda=agenda,
            results=all_results,
            total_time=elapsed,
            success_count=success,
            fail_count=fail,
        )

    async def _execute_one(
        self,
        query: QueryItem,
        previous_results: dict[str, QueryResult],
        semaphore: asyncio.Semaphore,
    ) -> QueryResult:
        params = dict(query.params)
        if query.depends_on:
            for dep_id in query.depends_on:
                dep_result = previous_results.get(dep_id)
                if dep_result and dep_result.success:
                    params = self._resolve_params(params, dep_result.data)

        async with semaphore:
            t0 = time.time()
            try:
                loop = asyncio.get_running_loop()
                result_data = await loop.run_in_executor(
                    None, self._execute_sync, query.cypher, params
                )
                elapsed = time.time() - t0
                result_count = self._count_results(result_data)
                return QueryResult(
                    query_id=query.id,
                    intent=query.intent,
                    cypher=query.cypher,
                    data=result_data,
                    success=True,
                    execution_time=elapsed,
                    result_count=result_count,
                )
            except Exception as e:
                elapsed = time.time() - t0
                return QueryResult(
                    query_id=query.id,
                    intent=query.intent,
                    cypher=query.cypher,
                    data=None,
                    success=False,
                    error=str(e),
                    execution_time=elapsed,
                )

    def _execute_sync(self, cypher: str, params: dict) -> Any:
        result = self.graph_tools.execute(cypher, params)
        if isinstance(result, dict):
            if "error" in result:
                raise RuntimeError(result["error"])
            if "result" in result:
                return result["result"]
            if "match_count" in result:
                return result.get("matches", [])
            if "triples" in result:
                return result.get("triples", [])
            if "entities" in result:
                return result.get("entities", [])
            if "count" in result and "keyword" in result:
                return result.get("matches", result.get("triples", []))
        return result

    def _resolve_params(self, params: dict, dep_data: Any) -> dict:
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str) and v.startswith("$prev."):
                path = v[6:]
                resolved[k] = self._extract_from_path(dep_data, path)
            else:
                resolved[k] = v
        return resolved

    def _extract_from_path(self, data: Any, path: str) -> Any:
        if not data:
            return ""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                if part.endswith("[0]") and part[:-3].isdigit():
                    part = part[:-3]
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part) if part.isdigit() else 0
                    current = current[idx] if idx < len(current) else current[0]
                except (ValueError, IndexError):
                    current = current[0] if current else ""
            else:
                return str(current)
        return current if current is not None else ""

    def _count_results(self, data: Any) -> int:
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    return len(v)
            return 1
        if isinstance(data, list):
            return len(data)
        return 1 if data else 0

    def _topological_sort(self, queries: list[QueryItem]) -> list[list[QueryItem]]:
        id_to_query = {q.id: q for q in queries}
        in_degree = {q.id: 0 for q in queries}
        dependents: dict[str, list[str]] = {q.id: [] for q in queries}

        for q in queries:
            for dep in q.depends_on:
                if dep in id_to_query:
                    in_degree[q.id] += 1
                    dependents.setdefault(dep, []).append(q.id)

        queue = deque([q.id for q in queries if in_degree[q.id] == 0])
        phases = []
        while queue:
            phase = []
            for _ in range(len(queue)):
                qid = queue.popleft()
                phase.append(id_to_query[qid])
                for dep_id in dependents.get(qid, []):
                    in_degree[dep_id] -= 1
                    if in_degree[dep_id] == 0:
                        queue.append(dep_id)
            if phase:
                phases.append(phase)

        return phases

    def execute_sync(self, agenda: QueryAgenda) -> CognitiveContext:
        import concurrent.futures
        from config import COGNIWEAVE_AGENDA_TIMEOUT
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self.weave(agenda))
            return future.result(timeout=COGNIWEAVE_AGENDA_TIMEOUT)