"""Loopback TLS fault fixture for AnimalPrivateActivityTest. No cloud calls."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import math
import ssl
import struct

from backend.animal.cloud import game_server
from backend.demo import Demo


CASES = ("asr", "first-pcm", "between", "playing", "release", "late", "blackhole", "disconnect", "conversation")


class Fixture(Demo):
    def __init__(self, scenario):
        self.scenario = scenario
        self.recognitions = 0
        self.segments = 0
        self.network_fault = asyncio.Event()

    @asynccontextmanager
    async def recognize(self, sample_rate):
        self.recognitions += 1
        yield self

    async def finish(self):
        if self.scenario == "asr" and self.recognitions == 1:
            await asyncio.Future()
        if self.scenario == "conversation":
            turns = ("告诉我答案", "我想聊天", "我喜欢小猫", "玩猜动物", "再见")
            return turns[(self.recognitions - 1) % len(turns)]
        return "告诉我答案"

    @asynccontextmanager
    async def answer(self, transcript, *, heard=None):
        async def segments():
            yield "小猫软软的。"
            yield "它会轻轻地喵喵叫。"
        yield segments()

    @asynccontextmanager
    async def synthesize(self, segment, sample_rate):
        self.segments += 1
        number = self.segments

        async def frames():
            if ((self.scenario == "first-pcm" and number == 2) or
                    (self.scenario in {"between", "blackhole", "disconnect"} and number == 3)):
                if self.scenario in {"blackhole", "disconnect"}:
                    await asyncio.sleep(1.5)  # Let the first reveal play and be acknowledged.
                    self.network_fault.set()
                await asyncio.Future()
            duration = 3.0 if self.scenario == "playing" and number == 2 else 0.45
            pcm = struct.pack("<480h", *(round(1200 * math.sin(math.tau * 440 * i / sample_rate))
                                         for i in range(480)))
            for _ in range(round(duration / 0.02)):
                yield pcm
                await asyncio.sleep(0.02)
        yield frames()


@asynccontextmanager
async def fixture_server(port, tls, token, scenario, *, report=lambda _: None):
    fixture = Fixture(scenario)
    async with game_server(0, tls, token, fixture, seed=0, report=report) as backend:
        destination = backend.sockets[0].getsockname()[1]
        first = True

        async def proxy(reader, writer):
            nonlocal first
            inject = first and scenario in {"blackhole", "disconnect"}
            first = False
            upstream, transport = await asyncio.open_connection("127.0.0.1", destination)

            async def relay(source, target, *, keep_blackhole=False):
                while data := await source.read(8192):
                    if inject and fixture.network_fault.is_set():
                        if scenario == "disconnect":
                            return
                        continue
                    target.write(data)
                    await target.drain()
                if keep_blackhole and inject and scenario == "blackhole" and fixture.network_fault.is_set():
                    # Keep the client leg open even after the origin times out.
                    await asyncio.Future()

            async def cut():
                await fixture.network_fault.wait()
                report(f"animal_fixture_fault scenario={scenario}")
                if scenario == "blackhole":
                    await asyncio.Future()

            tasks = [asyncio.create_task(relay(reader, transport)), asyncio.create_task(relay(upstream, writer, keep_blackhole=True))]
            if inject:
                tasks.append(asyncio.create_task(cut()))
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                writer.close()
                transport.close()
                await asyncio.gather(*tasks, writer.wait_closed(), transport.wait_closed(), return_exceptions=True)

        async with await asyncio.start_server(proxy, "127.0.0.1", port) as listener:
            yield listener


async def main(args):
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert, args.key)
    async with fixture_server(args.port, tls, args.token, args.scenario,
                              report=print if args.timing else lambda _: None) as listener:
        port = listener.sockets[0].getsockname()[1]
        print(f"animal_fixture_ready scenario={args.scenario} port={port}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=CASES)
    parser.add_argument("--port", type=int, default=9444)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--timing", action="store_true")
    parser.add_argument("--token", default="offlinefixture" * 3)
    asyncio.run(main(parser.parse_args()))
