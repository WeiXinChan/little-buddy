"""Transport-independent one-turn contract for the private voice backend."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import AsyncContextManager
from typing import Protocol

UPLOAD_RATE = 16_000
PLAYBACK_RATE = 24_000
MAX_SAMPLES = UPLOAD_RATE * 20
MAX_FRAME_SAMPLES = UPLOAD_RATE // 5


class ProtocolError(ValueError):
    pass


class Recognition(Protocol):
    async def write(self, pcm16le: bytes) -> None: ...
    async def finish(self) -> str: ...


class Providers(Protocol):
    # Enter returns only after the streaming recognizer is ready.
    def recognize(self, sample_rate: int) -> AsyncContextManager[Recognition]: ...
    def answer(self, transcript: str) -> AsyncContextManager[AsyncIterator[str]]: ...
    def synthesize(self, segment: str, sample_rate: int) -> AsyncContextManager[AsyncIterator[bytes]]: ...


class Channel(Protocol):
    async def ready(self) -> None: ...
    async def receive(self) -> "Audio | End": ...
    async def segment_started(self, number: int) -> None: ...
    async def audio(self, pcm16le: bytes) -> None: ...
    async def segment_ended(self, number: int, samples: int) -> None: ...
    async def reply_ended(self, count: int) -> None: ...


class ContentPolicy(Protocol):
    # Return an approved replacement or None to terminate the reply.
    def input(self, transcript: str) -> str | None: ...
    def segment(self, text: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Audio:
    start: int
    data: bytes


@dataclass(frozen=True, slots=True)
class End:
    samples: int


@dataclass(frozen=True, slots=True)
class Limits:
    ready: float = 3
    io: float = 4
    turn: float = 45


@asynccontextmanager
async def prefetch_segments(segments: AsyncIterator[str]):
    """Read ahead while TTS is busy, with one queue slot and turn-owned cleanup."""
    queue: asyncio.Queue[str | Exception | None] = asyncio.Queue(maxsize=1)

    async def produce():
        try:
            async for segment in segments:
                await queue.put(segment)
        except Exception as exc:
            await queue.put(exc)
        else:
            await queue.put(None)

    async def consume():
        while (item := await queue.get()) is not None:
            if isinstance(item, Exception):
                raise item
            yield item

    producer = asyncio.create_task(produce())
    try:
        yield consume()
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


async def run_turn(
    channel: Channel, providers: Providers, policy: ContentPolicy, limits: Limits = Limits(),
    *, mark: Callable[[str], None] = lambda _: None,
) -> None:
    """Run inside an authenticated connection-owned task.

    The transport cancels and awaits this task on stop/disconnect before granting
    another turn. Provider contexts own resource cleanup on every exit path.
    """
    async with asyncio.timeout(limits.turn):
        transcript = await recognize(channel, providers, limits, mark)
        mark("asr_final")
        approved = policy.input(transcript)
        if not approved:
            raise ProtocolError("input rejected")
        deadline = asyncio.get_running_loop().time() + limits.io
        async with AsyncExitStack() as resources:
            async with asyncio.timeout_at(deadline):
                segments = await resources.enter_async_context(providers.answer(approved))
            async with prefetch_segments(segments) as buffered:
                count, deadline = await deliver(channel, providers, policy, buffered, limits, deadline, mark)
        if count == 0:
            raise ProtocolError("empty reply")
        async with asyncio.timeout_at(deadline):
            await channel.reply_ended(count)


async def recognize(channel: Channel, providers: Providers, limits: Limits,
                    mark: Callable[[str], None]) -> str:
    async with AsyncExitStack() as resources:
        async with asyncio.timeout(limits.ready):
            asr = await resources.enter_async_context(providers.recognize(UPLOAD_RATE))
        await channel.ready()
        position = 0
        while True:
            async with asyncio.timeout(limits.io):
                event = await channel.receive()
                if isinstance(event, End):
                    if position == 0 or event.samples != position:
                        raise ProtocolError("invalid end position")
                    mark("capture_sealed")
                    transcript = (await asr.finish()).strip()
                    if not transcript or len(transcript) > 1024:
                        raise ProtocolError("invalid transcript")
                    return transcript
                samples, extra_byte = divmod(len(event.data), 2)
                if (event.start != position or extra_byte or
                        not 0 < samples <= MAX_FRAME_SAMPLES or position + samples > MAX_SAMPLES):
                    raise ProtocolError("invalid audio frame")
                await asr.write(event.data)
                position += samples


async def deliver(
    channel: Channel,
    providers: Providers,
    policy: ContentPolicy,
    segments: AsyncIterator[str],
    limits: Limits,
    deadline: float,
    mark: Callable[[str], None],
) -> tuple[int, float]:
    count = 0
    clock = asyncio.get_running_loop().time
    while True:
        async with asyncio.timeout_at(deadline):
            text = await anext(segments, None)
        if text is None:
            return count, deadline
        count += 1
        approved = policy.segment(text)
        if count > 8 or not approved or len(approved) > 240:
            raise ProtocolError("invalid reply segment")
        if count == 1:
            mark("llm_first_approved_segment")
        async with AsyncExitStack() as resources:
            async with asyncio.timeout_at(deadline):
                frames = await resources.enter_async_context(providers.synthesize(approved, PLAYBACK_RATE))
                await channel.segment_started(count)
            samples = 0
            while True:
                async with asyncio.timeout_at(deadline):
                    frame = await anext(frames, None)
                    if frame is None:
                        break
                    frame_samples, extra_byte = divmod(len(frame), 2)
                    first_pcm = count == 1 and samples == 0
                    samples += frame_samples
                    if extra_byte or not frame_samples or samples > PLAYBACK_RATE * 10:
                        raise ProtocolError("invalid synthesized audio")
                    if first_pcm:
                        mark("tts_first_pcm")
                    await channel.audio(frame)
                deadline = clock() + limits.io
            if samples == 0:
                raise ProtocolError("empty synthesized audio")
            async with asyncio.timeout_at(deadline):
                await channel.segment_ended(count, samples)
            deadline = clock() + limits.io
