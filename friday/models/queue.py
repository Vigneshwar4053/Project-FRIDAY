"""Deterministic priority/FIFO queue for a single-threaded runtime."""
import heapq
from itertools import count

from friday.models.job import JobStatus, ModelJob


class ModelJobQueue:
    """Lower numeric priority executes first; equal priorities use enqueue order.

    Priority is captured at enqueue time; editing a queued job is unsupported.
    This queue provides no cross-thread or cross-process synchronization.
    """
    def __init__(self):
        self._entries: list[tuple[int, int, ModelJob]] = []
        self._sequence = count()
        self._queued_ids: set[str] = set()

    def __len__(self) -> int:
        return len(self._entries)

    def enqueue(self, job: ModelJob) -> None:
        if job.status != JobStatus.PENDING:
            raise ValueError('Only pending jobs can be queued.')
        if job.job_id in self._queued_ids:
            raise ValueError('This job is already queued.')
        heapq.heappush(self._entries, (job.priority, next(self._sequence), job))
        self._queued_ids.add(job.job_id)

    def next_job(self) -> ModelJob | None:
        if not self._entries:
            return None
        _, _, job = heapq.heappop(self._entries)
        self._queued_ids.remove(job.job_id)
        return job

    def remove(self, job: ModelJob) -> None:
        """Remove a supplied job before direct execution, avoiding later replay."""
        for index, (_, _, queued) in enumerate(self._entries):
            if queued.job_id == job.job_id:
                if queued is not job:
                    raise ValueError('A different queued job has this job ID.')
                self._entries.pop(index)
                self._queued_ids.remove(job.job_id)
                heapq.heapify(self._entries)
                return
