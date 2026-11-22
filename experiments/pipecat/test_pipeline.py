import asyncio
import unittest
from uuid import uuid4
from contextlib import asynccontextmanager
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed, InvalidStatus

from backend.demo import Demo
from backend.server import voice_server
from backend.tests import test_server, test_voice
from backend.voice import Audio, End, Limits
from experiments.pipecat.ab import trial
from experiments.pipecat.pipeline import EndFrame, PipelineRunner, PipelineTask, Stage, run_pipeline


def pipeline_server(*args, **kwargs):
    return voice_server(*args, **kwargs, turn_handler=run_pipeline)


class BlockingPhase(Demo):
    def __init__(self, phase):
        self.phase = phase
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.closed = asyncio.Event()
        self.active = 0

    async def stall_once(self, phase):
        if self.phase != phase or self.entered.is_set():
            return
        self.entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            # Simulate a late provider error during an explicit stop.
            self.cancelled.set()
            raise RuntimeError("synthetic late error") from None

    async def finish(self):
        await self.stall_once("asr")
        return await super().finish()

    @asynccontextmanager
    async def recognize(self, rate):
        self.active += 1
        try:
            yield self
        finally:
            self.active -= 1
            if self.entered.is_set():
                self.closed.set()

    @asynccontextmanager
    async def answer(self, transcript):
        self.active += 1
        try:
            await self.stall_once("llm")
            async with super().answer(transcript) as stream:
                yield stream
        finally:
            self.active -= 1

    @asynccontextmanager
    async def synthesize(self, segment, rate):
        self.active += 1
        try:
            async with super().synthesize(segment, rate) as stream:
                async def frames():
                    async for frame in stream:
                        yield frame
                        if self.phase == "tts_pcm" and not self.entered.is_set():
                            try:
                                await self.stall_once("tts_pcm")
                            except RuntimeError:
                                # A provider may yield PCM even after cancellation.
                                yield b"\xff\x7f" * 480
                                return
                        await self.stall_once("tts")
                yield frames()
        finally:
            self.active -= 1


class PipelineTest(test_server.ServerTest):
    async def asyncSetUp(self):
        self.enterContext(patch.object(test_server, "voice_server", pipeline_server))

    async def test_ab_client_accepts_real_wss_and_pcm_from_both_fake_serving_paths(self):
        for serve in (voice_server, pipeline_server):
            demo = Demo()
            async with serve("127.0.0.1", 0, self.tls, test_server.TOKEN, demo, demo) as server:
                port = server.sockets[0].getsockname()[1]
                with patch("experiments.pipecat.ab.PORT", port):
                    async with asyncio.timeout(3):
                        self.assertEqual(await trial(b"\x01\x00" * 320, test_server.TOKEN,
                                                     self.trust, str(uuid4())), "ok")

    async def test_blocked_end_frame_times_out_and_releases_connection_slot(self):
        process = Stage.process_frame
        blocked = asyncio.Event()
        exited = asyncio.Event()
        demo = Demo()

        async def block_first_end(stage, frame, direction):
            if isinstance(frame, EndFrame) and not blocked.is_set():
                blocked.set()
                try:
                    await asyncio.Future()
                finally:
                    exited.set()
            await process(stage, frame, direction)

        async def short_turn(channel, providers, policy, **kwargs):
            await run_pipeline(channel, providers, policy, Limits(turn=0.3, io=2), **kwargs)

        with patch.object(Stage, "process_frame", block_first_end):
            async with voice_server("127.0.0.1", 0, self.tls, test_server.TOKEN,
                                    demo, demo, turn_handler=short_turn) as server:
                async with asyncio.timeout(1):
                    async with self.open(server) as socket:
                        await self.upload(socket)
                        await blocked.wait()
                        with self.assertRaises(ConnectionClosed) as closed:
                            while True:
                                self.assertNotIn("reply.end", str(await socket.recv()))
                        self.assertEqual(closed.exception.rcvd.code, 1013)
                        self.assertTrue(exited.is_set())
                    port = server.sockets[0].getsockname()[1]
                    with patch("experiments.pipecat.ab.PORT", port):
                        self.assertEqual(await trial(b"\x01\x00" * 320, test_server.TOKEN,
                                                     self.trust, str(uuid4())), "ok")

    async def test_cancel_at_every_provider_and_reopen(self):
        for phase in ("asr", "llm", "tts", "tts_pcm"):
            with self.subTest(phase=phase):
                demo = BlockingPhase(phase)
                async with pipeline_server("127.0.0.1", 0, self.tls, test_server.TOKEN, demo, demo) as server:
                    async with asyncio.timeout(3):
                        async with self.open(server) as socket:
                            await self.upload(socket)
                            await demo.entered.wait()
                            await socket.close(4403)
                        while True:
                            try:
                                async with self.open(server) as replacement:
                                    await self.upload(replacement)
                                    controls = []
                                    pcm_bytes = 0
                                    async for event in replacement:
                                        if isinstance(event, str):
                                            controls.append(event)
                                        else:
                                            pcm_bytes += len(event) - test_server.HEADER.size
                                    self.assertEqual(len(controls), 5)
                                    self.assertEqual(pcm_bytes, 4800 * 2 * 2)
                                break
                            except InvalidStatus as error:
                                self.assertEqual(error.response.status_code, 503)
                                await asyncio.sleep(0.01)
                    self.assertTrue(demo.cancelled.is_set())
                    self.assertTrue(demo.closed.is_set())
                    self.assertEqual(demo.active, 0)


class PipelineVoiceTest(test_voice.VoiceTest):
    def prepared_turn(self, fake):
        fake.events.put_nowait(Audio(0, b"\x00\x00"))
        fake.events.put_nowait(End(1))
        return run_pipeline(fake, fake, fake, Limits(turn=0.3, io=2))

    async def test_turn_deadline_cancels_slow_reply_end(self):
        class SlowReply(test_voice.Fake):
            async def reply_ended(self, count):
                self.trace.append("reply attempted")
                await asyncio.sleep(0.6)
                await super().reply_ended(count)

        fake = SlowReply()
        with self.assertRaises(TimeoutError):
            await self.prepared_turn(fake)
        self.assertIn(("end", 2, 2), fake.trace)
        self.assertIn("reply attempted", fake.trace)
        self.assertNotIn(("reply", 2), fake.trace)

    async def test_turn_deadline_covers_queueing_end_frame(self):
        queue = PipelineTask.queue_frame
        end_cancelled = asyncio.Event()

        async def queue_slow_end(task, frame, *args, **kwargs):
            if isinstance(frame, EndFrame):
                try:
                    await asyncio.sleep(0.6)
                finally:
                    end_cancelled.set()
            await queue(task, frame, *args, **kwargs)

        fake = test_voice.Fake()
        with patch.object(PipelineTask, "queue_frame", queue_slow_end):
            with self.assertRaises(TimeoutError):
                await self.prepared_turn(fake)
        self.assertTrue(end_cancelled.is_set())
        self.assertIn(("end", 2, 2), fake.trace)
        self.assertNotIn(("reply", 2), fake.trace)

    async def test_turn_deadline_cancels_delayed_runner_without_reply(self):
        run = PipelineRunner.run
        finishing = asyncio.Event()
        exited = asyncio.Event()

        async def delayed_runner(runner, task):
            await run(runner, task)
            finishing.set()
            try:
                await asyncio.Future()
            finally:
                exited.set()

        fake = test_voice.Fake()
        with patch.object(PipelineRunner, "run", delayed_runner):
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(self.prepared_turn(fake), 1)
        self.assertTrue(finishing.is_set())
        self.assertTrue(exited.is_set())
        self.assertNotIn(("reply", 2), fake.trace)

    async def test_repeated_cancel_during_timeout_waits_for_provider_cleanup(self):
        cleaning = asyncio.Event()
        release = asyncio.Event()
        closed = asyncio.Event()

        class SlowRecognition(test_voice.Fake):
            @asynccontextmanager
            async def recognize(self, rate):
                try:
                    yield self
                finally:
                    cleaning.set()
                    await release.wait()
                    closed.set()

            async def finish(self):
                await asyncio.Future()

        fake = SlowRecognition()
        turn = asyncio.create_task(self.prepared_turn(fake))
        try:
            await asyncio.wait_for(cleaning.wait(), 1)
            for _ in range(2):
                turn.cancel()
                await asyncio.sleep(0)
                self.assertFalse(turn.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(turn, 1)
            self.assertTrue(closed.is_set())
            self.assertNotIn(("reply", 2), fake.trace)
        finally:
            release.set()
            await asyncio.gather(turn, return_exceptions=True)

    async def asyncSetUp(self):
        self.enterContext(patch.object(test_voice, "run_turn", run_pipeline))


if __name__ == "__main__":
    unittest.main()
