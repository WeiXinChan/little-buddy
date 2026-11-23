import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile
import time
import unittest

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from backend.animal.cloud import game_server
from backend.animal.rules import CARDS, CATALOG_VERSION
from backend.demo import Demo


ROOT = Path(__file__).resolve().parents[2]


class StandaloneTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.cert, cls.key = (Path(directory.name) / name for name in ("cert", "key"))
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-subj", "/CN=fixture", "-addext", "subjectAltName=IP:127.0.0.1",
            "-days", "1", "-keyout", cls.key, "-out", cls.cert,
        ], check=True, capture_output=True)
        cls.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.tls.load_cert_chain(cls.cert, cls.key)
        cls.trust = ssl.create_default_context(cafile=str(cls.cert))
        expired = cls.cert.with_name("expired")
        subprocess.run([
            "openssl", "x509", "-in", cls.cert, "-signkey", cls.key,
            "-days", "0", "-out", expired,
        ], check=True, capture_output=True)
        cls.expired_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.expired_tls.load_cert_chain(expired, cls.key)
        cls.expired_trust = ssl.create_default_context(cafile=str(expired))

    def open(self, server, token, *, host="127.0.0.1", trust=None, headers=()):
        port = server.sockets[0].getsockname()[1]
        return connect(f"wss://{host}:{port}/v1/animal", ssl=trust or self.trust,
                       proxy=None, open_timeout=2, close_timeout=0.2,
                       additional_headers=[("Authorization", f"Bearer {token}"),
                                           *headers])

    async def rejected(self, request, status):
        with self.assertRaises(InvalidStatus) as rejected:
            async with request:
                self.fail("unexpected upgrade")
        self.assertEqual(rejected.exception.response.status_code, status)

    async def test_strict_ip_tls_authority_and_auth(self):
        token = secrets.token_hex(32)
        # Suppress asyncio debug tracebacks for expected TLS handshake aborts.
        asyncio.get_running_loop().set_debug(False)
        async with game_server(0, self.tls, token, Demo(), expires_at=time.time() + 30) as server:
            for arguments in ({"trust": ssl.create_default_context()}, {"host": "localhost"}):
                with self.assertRaises(ssl.SSLCertVerificationError):
                    async with self.open(server, token, **arguments):
                        self.fail("unexpected TLS acceptance")
        await asyncio.sleep(1.1)  # OpenSSL timestamps have one-second precision.
        async with game_server(0, self.expired_tls, token, Demo()) as server:
            with self.assertRaisesRegex(ssl.SSLCertVerificationError, "certificate has expired"):
                async with self.open(server, token, trust=self.expired_trust):
                    self.fail("unexpected TLS acceptance")
        async with game_server(0, self.tls, token, Demo(), authority="127.0.0.1",
                               expires_at=time.time() + 30) as server:
            await self.rejected(self.open(server, token), 404)
        async with game_server(0, self.tls, token, Demo(), expires_at=time.time() + 30) as server:
            await self.rejected(self.open(server, secrets.token_hex(32)), 401)
            await self.rejected(self.open(server, token, headers=[("Authorization", f"Bearer {token}")]), 401)
            async with self.open(server, token):
                for _ in range(5):
                    await self.rejected(self.open(server, token), 503)
                await self.rejected(self.open(server, token), 429)

    async def test_online_expiry_and_credential_replacement(self):
        old, new = secrets.token_hex(32), secrets.token_hex(32)
        async with game_server(0, self.tls, old, Demo(), expires_at=time.time() + 1) as server:
            async with self.open(server, old) as ws:
                with self.assertRaises(ConnectionClosed) as closed:
                    await asyncio.wait_for(ws.recv(), 3)
                self.assertEqual(closed.exception.rcvd.code, 1008)
            await self.rejected(self.open(server, old), 401)
        async with game_server(0, self.tls, new, Demo(), expires_at=time.time() + 30) as server:
            await self.rejected(self.open(server, old), 401)
            async with self.open(server, new):
                pass

    async def test_disconnect_releases_provider_and_starts_fresh_session(self):
        started, cleaned = asyncio.Event(), asyncio.Event()
        reported = asyncio.Event()

        def report(line):
            if line.startswith("animal_usage reason=disconnect"):
                reported.set()

        class HangingAudio(Demo):
            @asynccontextmanager
            async def synthesize(self, text, sample_rate):
                started.set()
                try:
                    await asyncio.Future()
                    yield
                finally:
                    cleaned.set()

        async def session(ws):
            await ws.send(json.dumps(dict(event="session.start", v=1, catalog=CATALOG_VERSION,
                                          images=[card.image_id for card in CARDS])))
            return json.loads(await asyncio.wait_for(ws.recv(), 2))["key"]

        token = secrets.token_hex(32)
        async with game_server(0, self.tls, token, HangingAudio(), report=report,
                               trial_limits=True, expires_at=time.time() + 30) as server:
            async with self.open(server, token) as ws:
                first = await session(ws)
                await asyncio.wait_for(started.wait(), 2)
                ws.transport.abort()
            await asyncio.wait_for(cleaned.wait(), 2)
            await asyncio.wait_for(reported.wait(), 2)
            async with self.open(server, token) as ws:
                second = await session(ws)
            self.assertEqual(first["turn_id"], second["turn_id"])
            self.assertNotEqual(first["session_id"], second["session_id"])

    async def test_release_selection_and_rollback_preserve_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credential = root / "credential"
            credential.write_text(secrets.token_hex(32))
            original = credential.read_bytes()
            stable, candidate = "a" * 40, "b" * 40
            for sha in (stable, candidate):
                release = root / "releases" / sha
                (release / "backend").mkdir(parents=True)
                (release / ".venv/bin").mkdir(parents=True)
                (release / ".venv/bin/python").symlink_to(sys.executable)
            for sha, result, selected in ((stable, 0, stable), (candidate, 0, candidate),
                                          ("f" * 40, 2, candidate), (stable, 0, stable)):
                process = await asyncio.create_subprocess_exec(
                    ROOT / "backend/deploy/select-release", sha,
                    env={**os.environ, "LITTLE_BUDDY_RELEASE_ROOT": directory},
                    stderr=subprocess.DEVNULL,
                )
                self.assertEqual(await process.wait(), result)
                self.assertEqual((root / "current").resolve().name, selected)
                self.assertEqual(credential.read_bytes(), original)
