"""Deterministic script for the offline integration contract."""
from .rules import CATALOG_VERSION, RULE_VERSION
from .session import Playback, Session

SEED = 18


def play(session, playback):
    """Feed a fully played reply through the normal event API."""
    reply = session.reply
    key = reply.key
    op = key.turn_id
    assert playback.begin(reply, op)
    for number, _ in enumerate(reply.segments, start=1):
        assert session.segment_sent(key, number)
        assert playback.progress(key, op, number, complete=True)
        result = session.ack(key, number)
        assert playback.segment_committed(key, result.segment_committed)
    playback.reply_end(key, number)
    playback.committed(session.reply_end(key, number))
    playback.drain(key, op)
    playback.release(key, op)
    receipt = playback.ready(key, eligible=True, image_hold_done=True)
    assert receipt is not None
    return receipt


def say(session, receipt, text, *, reliable=True):
    assert session.consume(receipt.key, receipt.listen_id, "start")
    reply = session.transcript(receipt.key, text, reliable=reliable)
    assert reply is not None
    return reply


def main():
    session = Session(SEED, session_id="script")
    playback = Playback()
    playback.activate(session.session_id)
    receipt = play(session, playback)
    print(f"catalog={CATALOG_VERSION} rules={RULE_VERSION} seed={SEED}")
    for _ in range(3):
        card = session.game.card
        say(session, receipt, card.aliases[-1])
        receipt = play(session, playback)
        assert playback.image == (len(session.game.used), card.image_id)
        print(f"reveal={card.animal_id} image={card.image_id} completed={session.game.completed}")
        assert session.advance(receipt.key)
        receipt = play(session, playback)
    assert session.game.phase == "replay"
    say(session, receipt, "再玩一次")
    play(session, playback)
    assert session.game.completed == 0 and len(session.game.used) == 1
    print(f"replay={session.game.card.animal_id} completed=0 shown=1")
    session.cancel("stop")
    playback.cancel()
    assert session.game is None and playback.image is None
    print("stop=cleared")


if __name__ == "__main__":
    main()
