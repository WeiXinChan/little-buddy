"""Actual VoicePeer + UnifiedProviders + synthetic HTTP/PNG; real cloud calls zero."""
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
import json
import unittest
from unittest.mock import patch
import httpx
from backend.v2.companion import UnifiedProviders, CompanionPolicy
from backend.v2.dynamic_images import QwenImages, ReviewDecision, ImageConfig
from backend.v2.protocol import CONTRACT
from backend.v2.voice import VoicePeer, WireError
from tests.v2.test_m05 import Model, Socket
from tests.v2.test_images import Speech
from tests.v2.test_dynamic_images import RAW, PNG, CONFIG, Stream


class Wire(unittest.IsolatedAsyncioTestCase):
    async def make(self,*,mode='chat',action='continue',secrets=None,sentence='我们一起看看猫。',
                   kind='generate_image',feature='images_v2',hook=None,http_hook=None,config=CONFIG):
        calls=[]
        async def transport(request):
            calls.append(request)
            if http_hook:await http_hook()
            body=json.dumps(dict(data=[dict(b64_json=base64.b64encode(RAW).decode())])).encode()
            return httpx.Response(200,headers={'content-type':'application/json'},stream=Stream(body))
        async def prompt(text,nonce):return ReviewDecision(True,sha256(text.encode()).hexdigest(),nonce,CONFIG.prompt_policy)
        async def image(png,nonce):return ReviewDecision(True,sha256(png).hexdigest(),nonce,CONFIG.image_policy)
        http=httpx.AsyncClient(transport=httpx.MockTransport(transport));self.addAsyncCleanup(http.aclose)
        adapter=QwenImages(http,config=config,api_key='SYNTHETIC_ONLY',prompt_reviewer=prompt,image_reviewer=image)
        self.addAsyncCleanup(adapter.aclose)
        plan=dict(action=action,mode=mode,rules='轮流',roles=['猫船长'],secrets=secrets or {},sentences=[sentence],anchors={},
                  tools=[dict(kind=kind,asset_id='cat')])
        provider=UnifiedProviders(Speech(),Model(plan),dynamic_images=adapter)
        class WireSocket(Socket):
            async def send(self,raw):
                if hook:await hook(json.loads(raw))
                await super().send(raw)
        socket=WireSocket();socket.acknowledge=False
        peer=VoicePeer(socket,provider,CompanionPolicy());socket.peer=peer
        self.addAsyncCleanup(self.cleanup,peer)
        await self.start(peer,socket,feature=feature)
        return peer,socket,calls

    async def cleanup(self,peer):
        peer.invalidate_visual()
        if peer.generation and not peer.generation.done():peer.generation.cancel()
        await asyncio.gather(*([peer.generation] if peer.generation else []),*peer.retired_tasks,return_exceptions=True)

    async def until(self,condition):
        async def wait():
            while not condition():await asyncio.sleep(.001)
        await asyncio.wait_for(wait(),2)

    async def start(self,peer,socket,feature='images_v2'):
        peer.session.begin_turn();peer.session.drain_commands()
        peer.generation=asyncio.create_task(peer.respond('一起玩',peer.epoch))
        fields=dict(v=2,type='bind',epoch=peer.epoch,seq=peer.sequence+1,player='p'+str(peer.session.turn),features=[feature])
        if feature=='images_v2':fields['image_contract']=CONTRACT
        await peer.handle(json.dumps(fields))
        await self.until(lambda:any(e['type']=='audio' and e['stream']==peer.session.stream for e in socket.events))

    async def ack(self,peer,event,head=None):
        identity=replace(peer.ack_identity,sequence=peer.ack_sequence);peer.ack_sequence+=1
        peer.session.ack(identity,player=event['player'],stream=event['stream'],segment=event['segment'],
                         head=event['end'] if head is None else head)
        await peer.commands()

    async def finish(self,peer,socket):
        for event in list(socket.events):
            if event['type']=='audio' and event['stream']==peer.session.stream:await self.ack(peer,event)
        await asyncio.wait_for(peer.generation,2)
        if peer.visual_task:await asyncio.wait_for(peer.visual_task,2)

    def displays(self,socket):return [e for e in socket.events if e['type']=='image_display' and e['action']!='hide']

    async def test_actual_dynamic_png_transport_only_after_full_played_ack(self):
        p,s,calls=await self.make()
        self.assertEqual(calls,[]);self.assertFalse(any(e['type'].startswith('image_') for e in s.events))
        final=[e for e in s.events if e['type']=='audio'][-1]
        await self.ack(p,final,final['end']-1);self.assertEqual(calls,[])
        await self.finish(p,s)
        begin=next(e for e in s.events if e['type']=='image_begin')
        packets=[e for e in s.events if e['type']=='image_chunk']
        png=b''.join(base64.b64decode(e['data'],validate=True) for e in packets)
        self.assertEqual(png,PNG);self.assertEqual(sha256(png).hexdigest(),begin['sha256'])
        self.assertEqual(len(png),begin['bytes']);self.assertEqual(len(packets),begin['chunks'])
        self.assertEqual([e['index'] for e in packets],list(range(len(packets))))
        self.assertEqual([e['offset'] for e in packets],[i*8192 for i in range(len(packets))])
        self.assertTrue(all(len(json.dumps(e).encode())<=16000 for e in s.events if e['type'].startswith('image_')))
        display=self.displays(s)[0];self.assertEqual(display['source'],'dynamic');self.assertEqual(display['duration_ms'],6000)
        for e in packets+[display]:
            for key in ('session','turn','epoch','revision','topic','token','image_id','sha256'):
                self.assertEqual(e[key],begin[key])
        self.assertEqual(display['segment'],final['segment']);self.assertEqual(display['end'],final['end'])
        self.assertEqual(len(calls),1);self.assertTrue(p.providers.dynamic_images._last.released)

    async def test_story_duration_and_auto_hide_restore_eyes_keep_only_bounded_cache(self):
        p,s,_=await self.make(mode='story');await self.finish(p,s)
        self.assertEqual(self.displays(s)[0]['duration_ms'],12000)
        cache=p.visual_cache;deadline=cache.deadline
        cache.visible_until=asyncio.get_running_loop().time()-.001
        await p.poll_visual()
        hide=s.events[-1];self.assertEqual((hide['type'],hide['action'],hide['eyes']),('image_display','hide',True))
        self.assertIs(p.visual_cache,cache);self.assertEqual(cache.deadline,deadline)
        cache.release();await p.poll_visual();self.assertIsNone(p.visual_cache);self.assertFalse(cache.png)

    async def test_disabled_resource_is_unavailable_not_fake_dynamic_or_fee(self):
        p,s,calls=await self.make(config=ImageConfig());await self.finish(p,s)
        self.assertEqual(calls,[]);self.assertEqual(self.displays(s),[])
        self.assertEqual([e['state'] for e in s.events if e['type']=='image_status'],['unavailable'])
        self.assertIsNone(p.visual_cache)

    async def test_private_and_unspoken_riddle_never_dispatch_image_request(self):
        for args in (dict(action='private'),dict(mode='guess',secrets={'answer':'猫'},sentence='它喜欢捉老鼠。')):
            p,s,calls=await self.make(**args);await self.finish(p,s)
            self.assertEqual(calls,[]);self.assertEqual(self.displays(s),[])

    async def test_spoken_answer_is_not_exported_until_exact_ack(self):
        p,s,calls=await self.make(mode='guess',secrets={'answer':'猫'},sentence='答案是猫。')
        self.assertEqual(calls,[]);await self.finish(p,s)
        self.assertEqual(len(calls),1);self.assertEqual(p.session.secrets,{})
        self.assertEqual(len(self.displays(s)),1)

    async def test_legacy_images_v1_only_static_fallback_never_dynamic_bytes(self):
        p,s,calls=await self.make(feature='images_v1');await self.finish(p,s)
        self.assertEqual(calls,[]);self.assertFalse(any(e['type']=='image_chunk' for e in s.events))
        self.assertTrue(any(e['type']=='image_ready' and e['source']=='default' for e in s.events))
        self.assertTrue(any(e['type']=='reveal' for e in s.events))

    async def test_new_scope_contract_required_for_images_v2(self):
        p,s,_=await self.make();await self.finish(p,s)
        await p.send('scope');self.assertEqual(s.events[-1]['protocol_contract'],CONTRACT)
        p.session.interrupt();await p.commands()
        with self.assertRaisesRegex(WireError,'image contract'):
            await p.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=1,player='new',features=['images_v2'],image_contract='old')))

    async def test_revoke_during_http_never_sends_late_image_or_keeps_buffer(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def blocked():entered.set();await release.wait()
        p,s,_=await self.make(http_hook=blocked)
        for event in list(s.events):
            if event['type']=='audio':await self.ack(p,event)
        await entered.wait();p.revision+=1;await p.hide_visual('input_changed');release.set()
        await self.until(lambda:not p.retired_tasks)
        self.assertEqual(self.displays(s),[]);self.assertIsNone(p.visual_cache)
        self.assertFalse(any(e['type']=='image_chunk' for e in s.events))

    async def test_blocked_chunk_scope_change_rejects_all_later_delivery_and_erases(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def block(event):
            if event['type']=='image_chunk':entered.set();await release.wait()
        p,s,_=await self.make(hook=block)
        for event in list(s.events):
            if event['type']=='audio':await self.ack(p,event)
        await entered.wait();cache=p.visual_cache
        p.session.pause_management();p.invalidate_visual();release.set()
        await self.until(lambda:not p.retired_tasks)
        self.assertEqual(self.displays(s),[]);self.assertTrue(cache.released);self.assertFalse(cache.png)
        self.assertFalse(any(e['type']=='image_ready' for e in s.events))

    async def test_session_topic_turn_epoch_revision_connection_and_player_isolation(self):
        for mutation in ('topic','turn','epoch','revision','connection','player','stream','private','expired'):
            p,s,_=await self.make();await self.finish(p,s);cache=p.visual_cache
            if mutation in {'epoch','revision'}:setattr(p,mutation,getattr(p,mutation)+1)
            elif mutation=='private':p.session.private_mode=True
            elif mutation=='expired':p.session.expires=p.session.clock()
            elif mutation=='player':p.session.player='other'
            else:setattr(p.session,mutation,getattr(p.session,mutation)+1)
            if mutation in {'epoch','revision','turn','player','stream'}:
                p.invalidate_visual(keep_cache=True) # public cache may survive media changes, never old delivery
                self.assertIsNone(p.display_scope)
            else:
                await p.poll_visual();self.assertTrue(cache.released)

    async def control(self,p,s,kind):
        cache=p.visual_cache
        p.revision+=1;await p.hide_visual('input_changed')
        p.session.interrupt();await p.commands()
        plan=dict(p.providers.model.next_plan,tools=[dict(kind=kind)],secrets={},action='continue')
        p.providers.model.next_plan=plan
        await self.start(p,s);await self.finish(p,s)
        return cache

    async def test_natural_control_reshow_extend_hide_rebind_without_renewing_material_ttl(self):
        p,s,calls=await self.make();await self.finish(p,s)
        cache=p.visual_cache;deadline=cache.deadline;oldtoken=self.displays(s)[-1]['token']
        await self.control(p,s,'reshow_image')
        self.assertEqual(self.displays(s)[-1]['action'],'reshow');self.assertNotEqual(self.displays(s)[-1]['token'],oldtoken)
        for _ in range(3):await self.control(p,s,'extend_image')
        self.assertEqual(self.displays(s)[-1]['action'],'extend');self.assertEqual(cache.deadline,deadline)
        self.assertLessEqual(cache.visible_until,deadline);self.assertEqual(len(calls),1)
        await p.hide_visual('requested');self.assertIs(p.visual_cache,cache)
        cache.release();await p.poll_visual();before=len(self.displays(s))
        await self.control(p,s,'reshow_image');self.assertEqual(len(self.displays(s)),before)

    async def test_changed_rules_cannot_migrate_old_image_as_control(self):
        p,s,_=await self.make();await self.finish(p,s)
        count=len(self.displays(s));cache=p.visual_cache
        p.providers.model.next_plan['rules']='另一个玩法'
        await self.control(p,s,'reshow_image');self.assertEqual(len(self.displays(s)),count)
        await p.poll_visual();self.assertTrue(cache.released)

    async def test_negative_control_bypassing_played_gate_is_detected(self):
        p,s,calls=await self.make();final=[e for e in s.events if e['type']=='audio'][-1]
        original=type(p.session).ack
        def accepts_partial(session,event,**fields):
            fields['head']=final['end'] # deliberate mutation: partial playback becomes complete
            return original(session,event,**fields)
        with patch.object(type(p.session),'ack',accepts_partial):
            await self.ack(p,final,final['end']-1)
            await self.until(lambda:p.visual_task is None)
            if getattr(self,'unwrapped_negative',False):self.assertEqual(calls,[])
            else:
                with self.assertRaises(AssertionError):self.assertEqual(calls,[])
        self.assertTrue(self.displays(s))

    async def test_transfer_failure_cleans_cache_and_never_publishes_or_retries(self):
        async def fail(event):
            if event['type']=='image_chunk':raise OSError('synthetic body failure with private supplier detail')
        p,s,calls=await self.make(hook=fail);await self.finish(p,s)
        self.assertEqual(len(calls),1);self.assertEqual(self.displays(s),[]);self.assertIsNone(p.visual_cache)
        self.assertNotIn('private supplier detail',json.dumps(s.events))

    async def test_final_retention_expiry_clears_real_buffer_without_another_input(self):
        p,s,_=await self.make(config=replace(CONFIG,result_ttl=.04));await self.finish(p,s)
        cache=p.visual_cache;await asyncio.sleep(.05)
        self.assertTrue(cache.released);self.assertFalse(cache.png)
        await p.poll_visual();self.assertIsNone(p.visual_cache)
        self.assertTrue(any(e['type']=='image_display' and e['action']=='hide' for e in s.events))

    async def test_natural_hide_tool_returns_eyes_without_new_image_calls(self):
        p,s,calls=await self.make();await self.finish(p,s)
        p.providers.model.next_plan['tools']=[dict(kind='hide_image')]
        p.session.interrupt();await p.commands();await self.start(p,s);await self.finish(p,s)
        self.assertTrue(any(e['type']=='hide' and e['reason']=='requested' for e in s.events))
        self.assertEqual(len(calls),1)
        cache=p.visual_cache;self.assertIsNotNone(cache);deadline=cache.deadline
        await self.control(p,s,'reshow_image')
        self.assertEqual(self.displays(s)[-1]['action'],'reshow');self.assertEqual(cache.deadline,deadline)


class Volume(unittest.IsolatedAsyncioTestCase):
    def make(self):
        socket=Socket();socket.acknowledge=False
        p=VoicePeer(socket,object(),CompanionPolicy());socket.peer=p
        return p,socket

    async def test_endpoint_fixed_direction_schema_and_actual_scoped_once_event_no_media_reset(self):
        class EndpointModel:
            async def complete(self,instruction,data,*,schema):return json.dumps(dict(completion='complete',meaning='volume_down'))
        provider=UnifiedProviders(object(),EndpointModel())
        result=await provider.endpoint('声音小点',{})
        p,s=self.make();p.suspended=True;p.session.player='already-playing'
        output=p.session.output
        await p.decision('声音小点',result['meaning'],p.revision,p.session.clock()+15)
        await p.decision('声音大点','volume_up',p.revision,p.session.clock()+15)
        self.assertEqual([e['type'] for e in s.events],['scope','volume'])
        event=s.events[-1];self.assertEqual(event['direction'],'down');self.assertEqual(event['control_v'],1)
        self.assertEqual(len(event['token']),32);self.assertEqual(event['session'],p.session.session)
        self.assertNotIn('声音',json.dumps(event,ensure_ascii=False));self.assertNotIn('value',event)
        self.assertTrue(p.suspended);self.assertEqual(p.session.player,'already-playing');self.assertEqual(output,p.session.output)

    async def test_actual_analyze_read_request_seal_routes_volume_without_plan_or_tts(self):
        calls=[]
        class Recognizer:
            async def write(self,pcm):calls.append('pcm')
            async def finish(self):return '声音小一点'
        class LocalSpeech:
            @asynccontextmanager
            async def recognize(self,rate):yield Recognizer()
        class EndpointModel:
            async def complete(self,instruction,data,*,schema):
                calls.append('endpoint');return json.dumps(dict(completion='complete',meaning='volume_down'))
        p,s=self.make();p.providers=UnifiedProviders(LocalSpeech(),EndpointModel())
        await p.handle(json.dumps(dict(v=2,type='input',epoch=0,seq=0,pcm=base64.b64encode(b'\x01\x00'*240).decode())))
        await p.analyze(bytes(p.capture),0,p.revision)
        await p.handle(json.dumps(dict(v=2,type='seal',epoch=0,seq=1,revision=p.revision)))
        self.assertEqual(calls,['pcm','endpoint'])
        self.assertEqual([e['type'] for e in s.events],['endpoint','scope','volume'])
        self.assertEqual(s.events[-1]['direction'],'down')
        self.assertNotIn('声音',json.dumps(s.events,ensure_ascii=False))
        self.assertIsNone(p.generation)

    async def test_up_and_new_revision_are_independent_once_only_controls(self):
        p,s=self.make()
        for direction in ('volume_up','volume_down'):
            p.revision+=1;await p.decision('private-child-utterance',direction,p.revision,p.session.clock()+15)
        self.assertEqual([e['direction'] for e in s.events if e['type']=='volume'],['up','down'])
        self.assertEqual(len({e['token'] for e in s.events if e['type']=='volume'}),2)

    async def test_stale_expired_paused_closed_and_waiting_scopes_cannot_control(self):
        for key in ('revision','expired','paused','closed','waiting'):
            p,s=self.make();revision=p.revision
            if key=='revision':p.revision+=1
            elif key=='expired':p.session.expires=p.session.clock()
            elif key=='paused':p.session.pause_management()
            elif key=='closed':p.closed=True
            else:p.waiting_wake=True
            await p.decision('声音大点','volume_up',revision,p.session.clock()+15)
            self.assertEqual(s.events,[])

    async def test_revoke_at_scope_write_prevents_volume_and_failed_write_never_retries_raise(self):
        p,s=self.make()
        async def revoke(raw):p.revision+=1
        s.send=revoke
        await p.decision('声音大点','volume_up',0,p.session.clock()+15)
        self.assertEqual(s.events,[])
        p,s=self.make();calls=[]
        async def failed(raw):calls.append(raw);raise OSError('synthetic')
        s.send=failed
        with self.assertRaises(OSError):await p.decision('声音大点','volume_up',0,p.session.clock()+15)
        await p.decision('声音大点','volume_up',0,p.session.clock()+15)
        self.assertEqual(len(calls),1)
