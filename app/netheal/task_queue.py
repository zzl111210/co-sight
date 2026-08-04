"""Background task queue with idempotency, retry, and progress tracking.

Provides a lightweight in-process task runner for NetHeal-Agent operations.
For production, replace with Celery/RQ while keeping the same interface.

Key features:
- Idempotency: duplicate task submissions with the same key return the existing result.
- Retry: configurable max retries with exponential backoff.
- Progress: tasks report their current stage for real-time UI updates.
- Cancellation: long-running tasks can be cancelled.

See: CODEX_HANDOFF.md §19.2 (P1-3)
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskProgress:
    """Progress snapshot for a running task."""

    stage: int = 0
    total_stages: int = 6
    stage_label: str = ""
    message: str = ""
    percent: float = 0.0


@dataclass
class TaskResult:
    """Result of a completed or failed task."""

    task_id: str
    status: TaskStatus
    result: Any = None
    error: str = ""
    progress: TaskProgress = field(default_factory=TaskProgress)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    attempts: int = 0
    idempotency_key: str = ""


class TaskQueue:
    """In-process task queue with idempotency and retry support.

    Usage:
        queue = TaskQueue(max_workers=4)
        task_id = queue.submit(
            fn=my_long_running_function,
            idempotency_key="demo-001-run",
            args=(scenario_id,),
        )
        # Poll for progress
        progress = queue.get_progress(task_id)
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, TaskResult] = {}
        self._futures: dict[str, Future] = {}
        self._progress: dict[str, TaskProgress] = {}
        self._idempotency: dict[str, str] = {}  # key -> task_id
        self._lock = threading.RLock()

    def submit(
        self,
        fn: Callable,
        idempotency_key: str | None = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 2.0,
        args: tuple = (),
        kwargs: dict | None = None,
        inject_task_id: bool = False,
    ) -> str:
        """Submit a task for background execution.

        Args:
            fn: The callable to execute.
            idempotency_key: If provided and a task with the same key exists,
                returns the existing task_id instead of creating a duplicate.
            max_retries: Maximum retry attempts on failure.
            retry_delay_seconds: Base delay between retries (exponential backoff).
            args: Positional arguments for fn.
            kwargs: Keyword arguments for fn.
            inject_task_id: Pass the generated task id as the callable's first
                positional argument. Useful for progress-aware jobs.

        Returns:
            task_id: Unique identifier for tracking progress and retrieving results.
        """
        kwargs = kwargs or {}

        with self._lock:
            # Idempotency check
            if idempotency_key and idempotency_key in self._idempotency:
                existing_id = self._idempotency[idempotency_key]
                existing = self._tasks.get(existing_id)
                if existing and existing.status in (TaskStatus.COMPLETED, TaskStatus.RUNNING):
                    return existing_id

            task_id = f"TASK-{uuid.uuid4().hex[:8].upper()}"
            result = TaskResult(
                task_id=task_id,
                status=TaskStatus.PENDING,
                idempotency_key=idempotency_key or "",
            )
            self._tasks[task_id] = result
            self._progress[task_id] = TaskProgress()

            if idempotency_key:
                self._idempotency[idempotency_key] = task_id

        future = self._executor.submit(
            self._run_with_retry,
            task_id, fn, max_retries, retry_delay_seconds, args, kwargs, inject_task_id,
        )
        self._futures[task_id] = future
        return task_id

    def _run_with_retry(
        self,
        task_id: str,
        fn: Callable,
        max_retries: int,
        retry_delay: float,
        args: tuple,
        kwargs: dict,
        inject_task_id: bool,
    ) -> None:
        result = self._tasks[task_id]
        result.status = TaskStatus.RUNNING
        result.started_at = time.time()

        last_error: str | None = None
        for attempt in range(max_retries + 1):
            result.attempts = attempt + 1

            # Check cancellation
            if result.status == TaskStatus.CANCELLED:
                return

            try:
                output = (
                    fn(task_id, *args, **kwargs)
                    if inject_task_id
                    else fn(*args, **kwargs)
                )
                result.status = TaskStatus.COMPLETED
                result.result = output
                result.completed_at = time.time()
                self._progress[task_id].percent = 100.0
                return
            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)  # exponential backoff
                    time.sleep(delay)
                else:
                    result.status = TaskStatus.FAILED
                    result.error = last_error
                    result.completed_at = time.time()

    def update_progress(
        self,
        task_id: str,
        stage: int,
        total_stages: int = 6,
        stage_label: str = "",
        message: str = "",
    ) -> None:
        """Update the progress of a running task (called from within the task)."""
        with self._lock:
            if task_id in self._progress:
                self._progress[task_id] = TaskProgress(
                    stage=stage,
                    total_stages=total_stages,
                    stage_label=stage_label,
                    message=message,
                    percent=((stage + 1) / max(total_stages, 1)) * 100,
                )

    def get_progress(self, task_id: str) -> TaskProgress | None:
        """Get current progress for a task."""
        return self._progress.get(task_id)

    def get_result(self, task_id: str, wait: bool = True) -> TaskResult | None:
        """Get a task result, optionally waiting for completion.

        Polling API handlers should pass wait=False so they remain responsive
        while a diagnosis is still running.
        """
        future = self._futures.get(task_id)
        if wait and future and not future.done():
            future.result()  # block until complete
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task."""
        with self._lock:
            result = self._tasks.get(task_id)
            if result and result.status == TaskStatus.RUNNING:
                result.status = TaskStatus.CANCELLED
                result.completed_at = time.time()
                return True
        return False

    def list_tasks(self) -> list[dict[str, Any]]:
        """List all tasks with basic status."""
        return [
            {
                "task_id": t.task_id,
                "status": t.status.value,
                "attempts": t.attempts,
                "error": t.error[:200] if t.error else "",
                "idempotency_key": t.idempotency_key,
            }
            for t in self._tasks.values()
        ]

    def shutdown(self, wait: bool = True) -> None:
        """Gracefully shut down the executor."""
        self._executor.shutdown(wait=wait)


# ---------------------------------------------------------------------------
# Global singleton for the NetHeal router
# ---------------------------------------------------------------------------

_global_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _global_queue
    if _global_queue is None:
        _global_queue = TaskQueue(max_workers=4)
    return _global_queue
