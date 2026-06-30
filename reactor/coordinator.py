"""Coordinator — intelligent task routing and lifecycle management."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Optional

import aiohttp

from .config import WORKER_CAPS
from .models.task import Task, TaskPriority, TaskStatus, TaskType
from .quota_monitor import QuotaMonitor

logger = logging.getLogger("reactor.coordinator")


# Mapping from worker name prefix to quota source
WORKER_QUOTA_MAP: dict[str, str] = {
    "modal": "modal",
    "kaggle": "kaggle",
    "lightning": "lightning",
    "api_pollinations": "pollinations",
    "api_agnes": "agnes",
    "api_huggingface": "huggingface",
    "api_magic_hour": "magic_hour",
    "api_kling": "kling",
    "api_veo3": "veo3",
}


class Coordinator:
    """Central coordinator for GPU task routing and execution."""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.quota = QuotaMonitor()
        self.tasks: dict[str, Task] = {}
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.workers: dict[str, Any] = {}
        self._running: bool = False
        self._active_tasks: set[str] = set()
        self._callbacks: dict[str, Callable[..., Coroutine]] = {}

    def register_worker(self, name: str, worker: Any) -> None:
        """Register a worker instance."""
        self.workers[name] = worker
        logger.info(f"Registered worker: {name}")

    async def submit_task(self, task: Task) -> Task:
        """Submit a new task for processing."""
        self.tasks[task.id] = task
        task.status = TaskStatus.QUEUED
        # Priority queue uses (priority_value, timestamp, task_id)
        await self.queue.put((task.priority.value, task.created_at, task.id))
        logger.info(f"Task {task.id} queued (type={task.type.value}, priority={task.priority.name})")
        return task

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task by ID."""
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return False
        task.status = TaskStatus.CANCELLED
        task.completed_at = time.time()
        logger.info(f"Task {task_id} cancelled")
        return True

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self.tasks.get(task_id)

    def get_status(self) -> dict[str, Any]:
        """Get coordinator status summary."""
        statuses = {}
        for t in self.tasks.values():
            s = t.status.value
            statuses[s] = statuses.get(s, 0) + 1
        return {
            "total_tasks": len(self.tasks),
            "active": len(self._active_tasks),
            "max_concurrent": self.max_concurrent,
            "statuses": statuses,
            "workers": list(self.workers.keys()),
            "quotas": self.quota.get_all_quotas(),
        }

    def _get_quota_source(self, worker_name: str) -> Optional[str]:
        """Map worker name to its quota source."""
        for prefix, source in WORKER_QUOTA_MAP.items():
            if worker_name.startswith(prefix):
                return source
        return None

    def _select_worker(self, task: Task) -> Optional[str]:
        """Score and select the best worker for a task."""
        candidates: list[tuple[float, str]] = []

        for name, caps in WORKER_CAPS.items():
            # Must support the task type
            if task.type.value not in caps["tasks"]:
                continue

            # Skip workers that already failed this task
            if name in task.failed_workers:
                continue

            # Check quota
            quota_source = self._get_quota_source(name)
            if quota_source and not self.quota.has_quota(quota_source):
                continue

            # Must be registered
            if name not in self.workers:
                continue

            # Scoring
            score = 0.0

            # VRAM fit bonus
            vram = caps.get("vram_gb", 0)
            if task.type in (TaskType.VIDEO_4K, TaskType.TRAINING, TaskType.LLM_HEAVY):
                score += min(vram / 80.0, 1.0) * 30
            elif task.type in (TaskType.VIDEO_HD,):
                score += min(vram / 24.0, 1.0) * 20
            else:
                score += 10  # any VRAM is fine

            # Speed bonus
            speed = caps.get("speed", "medium")
            speed_scores = {"fast": 25, "medium": 15, "slow": 5}
            if task.priority in (TaskPriority.CRITICAL, TaskPriority.HIGH):
                score += speed_scores.get(speed, 10) * 1.5
            else:
                score += speed_scores.get(speed, 10)

            # Availability bonus
            avail = caps.get("availability", "limited")
            avail_scores = {"always": 20, "on_demand": 15, "limited": 5, "rate_limited": 8}
            score += avail_scores.get(avail, 5)

            # Quota remaining bonus
            if quota_source:
                pct = self.quota.get_quota_percent(quota_source)
                score += pct * 0.1

            # Prefer free APIs for low-priority tasks
            if task.priority in (TaskPriority.LOW, TaskPriority.BACKGROUND):
                if caps.get("vram_gb", 0) == 0:
                    score += 15

            candidates.append((score, name))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    async def _execute_task(self, task: Task) -> None:
        """Execute a single task on the selected worker."""
        self._active_tasks.add(task.id)

        try:
            worker_name = self._select_worker(task)
            if not worker_name:
                task.mark_failed("No suitable worker available")
                logger.warning(f"Task {task.id}: no worker available")
                return

            worker = self.workers[worker_name]
            task.mark_running(worker_name)
            logger.info(f"Task {task.id} → {worker_name} (attempt {task.attempt})")

            # Record quota usage
            quota_source = self._get_quota_source(worker_name)
            if quota_source:
                self.quota.record_usage(quota_source)

            # Execute
            result = await worker.execute(task)

            if result.get("success"):
                task.mark_completed(
                    result_url=result.get("url"),
                    result_data=result.get("data"),
                )
                logger.info(f"Task {task.id} completed in {task.elapsed:.1f}s")
            else:
                error = result.get("error", "Unknown error")
                if task.can_retry:
                    task.mark_retrying()
                    logger.warning(f"Task {task.id} failed, retrying: {error}")
                    await asyncio.sleep(task.retry_delay)
                    await self.queue.put((task.priority.value, time.time(), task.id))
                else:
                    task.mark_failed(error)
                    logger.error(f"Task {task.id} permanently failed: {error}")

        except Exception as e:
            error = str(e)
            if task.can_retry:
                task.mark_retrying()
                logger.warning(f"Task {task.id} exception, retrying: {error}")
                await asyncio.sleep(task.retry_delay)
                await self.queue.put((task.priority.value, time.time(), task.id))
            else:
                task.mark_failed(error)
                logger.error(f"Task {task.id} permanently failed: {error}")
        finally:
            self._active_tasks.discard(task.id)
            # Fire callback
            if task.callback_url and task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                asyncio.create_task(self._fire_callback(task))

    async def _fire_callback(self, task: Task) -> None:
        """Send task result to callback URL."""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    task.callback_url,
                    json=task.to_dict(),
                    timeout=aiohttp.ClientTimeout(total=10),
                )
                logger.info(f"Callback sent for task {task.id}")
        except Exception as e:
            logger.warning(f"Callback failed for task {task.id}: {e}")

    async def run(self) -> None:
        """Main processing loop."""
        self._running = True
        logger.info(f"Coordinator started (max_concurrent={self.max_concurrent})")

        while self._running:
            # Wait for available slot
            if len(self._active_tasks) >= self.max_concurrent:
                await asyncio.sleep(0.5)
                continue

            try:
                priority, ts, task_id = await asyncio.wait_for(
                    self.queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            task = self.tasks.get(task_id)
            if not task or task.status == TaskStatus.CANCELLED:
                continue

            asyncio.create_task(self._execute_task(task))

    async def stop(self) -> None:
        """Stop the coordinator loop."""
        self._running = False
        logger.info("Coordinator stopped")
