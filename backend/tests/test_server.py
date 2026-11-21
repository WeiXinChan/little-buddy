import asyncio
import json
import ssl
import subprocess
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from backend.demo import Demo
from backend.server import voice_server
from backend.wire import HEADER

TOKEN = "test" * 8


class BlockingDemo(Demo):
    def __init__(self):
        self.entered = asyncio.Event()
        self.released = asyncio.Event()

    @asynccontextmanager
    async def answer(self, transcript):
        try:
            self.entered.set()
            await asyncio.Future()
            yield
        finally:
            self.released.set()


class ServerTest(unittest.IsolatedAsyncioTestCase):
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
        cls.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.tls.load_cert_chain(cert, key)
        cls.trust = ssl.create_default_context(cafile=str(cert))

    def open(self, server, token=TOKEN):
        port = server.sockets[0].getsockname()[1]
        return connect(f"wss://localhost:{port}/v1/turn", ssl=self.trust,
                       additional_headers={"Authorization": f"Bearer {token}"})

    async def upload(self, socket, end=4):
        self.assertEqual(json.loads(await socket.recv()), {"v": 1, "type": "turn.ready"})
        await socket.send(HEADER.pack(1, 1, 0) + b"\0\0" * 2)
        await socket.send(HEADER.pack(1, 1, 2) + b"\1\0" * 2)
        await socket.send(json.dumps({"v": 1, "type": "turn.end", "samples": end}))

    async def test_auth_one_device_and_segment_positions(self):
        demo = Demo()
        async with voice_server("127.0.0.1", 0, self.tls, TOKEN, demo, demo) as server:
            with self.assertRaises(InvalidStatus) as denied:
                await self.open(server, "invalid")
            self.assertEqual(denied.exception.response.status_code, 401)
            async with self.open(server) as socket:
                with self.assertRaises(InvalidStatus) as busy:
                    await self.open(server)
                self.assertEqual(busy.exception.response.status_code, 503)
                await self.upload(socket)
                for number in (1, 2):
                    start = json.loads(await socket.recv())
                    self.assertEqual(start, {"v": 1, "type": "segment.start", "number": number})
                    position = 0
                    while isinstance(frame := await socket.recv(), bytes):
                        self.assertEqual(HEADER.unpack_from(frame), (1, 2, position))
                        position += (len(frame) - HEADER.size) // 2
                    self.assertEqual(position, 4800)
                    self.assertEqual(json.loads(frame),
                                     {"v": 1, "type": "segment.end", "number": number, "samples": position})
                self.assertEqual(json.loads(await socket.recv()), {"v": 1, "type": "reply.end", "count": 2})

    async def test_bad_seal_rejected(self):
        demo = Demo()
        async with voice_server("127.0.0.1", 0, self.tls, TOKEN, demo, demo) as server:
            async with self.open(server) as socket:
                await self.upload(socket, end=5)
                with self.assertRaises(ConnectionClosed) as error:
                    await socket.recv()
                self.assertEqual(error.exception.rcvd.code, 1008)

    async def test_disconnect_cancels_provider_and_next_turn_can_start(self):
        demo = BlockingDemo()
        async with voice_server("127.0.0.1", 0, self.tls, TOKEN, demo, demo) as server:
            async with self.open(server) as socket:
                await self.upload(socket)
                await asyncio.wait_for(demo.entered.wait(), 1)
            await asyncio.wait_for(demo.released.wait(), 1)
            async with asyncio.timeout(1):
                while True:
                    try:
                        async with self.open(server) as replacement:
                            self.assertEqual(json.loads(await replacement.recv())["type"], "turn.ready")
                        break
                    except InvalidStatus as denied:
                        self.assertEqual(denied.response.status_code, 503)
                        await asyncio.sleep(0.01)
