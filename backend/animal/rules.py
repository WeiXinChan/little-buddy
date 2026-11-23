"""Deterministic decisions for the click-to-play animal catalog."""
import random
import re
import unicodedata
from dataclasses import dataclass

CATALOG_VERSION = "animal-click-1"
RULE_VERSION = "animal-rules-3"


@dataclass(frozen=True)
class Card:
    animal_id: str
    name: str
    clues: tuple[str, ...]
    aliases: tuple[str, ...]
    confusions: tuple[str, ...]

    @property
    def image_id(self):
        return f"animal-{self.animal_id}"


CARDS = (
    Card("dog", "狗", ("它有四条腿。", "它喜欢摇尾巴。", "它会汪汪叫。"),
         ("狗", "小狗", "狗狗"), ("猫",)),
    Card("cat", "猫", ("它走路轻轻的。", "它有长胡须。", "它会喵喵叫。"),
         ("猫", "小猫", "猫咪"), ("狗", "兔")),
    Card("duck", "鸭", ("它会在水里游。", "它的脚趾中间连着一层皮。", "它会嘎嘎叫。"),
         ("鸭", "鸭子", "小鸭"), ("鸡", "鹅")),
    Card("rabbit", "兔", ("它会蹦蹦跳。", "它的尾巴短短的。", "它的耳朵长长的。"),
         ("兔", "兔子", "小兔"), ("猫",)),
    Card("elephant", "象", ("它的身体很大。", "它的耳朵很大。", "它的鼻子像长长的管子。"),
         ("象", "大象", "小象"), ("长颈鹿",)),
    Card("giraffe", "长颈鹿", ("它身上有斑块。", "它能吃到高处的叶子。", "它的脖子特别长。"),
         ("长颈鹿", "小长颈鹿"), ("鹿", "大象")),
)

ALIASES = {alias: card for card in CARDS for alias in card.aliases}
OTHER_ANIMALS = frozenset({"鸡", "小鸡", "鹅", "鹿", "熊", "老虎", "狮子", "猪", "鱼", "马", "牛", "羊"})
COMMANDS = {
    "hint": (
        "提示", "给我提示", "再给一个提示", "再说一个提示",
        "再提示一下", "提示一下", "再给我一点提示", "我不知道", "不知道",
    ),
    "answer": ("告诉我答案", "我想知道答案", "说答案", "公布答案", "是什么动物"),
    "skip": ("换一个", "换题", "下一题"),
    "yes": ("是", "对", "好", "可以", "要"),
    "replay": ("再玩", "再玩一次"),
    "no": ("不是", "不对", "不要", "不", "不用", "别告诉我", "不想知道"),
    "decline_replay": ("不想再玩",),
    "exit": ("退出", "再见", "不玩了", "停止", "停一下"),
    "chat": ("我想聊天", "聊聊天", "我们聊天吧"),
    "help": ("我受伤了", "我好害怕", "我害怕", "我流血了"),
}
INTENTS = {phrase: intent for intent, phrases in COMMANDS.items() for phrase in phrases}


def classify(text, reliable):
    normalized = unicodedata.normalize("NFKC", text)
    phrases = re.findall(r"[\w]+", normalized)
    urgent = [INTENTS.get(phrase) for phrase in phrases]
    for intent in ("help", "exit"):
        if intent in urgent:
            return intent, None
    phrase = "".join(phrases)
    if reliable and phrase in INTENTS:
        return INTENTS[phrase], None
    match = re.fullmatch(r"(?:我猜(?:是)?|我觉得是|是)?(.+?)(?:吧|呀|啊)?", phrase)
    candidate = match[1] if match else ""
    if candidate in ALIASES or candidate in OTHER_ANIMALS:
        return ("guess" if reliable else "unclear"), candidate
    if not phrase or not reliable or any(word in phrase for word in ("还是", "不是", "或者", "不对", "提示", "答案")):
        return "unclear", None
    if any(alias in phrase for alias in ALIASES) or any(item in INTENTS for item in phrases):
        return "unclear", None
    return "off_topic", None


@dataclass(frozen=True)
class Segment:
    text: str
    image_id: str | None = None
    question: int | None = None


class Game:
    """One in-memory game. Session installs changes only on reply commit."""

    def __init__(self, seed):
        self.deck = list(range(len(CARDS)))
        random.Random(seed).shuffle(self.deck)
        self.used = []
        self.completed = 0
        self.phase = "guess"
        self.silences = 0
        self.pending = None
        self.resume = "guess"
        self.reason = None
        self.clue_index = 0
        self.wrong = 0
        self.refused = False

    @property
    def card(self):
        return CARDS[self.used[-1]]

    def say(self, text):
        return (Segment(text),), "listen"

    def finish(self, reason, text):
        self.reason = reason
        return (Segment(text),), "end"

    def next_card(self):
        if not self.deck:
            return self.finish("exhausted", "这次的动物都出完啦。下次再玩吧！")
        self.used.append(self.deck.pop())
        self.clue_index = 1
        self.wrong = 0
        self.refused = False
        self.pending = None
        self.resume = self.phase = "guess"
        return self.say("猜猜它是谁？" + self.card.clues[0])

    def reveal(self, *, guessed_correctly):
        self.pending = None
        self.completed += 1
        follow_up = "你猜对啦！" if guessed_correctly else "我们看看它的样子，再玩下一题吧。"
        return (
            Segment(f"答案是{self.card.name}！", self.card.image_id, len(self.used)),
            Segment(follow_up),
        ), "advance"

    def advance(self):
        if self.completed == 3:
            self.phase = "replay"
            return self.say("我们猜完三道题啦！还想再玩一次吗？")
        return self.next_card()

    def repeat(self):
        if self.phase == "confirm":
            prompt = f"你说的是{self.pending}吗？" if self.pending else "能再说清楚一点吗？"
            return self.say(prompt)
        if self.phase == "replay":
            return self.say("想再玩一次吗？")
        if self.phase == "offer":
            return self.say("想知道答案吗？")
        return self.say("再猜猜吧！" + self.card.clues[self.clue_index - 1])

    def clue(self, requested):
        if not self.refused and (self.clue_index == len(self.card.clues) or self.wrong >= 2):
            self.phase = "offer"
            return self.repeat()
        if self.refused and not requested:
            return self.say("再猜猜吧，也可以说换题。")
        if self.clue_index == len(self.card.clues):
            return self.say("提示说完啦，再猜猜，或者说换题。")
        text = self.card.clues[self.clue_index]
        self.clue_index += 1
        return self.say(text)

    def silence(self):
        self.silences += 1
        if self.silences >= 2:
            return self.finish("silence", "我们先休息一下，下次再玩。")
        return self.say("你还想接着玩吗？有需要可以说停一下。")

    def respond(self, text, reliable):
        after_silence_prompt = self.silences == 1
        self.silences = 0
        intent, candidate = classify(text, reliable)
        if intent == "help":
            return self.finish("help", "请找身边的大人来帮忙。")
        if intent == "exit":
            return self.finish("exit", "好，下次再玩！")
        if intent == "chat":
            return self.finish("chat", "我们先结束猜动物。回到待机后可以使用语音入口。")

        if after_silence_prompt:
            # The committed silence prompt temporarily owns the yes/no context.
            if intent == "no":
                return self.finish("exit", "好，下次再玩！")
            if intent in {"yes", "unclear"} or self.phase == "replay":
                return self.repeat()

        context = self.resume if self.phase == "confirm" else self.phase
        if context == "replay":
            intent = {"replay": "yes", "decline_replay": "no"}.get(intent, intent)

        if self.phase == "confirm":
            self.phase = self.resume
            pending, self.pending = self.pending, None
            if intent == "yes" and pending:
                intent, candidate = "guess", pending
            elif intent in {"yes", "no", "unclear"}:
                return self.repeat()

        if intent == "unclear" or (self.phase == "replay" and intent not in {"yes", "no"}):
            self.resume, self.phase = self.phase, "confirm"
            self.pending = candidate if self.resume != "replay" else None
            return self.repeat()

        if self.phase == "replay":
            if intent == "yes":
                return (), "restart"
            return self.finish("complete", "好，下次再玩！")

        if self.phase == "offer":
            if intent == "yes":
                return self.reveal(guessed_correctly=False)
            self.phase = "guess"
            if intent == "no":
                self.refused = True
                return self.repeat()

        if intent == "skip":
            return self.next_card()
        if intent == "answer":
            return self.reveal(guessed_correctly=False)
        if intent == "guess":
            if ALIASES.get(candidate) == self.card:
                return self.reveal(guessed_correctly=True)
            self.wrong += 1
            return self.clue(requested=False)
        if intent == "hint":
            self.wrong = 0
            return self.clue(requested=True)
        if intent == "off_topic":
            return self.say("我们接着猜动物吧！" + self.card.clues[self.clue_index - 1])
        return self.repeat()
