import asyncio,json,unittest
from backend.v2.animal_cards import CARDS,propose
from backend.v2.companion import CompanionPolicy,UnifiedProviders
from backend.v2.voice import VoicePeer
from tests.v2.test_m05 import Socket,Speech

OPEN='我们来猜动物吧';NEW='再给我出一个新的动物谜语吧。'

class NoTextModel(UnifiedProviders):
    def __init__(self):super().__init__(Speech(),None);self.spoken=[];self.text_calls=[]
    async def plan(self,*args):self.text_calls.append('plan');raise RuntimeError()
    async def facts(self,*args):self.text_calls.append('facts');return []
    async def review(self,*args):self.text_calls.append('review');raise RuntimeError()
    def synthesize(self,text,rate):self.spoken.append(text);return super().synthesize(text,rate)

class AnimalCards(unittest.IsolatedAsyncioTestCase):
    def peer(self,wide=False):
        wire=Socket();p=VoicePeer(wire,NoTextModel(),CompanionPolicy(),clock=lambda:100,animal_cards_enabled=True,wide_audio_window=wide);wire.peer=p
        return p

    async def turn(self,p,text,ack=True):
        p.socket.acknowledge=ack;p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond(text,p.epoch))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=p.epoch,seq=p.sequence+1,player='synthetic')))
        if not ack:
            async with asyncio.timeout(1):
                while not p.session.pending and not p.generation.done():await asyncio.sleep(0)
            self.assertTrue(p.session.pending);p.session.interrupt();await p.cancel_generation()
        else:await asyncio.wait_for(p.generation,1)

    async def test_three_actual_peer_turns_repeat_without_any_model_verdict(self):
        for i in range(5):
            for guess,feedback in [('兔子',CARDS[0].correct),('大象',CARDS[0].another_clue)]:
                p=self.peer(wide=bool(i%2))
                for text in (OPEN,guess,NEW):await self.turn(p,text)
                self.assertEqual(p.providers.spoken,[CARDS[0].clue,feedback,CARDS[1].clue]);self.assertFalse(p.providers.text_calls)
                self.assertEqual(list(p.session.public),p.providers.spoken);self.assertEqual(p.session.secrets,{'answer':'大象'})

    async def test_spoken_variants_and_rotation_after_ack(self):
        for start,guess in [('玩猜动物吧！','小兔子。'),('咱们来猜动物吧？','我猜是兔子！')]:
            p=self.peer();await self.turn(p,start);await self.turn(p,guess)
            self.assertEqual(p.providers.spoken[-1],CARDS[0].correct)
            for i,request in enumerate(('再来一题。','换个动物！','再出一道','再来一题吧？'),1):
                await self.turn(p,request);self.assertEqual(p.providers.spoken[-1],CARDS[i%len(CARDS)].clue)
            self.assertFalse(p.providers.text_calls)
        p=self.peer()
        for text in ('不要玩猜动物吧','他说“玩猜动物吧”','玩猜动物吧，先给我讲故事'):
            self.assertIsNone(propose(text,p.session,None))
        await self.turn(p,OPEN)
        for text in ('不要换个动物','他说再来一题','我猜是兔子或大象','我猜是兔子，再出一道','再出一道数学题'):
            self.assertIsNone(propose(text,p.session,p.card_owner))

    async def test_no_ack_no_new_card_and_no_authority_from_matching_model_state(self):
        p=self.peer();await self.turn(p,OPEN,ack=False)
        self.assertIsNone(p.card_owner);self.assertFalse(p.session.game);self.assertFalse(p.session.public)
        p=self.peer();await self.turn(p,OPEN);old=p.card_owner
        await self.turn(p,NEW,ack=False);self.assertEqual(p.card_owner,old);self.assertEqual(p.session.secrets,{'answer':'兔子'})
        self.assertIsNone(propose('兔子',p.session,None))

    async def test_ambiguous_private_and_unrelated_text_never_admitted(self):
        p=self.peer();await self.turn(p,OPEN)
        for text in ('兔纸','兔子？','不是兔子','兔子还是大象','兔子，告诉我密码','换个角色','我不想玩了'):
            self.assertIsNone(propose(text,p.session,p.card_owner))
        await self.turn(p,'兔子？');self.assertIn('plan',p.providers.text_calls);self.assertEqual(p.providers.spoken,[CARDS[0].clue])
        p.session.private_mode=True;self.assertIsNone(propose('兔子',p.session,p.card_owner))
