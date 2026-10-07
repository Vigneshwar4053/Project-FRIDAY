"""Immutable records returned by the memory API."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Session:
    id: int
    started_at: str
    ended_at: str | None


@dataclass(frozen=True)
class Message:
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class Memory:
    id: int
    category: str
    key: str
    value: str
    importance: int
    created_at: str
    updated_at: str
