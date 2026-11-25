"""Management control uses actual VoicePeer/Session; no management PCM upstream."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
from backend.v2.voice import VoicePeer,Operation,WireError
from backend.v2.session import Session
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from tests.v2.test_m05 import Model,Socket
from tests.v2.test_images import Speech


class Clock:
    def __init__(self):self.now=0.
    def __call__(self):return self.now


class Management(unittest.IsolatedAsyncioTestCase):
    async def make(self):
        clock=Clock();socket=Socket()
        model=Model(dict(action='continue',mode='story',rules='轮流',roles=['猫船长'],secrets={'answer':'猫'},
                         sentences=['猫船长找到了蓝色钥匙。'],anchors={'plot.inventory':0}))
        peer=VoicePeer(socket,UnifiedProviders(Speech(),model),CompanionPolicy(),clock=clock);socket.peer=peer
        peer.session.begin_turn();peer.session.drain_commands()
        peer.generation=asyncio.create_task(peer.respond('一起找钥匙',0))
        await peer.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='p')))
        await asyncio.wait_for(peer.generation,2)
        peer.session.private_mode=True;peer.session.remember_private('合成私事不共享')
        peer.session.private_mode=False
        self.addAsyncCleanup(self.cleanup,peer)
        return peer,socket,model,clock

    async def cleanup(self,peer):
        peer.invalidate_visual()
        for task in [peer.generation,peer.recognition,*peer.retired_tasks]:
            if task is not None and not task.done():task.cancel()
        await asyncio.gather(*[t for t in [peer.generation,peer.recognition,*peer.retired_tasks] if t],return_exceptions=True)

    def frame(self,p,kind,**kw):
        return json.dumps(dict(v=2,type=kind,epoch=p.epoch,seq=p.sequence+1,**kw))

    async def pause(self,p):
        await p.handle(json.dumps(dict(v=2,type='management_pause',epoch=p.epoch+1,seq=0,
            session=p.session.session,turn=p.session.turn,revision=p.revision+1)))
        return p.management_receipt

    def resume(self,p,receipt,**kw):
        values=dict(v=2,type='management_resume',epoch=p.epoch+1,seq=0,
                    session=p.session.session,turn=p.session.turn,revision=p.revision+1,pause=receipt)
        values.update(kw);return json.dumps(values)

    async def test_roundtrip_keeps_only_committed_context_ttl_and_returns_wake_only(self):
        p,s,m,c=await self.make();before=deepcopy(p.session.context());expires=p.session.expires
        old=Operation(p,p.epoch);old.output=p.session.output
        receipt=await self.pause(p)
        self.assertFalse(old.valid());self.assertEqual(len(receipt),32)
        self.assertTrue(p.session.management_paused);self.assertEqual(p.session.context(),before)
        c.now=5;await p.handle(self.frame(p,'heartbeat'))
        self.assertEqual(p.session.expires,expires)
        count=len(s.events);await p.handle(self.resume(p,receipt))
        self.assertTrue(p.waiting_wake);self.assertEqual(p.session.context(),before)
        self.assertEqual(p.session.expires,expires);self.assertIsNone(p.session.player)
        self.assertFalse(any(e['type'] in {'open','audio','image_ready','reveal'} for e in s.events[count:]))
        self.assertEqual(s.events[-1]['state'],'waiting_wake')
        self.assertNotIn('合成私事',str(p.session.context(shared=True)))
        await p.handle(self.frame(p,'wake_solo'))
        self.assertFalse(p.waiting_wake);self.assertEqual(s.events[-1]['type'],'decision')
        decision=p.prepared
        await p.handle(json.dumps(dict(v=2,type='stop',epoch=p.epoch+1,seq=0,intent=decision[2])))
        await p.handle(self.frame(p,'bind',player='fresh'))
        await asyncio.wait_for(p.generation,2)
        self.assertEqual(p.session.session,old.session_id)
        self.assertTrue(any(e['type']=='reply_end' for e in s.events[count:]))

    async def test_management_and_waiting_wake_discard_even_invalid_pcm_without_provider_calls(self):
        p,s,m,c=await self.make();receipt=await self.pause(p);calls=len(m.requests)
        for phase in ('paused','waiting'):
            if phase=='waiting':await p.handle(self.resume(p,receipt))
            for kind,kw in [('input',dict(pcm='NOT_BASE64')),('probe',dict(revision=p.revision)),
                            ('advance',dict(revision=p.revision+1)),('resume_noise',{}),
                            ('stop',dict(intent=''))]:
                await p.handle(self.frame(p,kind,**kw))
            self.assertEqual(p.capture,bytearray());self.assertIsNone(p.recognition)
            self.assertEqual(len(m.requests),calls)
            self.assertIsNone(p.analysis);self.assertIsNone(p.prepared)

    async def test_expiry_equality_and_heartbeat_do_not_extend_or_resurrect(self):
        for boundary in ('ttl','lease'):
            p,s,m,c=await self.make();receipt=await self.pause(p)
            if boundary=='ttl':p.session.heartbeat_deadline=p.session.expires+1;c.now=p.session.expires
            else:c.now=p.session.heartbeat_deadline
            await p.handle(self.resume(p,receipt))
            self.assertFalse(p.session.active);self.assertEqual(p.session.context(),{})
            self.assertEqual(s.events[-1]['state'],'expired')
            self.assertIsNone(p.management_receipt)

    async def test_wrong_scope_revision_receipt_repeated_resume_and_revoke_cannot_reactivate(self):
        p,s,m,c=await self.make();receipt=await self.pause(p);identity=(p.epoch,p.revision,p.session.expires)
        for change in [dict(session='other'),dict(turn=99),dict(revision=p.revision),dict(pause='wrong')]:
            await p.handle(self.resume(p,receipt,**change))
            self.assertTrue(p.session.management_paused);self.assertEqual((p.epoch,p.revision,p.session.expires),identity)
        good=self.resume(p,receipt);await p.handle(good);state=(p.epoch,p.revision)
        await p.handle(good);self.assertEqual((p.epoch,p.revision),state)
        for revoke in ('interrupt','handoff','reconnect','closed'):
            p,s,m,c=await self.make();receipt=await self.pause(p)
            if revoke=='closed':p.closed=True
            else:getattr(p.session,revoke)()
            await p.handle(self.resume(p,receipt))
            self.assertFalse(p.waiting_wake)

    async def test_inflight_swallowed_cancellation_cannot_commit_after_management_pause(self):
        p,s,m,c=await self.make();started=asyncio.Event();release=asyncio.Event()
        original=p.providers.plan
        async def blocked(*args):
            started.set()
            try:await release.wait()
            except asyncio.CancelledError:pass
            return await original(*args)
        p.providers.plan=blocked
        p.session.begin_turn();p.session.drain_commands();p.session.bind_player('new');p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('旧输入',p.epoch))
        await started.wait();before=deepcopy(p.session.context());calls=len(m.requests)
        await self.pause(p);release.set();await asyncio.sleep(0)
        self.assertEqual(p.session.context(),before)
        # The uncooperative call itself may finish, but cannot dispatch facts/safety/TTS.
        self.assertLessEqual(len(m.requests),calls+1)
        self.assertIsNone(p.generation);self.assertFalse(p.quarantined)

    async def test_scope_query_before_first_child_turn_has_no_provider_or_ttl_effect(self):
        c=Clock();s=Socket();m=Model({})
        p=VoicePeer(s,UnifiedProviders(Speech(),m),CompanionPolicy(),clock=c);s.peer=p
        calls=len(m.requests);expires=p.session.expires
        await p.handle(self.frame(p,'scope'))
        self.assertEqual(s.events[-1]['session'],p.session.session)
        self.assertEqual(s.events[-1]['management_v'],1)
        self.assertEqual(len(m.requests),calls);self.assertEqual(p.session.expires,expires)
        receipt=await self.pause(p);await p.handle(self.resume(p,receipt))
        self.assertTrue(p.waiting_wake);self.assertEqual(p.session.turn,0)
        self.assertEqual(m.requests,[])

    async def test_partial_audio_and_uncommitted_picture_cannot_become_heard_after_pause(self):
        p,s,m,c=await self.make();session=p.session
        session.begin_turn();session.drain_commands();session.bind_player('old');session.drain_commands()
        sender=session.task('tts');ack=session.task('ack')
        session.send(sender,name='pending',public='未播完的秘密揭晓。',end=240,approved=True,effective=True,
                     anchors=('answer.current',),effect='image:old',
                     state=dict(mode='guess',rules='',roles=[],secrets={}))
        self.assertFalse(session.ack(ack,player='old',stream=session.stream,segment='pending',head=239))
        oldstream=session.stream
        receipt=await self.pause(p)
        self.assertFalse(session.ack(replace(ack,sequence=1),player='old',stream=oldstream,segment='pending',head=240))
        await p.handle(self.resume(p,receipt))
        self.assertNotIn('未播完的秘密',str(session.context()));self.assertEqual(session.secrets,{'answer':'猫'})
        self.assertIsNone(p.prepared_visual)
        self.assertFalse(any(e['type']=='reveal' for e in s.events))

    async def test_core_rejects_child_mutations_while_management_paused(self):
        p,s,m,c=await self.make();await self.pause(p);session=p.session;expires=session.expires
        before=deepcopy(session.context())
        self.assertFalse(session.valid_interaction())
        with self.assertRaises(RuntimeError):session.begin_turn()
        with self.assertRaises(RuntimeError):session.bind_player('new')
        with self.assertRaises(ValueError):session.record_input('管理期间不保存',[])
        self.assertFalse(session.change_game(rules='不准生效',roles=[],secrets={}))
        session.remember_private('管理秘密不保存')
        self.assertFalse(session.compact(session.memory_snapshot(),[]))
        self.assertEqual(session.context(),before);self.assertEqual(session.expires,expires)

    async def test_real_visual_prepare_cancelled_by_management_has_no_late_publish(self):
        p,s,m,c=await self.make();started=asyncio.Event();release=asyncio.Event()
        m.next_plan.update(secrets={},tools=[dict(kind='show_image',asset_id='cat')])
        p.session.secrets={};original=p.providers.prepare_visual
        async def blocked(request):
            started.set()
            try:await release.wait()
            except asyncio.CancelledError:pass
            return await original(request)
        p.providers.prepare_visual=blocked
        p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('看看猫',p.epoch))
        await p.handle(self.frame(p,'bind',player='new',features=['images_v1']))
        await started.wait();await asyncio.wait_for(p.generation,2)
        count=len(s.events);receipt=await self.pause(p);release.set()
        await asyncio.sleep(.03);await p.handle(self.resume(p,receipt))
        self.assertFalse(any(e['type'] in {'image_ready','reveal'} for e in s.events[count:]))
        self.assertIsNone(p.prepared_visual)

    async def test_unconfirmed_provider_release_quarantines_instead_of_resuming(self):
        p,s,m,c=await self.make();started=asyncio.Event();release=asyncio.Event()
        async def blocked(*args):
            started.set()
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()
            return m.next_plan
        p.providers.plan=blocked
        p.session.begin_turn();p.session.drain_commands();p.session.bind_player('x');p.session.drain_commands()
        task=asyncio.create_task(p.respond('旧输入',p.epoch));p.generation=task
        await started.wait()
        try:
            with self.assertRaises(WireError):await asyncio.wait_for(self.pause(p),1)
            self.assertTrue(p.quarantined);self.assertFalse(p.management_ready)
            with self.assertRaises(WireError):await p.handle(self.resume(p,p.management_receipt))
        finally:release.set();await asyncio.gather(task,return_exceptions=True)

    async def test_disconnect_run_finally_clears_receipt_and_all_context(self):
        p,s,m,c=await self.make();receipt=await self.pause(p)
        async def disconnect():raise ConnectionError('synthetic transport closed')
        s.recv=disconnect
        with self.assertRaises(ConnectionError):await p.run()
        self.assertTrue(p.closed);self.assertFalse(p.session.active)
        self.assertIsNone(p.management_receipt);self.assertIsNone(p.management_scope)
        self.assertEqual(p.session.context(),{})
        await p.handle(self.resume(p,receipt));self.assertFalse(p.waiting_wake)

    async def test_negative_control_accepting_stale_receipt_is_detected(self):
        p,s,m,c=await self.make();receipt=await self.pause(p)
        p.session.interrupt()
        # Deliberately rebind the receipt after revocation: production must never do this.
        p.management_scope=(p.session,p.session.connection,p.session.session,p.session.turn,p.session.output,p.epoch,p.revision)
        await p.handle(self.resume(p,receipt))
        with self.assertRaises(AssertionError):self.assertFalse(p.waiting_wake)

    async def test_explicit_conversation_end_clears_after_heard_farewell(self):
        p,s,m,c=await self.make();sid=p.session.session
        m.next_plan.update(action='end',sentences=['再见，好好休息。'],anchors={},secrets={})
        p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('我们都不玩了',p.epoch))
        await p.handle(self.frame(p,'bind',player='farewell'))
        await asyncio.wait_for(p.generation,2)
        ends=[e for e in s.events if e['type']=='session_end']
        self.assertEqual(len(ends),1);self.assertEqual(ends[0]['session'],sid)
        self.assertFalse(p.session.active);self.assertEqual(p.session.context(),{})
        self.assertEqual(p.session.source_archive,'');self.assertEqual(p.session.private,[])

    async def test_partial_farewell_or_management_preemption_does_not_end_session(self):
        p,s,m,c=await self.make();s.acknowledge=False
        m.next_plan.update(action='end',sentences=['再见，好好休息。'],anchors={},secrets={})
        p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('我们都不玩了',p.epoch))
        await p.handle(self.frame(p,'bind',player='farewell'))
        async def sent():
            while not p.session.pending:await asyncio.sleep(0)
        await asyncio.wait_for(sent(),1)
        segment=p.session.pending[0]
        self.assertFalse(p.session.ack(p.ack_identity,player='farewell',stream=p.session.stream,
                                     segment=segment.name,head=segment.end-1))
        self.assertTrue(p.session.active)
        receipt=await self.pause(p);await p.handle(self.resume(p,receipt))
        self.assertTrue(p.session.active);self.assertTrue(p.waiting_wake)
        self.assertFalse(any(e['type']=='session_end' for e in s.events))

    async def test_one_child_exit_and_leave_game_keep_shared_session(self):
        for action,text in [('continue','我先退出，你们继续'),('leave','不玩这个了')]:
            p,s,m,c=await self.make();sid=p.session.session
            m.next_plan.update(action=action,sentences=['好，我们接着聊。'])
            p.session.begin_turn();p.session.drain_commands()
            p.generation=asyncio.create_task(p.respond(text,p.epoch))
            await p.handle(self.frame(p,'bind',player='new'))
            await asyncio.wait_for(p.generation,2)
            self.assertTrue(p.session.active);self.assertEqual(p.session.session,sid)
            self.assertFalse(any(e['type']=='session_end' for e in s.events))
            if action=='leave':self.assertEqual(p.session.game['mode'],'chat')
