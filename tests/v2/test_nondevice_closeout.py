"""Only synthetic material, temporary SQLite/TLS, no production endpoint."""
import asyncio,json,ssl,tempfile,time,unittest
from pathlib import Path
from hashlib import sha256
from uuid import uuid4
from unittest.mock import patch
from websockets.asyncio.client import connect
from backend.v2.session import Session
from backend.v2.feedback_store import FeedbackStore,FeedbackError
from backend.v2.feedback_receiver import configured_feedback,checked_runtime
from backend.v2.server import voice_server
from tests.v2.test_release import Fixture
from tests.v2.test_feedback_store import key_at

class CoexistingMemory(unittest.TestCase):
    def test_compact_query_preserves_roles_rules_clue_plot_negation_and_new_fact(self):
        s=Session(lambda:0);sid=s.session
        texts=[('role','孩子当船长，瓦力当领航员'),('rule','只能慢慢飞，不许传送'),('clue','钥匙在蓝色岩石下面'),('plot','先到月亮站，再找钥匙'),('preference','我不喜欢猫玩偶')]
        for key,text in texts:s.record_input(text,[dict(key=key,value=text,start=0,end=len(text))])
        expected=[v.copy() for v in s.facts.values()]
        s.begin_turn();s.drain_commands();s.bind_player('p');s.drain_commands()
        state=dict(mode='adventure',rules=texts[1][1],roles=[texts[0][1]],secrets={})
        self.assertTrue(s.send(s.task('tts'),name='key',public='下一站是月亮站。',end=240,approved=True,state=state,anchors=('plot.current',)))
        self.assertTrue(s.ack(s.task('ack'),player='p',stream=s.stream,segment='key',head=240))
        s.public.extend('合成背景'+str(n) for n in range(50))
        before=s.memory_snapshot();self.assertTrue(s.compact(before,[]))
        new='现在钥匙换到绿色岩石下面';s.record_input(new,[dict(key='clue',value=new,start=0,end=len(new))])
        context=s.context(query='船长 传送 钥匙 月亮站 猫')
        entries=list(context['facts'].values())
        for fact in expected:self.assertIn(fact,entries)
        self.assertIn(new,str(entries));self.assertEqual(context['game'],{k:v for k,v in state.items() if k!='secrets'})
        self.assertEqual(s.session,sid);self.assertTrue(s._fits())
        self.assertFalse(s.compact(before,[])) # stale pre-update snapshot cannot erase new evidence

class FeedbackIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_failure_disables_then_restart_recovers_original_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.db';runtime=checked_runtime(path);token='synthetic-v2-only';device=sha256(token.encode()).hexdigest()
            with self.assertRaisesRegex(FeedbackError,'storage'):
                async with configured_feedback(runtime,token) as receiver:
                    key=key_at(int(time.time()*1000));receipt=receiver.store.submit(device,key,'OTHER','synthetic',b'')
                    with patch.object(receiver.store,'sweep',side_effect=FeedbackError('storage')):
                        await asyncio.sleep(0);await asyncio.sleep(0)
                        self.assertTrue(receiver.disabled)
            async with configured_feedback(runtime,token) as recovered:
                self.assertFalse(recovered.disabled)
                self.assertEqual(recovered.store.read(device,key)['delete_by'],receipt['delete_by'])
                recovered.store.maintain(device,key,reply='synthetic administrator reply')
                self.assertEqual(recovered.store.read(device,key)['delete_by'],receipt['delete_by'])
                recovered.store.clock=lambda:receipt['delete_by']
                recovered.store.sweep()
                self.assertEqual(recovered.store.pending(),[])
            # Restart at the same controlled time; real wall time must not
            # roll back behind the persisted monotonic high-water mark.
            with patch('backend.v2.feedback_store.time.time',return_value=receipt['delete_by']/1000):
              async with configured_feedback(runtime,token) as restarted:
                result=restarted.request(json.dumps(dict(v=1,request=str(uuid4()),id=key,operation='withdraw')))
                self.assertFalse(result['result']['all_copies_deleted'])
                self.assertFalse(restarted.copies_reviewed)

    async def test_real_tls_fragmented_upload_cancel_withdraw_and_restart_rejects_replay(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture=Fixture(root);runtime=checked_runtime(root/'isolated.db')
            server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.load_cert_chain(root/'cert',root/'key')
            client_tls=ssl.create_default_context(cafile=str(root/'cert'))
            key=key_at(int(time.time()*1000));gate=asyncio.Event();started=asyncio.Event()
            raw=json.dumps(dict(v=1,request=str(uuid4()),id=key,operation='submit',category='OTHER',description='SYNTHETIC_UPLOAD_CANARY',logs=''))
            async def fragments():
                yield raw[:30];started.set();await gate.wait();yield raw[30:]
            async with configured_feedback(runtime,fixture.token) as receiver:
                async with voice_server('127.0.0.1',0,server_tls,fixture.token,object(),object(),feedback=receiver) as server:
                    url='wss://127.0.0.1:'+str(server.sockets[0].getsockname()[1])+'/v2/feedback'
                    async with connect(url,ssl=client_tls,proxy=None,additional_headers={'Authorization':'Bearer '+fixture.token}) as ws:
                        await ws.recv();upload=asyncio.create_task(ws.send(fragments()))
                        await asyncio.wait_for(started.wait(),1)
                        upload.cancel();await asyncio.gather(upload,return_exceptions=True)
                    async with asyncio.timeout(1):
                        while receiver.active:await asyncio.sleep(.001)
                    self.assertEqual(receiver.store.pending(),[])
                    async with connect(url,ssl=client_tls,proxy=None,additional_headers={'Authorization':'Bearer '+fixture.token}) as ws:
                        await ws.recv();await ws.send(json.dumps(dict(v=1,request=str(uuid4()),id=key,operation='withdraw')))
                        receipt=json.loads(await ws.recv());self.assertTrue(receipt['ok'])
                        self.assertFalse(receipt['result']['all_copies_deleted'])
                        await ws.send(raw);self.assertEqual(json.loads(await ws.recv())['error'],'deleted')
            async with configured_feedback(runtime,fixture.token) as restarted:
                self.assertEqual(restarted.request(raw)['error'],'deleted')
                self.assertFalse(restarted.copies_reviewed)
                self.assertNotIn(b'SYNTHETIC_UPLOAD_CANARY',(root/'isolated.db').read_bytes())
