"""Metadata-only observations; synthetic provider injections, never live calls."""
import asyncio,json,unittest
from contextlib import asynccontextmanager
from unittest.mock import patch
from backend.v2.failure_observer import FailureWindow,metadata,record
from backend.v2.voice import VoicePeer,Operation
from backend.v2.companion import UnifiedProviders,CompanionPolicy,ModelError
from backend.v2.diagnostics import mark_contract,mark_contract_detail
from tests.v2 import test_post_solo_probe as protocol

class Controls(unittest.TestCase):
    def peer(self):
        return VoicePeer(protocol.Wire(),object(),object(),clock=protocol.Clock())
    def test_default_disabled_and_cli(self):
        from backend.v2.live import parser
        self.assertFalse(parser().get_default('observe_failures'))
        p=self.peer()
        with patch('backend.v2.failure_observer.metadata',side_effect=AssertionError('must_not_allocate')):
            record(p,Operation(p,0,0),'plan',RuntimeError())
        self.assertFalse(hasattr(p,'failure_observer'))
    def test_fixed_enum_and_no_exception_body_or_arbitrary_class(self):
        class SECRET_CLASS(Exception):
            def __str__(self):raise AssertionError('never stringify')
        error=SECRET_CLASS('PRIVATE_BODY');error.contract_diagnostic=['PRIVATE'];error.contract_detail={'PRIVATE':1}
        self.assertEqual(metadata('PRIVATE_STAGE',error),dict(stage='unknown',kind='unknown',contract='unknown'))
        error=mark_contract_detail(mark_contract(ModelError('PRIVATE'),'plan_anchors'),'anchor_index_type')
        self.assertEqual(metadata('plan',error),dict(stage='plan',kind='ModelError',contract='plan_anchors',detail='anchor_index_type'))
    def test_peer_record_and_time_limits_are_shared_not_renewed(self):
        clock=protocol.Clock();rows=[];window=FailureWindow(rows.append,clock=clock)
        for _ in range(6):
            p=self.peer();window.attach(p)
            for _ in range(10):record(p,Operation(p,0,0),'plan',RuntimeError('PRIVATE'))
        self.assertEqual((window.peers,window.records,len(rows)),(4,16,16))
        self.assertEqual({r['record'] for r in rows},{1,2,3,4})
        rows=[];window=FailureWindow(rows.append,clock=clock);p=self.peer();window.attach(p)
        clock.now+=900;record(p,Operation(p,0,0),'plan',RuntimeError());window.attach(self.peer())
        self.assertFalse(rows);self.assertEqual(window.peers,1)
    def test_stale_private_and_replacement_peer_cannot_become_current(self):
        for change in ('revision','epoch','turn','connection','session','private','cancel','closed','management','lease'):
            with self.subTest(change=change):
                rows=[];p=self.peer();window=FailureWindow(rows.append);window.attach(p);op=Operation(p,0,0)
                if change=='revision':p.revision+=1
                elif change=='epoch':p.epoch+=1
                elif change=='turn':p.session.turn+=1
                elif change=='connection':p.session.connection+=1
                elif change=='session':p.session=self.peer().session
                elif change=='private':p.session.private_mode=True
                elif change=='cancel':op.cancelled=True
                elif change=='closed':p.closed=True
                elif change=='management':p.session.management_paused=True
                elif change=='lease':p.session.clock.now=116
                record(p,op,'plan',RuntimeError());self.assertFalse(rows)
    def test_response_none_revision_cannot_borrow_new_revision(self):
        rows=[];p=self.peer();window=FailureWindow(rows.append);window.attach(p);op=Operation(p,0)
        p.revision=1;record(p,op,'plan',RuntimeError(),revision=0);self.assertFalse(rows)
    def test_observer_failure_isolated_and_disabled(self):
        def broken(row):raise RuntimeError('PRIVATE_OBSERVER')
        p=self.peer();window=FailureWindow(broken);window.attach(p)
        record(p,Operation(p,0,0),'plan',RuntimeError());self.assertTrue(window.disabled)
        record(p,Operation(p,0,0),'plan',RuntimeError());self.assertEqual(window.records,1)
    def test_namespace_sink_has_only_whitelisted_scalars(self):
        import io
        from backend.v2.failure_observer import journal_sink
        rows=[];p=self.peer();window=FailureWindow(rows.append);window.attach(p)
        p.failure_observer.record(p,Operation(p,0,0),dict(stage='plan',kind='PRIVATE',contract='PRIVATE',detail='PRIVATE',body='PRIVATE'))
        output=io.StringIO()
        with patch('sys.stderr',output):journal_sink(rows[0])
        value=json.loads(output.getvalue());self.assertNotIn('PRIVATE',output.getvalue())
        self.assertEqual(set(value),{'service','event','stage','kind','contract','detail','peer','record','turn','epoch','revision','elapsed_ms'})
    def test_async_observer_is_rejected_without_orphan(self):
        async def async_sink(row):pass
        with self.assertRaises(ValueError):FailureWindow(async_sink)
        p=self.peer();window=FailureWindow(lambda row:async_sink(row));window.attach(p)
        record(p,Operation(p,0,0),'plan',RuntimeError());self.assertTrue(window.disabled)
    def test_same_peer_cannot_reopen_its_record_allowance(self):
        rows=[];p=self.peer();window=FailureWindow(rows.append);window.attach(p)
        for _ in range(8):
            window.attach(p);record(p,Operation(p,0,0),'plan',RuntimeError())
        self.assertEqual(window.peers,1);self.assertEqual(len(rows),4)
    def test_release_package_selects_module(self):
        from backend.v2.release import selected
        self.assertTrue(selected('backend/v2/failure_observer.py'))

class FailureTLS(unittest.IsolatedAsyncioTestCase):
    async def scenario(self,injection,sink=None):
        # Use exactly production authenticated TLS, Session, ASR/endpoint/PLAN/
        # FACTS/review gates and wire ACK; only providers are synthetic.
        t=protocol.ResolutionTLS('test_solo_full_reply_then_next_probe_and_turn_are_not_stale')
        rows=[]
        def collect(row):
            rows.append(row)
            if sink is not None:sink(row)
        window=FailureWindow(collect)
        from backend.v2 import server as production_server
        serve=production_server.voice_server
        def observed_server(*args,**kwargs):
            return serve(*args,**kwargs,failure_observation=window)
        with patch('backend.v2.server.voice_server',observed_server):await t.asyncSetUp()
        self.assertEqual(window.peers,1)
        @asynccontextmanager
        async def intro(rate):
            class R:
                async def write(self,pcm):pass
                async def finish(self):return '你好瓦力，请介绍一下你自己。'
            yield R()
        t.speech.recognize=intro
        try:
            await t.probe(1,110);await t.until('endpoint');await t.send('seal',revision=1);await t.finish_reply()
            self.assertEqual(t.peer.session.turn,2)
            before=len([r for r in t.wire.events if r['type']=='audio'])
            # Same synthetic text, continuation invalidates the earlier snapshot.
            t.model.block=True;await t.probe(2,111);await t.model.entered.get() # first previous entry
            async with asyncio.timeout(1):
                while t.model.endpoint_calls<2:await asyncio.sleep(0)
            await t.probe(3,111.6)
            async with asyncio.timeout(1):
                while t.peer.revision!=3 or t.model.endpoint_calls<3:await asyncio.sleep(0)
            t.model.release.set();await t.until('endpoint')
            if injection=='plan':
                t.model.next_plan['anchors']={'synthetic':True}
            elif injection=='facts':
                t.model.extracted=[dict(key='preference',value='synthetic',source_id='bad',source_text='bad')]
                # Model fixture intentionally drops source fields: force contract failure directly.
                async def invalid_facts(text):raise mark_contract(ModelError('PRIVATE'),'fact_source_mismatch')
                t.providers.facts=invalid_facts
            elif injection=='review':t.model.allowed=False
            elif injection=='tts':
                @asynccontextmanager
                async def broken(*args):
                    raise RuntimeError('PRIVATE_TTS');yield
                t.speech.synthesize=broken
            from copy import deepcopy
            before_game=deepcopy(t.peer.session.game);before_public=list(t.peer.session.public)
            await t.send('seal',revision=3)
            if injection:
                async with asyncio.timeout(2):
                    while True:
                        event=await t.wire.outgoing.get()
                        if event['type']=='decision':
                            t.epoch+=1;t.seq=0;await t.send('stop',intent=event['intent'])
                        elif event['type']=='open':await t.send('bind',player='synthetic-failure')
                        elif event['type']=='failure':failure=event;break
                        elif event['type']=='audio':self.fail('bad candidate cannot emit audio')
                await t.peer.generation
                self.assertEqual(len([r for r in t.wire.events if r['type']=='audio']),before)
                self.assertEqual(len(rows),1)
                self.assertEqual(t.peer.session.game,before_game);self.assertEqual(t.peer.session.public,before_public)
                self.assertFalse(t.peer.session.pending)
                expected={'plan':('plan','ModelError','plan_anchors'),'facts':('facts','ModelError','fact_source_mismatch'),
                          'review':('safety','SafetyFault','unknown'),'tts':('synthesis','RuntimeError','unknown')}
                self.assertEqual(tuple(rows[0][k] for k in ('stage','kind','contract')),expected[injection])
                self.assertNotIn('stage',failure);self.assertNotIn('contract',failure)
                if sink is not None:self.assertTrue(window.disabled)
                return rows[0]
            await t.finish_reply();self.assertEqual(t.peer.session.turn,3)
            self.assertFalse(rows)
        finally:
            await t.asyncTearDown()
            self.assertFalse(t.peer.quarantined)
            self.assertFalse(any(not task.done() for task in t.peer.retired_tasks))
    async def test_intro_full_ack_then_same_text_continuation_failures(self):
        for stage in ('plan','facts','review','tts'):
            with self.subTest(stage=stage):await self.scenario(stage)
    async def test_successful_reply_emits_no_failure_record(self):
        # Success has no failure record; throwing observer on a failure is checked
        # separately below and still delivers the original failure wire.
        await self.scenario(None)

    async def test_throwing_observer_preserves_failure_wire_and_cleanup(self):
        def broken(row):raise RuntimeError('PRIVATE')
        await self.scenario('plan',broken)
