"""TLS transport for the one-turn voice contract (Python 3.11+)."""

import asyncio
import hmac
import json
import logging
import ssl
from http import HTTPStatus

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from backend.voice import ContentPolicy, End, ProtocolError, Providers, run_turn
from backend.wire import VERSION, decode_input, playback_frame


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
                 providers: Providers, policy: ContentPolicy):
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
        if active:
            return socket.respond(HTTPStatus.SERVICE_UNAVAILABLE, "busy\n")

    async def handler(socket):
        nonlocal active
        if active:
            await socket.close(1013, "busy")
            return
        active = True
        channel = Channel(socket)
        turn = asyncio.create_task(run_turn(channel, providers, policy))
        disconnected = asyncio.create_task(socket.wait_closed())
        extra_input = asyncio.create_task(channel.reject_after_seal())
        tasks = (turn, disconnected, extra_input)
        try:
            finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if extra_input in finished:
                extra_input.result()
            if turn in finished:
                turn.result()
        except ConnectionClosed:
            pass
        except ProtocolError:
            await socket.close(1008, "invalid turn")
        except TimeoutError:
            await socket.close(1013, "turn timed out")
        except Exception:
            await socket.close(1011, "turn failed")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            active = False

    return serve(handler, host, port, ssl=tls, process_request=handshake,
                 origins=[None], compression=None, max_size=6406, max_queue=4,
                 open_timeout=4, close_timeout=1, server_header=None, logger=logger)
