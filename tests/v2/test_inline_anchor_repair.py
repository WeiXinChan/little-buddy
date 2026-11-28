"""Index-free complete repair DTO compiles actual positions, never patches bad indexes."""
import asyncio,json,unittest
from copy import deepcopy
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import UnifiedProviders,DashScopeModel,ModelError
from backend.v2 import schemas
from tests.v2.test_initial_guess_quality import candidate
from tests.v2 import test_plan_repair as prior
from tests.v2 import test_m05 as fixtures

class Inline(unittest.IsolatedAsyncioTestCase):
    async def provider(self,responses):
        calls=[];items=iter(responses)
        def handler(request):
            calls.append(json.loads(request.content));value=next(items)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}]})
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler));self.addAsyncCleanup(http.aclose)
        model=DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',key='SYNTHETIC',
            asr='fake',llm='qwen3.8-omni-flash',tts='fake',voice='fake'))
        return UnifiedProviders(fixtures.Speech(),model),calls

    async def test_full_repair_is_index_free_and_preserves_every_sentence_and_anchor(self):
        raw=candidate();raw.pop('anchors');raw['sentences']=[dict(text='它有长长的耳朵。',anchors=['clue.current']),dict(text='你猜是什么？',anchors=['prompt.current'])]
        p,calls=await self.provider([raw]);before=deepcopy(raw)
        result=await p.repair_plan_format('继续猜动物。',{},code='plan_anchors',detail='anchor_index_range')
        self.assertEqual(raw,before);self.assertEqual(result['sentences'],[v['text'] for v in raw['sentences']])
        self.assertEqual(result['anchors'],{'clue.current':0,'prompt.current':1});self.assertEqual(result['secrets'],{'answer':'兔子'})
        data=json.loads(calls[0]['messages'][1]['content'])
        self.assertEqual(data['server_constraints']['anchor_encoding'],'sentence_labels')
        contract=json.loads(calls[0]['messages'][0]['content'].split('输出契约JSON Schema：',1)[1])
        self.assertEqual(contract,schemas.PLAN_FORMAT_REPAIR);self.assertNotIn('anchors',contract['properties'])
        self.assertEqual(contract['properties']['sentences']['items']['type'],'object')

    async def test_legacy_bad_indices_or_numeric_labels_are_never_coerced(self):
        old=candidate();old['anchors']={'clue.current':1}
        numeric=candidate();numeric.pop('anchors');numeric['sentences']=[dict(text='完整线索。',anchors=[0])]
        duplicate=deepcopy(numeric);duplicate['sentences']=[dict(text='完整线索。',anchors=['clue.current','clue.current'])]
        extra=deepcopy(numeric);extra['sentences']=[dict(text='完整线索。',anchors=[],answer='兔子')]
        for raw in (old,numeric,duplicate,extra):
            p,calls=await self.provider([raw])
            with self.assertRaises(ModelError):await p.repair_plan_format('合成',{},code='plan_anchors',detail='anchor_index_range')
            self.assertEqual(len(calls),1)

    async def test_other_full_plan_and_secret_validation_still_runs(self):
        raw=candidate();raw.pop('anchors');raw['sentences']=[dict(text='完整线索。',anchors=['clue.current'])]
        for bad in ({**raw,'mode':'invalid'},{**raw,'roles':'invalid'}, {**raw,'secrets':{'k':'v'*1000}}):
            p,_=await self.provider([bad])
            with self.assertRaises(ModelError):await p.repair_plan_format('合成',{},code='plan_anchors',detail='anchor_index_type')

    async def test_first_normal_plan_contract_is_unchanged(self):
        p,calls=await self.provider([candidate()]);await p.plan('我们来猜动物吧',{})
        body=calls[0];data=json.loads(body['messages'][1]['content'])
        self.assertNotIn('anchor_encoding',data['server_constraints'])
        self.assertNotIn('本次是一次完整PLAN格式重规划',body['messages'][0]['content'])
        self.assertEqual(json.loads(body['messages'][0]['content'].split('输出契约JSON Schema：',1)[1]),schemas.PLAN)

class Compile(unittest.TestCase):
    def test_all_accepted_labels_are_positions_in_actual_output(self):
        for n in range(1,5):
            raw=candidate();raw.pop('anchors');raw['sentences']=[dict(text=f'第{i}句。',anchors=[f'clue.{i}']) for i in range(n)]
            p=UnifiedProviders.compile_format_repair(raw)
            self.assertEqual(list(p['anchors'].values()),list(range(n)))
            self.assertTrue(all(0<=i<len(p['sentences']) for i in p['anchors'].values()))

class MultiTurn(unittest.IsolatedAsyncioTestCase):
    async def test_second_turn_repair_keeps_first_and_later_guess_roles_and_ack_commit(self):
        from pathlib import Path
        from scripts.v2_multiturn_probe import run_case
        case=next(c for c in json.loads(Path('docs/testing/v2/multiturn/cases.json').read_text())['cases'] if c['id']=='guess-animal')
        case=deepcopy(case);case['turns'][0]['input']='我们来猜动物吧'
        calls=[];texts=[]
        def response(request):
            body=json.loads(request.content);calls.append(body)
            instruction=body['messages'][0]['content'];data=json.loads(body['messages'][1]['content'])
            if '提取孩子' in instruction:value={'facts':[]}
            elif '审核下一个' in instruction:value={'allow':True,'quality':True}
            else:
                text=data['text'];repair=data['server_constraints'].get('correction')=='plan_anchors'
                value=candidate()
                if '再给一个' in text:
                    value.update(action='continue',sentences=['不是大象，再给你一条线索：它喜欢吃胡萝卜。'],anchors={'clue.current':1})
                    if repair:
                        value.pop('anchors');value['sentences']=[dict(text='不是大象，再给你一条线索：它喜欢吃胡萝卜。',anchors=['clue.current'])]
                elif '换我出题' in text:
                    value.update(guess_role='guesser',secrets={},sentences=['我猜是兔子，换你出题真有趣。'],anchors={})
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}]})
        from contextlib import asynccontextmanager
        class Synth(fixtures.Speech):
            @asynccontextmanager
            async def synthesize(self,text,rate):
                texts.append(text)
                async with super().synthesize(text,rate) as chunks:yield chunks
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            providers=UnifiedProviders(Synth(),DashScopeModel(DashScope(http,workspace='synthetic',region='cn-beijing',
                key='SYNTHETIC',asr='fake',llm='qwen3.8-omni-flash',tts='fake',voice='fake')))
            snapshots=[];report=await run_case(case,providers,observer=lambda label,s:snapshots.append(s))
        self.assertEqual(len(report['turns']),3);self.assertTrue(all(t['checks']['delivery'] for t in report['turns']))
        self.assertTrue(all(t['checks']['mode'] for t in report['turns']))
        self.assertEqual(snapshots[0]['unrevealed'],{'answer':'兔子'});self.assertEqual(snapshots[1]['unrevealed'],{'answer':'兔子'})
        self.assertEqual(snapshots[2]['unrevealed'],{});self.assertEqual(snapshots[2]['game']['guess_role'],'guesser')
        self.assertEqual(report['turns'][1]['plan_format_repair'],dict(initial_detail='anchor_index_range',encoding='sentence_labels',validated=True))
        self.assertIsNone(report['turns'][0]['plan_format_repair']);self.assertIsNone(report['turns'][2]['plan_format_repair'])
        self.assertEqual(len(texts),3);self.assertEqual(report['model_requests'],10)
        self.assertTrue(report['cleanup']['confirmed']);self.assertEqual(report['cleanup']['pending_tasks'],0)

    async def test_repair_cannot_change_existing_answer(self):
        raw=candidate('大象');raw.update(action='continue');raw.pop('anchors')
        raw['sentences']=[dict(text='它有长鼻子。',anchors=['clue.current'])]
        # Use this test's actual HTTP fixture and cleanup ownership.
        p,calls=await Inline.provider(self,[raw])
        with self.assertRaises(ModelError) as caught:
            await p.repair_plan_format('再给线索。',{'game':{'mode':'guess','guess_role':'setter'},'unrevealed':{'answer':'兔子'}},code='plan_anchors',detail='anchor_index_range')
        from backend.v2.diagnostics import contract_code
        self.assertEqual(contract_code(caught.exception),'plan_guess_answer_changed')
