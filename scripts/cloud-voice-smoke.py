"""Bounded Beijing greeting probe. Run as a non-root systemd service with credentials."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from time import monotonic

from websockets.exceptions import ConnectionClosed, InvalidStatus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.dashscope import ChatStatusError, DashScope, GreetingPolicy, SpeechTaskError, http_client, upstream_details


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
    if not pcm or not any(pcm):
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
    if segments != ["你好。", "我是瓦力。"]:
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
            fixture_ms = elapsed(start)
            stage = "fixture_decode"
            converted = subprocess.run(
                ["/usr/bin/ffmpeg", "-v", "error", "-f", "s16le", "-ar", "24000",
                 "-ac", "1", "-i", "pipe:0", "-f", "s16le", "-ar", "16000", "pipe:1"],
                input=fixture, capture_output=True, check=True, timeout=4,
            ).stdout
            if not converted or len(converted) % 2 or not any(converted):
                raise ValueError("invalid decoded fixture")
            report("tts_fixture", result="ok", ms=fixture_ms, validated_ms=elapsed(start),
                   bytes=len(fixture), duration_ms=round(len(fixture) / 48),
                   format="pcm_s16le/24000/mono")
            del fixture
            if mode == "tts-fixture":
                return 0
            stage, start = "asr", monotonic()
            turn_start = start
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
                metrics = {"seal_to_playable_ms": elapsed(seal)} if number == 1 else {}
                report(stage, result="ok", ms=elapsed(start), bytes=len(result),
                       duration_ms=round(len(result) / 48), format="pcm_s16le/24000/mono", **metrics)
                del result
            report("turn", result="ok", ms=elapsed(turn_start), seal_to_done_ms=elapsed(seal))
            return 0
    except Exception as exc:
        details = {}
        if isinstance(exc, SpeechTaskError):
            details.update(exc.details)
        elif isinstance(exc, ChatStatusError):
            details.update(exc.details, http_status=exc.status)
        elif isinstance(exc, InvalidStatus):
            details["http_status"] = exc.response.status_code
        elif isinstance(exc, ConnectionClosed):
            details["ws_code"] = exc.rcvd.code if exc.rcvd else 1006
            if exc.rcvd and exc.rcvd.reason:
                details.update(upstream_details(None, exc.rcvd.reason, None))
        report(stage, result="failed", ms=elapsed(start), error=type(exc).__name__, **details)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("turn", "asr-ready", "llm-only", "tts-fixture"), default="turn")
    parser.add_argument("--shared-speech", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(probe(args.mode, args.shared_speech)))
