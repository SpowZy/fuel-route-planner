"""Bookkeeping for calls to external services, reported back in every API response."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CallLog:
    calls: list[dict] = field(default_factory=list)

    def record(self, service: str, started: float, note: str = "") -> None:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        self.calls.append({"service": service, "ms": elapsed_ms, "note": note})

    def __len__(self) -> int:
        return len(self.calls)
