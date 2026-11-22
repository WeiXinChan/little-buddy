"""DashScope adapters for the approved synthetic/adult greeting smoke test."""

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

from backend.voice import ProtocolError


class GreetingPolicy:
    # Restrict live testing to the documented greeting. Canonicalize before sending to a model.
    def input(self, transcript):
        if re.fullmatch(r"你好[，,。！!\s]*瓦力[。！!\s]*", transcript):
            return "你好，瓦力。"
        return None

    def segment(self, text):
        for allowed in ("你好", "我是瓦力"):
            if text.strip().rstrip("。！!?？") == allowed:
                return allowed + "。"
        return None


class SpeechTask:
    def __init__(self, socket):
        self.socket = socket
        self.id = str(uuid4())

    async def command(self, action, **payload):
        await self.socket.send(json.dumps({
            "header": {"action": action, "task_id": self.id, "streaming": "duplex"},
            "payload": {"input": {}, **payload},
        }))

    def event(self, message):
        response = json.loads(message)
        header = response["header"]
        if header["task_id"] != self.id or header["event"] == "task-failed":
            raise ProtocolError("speech task failed")
        return header["event"], response.get("payload", {})

    async def start(self, task, function, model, parameters):
        await self.command("run-task", task_group="audio", task=task,
                           function=function, model=model, parameters=parameters)
        event, _ = self.event(await self.socket.recv())
        if event != "task-started":
            raise ProtocolError("speech task not ready")


class Recognition:
    def __init__(self, task):
        self.task = task
        self.results = asyncio.create_task(self.read_final_sentences())

    async def read_final_sentences(self):
        sentences = []
        length = 0
        async for message in self.task.socket:
            event, payload = self.task.event(message)
            if event == "task-finished":
                return "".join(sentences)
            if event == "result-generated":
                sentence = payload["output"]["sentence"]
                if sentence.get("heartbeat") or not sentence.get("sentence_end"):
                    continue
                text = sentence["text"]
                length += len(text)
                if length > 1024 or len(sentences) >= 64:
                    raise ProtocolError("oversized transcript")
                sentences.append(text)
        raise ProtocolError("unfinished recognition")

    async def write(self, pcm16le):
        if self.results.done():
            self.results.result()
            raise ProtocolError("recognizer stopped before seal")
        await self.task.socket.send(pcm16le)

    async def finish(self):
        await self.task.command("finish-task")
        return await self.results

    async def close(self):
        self.results.cancel()
        await asyncio.gather(self.results, return_exceptions=True)


class DashScope:
    def __init__(self, http, *, workspace, region, key, asr, llm, tts, voice):
        if region not in {"cn-beijing", "ap-southeast-1"} or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", workspace
        ):
            raise ValueError("invalid DashScope workspace or region")
        if not all(value and value.isascii() and not any(c.isspace() for c in value)
                   for value in (key, asr, llm, tts, voice)):
            raise ValueError("invalid DashScope credentials or model configuration")
        host = f"{workspace}.{region}.maas.aliyuncs.com"
        self.ws_url = f"wss://{host}/api-ws/v1/inference"
        self.chat_url = f"https://{host}/compatible-mode/v1/chat/completions"
        self.headers = {"Authorization": f"Bearer {key}"}
        self.http, self.asr, self.llm, self.tts, self.voice = http, asr, llm, tts, voice

    @classmethod
    def from_environment(cls, http):
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if not directory:
            raise ValueError("DashScope systemd credential directory is missing")
        try:
            with (Path(directory) / "dashscope-api-key").open(encoding="ascii") as credential:
                key = credential.read(4097).rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ValueError("DashScope systemd credential is unavailable") from None
        if not 1 <= len(key) <= 4096:
            raise ValueError("DashScope systemd credential has an invalid length")
        return cls(http, key=key, **{
            name: os.environ.get("DASHSCOPE_" + variable, "") for name, variable in {
                "workspace": "WORKSPACE", "region": "REGION",
                "asr": "ASR_MODEL", "llm": "LLM_MODEL", "tts": "TTS_MODEL", "voice": "TTS_VOICE",
            }.items()
        })

    def speech_socket(self):
        return connect(self.ws_url, additional_headers=self.headers, proxy=None,
                       open_timeout=3, close_timeout=1, max_queue=4, max_size=128_000)

    @asynccontextmanager
    async def recognize(self, sample_rate):
        async with self.speech_socket() as socket:
            task = SpeechTask(socket)
            await task.start("asr", "recognition", self.asr,
                             {"format": "pcm", "sample_rate": sample_rate})
            recognition = Recognition(task)
            try:
                yield recognition
            finally:
                await recognition.close()

    @asynccontextmanager
    async def answer(self, transcript):
        async with self.http.stream("POST", self.chat_url, headers=self.headers, json={
            "model": self.llm,
            "messages": [
                {"role": "system", "content": "请只用这两句话打招呼：你好！我是瓦力。"},
                {"role": "user", "content": transcript},
            ],
            "stream": True,
            "enable_thinking": False,
            "max_tokens": 64,
        }) as response:
            response.raise_for_status()
            yield self.sentences(response)

    async def sentences(self, response):
        pending = ""
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                if pending.strip():
                    yield pending.strip()
                return
            choices = json.loads(data)["choices"]
            if not choices:
                continue
            content = choices[0]["delta"].get("content")
            if not content:
                continue
            pending += content
            if len(pending) > 240:
                raise ProtocolError("oversized model segment")
            while match := re.match(r"^.*?[。！？!?\n]", pending, re.S):
                text, pending = pending[:match.end()].strip(), pending[match.end():]
                if text:
                    yield text
        raise ProtocolError("unfinished model response")

    @asynccontextmanager
    async def synthesize(self, segment, sample_rate):
        async with self.speech_socket() as socket:
            task = SpeechTask(socket)
            await task.start("tts", "SpeechSynthesizer", self.tts, {
                "text_type": "PlainText", "voice": self.voice, "format": "pcm",
                "sample_rate": sample_rate, "enable_ssml": False,
            })
            await task.command("continue-task", input={"text": segment})
            await task.command("finish-task")
            yield self.audio(task)

    async def audio(self, task):
        async for message in task.socket:
            if isinstance(message, bytes):
                yield message
            elif task.event(message)[0] == "task-finished":
                return
        raise ProtocolError("unfinished synthesis")


def http_client():
    return httpx.AsyncClient(timeout=4, trust_env=False, follow_redirects=False)
