import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import asynccontextmanager

import httpx

from backend.dashscope import ChatStatusError, DashScope, GreetingPolicy, SpeechTask, SpeechTaskError, upstream_details


class SpeechSocket:
    def __init__(self, events):
        self.events = iter(events)
        self.actions = []
        self.binary = []

    async def send(self, message):
        if isinstance(message, bytes):
            self.binary.append(message)
            return
        command = json.loads(message)
        self.actions.append(command)
        self.id = command["header"]["task_id"]

    def event(self, name, payload=None):
        return json.dumps({"header": {"task_id": self.id, "event": name}, "payload": payload or {}})

    async def recv(self):
        return self.event("task-started")

    async def __aiter__(self):
        for item in self.events:
            if isinstance(item, bytes):
                yield item
            else:
                yield self.event(*item)


class AdapterTest(unittest.IsolatedAsyncioTestCase):
    def test_failed_task_preserves_code_without_provider_message(self):
        task = SpeechTask(None)
        event = json.dumps({"header": {
            "task_id": task.id, "event": "task-failed", "error_code": "AccessDenied",
            "error_message": "private upstream details",
        }})
        with self.assertRaises(SpeechTaskError) as failure:
            task.event(event)
        self.assertEqual(failure.exception.code, "AccessDenied")
        self.assertEqual(str(failure.exception), "speech task failed")


    def test_upstream_fields_cannot_echo_format_valid_markers(self):
        marker = "deadbeefdeadbeef"
        fields = upstream_details("PrivateMarkerCode", marker, marker)
        self.assertNotIn("code", fields)
        self.assertEqual(len(fields["request_id_sha256_prefix"]), 16)
        self.assertNotIn(marker, str(fields))

    async def test_chat_failure_extracts_diagnostics_without_echoing_error_body(self):
        async def denied(request):
            return httpx.Response(403, json={
                "error": {"code": "insufficient_quota", "message": "private upstream detail"},
                "request_id": "abcdef00-1111-2222-3333-444444444444",
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(denied)) as http:
            adapter = DashScope(http, workspace="workspace", region="cn-beijing", key="synthetic",
                                asr="asr", llm="llm", tts="tts", voice="voice")
            with self.assertRaises(ChatStatusError) as error:
                async with adapter.answer("你好，瓦力。"):
                    self.fail("unexpected successful stream")

        self.assertEqual(error.exception.status, 403)
        self.assertEqual(error.exception.details, {
            "code": "insufficient_quota", "request_id_sha256_prefix": "c06936b0dc5003fb",
            "message": "[redacted upstream message]",
        })

    def test_close_summary_keeps_only_fixed_quota_fragment(self):
        self.assertEqual(upstream_details(None, "private-id: quota limit", None),
                         {"message": "quota"})

    async def test_tts_waits_for_ready_before_continue_and_finish(self):
        waiting = asyncio.Event()
        ready = asyncio.Event()

        class DelayedReady(SpeechSocket):
            async def recv(self):
                waiting.set()
                await ready.wait()
                return await super().recv()

        socket = DelayedReady([b"\x01\x00", ("task-finished",)])

        @asynccontextmanager
        async def speech_socket():
            yield socket

        adapter = DashScope(None, workspace="workspace", region="cn-beijing", key="synthetic",
                            asr="asr", llm="llm", tts="cosyvoice-v3-flash", voice="longanyang")
        adapter.speech_socket = speech_socket

        async def synthesize():
            async with adapter.synthesize("你好。", 24_000) as frames:
                return [frame async for frame in frames]

        pending = asyncio.create_task(synthesize())
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            self.assertEqual([event["header"]["action"] for event in socket.actions], ["run-task"])
            ready.set()
            self.assertEqual(await asyncio.wait_for(pending, 1), [b"\x01\x00"])
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

        headers = [event["header"] for event in socket.actions]
        self.assertEqual([header["action"] for header in headers],
                         ["run-task", "continue-task", "finish-task"])
        self.assertEqual({header["streaming"] for header in headers}, {"duplex"})
        self.assertEqual(len({header["task_id"] for header in headers}), 1)
        self.assertEqual(socket.actions[0]["payload"]["parameters"]["format"], "pcm")
        self.assertEqual(socket.actions[0]["payload"]["parameters"]["sample_rate"], 24_000)
        self.assertEqual(socket.actions[1]["payload"]["input"], {"text": "你好。"})
        self.assertEqual(socket.actions[2]["payload"]["input"], {})

    def test_uses_systemd_credential_file(self):
        with TemporaryDirectory() as folder, patch.dict("os.environ", {
            "CREDENTIALS_DIRECTORY": folder,
            "DASHSCOPE_WORKSPACE": "test-workspace",
            "DASHSCOPE_REGION": "cn-beijing",
            "DASHSCOPE_ASR_MODEL": "fun-asr-realtime",
            "DASHSCOPE_LLM_MODEL": "qwen3.8-flash",
            "DASHSCOPE_TTS_MODEL": "cosyvoice-v3-flash",
            "DASHSCOPE_TTS_VOICE": "longanyang",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "credential is unavailable"):
                DashScope.from_environment(None)
            (Path(folder) / "dashscope-api-key").write_text("dummy-offline-key\n", encoding="ascii")
            adapter = DashScope.from_environment(None)
            self.assertEqual(adapter.headers["Authorization"], "Bearer dummy-offline-key")
            self.assertEqual(adapter.llm, "qwen3.8-flash")
            self.assertEqual(adapter.ws_url,
                             "wss://test-workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference")

    async def test_synthetic_pipeline_uses_final_transcript_and_pcm_formats(self):
        async def chat(request):
            body = json.loads(request.content)
            self.assertEqual(body["messages"][-1]["content"], "你好，瓦力。")
            self.assertTrue(body["stream"])
            self.assertFalse(body["enable_thinking"])
            chunks = ["你好！我", "是瓦力。"]
            content = "".join("data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]})
                              + "\n\n" for chunk in chunks)
            return httpx.Response(200, text=content + "data: [DONE]\n\n")

        asr = SpeechSocket([
            ("result-generated", {"output": {"sentence": {"sentence_end": False, "text": "ignore"}}}),
            ("result-generated", {"output": {"sentence": {"sentence_end": True, "text": "你好，瓦力。"}}}),
            ("task-finished",),
        ])
        tts = SpeechSocket([b"\x01\x00", ("task-finished",)])
        sockets = iter((asr, tts))

        @asynccontextmanager
        async def speech_socket():
            yield next(sockets)

        async with httpx.AsyncClient(transport=httpx.MockTransport(chat)) as http:
            adapter = DashScope(http, workspace="workspace", region="cn-beijing", key="synthetic",
                                asr="asr", llm="llm", tts="tts", voice="voice")
            adapter.speech_socket = speech_socket
            async with adapter.recognize(16_000) as recognition:
                await recognition.write(b"\x02\x00")
                transcript = await recognition.finish()
            policy = GreetingPolicy()
            events = []
            async with adapter.answer(policy.input(transcript),
                                      on_first_text=lambda: events.append("first text")) as answer:
                segments = []
                async for text in answer:
                    events.append("complete segment")
                    segments.append(policy.segment(text))
            self.assertEqual(events, ["first text", "complete segment", "complete segment"])
            async with adapter.synthesize(segments[0], 24_000) as frames:
                self.assertEqual([frame async for frame in frames], [b"\x01\x00"])

        self.assertEqual(segments, ["你好。", "我是瓦力。"])
        self.assertEqual(asr.binary, [b"\x02\x00"])
        self.assertEqual(asr.actions[0]["payload"]["parameters"], {"format": "pcm", "sample_rate": 16000})
        self.assertEqual(tts.actions[0]["payload"]["parameters"]["sample_rate"], 24000)
        self.assertEqual(tts.actions[1]["payload"]["input"], {"text": "你好。"})
        self.assertIsNone(policy.input("其他输入"))
        self.assertIsNone(policy.segment("其他回复"))
