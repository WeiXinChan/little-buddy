"""Serial event-driven game integration API, independent of transport and audio."""
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from .chat import HELP, Chat, route
from .rules import CATALOG_VERSION, Game, Segment


@dataclass(frozen=True)
class TurnKey:
    session_id: str
    turn_id: int


@dataclass(frozen=True)
class Reply:
    key: TurnKey
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class Commit:
    key: TurnKey
    count: int
    next_action: str
    listen_id: str | None
    mode: str = "game"


@dataclass(frozen=True)
class Result:
    key: TurnKey
    segment_committed: int | None
    commit: Commit | None


@dataclass(frozen=True)
class Summary:
    reason: str
    completed: int

    @property
    def reached_three(self):
        return self.completed == 3


MAX_CHAT_TURNS = 3


class Session:
    """Call on one serial dispatcher. One instance owns one click session."""

    def __init__(self, seed, catalog_version=CATALOG_VERSION, *, session_id=None, conversation=False):
        if catalog_version != CATALOG_VERSION:
            raise ValueError("unsupported animal catalog")
        self.session_id = session_id if session_id is not None else uuid4().hex
        self.seed = seed
        self.conversation = conversation
        self.game_number = 0
        self.game = Game(seed)
        self.reply = None
        self.summary = None
        self.game_results = []
        self.terminal_receipt = None
        self.heard = []
        self.chat_history = []
        self.turn_id = 0
        self._stage(deepcopy(self.game), Game.next_card)

    def _stage(self, proposed, decide):
        segments, self.next_action = decide(proposed)
        self.switching = type(proposed) is not type(self.game)
        restarting = self.next_action == "restart"
        if restarting:
            self.game_number += 1
            proposed = Game(self.seed + self.game_number)
            segments, self.next_action = proposed.next_card()
        self.restarting = restarting
        self.turn_id += 1
        self.reply = Reply(TurnKey(self.session_id, self.turn_id), segments)
        self.proposed = proposed
        self.chat_input = None
        self.sent = 0
        self.confirmed = 0
        self.declared = False
        self.commit = None
        self.consumed = None

    def _current(self, key):
        return self.reply is not None and key == self.reply.key

    def segment_sent(self, key, number):
        """After emitting the complete segment and its validated sample count."""
        if self._current(key) and number == self.sent + 1 <= len(self.reply.segments):
            self.sent = number
            return True
        return False

    def reply_end(self, key, count):
        terminal = self.terminal_receipt
        if terminal and terminal.key == key and terminal.count == count:
            return terminal
        if not self._current(key) or count != len(self.reply.segments) or count != self.sent:
            return None
        self.declared = True
        return self._commit_reply()

    def ack(self, key, number):
        terminal = self.terminal_receipt
        if terminal and terminal.key == key and 1 <= number <= terminal.count:
            return Result(key, number, terminal)
        if not self._current(key) or not 1 <= number <= min(self.sent, self.confirmed + 1):
            return None
        if number == self.confirmed + 1:
            self.confirmed = number
            if not self.switching:
                self.heard.append(self.reply.segments[number - 1].text)
                del self.heard[:-9]
            if self.chat_input is not None:
                # Only a new contiguous ACK can create or extend this turn's pair.
                turn = (self.chat_input, "".join(segment.text for segment in self.reply.segments[:number]))
                if number == 1:
                    self.chat_history.append(turn)
                    del self.chat_history[:-MAX_CHAT_TURNS]
                else:
                    self.chat_history[-1] = turn
        return Result(key, number, self._commit_reply())

    def _commit_reply(self):
        if self.commit is None and self.declared and self.confirmed == len(self.reply.segments):
            key = self.reply.key
            listen_id = f"{key.session_id}:{key.turn_id}" if self.next_action == "listen" else None
            mode = "chat" if isinstance(self.proposed, Chat) else "game"
            receipt = Commit(key, self.confirmed, self.next_action, listen_id, mode)
            if self.restarting:
                self.game_results.append(Summary("complete", self.game.completed))
            if self.switching:
                self.chat_history.clear()
                self.heard[:] = [segment.text for segment in self.reply.segments]
            self.game = self.proposed
            if self.next_action == "end":
                self.cancel(self.game.reason)
                self.terminal_receipt = receipt
            else:
                self.commit = receipt
            return receipt
        return self.commit

    def advance(self, key):
        """After client playback release and image hold. Retries use the same key."""
        if self._current(key) and self.commit and self.commit.next_action == "advance":
            self._stage(deepcopy(self.game), Game.advance)
            return self.reply
        return None

    def consume(self, key, listen_id, outcome):
        """Accept first start/silence. True authorizes the corresponding effect once."""
        if (not self._current(key) or not self.commit or not self.commit.listen_id
                or self.commit.listen_id != listen_id or self.consumed is not None
                or outcome not in {"start", "silence"}):
            return False
        self.consumed = outcome
        if outcome == "silence":
            self._stage(deepcopy(self.game), self._silence)
        return True

    def _silence(self, state):
        if self.conversation and state.silences == 1:
            state.reason = "silence"
            return (), "end"
        return state.silence()

    def chat_request(self, key, text):
        if (self._current(key) and self.consumed == "start"
                and isinstance(self.game, Chat) and route(text, True) == "answer"):
            return tuple(self.chat_history)
        return None

    def transcript(self, key, text, *, reliable=True, answer=(), needs_adult=False):
        """Accept one final ASR result for a consumed start, including empty results."""
        if self._current(key) and self.consumed == "start":
            intent = route(text, reliable) if self.conversation else None
            if needs_adult:
                intent = "help"
            if isinstance(self.game, Chat):
                if intent == "game":
                    self.game_number += 1
                    self._stage(Game(self.seed + self.game_number), Game.next_card)
                else:
                    self._stage(deepcopy(self.game), lambda chat: chat.respond(intent, answer))
                    if intent == "answer":
                        self.chat_input = text
            elif intent == "chat":
                self._stage(Chat(), lambda chat: chat.respond(intent, ()))
            elif intent == "help":
                self._stage(deepcopy(self.game), lambda game: game.finish("help", HELP))
            else:
                self._stage(deepcopy(self.game), lambda game: game.respond(text, reliable))
            if self.restarting:
                self.heard.clear()
            return self.reply
        return None

    def limit(self):
        # Replace the staged reply before transport observes its turn key.
        assert self.sent == 0
        self.proposed = deepcopy(self.game)
        self.proposed.reason = "usage_limit"
        self.reply = Reply(self.reply.key, (Segment("今天先聊到这里吧。"),))
        self.next_action = "end"
        self.chat_input = None
        self.switching = self.restarting = False
        return self.reply

    def cancel(self, reason):
        self.terminal_receipt = None
        if self.reply is None:
            return
        self.summary = Summary(reason, self.game.completed)
        self.game_results.append(self.summary)
        self.reply = self.game = self.proposed = self.commit = self.consumed = None
        self.heard.clear()
        self.chat_history.clear()
        self.chat_input = None


class Playback:
    """Client-side contract model for each device, across session generations.

    A TurnKey must never be reused. op_id identifies the exact playback handle.
    True from ready() claims one action. Audio callbacks remain external.
    """

    def __init__(self):
        self.reply = None
        self.handle = None
        self.image = None
        self.session_id = None
        self.last_turn = 0

    def activate(self, session_id):
        self.cancel()
        self.session_id = session_id

    def begin(self, reply, op_id):
        if (self.handle is not None or reply.key.session_id != self.session_id
                or reply.key.turn_id != self.last_turn + 1
                or (self.reply is not None and not self.claimed)):
            return False
        self.reply = reply
        self.last_turn = reply.key.turn_id
        self.handle = (reply.key, op_id)
        self.op_id = op_id
        self.played = self.confirmed = 0
        self.partial = None
        self.ended = self.drained = self.released = self.claimed = self.listening = False
        self.receipt = None
        self.image = None
        return True

    def _matches(self, key, op_id):
        return self.reply is not None and key == self.reply.key and op_id == self.op_id

    def progress(self, key, op_id, number, *, complete):
        """The adapter reports only verified playback head progress, never enqueue."""
        if self.handle != (key, op_id) or not self._matches(key, op_id):
            return False
        if number != self.played + 1 or number > len(self.reply.segments):
            return False
        if complete:
            self.played = number
            self.partial = None
        else:
            self.partial = number
        return True

    def segment_committed(self, key, number):
        if self.reply is None or key != self.reply.key or number != self.confirmed + 1 or number > self.played:
            return False
        self.confirmed = number
        segment = self.reply.segments[number - 1]
        if segment.image_id:
            self.image = (segment.question, segment.image_id)
        return True

    @property
    def heard(self):
        if self.reply is None:
            return (), None
        prefix = tuple(segment.text for segment in self.reply.segments[:self.confirmed])
        return prefix, self.partial

    def reply_end(self, key, count):
        if self.reply is not None and key == self.reply.key and count == len(self.reply.segments):
            self.ended = True

    def committed(self, receipt):
        if self.reply is not None and receipt.key == self.reply.key and receipt.count == len(self.reply.segments):
            self.receipt = receipt

    def drain(self, key, op_id):
        if self._matches(key, op_id) and self.played == len(self.reply.segments):
            self.drained = True

    def release(self, key, op_id):
        if self.handle != (key, op_id):
            return
        self.handle = None
        if self._matches(key, op_id):
            self.released = True

    def ready(self, key, *, eligible, image_hold_done=False):
        if (self.reply is None or key != self.reply.key or self.claimed or not eligible
                or not self.receipt or not self.ended or not self.drained or not self.released
                or self.confirmed != len(self.reply.segments)
                or (self.receipt.next_action == "advance" and not image_hold_done)):
            return None
        self.claimed = True
        receipt = self.receipt
        if receipt.next_action == "end":
            self.cancel()
        return receipt

    def first_frame(self, key, listen_id):
        if (self.reply is not None and key == self.reply.key and self.claimed and self.receipt.listen_id
                and self.receipt.listen_id == listen_id and not self.listening):
            self.listening = True
            return True
        return False

    def cancel(self):
        self.reply = self.image = self.receipt = self.partial = self.session_id = None
        self.last_turn = 0
        self.listening = False
        # A cancelled operation retains its handle until its exact release callback.
