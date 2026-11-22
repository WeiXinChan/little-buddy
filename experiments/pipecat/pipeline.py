"""Per-WebSocket Pipecat pipeline for the private greeting experiment."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from unittest.mock import patch

from loguru import logger

# Pipecat 0.0.105 tries to download tokenizer data on import. The existing
# DashScope adapter splits sentences, so the experiment never uses that data.
logger.disable("pipecat")
with patch("nltk.download", return_value=False):
    from pipecat.frames.frames import DataFrame, EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.utils.asyncio.task_manager import TaskManager

from backend.demo import main
from backend.timing import mark, observer
from backend.voice import GreetingMismatch, Limits, ProviderError, deliver, join_closures, prefetch_segments, recognize


@dataclass
class Capture(DataFrame):
    pass


@dataclass
class Transcript(DataFrame):
    approved: str = field(repr=False)


@dataclass
class Reply(DataFrame):
    segments: AsyncIterator[str]
    deadline: float


class Stage(FrameProcessor):
    def __init__(self, frame_type, handle, *, direct=True):
        # Couple each frame to downstream consumption. The existing segment
        # prefetch is the only read-ahead queue and owns its producer.
        super().__init__(enable_direct_mode=direct)
        self.frame_type = frame_type
        self.handle = handle

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, self.frame_type):
            await self.handle(frame, lambda output: self.push_frame(output, direction))
        else:
            await self.push_frame(frame, direction)


class TurnPipelineTask(PipelineTask):
    """Own the pinned Pipecat 0.0.105 task lifecycle for one private turn."""

    def __init__(self, pipeline, **kwargs):
        self.workers = TaskManager()
        super().__init__(pipeline, task_manager=self.workers, **kwargs)
        self.cleaned = False
        self.provider_work = None

    async def _cleanup(self, cleanup_pipeline):
        await super()._cleanup(cleanup_pipeline)
        self.cleaned = True

    async def run(self, params):
        # The upstream run() cancellation handler sends a CancelFrame via the
        # same queue as EndFrame. Keep normal frame processing, but unwind the
        # owned tasks directly if their queue stops making progress.
        try:
            await self._setup(params)
            await self._create_tasks()
            await self._wait_for_pipeline_finished()
        finally:
            workers = tuple(self.workers.current_tasks())
            provider = self.provider_work
            owned = workers if provider is None else (*workers, provider)
            for worker in owned:
                if not worker.done() and not worker.cancelling():
                    worker.cancel()
            try:
                await asyncio.gather(*workers, return_exceptions=True)
                if not self.cleaned:
                    await self._cleanup(True)
            finally:
                # Provider contexts keep their I/O deadlines and shielded
                # closure joins independently of Pipecat frame processing.
                if provider is not None:
                    await asyncio.gather(provider, return_exceptions=True)
            self._finished = True


async def abort_runner(running):
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)


async def run_pipeline(channel, providers, policy, limits=Limits(), *, timing=None):
    loop = asyncio.get_running_loop()
    turn_deadline = loop.time() + limits.turn
    result = loop.create_future()
    failure = None
    delivered = None

    async def capture(frame, emit):
        try:
            async with recognize(channel, providers, limits) as (transcript, asr_cleanup):
                approved = policy.input(transcript)
                if not approved:
                    raise GreetingMismatch()
                await emit(Transcript(approved))
                if failure is not None:
                    raise failure
                _, deadline = delivered
                async with asyncio.timeout_at(deadline):
                    await asyncio.shield(asr_cleanup)
        except Exception as error:
            result.set_result(error)
        else:
            result.set_result(None)

    async def answer(frame, emit):
        deadline = loop.time() + limits.io
        mark("llm_request")
        async with AsyncExitStack() as resources:
            async with asyncio.timeout_at(deadline):
                segments = await resources.enter_async_context(providers.answer(frame.approved))
            mark("llm_headers")
            async with prefetch_segments(segments) as buffered:
                await emit(Reply(buffered, deadline))

    async def speak(frame, emit):
        nonlocal delivered
        delivered = await deliver(channel, providers, policy, frame.segments, limits, frame.deadline)
        if delivered[0] == 0:
            raise ProviderError("empty reply")

    def preserve_error(handle):
        async def process(frame, emit):
            nonlocal failure
            try:
                await handle(frame, emit)
            except Exception as error:
                # Pipecat consumes processor exceptions. Preserve the original
                # type for the existing WebSocket close-code mapping.
                failure = error
        return process

    async def dispatch_capture(frame, emit):
        task.provider_work = asyncio.create_task(capture(frame, emit))
        await asyncio.shield(task.provider_work)

    pipeline = Pipeline([
        Stage(Capture, dispatch_capture, direct=False),
        Stage(Transcript, preserve_error(answer)),
        Stage(Reply, preserve_error(speak)),
    ])
    task = TurnPipelineTask(
        pipeline, params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
        idle_timeout_secs=None, enable_rtvi=False, enable_turn_tracking=False,
    )
    runner = PipelineRunner(handle_sigint=False, handle_sigterm=False)

    token = observer.set(timing)
    try:
        running = asyncio.create_task(runner.run(task))
        try:
            async with asyncio.timeout_at(turn_deadline):
                await task.queue_frame(Capture())
                ready, _ = await asyncio.wait((result, running), return_when=asyncio.FIRST_COMPLETED)
                if result not in ready:
                    running.result()
                    raise ProviderError("pipeline exited before reply")
                await task.queue_frame(EndFrame())
                await asyncio.shield(running)
                if (error := result.result()) is not None:
                    raise error
                count, deadline = delivered
                async with asyncio.timeout_at(deadline):
                    await channel.reply_ended(count)
                mark("reply_sent")
        finally:
            # The deadline stops the reply. Join the cancelled pipeline so
            # providers finish cleanup before the connection releases its slot.
            if not running.done():
                await join_closures([asyncio.create_task(abort_runner(running))])
    finally:
        observer.reset(token)


if __name__ == "__main__":
    asyncio.run(main(default_port=8444, turn_handler=run_pipeline, loopback_only=True))
