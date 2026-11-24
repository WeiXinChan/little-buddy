"""Authenticated V2-only endpoint. Construct explicitly; never modifies V1."""
import hmac
import logging
from http import HTTPStatus
from websockets.asyncio.server import serve
from backend.v2.voice import VoicePeer


def voice_server(host, port, tls, token, providers, policy):
    if tls is None or not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii() or not token.isalnum():
        raise ValueError('TLS and random device credential required')
    active = False
    logger = logging.Logger('little_buddy.v2')
    logger.addHandler(logging.NullHandler())

    async def authenticate(socket, request):
        if request.path != '/v2/voice':
            return socket.respond(HTTPStatus.NOT_FOUND, 'not found\n')
        values = request.headers.get_all('Authorization')
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), ('Bearer ' + token).encode()):
            return socket.respond(HTTPStatus.UNAUTHORIZED, 'unauthorized\n')

    async def handler(socket):
        nonlocal active
        if active:
            await socket.close(1013, 'busy')
            return
        active = True
        peer = VoicePeer(socket, providers, policy)
        try:
            await peer.run()
        except Exception:
            await socket.close(1011, 'voice closed')
        finally:
            # An unconfirmed native/provider release disables this server instance.
            if not peer.quarantined:
                active = False
    return serve(handler, host, port, ssl=tls, process_request=authenticate,
                 max_size=16000, max_queue=4, write_limit=16000, logger=logger)
