import asyncio
from contextlib import asynccontextmanager
import json
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from backend.animal.cloud import game_server
from backend.animal.private_fixture import fixture_server
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
                       additional_headers={"Authorization": f"Bearer {token or self.token}"},
                       ping_interval=2, ping_timeout=2, close_timeout=0.5)

    async def receive(self, ws, event):
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        self.assertEqual(message["event"], event)
        return message

    async def start(self, ws, conversation=False):
        await ws.send(json.dumps(dict(event="session.start", v=1, catalog=CATALOG_VERSION, conversation=conversation,
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

    async def test_reveal_ack_during_later_tts_or_asr_cleanup(self):
        for phase in ("tts", "asr_cleanup"):
            with self.subTest(phase=phase):
                blocked = asyncio.Event()
                release = asyncio.Event()

                class Delayed(SpeechFixture):
                    @asynccontextmanager
                    async def recognize(self, sample_rate):
                        async with super().recognize(sample_rate) as asr:
                            yield asr
                        if phase == "asr_cleanup":
                            blocked.set()
                            await release.wait()

                    @asynccontextmanager
                    async def synthesize(self, segment, sample_rate):
                        if phase == "tts" and len(self.spoken) == 2:
                            blocked.set()
                            await release.wait()
                        async with super().synthesize(segment, sample_rate) as result:
                            yield result

                demo = Delayed(["告诉我答案"])
                async with game_server(0, self.tls, self.token, demo, seed=0, report=lambda _: None) as server:
                    async with self.open(server) as ws:
                        await self.start(ws)
                        first = await self.reply(ws)
                        await self.speech(ws, first)
                        reply = await self.receive(ws, "reply")
                        self.assertTrue(reply["segments"][0]["image_id"])
                        key = reply["key"]

                        async def drain(number):
                            self.assertEqual((await self.receive(ws, "segment.start"))["number"], number)
                            while isinstance(frame := await ws.recv(), bytes):
                                pass
                            self.assertEqual(json.loads(frame)["event"], "segment.end")

                        await drain(1)
                        if phase == "asr_cleanup":
                            await drain(2)
                            self.assertEqual((await self.receive(ws, "reply.end"))["count"], 2)
                        await asyncio.wait_for(blocked.wait(), 1)
                        try:
                            for _ in range(2):
                                await self.send(ws, "playback.segment_completed", key, number=1)
                                committed = await asyncio.wait_for(
                                    self.receive(ws, "playback.segment_committed"), 0.6)
                                self.assertEqual(committed["number"], 1)
                            with self.assertRaises(TimeoutError):
                                await asyncio.wait_for(ws.recv(), 0.05)
                            if phase == "tts":
                                release.set()
                                await drain(2)
                                await self.receive(ws, "reply.end")
                            await self.send(ws, "playback.segment_completed", key, number=2)
                            await self.receive(ws, "playback.segment_committed")
                            receipt = await self.receive(ws, "turn.committed")
                            self.assertEqual((receipt["completed"], receipt["next_action"]), (1, "advance"))
                            await self.send(ws, "turn.advance", key)
                            if phase == "asr_cleanup":
                                with self.assertRaises(TimeoutError):
                                    await asyncio.wait_for(ws.recv(), 0.05)
                            release.set()
                            self.assertEqual((await self.reply(ws))["completed"], 1)
                        finally:
                            release.set()


    async def test_conversation_context_switch_and_silent_exit(self):
        contexts = []

        class ChatFixture(SpeechFixture):
            @asynccontextmanager
            async def answer(self, transcript, *, heard):
                contexts.append(heard)

                async def sentences():
                    yield "猫咪会喵喵叫。"
                    yield "它喜欢晒太阳。"
                yield sentences()

        demo = ChatFixture(["告诉我答案", "我想聊天", "聊小猫", "它爱做什么", "玩猜动物", "我想聊天"])
        logs = []
        async with game_server(0, self.tls, self.token, demo, seed=0, report=logs.append) as server:
            async with self.open(server) as ws:
                await self.start(ws, conversation=True)
                initial = await self.reply(ws)
                await self.speech(ws, initial)
                reveal = await self.reply(ws, reveal=True)
                await self.send(ws, "turn.advance", reveal["key"])
                game = await self.reply(ws)
                self.assertEqual(game["completed"], 1)
                await self.speech(ws, game)
                chat = await self.reply(ws)
                self.assertEqual((chat["mode"], chat["completed"]), ("chat", 0))
                await self.send(ws, "turn.start", game["key"], listen_id=game["listen_id"])
                await self.send(ws, "playback.segment_completed", game["key"], number=1)
                await self.speech(ws, chat)
                first = await self.reply(ws)
                await self.speech(ws, first)
                second = await self.reply(ws)
                await self.speech(ws, second)
                fresh = await self.reply(ws)
                self.assertEqual((fresh["mode"], fresh["completed"]), ("game", 0))
                await self.speech(ws, fresh)
                current = await self.reply(ws)
                for expected in ("listen", "end"):
                    await self.send(ws, "listen.silence", current["key"], listen_id=current["listen_id"])
                    current = await self.reply(ws)
                    self.assertEqual(current["next_action"], expected)
                self.assertEqual((current["count"], current["mode"]), (0, "chat"))
        self.assertEqual(contexts, [
            ("好呀，你想聊什么？",),
            ("好呀，你想聊什么？", "猫咪会喵喵叫。", "它喜欢晒太阳。"),
        ])
        self.assertEqual(demo.requests, 6)
        self.assertTrue(any("reason=silence asr=6 " in line and "llm=2" in line for line in logs))
        self.assertFalse(any("小猫" in line for line in logs))

    async def test_conversation_input_output_gate_and_usage_cap(self):
        for case in ("input", "output", "private", "limit"):
            with self.subTest(case=case):
                user_text = {"input": "我肚子不舒服", "private": "我叫小花", "output": "聊小猫",
                             "limit": "聊小猫"}[case]
                model_calls = []

                class ChatFixture(SpeechFixture):
                    @asynccontextmanager
                    async def answer(self, transcript, *, heard):
                        model_calls.append(transcript)

                        async def sentences():
                            yield "猫咪会喵喵叫。"
                            if case == "output":
                                yield "拿刀玩吧。"
                        yield sentences()

                demo = ChatFixture(["我想聊天", user_text, "再见"])
                with patch("backend.animal.cloud.MAX_LLM", 1 if case == "limit" else 12):
                    async with game_server(0, self.tls, self.token, demo, seed=0, report=lambda _: None) as server:
                        async with self.open(server) as ws:
                            await self.start(ws, conversation=True)
                            await self.speech(ws, await self.reply(ws))
                            chat = await self.reply(ws)
                            await self.speech(ws, chat)
                            outcome = await self.reply(ws)
                            if case == "private":
                                self.assertEqual(outcome["next_action"], "listen")
                                await self.speech(ws, outcome)
                                outcome = await self.reply(ws)
                            self.assertEqual(outcome["next_action"], "end")
                expected = {"input": "请找身边的大人来帮忙。", "output": "请找身边的大人来帮忙。",
                            "private": "好，下次见！", "limit": "今天先聊到这里吧。"}[case]
                self.assertEqual(demo.spoken[-1], expected)
                self.assertNotIn("猫咪会喵喵叫。", demo.spoken)
                self.assertEqual(len(model_calls), int(case in {"output", "limit"}))

    async def test_private_fixture_faults_and_fresh_connection(self):
        for scenario in ("asr", "first-pcm", "between", "blackhole", "disconnect"):
            with self.subTest(scenario=scenario):
                async with fixture_server(0, self.tls, self.token, scenario) as server:
                    async with self.open(server) as ws:
                        await self.start(ws)
                        first = await self.reply(ws)
                        await self.speech(ws, first)
                        if scenario != "asr":
                            response = await self.receive(ws, "reply")
                            await self.receive(ws, "segment.start")
                            if scenario == "first-pcm":
                                with self.assertRaises(TimeoutError):
                                    await asyncio.wait_for(ws.recv(), 0.15)
                            else:
                                while isinstance(frame := await ws.recv(), bytes):
                                    pass
                                self.assertEqual(json.loads(frame)["event"], "segment.end")
                                await self.send(ws, "playback.segment_completed", response["key"], number=1)
                                controls = [json.loads(await asyncio.wait_for(ws.recv(), 1)) for _ in range(2)]
                                self.assertEqual({(item["event"], item["number"]) for item in controls},
                                                 {("playback.segment_committed", 1), ("segment.start", 2)})
                        if scenario in {"blackhole", "disconnect"}:
                            with self.assertRaises(ConnectionClosed):
                                await asyncio.wait_for(ws.recv(), 12)
                        elif scenario == "asr":
                            with self.assertRaises(TimeoutError):
                                await asyncio.wait_for(ws.recv(), 0.15)
                    # The old TCP tunnel can take one scheduler cycle to close
                    # before its server stops returning 503 to new clients.
                    await asyncio.sleep(0.1)
                    async with self.open(server) as ws:
                        await self.start(ws)
                        fresh = await self.reply(ws)
                        self.assertEqual(fresh["completed"], 0)
                        self.assertNotEqual(first["key"]["session_id"], fresh["key"]["session_id"])
