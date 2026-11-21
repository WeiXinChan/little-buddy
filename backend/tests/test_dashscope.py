import json
import unittest
from contextlib import asynccontextmanager

import httpx

from backend.dashscope import DashScope, GreetingPolicy


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
    async def test_synthetic_pipeline_uses_final_transcript_and_pcm_formats(self):
        async def chat(request):
            body = json.loads(request.content)
            self.assertEqual(body["messages"][-1]["content"], "你好，瓦力。")
            self.assertTrue(body["stream"])
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
            async with adapter.answer(policy.input(transcript)) as answer:
                segments = [policy.segment(text) async for text in answer]
            async with adapter.synthesize(segments[0], 24_000) as frames:
                self.assertEqual([frame async for frame in frames], [b"\x01\x00"])

        self.assertEqual(segments, ["你好。", "我是瓦力。"])
        self.assertEqual(asr.binary, [b"\x02\x00"])
        self.assertEqual(asr.actions[0]["payload"]["parameters"], {"format": "pcm", "sample_rate": 16000})
        self.assertEqual(tts.actions[0]["payload"]["parameters"]["sample_rate"], 24000)
        self.assertEqual(tts.actions[1]["payload"]["input"], {"text": "你好。"})
        self.assertIsNone(policy.input("其他输入"))
        self.assertIsNone(policy.segment("其他回复"))
