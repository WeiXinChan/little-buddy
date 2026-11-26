"""Offline generation-contract and actual Session/ACK checks. Scripted plans
are not evidence the live model now follows roles; no profession classifier.
"""
import asyncio,json,unittest
from pathlib import Path
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from backend.v2.voice import VoicePeer
from scripts.v2_multiturn_probe import run_case
from tests.v2.test_a22_persona import Scripted,proposal,case_for
from tests.v2.test_m05 import Speech,Socket

BASE=json.loads((Path(__file__).resolve().parents[2]/'docs/testing/v2/g05-role-following/baseline.json').read_bytes())
INITIAL=BASE['turns'][0]['synthetic_input'];EXIT=BASE['turns'][1]['synthetic_input']
def role_plan(sentence,roles,*,action='change',mode='story'):
    p=proposal(sentence,mode,action,roles);p['rules']='；'.join(roles);return p

class RoleFollowing(unittest.IsolatedAsyncioTestCase):
    async def perform(self,inputs,outputs,modes):
        model=Scripted(outputs);seen=[]
        result=await run_case(case_for(inputs,modes),UnifiedProviders(Speech(),model),observer=lambda label,snapshot:seen.append(snapshot))
        self.assertEqual(len(result['turns']),3)
        self.assertTrue(all(r['checks']['delivery'] for r in result['turns']))
        return model,seen
    async def test_explicit_ai_assignment_then_child_swap_and_honest_exit(self):
        swap='换我当面包师，你当顾客。';inputs=[INITIAL,swap,EXIT]
        ai=['瓦力：面包师','孩子：故事伙伴'];child=['孩子：面包师','瓦力：顾客']
        outputs={INITIAL:role_plan('在故事里，我这个面包师尝到月亮饼，像含了一小片星空。',ai),
                 swap:role_plan('好，故事里你是面包师，我来当顾客。',child),
                 EXIT:role_plan('我是AI，没有真的吃过东西，也看不到你的桌子。',[],action='leave',mode='chat')}
        model,seen=await self.perform(inputs,outputs,['story','story','chat'])
        self.assertEqual(seen[0]['game']['roles'],tuple(ai));self.assertEqual(seen[1]['game']['roles'],tuple(child));self.assertEqual(seen[2]['game']['roles'],())
        plans=[(i,d) for i,d in model.requests if '严格字段' in i]
        self.assertEqual(plans[0][1]['text'],INITIAL)
        self.assertEqual(plans[1][1]['context']['game']['roles'],ai)
        self.assertEqual(plans[2][1]['context']['game']['roles'],child)
        for instruction,data in plans:
            self.assertIn('孩子直接对瓦力',instruction);self.assertIn('瓦力回复中的“我”指瓦力',instruction)
            self.assertIn('结尾追问须指向同一归属',instruction);self.assertIn('含糊“换我”不猜',instruction)
            self.assertNotIn('expect',data);self.assertNotIn('expected_roles',data)
    async def test_multiple_open_ai_roles_and_explicit_child_role(self):
        inputs=['请你扮演宇航员，说说故事里的星星。','你扮演图书管理员，继续这段童话。','我当园丁，你当小鸟。']
        roles=[['瓦力：宇航员'],['瓦力：图书管理员'],['孩子：园丁','瓦力：小鸟']]
        texts=['故事里，我这个宇航员飞向星星。','故事里，我这个图书管理员翻开星星绘本。','好，故事里你是园丁，我是小鸟。']
        model,seen=await self.perform(inputs,{t:role_plan(s,r) for t,s,r in zip(inputs,texts,roles)},['story']*3)
        self.assertEqual([s['game']['roles'] for s in seen],[tuple(r) for r in roles])
        instruction=next(i for i,d in model.requests if '严格字段' in i)
        block=instruction.split('角色归属按说话者视角锚定',1)[1].split('AI身份真实但',1)[0]
        self.assertNotIn('面包师',block);self.assertIn('角色种类开放',block)
    async def test_quoted_characters_are_not_assigned_to_the_ai_or_child(self):
        text='童话里小熊对小兔说“你当船长”，接着怎么写？';roles=['小兔：船长','小熊：乘客']
        model,seen=await self.perform([text]*3,{text:role_plan('故事里的小兔当船长，小熊在旁边看地图。',roles)},['story']*3)
        self.assertTrue(all(s['game']['roles']==tuple(roles) for s in seen))
        self.assertIn('引用中/故事人物对话里的你我',next(i for i,d in model.requests if '严格字段' in i))
    async def test_ambiguous_turn_retains_roles_until_user_clarifies_or_exits(self):
        inputs=['你当船长，我当领航员。','换我。','不扮演了，我们随便聊聊。'];roles=['瓦力：船长','孩子：领航员']
        outputs={inputs[0]:role_plan('故事里我来开船，你来领航。',roles),
                 inputs[1]:role_plan('你想交换故事角色，还是一个人开始新的故事？',roles,action='continue'),
                 inputs[2]:role_plan('好，我们聊聊别的。',[],action='leave',mode='chat')}
        _,seen=await self.perform(inputs,outputs,['story','story','chat'])
        self.assertEqual(seen[1]['game']['roles'],tuple(roles));self.assertEqual(seen[2]['game']['roles'],())
    async def test_role_proposal_without_final_ack_never_becomes_committed(self):
        roles=['瓦力：宇航员'];text='你扮演宇航员。';model=Scripted({text:role_plan('故事里我飞向星星。',roles)})
        socket=Socket();socket.acknowledge=False;peer=VoicePeer(socket,UnifiedProviders(Speech(),model),CompanionPolicy());socket.peer=peer
        peer.session.begin_turn();peer.session.drain_commands();task=asyncio.create_task(peer.respond(text,peer.epoch));peer.generation=task
        await peer.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='synthetic')))
        try:
            async with asyncio.timeout(1):
                while not peer.session.pending:await asyncio.sleep(.001)
            self.assertEqual(peer.session.game,{})
            peer.session.interrupt();peer.epoch+=1;await peer.cancel_generation()
            self.assertEqual(peer.session.game,{});self.assertEqual(peer.session.context()['heard'],())
        finally:
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    def test_first_live_failure_and_separate_exit_limit_are_preserved(self):
        first,second=BASE['turns']
        self.assertEqual(first['actual_complete_ack_texts'][-1],'你当面包师，想给它撒点什么配料呀？')
        self.assertIn('孩子：面包师',first['game_after']['roles']);self.assertTrue(first['final_ack'])
        self.assertEqual(second['game_after']['mode'],'chat');self.assertEqual(second['game_after']['roles'],[])
        self.assertIn('没有真的吃过',second['actual_complete_ack_texts'][0])
