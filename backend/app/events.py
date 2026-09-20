"""
In-process async pub/sub hub.

Every WebSocket client (app/api/ws.py) is a subscriber. Publishers are the
controller, the pipeline, and the db layer's alert/foot-check writers. Kept
deliberately tiny -- see docs/PLAN.md section 1 decision 5 (no Redis, no
Celery; one process, asyncio queues).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("glucosentry.events")


@dataclass
class Frame:
    """A single WebSocket frame, per docs/API_CONTRACT.md section 4."""

    type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data}


class EventBus:
    """Fan-out broadcaster. Each subscriber gets its own bounded queue so one
    slow WebSocket client can't back-pressure the producers; a full queue for
    that subscriber just drops the oldest frame (live data, not a log)."""

    def __init__(self, max_queue: int = 64) -> None:
        self._subscribers: set[asyncio.Queue[Frame]] = set()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue[Frame]:
        q: asyncio.Queue[Frame] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(q)
        logger.debug("subscriber added, total=%d", len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue[Frame]) -> None:
        self._subscribers.discard(q)
        logger.debug("subscriber removed, total=%d", len(self._subscribers))

    def publish(self, frame_type: str, data: dict[str, Any]) -> None:
        frame = Frame(type=frame_type, data=data)
        for q in list(self._subscribers):
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                # Drop the oldest frame to make room -- live telemetry favors
                # recency over completeness. A stuck client still gets the
                # next status/hello frame to resync from.
                try:
                    q.get_nowait()
                    q.put_nowait(frame)
                except asyncio.QueueEmpty:
                    pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Module-level singleton -- one bus per process, matching the one-backend-
# process decision in docs/PLAN.md section 1.
bus = EventBus()
