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

    async def test_llm_and_tts_setup_share_the_deadline_after_segment_end(self):
        class SlowNextSegment(Fake):
            @asynccontextmanager
            async def answer(self, transcript):
                async def parts():
                    yield "第一段"
                    await asyncio.sleep(0.06)
                    self.trace.append("second text")
                    yield "第二段"
                yield parts()

            @asynccontextmanager
            async def synthesize(self, text, rate):
                if ("end", 1, 1) in self.trace:
                    try:
                        await asyncio.sleep(0.06)
                    finally:
                        self.trace.append("second setup exited")
                yield values(b"\x00\x00")

        fake = SlowNextSegment()
        fake.events.put_nowait(Audio(0, b"\x00\x00"))
        fake.events.put_nowait(End(1))
        with self.assertRaises(TimeoutError):
            await run_turn(fake, fake, fake, Limits(io=0.1, turn=2))
        self.assertEqual(fake.trace[-3:], [("end", 1, 1), "second text", "second setup exited"])

    async def test_second_tts_setup_and_first_pcm_share_progress_deadline(self):
        class SlowAudio(Fake):
            @asynccontextmanager
            async def synthesize(self, text, rate):
                if ("end", 1, 1) not in self.trace:
                    yield values(b"\x00\x00")
                    return

                async def delayed_audio():
                    self.trace.append("waiting for first PCM")
                    await asyncio.sleep(0.07)
                    yield b"\x01\x00"

                try:
                    await asyncio.sleep(0.07)
                    yield delayed_audio()
                finally:
                    self.trace.append("second tts closed")

        fake = SlowAudio()
        fake.events.put_nowait(Audio(0, b"\x00\x00"))
        fake.events.put_nowait(End(1))
        with self.assertRaises(TimeoutError):
            await run_turn(fake, fake, fake, Limits(io=0.1, turn=2))
        self.assertEqual(fake.trace[-4:],
                         [("end", 1, 1), ("start", 2), "waiting for first PCM", "second tts closed"])

    async def test_reply_control_backpressure_cannot_wait_for_turn_deadline(self):
        class Backpressure(Fake):
            async def segment_ended(self, number, samples):
                if self.block == "segment.end":
                    await self.wait_for_send()
                await super().segment_ended(number, samples)

            async def reply_ended(self, count):
                if self.block == "reply.end":
                    await self.wait_for_send()
                await super().reply_ended(count)

            async def wait_for_send(self):
                self.trace.append("send blocked")
                try:
                    await asyncio.Future()
                finally:
                    self.trace.append("send cancelled")

        for frame in ("segment.end", "reply.end"):
            with self.subTest(frame=frame):
                fake = Backpressure()
                fake.block = frame
                fake.events.put_nowait(Audio(0, b"\x00\x00"))
                fake.events.put_nowait(End(1))
                task = asyncio.create_task(run_turn(fake, fake, fake, Limits(io=0.04, turn=5)))
                try:
                    done, _ = await asyncio.wait({task}, timeout=0.5)
                    self.assertEqual(done, {task})
                    with self.assertRaises(TimeoutError):
                        await task
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self.assertEqual(fake.trace[-2:], ["send blocked", "send cancelled"])
                self.assertNotIn(("reply", 2), fake.trace)

    async def test_llm_read_ahead_overlaps_tts_and_preserves_playback_order(self):
        first_synthesis = asyncio.Event()
        later_text_read = asyncio.Event()

        class Overlap(Fake):
            @asynccontextmanager
            async def answer(self, transcript):
                async def parts():
                    yield "first"
                    await first_synthesis.wait()
                    later_text_read.set()
                    yield "second"
                yield parts()

            def segment(self, text):
                return text

            @asynccontextmanager
            async def synthesize(self, text, rate):
                if text == "first":
                    first_synthesis.set()
                    await later_text_read.wait()
                yield values(b"\x01\x00" if text == "first" else b"\x02\x00")

        fake = Overlap()
        fake.events.put_nowait(Audio(0, b"\x00\x00"))
        fake.events.put_nowait(End(1))
        await run_turn(fake, fake, fake, Limits(io=0.5, turn=2))
        self.assertEqual(fake.trace[-7:], [
            ("start", 1), ("audio", b"\x01\x00"), ("end", 1, 1),
            ("start", 2), ("audio", b"\x02\x00"), ("end", 2, 1), ("reply", 2),
        ])
