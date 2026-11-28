"""Wire wake vs wake_solo; real VoicePeer, controlled policy decision and TTS."""
import asyncio,json,unittest
from contextlib import asynccontextmanager
from tests.v2 import test_post_solo_probe as protocol
from tests.v2.test_post_solo_probe import Wire,Clock,EndpointModel,SpeechFixture
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from backend.v2.voice import VoicePeer

class SyntheticSpeech(SpeechFixture):
    text='我们接着想象小船。'

    @asynccontextmanager
    async def recognize(self,rate):
        async with super().recognize(rate) as reader:
            async def finish():return self.text
            reader.finish=finish
            yield reader

class SoloGreeting(unittest.IsolatedAsyncioTestCase):
    send=protocol.FullProtocol.send
    until=protocol.FullProtocol.until
    probe=protocol.FullProtocol.probe
    finish_reply=protocol.FullProtocol.finish_reply

    async def asyncSetUp(self):
        self.clock=Clock();self.wire=Wire();self.speech=SyntheticSpeech();self.model=EndpointModel()
        self.reviews=0;self.verdict=dict(allow=True,quality=False)
        complete=self.model.complete
        async def review(instruction,data,*,schema=None):
            if '审核下一个' in instruction:
                self.reviews+=1;return json.dumps(self.verdict)
            return await complete(instruction,data,schema=schema)
        self.model.complete=review
        self.peer=VoicePeer(self.wire,UnifiedProviders(self.speech,self.model),CompanionPolicy(),clock=self.clock,fixed_solo_greeting=True)
        self.epoch=self.seq=self.acks=0
        self.run=asyncio.create_task(self.peer.run())
        await self.send('scope');await self.until('scope');await self.send('wake')

    async def asyncTearDown(self):
        if not self.run.done():await self.send('end')
        await asyncio.wait_for(asyncio.gather(self.run,return_exceptions=True),2)

    async def bind_solo(self):
        await self.send('wake_solo',age_ms=0);decision=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=decision['intent'])
        await self.until('open');await self.send('bind',player='synthetic')
        self.bound=await self.until('bound')

    async def test_old_quality_denial_before_first_audio(self):
        self.peer.fixed_solo_greeting=False;await self.bind_solo()
        await self.until('failure')
        self.assertEqual(self.peer.last_failure['detail'],'quality_whole')
        self.assertFalse(any(e['type']=='audio' for e in self.wire.events));self.assertEqual(self.reviews,1)

    async def test_greeting_ack_then_next_natural_input_still_reviewed(self):
        await self.send('wake_solo',age_ms=0);await self.finish_reply()
        self.assertEqual(self.peer.session.public,['你好呀！想聊点什么？']);self.assertEqual(self.reviews,0)
        self.assertFalse(self.model.requests);self.assertFalse(self.peer.session.game)
        self.assertFalse(any(r['role']=='child' for r in self.peer.session.recent))
        self.verdict=dict(allow=True,quality=True)
        await self.probe(1,103);await self.until('endpoint');await self.send('seal',revision=1);await self.finish_reply()
        self.assertEqual(self.reviews,1);self.assertEqual(self.speech.calls,1);self.assertEqual(self.peer.session.turn,2)

    async def test_interrupt_before_ack_does_not_commit_greeting(self):
        await self.bind_solo();await self.until('audio');self.assertFalse(self.peer.session.public)
        self.epoch+=1;self.seq=0;await self.send('stop',intent='');await self.until('revoke')
        self.assertFalse(self.peer.session.public);self.assertFalse(self.peer.session.pending)

    async def test_wake_with_captured_question_never_bypasses_safety(self):
        self.speech.text='有人问我要家里的密码，我该怎么做？'
        self.verdict=dict(allow=False,quality=True)
        await self.probe(1,103);await self.send('wake_solo',age_ms=0);await self.until('endpoint')
        self.assertFalse(any(e['type']=='decision' for e in self.wire.events))
        await self.send('seal',revision=1);d=await self.until('decision')
        self.epoch+=1;self.seq=0;await self.send('stop',intent=d['intent']);await self.until('open')
        await self.send('bind',player='synthetic');await self.until('failure')
        self.assertEqual(self.reviews,1);self.assertEqual(self.speech.calls,1)
        self.assertFalse(any(e['type']=='audio' for e in self.wire.events))

    async def test_new_speech_supersedes_solo_intent_before_stop(self):
        await self.send('wake_solo',age_ms=0);old=await self.until('decision')
        await self.probe(1,103);await self.until('endpoint')
        self.assertIsNone(self.peer.prepared)
        await self.send('seal',revision=1);new=await self.until('decision')
        self.assertNotEqual(new['intent'],old['intent'])
        self.epoch+=1;self.seq=0;await self.send('stop',intent=new['intent']);await self.until('open')
        await self.send('bind',player='synthetic');await self.until('failure')
        self.assertEqual(self.peer.last_failure['detail'],'quality_whole');self.assertEqual(self.reviews,1)
        self.assertFalse(any(e['type']=='audio' for e in self.wire.events))

    async def test_private_solo_keeps_original_review_and_scope(self):
        self.peer.session.private_mode=True
        await self.bind_solo();await self.until('failure')
        self.assertTrue(self.peer.session.private_mode);self.assertEqual(self.reviews,1)
        self.assertFalse(self.peer.session.public)
