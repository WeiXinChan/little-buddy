"""One first-effective-response budget, anchored before ASR/endpoint waiting.

Only server receipt minus a nonnegative capture age establishes a boundary.
No client absolute/future clock, probe, seal or retry can create extra time.
"""
import math


class ResponseBudget:
    def __init__(self, clock, seconds=15):
        self.clock, self.seconds = clock, seconds
        self.anchor = None
        self.thinking_at = None
        self.thinking_seconds = 0.0
        # Shared by endpoint, planning and fact reads for this expression. A
        # player/turn rebuild must not grant another retry or a fresh deadline.
        self.read_retry_revision = None

    def speech(self, age_ms=0):
        if type(age_ms) is not int or not 0 <= age_ms <= 20000:
            raise ValueError('capture age')
        boundary = self.clock() - age_ms / 1000
        # Older buffered frames cannot move an already observed boundary backwards.
        if self.anchor is None or boundary > self.anchor:
            self.anchor = boundary
            self.thinking_at = None
            self.thinking_seconds = 0.0

    def pause_thinking(self):
        if self.thinking_at is None:
            self.thinking_at = self.clock()

    def resume(self):
        if self.thinking_at is not None:
            self.thinking_seconds += max(0, self.clock() - self.thinking_at)
            self.thinking_at = None

    @property
    def deadline(self):
        return None if self.anchor is None else self.anchor + self.seconds + self.thinking_seconds

    def remaining(self):
        if self.deadline is None:
            raise ValueError('no expression boundary')
        value = self.deadline - self.clock()
        if not math.isfinite(value) or value <= 0:
            raise TimeoutError('response budget exhausted')
        return value
