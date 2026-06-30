"""KaggleWorker — marks tasks for pickup by polling Kaggle notebook."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from ..config import KAGGLE_KEY, KAGGLE_USERNAME
from ..models.task import Task, TaskStatus

logger = logging.getLogger("reactor.workers.kaggle")

KAGGLE_QUEUE_DIR = Path(__file__).parent.parent.parent / "data" / "kaggle_queue"


class KaggleWorker:
    """
    Worker that writes tasks to a JSON queue for Kaggle notebook pickup.

    Flow:
    1. Task is written to data/kaggle_queue/{task_id}.json
    2. Kaggle notebook polls GET /api/task/{id} to pick up work
    3. Notebook processes the task on T4x2 GPU
    4. Notebook calls POST /api/notify with result
    5. This worker's wait loop detects completion
    """

    def __init__(self):
        self.name = "kaggle_t4x2"
        self.poll_interval = 10.0  # seconds between status checks
        self.max_wait = 1800.0  # 30 minutes max wait

    async def execute(self, task: Task) -> dict[str, Any]:
        """Queue task for Kaggle and wait for completion callback."""
        if not KAGGLE_USERNAME or not KAGGLE_KEY:
            return {"success": False, "error": "Kaggle credentials not configured"}

        # Write task to pickup queue
        try:
            self._write_task_to_queue(task)
        except Exception as e:
            return {"success": False, "error": f"Failed to queue for Kaggle: {e}"}

        logger.info(f"Task {task.id} queued for Kaggle pickup")

        # Wait for the task to be completed via /api/notify callback
        result = await self._wait_for_completion(task)
        return result

    def _write_task_to_queue(self, task: Task) -> None:
        """Write task details to the Kaggle pickup queue directory."""
        KAGGLE_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

        task_file = KAGGLE_QUEUE_DIR / f"{task.id}.json"
        payload = {
            "id": task.id,
            "type": task.type.value,
            "prompt": task.prompt,
            "params": task.params,
            "priority": task.priority.value,
            "created_at": task.created_at,
            "status": "waiting_pickup",
            "kaggle_meta": {
                "gpu": "T4x2",
                "max_runtime_hours": 12,
                "model_suggestions": self._get_model_suggestions(task),
            },
        }

        with open(task_file, "w") as f:
            json.dump(payload, f, indent=2)

    def _get_model_suggestions(self, task: Task) -> list[str]:
        """Suggest models appropriate for Kaggle T4x2."""
        from ..models.task import TaskType

        suggestions = {
            TaskType.VIDEO_HD: ["wan2.1-t2v", "ltx-video"],
            TaskType.VIDEO_EXPRESS: ["ltx-video", "animatediff"],
            TaskType.IMAGE_HD: ["sdxl", "flux-schnell"],
            TaskType.LLM_HEAVY: ["llama-3-8b", "mistral-7b"],
            TaskType.TRAINING: ["lora-sdxl", "lora-flux"],
        }
        return suggestions.get(task.type, ["auto"])

    async def _wait_for_completion(self, task: Task) -> dict[str, Any]:
        """Poll task status until completion or timeout."""
        start = time.time()

        while (time.time() - start) < self.max_wait:
            # Check if task was completed via callback (status updated externally)
            if task.status == TaskStatus.COMPLETED:
                self._cleanup_queue(task.id)
                return {
                    "success": True,
                    "url": task.result_url,
                    "data": task.result_data,
                }

            if task.status == TaskStatus.FAILED:
                self._cleanup_queue(task.id)
                return {"success": False, "error": task.error or "Kaggle execution failed"}

            if task.status == TaskStatus.CANCELLED:
                self._cleanup_queue(task.id)
                return {"success": False, "error": "Task cancelled"}

            await asyncio.sleep(self.poll_interval)

        # Timeout
        self._cleanup_queue(task.id)
        return {"success": False, "error": f"Kaggle worker timed out after {self.max_wait}s"}

    def _cleanup_queue(self, task_id: str) -> None:
        """Remove task file from queue after processing."""
        task_file = KAGGLE_QUEUE_DIR / f"{task_id}.json"
        try:
            if task_file.exists():
                task_file.unlink()
        except OSError:
            pass

    def get_pending_tasks(self) -> list[dict[str, Any]]:
        """List tasks waiting for Kaggle pickup (used by notebook poller)."""
        if not KAGGLE_QUEUE_DIR.exists():
            return []

        tasks = []
        for f in KAGGLE_QUEUE_DIR.glob("*.json"):
            try:
                with open(f, "r") as fp:
                    data = json.load(fp)
                    if data.get("status") == "waiting_pickup":
                        tasks.append(data)
            except (json.JSONDecodeError, IOError):
                continue

        # Sort by priority (lower = higher priority)
        tasks.sort(key=lambda t: t.get("priority", 2))
        return tasks
