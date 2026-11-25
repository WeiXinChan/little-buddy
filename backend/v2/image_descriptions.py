"""Minimal grounded visual vocabulary, never a conversation-to-image prompt passthrough."""
import asyncio
from collections import deque
import re
import time
import weakref
from backend.v2.dynamic_images import ImageFailure

COLORS={'blue':'蓝色','red':'红色','yellow':'黄色','green':'绿色','purple':'紫色','pink':'粉色',
        'orange':'橙色','white':'白色','black':'黑色','silver':'银色','gold':'金色','rainbow':'彩虹色'}
OUTFITS={'spacesuit':'宇航服','raincoat':'雨衣','cape':'披风','dress':'裙子','scarf':'围巾',
         'hat':'帽子','sweater':'毛衣','overalls':'背带裤','boots':'靴子','crown':'皇冠'}
SETTINGS={'moon':'月球','space':'太空','forest':'森林','garden':'花园','beach':'海滩','ocean':'海底',
          'mountain':'山上','clouds':'云朵','castle':'城堡','snow':'雪地','rainbow':'彩虹','meadow':'草地'}
ACTIONS={'walking':'散步','flying':'飞行','dancing':'跳舞','reading':'看书','painting':'画画',
         'playing':'玩耍','sleeping':'睡觉','waving':'挥手','exploring':'探险','singing':'唱歌'}
PROPS={'ball':'球','kite':'风筝','flag':'旗子','flower':'花朵','book':'书','umbrella':'雨伞',
       'rocket':'火箭','star':'星星','balloon':'气球','lantern':'灯笼'}
VOCAB={'color':COLORS,'outfit':OUTFITS,'setting':SETTINGS,'action':ACTIONS,'prop':PROPS}
ASK=re.compile(r'画|绘|生成|给我看|看一下|看看|再看|改成|换成|改为|修改|变成|穿上|戴上|再来一张')


def explicit_request(text):
    return (isinstance(text,str) and ASK.search(text) is not None and
            re.search(r'(?:不要|别|不用|不想|停止|取消).{0,4}(?:画|生成|看图|配图|生图)',text) is None)


class ExplicitImageRequest(dict):
    """Local PLAN provenance for a current explicit image request; not wire data."""


class MinimalDescription:
    """Owned bounded canonical art bytes, no caption/source/identity retained.

    Unsent proposals expire after 15s; destruction and dispatch completion release
    the buffer. The timer holds only a weakref, so cancelled plans are not retained.
    """
    def __init__(self,phrase):
        self._data=bytearray(phrase.encode());self._released=False
        loop=asyncio.get_running_loop();self.deadline=loop.time()+15.
        ref=weakref.ref(self)
        def expire():
            value=ref()
            if value is not None:value.release()
        self._timer=loop.call_at(self.deadline,expire)

    def read(self):
        if self._released or asyncio.get_running_loop().time()>=self.deadline:
            self.release();raise ImageFailure('prompt')
        return self._data.decode()

    def release(self):
        if not self._released:
            self._released=True;self._timer.cancel();self._data[:]=b'\0'*len(self._data);self._data.clear()

    def __del__(self):self.release()


def compile_description(value,*,request,text,context,plan,catalogue):
    if (type(value) is not dict or set(value)-({'subject'}|set(VOCAB)) or 'subject' not in value or
        plan['action'] in {'private','handoff','end'} or context.get('private') or
        not explicit_request(text)):
        raise ImageFailure('prompt')
    names={entry['id']:entry['name'] for entry in catalogue}
    subject=value['subject']
    if not isinstance(subject,str) or subject!=request.get('asset_id') or subject not in names:
        raise ImageFailure('prompt')
    labels={'subject':names[subject]}
    for key,choices in VOCAB.items():
        if key in value:
            if not isinstance(value[key],str) or value[key] not in choices:raise ImageFailure('prompt')
            labels[key]=choices[value[key]]
    # Preserve explicit local corrections rather than borrowing an older public
    # colour/outfit over the child's current choice. Ambiguity fails closed.
    for key,choices in VOCAB.items():
        mentioned={label for label in choices.values() if label in text and
            not re.search(r'(?:不要|不是|不穿|别|不用|去掉)[^。！？,，]{0,5}'+re.escape(label),text)}
        selected=labels.get(key)
        if selected and re.search(r'(?:不要|不是|不穿|别|不用|去掉)[^。！？,，]{0,5}'+re.escape(selected),text):
            raise ImageFailure('prompt')
        if mentioned and selected not in mentioned:raise ImageFailure('prompt')
    # Each exported feature must already be public/current and explicitly spoken
    # in the final approved segment, whose exact full ACK gates actual dispatch.
    heard=context.get('heard',())
    if not isinstance(heard,(tuple,list)) or any(not isinstance(s,str) for s in heard):raise ImageFailure('prompt')
    sources=(text,)+tuple(heard)
    caption=plan['sentences'][-1]
    if any(label not in caption or not any(label in source for source in sources) for label in labels.values()):
        raise ImageFailure('prompt')
    phrase='儿童插画：'+(labels.get('color','')+'的' if 'color' in labels else '')+labels['subject']
    for key,prefix in (('outfit','，穿着'),('setting','，在'),('action','，'),('prop','，配有')):
        if key in labels:phrase+=prefix+labels[key]
    if len(phrase)>160 or len(phrase.encode())>480:raise ImageFailure('prompt')
    return MinimalDescription(phrase)


class ImageAllowance:
    """Process/bundle-wide rolling attempt bound, shared across WS reconnects.

    Count before review/generation; failures/cancels are never refunded. This is
    a call bound, NOT a claimed price, provider quota or user budget cutoff.
    """
    def __init__(self,*,clock=None):
        self.clock=clock or time.monotonic
        self.attempts=deque(maxlen=4)

    def take(self):
        now=self.clock()
        while self.attempts and now-self.attempts[0]>=3600:self.attempts.popleft()
        if len(self.attempts)>=4 or self.attempts and now-self.attempts[-1]<15:
            raise ImageFailure('budget')
        self.attempts.append(now)
