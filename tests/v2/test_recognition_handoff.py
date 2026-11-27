"""Real VoicePeer continuation handoff, fixed synthetic providers, no cloud."""
import asyncio,base64,json,time,unittest
from contextlib import asynccontextmanager
from backend.v2.voice import VoicePeer
from backend.v2.companion import CompanionPolicy

class Socket:
    def __init__(self):self.events=[]
    async def send(self,raw):self.events.append(json.loads(raw))
    async def close(self,*a):pass
class Providers:
    def __init__(self):
        self.calls=0;self.recognizers=0;self.first=asyncio.Event();self.second=asyncio.Event();self.release=asyncio.Event()
        self.close_enter=asyncio.Event();self.close_gate=None;self.cancelled=False;self.stubborn=False;self.fail_close=False;self.before_second=None;self.hold_asr=False;self.written=[]
    @asynccontextmanager
    async def recognize(self,rate):
        self.recognizers+=1
        owner=self;number=self.recognizers
        class R:
            async def write(self,pcm):owner.written.append((number,len(pcm)))
            async def finish(self):
                if owner.hold_asr and number==1:
                    owner.first.set();await owner.release.wait()
                return '固定合成输入。'
        try:yield R()
        finally:
            self.close_enter.set()
            if self.close_gate:await self.close_gate.wait()
            if self.fail_close:raise RuntimeError('fixed_close_failure')
    async def endpoint(self,text,context):
        self.calls+=1
        if self.calls==1 and not self.hold_asr:
            self.first.set()
            while not self.release.is_set():
                try:await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled=True
                    if not self.stubborn:raise
        else:
            if self.before_second:self.before_second()
            self.second.set()
        return dict(completion='complete',meaning='new_turn')

class Handoff(unittest.IsolatedAsyncioTestCase):
    async def make(self,*,hold_asr=False,gate=None,fail_close=False):
        self.providers=Providers();self.providers.hold_asr=hold_asr;self.providers.close_gate=gate;self.providers.fail_close=fail_close;self.socket=Socket();self.peer=VoicePeer(self.socket,self.providers,CompanionPolicy())
        await self.send('advance',revision=1);await self.send('input',pcm=base64.b64encode(b'\1\0'*320).decode(),speech=True,age_ms=0)
        await self.send('probe',revision=1);await self.providers.first.wait()
    async def send(self,kind,**fields):
        p=self.peer;await p.handle(json.dumps(dict(v=2,type=kind,epoch=p.epoch,seq=p.sequence+1,**fields)))
    async def clean(self):
        self.providers.release.set()
        if self.providers.close_gate:self.providers.close_gate.set()
        try:await self.peer.cancel_recognition()
        finally:
            for t in list(self.peer.retired_tasks):
                if not t.done():t.cancel()
            if self.peer.retired_tasks:await asyncio.gather(*list(self.peer.retired_tasks),return_exceptions=True)
            self.peer.closed=True;self.peer.session.clear()
    async def test_continuation_new_probe_does_not_wait_for_old_endpoint(self):
        await self.make();p=self.peer
        try:
            deadline=p.input_budget.deadline
            start=time.monotonic();await self.send('advance',revision=2)
            self.assertLess(time.monotonic()-start,.05) # owner returns without awaiting .5s release
            self.assertEqual(p.input_budget.deadline,deadline)
            await self.send('input',pcm=base64.b64encode(b'\2\0'*320).decode(),speech=True,age_ms=0)
            await self.send('probe',revision=2)
            await asyncio.wait_for(self.providers.second.wait(),.15)
            await p.recognition
            self.assertTrue(self.providers.cancelled)
            self.assertFalse(self.providers.release.is_set())
            self.assertEqual([e['revision'] for e in self.socket.events if e['type']=='endpoint'],[2])
            self.assertEqual(p.analysis[0],2);self.assertFalse(p.quarantined)
        finally:await self.clean()

    async def queue(self,version):
        await self.send('advance',revision=version)
        await self.send('input',pcm=base64.b64encode(b'\2\0'*320).decode(),speech=True,age_ms=0)
        await self.send('probe',revision=version)
    async def test_release_must_confirm_and_latest_probe_wins(self):
        gate=asyncio.Event();await self.make(hold_asr=True,gate=gate)
        try:
            await self.queue(2);await self.providers.close_enter.wait()
            await self.queue(3);await asyncio.sleep(.02)
            self.assertEqual(self.providers.recognizers,1)
            gate.set();await asyncio.wait_for(self.providers.second.wait(),.15);await self.peer.recognition
            self.assertEqual(self.peer.analysis[0],3)
            self.assertEqual(self.providers.recognizers,2)
            self.assertEqual(self.providers.written,[(1,640),(2,1920)])
            self.assertEqual([e['revision'] for e in self.socket.events if e['type']=='endpoint'],[3])
        finally:await self.clean()
    async def test_swallowed_cancellation_is_quarantined_at_original_bound(self):
        await self.make();self.providers.stubborn=True
        try:
            old=self.peer.recognition;await self.queue(2)
            await asyncio.sleep(.54)
            self.assertTrue(self.peer.quarantined);self.assertFalse(old.done())
            self.assertEqual(self.providers.recognizers,1);self.assertIn(old,self.peer.retired_tasks)
        finally:await self.clean()
    async def test_failed_or_unconfirmed_asr_close_never_starts_new_provider(self):
        for failure in ('failed','unconfirmed'):
            gate=asyncio.Event() if failure=='unconfirmed' else None
            await self.make(hold_asr=True,gate=gate,fail_close=failure=='failed')
            try:
                await self.queue(2);await asyncio.sleep(.54 if gate else .03)
                self.assertTrue(self.peer.quarantined);self.assertEqual(self.providers.recognizers,1)
                self.assertFalse(any(e['type']=='endpoint' for e in self.socket.events))
            finally:await self.clean()
    async def test_scope_change_during_release_does_not_dispatch_pending(self):
        from backend.v2.session import Session
        for change in ('session','connection','epoch','private'):
            gate=asyncio.Event();await self.make(hold_asr=True,gate=gate)
            try:
                await self.queue(2);await self.providers.close_enter.wait()
                p=self.peer
                if change=='session':
                    old=p.session;old.clear();p.session=Session(old.clock)
                elif change=='private':p.session.private_mode=True
                elif change=='epoch':p.epoch+=1
                else:p.session.connection+=1
                task=p.recognition_handoff;gate.set();await task
                self.assertEqual(self.providers.recognizers,1);self.assertIsNone(p.next_probe)
                self.assertFalse(any(e['type']=='endpoint' for e in self.socket.events))
            finally:await self.clean()
    async def test_caller_cancel_during_release_is_isolated_and_never_dispatches(self):
        gate=asyncio.Event();await self.make(hold_asr=True,gate=gate)
        try:
            await self.queue(2);await self.providers.close_enter.wait()
            closing=asyncio.create_task(self.peer.cancel_recognition());await asyncio.sleep(0);closing.cancel()
            await asyncio.gather(closing,return_exceptions=True)
            self.assertTrue(self.peer.quarantined);self.assertEqual(self.providers.recognizers,1)
            gate.set();await asyncio.sleep(.01)
            self.assertFalse(self.providers.second.is_set())
        finally:await self.clean()
    async def test_old_finally_and_handoff_cannot_consume_replacement_owner(self):
        from backend.v2.voice import Operation
        gate=asyncio.Event();await self.make(hold_asr=True,gate=gate)
        fresh=None
        try:
            await self.queue(2);await self.providers.close_enter.wait();p=self.peer
            helper=p.recognition_handoff
            fresh=asyncio.create_task(asyncio.sleep(.03));p.recognition=fresh
            pending=(b'\3\0',Operation(p,p.epoch,p.revision),fresh);p.next_probe=pending
            gate.set();await helper
            self.assertIs(p.recognition,fresh);self.assertIs(p.next_probe,pending)
            self.assertEqual(self.providers.recognizers,1)
        finally:
            if fresh:await fresh
            await self.clean()
    async def test_expired_original_input_budget_cannot_dispatch_new_recognizer(self):
        gate=asyncio.Event();await self.make(hold_asr=True,gate=gate)
        try:
            await self.queue(2);await self.providers.close_enter.wait();p=self.peer
            deadline=p.input_budget.deadline
            # A controlled clock crossing only the original expression deadline;
            # session TTL/heartbeat remain valid and no budget is renewed.
            p.session.clock=lambda:deadline+.01
            p.input_budget.clock=p.session.clock
            p.session.expires=deadline+600;p.session.heartbeat_deadline=deadline+10
            helper=p.recognition_handoff;gate.set();await helper
            if p.recognition:await p.recognition
            self.assertEqual(p.input_budget.deadline,deadline)
            self.assertEqual(self.providers.recognizers,1)
            self.assertIsNone(p.analysis)
        finally:await self.clean()

    async def test_direct_handoff_caller_cancel_does_not_leave_reusable_connection(self):
        gate=asyncio.Event();await self.make(hold_asr=True,gate=gate)
        try:
            await self.queue(2);await self.providers.close_enter.wait()
            helper=self.peer.recognition_handoff;helper.cancel();await asyncio.gather(helper,return_exceptions=True)
            self.assertTrue(self.peer.quarantined);self.assertIsNone(self.peer.next_probe)
            self.assertEqual(self.providers.recognizers,1)
        finally:await self.clean()
