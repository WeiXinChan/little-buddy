import unittest
from dataclasses import replace
from backend.v2.session import Session
from tools.v2_harness.session_adapter import SessionAdapter, assert_stop


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.s = Session(lambda: self.now)
        self.s.begin_turn()
        self.stream = self.s.bind_player('p')
        self.event = self.s.task('tts')

    def send(self, **kw):
        return self.s.send(self.event, name='a', public='clue', answer='answer',
                           end=100, effect='image', approved=True, **kw)

    def ack(self, head=100, **kw):
        event = self.s.task('ack')
        return self.s.ack(event, player='p', stream=self.stream, segment='a', head=head, **kw)

    def test_prefix_and_secret(self):
        self.assertTrue(self.send())
        self.assertEqual(self.s.context()['heard'], ())
        self.assertTrue(self.ack())
        self.assertEqual(self.s.context()['heard'], ('clue', 'answer'))
        self.assertEqual(sum(c[0]=='reveal' for c in self.s.drain_commands()), 1)

    def test_partial(self):
        self.send()
        self.assertFalse(self.ack(50))
        self.assertEqual(self.s.context()['heard'], ())
        self.assertEqual(self.s.context()['partial_unknown'], ('a',))
        self.s.interrupt()
        self.assertEqual(self.s.context()['partial_unknown'], ('a',))

    def test_all_stream_resets(self):
        for reason in ('flush','stop','rebuild','wrap','route-loss'):
            with self.subTest(reason=reason):
                self.setUp()
                self.send()
                event = self.s.task('ack')
                self.s.reset_player(reason)
                self.s.bind_player('p')
                self.assertFalse(self.s.ack(event, player='p', stream=self.stream, segment='a', head=100))
                self.assertEqual(self.s.context()['heard'], ())

    def test_six_identity_dimensions(self):
        for field, value in [('connection',9),('session','old'),('turn',9),
                             ('output',9),('task','old'),('sequence',9)]:
            self.assertFalse(self.s.accept(replace(self.event, **{field:value})))
        self.assertTrue(self.s.accept(self.event))
        self.assertFalse(self.s.accept(self.event))
        self.assertFalse(self.s.accept(replace(self.event, sequence=True)))

    def test_late_safety_image_and_reconnect(self):
        old = self.event
        self.s.interrupt()
        self.assertFalse(self.s.send(old, name='x', public='x', end=10, approved=True))
        self.assertFalse(self.s.image_ready(old, topic=self.s.topic))
        self.s.reconnect()
        self.assertFalse(self.s.accept(old))

    def test_order_and_queue(self):
        self.assertTrue(self.send())
        self.assertTrue(self.s.send(replace(self.event,sequence=1),name='b',public='b',end=200,approved=True))
        self.assertFalse(self.s.send(replace(self.event,sequence=2),name='c',public='c',end=300,approved=True))
        ack = self.s.task('ack')
        self.assertFalse(self.s.ack(ack,player='p',stream=self.stream,segment='b',head=200))
        self.assertTrue(self.s.ack(ack,player='p',stream=self.stream,segment='a',head=100))
        self.assertFalse(self.s.ack(ack,player='p',stream=self.stream,segment='a',head=100))

    def test_retry_deadline(self):
        deadline = self.s.deadline
        self.assertFalse(self.s.retry(safe=False,idempotent=True))
        self.assertTrue(self.s.retry(safe=True,idempotent=True))
        self.assertEqual(self.s.deadline,deadline)
        self.assertFalse(self.s.retry(safe=True,idempotent=True))
        self.now = deadline
        self.assertFalse(self.s.accept(self.event))

    def test_shared_context_and_roles(self):
        self.send(); self.ack()
        self.s.remember_private('private')
        self.s.change_game(rules='rule',roles=('child','robot'),secrets={'answer':'secret'})
        shared = self.s.context(shared=True)
        self.assertEqual(shared['private'],())
        self.assertEqual(shared['unrevealed'],{})
        self.assertEqual(shared['heard'],('clue','answer'))
        self.assertEqual(self.s.context()['unrevealed'],{'answer':'secret'})

    def test_end_handoff_and_expiry(self):
        for mode in ('clear','handoff','ttl','lease'):
            with self.subTest(mode=mode):
                self.setUp(); self.send()
                self.s.remember_private('private')
                if mode in ('clear','handoff'):
                    getattr(self.s,mode)()
                else:
                    self.now = self.s.expires if mode=='ttl' else self.s.heartbeat_deadline
                    self.s.poll()
                self.assertEqual(self.s.context(),{})
                self.assertFalse(self.s.accept(self.event))
                self.assertEqual(len(self.s.tasks),0)
                self.assertEqual(len(self.s.pending),0)
                self.assertEqual(self.s.private,[])

    def test_heartbeat_never_extends_expiry(self):
        deadline = self.s.expires
        self.now = 10
        self.assertTrue(self.s.heartbeat())
        self.assertEqual(self.s.expires,deadline)

    def test_long_interaction_then_idle_expiry(self):
        for t in range(0, 1201, 5):
            self.now = t
            self.assertTrue(self.s.heartbeat())
            if t % 100 == 0:
                self.assertTrue(self.s.valid_interaction())
        self.assertEqual(self.s.expires, 1800)
        for t in range(1205, 1800, 5):
            self.now = t
            self.assertTrue(self.s.heartbeat())
        self.now = 1800
        self.assertFalse(self.s.poll())

    def test_combined_capacity_atomic(self):
        self.s.remember_private('p' * 40000)
        with self.assertRaises(BufferError):
            self.s.change_game(rules='x'*30000, roles=[], secrets={})
        self.assertEqual(self.s.game,{})
        with self.assertRaises(BufferError):
            self.s.remember_private('p'*30000)
        self.assertFalse(self.s.send(self.event,name='a',public='x'*30000,end=100,approved=True))
        self.assertEqual(self.s.pending.__len__(),0)

    def test_adapter_and_negative_controls(self):
        assert_stop(SessionAdapter().stop_case())
        for empty in ({}, None, {'old_ack':True,'heard':(),'reveals':0}):
            with self.assertRaises(AssertionError):
                assert_stop(empty)
        class Broken(Session):
            def ack(self,*a,**k): return True
        with self.assertRaises(AssertionError):
            assert_stop(SessionAdapter(Broken).stop_case())

if __name__ == '__main__': unittest.main()
