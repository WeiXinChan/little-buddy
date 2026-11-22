import asyncio
import unittest
from contextlib import asynccontextmanager

from backend.voice import Audio, End, Limits, ProtocolError, run_turn


async def values(*items):
    for item in items:
        yield item


class Fake:
    def __init__(self):
        self.trace = []
        self.events = asyncio.Queue()
        self.waiting = asyncio.Event()

    @asynccontextmanager
    async def recognize(self, rate):
        self.trace.append(("open", rate))
        try:
            yield self
        finally:
            self.trace.append("closed")

    async def ready(self):
        self.trace.append("ready")

    async def receive(self):
        self.waiting.set()
        return await self.events.get()

    async def write(self, pcm):
        self.trace.append(("write", pcm))

    async def finish(self):
        self.trace.append("finish")
        return "你好"

    def input(self, transcript):
        return transcript

    def segment(self, text):
        return "批准的短句"

    @asynccontextmanager
    async def answer(self, transcript):
        self.trace.append(("answer", transcript))
        yield values("第一段", "第二段")

    @asynccontextmanager
    async def synthesize(self, text, rate):
        self.trace.append(("tts", text, rate))
        yield values(b"\x00\x00", b"\x01\x00")

    async def segment_started(self, number):
        self.trace.append(("start", number))

    async def audio(self, frame):
        self.trace.append(("audio", frame))

    async def segment_ended(self, number, samples):
        self.trace.append(("end", number, samples))

    async def reply_ended(self, count):
        self.trace.append(("reply", count))


class VoiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_preserves_order_and_filters_before_tts(self):
        fake = Fake()
        for event in (Audio(0, b"\x00\x00"), Audio(1, b"\x01\x00"), End(2)):
            fake.events.put_nowait(event)
        await run_turn(fake, fake, fake)
        self.assertEqual(fake.trace[:7], [
            ("open", 16000), "ready", ("write", b"\x00\x00"),
            ("write", b"\x01\x00"), "finish", "closed", ("answer", "你好"),
        ])
        self.assertEqual(fake.trace[7:12], [
            ("tts", "批准的短句", 24000), ("start", 1), ("audio", b"\x00\x00"),
            ("audio", b"\x01\x00"), ("end", 1, 2),
        ])
        self.assertEqual(fake.trace[-2:], [("end", 2, 2), ("reply", 2)])

    async def test_bad_position_and_empty_end_never_reach_model(self):
        for event in (Audio(1, b"\x00\x00"), Audio(0, b"\x00"), End(0)):
            with self.subTest(event=event):
                fake = Fake()
                fake.events.put_nowait(event)
                with self.assertRaises(ProtocolError):
                    await run_turn(fake, fake, fake)
                self.assertEqual(fake.trace, [("open", 16000), "ready", "closed"])

    async def test_cancel_closes_recognition(self):
        fake = Fake()
        task = asyncio.create_task(run_turn(fake, fake, fake))
        await fake.waiting.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(fake.trace, [("open", 16000), "ready", "closed"])

    async def test_stalled_audio_closes_recognition(self):
        fake = Fake()
        with self.assertRaises(TimeoutError):
            await run_turn(fake, fake, fake, Limits(io=0.01))
        self.assertEqual(fake.trace, [("open", 16000), "ready", "closed"])

    async def test_rejected_segment_never_reaches_synthesis(self):
        fake = Fake()
        fake.events.put_nowait(Audio(0, b"\x00\x00"))
        fake.events.put_nowait(End(1))

        class Reject(Fake):
            def segment(self, text):
                return None

        with self.assertRaises(ProtocolError):
            await run_turn(fake, fake, Reject())
        self.assertEqual(fake.trace[-1], ("answer", "你好"))

    async def test_second_tts_initialization_uses_progress_deadline_and_cleans_up(self):
        class Stalled(Fake):
            @asynccontextmanager
            async def synthesize(self, text, rate):
                if ("end", 1, 2) not in self.trace:
                    yield values(b"\x00\x00", b"\x01\x00")
                    return
                try:
                    await asyncio.Future()
                    yield
                finally:
                    self.trace.append("second tts closed")

        fake = Stalled()
        fake.events.put_nowait(Audio(0, b"\x00\x00"))
        fake.events.put_nowait(End(1))
        task = asyncio.create_task(run_turn(fake, fake, fake, Limits(io=0.02, turn=5)))
        try:
            done, _ = await asyncio.wait({task}, timeout=0.5)
            self.assertEqual(done, {task})
            with self.assertRaises(TimeoutError):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(fake.trace[-2:], [("end", 1, 2), "second tts closed"])
