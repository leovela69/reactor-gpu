"""Task model with enums and dataclass for REACTOR."""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskType(str, Enum):
    """Types of GPU/AI tasks supported."""
    VIDEO_EXPRESS = "video_express"
    VIDEO_HD = "video_hd"
    VIDEO_4K = "video_4k"
    IMAGE_HD = "image_hd"
    IMAGE_EXPRESS = "image_express"
    LLM_HEAVY = "llm_heavy"
    LLM_LIGHT = "llm_light"
    TRAINING = "training"
    AUDIO = "audio"
    AUDIO_MUSIC = "audio_music"
    FACE_SWAP = "face_swap"
    UPSCALE = "upscale"


class TaskStatus(str, Enum):
    """Lifecycle states for a task."""
    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class TaskPriority(int, Enum):
    """Priority levels (lower number = higher priority)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class Task:
    """Represents a single GPU/AI processing task."""

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: TaskType = TaskType.IMAGE_HD
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING

    # Input
    prompt: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    source_bot: str = ""
    callback_url: Optional[str] = None

    # Assignment
    assigned_worker: Optional[str] = None
    worker_meta: dict[str, Any] = field(default_factory=dict)

    # Timing
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    timeout_seconds: float = 300.0

    # Result
    result_url: Optional[str] = None
    result_data: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    # Retry logic
    attempt: int = 0
    max_retries: int = 3
    retry_delay: float = 5.0
    failed_workers: list[str] = field(default_factory=list)

    @property
    def elapsed(self) -> Optional[float]:
        """Time elapsed since task started running."""
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def is_timed_out(self) -> bool:
        """Check if task has exceeded its timeout."""
        if self.started_at is None:
            return False
        return (time.time() - self.started_at) > self.timeout_seconds

    @property
    def can_retry(self) -> bool:
        """Check if task has remaining retry attempts."""
        return self.attempt < self.max_retries

    def mark_running(self, worker: str) -> None:
        """Mark task as running on a specific worker."""
        self.status = TaskStatus.RUNNING
        self.assigned_worker = worker
        self.started_at = time.time()
        self.attempt += 1

    def mark_completed(self, result_url: Optional[str] = None, result_data: Optional[dict] = None) -> None:
        """Mark task as successfully completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = time.time()
        self.result_url = result_url
        self.result_data = result_data

    def mark_failed(self, error: str) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.completed_at = time.time()
        self.error = error
        if self.assigned_worker:
            self.failed_workers.append(self.assigned_worker)

    def mark_retrying(self) -> None:
        """Mark task for retry."""
        self.status = TaskStatus.RETRYING
        if self.assigned_worker:
            self.failed_workers.append(self.assigned_worker)
        self.assigned_worker = None
        self.started_at = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize task to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "prompt": self.prompt,
            "params": self.params,
            "source_bot": self.source_bot,
            "callback_url": self.callback_url,
            "assigned_worker": self.assigned_worker,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed": self.elapsed,
            "result_url": self.result_url,
            "result_data": self.result_data,
            "error": self.error,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
        }
