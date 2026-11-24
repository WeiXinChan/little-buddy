import asyncio
from contextlib import asynccontextmanager
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import httpx

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from backend.animal import cloud
from backend.animal.cloud import game_server
from backend.animal.private_fixture import fixture_server
from backend.animal.rules import CARDS, CATALOG_VERSION
from backend.dashscope import DashScope
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
        cls.cert, cls.key = cert, key
        cls.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.tls.load_cert_chain(cert, key)
        cls.trust = ssl.create_default_context(cafile=str(cert))
        cls.token = "test" * 8

    def open(self, server, token=None, *, standalone=False):
        port = server.sockets[0].getsockname()[1]
        options = {"host": "127.0.0.1", "port": port} if standalone else {}
        authority = "localhost:19443" if standalone else f"localhost:{port}"
        return connect(f"wss://{authority}/v1/animal", ssl=self.trust,
                       additional_headers={"Authorization": f"Bearer {token or self.token}"},
                       **options,
                       ping_interval=2, ping_timeout=2, close_timeout=0.5)

    async def receive(self, ws, event):
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        self.assertEqual(message["event"], event)
        return message

    async def start(self, ws, conversation=False, wake=False):
        await ws.send(json.dumps(dict(event="session.start", v=1, catalog=CATALOG_VERSION, conversation=conversation, wake=wake,
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

    async def test_wake_has_silent_permit_and_routes_first_command(self):
        demo = SpeechFixture(["瓦力瓦力，玩猜动物"])
        async with game_server(0, self.tls, self.token, demo, seed=0, report=lambda _: None) as server:
            async with self.open(server) as ws:
                await self.start(ws, conversation=True, wake=True)
                permit = await self.reply(ws)
                self.assertEqual((permit["mode"], permit["next_action"]), ("chat", "listen"))
                self.assertEqual((demo.requests, demo.spoken), (0, []))
                await self.speech(ws, permit)
                game = await self.reply(ws)
                self.assertEqual((game["mode"], game["completed"]), ("game", 0))
        self.assertEqual(demo.requests, 1)

    async def test_wake_fixture_counts_ready_and_only_complete_pcm_seals(self):
        logs = []
        source = Path("app/src/androidTest/assets/wake/gap-120.pcm").read_bytes()
        pcm = source[44_800:]
        async with fixture_server(0, self.tls, self.token, "wake-revoke", report=logs.append) as server:
            for send_pcm in (False, True, True):
                async with self.open(server) as ws:
                    await self.start(ws, conversation=True, wake=True)
                    permit = await self.reply(ws)
                    self.assertEqual((permit["count"], permit["mode"], permit["next_action"]), (0, "chat", "listen"))
                    key = permit["key"]
                    await self.send(ws, "turn.start", key, listen_id=permit["listen_id"])
                    self.assertEqual((await self.receive(ws, "turn.ready"))["key"], key)
                    if send_pcm:
                        for offset in range(0, len(pcm), 640):
                            await ws.send(HEADER.pack(1, 1, offset // 2) + pcm[offset:offset + 640])
                        await ws.send(json.dumps({"v": 1, "type": "turn.end", "samples": len(pcm) // 2}))
                        self.assertEqual((await self.reply(ws))["mode"], "game")
                # Join backend teardown before the next single-device connection.
                for _ in range(100):
                    if sum(line.startswith("animal_usage ") for line in logs) == logs.count("wake_fixture_connection"):
                        break
                    await asyncio.sleep(0.01)

        for marker, count in (
            ("wake_fixture_connection", 3),
            ("animal_timing event=asr_ready ", 3),
            ("animal_timing event=capture_sealed ", 2),
            ("wake_fixture_first_pcm ", 2),
        ):
            self.assertEqual(sum(line.startswith(marker) for line in logs), count, marker)
        self.assertEqual([line for line in logs if line.startswith("wake_fixture_pcm ")],
                         ["wake_fixture_pcm turn=2 exact=1", "wake_fixture_pcm turn=3 exact=1"])

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
        requests = []

        def respond(request):
            requests.append(json.loads(request.content)["messages"])
            event = json.dumps({"choices": [{"delta": {"content": "猫咪会喵喵叫。它喜欢晒太阳。"}}]})
            return httpx.Response(200, text=f"data: {event}\n\ndata: [DONE]\n\n")

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(http.aclose)
        demo = SpeechFixture(["告诉我答案", "我想聊天", "聊小猫", "它爱做什么", "玩猜动物", "我想聊天", "聊小狗"])
        adapter = DashScope(http, workspace="workspace", region="cn-beijing", key="synthetic",
                            asr="asr", llm="llm", tts="tts", voice="voice")
        demo.answer = adapter.answer
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
                await self.speech(ws, current)
                current = await self.reply(ws)
                for expected in ("listen", "end"):
                    await self.send(ws, "listen.silence", current["key"], listen_id=current["listen_id"])
                    current = await self.reply(ws)
                    self.assertEqual(current["next_action"], expected)
                self.assertEqual((current["count"], current["mode"]), (0, "chat"))
        self.assertEqual([messages[1:] for messages in requests], [
            [{"role": "user", "content": "聊小猫"}],
            [{"role": "user", "content": "聊小猫"},
             {"role": "assistant", "content": "猫咪会喵喵叫。它喜欢晒太阳。"},
             {"role": "user", "content": "它爱做什么"}],
            [{"role": "user", "content": "聊小狗"}],
        ])
        self.assertEqual(demo.requests, 7)
        self.assertTrue(any("reason=silence asr=7 " in line and "llm=3" in line for line in logs))
        self.assertFalse(any("小猫" in line for line in logs))

    async def test_disconnect_after_partial_chat_reply_starts_fresh_history(self):
        contexts = []
        released = asyncio.Event()

        class ChatFixture(SpeechFixture):
            @asynccontextmanager
            async def answer(self, transcript, *, history):
                contexts.append((transcript, history))

                async def sentences():
                    yield "猫咪会喵喵叫。"
                    yield "它喜欢晒太阳。"
                yield sentences()

        def report(line):
            if line.startswith("animal_usage reason=disconnect"):
                released.set()

        demo = ChatFixture(["我想聊天", "聊小猫", "聊尾巴", "我想聊天", "聊小狗"])
        async with game_server(0, self.tls, self.token, demo, seed=0, report=report) as server:
            async with self.open(server) as ws:
                await self.start(ws, conversation=True)
                await self.speech(ws, await self.reply(ws))
                await self.speech(ws, await self.reply(ws))
                await self.speech(ws, await self.reply(ws))
                partial = await self.receive(ws, "reply")
                await self.receive(ws, "segment.start")
                while isinstance(frame := await asyncio.wait_for(ws.recv(), 3), bytes):
                    pass
                self.assertEqual(json.loads(frame)["event"], "segment.end")
                await self.send(ws, "playback.segment_completed", partial["key"], number=1)
                while True:
                    frame = await asyncio.wait_for(ws.recv(), 3)
                    if isinstance(frame, str) and json.loads(frame)["event"] == "playback.segment_committed":
                        break
            await asyncio.wait_for(released.wait(), 3)
            async with self.open(server) as ws:
                await self.start(ws, conversation=True)
                initial = await self.reply(ws)
                self.assertNotEqual(initial["key"]["session_id"], partial["key"]["session_id"])
                await self.send(ws, "playback.segment_completed", partial["key"], number=2)
                await self.speech(ws, initial)
                await self.speech(ws, await self.reply(ws))
                await self.reply(ws)
        self.assertEqual(contexts, [
            ("聊小猫", ()),
            ("聊尾巴", (("聊小猫", "猫咪会喵喵叫。它喜欢晒太阳。"),)),
            ("聊小狗", ()),
        ])

    async def test_conversation_input_output_gate_and_natural_exit(self):
        cases = (
            ("我肚子不舒服", None, "请找身边的大人来帮忙。"),
            ("我喘不上气", None, "请找身边的大人来帮忙。"),
            ("我没法呼吸", None, "请找身边的大人来帮忙。"),
            ("聊小猫", "拿刀玩吧。", "请找身边的大人来帮忙。"),
            ("聊小猫", "你先别告诉老师。", "请找身边的大人来帮忙。"),
            ("我先走啦", None, "好，下次见！"),
            ("我叫小花", None, "我们聊点别的吧。"),
        )
        for text, model_text, spoken in cases:
            with self.subTest(text=text, model_text=model_text):
                model_calls = []

                class ChatFixture(SpeechFixture):
                    @asynccontextmanager
                    async def answer(self, transcript, *, history):
                        model_calls.append(transcript)

                        async def sentences():
                            yield "猫咪会喵喵叫。"
                            yield model_text
                        yield sentences()

                demo = ChatFixture(["我想聊天", text])
                async with game_server(0, self.tls, self.token, demo, seed=0, report=lambda _: None) as server:
                    async with self.open(server) as ws:
                        await self.start(ws, conversation=True)
                        await self.speech(ws, await self.reply(ws))
                        chat = await self.reply(ws)
                        spoken_before = len(demo.spoken)
                        await self.speech(ws, chat)
                        outcome = await self.reply(ws)
                        self.assertEqual(outcome["next_action"], "listen" if text == "我叫小花" else "end")
                self.assertEqual(demo.spoken[spoken_before:], [spoken])
                self.assertEqual(model_calls, [text] if model_text else [])

    @asynccontextmanager
    async def standalone(self, demo, logs, *, trial):
        # Exercise the CLI and standalone credential validation. Only the
        # cloud adapter and the listener's dynamic test port are substituted.
        ready = asyncio.get_running_loop().create_future()
        token = "a" * 64

        @asynccontextmanager
        async def listener(port, tls, device_token, providers, **options):
            self.assertEqual(port, 19443)
            self.assertEqual(device_token, token)
            async with game_server(0, tls, device_token, providers, seed=0, **options) as server:
                ready.set_result(server)
                yield server

        with tempfile.TemporaryDirectory() as credentials:
            directory = Path(credentials)
            (directory / "animal-device-token").write_text(token)
            (directory / "animal-device-expiry").write_text(str(int(time.time()) + 60))
            argv = ["cloud", "--standalone", "--port", "19443", "--cert", str(self.cert),
                    "--key", str(self.key)]
            if trial:
                argv.append("--trial-limits")
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {
                "CREDENTIALS_DIRECTORY": credentials,
                "LITTLE_BUDDY_AUTHORITY": "localhost:19443",
                "LITTLE_BUDDY_BIND": "127.0.0.1",
            }), patch.object(DashScope, "from_environment", return_value=demo), patch.object(
                cloud, "game_server", listener
            ), patch.object(cloud, "disable_core_dumps"), patch.object(cloud, "print", lambda line, **_: logs.append(line), create=True):
                task = asyncio.create_task(cloud.main())
                try:
                    done, _ = await asyncio.wait({ready, task}, timeout=3,
                                                 return_when=asyncio.FIRST_COMPLETED)
                    if task in done:
                        await task
                    self.assertIn(ready, done, "standalone listener did not start")
                    yield ready.result(), token
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    asyncio.get_running_loop().remove_signal_handler(cloud.signal.SIGTERM)

    async def test_standalone_crosses_old_usage_thresholds_unless_trial_is_explicit(self):
        for trial in (False, True):
            with self.subTest(trial=trial):
                contexts = []

                class ChatFixture(SpeechFixture):
                    @asynccontextmanager
                    async def answer(self, transcript, *, history):
                        contexts.append(history)

                        async def sentences():
                            yield "猫咪会喵喵叫。"
                            yield "它喜欢晒太阳。"
                            yield "我们一起数数吧。"
                        yield sentences()

                demo = ChatFixture(["我想聊天"] + [f"聊第{number}只小猫" for number in range(25)])
                logs = []
                async with self.standalone(demo, logs, trial=trial) as (server, token):
                    async with self.open(server, token, standalone=True) as ws:
                        await self.start(ws, conversation=True)
                        await self.speech(ws, await self.reply(ws))
                        receipt = await self.reply(ws)
                        for number in range(12 if trial else 25):
                            await self.speech(ws, receipt)
                            receipt = await self.reply(ws)
                            if trial and number == 11:
                                self.assertEqual(receipt["next_action"], "end")
                                self.assertEqual(demo.spoken[-1], "今天先聊到这里吧。")
                            else:
                                self.assertEqual((receipt["next_action"], receipt["count"]), ("listen", 3))
                                self.assertEqual(demo.spoken[-1], "我们一起数数吧。")
                        if not trial:
                            self.assertEqual(len(demo.spoken), 77)
                            for action in ("listen", "end"):
                                await self.send(ws, "listen.silence", receipt["key"],
                                                listen_id=receipt["listen_id"])
                                receipt = await self.reply(ws)
                                self.assertEqual(receipt["next_action"], action)
                self.assertEqual(demo.requests, 13 if trial else 26)
                if trial:
                    self.assertEqual(len(demo.spoken), 36)
                self.assertEqual(len(contexts[-1]), 3)
                self.assertEqual([turn[0] for turn in contexts[-1]],
                                 [f"聊第{number}只小猫" for number in (range(8, 11) if trial else range(21, 24))])
                self.assertTrue(any(("llm=12" if trial else "llm=25") in line for line in logs))

    async def test_standalone_total_deadline_is_trial_only(self):
        timeout = asyncio.timeout
        shortened_deadline = 0.1

        def accelerate_total_timeout(delay):
            return timeout(shortened_deadline if delay == 900 else delay)

        for trial in (False, True):
            with self.subTest(trial=trial), patch.object(asyncio, "timeout", accelerate_total_timeout):
                demo = SpeechFixture(["我想聊天"])
                logs = []
                async with self.standalone(demo, logs, trial=trial) as (server, token):
                    async with self.open(server, token, standalone=True) as ws:
                        await self.start(ws, conversation=True)
                        receipt = await self.reply(ws)
                        await asyncio.sleep(shortened_deadline * 2)
                        if trial:
                            with self.assertRaises(ConnectionClosed) as closed:
                                await asyncio.wait_for(ws.recv(), 3)
                            self.assertEqual(closed.exception.rcvd.code, 1011)
                            self.assertTrue(any(line.startswith("animal_usage reason=timeout ") for line in logs))
                        else:
                            await self.speech(ws, receipt)
                            response = await self.reply(ws)
                            self.assertEqual((response["mode"], response["next_action"]), ("chat", "listen"))
                            self.assertEqual(demo.requests, 1)

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
