"""USB-only simulated game transport. One rule Session per connection."""
import asyncio
from dataclasses import asdict
import json

from websockets.asyncio.server import serve

from .rules import CARDS, CATALOG_VERSION
from .session import Session, TurnKey


async def game(socket):
    session = None
    ack_first = False
    duplicate = False
    hold_reveal = False

    async def send(event, **fields):
        await socket.send(json.dumps(dict(event=event, **fields), ensure_ascii=False))

    async def commit(receipt):
        if receipt:
            fields = asdict(receipt)
            fields.update(completed=session.game.completed if session.game else session.summary.completed)
            await send("turn.committed", **fields)
            if duplicate:
                await send("turn.committed", **fields)

    async def end(reply):
        await send("reply.end", key=asdict(reply.key), count=len(reply.segments))
        await commit(session.reply_end(reply.key, len(reply.segments)))

    async def reply(value):
        if value:
            for number in range(1, len(value.segments) + 1):
                assert session.segment_sent(value.key, number)
            await send("reply", **asdict(value))
            if not ack_first:
                await end(value)

    try:
        async for raw in socket:
            message = json.loads(raw)
            event = message["event"]
            if event == "session.start" and session is None:
                if set(message["images"]) != {card.image_id for card in CARDS}:
                    raise ValueError("catalog images mismatch")
                session = Session(0, message["catalog"])
                ack_first = message.get("ack_first") is True
                duplicate = message.get("duplicate") is True
                hold_reveal = message.get("hold_reveal") is True
                await reply(session.reply)
                continue
            if session is None:
                raise ValueError("missing session")
            key = TurnKey(**message["key"])
            if event == "playback.segment_completed":
                number = message["number"]
                current = session.reply
                if (hold_reveal and current and current.key == key
                        and 1 <= number <= len(current.segments) and current.segments[number - 1].image_id):
                    continue
                result = session.ack(key, number)
                if result:
                    fields = dict(key=asdict(key), number=result.segment_committed)
                    await send("playback.segment_committed", **fields)
                    if duplicate:
                        await send("playback.segment_committed", **fields)
                    await commit(result.commit)
                    if ack_first and session.reply and not session.declared and session.confirmed == len(session.reply.segments):
                        await end(session.reply)
            elif event in ("turn.start", "listen.silence"):
                outcome = "start" if event == "turn.start" else "silence"
                if session.consume(key, message["listen_id"], outcome):
                    if outcome == "start":
                        await reply(session.transcript(key, message["text"][:80], reliable=message.get("reliable", True)))
                    else:
                        await reply(session.reply)
            elif event == "turn.advance":
                await reply(session.advance(key))
            else:
                raise ValueError("unsupported event")
    except (KeyError, ValueError, TypeError):
        await socket.close(1008, "invalid fake game event")
    finally:
        if session:
            session.cancel("disconnect")


async def main():
    async with serve(game, "127.0.0.1", 8765, max_size=4096, max_queue=4):
        print(f"瓦力假服务 ws://127.0.0.1:8765 · {CATALOG_VERSION}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
