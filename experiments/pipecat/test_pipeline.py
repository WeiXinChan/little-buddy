import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from websockets.exceptions import InvalidStatus

from backend.demo import Demo
from backend.server import voice_server
from backend.tests import test_server, test_voice
from experiments.pipecat.pipeline import run_pipeline


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
    async def asyncSetUp(self):
        self.enterContext(patch.object(test_voice, "run_turn", run_pipeline))


if __name__ == "__main__":
    unittest.main()
