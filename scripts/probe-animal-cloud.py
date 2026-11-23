"""One bounded synthetic game using the existing private DashScope configuration."""
import asyncio
import json
import subprocess
from pathlib import Path
import ssl
import sys

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.animal.cloud import game_server
from backend.animal.rules import CARDS, CATALOG_VERSION
from backend.dashscope import DashScope, http_client
from backend.wire import HEADER


async def run(adapter, ws):
    async def send(event, **fields):
        await ws.send(json.dumps(dict(event=event, **fields)))

    async def receive(event):
        message = json.loads(await ws.recv())
        if message["event"] != event:
            raise ValueError("unexpected event")
        return message

    async def reply():
        value = await receive("reply")
        key = value["key"]
        for number, _ in enumerate(value["segments"], 1):
            await receive("segment.start")
            samples = 0
            while isinstance(frame := await ws.recv(), bytes):
                if HEADER.unpack_from(frame) != (1, 2, samples):
                    raise ValueError("invalid playback position")
                samples += (len(frame) - HEADER.size) // 2
            end = json.loads(frame)
            if end["event"] != "segment.end" or end["samples"] != samples:
                raise ValueError("invalid playback seal")
        await receive("reply.end")
        for number, _ in enumerate(value["segments"], 1):
            await send("playback.segment_completed", key=key, number=number)
            await receive("playback.segment_committed")
        return await receive("turn.committed")

    async def fixture(text):
        pcm = bytearray()
        async with adapter.synthesize(text, 24_000) as frames:
            async for frame in frames:
                pcm.extend(frame)
                if len(pcm) > 480_000:
                    raise ValueError("fixture too long")
        return subprocess.run(
            ["/usr/bin/ffmpeg", "-v", "error", "-f", "s16le", "-ar", "24000", "-ac", "1",
             "-i", "pipe:0", "-f", "s16le", "-ar", "16000", "pipe:1"],
            input=pcm, capture_output=True, check=True, timeout=4,
        ).stdout

    async def speak(receipt, pcm):
        await send("turn.start", key=receipt["key"], listen_id=receipt["listen_id"])
        await receive("turn.ready")
        for offset in range(0, len(pcm), 3200):
            await ws.send(HEADER.pack(1, 1, offset // 2) + pcm[offset:offset + 3200])
            await asyncio.sleep(0.1)
        await ws.send(json.dumps(dict(v=1, type="turn.end", samples=len(pcm) // 2)))
        return await reply()

    await send("session.start", v=1, catalog=CATALOG_VERSION, images=[card.image_id for card in CARDS])
    receipt = await reply()
    reveal = await fixture("告诉我答案。")
    for completed in range(1, 4):
        receipt = await speak(receipt, reveal)
        if receipt["completed"] != completed or receipt["next_action"] != "advance":
            raise ValueError("reveal was not committed")
        await send("turn.advance", key=receipt["key"])
        receipt = await reply()
    receipt = await speak(receipt, await fixture("再玩一次。"))
    if receipt["completed"] != 0 or receipt["next_action"] != "listen":
        raise ValueError("restart was not committed")


async def main(cert, key):
    # The caller supplies a disposable localhost certificate and trusted copy.
    import secrets
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    trust = ssl.create_default_context(cafile=cert)
    token = secrets.token_hex(24)
    async with http_client() as http:
        adapter = DashScope.from_environment(http)
        async with game_server(0, tls, token, adapter, report=lambda line: print(line, flush=True)) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"wss://localhost:{port}/v1/animal", ssl=trust,
                               additional_headers={"Authorization": f"Bearer {token}"}) as ws:
                async with asyncio.timeout(115):
                    await run(adapter, ws)


if __name__ == "__main__":
    try:
        asyncio.run(main(*sys.argv[1:]))
    except Exception as exc:
        print(f"animal_probe success=0 attempts=1 error={type(exc).__name__}", flush=True)
        raise SystemExit(1) from None
    print("animal_probe success=1 attempts=1 synthetic_fixture_tts=2", flush=True)
