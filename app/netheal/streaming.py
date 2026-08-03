"""Server-Sent Events (SSE) and WebSocket streaming for NetHeal-Agent.

Provides real-time push of:
- Agent execution stages (alarm → topology → diagnosis → repair → verify)
- Tool call logs with input/output
- Incident lifecycle state changes
- KPI metric updates

SSE is preferred for one-way server→client streaming (simpler, works through proxies).
WebSocket is available for bidirectional communication when needed.

See: CODEX_HANDOFF.md §19.2 (P1-5)
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Optional


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class StreamEventType(str, Enum):
    """Types of events that can be streamed to the client."""

    # Agent lifecycle
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    # Tool calls
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"

    # Incident lifecycle
    INCIDENT_CREATED = "incident_created"
    STATUS_CHANGED = "status_changed"
    INCIDENT_CLOSED = "incident_closed"

    # Metrics
    KPI_UPDATED = "kpi_updated"
    TOPOLOGY_CHANGED = "topology_changed"

    # System
    HEARTBEAT = "heartbeat"
    ERROR = "error"


@dataclass
class StreamEvent:
    """A single event to be sent over SSE or WebSocket."""

    event_type: StreamEventType
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
    timestamp: float = field(default_factory=time.time)
    incident_id: str = ""


# ---------------------------------------------------------------------------
# Event bus (in-process pub/sub)
# ---------------------------------------------------------------------------


class EventBus:
    """Thread-safe publish/subscribe event bus for NetHeal streaming.

    Subscribers register queues to receive events. Publishers push events
    to all active subscribers. This is the core mechanism that drives both
    SSE and WebSocket streams.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, queue.Queue] = {}
        self._lock = threading.RLock()
        self._running = True

    def subscribe(self) -> str:
        """Register a new subscriber and return its ID."""
        subscriber_id = f"sub-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._subscribers[subscriber_id] = queue.Queue()
        return subscriber_id

    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber."""
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish(self, event: StreamEvent) -> None:
        """Publish an event to all active subscribers."""
        with self._lock:
            for sub_id, q in list(self._subscribers.items()):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass  # Skip slow subscribers

    def get_events(self, subscriber_id: str, timeout: float = 30.0) -> list[StreamEvent]:
        """Block until at least one event is available, then return all pending."""
        q = self._subscribers.get(subscriber_id)
        if q is None:
            return []

        events = []
        try:
            # Block for the first event
            first = q.get(timeout=timeout)
            events.append(first)
            # Drain remaining events without blocking
            while True:
                try:
                    events.append(q.get_nowait())
                except queue.Empty:
                    break
        except queue.Empty:
            pass
        return events

    def shutdown(self) -> None:
        self._running = False
        with self._lock:
            self._subscribers.clear()


# ---------------------------------------------------------------------------
# Global event bus singleton
# ---------------------------------------------------------------------------

_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# ---------------------------------------------------------------------------
# SSE generator for FastAPI
# ---------------------------------------------------------------------------


async def sse_event_stream(
    subscriber_id: str | None = None,
    incident_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Async generator yielding SSE-formatted events.

    Usage in FastAPI:
        from fastapi.responses import StreamingResponse
        return StreamingResponse(sse_event_stream(), media_type="text/event-stream")

    The client receives events in this format:
        event: agent_started
        id: evt-abc123
        data: {"agent": "alarm_agent", "message": "..."}

    """
    bus = get_event_bus()
    sub_id = subscriber_id or bus.subscribe()
    heartbeat_interval = 15  # seconds

    try:
        last_heartbeat = time.time()
        while True:
            events = bus.get_events(sub_id, timeout=heartbeat_interval)

            for event in events:
                # Filter by incident_id if requested
                if incident_id and event.incident_id and event.incident_id != incident_id:
                    continue

                sse_data = json.dumps(event.data, ensure_ascii=False)
                yield f"event: {event.event_type.value}\n"
                yield f"id: {event.event_id}\n"
                yield f"data: {sse_data}\n\n"

            # Send heartbeat if no events in the interval
            now = time.time()
            if now - last_heartbeat >= heartbeat_interval:
                yield f"event: heartbeat\n"
                yield f"data: {{\"timestamp\": {now}}}\n\n"
                last_heartbeat = now

            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass
    finally:
        if not subscriber_id:
            bus.unsubscribe(sub_id)


# ---------------------------------------------------------------------------
# Convenience functions for publishing from service layer
# ---------------------------------------------------------------------------


def publish_agent_event(
    agent_name: str,
    event_type: StreamEventType,
    incident_id: str = "",
    message: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """Publish an agent lifecycle event to the event bus."""
    bus = get_event_bus()
    bus.publish(
        StreamEvent(
            event_type=event_type,
            data={
                "agent": agent_name,
                "message": message,
                **(detail or {}),
            },
            incident_id=incident_id,
        )
    )


def publish_tool_event(
    tool_name: str,
    event_type: StreamEventType,
    incident_id: str = "",
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    error: str = "",
    duration_ms: float = 0.0,
) -> None:
    """Publish a tool call event to the event bus."""
    bus = get_event_bus()
    bus.publish(
        StreamEvent(
            event_type=event_type,
            data={
                "tool": tool_name,
                "input": input_data,
                "output": output_data,
                "error": error,
                "duration_ms": round(duration_ms, 2),
            },
            incident_id=incident_id,
        )
    )


def publish_status_change(
    incident_id: str,
    old_status: str,
    new_status: str,
    actor: str = "system",
    message: str = "",
) -> None:
    """Publish an incident status change event."""
    bus = get_event_bus()
    bus.publish(
        StreamEvent(
            event_type=StreamEventType.STATUS_CHANGED,
            data={
                "old_status": old_status,
                "new_status": new_status,
                "actor": actor,
                "message": message,
            },
            incident_id=incident_id,
        )
    )
