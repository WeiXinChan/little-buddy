"""Transport-independent one-turn contract for the private voice backend."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
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


async def run_turn(
    channel: Channel, providers: Providers, policy: ContentPolicy, limits: Limits = Limits()
) -> None:
    """Run inside an authenticated connection-owned task.

    The transport cancels and awaits this task on stop/disconnect before granting
    another turn. Provider contexts own resource cleanup on every exit path.
    """
    async with asyncio.timeout(limits.turn):
        transcript = await recognize(channel, providers, limits)
        approved = policy.input(transcript)
        if not approved:
            raise ProtocolError("input rejected")
        async with providers.answer(approved) as segments:
            count = await deliver(channel, providers, policy, segments, limits)
        if count == 0:
            raise ProtocolError("empty reply")
        await channel.reply_ended(count)


async def recognize(channel: Channel, providers: Providers, limits: Limits) -> str:
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
) -> int:
    count = 0
    while True:
        async with asyncio.timeout(limits.io):
            text = await anext(segments, None)
        if text is None:
            return count
        count += 1
        approved = policy.segment(text)
        if count > 8 or not approved or len(approved) > 240:
            raise ProtocolError("invalid reply segment")
        async with AsyncExitStack() as resources:
            async with asyncio.timeout(limits.io):
                frames = await resources.enter_async_context(providers.synthesize(approved, PLAYBACK_RATE))
            await channel.segment_started(count)
            samples = 0
            while True:
                async with asyncio.timeout(limits.io):
                    frame = await anext(frames, None)
                    if frame is None:
                        break
                    frame_samples, extra_byte = divmod(len(frame), 2)
                    samples += frame_samples
                    if extra_byte or not frame_samples or samples > PLAYBACK_RATE * 10:
                        raise ProtocolError("invalid synthesized audio")
                    await channel.audio(frame)
            if samples == 0:
                raise ProtocolError("empty synthesized audio")
            await channel.segment_ended(count, samples)
