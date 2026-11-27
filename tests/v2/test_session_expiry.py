"""Fake-clock lifecycle evidence; real VoicePeer/Session, zero suppliers."""
import asyncio,json,unittest
from backend.v2.voice import VoicePeer,Operation
from backend.v2.companion import CompanionPolicy
from backend.v2.session import Session

class Clock:
    def __init__(self):self.now=0.
    def __call__(self):return self.now
class Suppliers:
    def __init__(self):self.calls=[]
    async def recognize(self,*a):self.calls.append('asr');raise AssertionError('supplier')
    async def plan(self,*a):self.calls.append('model');raise AssertionError('supplier')
    async def synthesize(self,*a):self.calls.append('tts');raise AssertionError('supplier')
    async def prepare_visual(self,*a):self.calls.append('image');raise AssertionError('supplier')
class Socket:
    def __init__(self):self.events=[];self.queue=asyncio.Queue();self.receiving=asyncio.Event()
    async def send(self,raw):self.events.append(json.loads(raw))
    async def recv(self):self.receiving.set();return await self.queue.get()
    async def close(self,*a):pass

class Expiry(unittest.IsolatedAsyncioTestCase):
    def make(self):
        c=Clock();s=Socket();providers=Suppliers();p=VoicePeer(s,providers,CompanionPolicy(),clock=c)
        self.addCleanup(self.assertEqual,providers.calls,[])
        return p,s,c
    def idle_to_590(self,p,c):
        for n in range(10,600,10):c.now=n;self.assertTrue(p.session.heartbeat())
        self.assertEqual(p.session.expires,600)
    async def monitored(self,p):await asyncio.wait_for(p.monitor(),1.8)
    async def test_idle_ttl_sends_normal_scoped_end_not_failure(self):
        p,s,c=self.make();sid=p.session.session;self.idle_to_590(p,c);c.now=600.01
        await self.monitored(p)
        ends=[e for e in s.events if e['type']=='session_end']
        self.assertEqual(len(ends),1,s.events)
        self.assertEqual(ends[0],dict(v=2,type='session_end',epoch=0,reason='session_expired',session=sid,turn=0,revision=0))
        self.assertFalse(any(e['type']=='failure' for e in s.events))
        self.assertFalse(p.session.active);self.assertEqual(p.session.context(),{})
    async def test_earlier_heartbeat_or_reply_or_progress_is_never_normal_ttl(self):
        for reason in ('heartbeat','response','progress','response_already_expired','equal_heartbeat','equal_reply'):
            p,s,c=self.make()
            if reason not in ('heartbeat','equal_heartbeat'):self.idle_to_590(p,c)
            if reason=='equal_heartbeat':p.session.heartbeat_deadline=600
            if reason in ('response','progress','equal_reply'):
                p.session.deadline=600 if reason=='equal_reply' else 15
                p.session.response_confirmed=reason=='progress'
                p.session.progress_deadline=30 if reason=='progress' else 0
            if reason=='response_already_expired':p.session.response_expired=True
            c.now=610 # one poll crosses multiple deadlines, earliest failure wins
            await self.monitored(p)
            self.assertFalse(any(e['type']=='session_end' for e in s.events),reason)
            self.assertTrue(any(e.get('code')=='timeout' for e in s.events),reason)
    async def test_live_ttl_does_not_change_response_or_progress_timeouts(self):
        for progress in (False,True):
            p,s,c=self.make();p.session.deadline=5;p.session.response_confirmed=progress;p.session.progress_deadline=5
            c.now=6;await self.monitored(p)
            self.assertTrue(p.session.response_expired);self.assertTrue(p.session.active)
            self.assertFalse(any(e['type']=='session_end' for e in s.events))
            self.assertTrue(any(e.get('code')=='timeout' for e in s.events))
    async def test_original_ingress_budget_wins_and_is_not_renewed(self):
        p,s,c=self.make();self.idle_to_590(p,c)
        p.awaiting_input=True;p.input_budget.speech(0);deadline=p.input_budget.deadline;c.now=610
        await self.monitored(p)
        self.assertEqual(p.input_budget.deadline,deadline)
        self.assertTrue(any(e.get('code')=='timeout' for e in s.events))
        self.assertFalse(any(e['type']=='session_end' for e in s.events))
    async def test_management_expiry_is_not_normal_end(self):
        p,s,c=self.make();self.assertTrue(p.session.pause_management());self.idle_to_590(p,c);c.now=600.01
        await self.monitored(p)
        self.assertEqual(p.session.expiry_reason,'management_expired')
        self.assertTrue(any(e.get('code')=='timeout' for e in s.events))
        self.assertFalse(any(e['type']=='session_end' for e in s.events))
    async def test_run_heartbeat_discovers_ttl_then_emits_end_and_closes_cleanly(self):
        p,s,c=self.make();self.idle_to_590(p,c);sid=p.session.session
        task=asyncio.create_task(p.run());await s.receiving.wait();c.now=600.01
        await s.queue.put(json.dumps(dict(v=2,type='heartbeat',epoch=0,seq=0)))
        await asyncio.wait_for(task,1.8)
        self.assertTrue(p.closed);self.assertFalse(p.quarantined)
        self.assertEqual([(e['reason'],e['session']) for e in s.events if e['type']=='session_end'],[('session_expired',sid)])
        self.assertFalse(any(e['type']=='failure' for e in s.events));self.assertFalse(p.capture)
    async def test_explicit_clear_is_not_a_ttl_notice(self):
        p,s,c=self.make();p.session.clear();await asyncio.wait_for(p.run(),1)
        self.assertFalse(any(e['type']=='session_end' for e in s.events))
    async def test_pending_generation_recognition_and_late_exit_confirm_before_notice(self):
        p,s,c=self.make();self.idle_to_590(p,c)
        p.capture.extend(b'synthetic');p.session.private=['PRIVATE'];p.session.facts={'synthetic':{}};p.session.secrets={'answer':'SYNTHETIC'}
        started=asyncio.Event();exit_done=asyncio.Event()
        async def closing():await asyncio.sleep(0);exit_done.set()
        async def generation():
            started.set()
            try:await asyncio.Future()
            finally:p.track_retired(asyncio.create_task(closing()))
        async def recognition():await asyncio.Future()
        p.generation=asyncio.create_task(generation());p.recognition=asyncio.create_task(recognition());await started.wait()
        old=p.generation;recognition_task=p.recognition;c.now=600.01
        await self.monitored(p)
        self.assertTrue(old.done() and recognition_task.done());self.assertTrue(exit_done.is_set())
        self.assertFalse(p.quarantined);self.assertFalse(p.capture or p.session.private or p.session.facts or p.session.secrets)
        self.assertFalse(any(not t.done() for t in p.retired_tasks))
        self.assertEqual(len([e for e in s.events if e['type']=='session_end']),1)
        await self.monitored(p) # idempotent even if a caller starts another monitor
        self.assertEqual(len([e for e in s.events if e['type']=='session_end']),1)
    async def test_new_scope_during_old_cleanup_is_not_notified_or_cleared(self):
        for change in ('session','epoch','revision','connection','turn','output'):
            p,s,c=self.make();self.idle_to_590(p,c)
            old=p.session;started=asyncio.Event();replaced=asyncio.Event()
            async def generation():
                started.set()
                try:await asyncio.Future()
                finally:
                    if change=='session':p.session=Session(c)
                    elif change=='epoch':p.epoch+=1
                    elif change=='revision':p.revision+=1
                    elif change=='connection':p.session.connection+=1
                    elif change=='turn':p.session.turn+=1
                    else:p.session.output+=1
                    replaced.set()
            p.generation=asyncio.create_task(generation());await started.wait();c.now=600.01
            old.poll();scope=(old,0,0,old.connection,0,old.output)
            self.assertFalse(await p.finish_session_expiry(scope),change)
            self.assertTrue(replaced.is_set());self.assertFalse(any(e['type']=='session_end' for e in s.events),change)
            if change=='session':self.assertTrue(p.session.active)
    async def test_unconfirmed_closing_resource_cannot_emit_normal_end(self):
        p,s,c=self.make();self.idle_to_590(p,c);release=asyncio.Event()
        task=asyncio.create_task(release.wait());p.track_retired(task);c.now=600.01
        try:
            await self.monitored(p)
            self.assertTrue(p.quarantined);self.assertFalse(task.done())
            self.assertTrue(any(e.get('code')=='voice' for e in s.events))
            self.assertFalse(any(e['type']=='session_end' for e in s.events))
            self.assertIn(task,p.retired_tasks)
        finally:release.set();await task;await asyncio.sleep(0)
    async def test_safety_refusal_still_has_scoped_local_help_not_normal_end(self):
        p,s,c=self.make();p.session.begin_turn();p.session.drain_commands()
        p.generation=asyncio.create_task(p.respond('我想伤害自己',0))
        await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='synthetic')));await p.generation
        failures=[e for e in s.events if e['type']=='failure']
        self.assertEqual(failures[0]['code'],'safety');self.assertIn('local_help',failures[0])
        self.assertFalse(any(e['type']=='session_end' for e in s.events))
    async def test_ttl_first_with_still_valid_reply_does_not_extend_any_budget(self):
        for progress in (False,True):
            p,s,c=self.make();self.idle_to_590(p,c)
            p.session.deadline=610;p.session.response_confirmed=progress;p.session.progress_deadline=620 if progress else 0
            prior=(p.session.expires,p.session.heartbeat_deadline,p.session.deadline,p.session.progress_deadline)
            c.now=600.01;await self.monitored(p)
            self.assertEqual((p.session.expires,p.session.heartbeat_deadline,p.session.deadline,p.session.progress_deadline),prior)
            self.assertEqual([e['reason'] for e in s.events if e['type']=='session_end'],['session_expired'])
    async def test_replacement_generation_during_cancel_cannot_borrow_notice(self):
        p,s,c=self.make();self.idle_to_590(p,c);started=asyncio.Event();replacement=[]
        async def generation():
            started.set()
            try:await asyncio.Future()
            finally:
                task=asyncio.create_task(asyncio.sleep(100));p.generation=task;replacement.append(task)
        p.generation=asyncio.create_task(generation());await started.wait();c.now=600.01;p.session.poll()
        try:
            scope=(p.session,p.epoch,p.revision,p.session.connection,p.session.turn,p.session.output)
            self.assertFalse(await p.finish_session_expiry(scope))
            self.assertFalse(any(e['type']=='session_end' for e in s.events));self.assertFalse(replacement[0].done())
        finally:
            for task in replacement:task.cancel()
            await asyncio.gather(*replacement,return_exceptions=True)
    async def test_old_monitor_cleanup_does_not_close_replacement_session_in_run(self):
        p,s,c=self.make();self.idle_to_590(p,c);old=p.session;started=asyncio.Event();replaced=asyncio.Event()
        async def generation():
            started.set()
            try:await asyncio.Future()
            finally:
                p.session=Session(c);p.epoch+=1;p.sequence=-1;replaced.set()
        p.generation=asyncio.create_task(generation());await started.wait()
        running=asyncio.create_task(p.run());await s.receiving.wait();c.now=600.01
        try:
            await asyncio.wait_for(replaced.wait(),1);await asyncio.sleep(.12)
            self.assertIsNot(p.session,old);self.assertTrue(p.session.active);self.assertFalse(running.done())
            self.assertFalse(any(e['type']=='session_end' for e in s.events))
        finally:
            running.cancel();await asyncio.gather(running,return_exceptions=True)
    async def test_ttl_with_still_valid_ingress_never_renews_original_boundary(self):
        p,s,c=self.make();self.idle_to_590(p,c)
        p.awaiting_input=True;p.input_budget.speech(0);original=p.input_budget.deadline;c.now=600.01
        await self.monitored(p)
        self.assertEqual(p.input_budget.deadline,original);self.assertFalse(p.awaiting_input)
        self.assertEqual([e['reason'] for e in s.events if e['type']=='session_end'],['session_expired'])
