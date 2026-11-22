import asyncio
from contextlib import asynccontextmanager
import json
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from backend.animal.cloud import game_server
from backend.animal.rules import CARDS, CATALOG_VERSION
from backend.demo import Demo
from backend.wire import HEADER


class SpeechFixture(Demo):
    def __init__(self, answers):
        self.answers = iter(answers)
        self.requests = 0
        self.spoken = []

    @asynccontextmanager
    async def recognize(self, sample_rate):
        self.requests += 1
        yield self

    async def finish(self):
        return next(self.answers)

    @asynccontextmanager
    async def synthesize(self, segment, sample_rate):
        self.spoken.append(segment)
        async with super().synthesize(segment, sample_rate) as frames:
            yield frames


class CloudGameTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cert, key = (Path(directory.name) / name for name in ("cert", "key"))
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-days", "1", "-keyout", key, "-out", cert,
        ], check=True, capture_output=True)
        cls.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.tls.load_cert_chain(cert, key)
        cls.trust = ssl.create_default_context(cafile=str(cert))
        cls.token = "test" * 8

    def open(self, server, token=None):
        port = server.sockets[0].getsockname()[1]
        return connect(f"wss://localhost:{port}/v1/animal", ssl=self.trust,
                       additional_headers={"Authorization": f"Bearer {token or self.token}"})

    async def receive(self, ws, event):
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        self.assertEqual(message["event"], event)
        return message

    async def start(self, ws):
        await ws.send(json.dumps(dict(event="session.start", v=1, catalog=CATALOG_VERSION,
                                      images=[card.image_id for card in CARDS])))

    async def reply(self, ws, reveal=False):
        reply = await self.receive(ws, "reply")
        segments = reply["segments"]
        self.assertEqual(any(item["image_id"] for item in segments), reveal)
        self.assertTrue(all(set(item) == {"image_id"} for item in segments))
        key = reply["key"]
        for number in range(1, len(segments) + 1):
            self.assertEqual((await self.receive(ws, "segment.start"))["number"], number)
            position = 0
            while isinstance(frame := await asyncio.wait_for(ws.recv(), 3), bytes):
                self.assertEqual(HEADER.unpack_from(frame), (1, 2, position))
                position += (len(frame) - HEADER.size) // 2
            end = json.loads(frame)
            self.assertEqual((end["key"], end["number"], end["samples"]), (key, number, position))
        self.assertEqual((await self.receive(ws, "reply.end"))["count"], len(segments))
        if len(segments) > 1:
            await self.send(ws, "playback.segment_completed", key, number=len(segments))
        for number in range(1, len(segments) + 1):
            await self.send(ws, "playback.segment_completed", key, number=number)
            self.assertEqual((await self.receive(ws, "playback.segment_committed"))["number"], number)
            if number < len(segments):
                await self.send(ws, "playback.segment_completed", key, number=number)
                self.assertEqual((await self.receive(ws, "playback.segment_committed"))["number"], number)
        return await self.receive(ws, "turn.committed")

    async def send(self, ws, kind, key, **fields):
        await ws.send(json.dumps(dict(event=kind, key=key, **fields)))

    async def speech(self, ws, receipt):
        key = receipt["key"]
        await self.send(ws, "turn.start", key, listen_id=receipt["listen_id"])
        self.assertEqual((await self.receive(ws, "turn.ready"))["key"], key)
        await ws.send(HEADER.pack(1, 1, 0) + b"\0\0" * 320)
        await ws.send(json.dumps({"v": 1, "type": "turn.end", "samples": 320}))

    async def test_three_reveals_then_restart(self):
        demo = SpeechFixture(["告诉我答案"] * 3 + ["是"])
        logs = []
        async with game_server(0, self.tls, self.token, demo, seed=0, report=logs.append) as server:
            with self.assertRaises(InvalidStatus):
                await self.open(server, "wrong")
            async with self.open(server) as ws:
                await self.start(ws)
                receipt = await self.reply(ws)
                for completed in range(1, 4):
                    await self.speech(ws, receipt)
                    receipt = await self.reply(ws, reveal=True)
                    self.assertEqual(receipt["completed"], completed)
                    self.assertEqual(receipt["next_action"], "advance")
                    await self.send(ws, "turn.advance", receipt["key"])
                    receipt = await self.reply(ws)
                await self.speech(ws, receipt)
                receipt = await self.reply(ws)
                self.assertEqual((receipt["completed"], receipt["next_action"]), (0, "listen"))
        self.assertEqual(demo.requests, 4)
        self.assertIn("animal_result reason=complete completed=3", logs)
        self.assertTrue(any("asr=4 asr_samples=1280" in line and "llm=0" in line for line in logs))

    async def test_silence_consumes_permit_without_asr_and_stale_key_is_ignored(self):
        demo = SpeechFixture([])
        async with game_server(0, self.tls, self.token, demo, seed=0, report=lambda _: None) as server:
            async with self.open(server) as ws:
                await self.start(ws)
                first = await self.reply(ws)
                await self.send(ws, "listen.silence", first["key"], listen_id=first["listen_id"])
                await self.send(ws, "turn.start", first["key"], listen_id=first["listen_id"])
                second = await self.reply(ws)
                await self.send(ws, "listen.silence", second["key"], listen_id=second["listen_id"])
                last = await self.reply(ws)
                self.assertEqual((last["completed"], last["next_action"]), (0, "end"))
        self.assertEqual(demo.requests, 0)

    async def test_reject_then_hint_wrong_and_bare_yes_do_not_reveal(self):
        demo = SpeechFixture(["老虎", "熊", "不要", "给我提示", "狮子", "是"])
        async with game_server(0, self.tls, self.token, demo, seed=0, report=lambda _: None) as server:
            async with self.open(server) as ws:
                await self.start(ws)
                receipt = await self.reply(ws)
                for _ in range(6):
                    await self.speech(ws, receipt)
                    receipt = await self.reply(ws)
                    self.assertEqual((receipt["completed"], receipt["next_action"]), (0, "listen"))
        self.assertEqual(demo.requests, 6)
