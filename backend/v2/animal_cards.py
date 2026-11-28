"""Closed voice-only catalogue. No child, history or model text is interpolated."""
import re
from typing import NamedTuple


class Card(NamedTuple):
    answer: str
    clue: str
    correct: str
    another_clue: str


CARDS = (
    Card('兔子', '它有长长的耳朵，短短的尾巴，蹦蹦跳跳向前跑。你猜是谁？',
         '对啦！就是兔子。还想再猜一题吗？', '还没猜中。再想想，谁有两只长耳朵，还会蹦蹦跳跳？'),
    Card('大象', '它有长长的鼻子，大大的耳朵，还会用鼻子卷起青草。你猜是谁？',
         '对啦！就是大象。还想再猜一题吗？', '还没猜中。再想想，谁能用长鼻子卷起青草？'),
    Card('长颈鹿', '它的脖子很长，站着就能吃到高高树枝上的叶子。你猜是谁？',
         '猜对了，是长颈鹿！还要继续吗？', '还没猜中。它的脖子长，身上还有一块一块的斑纹。'),
    Card('斑马', '它看起来像马，身上却有黑白相间的条纹。你猜是谁？',
         '没错，是斑马！还想玩一题吗？', '还没猜中。它有马蹄，身上有黑白条纹。'),
)

OPEN = re.compile(r'(?:(?:我们|咱们)?(?:一起|来)?(?:玩)?猜动物(?:游戏)?(?:吧|好吗)?|玩个猜动物的游戏吧)')
NEXT = re.compile(r'(?:再给我出一个新的动物谜语|再来一题|换个动物|再出一道(?:题)?|再给我出一题)(?:吧)?')
NAMES = {'小兔子':'兔子', **{c.answer:c.answer for c in CARDS}}
GUESS = re.compile(r'(?:我猜是|我猜|是)?('+'|'.join(map(re.escape,NAMES))+')')


def propose(text, session, owner):
    if not isinstance(text,str) or session.private_mode or session.management_paused:return None
    # Match the entire utterance. Question punctuation is accepted for game
    # invitations but a tentative answer is left to the semantic path.
    raw=text.strip();word=raw.rstrip('。.!！?？')
    mode=session.game.get('mode')
    if OPEN.fullmatch(word) and mode in (None,'chat') and not session.secrets:
        index=0;action='change';sentence=CARDS[index].clue
    else:
        if not owner or owner[:2]!=(session.session,session.topic):return None
        index=owner[2];card=CARDS[index]
        if mode!='guess' or session.game.get('guess_role')!='setter' or session.secrets!={'answer':card.answer}:return None
        if NEXT.fullmatch(word):
            index=(index+1)%len(CARDS);action='change';sentence=CARDS[index].clue
        elif (guess:=GUESS.fullmatch(word)) and not raw.endswith(('？','?')):
            action='continue';sentence=card.correct if NAMES[guess[1]]==card.answer else card.another_clue
        else:return None
    return index,dict(mode='guess',action=action,guess_role='setter',roles=['瓦力出题','孩子猜'],
                      rules='根据动物线索猜答案。',secrets={'answer':CARDS[index].answer},
                      sentences=[sentence],anchors={},tools=[])
