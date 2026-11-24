"""Regressions for independent TITA-96 counterexamples, against production core."""
import unittest
from copy import deepcopy
from dataclasses import replace
from backend.v2.session import Session


class Review96Tests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.s = Session(lambda: self.now)
        self.s.begin_turn()
        self.stream = self.s.bind_player('p')
        self.e, self.a = self.s.task('tts'), self.s.task('ack')
        self.s.drain_commands()

    def send(self, i=0, **kwargs):
        return self.s.send(replace(self.e, sequence=i), name=str(i), public='story',
                           end=(i+1)*100, approved=True, **kwargs)

    def ack(self, i=0, head=None):
        return self.s.ack(replace(self.a, sequence=i), player='p', stream=self.stream,
                          segment=str(i), head=(i+1)*100 if head is None else head)

    def test_r96_01_story_after_effective_audio_ack(self):
        self.assertTrue(self.send())
        self.assertTrue(self.ack())
        for i in range(1, 21):
            self.now = i*10
            self.assertTrue(self.s.heartbeat())
            self.assertTrue(self.s.poll())
            self.assertTrue(self.send(i))
            self.assertTrue(self.ack(i))
            self.s.drain_commands()
        self.assertEqual(len(self.s.context()['heard']),21)
        self.assertEqual(self.s.deadline,15)
        self.assertFalse(self.s.retry(safe=True,idempotent=True))

    def test_r96_01_no_response_deadline_and_late_ack(self):
        self.assertTrue(self.send())
        self.now = 10
        self.s.heartbeat()
        self.now = 15
        self.s.poll()
        self.assertFalse(self.ack())
        self.assertFalse(self.send(1))
        self.assertFalse(self.s.response_confirmed)
        self.assertEqual(self.s.context()['heard'],())

    def test_r96_01_partial_or_feedback_is_not_response(self):
        self.send()
        self.assertFalse(self.ack(head=50))
        self.assertFalse(self.s.response_confirmed)
        self.now = 10; self.s.heartbeat(); self.now = 15
        self.assertFalse(self.s.accept(replace(self.a,sequence=1)))
        self.setUp()
        self.assertTrue(self.send(effective=False))
        self.assertTrue(self.ack())
        self.assertFalse(self.s.response_confirmed)
        self.now = 10; self.s.heartbeat(); self.now = 15
        self.assertFalse(self.send(1))

    def test_r96_01_retry_does_not_reset_budget(self):
        self.now = 10
        self.s.heartbeat()
        self.assertTrue(self.s.retry(safe=True,idempotent=True))
        self.assertEqual(self.s.deadline,15)
        self.assertFalse(self.s.retry(safe=True,idempotent=True))
        self.s.bind_player('p2')
        event = self.s.task('retry')
        self.now = 15
        self.assertFalse(self.s.accept(event))

    def test_r96_01_progress_timeout_is_independent(self):
        self.send(); self.ack()
        self.now = 10; self.s.heartbeat()
        self.now = 15
        self.assertTrue(self.s.accept(replace(self.e,sequence=1)))
        for t in (20,30,40,50):
            self.now = t; self.s.heartbeat()
        self.now = 60
        self.s.poll()
        self.assertIsNone(self.s.player)
        self.assertFalse(self.s.accept(replace(self.e,sequence=2)))
        self.assertEqual(self.s.context()['heard'],('story',))

    def test_r96_02_reserve_pending_and_atomic_rejection(self):
        for i in range(127):
            self.assertTrue(self.send(i)); self.assertTrue(self.ack(i))
            self.s.drain_commands()
        self.assertTrue(self.send(127))
        before = deepcopy(self.s.__dict__)
        self.assertFalse(self.send(128))
        self.assertEqual(before,self.s.__dict__)
        self.assertEqual(self.s.tasks['tts'],127)
        self.assertTrue(self.ack(127))
        self.assertEqual(len(self.s.revealed),128)
        self.assertEqual(len(self.s.context()['heard']),128)
        self.assertFalse(self.send(128))

    def test_r96_03_invalid_schema_preserves_entire_state(self):
        self.s.change_game(rules='old',roles=['child'],secrets={'answer':'old-secret'})
        for candidate in ([], ['invalid'], [('a','b')], None, 'bad', {'a':[]}, {1:'x'}):
            before = deepcopy(self.s.__dict__)
            with self.assertRaises(TypeError):
                self.s.change_game(rules='new',roles=[],secrets=candidate)
            self.assertEqual(before,self.s.__dict__)
        for rules,roles in (([],[]),('new',{}),('new',[{}])):
            before = deepcopy(self.s.__dict__)
            with self.assertRaises(TypeError):
                self.s.change_game(rules=rules,roles=roles,secrets={})
            self.assertEqual(before,self.s.__dict__)

    def test_r96_03_copy_failure_and_success_detachment(self):
        class Uncopyable(str):
            def __deepcopy__(self,memo): raise ValueError('synthetic copy failure')
        before = deepcopy(self.s.__dict__)
        with self.assertRaises(ValueError):
            self.s.change_game(rules=Uncopyable('new'),roles=[],secrets={})
        self.assertEqual(before,self.s.__dict__)
        roles,secrets=['child'],{'answer':'hidden'}
        self.assertTrue(self.s.change_game(rules='new',roles=roles,secrets=secrets))
        roles.append('other'); secrets['answer']='changed'
        self.assertEqual(self.s.game['roles'],['child'])
        self.assertEqual(self.s.secrets,{'answer':'hidden'})
