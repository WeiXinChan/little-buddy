"""Bounded Beijing greeting probe. Run as a non-root systemd service with credentials."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from time import monotonic

import httpx
from websockets.exceptions import ConnectionClosed, InvalidStatus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.dashscope import DashScope, GreetingPolicy, SpeechTaskError, http_client


def report(stage, **fields):
    print(json.dumps({"stage": stage, **fields}, ensure_ascii=True), flush=True)


def elapsed(start):
    return round((monotonic() - start) * 1000)


async def synthesize(adapter, text):
    pcm = bytearray()
    async with adapter.synthesize(text, 24_000) as frames:
        async for frame in frames:
            if len(frame) % 2 or len(pcm) + len(frame) > 480_000:
                raise ValueError("invalid PCM")
            pcm.extend(frame)
    if not pcm:
        raise ValueError("empty PCM")
    return pcm


async def answer(adapter, policy, prompt):
    start = monotonic()
    segments = []
    async with asyncio.timeout(8):
        async with adapter.answer(prompt) as answer:
            async for text in answer:
                if not segments:
                    first_ms = elapsed(start)
                approved_segment = policy.segment(text)
                if not approved_segment or len(segments) == 2:
                    raise ValueError("unexpected reply")
                segments.append(approved_segment)
    if len(segments) != 2:
        raise ValueError("unexpected segment count")
    report("llm", result="ok", ms=elapsed(start), first_ms=first_ms, segments=len(segments))
    return segments


async def probe(mode, shared_speech):
    stage = "configuration"
    start = monotonic()
    try:
        if os.geteuid() == 0 or os.environ.get("DASHSCOPE_REGION") != "cn-beijing":
            raise ValueError("expected non-root Beijing service")
        async with http_client() as http:
            adapter = DashScope.from_environment(http)
            if shared_speech:
                adapter.ws_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
                adapter.headers["X-DashScope-WorkSpace"] = os.environ["DASHSCOPE_WORKSPACE"]
            policy = GreetingPolicy()
            report(stage, result="ok", region="cn-beijing", asr=adapter.asr,
                   llm=adapter.llm, tts=adapter.tts, voice=adapter.voice, speech_endpoint="shared" if shared_speech else "workspace")
            if mode == "asr-ready":
                stage, start = "asr_ready", monotonic()
                async with asyncio.timeout(6):
                    async with adapter.recognize(16_000):
                        ready_ms = elapsed(start)
                report(stage, result="ok", ms=ready_ms, cancelled_without_audio=True)
                return 0
            if mode == "llm-only":
                stage, start = "llm", monotonic()
                await answer(adapter, policy, "你好，瓦力。")
                return 0

            stage, start = "tts_fixture", monotonic()
            async with asyncio.timeout(10):
                fixture = await synthesize(adapter, "你好，瓦力。")
            report(stage, result="ok", ms=elapsed(start), bytes=len(fixture), format="pcm_s16le/24000/mono")
            stage, start = "resample", monotonic()
            converted = subprocess.run(
                ["/usr/bin/ffmpeg", "-v", "error", "-f", "s16le", "-ar", "24000",
                 "-ac", "1", "-i", "pipe:0", "-f", "s16le", "-ar", "16000", "pipe:1"],
                input=fixture, capture_output=True, check=True, timeout=4,
            ).stdout
            del fixture
            stage, start = "asr", monotonic()
            async with asyncio.timeout(12):
                async with adapter.recognize(16_000) as recognition:
                    ready_ms = elapsed(start)
                    for offset in range(0, len(converted), 3200):
                        await recognition.write(converted[offset:offset + 3200])
                        await asyncio.sleep(0.1)
                    seal = monotonic()
                    approved = policy.input((await recognition.finish()).strip())
            report(stage, result="ok" if approved else "policy_rejected", ms=elapsed(start),
                   ready_ms=ready_ms, seal_ms=elapsed(seal), bytes=len(converted),
                   format="pcm_s16le/16000/mono")
            del converted
            if not approved:
                return 1

            stage, start = "llm", monotonic()
            segments = await answer(adapter, policy, approved)
            for number, segment in enumerate(segments, 1):
                stage, start = f"tts_reply_{number}", monotonic()
                async with asyncio.timeout(10):
                    result = await synthesize(adapter, segment)
                report(stage, result="ok", ms=elapsed(start), bytes=len(result),
                       format="pcm_s16le/24000/mono")
                del result
            return 0
    except Exception as exc:
        details = {}
        if isinstance(exc, SpeechTaskError):
            details["code"] = exc.code
        elif isinstance(exc, httpx.HTTPStatusError):
            details["http_status"] = exc.response.status_code
        elif isinstance(exc, InvalidStatus):
            details["http_status"] = exc.response.status_code
        elif isinstance(exc, ConnectionClosed):
            details["ws_code"] = exc.rcvd.code if exc.rcvd else 1006
        report(stage, result="failed", ms=elapsed(start), error=type(exc).__name__, **details)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("turn", "asr-ready", "llm-only"), default="turn")
    parser.add_argument("--shared-speech", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(probe(args.mode, args.shared_speech)))
