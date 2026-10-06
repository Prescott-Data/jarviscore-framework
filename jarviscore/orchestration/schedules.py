"""Durable schedules and event triggers that start or wake goals.

A schedule names an action and when it happens. The action starts a goal or
wakes a step that is waiting. The time is a moment, an interval, or a named
event. Records live in Redis so they outlive the process that made them.
Every firing has a deterministic occurrence, so mesh nodes polling the same
book start each occurrence once.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import redis

SCHEDULES = "jarviscore:schedules"
DUE = "jarviscore:schedules:due"
EVENT_PREFIX = "jarviscore:schedule_events:"


@dataclass(frozen=True)
class Firing:
    schedule_id: str
    occurrence: str
    action: Dict[str, Any]
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def workflow_id(self) -> str:
        if self.action["kind"] == "wake":
            return str(self.action["workflow_id"])
        return f"{self.schedule_id}-{self.occurrence}"


def _validated_action(action: Dict[str, Any]) -> Dict[str, Any]:
    kind = action.get("kind")
    if kind == "goal":
        if not str(action.get("goal") or "").strip():
            raise ValueError("A scheduled goal needs goal text.")
    elif kind == "wake":
        if not action.get("workflow_id") or not action.get("step_id"):
            raise ValueError("A scheduled wake needs workflow_id and step_id.")
    else:
        raise ValueError("A schedule action is a goal or a wake.")
    return {**action, "context": dict(action.get("context") or {})}


class ScheduleBook:
    def __init__(self, client: "redis.Redis", clock: Callable[[], float] = time.time):
        self._redis = client
        self._clock = clock

    def add(
        self,
        action: Dict[str, Any],
        *,
        at: Optional[float] = None,
        every_seconds: Optional[float] = None,
        event: Optional[str] = None,
        schedule_id: Optional[str] = None,
    ) -> str:
        action = _validated_action(action)
        timed = at is not None or every_seconds is not None
        if timed == bool(event):
            raise ValueError("A schedule runs at a time, on an interval, or on an event.")
        if every_seconds is not None and every_seconds <= 0:
            raise ValueError("A schedule interval must be positive.")
        if action["kind"] == "wake" and every_seconds is not None:
            raise ValueError("A waiting step is woken once, not on an interval.")
        identity = schedule_id or f"sched-{uuid.uuid4().hex[:12]}"
        now = self._clock()
        next_run_at = at if at is not None else (now + every_seconds if every_seconds else None)
        record = {
            "schedule_id": identity,
            "action": action,
            "every_seconds": every_seconds,
            "next_run_at": next_run_at,
            "event": event or None,
            "created_at": now,
            "fired": 0,
            "last_fired_at": None,
            "last_occurrence": None,
        }
        pipe = self._redis.pipeline()
        pipe.hset(SCHEDULES, identity, json.dumps(record, default=str))
        if next_run_at is not None:
            pipe.zadd(DUE, {identity: next_run_at})
        if event:
            pipe.sadd(EVENT_PREFIX + event, identity)
        pipe.execute()
        return identity

    def get(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        raw = self._redis.hget(SCHEDULES, schedule_id)
        return json.loads(raw) if raw else None

    def list(self) -> List[Dict[str, Any]]:
        return [json.loads(raw) for raw in self._redis.hgetall(SCHEDULES).values()]

    def cancel(self, schedule_id: str) -> bool:
        record = self.get(schedule_id)
        if record is None:
            return False
        pipe = self._redis.pipeline()
        pipe.hdel(SCHEDULES, schedule_id)
        pipe.zrem(DUE, schedule_id)
        if record.get("event"):
            pipe.srem(EVENT_PREFIX + record["event"], schedule_id)
        pipe.execute()
        return True

    def claim_due(self) -> List[Firing]:
        """Take every timed schedule whose moment has come.

        A recurring schedule that missed several moments while nothing was
        running fires once and resumes its interval from now: the person gets
        the work, not a burst of identical runs.
        """
        now = self._clock()
        firings = []
        for schedule_id in self._redis.zrangebyscore(DUE, "-inf", now):
            firing = self._claim(schedule_id, now)
            if firing is not None:
                firings.append(firing)
        return firings

    def _claim(self, schedule_id: str, now: float) -> Optional[Firing]:
        pipe = self._redis.pipeline()
        while True:
            try:
                pipe.watch(DUE, SCHEDULES)
                score = pipe.zscore(DUE, schedule_id)
                raw = pipe.hget(SCHEDULES, schedule_id)
                if score is None or score > now or raw is None:
                    pipe.unwatch()
                    return None
                record = json.loads(raw)
                occurrence = str(int(score))
                every = record.get("every_seconds")
                record["fired"] = int(record.get("fired") or 0) + 1
                record["last_fired_at"] = now
                record["last_occurrence"] = occurrence
                pipe.multi()
                if every:
                    following = score + every
                    record["next_run_at"] = following if following > now else now + every
                    pipe.zadd(DUE, {schedule_id: record["next_run_at"]})
                    pipe.hset(SCHEDULES, schedule_id, json.dumps(record, default=str))
                else:
                    pipe.zrem(DUE, schedule_id)
                    pipe.hdel(SCHEDULES, schedule_id)
                pipe.execute()
                return Firing(schedule_id, occurrence, record["action"], dict(record["action"]["context"]))
            except redis.WatchError:
                continue

    def for_event(self, event: str, event_id: str, payload: Optional[Dict[str, Any]] = None) -> List[Firing]:
        firings = []
        for schedule_id in sorted(self._redis.smembers(EVENT_PREFIX + event)):
            record = self.get(schedule_id)
            if record is None:
                continue
            context = {
                **record["action"]["context"],
                "event": {"name": event, "id": event_id, "payload": dict(payload or {})},
            }
            firings.append(Firing(schedule_id, f"event-{event_id}", record["action"], context))
        return firings
