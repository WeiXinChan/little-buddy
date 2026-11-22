"""Private game transport. Run on a separate loopback TLS listener."""
import argparse
import asyncio
from dataclasses import asdict
import hmac
from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import secrets
import ssl

from websockets.asyncio.server import serve

from backend.dashscope import DashScope, http_client
from backend.server import Channel, DeviceDisconnected
from backend.timing import observer
from backend.voice import End, Limits, ProtocolError, deliver, recognize
from backend.wire import decode_input
from .rules import CARDS
from .session import Session, TurnKey


class GameChannel(Channel):
    def __init__(self, socket):
        super().__init__(socket)
        self.key = None
        self.session = None
        self.counts = dict(asr=0, asr_samples=0, tts=0, tts_chars=0, llm=0)

    async def control(self, kind, **fields):
        await self.send(json.dumps(dict(event=kind, key=asdict(self.key), **fields)))

    async def segment_ended(self, number, samples):
        await super().segment_ended(number, samples)
        if not self.session.segment_sent(self.key, number):
            raise ProtocolError("invalid segment order")

    async def receive(self):
        while True:
            raw = await self.recv()
            if isinstance(raw, str):
                message = json.loads(raw)
                if isinstance(message, dict) and message.get("event") in {
                    "turn.start", "listen.silence", "playback.segment_completed", "turn.advance"
                }:
                    continue  # The active ASR already consumed the only permit.
            item = decode_input(raw)
            if not isinstance(item, End):
                self.counts["asr_samples"] += len(item.data) // 2
            return item


class RuleSpeech:
    def segment(self, text):
        return text  # Only Session-authored templates enter this pipeline.


async def play_game(socket, providers, *, seed=None, report=print):
    channel = GameChannel(socket)
    session = None
    limits = Limits()
    counts = channel.counts
    reason = "disconnect"
    clock = asyncio.get_running_loop().time
    started = clock()

    def timing(event, segment):
        if event in {"asr_ready", "capture_sealed", "asr_final", "first_pcm_sent", "segment_sent"}:
            report(f"animal_timing event={event} turn={channel.key.turn_id} segment={segment} "
                   f"ms={round((clock() - started) * 1000)}")

    async def receive():
        raw = await channel.recv()
        if not isinstance(raw, str):
            raise ProtocolError("control required")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProtocolError("control object required")
        return value

    async def commit(receipt):
        if receipt:
            await channel.control("turn.committed", count=receipt.count,
                                  next_action=receipt.next_action, listen_id=receipt.listen_id,
                                  completed=(session.game or session.summary).completed)

    async def acknowledge(key, number):
        if type(number) is not int:
            raise ProtocolError("invalid acknowledgement")
        result = session.ack(key, number)
        if result:
            await channel.control("playback.segment_committed", number=number)
            await commit(result.commit)

    async def send_reply(reply):
        channel.key = reply.key
        started_at = clock()
        await channel.control("reply", segments=[dict(image_id=s.image_id) for s in reply.segments])
        async def segments():
            for segment in reply.segments:
                counts["tts"] += 1
                counts["tts_chars"] += len(segment.text)
                yield segment.text
        async with asyncio.timeout(limits.turn):
            count, _ = await deliver(channel, providers, RuleSpeech(), segments(), limits, started_at + limits.io)
            await channel.reply_ended(count)
            await commit(session.reply_end(reply.key, count))

    watch = observer.set(timing)
    try:
        async with asyncio.timeout(5):
            hello = await receive()
            if (hello["event"] != "session.start" or hello["v"] != 1
                    or set(hello["images"]) != {card.image_id for card in CARDS}):
                raise ProtocolError("catalog mismatch")
            try:
                session = channel.session = Session(secrets.randbits(32) if seed is None else seed, hello["catalog"])
            except ValueError as exc:
                raise ProtocolError("unsupported catalog") from exc
        await send_reply(session.reply)
        # A single coroutine owns all rule mutations. The outer handler cancels
        # and joins it on disconnect, including while waiting on a provider.
        async with asyncio.timeout(900):
            while session.game:
                async with asyncio.timeout(30):
                    message = await receive()
                event = message["event"]
                key = TurnKey(**message["key"])
                if event == "playback.segment_completed":
                    await acknowledge(key, message["number"])
                elif event == "turn.advance":
                    if reply := session.advance(key):
                        started = clock()
                        await send_reply(reply)
                elif event in {"turn.start", "listen.silence"}:
                    outcome = "start" if event == "turn.start" else "silence"
                    if not session.consume(key, message["listen_id"], outcome):
                        continue
                    started = clock()
                    if outcome == "start":
                        counts["asr"] += 1
                        async with asyncio.timeout(limits.turn):
                            async with recognize(channel, providers, limits, allow_empty=True) as (text, _):
                                # The provider delivers text without calibrated confidence.
                                # Apply exact phrases and context guards. Empty or ambiguous text clarifies.
                                reply = session.transcript(key, text)
                                del text
                                await send_reply(reply)
                    else:
                        await send_reply(session.reply)
                else:
                    raise ProtocolError("unsupported event")
        reason = session.summary.reason
    except (ProtocolError, json.JSONDecodeError, KeyError, TypeError):
        reason = "protocol_error"
    except TimeoutError:
        reason = "timeout"
    except DeviceDisconnected:
        reason = "disconnect"
    except Exception:
        reason = "provider_error"
    finally:
        observer.reset(watch)
        if session:
            if session.game:
                session.cancel(reason)
            for result in session.game_results:
                report(f"animal_result reason={result.reason} completed={result.completed}")
        report(f"animal_usage reason={reason} " + " ".join(f"{k}={v}" for k, v in counts.items()))
    if reason in {"protocol_error", "timeout", "provider_error"}:
        await socket.close(1008 if reason == "protocol_error" else 1011, reason)


def game_server(port, tls, token, providers, *, seed=None, report=print):
    if tls is None or not 32 <= len(token) <= 256 or not token.isascii() or not token.isalnum():
        raise ValueError("TLS and a 32–256 ASCII alphanumeric device token are required")
    expected = ("Bearer " + token).encode("ascii")
    active = False
    logger = logging.Logger("little_buddy.animal")
    logger.addHandler(logging.NullHandler())

    async def handshake(socket, request):
        if request.path == "/healthz":
            return socket.respond(HTTPStatus.OK, "ok\n")
        if request.path != "/v1/animal":
            return socket.respond(HTTPStatus.NOT_FOUND, "not found\n")
        values = request.headers.get_all("Authorization")
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), expected):
            return socket.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
        if active:
            return socket.respond(HTTPStatus.SERVICE_UNAVAILABLE, "busy\n")

    async def handler(socket):
        nonlocal active
        if active:
            await socket.close(1013, "busy")
            return
        active = True
        tasks = (asyncio.create_task(play_game(socket, providers, seed=seed, report=report)),
                 asyncio.create_task(socket.wait_closed()))
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            active = False

    return serve(handler, "127.0.0.1", port, ssl=tls, process_request=handshake,
                 origins=[None], compression=None, max_size=6406, max_queue=4,
                 open_timeout=4, close_timeout=1, ping_interval=5, ping_timeout=5,
                 server_header=None, logger=logger)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8444)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--provider", choices=("dashscope", "fake"), default="dashscope")
    args = parser.parse_args()
    if args.port == 8443:
        parser.error("8443 is reserved for the single-turn service")
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.cert, args.key)
    credential_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    token_file = Path(credential_dir) / "animal-device-token" if credential_dir else None
    token = token_file.read_text(encoding="ascii").strip() if token_file else os.environ.get("ANIMAL_DEVICE_TOKEN", "")
    async with http_client() as http:
        if args.provider == "fake":
            from backend.demo import Demo
            providers = Demo()
        else:
            providers = DashScope.from_environment(http)
        async with game_server(args.port, tls, token, providers, report=lambda line: print(line, flush=True)):
            print(f"animal_ready port={args.port}", flush=True)
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
