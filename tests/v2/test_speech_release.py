"""Real local websocket lifetime; no supplier, credentials, model or device."""
import asyncio
import base64
import hashlib
import json
import time
import tempfile
from pathlib import Path
import unittest
from contextlib import asynccontextmanager
from websockets.asyncio.server import serve
from backend.v2.speech import V2Speech,SpeechReleaseError
from backend.v2.companion import UnifiedProviders
from scripts.v2_multiturn_probe import run_case
from tests.v2 import test_multiturn_probe as fixtures
from tests.v2.test_m05 import Model,plan

class Release(unittest.IsolatedAsyncioTestCase):
    def speech(self,port):
        value=V2Speech(None,workspace='synthetic',region='cn-beijing',key='SYNTHETIC_ONLY',asr='fake',llm='qwen4-max',tts='fake',voice='fake')
        value.ws_url=f'ws://127.0.0.1:{port}';return value

    @asynccontextmanager
    async def server(self,handler):
        async with serve(handler,'127.0.0.1',0,close_timeout=.1) as server:
            yield server.sockets[0].getsockname()[1]

    async def idle(self,socket):await socket.wait_closed()

    async def test_real_normal_close_confirms_connection_lost_and_tasks(self):
        async with self.server(self.idle) as port:
            speech=self.speech(port);start=time.monotonic()
            async with speech.speech_socket() as socket:pass
            self.assertTrue(socket.connection_lost_waiter.done())
            self.assertTrue(speech.last_release['confirmed']);self.assertEqual(speech.last_release['pending_tasks'],0)
            self.assertLess(time.monotonic()-start,.5)
            await asyncio.sleep(0);self.assertFalse(speech.release_tasks)

    @asynccontextmanager
    async def silent_server(self):
        release=asyncio.Event();handlers=[]
        async def raw(reader,writer):
            handlers.append(asyncio.current_task())
            try:
                request=await reader.readuntil(b'\r\n\r\n')
                key=next(line.split(b':',1)[1].strip() for line in request.split(b'\r\n') if line.lower().startswith(b'sec-websocket-key:'))
                accept=base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                writer.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n');await writer.drain()
                await release.wait() # never reads or acknowledges Close
            finally:writer.close();await writer.wait_closed()
        server=await asyncio.start_server(raw,'127.0.0.1',0)
        try:yield server.sockets[0].getsockname()[1]
        finally:
            release.set();server.close();await server.wait_closed();await asyncio.gather(*handlers)

    async def test_real_peer_does_not_respond_to_close_is_aborted_and_confirmed(self):
        async with self.silent_server() as port:
            speech=self.speech(port);start=time.monotonic()
            async with speech.speech_socket() as socket:pass
            self.assertLess(time.monotonic()-start,.5)
            self.assertTrue(socket.connection_lost_waiter.done());self.assertTrue(speech.last_release['confirmed'])
            self.assertEqual(speech.last_release['pending_tasks'],0)

    async def test_cancel_during_real_unanswered_close_aborts_then_confirms_before_raising(self):
        async with self.silent_server() as port:
            speech=self.speech(port);entered=asyncio.Event();captured=[]
            async def body():
                async with speech.speech_socket() as socket:captured.append(socket);entered.set()
            task=asyncio.create_task(body());await entered.wait();await asyncio.sleep(.02);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(captured[0].connection_lost_waiter.done())
            self.assertEqual(speech.last_release,{'confirmed':True,'aborted':True,'pending_tasks':0})

    async def test_real_cancelled_body_confirms_release_and_propagates_cancel(self):
        entered=asyncio.Event();captured=[]
        async with self.server(self.idle) as port:
            speech=self.speech(port)
            async def body():
                async with speech.speech_socket() as socket:
                    captured.append(socket);entered.set();await asyncio.Future()
            task=asyncio.create_task(body());await entered.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(captured[0].connection_lost_waiter.done());self.assertTrue(speech.last_release['confirmed'])

    async def test_real_body_failure_preserved_after_confirmed_release(self):
        async with self.server(self.idle) as port:
            speech=self.speech(port)
            with self.assertRaisesRegex(ValueError,'synthetic_body'):
                async with speech.speech_socket() as socket:raise ValueError('synthetic_body')
            self.assertTrue(socket.connection_lost_waiter.done());self.assertTrue(speech.last_release['confirmed'])

    async def test_unconfirmed_connection_lost_fails_closed_no_second_connect(self):
        speech=self.speech(1);release=asyncio.Event();closing=[]
        class Transport:
            def abort(self):pass # cannot confirm OS close, must not be treated as success
        class Socket:
            keepalive_task=None;transport=Transport()
            connection_lost_waiter=asyncio.get_running_loop().create_future()
            async def close(self):
                closing.append(asyncio.current_task())
                while not release.is_set():
                    try:await release.wait()
                    except asyncio.CancelledError:pass
            async def wait_closed(self):await asyncio.shield(self.connection_lost_waiter)
        socket=Socket()
        try:
            start=time.monotonic()
            with self.assertRaises(SpeechReleaseError):await speech._release(socket)
            self.assertLess(time.monotonic()-start,.5);self.assertTrue(speech.release_failed)
            self.assertFalse(speech.last_release['confirmed'])
            self.assertGreater(speech.last_release['pending_tasks'],0);self.assertTrue(speech.release_tasks)
            with self.assertRaises(SpeechReleaseError):
                async with speech.speech_socket():self.fail('must not connect')
        finally:
            release.set();await asyncio.gather(*tuple(speech.release_tasks),return_exceptions=True)

    async def tts(self,socket):
        async for raw in socket:
            event=json.loads(raw);header=event['header'];action=header['action'];id=header['task_id']
            if action=='run-task':await socket.send(json.dumps({'header':{'task_id':id,'event':'task-started'}}))
            elif action=='finish-task':
                await socket.send(b'\x01\x00'*4800)
                await socket.send(json.dumps({'header':{'task_id':id,'event':'task-finished'}}))
                await socket.wait_closed();return

    async def test_actual_voicepeer_three_turns_two_sentences_each_real_local_tts(self):
        async with self.server(self.tts) as port:
            speech=self.speech(port);model=Model(plan())
            model.next_plan.update(mode='story',rules='轮流编故事',roles=['小猫'],anchors={},sentences=['第一句。','第二句。'])
            report=await run_case(fixtures.CASE,UnifiedProviders(speech,model))
            self.assertTrue(report['cleanup']['confirmed']);self.assertEqual(len(report['turns']),3)
            self.assertEqual(report['tts_requests'],6)
            for turn in report['turns']:
                self.assertTrue(all(turn['checks'].values()));self.assertTrue(turn['delivery_metadata']['game_committed'])
                self.assertEqual(turn['delivery_metadata']['acks_accepted'],4)
                self.assertTrue(all(r['exit_outcome']=='confirmed' for r in turn['resource_diagnostics']))
            await asyncio.sleep(0);self.assertFalse(speech.release_tasks)

    async def test_runtime_factory_selects_v2_adapter_without_changing_v1_default(self):
        from backend.v2.runtime import providers
        from backend.dashscope import DashScope
        from tests.v2.test_safety_help import CONFIG
        with tempfile.TemporaryDirectory() as directory:
            credential=Path(directory)/'dashscope-api-key';credential.write_text('SYNTHETIC_ONLY');credential.chmod(0o600)
            bundle=providers(None,environment=CONFIG,credential_directory=directory)
            self.assertIsInstance(bundle.speech,V2Speech)
            self.assertIs(bundle.model.speech,bundle.speech)
            self.assertIsNot(V2Speech.speech_socket,DashScope.speech_socket)
