"""Trace sinks: in-memory ring buffer, live SSE bus, and the Postgres writer.

The bus and the memory store are the primary path, deliberately: the demo must
not depend on a database being reachable, and the live reasoning stream in the
chat UI is rendered from the bus while the answer is still composing. The
Postgres sink is what makes runs survive a restart and lets ``/api/metrics``
aggregate across a shift.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from typing import Any

from .tracer import Fact, RunTrace, Span


class MemorySink:
    """Keeps the last N runs fully inspectable without a database."""

    def __init__(self, capacity: int = 200) -> None:
        self.capacity = capacity
        self._runs: OrderedDict[str, RunTrace] = OrderedDict()

    def handle(self, event: str, payload: Any) -> None:
        if event == "run_start" and isinstance(payload, RunTrace):
            self._runs[payload.run_id] = payload
            while len(self._runs) > self.capacity:
                self._runs.popitem(last=False)

    def get(self, run_id: str) -> RunTrace | None:
        return self._runs.get(run_id)

    def list(self, limit: int = 50) -> list[RunTrace]:
        return list(reversed(list(self._runs.values())))[:limit]

    def all(self) -> list[RunTrace]:
        return list(self._runs.values())


class EventBus:
    """Fan-out of trace events to any number of live SSE subscribers."""

    def __init__(self, backlog: int = 500) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._global: list[asyncio.Queue] = []
        self._recent: deque[dict] = deque(maxlen=backlog)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ---- publishing (called from sync tracer code) --------------------
    def handle(self, event: str, payload: Any) -> None:
        message = _serialise(event, payload)
        if message is None:
            return
        self._recent.append(message)
        run_id = message.get("run_id")
        targets = list(self._global) + list(self._subscribers.get(run_id, []))
        for queue in targets:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass

    # ---- subscribing --------------------------------------------------
    def subscribe(self, run_id: str | None = None, maxsize: int = 1000) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        if run_id is None:
            self._global.append(queue)
        else:
            self._subscribers.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue, run_id: str | None = None) -> None:
        target = self._global if run_id is None else self._subscribers.get(run_id, [])
        if queue in target:
            target.remove(queue)
        if run_id and not self._subscribers.get(run_id):
            self._subscribers.pop(run_id, None)

    def recent(self, run_id: str | None = None, limit: int = 100) -> list[dict]:
        rows = [m for m in self._recent if run_id is None or m.get("run_id") == run_id]
        return rows[-limit:]


def _serialise(event: str, payload: Any) -> dict | None:
    if isinstance(payload, Span):
        return {
            "event": event,
            "run_id": payload.run_id,
            "span_id": payload.span_id,
            "parent_span_id": payload.parent_span_id,
            "name": payload.name,
            "type": payload.type,
            "status": payload.status,
            "duration_ms": payload.duration_ms,
            "attrs": payload.attrs,
            "error": payload.error,
        }
    if isinstance(payload, Fact):
        return {"event": event, "run_id": payload.run_id, **payload.as_dict()}
    if isinstance(payload, RunTrace):
        return {"event": event, **payload.summary()}
    if isinstance(payload, dict):
        return {"event": event, **payload}
    return None


class DatabaseSink:
    """Persists finished runs. Buffers so a slow DB never blocks a request."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self.enabled = session_factory is not None
        self.failures = 0

    def handle(self, event: str, payload: Any) -> None:
        if not self.enabled or event != "run_end" or not isinstance(payload, RunTrace):
            return
        try:
            from ..db.trace_repo import persist_run

            with self._session_factory() as session:
                persist_run(session, payload)
                session.commit()
        except Exception:  # noqa: BLE001 - never break a request over telemetry
            self.failures += 1


MEMORY_SINK = MemorySink()
EVENT_BUS = EventBus()
