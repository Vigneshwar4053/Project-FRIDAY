"""Backend contract and cooperative deadlines. Real action dispatch is disabled."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Event
from time import monotonic
from friday.desktop.observation import DesktopStatus


class DesktopFailure(RuntimeError):
    def __init__(self, status):
        self.status = DesktopStatus(status)
        super().__init__(self.status.value)


@dataclass(frozen=True)
class Deadline:
    expires: float
    cancelled: Event
    clock: object = monotonic

    def check(self):
        if self.cancelled.is_set():
            raise DesktopFailure(DesktopStatus.CANCELLED)
        if self.clock() >= self.expires:
            raise DesktopFailure(DesktopStatus.TIMEOUT)


class AccessibilityBackend(ABC):
    # Only explicit test doubles implement action dispatch at this checkpoint.
    supports_actions = False

    @abstractmethod
    def list_windows(self, application_id, deadline):
        """Bounded attributed windows for one approved application."""

    @abstractmethod
    def observe(self, window, deadline):
        """Fresh bounded snapshot or explicit unsupported/changed result."""

    def perform(self, action, deadline):
        deadline.check()
        raise DesktopFailure(DesktopStatus.UNSUPPORTED)

    def cancel(self):
        """Cancel owned requests only, never terminate owner applications."""

    def close(self):
        self.cancel()


class UnavailableBackend(AccessibilityBackend):
    def list_windows(self, application_id, deadline):
        deadline.check()
        raise DesktopFailure(DesktopStatus.UNSUPPORTED)

    def observe(self, window, deadline):
        deadline.check()
        raise DesktopFailure(DesktopStatus.UNSUPPORTED)
