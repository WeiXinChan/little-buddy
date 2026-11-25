"""A12 exact-source growth/retrieval and normal full-capacity conversation."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.v2.memory import unpack
from backend.v2.session import Session
from backend.v2.voice import VoicePeer
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from tests.v2.test_m05 import Model,Socket
from tests.v2.test_images import Speech


def fact(text,dimension='animal'):
    return dict(key='preference',value=text,start=0,end=len(text),dimension=dimension)


class Growth(unittest.TestCase):
    def grow(self,count=500):
        s=Session(lambda:0)
        for n in range(count):
            text=f'我喜欢第{n}种动物，但不喜欢它的玩偶'
            self.assertTrue(s.record_input(text,[fact(text)]))
            self.assertTrue(s._fits())
        return s

    def test_five_hundred_growing_sources_compress_and_retrieve_first_exact_negation(self):
        s=self.grow();self.assertTrue(s.source_archive)
        context=s.context(query='第0种动物')
        values=[v['source_text'] for v in context['facts'].values() if v['source']=='child']
        self.assertIn('我喜欢第0种动物，但不喜欢它的玩偶',values)
        self.assertGreater(context['memory']['omitted_sources'],0)
        self.assertEqual(s.content_limit,65536)
        self.assertLess(len(json.dumps(context,ensure_ascii=False).encode()),24000)
        all_sources=list(unpack(s.source_archive).values())+list(s.facts.items())
        self.assertEqual(len({v['source_id'] for k,v in all_sources}),500)

    def test_exact_duplicate_does_not_grow_archive_or_erase_correction(self):
        s=self.grow(90)
        first='我喜欢第0种动物，但不喜欢它的玩偶'
        for _ in range(30):self.assertTrue(s.record_input(first,[fact(first)]))
        sources=list(unpack(s.source_archive).values())+list(s.facts.items())
        self.assertEqual(len({v['source_id'] for k,v in sources}),90)
        correction='刚才说错了，我不喜欢第0种动物，我喜欢狗'
        self.assertTrue(s.record_input(correction,[fact(correction)]))
        context=s.context(query='第0种动物')
        self.assertIn(first,str(context));self.assertIn(correction,str(context))
        self.assertTrue(all(v['evidence_only'] for v in context['facts'].values()))

    def test_private_archive_not_retrieved_or_counted_by_shared_projection_and_handoff_clears(self):
        s=self.grow(70);s.private_mode=True
        for n in range(70):
            text=f'我不喜欢秘密合成动物{n}'
            self.assertTrue(s.record_input(text,[fact(text)]))
        private=s.context(query='秘密合成动物0')
        shared=s.context(shared=True,query='秘密合成动物0')
        self.assertIn('秘密',str(private));self.assertNotIn('秘密',str(shared))
        self.assertLess(shared['memory']['archived_sources'],private['memory']['archived_sources'])
        s.handoff();self.assertEqual(s.source_archive,'');self.assertEqual(s.context(),{})

    def test_capacity_keeps_accepted_evidence_and_recent_input_with_explicit_gap(self):
        s=self.grow(50);s.content_limit=len(json.dumps(dict(public=s.public,private=s.private,
            game=s.game,secrets=s.secrets,recent=s.recent,facts=s.facts,source_archive=s.source_archive,
            memory_limited=s.memory_limited,pending=[]),ensure_ascii=False).encode())+100
        before=deepcopy((s.facts,s.source_archive))
        text='现在想玩一个新的合成故事'
        self.assertFalse(s.record_input(text,[fact(text)]))
        self.assertEqual((s.facts,s.source_archive),before);self.assertTrue(s._fits())
        self.assertTrue(s.context()['memory']['capacity_limited'])
        self.assertIn(text,str(s.context()['recent']))

    def test_invalid_provenance_remains_atomic_after_archive_compression(self):
        s=self.grow(70);before=deepcopy((s.facts,s.source_archive,s.memory_revision))
        with self.assertRaises(ValueError):s.record_input('我不喜欢狗',[fact('我喜欢狗')])
        self.assertEqual((s.facts,s.source_archive,s.memory_revision),before)

    def test_compaction_keeps_heard_key_facts_but_never_proposed_facts(self):
        s=Session(lambda:0);s.begin_turn();s.drain_commands();s.bind_player('p');s.drain_commands()
        from dataclasses import replace
        sender=s.task('tts');ack=s.task('ack')
        self.assertTrue(s.send(sender,name='heard',public='猫船长答应先去森林，再找蓝色钥匙。',end=240,
            approved=True,effective=True,anchors=('plot.goal','promise.current')))
        self.assertTrue(s.ack(ack,player='p',stream=s.stream,segment='heard',head=240))
        s.public.extend(f'普通背景{i}' for i in range(45))
        self.assertTrue(s.compact(s.memory_snapshot(),[]))
        self.assertNotIn('猫船长答应',str(s.public))
        self.assertIn('猫船长答应',str(s.context()['facts']))
        self.assertTrue(s.send(replace(sender,sequence=1),name='unheard',public='没播过的错误承诺。',end=480,
            approved=True,effective=True,anchors=('promise.current',)))
        s.interrupt()
        self.assertNotIn('错误承诺',str(s.context()))
        self.assertEqual(s.context(query='猫呢')['facts']['public:played:promise.current']['value'],
                         '猫船长答应先去森林，再找蓝色钥匙。')

    def test_negative_control_discarding_cold_evidence_is_detected(self):
        s=self.grow(90);s.source_archive=''
        with self.assertRaises(AssertionError):
            self.assertIn('我喜欢第0种动物，但不喜欢它的玩偶',str(s.context(query='第0种动物')))


class ShortTopics(unittest.TestCase):
    def scenario(self,*,noise=False):
        s=Session(lambda:0);expected={}
        for source in ('我喜欢猫','我喜欢蓝色','刚才说错了，我不喜欢猫，我喜欢狗'):
            s.turn+=1
            self.assertTrue(s.record_input(source,[dict(key='preference',value=source,start=0,end=len(source))]))
            expected[source]=deepcopy(s.facts['public:preference'])
        for n in range(20):s.record_input(f'背景{n}',[])
        for n in range(40):
            s.turn+=1;source=f'我喜欢第{n}种颜色'+('呢吧吗啊' if noise else '')
            self.assertTrue(s.record_input(source,[dict(key='preference',value=source,start=0,end=len(source))]))
            expected[source]=deepcopy(s.facts['public:preference'])
        self.assertEqual(len(s.facts)+len(unpack(s.source_archive)),43)
        return s,expected

    def assert_source(self,context,expected):
        entries={v['source_id']:v for v in context['facts'].values() if v.get('source')=='child'}
        self.assertEqual(entries.get(expected['source_id']),expected)

    def test_short_single_parallel_and_particle_suffix_retrieve_exact_old_correction(self):
        s,expected=self.scenario()
        for query in ('猫','猫呢','猫狗','猫、狗','猫和狗呢'):
            with self.subTest(query=query):
                context=s.context(query=query)
                self.assert_source(context,expected['我喜欢猫'])
                self.assert_source(context,expected['刚才说错了，我不喜欢猫，我喜欢狗'])
                self.assertGreater(context['memory']['omitted_sources'],0)
        for query in ('狗','狗呢'):
            context=s.context(query=query)
            self.assert_source(context,expected['刚才说错了，我不喜欢猫，我喜欢狗'])
        self.assert_source(s.context(query='蓝色呢'),expected['我喜欢蓝色'])

    def test_particles_never_make_forty_unrelated_new_sources_pseudo_relevant(self):
        s,expected=self.scenario(noise=True)
        for query in ('猫呢','狗呢','猫狗吧'):
            context=s.context(query=query)
            self.assert_source(context,expected['刚才说错了，我不喜欢猫，我喜欢狗'])
        # Particle-only input has no topic signal and uses the unchanged empty-query tail.
        self.assertEqual(s.context(query='呢吧吗啊')['facts'],s.context(query='')['facts'])

    def test_negation_subject_time_and_question_remain_full_propositions(self):
        s=Session(lambda:0);expected=[]
        for source in ('我不喜欢猫','以前喜欢猫','妹妹喜欢猫','我喜欢猫吗'):
            s.turn+=1;s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)])
            expected.append(deepcopy(s.facts['public:preference']))
        for n in range(45):
            s.turn+=1;source=f'我喜欢第{n}种颜色'
            self.assertTrue(s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)]))
        context=s.context(query='猫呢')
        for item in expected:self.assert_source(context,item)
        self.assertTrue(all(item['evidence_only'] for item in context['facts'].values()))

    def test_short_query_filters_private_cold_sources_before_scoring_and_coverage(self):
        s,expected=self.scenario();s.private_mode=True
        source='私事是我不喜欢猫'
        s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)])
        private_id=s.facts['private:preference']['source_id']
        for n in range(40):
            s.turn+=1;source=f'私事里第{n}种颜色'
            s.record_input(source,[dict(key='preference',start=0,end=len(source),value=source)])
        private=s.context(query='猫呢');shared=s.context(shared=True,query='猫呢')
        self.assertIn(private_id,{v.get('source_id') for v in private['facts'].values()})
        self.assertNotIn('私事',str(shared));self.assertNotIn(private_id,str(shared))
        public_cold=[v for k,v in unpack(s.source_archive).values() if not v['private']]
        self.assertEqual(shared['memory']['archived_sources'],len(public_cold))
        self.assert_source(shared,expected['我喜欢猫'])
        s.private_mode=False;self.assertNotIn('私事',str(s.context(query='猫呢')))
        s.handoff();self.assertEqual(s.context(query='猫呢'),{})

    def test_short_query_is_bounded_projection_without_rewriting_stored_sources(self):
        s,expected=self.scenario();before=deepcopy((s.facts,s.source_archive,s.memory_revision))
        for query in ('猫','狗呢','猫狗','喜欢猫','刚才说错了'):
            context=s.context(query=query)
            self.assertLessEqual(context['memory']['retrieved_sources'],12)
            self.assertLessEqual(len(json.dumps(context['facts'],ensure_ascii=False).encode()),18000)
            self.assertEqual((s.facts,s.source_archive,s.memory_revision),before)
        all_values=[v for k,v in list(s.facts.items())+list(unpack(s.source_archive).values())]
        self.assertEqual({v['source_id']:v for v in all_values},{v['source_id']:v for v in expected.values()})


class FullConversation(unittest.IsolatedAsyncioTestCase):
    async def test_full_memory_is_normal_spoken_confirmation_not_voice_failure_or_fake_saved_fact(self):
        model=Model(dict(action='continue',mode='story',rules='',roles=[],secrets={},
                         sentences=['错误的已保存承诺。'],anchors={'promise.current':0}))
        model.extracted=[dict(key='preference',value='我喜欢猫')]
        socket=Socket();peer=VoicePeer(socket,UnifiedProviders(Speech(),model),CompanionPolicy());socket.peer=peer
        # Production partition + actual byte admission, with a smaller test
        # budget and existing exact evidence; no spy replacement of that path.
        for n in range(50):
            text=f'我喜欢第{n}种动物'
            peer.session.record_input(text,[fact(text)])
        baseline=len(json.dumps(dict(public=[],private=[],game={},secrets={},recent=peer.session.recent,
            facts=peer.session.facts,source_archive=peer.session.source_archive,memory_limited=False,
            pending=[]),ensure_ascii=False).encode())
        peer.session.content_limit=baseline+4096
        peer.session.begin_turn();peer.session.drain_commands()
        peer.generation=asyncio.create_task(peer.respond('我喜欢猫',0))
        await peer.handle(json.dumps(dict(v=2,type='bind',epoch=0,seq=0,player='p')))
        await asyncio.wait_for(peer.generation,2)
        self.assertFalse(any(e['type']=='failure' for e in socket.events))
        self.assertTrue(any('再告诉我' in t for t in peer.session.public))
        self.assertNotIn('错误的已保存承诺',str(peer.session.context()))
        self.assertNotEqual(peer.session.facts['public:preference']['value'],'我喜欢猫')
        self.assertTrue(peer.session.memory_limited)
