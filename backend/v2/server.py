"""Authenticated V2-only endpoint. Construct explicitly; never modifies V1."""
import hmac
import logging
import asyncio
import time
from http import HTTPStatus
from websockets.asyncio.server import serve
from backend.v2.voice import VoicePeer


def voice_server(host, port, tls, token, providers, policy, *, expires_at=None, clock=time.time, feedback=None, failure_observation=None, stream_asr=False):
    if tls is None or not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii() or not token.isalnum():
        raise ValueError('TLS and random device credential required')
    active = False
    logger = logging.Logger('little_buddy.v2')
    logger.addHandler(logging.NullHandler())

    async def authenticate(socket, request):
        if request.path != '/v2/voice' and not (feedback is not None and request.path == '/v2/feedback'):
            return socket.respond(HTTPStatus.NOT_FOUND, 'not found\n')
        values = request.headers.get_all('Authorization')
        if ((expires_at is not None and clock()>=expires_at) or len(values) != 1 or
                not hmac.compare_digest(values[0].encode(), ('Bearer ' + token).encode())):
            return socket.respond(HTTPStatus.UNAUTHORIZED, 'unauthorized\n')

    async def handler(socket):
        nonlocal active
        if socket.request.path == '/v2/feedback':
            try:
                if expires_at is None:await feedback.run(socket)
                else:
                    async with asyncio.timeout(max(0,expires_at-clock())):await feedback.run(socket)
            except TimeoutError:await socket.close(1008,'device credential expired')
            except Exception:await socket.close(1011,'feedback closed')
            return
        if active:
            await socket.close(1013, 'busy')
            return
        active = True
        if stream_asr:
            peer = VoicePeer(socket, providers, policy, stream_asr=True)
        else:
            peer = VoicePeer(socket, providers, policy)
        if failure_observation is not None:
            try:failure_observation.attach(peer)
            except BaseException:pass
        try:
            if expires_at is None:await peer.run()
            else:
                async with asyncio.timeout(max(0,expires_at-clock())):await peer.run()
        except TimeoutError:
            await socket.close(1008,'device credential expired')
        except Exception:
            await socket.close(1011, 'voice closed')
        finally:
            # An unconfirmed native/provider release disables this server instance.
            if not peer.quarantined:
                active = False
    return serve(handler, host, port, ssl=tls, process_request=authenticate,
                 max_size=400000 if feedback is not None else 16000, max_queue=4, write_limit=16000,close_timeout=1, logger=logger)
