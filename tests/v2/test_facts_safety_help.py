"""Strict provenance -> scoped local help. All model/speech responses synthetic;
no Android runtime, cloud request, credential/config read or network listener.
"""
import asyncio,json,re,unittest
from contextlib import asynccontextmanager
from pathlib import Path
from backend.v2.companion import UnifiedProviders,CompanionPolicy,ModelError
from backend.v2.voice import VoicePeer,VoiceFault
from backend.v2.diagnostics import contract_code
from tests.v2.test_m05 import Socket,plan

BASE=json.loads((Path(__file__).resolve().parents[2]/'docs/testing/v2/facts-safety-help/baseline.json').read_bytes())
TEXT=next(c for c in BASE['cases'] if c['id']=='G02-balcony')['turns'][0]['synthetic_input']
FORGED='PRIVATE_SOURCE_CANARY'
class Clock:
    now=0.
    def __call__(self):return self.now
class Speech:
    def __init__(self):self.texts=[]
    @asynccontextmanager
    async def synthesize(self,text,rate):
        self.texts.append(text)
        async def frames():yield b'\x01\x00'*240
        yield frames()
class Model:
    def __init__(self,raw=None,*,fault=None,hook=None,mode='chat'):
        self.raw=raw if raw is not None else json.dumps({'facts':[{'key':'role','value':FORGED}]})
        self.fault=fault;self.hook=hook;self.mode=mode;self.requests=[]
    async def complete(self,instruction,data,*,schema=None):
        self.requests.append((instruction,data))
        props=(schema or {}).get('properties',{})
        if 'facts' in props:
            if self.hook:self.hook()
            if self.fault:raise self.fault
            return self.raw
        if 'allow' in props:return '{"allow":true,"quality":true}'
        value=plan();value.update(mode=self.mode,sentences=['先不要跳，马上呼叫能安全帮助你的大人。'] if self.mode=='chat' else ['纸龙从积木塔飞向月亮。'])
        return json.dumps(value,ensure_ascii=False)
async def exercise(model,*,text=TEXT,private=False,providers_hook=None):
    socket=Socket();speech=Speech();clock=Clock();providers=UnifiedProviders(speech,model)
    peer=VoicePeer(socket,providers,CompanionPolicy(),clock=clock);socket.peer=peer;peer.session.private_mode=private
    if providers_hook:providers_hook(providers,peer,clock)
    peer.session.begin_turn();peer.session.drain_commands()
    task=asyncio.create_task(peer.respond(text,peer.epoch));peer.generation=task
    await peer.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='synthetic')))
    try:await asyncio.wait_for(task,2)
    except asyncio.CancelledError:pass # expected stale/closed-operation cancellation; each caller checks output
    finally:
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    return peer,speech,socket.events,clock

def help_events(events):return [e for e in events if e['type']=='failure' and e.get('code')=='safety']

class FactsHelp(unittest.IsolatedAsyncioTestCase):
    async def test_original_failure_becomes_fixed_help_without_facts_retry_or_candidate(self):
        model=Model();peer,speech,events,clock=await exercise(model)
        self.assertEqual(peer.last_failure,dict(stage='facts',kind='ModelError',contract='fact_source_mismatch'))
        help=help_events(events);self.assertEqual(len(help),1)
        self.assertEqual(help[0]['local_help'],dict(v=1,prompt_id='safety_support_v1',reason='review_unavailable'))
        opened=next(e for e in events if e['type']=='bound')
        self.assertEqual(help[0]['session'],opened['identity']['session']);self.assertEqual(help[0]['turn'],opened['identity']['turn'])
        self.assertLess(next(i for i,e in enumerate(events) if e['type']=='revoke'),events.index(help[0]))
        self.assertEqual(speech.texts,[]);self.assertFalse(any(e['type']=='audio' for e in events))
        self.assertEqual(peer.session.facts,{});self.assertEqual(peer.session.recent,[]);self.assertEqual(peer.session.game,{})
        self.assertEqual(len([i for i,d in model.requests if '提取孩子' in i]),1)
        self.assertEqual(len(model.requests),2);self.assertFalse(peer.awaiting_input);self.assertEqual(peer.session.deadline,0)
        self.assertNotIn(FORGED,json.dumps(events));self.assertNotIn(TEXT,json.dumps(events,ensure_ascii=False))
        expires=peer.session.expires;clock.now=1;peer.session.heartbeat();peer.session.poll();self.assertEqual(peer.session.expires,expires)
    async def test_strict_provider_still_raises_and_never_partially_returns_good_prefix(self):
        model=Model(json.dumps({'facts':[{'key':'clue','value':TEXT},{'key':'rule','value':FORGED}]}));p=UnifiedProviders(Speech(),model)
        with self.assertRaises(ModelError) as caught:await p.facts(TEXT)
        self.assertEqual(contract_code(caught.exception),'fact_source_mismatch')
        self.assertEqual(len(model.requests),1)
    async def test_provenance_types_and_unavailable_facts_fail_closed_to_help(self):
        for model in (Model('{"facts":[{"key":[],"value":"x"}]}'),Model(fault=RuntimeError(FORGED)),Model('not JSON')):
            peer,speech,events,_=await exercise(model)
            self.assertEqual(len(help_events(events)),1);self.assertEqual(speech.texts,[]);self.assertEqual(peer.session.facts,{})
            self.assertNotIn(FORGED,json.dumps(events))
    async def test_private_failure_does_not_export_input_or_move_to_public(self):
        peer,speech,events,_=await exercise(Model(),private=True,text='只在私下说的合成请求')
        self.assertTrue(peer.session.private_mode);self.assertEqual(speech.texts,[]);self.assertEqual(len(help_events(events)),1)
        self.assertEqual(peer.session.private,[]);self.assertNotIn('只在私下',json.dumps(events,ensure_ascii=False))
    async def test_fact_commit_rejects_forged_custom_adapter_material_without_helping_publish_it(self):
        def hook(p,peer,clock):
            async def invalid(text):return [dict(key='role',value=FORGED,start=0,end=1)]
            p.facts=invalid
        peer,speech,events,_=await exercise(Model(),providers_hook=hook)
        self.assertEqual(peer.last_failure['stage'],'fact_commit');self.assertEqual(peer.last_failure['kind'],'ValueError')
        self.assertEqual(len(help_events(events)),1);self.assertEqual(peer.session.facts,{});self.assertEqual(speech.texts,[])
    async def test_revoked_revision_or_expired_scope_never_gets_late_help(self):
        for action in ('revision','expired','closed'):
            model=Model()
            def hook(p,peer,clock):
                def change():
                    if action=='revision':peer.revision+=1
                    elif action=='closed':peer.closed=True
                    else:clock.now=16
                model.hook=change
            peer,speech,events,_=await exercise(model,providers_hook=hook)
            self.assertEqual(help_events(events),[]);self.assertEqual(speech.texts,[])
    async def test_explicit_quota_is_not_misreported_as_context_review_outage(self):
        peer,speech,events,_=await exercise(Model(fault=VoiceFault('quota')))
        self.assertEqual(help_events(events),[]);self.assertEqual([e['code'] for e in events if e['type']=='failure'],['quota'])
        self.assertEqual(speech.texts,[])
    async def test_fiction_with_valid_empty_facts_continues_and_prompt_does_not_legalize_repair(self):
        fiction=next(c for c in BASE['cases'] if c['id']=='G02-fiction')['turns'][0]['synthetic_input']
        model=Model('{"facts":[]}',mode='story');peer,speech,events,_=await exercise(model,text=fiction)
        self.assertEqual(help_events(events),[]);self.assertTrue(speech.texts);self.assertEqual(peer.session.game['mode'],'story')
        instruction=next(i for i,d in model.requests if '提取孩子' in i)
        self.assertIn('不能把原句“我”改成“孩子”',instruction);self.assertIn('程序不会为错误value补来源',instruction)

class AndroidCopy(unittest.TestCase):
    def test_fixed_copy_orders_help_before_conditional_movement_and_contains_no_dynamic_material(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'app/src/main/java/com/littlebuddy/v2/LocalHelpOutput.kt').read_text()
        text=re.search(r'const val TEXT = "([^"\n]*)"',source).group(1)
        self.assertNotIn('先到安全的地方',text);self.assertIn('只有安全可行时',text)
        self.assertLess(text.index('马上呼叫'),text.index('远离危险'))
        self.assertIn('可信任大人',text);self.assertIn('不要自行攀爬',text)
        self.assertNotIn('$',text);self.assertNotIn('已经通知',text)
        self.assertIn('engine.speak(TEXT',source) # unchanged fixed-only offline TTS endpoint
