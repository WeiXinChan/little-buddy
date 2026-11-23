"""Request-local timing markers. Values never come from voice or provider payloads."""
from contextvars import ContextVar

observer = ContextVar("voice_timing_observer", default=None)
segment_number = ContextVar("voice_timing_segment", default=0)


def mark(event: str) -> None:
    sink = observer.get()
    if sink is not None:
        sink(event, segment_number.get())
