"""In-memory model execution records; no persistence or synchronization."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4
from friday.models.profile import InferenceProfile


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(StrEnum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'


@dataclass
class ModelJob:
    model: str
    messages: list[dict[str, str]]
    priority: int = 0
    profile: InferenceProfile | None = field(default=None, kw_only=True)
    job_id: str = field(default_factory=lambda: str(uuid4()))
    status: JobStatus = field(default=JobStatus.PENDING, init=False)
    result: str | None = field(default=None, init=False)
    error: str | None = field(default=None, init=False)
    created_at: datetime = field(default_factory=utc_now, init=False)
    started_at: datetime | None = field(default=None, init=False)
    finished_at: datetime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError('A job needs a model name.')
        if not isinstance(self.priority, int):
            raise ValueError('Job priority must be an integer; lower means higher priority.')
        if self.profile is not None and not isinstance(self.profile, InferenceProfile):
            raise ValueError("A job needs a validated inference profile.")
        # Caller mutations must not alter a queued request.
        self.messages = [dict(message) for message in self.messages]
