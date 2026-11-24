"""Explicit loopback-only synthetic fixture for the production V2 server.

python -m backend.v2.fixture --cert CERT --key KEY --token-file TOKEN
No cloud calls, user audio, body logs or writes. Files must stay outside the repo.
"""
import argparse
import asyncio
import math
from pathlib import Path
import ssl
import struct
from contextlib import asynccontextmanager
from backend.v2.server import voice_server


class SyntheticProviders:
    @asynccontextmanager
    async def recognize(self, rate):
        class Recognition:
            async def write(self, pcm): pass
            async def finish(self): return 'synthetic command'
        yield Recognition()

    async def endpoint(self, text, context):
        return dict(completion='complete', meaning='new_turn')

    @asynccontextmanager
    async def answer(self, text, context):
        async def sentences(): yield '合成测试音，不是真人语音。'
        yield sentences()

    @asynccontextmanager
    async def synthesize(self, text, rate):
        async def chunks():
            for offset in range(0, 12000, 2400):
                yield b''.join(struct.pack('<h', int(1500*math.sin(2*math.pi*440*i/rate)))
                               for i in range(offset, offset+2400))
                await asyncio.sleep(.01)
        yield chunks()


class SyntheticPolicy:
    # Deliberately fixture-only: this is NOT a child safety implementation.
    def input(self, text): return text
    def segment(self, text): return text


async def main(args):
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.cert, args.key)
    token = Path(args.token_file).read_text().strip()
    async with voice_server('127.0.0.1', args.port, tls, token, SyntheticProviders(), SyntheticPolicy()):
        await asyncio.Event().wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cert', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--port', type=int, default=19482)
    asyncio.run(main(parser.parse_args()))
