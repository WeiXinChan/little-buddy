"""Private one-turn engineering server, using fake providers by default."""

import argparse
import asyncio
import math
import os
import ssl
import struct
from contextlib import asynccontextmanager
from pathlib import Path

from backend.dashscope import DashScope, GreetingPolicy, http_client
from backend.server import voice_server


class Demo:
    @asynccontextmanager
    async def recognize(self, sample_rate):
        yield self

    async def write(self, pcm16le):
        pass

    async def finish(self):
        return "synthetic"

    @asynccontextmanager
    async def answer(self, transcript):
        async def segments():
            yield "first"
            yield "second"
        yield segments()

    @asynccontextmanager
    async def synthesize(self, segment, sample_rate):
        frequency = 440 if segment == "first" else 660

        async def audio():
            for start in range(0, sample_rate // 5, 480):
                yield struct.pack("<480h", *(
                    round(2500 * math.sin(math.tau * frequency * i / sample_rate))
                    for i in range(start, start + 480)
                ))
        yield audio()

    def input(self, transcript):
        return transcript if transcript == "synthetic" else None

    def segment(self, text):
        return text if text in {"first", "second"} else None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8443, type=int)
    parser.add_argument("--provider", choices=("fake", "dashscope"), default="fake")
    parser.add_argument("--timings", action="store_true")
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.cert, args.key)
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    token_path = Path(directory) / "voice-device-token" if directory else None
    if token_path and token_path.is_file():
        token = token_path.read_text(encoding="ascii").strip()
    else:
        token = os.environ.get("VOICE_DEVICE_TOKEN", "")
    async with http_client() as http:
        demo = Demo()
        if args.provider == "dashscope":
            providers, policy = DashScope.from_environment(http), GreetingPolicy()
        else:
            providers, policy = demo, demo
        async with voice_server(args.host, args.port, tls, token, providers, policy, timings=args.timings):
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
