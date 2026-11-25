"""Targeted R88-01/provisioned adapter checks, with no provider/voice/device sampling."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from backend.v2.companion import CompanionPolicy, UnifiedProviders
from backend.v2.runtime import providers as configured_providers, settings, manifest
from backend.v2.voice import VoicePeer

spec = importlib.util.spec_from_file_location('r88_original', Path(__file__).resolve().parents[2] / 'docs/testing/v2/r88-01/original/test_m10.py')
_qa = importlib.util.module_from_spec(spec)
_previous = os.environ.get('M10_REQUIRE_HELP')
os.environ['M10_REQUIRE_HELP'] = '1'
try:
    spec.loader.exec_module(_qa)
finally:
    if _previous is None:
        os.environ.pop('M10_REQUIRE_HELP', None)
    else:
        os.environ['M10_REQUIRE_HELP'] = _previous

CONFIG = dict(DASHSCOPE_WORKSPACE='synthetic', DASHSCOPE_REGION='cn-beijing',
              DASHSCOPE_ASR_MODEL='fun-asr-realtime', DASHSCOPE_LLM_MODEL='qwen3.8-flash',
              DASHSCOPE_TTS_MODEL='cosyvoice-v3-flash', DASHSCOPE_TTS_VOICE='longanyang')


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now


class SafetyHelp(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, verdict='outage', *, mode='story', sentences=None, hook=None, revoke=None,
                       text='讲一个猫船长的故事', plan_outage=False):
        speech, socket, requests, clock = _qa.Speech(), _qa.Socket(), [], Clock()
        sentences = sentences or ['猫船长带队去月球。']
        count = 0
        async def response(request):
            nonlocal count
            body = json.loads(request.content); requests.append(body)
            instruction = body['messages'][0]['content']
            if '审核下一个' in instruction:
                count += 1
                if hook: await hook(socket.peer, count)
                value = verdict[count-1] if isinstance(verdict, list) else verdict
                if value == 'timeout': raise httpx.ReadTimeout('SYNTHETIC_PRIVATE_PROVIDER_ERROR')
                if value == 'outage': return httpx.Response(503, json={'error': {'message': 'SYNTHETIC_PRIVATE_PROVIDER_ERROR'}})
                content = value if isinstance(value, str) else json.dumps({'allow': value})
            elif '提取孩子' in instruction:
                content = '{"facts":[]}'
            else:
                if plan_outage: return httpx.Response(503)
                content = json.dumps(dict(action='continue', mode=mode, rules='轮流', roles=['猫船长'],
                    secrets={}, sentences=sentences, anchors={}))
            return httpx.Response(200, json={'choices': [{'message': {'content': content}}]})
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            service = directory/'service.env'
            service.write_text('\n'.join(f'{k}="{v}"' for k,v in CONFIG.items()))
            (directory/'dashscope-api-key').write_text('SYNTHETIC_PRIVATE_KEY')
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
                bundle = configured_providers(http, environment={}, service_env=service, credential_directory=directory)
                self.assertEqual(bundle.speech.asr, CONFIG['DASHSCOPE_ASR_MODEL'])
                self.assertEqual(bundle.speech.tts, CONFIG['DASHSCOPE_TTS_MODEL'])
                # Actual configured model/HTTP adapter; synthesis is explicitly synthetic and offline.
                bundle.speech = speech
                peer = VoicePeer(socket, bundle, CompanionPolicy(), clock=clock); socket.peer = peer
                original_send = socket.send
                async def send(raw):
                    await original_send(raw)
                    if json.loads(raw)['type'] == 'revoke' and revoke: await revoke(peer, clock)
                socket.send = send
                peer.session.begin_turn(); peer.session.drain_commands()
                await peer.send('open', revision=0)
                task = asyncio.create_task(peer.respond(text, 0))
                peer.generation = task
                await peer.handle(json.dumps(dict(v=2, type='bind', epoch=0, seq=0, player='p')))
                try:
                    await asyncio.wait_for(task, 2)
                finally:
                    if not task.done(): task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        return peer, speech, socket.events, requests

    def help(self, events):
        return [e for e in events if e['type']=='failure' and e.get('code')=='safety']

    async def test_503_is_local_enum_payload_with_preestablished_scope_and_no_tts(self):
        peer, speech, events, requests = await self.exercise()
        error = self.help(events).pop()
        self.assertEqual(error['local_help'],dict(v=1,prompt_id='safety_support_v1',reason='review_unavailable'))
        normal = next(e for e in events if e['type']=='open')
        self.assertEqual(tuple(error[k] for k in ('epoch','session','turn','revision')),
                         tuple(normal[k] for k in ('epoch','session','turn','revision')))
        self.assertEqual(speech.texts,[])
        self.assertLess(next(i for i,e in enumerate(events) if e['type']=='revoke'), events.index(error))
        encoded=json.dumps(events)+str(peer.last_failure)
        for value in ['SYNTHETIC_PRIVATE_PROVIDER_ERROR','SYNTHETIC_PRIVATE_KEY','猫船长带队去月球']:
            self.assertNotIn(value,encoded)
        self.assertEqual(len([r for r in requests if '审核下一个' in r['messages'][0]['content']]),1)

    async def test_timeout_malformed_and_false_are_strictly_classified(self):
        for verdict in ['timeout','{"allow":"true"}','{}','{"allow":true,"allow":false}',False]:
            with self.subTest(verdict=verdict):
                _,speech,events,_=await self.exercise(verdict)
                self.assertEqual(speech.texts,[])
                expected='content_blocked' if verdict is False else 'review_unavailable'
                self.assertEqual(self.help(events)[0]['local_help']['reason'],expected)

    async def test_normal_fiction_routes_all_four_games_and_chat_without_false_refusal(self):
        for mode in ['chat','guess','story','adventure','association']:
            with self.subTest(mode=mode):
                peer,speech,events,_=await self.exercise(True,mode=mode)
                self.assertEqual(speech.texts,['猫船长带队去月球。'])
                self.assertEqual(peer.session.game['mode'],mode)
                self.assertFalse(self.help(events));self.assertTrue(peer.session.public)
        _,speech,events,_=await self.exercise(True,text='猫船长说救救我，箱子太重。')
        self.assertTrue(speech.texts);self.assertFalse(self.help(events))

    async def test_explicit_help_cues_use_local_policy_even_when_model_is_down(self):
        for text in ['救救我','有人伤害我','我想伤害自己']:
            with self.subTest(text=text):
                _,speech,events,requests=await self.exercise(plan_outage=True,text=text)
                self.assertEqual(requests,[]);self.assertEqual(speech.texts,[])
                self.assertEqual(self.help(events)[0]['local_help']['reason'],'content_blocked')
                self.assertNotIn(text,json.dumps(events))

    async def test_later_segment_outage_never_synthesizes_the_unreviewed_remainder(self):
        peer,speech,events,_=await self.exercise([True,True,'outage'],sentences=['猫船长出发。','合成未审内容。'])
        self.assertEqual(speech.texts,['猫船长出发。']);self.assertEqual(peer.session.game,{})
        self.assertEqual(self.help(events)[0]['local_help']['reason'],'review_unavailable')
        self.assertNotIn('合成未审内容',json.dumps(events))

    async def test_new_input_during_review_cannot_borrow_the_new_revision_for_help(self):
        async def advance(peer,_):
            await peer.handle(json.dumps(dict(v=2,type='advance',epoch=0,seq=1,revision=1)))
        _,speech,events,_=await self.exercise(hook=advance)
        self.assertEqual(speech.texts,[]);self.assertFalse(self.help(events))

    async def test_handoff_during_review_cannot_notify_the_replacement_session(self):
        async def handoff(peer,_): peer.session.handoff()
        _,speech,events,_=await self.exercise(hook=handoff)
        self.assertEqual(speech.texts,[]);self.assertFalse(self.help(events))

    async def test_revoke_transport_yield_cannot_publish_help_after_expiry(self):
        async def expire(peer,clock): clock.now=10000
        peer,speech,events,_=await self.exercise(revoke=expire)
        self.assertEqual(speech.texts,[]);self.assertFalse(self.help(events));self.assertFalse(peer.session.active)

    async def test_cancellation_of_review_never_delivers_help_or_audio(self):
        async def cancel(peer,_): asyncio.current_task().cancel();await asyncio.sleep(0)
        with self.assertRaises(asyncio.CancelledError): await self.exercise(hook=cancel)

    async def test_local_help_disarms_old_response_budget_without_extending_idle_ttl(self):
        peer,_,events,_=await self.exercise()
        self.assertEqual(peer.session.deadline,0);self.assertFalse(peer.awaiting_input)
        expires=peer.session.expires
        for second in range(1,20):
            peer.session.clock.now=second
            peer.session.heartbeat();peer.session.poll()
        self.assertTrue(peer.session.active);self.assertFalse(peer.session.response_expired)
        self.assertEqual(peer.session.expires,expires);self.assertEqual(len(self.help(events)),1)

    async def test_plan_outage_without_help_cue_remains_distinct_from_review_failure(self):
        _,speech,events,_=await self.exercise(plan_outage=True)
        self.assertEqual(speech.texts,[]);self.assertFalse(self.help(events))
        self.assertEqual([e['code'] for e in events if e['type']=='failure'],['voice'])

    async def test_authenticated_local_tls_delivers_scoped_help_without_audio(self):
        import ssl
        import subprocess
        from websockets.asyncio.client import connect
        from backend.v2.server import voice_server
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
                '-keyout',str(root/'key'),'-out',str(root/'cert')],check=True,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'cert',root/'key')
            trust=ssl.create_default_context(cafile=str(root/'cert'))
            (root/'dashscope-api-key').write_text('SYNTHETIC_PRIVATE_KEY')
            async def response(request):
                instruction=json.loads(request.content)['messages'][0]['content']
                if '审核下一个' in instruction:return httpx.Response(503)
                plan=dict(action='continue',mode='story',rules='',roles=[],secrets={},
                          sentences=['猫船长出发。'],anchors={})
                return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan)}}]})
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
                bundle=configured_providers(http,environment=CONFIG,credential_directory=root)
                speech=_qa.Speech();bundle.speech=speech
                token='SyntheticOnly'*4
                async with voice_server('127.0.0.1',0,tls,token,bundle,CompanionPolicy()) as server:
                    port=server.sockets[0].getsockname()[1]
                    async with connect(f'wss://localhost:{port}/v2/voice',ssl=trust,proxy=None,
                                       additional_headers={'Authorization':'Bearer '+token}) as socket:
                        await socket.send(json.dumps(dict(v=2,type='wake_solo',epoch=0,seq=0,age_ms=0)))
                        async with asyncio.timeout(3):
                            decision=json.loads(await socket.recv())
                            self.assertEqual(decision['type'],'decision')
                            await socket.send(json.dumps(dict(v=2,type='stop',epoch=1,seq=0,intent=decision['intent'])))
                            events=[];bound=None
                            while True:
                                event=json.loads(await socket.recv());events.append(event)
                                if event['type']=='open':
                                    await socket.send(json.dumps(dict(v=2,type='bind',epoch=1,seq=1,player='local-software-test')))
                                elif event['type']=='bound':bound=event
                                elif event['type']=='failure':
                                    self.assertEqual(event['code'],'safety')
                                    self.assertEqual(event['session'],bound['session'])
                                    self.assertEqual(event['turn'],bound['turn'])
                                    self.assertEqual(event['local_help']['prompt_id'],'safety_support_v1');break
                            self.assertFalse(any(e['type']=='audio' for e in events));self.assertEqual(speech.texts,[])
                            await socket.send(json.dumps(dict(v=2,type='end',epoch=1,seq=2)))

    async def test_negative_control_reverting_failure_code_trips_the_original_assertion(self):
        original=VoicePeer.send
        async def generic(peer,kind,**fields):
            if kind=='failure' and fields.get('code')=='safety':fields['code']='voice'
            await original(peer,kind,**fields)
        with patch.object(VoicePeer,'send',generic):
            case=_qa.SafetyHelpAcceptance('test_r8801_safety_outage_preserves_independent_help')
            with self.assertRaises(AssertionError):await case.test_r8801_safety_outage_preserves_independent_help()


class RuntimeSettings(unittest.TestCase):
    def test_settings_are_literal_allowlisted_and_manifest_never_contains_credential_or_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'service.env'
            path.write_text('\n'.join(f'{k}="{v}"' for k,v in CONFIG.items())+'\nAPI_KEY=UNREAD_SECRET\n')
            config=settings(environment={},service_env=path)
            self.assertEqual(config['llm'],'qwen3.8-flash')
            public=json.dumps(manifest(config))
            self.assertNotIn('UNREAD_SECRET',public);self.assertNotIn('synthetic',public)
            self.assertEqual(manifest(config)['new_cloud_samples'],0)

    def test_shell_substitution_and_missing_credential_do_not_execute_or_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'service.env';marker=Path(directory)/'executed'
            path.write_text('\n'.join(f'{k}="{v}"' for k,v in CONFIG.items())+f'\nDASHSCOPE_LLM_MODEL="$(touch {marker})"\n')
            with self.assertRaisesRegex(ValueError,'settings'):settings(environment={},service_env=path)
            self.assertFalse(marker.exists())
            with self.assertRaisesRegex(ValueError,'credential'):configured_providers(object(),environment=CONFIG)
