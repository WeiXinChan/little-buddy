import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close

from experiments.pipecat.ab import trial


READY = '{"v":1,"type":"turn.ready"}'
START_1 = '{"v":1,"type":"segment.start","number":1}'
END_1 = '{"v":1,"type":"segment.end","number":1,"samples":2}'
START_2 = '{"v":1,"type":"segment.start","number":2}'
END_2 = '{"v":1,"type":"segment.end","number":2,"samples":1}'
REPLY = '{"v":1,"type":"reply.end","count":2}'
FIRST = bytes.fromhex("01 02 00 00 00 00 00 00")
SECOND = bytes.fromhex("01 02 00 00 00 01 01 00")
NEXT = bytes.fromhex("01 02 00 00 00 00 00 ff")
VALID = (READY, START_1, FIRST, SECOND, END_1, START_2, NEXT, END_2, REPLY)


class ABTest(unittest.IsolatedAsyncioTestCase):
    async def probe(self, frames, close=1000):
        class Socket:
            def __init__(self):
                self.frames = iter(frames)

            async def recv(self):
                try:
                    return next(self.frames)
                except StopIteration:
                    terminal = Close(close, "private synthetic diagnostic")
                    error = ConnectionClosedOK if close in (1000, 1001) else ConnectionClosedError
                    raise error(terminal, terminal, True) from None

            async def send(self, message):
                pass

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield Socket()

        with patch("experiments.pipecat.ab.connect", connect):
            return await trial(b"", "fake-token", None, "test-turn")

    async def test_two_ordered_segments_with_silence_chunk_and_normal_close(self):
        self.assertEqual(await self.probe(VALID), "ok")

    async def test_zero_sample_frames_cannot_pass_even_with_final_controls(self):
        frames = (READY, START_1, END_1.replace(":2}", ":0}"), START_2,
                  END_2.replace(":1}", ":0}"), REPLY)
        self.assertEqual(await self.probe(frames, 1011), "empty_pcm")
        silent = VALID[:3] + (SECOND[:-2] + b"\x00\x00",) + VALID[4:]
        self.assertEqual(await self.probe(silent), "empty_pcm")

    async def test_missing_duplicate_and_reordered_pcm_fail(self):
        for frames in (VALID[:2] + VALID[3:], VALID[:3] + VALID[2:],
                       VALID[:2] + (SECOND, FIRST) + VALID[4:]):
            self.assertEqual(await self.probe(frames), "invalid_pcm_frame")
        self.assertEqual(await self.probe(VALID[:3] + VALID[4:]), "invalid_segment_end")

    async def test_frame_version_direction_and_length(self):
        for frame in (b"\x02" + FIRST[1:], b"\x01\x01" + FIRST[2:], FIRST[:-1], FIRST[:6]):
            self.assertEqual(await self.probe(VALID[:2] + (frame,) + VALID[3:]), "invalid_pcm_frame")

    async def test_ready_and_control_order(self):
        self.assertEqual(await self.probe((READY.replace(":1,", ":true,"),) + VALID[1:]), "invalid_ready")
        self.assertEqual(await self.probe((READY, START_2) + VALID[2:]), "invalid_segment_start")
        self.assertEqual(await self.probe(VALID[:5] + (START_1,) + VALID[6:]), "invalid_segment_start")
        self.assertEqual(await self.probe(VALID[:4] + (END_2,) + VALID[5:]), "invalid_segment_end")
        self.assertEqual(await self.probe(VALID[:-1] + (REPLY.replace(":2}", ":1}"),)), "invalid_reply_end")

    async def test_missing_terminal_abnormal_close_and_trailing_data(self):
        self.assertEqual(await self.probe(VALID[:-1]), "closed_before_reply")
        for code in (1001, 1011):
            self.assertEqual(await self.probe(VALID, code), f"ws_{code}")
        self.assertEqual(await self.probe((READY,), 4402), "ws_4402")
        self.assertEqual(await self.probe(VALID + (REPLY,)), "data_after_reply")
