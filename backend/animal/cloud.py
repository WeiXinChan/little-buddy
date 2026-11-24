"""Private game transport. Run on a separate loopback TLS listener."""
import argparse
from collections import deque
import asyncio
import ctypes
from dataclasses import asdict
import hmac
from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import ssl
import time

from websockets.asyncio.server import serve

from backend.dashscope import DashScope, http_client
from backend.server import Channel, DeviceDisconnected
from backend.timing import observer
from backend.voice import End, Limits, ProtocolError, deliver, recognize
from backend.wire import decode_input
from .chat import FALLBACK, RISK, approved, normalized
from .rules import CARDS
from .session import Session, TurnKey


async def chat_answer(providers, text, history, counts):
    counts["llm"] += 1
    async with asyncio.timeout(4):
        async with providers.answer(text, history=history) as response:
            sentences = []
            async for sentence in response:
                if RISK.search(normalized("".join((*sentences, sentence)))):
                    return True, ()
                if len(sentences) == 3 or not approved(sentence):
                    return False, (FALLBACK,)
                sentences.append(sentence)
            return False, tuple(sentences)


class GameChannel(Channel):
    def __init__(self, socket):
        super().__init__(socket)
        self.key = None
        self.session = None
        self.receipts = asyncio.Lock()
        self.counts = dict(asr=0, asr_samples=0, tts=0, tts_chars=0, llm=0)

    async def control(self, kind, **fields):
        await self.send(json.dumps(dict(event=kind, key=asdict(self.key), **fields)))

    async def segment_ended(self, number, samples):
        async with self.receipts:
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
        return text  # Templates and pre-screened model sentences.


async def play_game(socket, providers, *, seed=None, report=print, trial_limits=False):
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
                                  mode=receipt.mode, completed=(session.game or session.summary).completed)

    async def acknowledge(key, number):
        if type(number) is not int:
            raise ProtocolError("invalid acknowledgement")
        async with channel.receipts:
            result = session.ack(key, number)
            if result:
                await channel.control("playback.segment_committed", number=number)
                await commit(result.commit)

    async def send_reply(reply, cleanup=None):
        if (trial_limits and session.next_action != "end" and
                (counts["tts"] + len(reply.segments) >= 64 or counts["asr"] >= 24 or counts["llm"] >= 12)):
            reply = session.limit()
        channel.key = reply.key
        started_at = clock()
        await channel.control("reply", segments=[dict(image_id=s.image_id) for s in reply.segments])

        async def segments():
            for segment in reply.segments:
                counts["tts"] += 1
                counts["tts_chars"] += len(segment.text)
                yield segment.text

        async def produce():
            async with asyncio.timeout(limits.turn):
                count, _ = await deliver(channel, providers, RuleSpeech(), segments(), limits, started_at + limits.io)
                async with channel.receipts:
                    await channel.reply_ended(count)
                    await commit(session.reply_end(reply.key, count))
                if cleanup is not None:
                    await asyncio.shield(cleanup)

        # While emitting audio and retiring providers, only ACKs can mutate
        # this reply. Do not overlap socket readers or start another provider.
        producer = asyncio.create_task(produce())
        reader = asyncio.create_task(receive())
        pending = None
        try:
            while True:
                ready, _ = await asyncio.wait((producer, reader), return_when=asyncio.FIRST_COMPLETED)
                if reader in ready:
                    message = reader.result()
                    kind = message["event"]
                    key = TurnKey(**message["key"])
                    if kind == "playback.segment_completed":
                        await acknowledge(key, message["number"])
                    elif kind in {"turn.start", "listen.silence", "turn.advance"}:
                        receipt = session.commit
                        if receipt and receipt.key == key and pending is None:
                            if kind == "turn.advance":
                                if receipt.next_action == "advance":
                                    pending = message
                            elif receipt.listen_id and receipt.listen_id == message.get("listen_id"):
                                pending = message
                    else:
                        raise ProtocolError("unsupported event during reply")
                if producer in ready:
                    producer.result()
                    return pending
                reader = asyncio.create_task(receive()) if reader.done() else reader
        finally:
            for task in (producer, reader):
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer, reader, return_exceptions=True)

    watch = observer.set(timing)
    try:
        async with asyncio.timeout(5):
            hello = await receive()
            if (hello["event"] != "session.start" or hello["v"] != 1
                    or set(hello["images"]) != {card.image_id for card in CARDS}):
                raise ProtocolError("catalog mismatch")
            wake = hello.get("wake") is True and hello.get("conversation") is True
            try:
                session = channel.session = Session(
                    secrets.randbits(32) if seed is None else seed, hello["catalog"],
                    conversation=hello.get("conversation") is True, wake=wake,
                )
            except ValueError as exc:
                raise ProtocolError("unsupported catalog") from exc
        pending = await send_reply(session.reply)
        # The outer handler cancels and joins this session on disconnect.
        # Only trials have a total deadline; every session retains per-operation limits.
        async with asyncio.timeout(900 if trial_limits else None):
            while session.game:
                async with asyncio.timeout(30):
                    message = pending if pending is not None else await receive()
                pending = None
                event = message["event"]
                key = TurnKey(**message["key"])
                if event == "playback.segment_completed":
                    await acknowledge(key, message["number"])
                elif event == "turn.advance":
                    if reply := session.advance(key):
                        started = clock()
                        pending = await send_reply(reply)
                elif event in {"turn.start", "listen.silence"}:
                    outcome = "start" if event == "turn.start" else "silence"
                    if not session.consume(key, message["listen_id"], outcome):
                        continue
                    started = clock()
                    if outcome == "start":
                        counts["asr"] += 1
                        async with asyncio.timeout(limits.turn):
                            async with recognize(channel, providers, limits, allow_empty=True) as (text, cleanup):
                                # The provider delivers text without calibrated confidence.
                                # Apply exact phrases and context guards. Empty or ambiguous text clarifies.
                                if wake and key.turn_id == 1:
                                    text = re.sub(r"^\s*瓦力[，、。！？,.!?\s]*瓦力[，、。！？,.!?\s]*", "", text, count=1)
                                history = session.chat_request(key, text)
                                needs_adult, answer = False, ()
                                if history is not None:
                                    needs_adult, answer = await chat_answer(providers, text, history, counts)
                                reply = session.transcript(key, text, answer=answer, needs_adult=needs_adult)
                                del text, history, answer
                                pending = await send_reply(reply, cleanup)
                    else:
                        pending = await send_reply(session.reply)
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


def game_server(port, tls, token, providers, *, seed=None, report=print, trial_limits=False,
                bind="127.0.0.1", authority=None, expires_at=None):
    if tls is None or not 32 <= len(token) <= 256 or not token.isascii() or not token.isalnum():
        raise ValueError("TLS and a 32–256 ASCII alphanumeric device token are required")
    expected = ("Bearer " + token).encode("ascii")
    active = False
    attempts = deque()
    logger = logging.Logger("little_buddy.animal")
    logger.addHandler(logging.NullHandler())

    async def handshake(socket, request):
        if request.path == "/healthz" and socket.remote_address[0] in {"127.0.0.1", "::1"}:
            return socket.respond(HTTPStatus.OK, "ok\n")
        if (request.path != "/v1/animal" or
                (authority is not None and request.headers.get_all("Host") != [authority])):
            return socket.respond(HTTPStatus.NOT_FOUND, "not found\n")
        values = request.headers.get_all("Authorization")
        if (len(values) != 1 or not hmac.compare_digest(values[0].encode(), expected)
                or (expires_at is not None and time.time() >= expires_at)):
            return socket.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
        if expires_at is not None:
            now = time.monotonic()
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 6:
                return socket.respond(HTTPStatus.TOO_MANY_REQUESTS, "slow down\n")
            attempts.append(now)
        if active:
            return socket.respond(HTTPStatus.SERVICE_UNAVAILABLE, "busy\n")

    async def handler(socket):
        nonlocal active
        if active:
            await socket.close(1013, "busy")
            return
        active = True
        tasks = (asyncio.create_task(play_game(socket, providers, seed=seed, report=report,
                                               trial_limits=trial_limits)),
                 asyncio.create_task(socket.wait_closed()))
        try:
            remaining = None if expires_at is None else max(0, expires_at - time.time())
            done, _ = await asyncio.wait(tasks, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                await socket.close(1008, "device credential expired")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            active = False

    return serve(handler, bind, port, ssl=tls, process_request=handshake,
                 origins=[None], compression=None, max_size=6406, max_queue=4,
                 ssl_handshake_timeout=4, open_timeout=4, close_timeout=1, ping_interval=5, ping_timeout=5,
                 server_header=None, logger=logger)


def disable_core_dumps():
    # Linux ignores RLIMIT_CORE for a piped core handler. Set the process flag
    # before loading any TLS or provider credentials.
    pr_set_dumpable = 4
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(pr_set_dumpable, 0, 0, 0, 0) != 0:
        raise RuntimeError("standalone could not disable core dumps")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8444)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--provider", choices=("dashscope", "fake"), default="dashscope")
    parser.add_argument("--trial-limits", action="store_true", help="enable per-session trial quotas")
    parser.add_argument("--standalone", action="store_true")
    args = parser.parse_args()
    if args.port == 8443:
        parser.error("8443 is reserved for the single-turn service")
    if args.standalone:
        disable_core_dumps()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.cert, args.key)
    credential_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    token_file = Path(credential_dir) / "animal-device-token" if credential_dir else None
    token = token_file.read_text(encoding="ascii").strip() if token_file else os.environ.get("ANIMAL_DEVICE_TOKEN", "")
    options = {}
    if args.standalone:
        # Only the standalone unit requires these credentials. Legacy private fixtures
        # continue to use their original invocation and listener.
        if not credential_dir or args.port in {80, 8444, 9444}:
            parser.error("standalone requires dedicated credentials and a dedicated port")
        expiry_file = Path(credential_dir) / "animal-device-expiry"
        expiry = expiry_file.read_text(encoding="ascii").strip()
        authority = os.environ.get("LITTLE_BUDDY_AUTHORITY", "")
        if (not re.fullmatch(r"[a-z0-9.-]+(?::[1-9][0-9]{0,4})?", authority)
                or (":" in authority and not 1 <= int(authority.rsplit(":", 1)[1]) <= 65535)
                or authority.endswith(":443")
                or not re.fullmatch(r"[0-9]{1,12}", expiry) or int(expiry) <= time.time()
                or not re.fullmatch(r"[0-9a-f]{64}", token)):
            parser.error("invalid standalone authority, device expiry or device credential")
        options = dict(authority=authority, expires_at=int(expiry),
                       bind=os.environ.get("LITTLE_BUDDY_BIND", "127.0.0.1"))
    stopped = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopped.set)
    async with http_client() as http:
        if args.provider == "fake":
            from backend.demo import Demo
            providers = Demo()
        else:
            providers = DashScope.from_environment(http)
        async with game_server(args.port, tls, token, providers, trial_limits=args.trial_limits,
                               report=lambda line: print(line, flush=True), **options):
            print(f"animal_ready port={args.port}", flush=True)
            await stopped.wait()


if __name__ == "__main__":
    asyncio.run(main())
