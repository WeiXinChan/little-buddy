"""Short chat policy for the product conversation."""
import re
import unicodedata

from .rules import Segment, classify

HELP = "请找身边的大人来帮忙。"
FALLBACK = "我们聊聊你喜欢的动物吧。"
RISK = re.compile(
    r"受伤|流血|疼|痛|难受|不舒服|生病|害怕|喘不过气|呼吸不了|晕倒|吞了|卡住|"
    r"自杀|去死|想死|杀人|打死|打人|虐待|爆炸|炸弹|枪|刀|玩火|点火|"
    r"触电|喝药|吃药|跳楼|煤气|毒|色情|脱衣|裸照|摸.{0,4}隐私|"
    r"别告诉.{0,4}(?:爸爸|妈妈|家长|大人)|忽略.{0,6}(?:指令|规则)"
)
PRIVATE = re.compile(
    r"名字|姓名|我叫|你叫|地址|住在|在哪住|手机号|电话号码|联系方式|"
    r"身份证|密码|学校|幼儿园|微信|[0-9]{4,}|https?"
)
START_GAME = {"玩猜动物", "猜动物", "我要玩猜动物", "我想玩猜动物", "我们玩猜动物吧"}


def normalized(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def route(text, reliable):
    phrase = normalized(text)
    intent, _ = classify(text, reliable)
    if RISK.search(phrase) or intent == "help":
        return "help"
    if intent in {"exit", "chat"}:
        return intent
    if reliable and phrase in START_GAME:
        return "game"
    if not phrase or not reliable or len(text) > 100:
        return "clarify"
    if PRIVATE.search(phrase):
        return "private"
    return "answer"


def approved(segment):
    phrase = normalized(segment)
    return (0 < len(segment) <= 36 and bool(phrase)
            and re.fullmatch(r"[\u3400-\u9fff，、。！？,.!? ]+", segment)
            and not RISK.search(phrase) and not PRIVATE.search(phrase)
            and sum(segment.count(mark) for mark in "。！？.!?") <= 1)


class Chat:
    completed = 0
    reason = None

    def __init__(self):
        self.silences = 0

    def silence(self):
        self.silences += 1
        return (Segment("你还想聊一会儿吗？"),), "listen"

    def respond(self, intent, answer):
        self.silences = 0
        if intent in {"exit", "help"}:
            self.reason = intent
            return (Segment(HELP if intent == "help" else "好，下次见！"),), "end"
        text = {
            "private": ("我们聊点别的吧。",),
            "clarify": ("可以再说一次吗？",),
            "chat": ("好呀，你想聊什么？",),
        }.get(intent, answer or (FALLBACK,))
        return tuple(Segment(sentence) for sentence in text), "listen"
