"""Real approved PNG reads; synthetic language/speech, no cloud or device."""
import asyncio
from dataclasses import replace
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.v2.companion import UnifiedProviders, CompanionPolicy
from backend.v2.images import DefaultImages
from backend.v2.voice import VoicePeer
from tests.v2.test_m05 import Model, Socket


class Speech:
    @asynccontextmanager
    async def synthesize(self,text,rate):
        async def chunks():yield b"\x01\x00"*240
        yield chunks()


class ImageRoutes(unittest.IsolatedAsyncioTestCase):
    async def make(self, *, mode='chat', action='continue', secrets=None,
                   sentence='我们一起看看猫。', kind='show_image', asset='cat', enabled=True, slow=False):
        plan=dict(action=action,mode=mode,rules='轮流',roles=['猫船长'],secrets=secrets or {},
                  sentences=[sentence],anchors={},tools=[dict(kind=kind,asset_id=asset)])
        provider=UnifiedProviders(Speech(),Model(plan))
        socket=Socket();socket.acknowledge=False
        peer=VoicePeer(socket,provider,CompanionPolicy());socket.peer=peer
        self.addAsyncCleanup(self.cleanup,peer)
        release=asyncio.Event(); started=asyncio.Event()
        if slow:
            original=provider.prepare_visual
            async def blocked(request):
                started.set();await release.wait();return await original(request)
            provider.prepare_visual=blocked
        peer.session.begin_turn();peer.session.drain_commands()
        peer.generation=asyncio.create_task(peer.respond('一起玩',0))
        bind=dict(v=2,type='bind',epoch=0,seq=0,player='p')
        if enabled:bind['features']=['images_v1']
        await peer.handle(json.dumps(bind))
        await self.until(lambda:any(e['type']=='audio' for e in socket.events))
        return peer,socket,release,started

    async def cleanup(self,peer):
        peer.invalidate_visual()
        if peer.generation and not peer.generation.done():peer.generation.cancel()
        await asyncio.gather(*([peer.generation] if peer.generation else []),*peer.retired_tasks,return_exceptions=True)

    async def until(self,condition):
        async def wait():
            while not condition():await asyncio.sleep(.001)
        await asyncio.wait_for(wait(),2)

    async def ack(self,peer,event,head=None):
        identity=replace(peer.ack_identity,sequence=peer.ack_sequence);peer.ack_sequence+=1
        peer.session.ack(identity,player=event['player'],stream=event['stream'],
                         segment=event['segment'],head=event['end'] if head is None else head)
        await peer.commands()

    async def finish(self,peer,socket):
        for event in list(socket.events):
            if event['type']=='audio':await self.ack(peer,event)
        await asyncio.wait_for(peer.generation,2)

    async def test_real_sixty_assets_have_verified_hash_and_finite_fallbacks(self):
        images=DefaultImages();self.assertEqual(len(images.catalogue()),60)
        for item in images.catalogue():
            image=await images.prepare(dict(kind='show_image',asset_id=item['id']))
            self.assertEqual(image.asset_id,item['id']);self.assertIsNone(image.fallback_reason)
        for kind,asset,reason in [('generate_image','cat','dynamic_unavailable'),
                                  ('show_image','../../secret','unknown_asset')]:
            image=await images.prepare(dict(kind=kind,asset_id=asset))
            self.assertEqual(image.fallback_reason,reason)
            self.assertNotIn('url',image.payload());self.assertEqual(image.payload()['source'],'default')

    async def test_corrupt_real_file_never_claims_ready(self):
        original=DefaultImages()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'png').mkdir()
            (root/'manifest.json').write_text(json.dumps(list(original.entries.values())))
            (root/'png/cat.png').write_bytes(b'invalid')
            self.assertIsNone(await DefaultImages(root).prepare(dict(kind='show_image',asset_id='cat')))

    async def test_ready_is_hidden_partial_ack_cannot_reveal_and_full_ack_is_once(self):
        peer,socket,_,_=await self.make()
        await self.until(lambda:any(e['type']=='image_ready' for e in socket.events))
        self.assertFalse(any(e['type']=='reveal' for e in socket.events))
        audio=[e for e in socket.events if e['type']=='audio']
        for event in audio[:-1]:await self.ack(peer,event)
        final=audio[-1];await self.ack(peer,final,final['end']-1)
        self.assertFalse(any(e['type']=='reveal' for e in socket.events))
        await self.ack(peer,final);await peer.generation
        reveals=[e for e in socket.events if e['type']=='reveal']
        self.assertEqual(len(reveals),1)
        for key in ('player','stream','segment','end'):self.assertEqual(reveals[0][key],final[key])
        await self.ack(peer,final)
        self.assertEqual(len([e for e in socket.events if e['type']=='reveal']),1)

    async def test_slow_image_does_not_block_speech_and_ack_waits_for_real_read(self):
        peer,socket,release,started=await self.make(slow=True)
        await started.wait();await self.finish(peer,socket)
        self.assertFalse(any(e['type'] in {'image_ready','reveal'} for e in socket.events))
        release.set();await self.until(lambda:any(e['type']=='reveal' for e in socket.events))
        self.assertEqual([e['type'] for e in socket.events if e['type'] in {'image_ready','reveal'}],['image_ready','reveal'])

    async def test_new_input_and_handoff_reject_late_image(self):
        for reason in ('advance','handoff'):
            with self.subTest(reason=reason):
                peer,socket,release,started=await self.make(slow=True)
                await started.wait();await self.finish(peer,socket)
                if reason=='advance':
                    await peer.handle(json.dumps(dict(v=2,type='advance',epoch=0,seq=1,revision=1)))
                else:peer.session.handoff();await peer.commands()
                release.set();await asyncio.sleep(.03)
                self.assertFalse(any(e['type'] in {'image_ready','reveal'} for e in socket.events))
                self.assertIsNone(peer.prepared_visual)

    async def test_all_modes_and_hide_and_legacy_route(self):
        for mode in ('chat','guess','story','adventure','association'):
            peer,socket,_,_=await self.make(mode=mode)
            await self.finish(peer,socket)
            await self.until(lambda:any(e['type']=='reveal' for e in socket.events))
            self.assertEqual(peer.session.game['mode'],mode)
            self.assertEqual(peer.session.game['rules'],'轮流')
        peer,socket,_,_=await self.make(kind='hide_image')
        await self.finish(peer,socket)
        self.assertTrue(any(e['type']=='hide' and e['reason']=='requested' for e in socket.events))
        peer,socket,_,_=await self.make(enabled=False)
        await self.finish(peer,socket)
        self.assertFalse(any(e['type'] in {'image_ready','reveal','hide'} for e in socket.events))

    async def test_private_and_unspoken_riddle_cannot_prepare_answer(self):
        for args in [dict(action='private'),dict(mode='guess',secrets={'answer':'猫'},sentence='它喜欢捉老鼠。'),
                     dict(mode='guess',secrets={'answer':'狗'},sentence='答案是狗。')]:
            peer,socket,_,_=await self.make(**args)
            await self.finish(peer,socket)
            self.assertFalse(any(e['type'] in {'image_ready','reveal'} for e in socket.events))

    async def test_spoken_riddle_answer_only_becomes_public_after_full_ack(self):
        peer,socket,_,_=await self.make(mode='guess',secrets={'answer':'猫'},sentence='答案是猫。')
        self.assertEqual(peer.session.game,{})
        await self.finish(peer,socket)
        await self.until(lambda:any(e['type']=='reveal' for e in socket.events))
        self.assertEqual(peer.session.secrets,{})
        self.assertTrue(any('answer.current' in k for k in peer.session.facts))

    async def test_negative_control_removing_played_gate_is_detected(self):
        original=VoicePeer.reveal_visual
        async def wrong(peer,prepared):
            if prepared['ready'] is not None:
                prepared['played']=('unplayed',0);peer.session.topic=prepared['topic']
            await original(peer,prepared)
        with patch.object(VoicePeer,'reveal_visual',wrong):
            peer,socket,_,_=await self.make()
            await self.until(lambda:any(e['type']=='reveal' for e in socket.events))
            self.assertFalse(any(e['type']=='reply_end' for e in socket.events))
            with self.assertRaises(AssertionError):
                self.assertFalse(any(e['type']=='reveal' for e in socket.events))
