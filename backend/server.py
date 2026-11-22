"""TLS transport for the one-turn voice contract (Python 3.11+)."""

import asyncio
import hmac
import json
import logging
import re
import ssl
from http import HTTPStatus
from uuid import uuid4

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from backend.timing import mark as mark_stage
from backend.voice import ContentPolicy, End, ProtocolError, Providers, run_turn
from backend.wire import VERSION, decode_input, playback_frame


TURN_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


class Channel:
    def __init__(self, socket: ServerConnection):
        self.socket = socket
        self.sealed = asyncio.Event()
        self.position = 0

    async def control(self, kind: str, **fields: int) -> None:
        await self.socket.send(json.dumps({"v": VERSION, "type": kind, **fields}))

    async def ready(self) -> None:
        await self.control("turn.ready")

    async def receive(self):
        event = decode_input(await self.socket.recv())
        if isinstance(event, End):
            self.sealed.set()
        return event

    async def segment_started(self, number: int) -> None:
        self.position = 0
        await self.control("segment.start", number=number)

    async def audio(self, pcm16le: bytes) -> None:
        for offset in range(0, len(pcm16le), 6400):
            frame = pcm16le[offset:offset + 6400]
            await self.socket.send(playback_frame(self.position, frame))
            if self.position == 0:
                mark_stage("first_pcm_sent")
            self.position += len(frame) // 2

    async def segment_ended(self, number: int, samples: int) -> None:
        await self.control("segment.end", number=number, samples=samples)

    async def reply_ended(self, count: int) -> None:
        await self.control("reply.end", count=count)

    async def reject_after_seal(self) -> None:
        await self.sealed.wait()
        await self.socket.recv()
        raise ProtocolError("unexpected input after seal")


def voice_server(host: str, port: int, tls: ssl.SSLContext, token: str,
                 providers: Providers, policy: ContentPolicy, *, timings: bool = False):
    if tls is None or not 32 <= len(token) <= 256 or not token.isascii() or not token.isalnum():
        raise ValueError("TLS and a random device token (32–256 ASCII alphanumerics) are required")
    expected = ("Bearer " + token).encode("ascii")
    active = False
    # Keep request headers and provider exceptions out of server logs.
    logger = logging.Logger("little_buddy.websocket")
    logger.addHandler(logging.NullHandler())

    async def handshake(socket, request):
        if request.path == "/healthz":
            return socket.respond(HTTPStatus.OK, "ok\n")
        if request.path != "/v1/turn":
            return socket.respond(HTTPStatus.NOT_FOUND, "not found\n")
        credentials = request.headers.get_all("Authorization")
        if len(credentials) != 1 or not hmac.compare_digest(credentials[0].encode(), expected):
            return socket.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
        ids = request.headers.get_all("X-Voice-Turn-ID")
        if ids and (len(ids) != 1 or not TURN_ID.fullmatch(ids[0])):
            return socket.respond(HTTPStatus.BAD_REQUEST, "invalid turn identifier\n")
        if active:
            return socket.respond(HTTPStatus.SERVICE_UNAVAILABLE, "busy\n")

    async def handler(socket):
        nonlocal active
        if active:
            await socket.close(1013, "busy")
            return
        active = True
        channel = Channel(socket)
        clock = asyncio.get_running_loop().time
        started = clock()

        connection_id = uuid4()
        turn_id = socket.request.headers.get("X-Voice-Turn-ID", "-")

        def mark(event: str, segment: int = 0) -> None:
            if timings:
                elapsed = round((clock() - started) * 1000)
                print(f"voice_timing {event} turn_id={turn_id} connection_id={connection_id} "
                      f"segment={segment} since_connect_ms={elapsed}", flush=True)

        mark("connected")
        turn = asyncio.create_task(run_turn(channel, providers, policy, timing=mark if timings else None))
        disconnected = asyncio.create_task(socket.wait_closed())
        extra_input = asyncio.create_task(channel.reject_after_seal())
        tasks = (turn, disconnected, extra_input)
        outcome = "disconnected"
        try:
            finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if turn in finished:
                turn.result()
                outcome = "completed"
            if extra_input in finished:
                extra_input.result()
        except ConnectionClosed:
            pass
        except ProtocolError:
            outcome = "protocol_error"
            await socket.close(1008, "invalid turn")
        except TimeoutError:
            outcome = "timeout"
            await socket.close(1013, "turn timed out")
        except Exception:
            outcome = "provider_error"
            await socket.close(1011, "turn failed")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            mark(outcome)
            active = False

    return serve(handler, host, port, ssl=tls, process_request=handshake,
                 origins=[None], compression=None, max_size=6406, max_queue=4,
                 open_timeout=4, close_timeout=1, server_header=None, logger=logger)
