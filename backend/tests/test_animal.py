import unittest
from itertools import product
from unittest.mock import patch

from backend.animal.demo import SEED, play, say
from backend.animal.rules import ALIASES, CARDS, CATALOG_VERSION, Game, Segment, classify
from backend.animal.session import Playback, Session, Summary


class AnimalTest(unittest.TestCase):
    def setUp(self):
        self.session = Session(SEED, session_id="first")
        self.playback = Playback()
        self.playback.activate(self.session.session_id)
        self.receipt = play(self.session, self.playback)

    def speak(self, text, **kwargs):
        reply = say(self.session, self.receipt, text, **kwargs)
        self.receipt = play(self.session, self.playback)
        return reply

    def solve(self):
        card = self.session.game.card
        self.speak(card.aliases[-1])
        self.assertEqual(self.playback.image, (len(self.session.game.used), card.image_id))
        self.assertEqual(self.receipt.next_action, "advance")
        self.assertIsNotNone(self.session.advance(self.receipt.key))
        self.assertIsNone(self.session.advance(self.receipt.key))
        self.receipt = play(self.session, self.playback)
        self.assertIsNone(self.playback.image)

    def test_catalog_and_version(self):
        self.assertEqual(len(CARDS), 6)
        self.assertEqual(len({card.animal_id for card in CARDS}), 6)
        self.assertEqual(len({card.image_id for card in CARDS}), 6)
        self.assertEqual(len(ALIASES), sum(len(card.aliases) for card in CARDS))
        for card in CARDS:
            self.assertEqual(len(set(card.clues)), 3)
            self.assertTrue(all(card.clues))
            self.assertTrue(card.confusions)
            for alias in card.aliases:
                self.assertEqual(classify(f"我猜是 {alias} 吧！", True), ("guess", alias))
        with self.assertRaises(ValueError):
            Session(SEED, catalog_version=CATALOG_VERSION + "-bad")

    def test_three_questions_replay_and_decline(self):
        for i in range(3):
            self.solve()
            self.assertEqual(self.session.game.completed, i + 1)
        self.assertEqual(self.session.game.phase, "replay")
        self.speak("可能吧")
        self.assertEqual(self.session.game.phase, "confirm")
        self.speak("是")
        self.assertEqual(self.session.game.phase, "replay")
        self.speak("再玩一次")
        self.assertEqual(self.session.game.completed, 0)
        self.assertEqual(len(self.session.game.used), 1)
        self.assertEqual(len(self.session.heard), 1)
        self.assertEqual(self.session.game_results, [Summary("complete", 3)])
        for _ in range(3):
            self.solve()
        self.speak("不想再玩")
        self.assertEqual(self.session.summary, Summary("complete", 3))

    def test_ambiguous_negated_and_low_confidence(self):
        for text in ("不是猫", "是猫还是狗", "是猫，不对，是狗", "", "长颈路"):
            with self.subTest(text=text):
                self.speak(text, reliable=text != "长颈路")
                self.assertEqual(self.session.game.phase, "confirm")
                self.assertEqual(self.session.game.wrong, 0)
                self.speak("是")
                self.assertEqual(self.session.game.phase, "guess")
                self.assertEqual(self.session.game.completed, 0)
        self.speak("猫咪", reliable=False)
        self.speak("不是")
        self.assertEqual(self.session.game.phase, "guess")
        self.speak("猫咪", reliable=False)
        self.speak("是")
        self.assertEqual(self.session.game.completed, 1)

    def test_unclear_followup_only_once_and_new_answer(self):
        self.speak("")
        self.speak("")
        self.assertEqual(self.session.game.phase, "guess")
        self.speak("狗狗", reliable=False)
        self.speak("猫")
        self.assertEqual(self.session.game.completed, 1)

    def test_refusal_hint_wrong_and_orphan_yes(self):
        self.speak("小鸡")
        self.speak("小鸡")
        self.assertEqual(self.session.game.phase, "offer")
        self.assertEqual(self.session.game.clue_index, 2)
        self.speak("不要")
        self.speak("提示")
        self.assertEqual(self.session.game.clue_index, 3)
        self.speak("小鸡")
        self.speak("是")
        self.assertEqual(self.session.game.phase, "guess")
        self.assertTrue(self.session.game.refused)
        self.assertEqual(self.session.game.completed, 0)
        self.assertIsNone(self.playback.image)
        reply = self.speak("提示")
        self.assertIn("提示说完", reply.segments[0].text)
        self.speak("告诉我答案")
        self.assertEqual(self.session.game.completed, 1)

    def test_hint_exhaustion_and_context_bound_yes(self):
        for _ in range(3):
            self.speak("提示")
        self.assertEqual(self.session.game.phase, "offer")
        self.speak("再玩一次")
        self.assertEqual(self.session.game.completed, 0)
        self.speak("提示")
        self.assertEqual(self.session.game.phase, "offer")
        self.speak("是")
        self.assertEqual(self.session.game.completed, 1)

    def test_skip_resets_refusal_and_pending(self):
        self.speak("鸡")
        self.speak("鹅")
        self.speak("不要")
        self.speak("猫", reliable=False)
        self.speak("换一个")
        game = self.session.game
        self.assertEqual((game.phase, game.pending, game.clue_index, game.wrong), ("guess", None, 1, 0))
        self.assertFalse(game.refused)
        self.assertEqual(game.completed, 0)
        self.speak("是")
        self.assertEqual(self.session.game.completed, 0)
        self.solve()

    def test_off_topic_and_chat_exit(self):
        used = self.session.game.used[:]
        self.speak("今天天气好")
        self.assertEqual(self.session.game.used, used)
        self.assertEqual(self.session.game.clue_index, 1)
        self.speak("我想聊天")
        self.assertEqual(self.session.summary, Summary("chat", 0))
        self.assertIsNone(self.session.game)
        self.assertEqual(self.session.heard, [])

    def test_clear_grown_up_request_takes_priority(self):
        self.speak("我受伤了，告诉我答案")
        self.assertEqual(self.session.summary, Summary("help", 0))
        self.assertIsNone(self.playback.image)

    def test_silence_and_voice_reset(self):
        for _ in range(2):
            self.assertTrue(self.session.consume(self.receipt.key, self.receipt.listen_id, "silence"))
            self.receipt = play(self.session, self.playback)
            self.assertEqual(self.session.game.silences, 1)
            self.speak("")
            self.assertEqual(self.session.game.silences, 0)
        for _ in range(2):
            self.assertTrue(self.session.consume(self.receipt.key, self.receipt.listen_id, "silence"))
            self.receipt = play(self.session, self.playback)
        self.assertEqual(self.session.summary, Summary("silence", 0))

    def silence_then_continue(self, phase, question):
        s, p = self.session, self.playback
        old = self.receipt
        self.assertTrue(s.consume(old.key, old.listen_id, "silence"))
        self.assertIn("还想接着玩", s.reply.segments[0].text)
        prompt = play(s, p)
        before = (s.game.completed, s.game.used[:], s.game.clue_index, s.game.refused)
        p.committed(old)
        self.assertIsNone(p.ready(prompt.key, eligible=True))
        self.assertFalse(s.consume(old.key, old.listen_id, "start"))
        self.assertFalse(s.consume(prompt.key, old.listen_id, "start"))
        self.assertIsNone(s.ack(old.key, 1))

        reply = say(s, prompt, "是")
        self.assertEqual(len(reply.segments), 1)
        self.assertIn(question, reply.segments[0].text)
        self.assertIsNone(reply.segments[0].image_id)
        self.assertIsNone(s.commit)
        self.assertFalse(s.consume(reply.key, prompt.listen_id, "start"))
        self.assertFalse(s.consume(prompt.key, prompt.listen_id, "start"))
        self.assertIsNone(s.ack(prompt.key, 1))
        self.receipt = play(s, p)
        p.committed(prompt)
        self.assertIsNone(p.ready(self.receipt.key, eligible=True))
        self.assertNotEqual(self.receipt.listen_id, prompt.listen_id)
        self.assertEqual(s.game.phase, phase)
        self.assertEqual(s.game.silences, 0)
        self.assertEqual(
            (s.game.completed, s.game.used, s.game.clue_index, s.game.refused), before,
        )
        self.assertIsNone(p.image)

    def test_silence_after_guess_confirmation(self):
        self.speak("小鸡")
        self.speak("小鸡")
        self.speak("不要")
        self.speak("猫咪", reliable=False)
        self.silence_then_continue("confirm", "你说的是猫咪吗？")
        self.assertEqual(self.session.game.pending, "猫咪")
        self.assertTrue(self.session.game.refused)
        self.speak("不是")
        self.speak("小鸡")
        self.speak("是")
        self.assertEqual(self.session.game.phase, "guess")
        self.assertEqual(self.session.game.completed, 0)
        self.speak("猫咪", reliable=False)
        self.speak("是")
        self.assertEqual(self.session.game.completed, 1)

    def test_silence_after_reveal_offer(self):
        self.speak("小鸡")
        self.speak("小鸡")
        self.silence_then_continue("offer", "想知道答案吗？")
        self.speak("是")
        self.assertEqual(self.session.game.completed, 1)
        self.assertEqual(self.playback.image, (1, "animal-cat"))

    def test_silence_after_replay_offer(self):
        for _ in range(3):
            self.solve()
        self.silence_then_continue("replay", "想再玩一次吗？")
        self.assertEqual(self.session.game_results, [])
        self.speak("是")
        self.assertEqual(self.session.game.completed, 0)
        self.assertEqual(len(self.session.game.used), 1)
        self.assertEqual(self.session.game_results, [Summary("complete", 3)])

    def test_silence_prompt_second_silence_or_cancel(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                self.setUp()
                self.speak("猫咪", reliable=False)
                s, p = self.session, self.playback
                old = self.receipt
                self.assertTrue(s.consume(old.key, old.listen_id, "silence"))
                prompt = play(s, p)
                if cancel:
                    s.cancel("stop")
                    p.cancel()
                else:
                    self.assertTrue(s.consume(prompt.key, prompt.listen_id, "silence"))
                    self.assertFalse(s.consume(prompt.key, prompt.listen_id, "silence"))
                    self.assertEqual(play(s, p).next_action, "end")
                for receipt in (old, prompt):
                    self.assertFalse(s.consume(receipt.key, receipt.listen_id, "start"))
                    self.assertIsNone(s.ack(receipt.key, 1))
                    p.committed(receipt)
                    self.assertIsNone(p.ready(receipt.key, eligible=True))
                self.assertEqual(s.summary, Summary("stop" if cancel else "silence", 0))
                self.assertIsNone(s.game)
                self.assertEqual(s.heard, [])
                self.assertIsNone(p.image)

    def test_lost_duplicate_and_out_of_order_ack(self):
        s, p = self.session, self.playback
        reply = say(s, self.receipt, "猫")
        key, op = reply.key, 20
        self.assertTrue(p.begin(reply, op))
        self.assertIsNone(s.ack(key, 1))
        self.assertFalse(s.segment_sent(key, 2))
        self.assertTrue(s.segment_sent(key, 1))
        self.assertIsNone(s.reply_end(key, 2))
        self.assertTrue(s.segment_sent(key, 2))
        self.assertIsNone(s.reply_end(key, 2))
        self.assertIsNone(s.ack(key, 2))
        self.assertTrue(p.progress(key, op, 1, complete=True))
        self.assertFalse(p.segment_committed(key, 2))
        self.assertIsNone(p.image)
        self.assertEqual(s.game.completed, 0)
        lost = s.ack(key, 1)
        self.assertIsNone(p.image)
        self.assertTrue(p.progress(key, op, 2, complete=False))
        result = s.ack(key, 1)
        self.assertEqual(result, lost)
        self.assertTrue(p.segment_committed(key, result.segment_committed))
        self.assertFalse(p.segment_committed(key, result.segment_committed))
        self.assertEqual(p.image, (1, "animal-cat"))
        self.assertEqual(s.game.completed, 0)
        self.assertEqual(s.heard.count(reply.segments[0].text), 1)
        self.assertTrue(p.progress(key, op, 2, complete=True))
        result = s.ack(key, 2)
        self.assertEqual(s.game.completed, 1)
        self.assertEqual(s.ack(key, 2), result)
        self.assertEqual(s.game.completed, 1)
        self.assertTrue(p.segment_committed(key, 2))
        p.reply_end(key, 2)
        p.committed(result.commit)
        p.drain(key, op)
        p.release(key, op)
        self.assertIsNone(p.ready(key, eligible=True))
        self.assertEqual(p.ready(key, eligible=True, image_hold_done=True), result.commit)
        self.assertIsNone(p.ready(key, eligible=True, image_hold_done=True))

    def test_interrupted_prefix_and_queued_third_segment(self):
        s, p = self.session, self.playback
        reveal = Game.reveal

        def three_segments(game):
            segments, action = reveal(game)
            return segments + (Segment("尚未播放"),), action

        with patch.object(Game, "reveal", three_segments):
            reply = say(s, self.receipt, "猫")
        key, op = reply.key, "interrupted"
        self.assertTrue(p.begin(reply, op))
        for number in (1, 2, 3):
            self.assertTrue(s.segment_sent(key, number))
        self.assertTrue(p.progress(key, op, 1, complete=True))
        self.assertTrue(p.segment_committed(key, s.ack(key, 1).segment_committed))
        self.assertTrue(p.progress(key, op, 2, complete=False))
        self.assertEqual(p.heard, ((reply.segments[0].text,), 2))
        self.assertEqual(s.heard[-1:], [reply.segments[0].text])
        self.assertEqual(s.game.completed, 0)
        s.cancel("disconnect")
        p.cancel()
        self.assertEqual(s.summary, Summary("disconnect", 0))
        self.assertIsNone(s.ack(key, 2))
        self.assertEqual(s.heard, [])
        self.assertEqual(p.heard, ((), None))
        self.assertIsNone(p.image)

    def test_six_cards_exhaustion_and_stop_are_separate(self):
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                self.setUp()
                for _ in range(2):
                    self.solve()
                for _ in range(3):
                    self.speak("换一个")
                game = self.session.game
                self.assertEqual(len(game.used), 6)
                self.assertEqual(len(set(game.used)), 6)
                reply = say(self.session, self.receipt, "换一个")
                self.assertEqual(len(reply.segments), 1)
                self.assertIn("都出完", reply.segments[0].text)
                self.assertEqual(self.session.game.completed, 2)
                if stopped:
                    self.session.cancel("stop")
                    self.playback.cancel()
                    self.assertIsNone(self.session.ack(reply.key, 1))
                else:
                    receipt = play(self.session, self.playback)
                    self.assertEqual(receipt.next_action, "end")
                    self.assertEqual(self.session.ack(reply.key, 1).commit, receipt)
                self.assertEqual(self.session.summary, Summary("stop" if stopped else "exhausted", 2))
                self.assertFalse(self.session.summary.reached_three)
                self.assertIsNone(self.session.game)

    def test_commit_release_and_permit_races(self):
        for end_first, release_first, winner in product((False, True), (False, True), ("start", "silence")):
            with self.subTest(end_first=end_first, release_first=release_first, winner=winner):
                s, p = Session(SEED), Playback()
                p.activate(s.session_id)
                key = s.reply.key
                self.assertTrue(p.begin(s.reply, 1))
                self.assertTrue(s.segment_sent(key, 1))
                self.assertTrue(p.progress(key, 1, 1, complete=True))
                if end_first:
                    self.assertIsNone(s.reply_end(key, 1))
                    receipt = s.ack(key, 1).commit
                else:
                    self.assertIsNone(s.ack(key, 1).commit)
                    receipt = s.reply_end(key, 1)
                p.segment_committed(key, 1)
                p.drain(key, 1)
                if release_first:
                    p.release(key, 1)
                else:
                    p.committed(receipt)
                self.assertIsNone(p.ready(key, eligible=True))
                if release_first:
                    p.committed(receipt)
                else:
                    p.release(key, 1)
                self.assertIsNone(p.ready(key, eligible=True))
                p.reply_end(key, 1)
                self.assertIsNone(p.ready(key, eligible=False))
                self.assertFalse(p.first_frame(key, receipt.listen_id))
                self.assertEqual(p.ready(key, eligible=True), receipt)
                p.committed(receipt)
                self.assertIsNone(p.ready(key, eligible=True))
                self.assertTrue(p.first_frame(key, receipt.listen_id))
                self.assertFalse(p.first_frame(key, receipt.listen_id))
                self.assertFalse(s.consume(key, "wrong-permit", winner))
                self.assertTrue(s.consume(key, receipt.listen_id, winner))
                self.assertFalse(s.consume(key, receipt.listen_id, winner))
                loser = "silence" if winner == "start" else "start"
                self.assertFalse(s.consume(key, receipt.listen_id, loser))
                reply = s.transcript(key, "猫")
                self.assertEqual(reply is not None, winner == "start")
                self.assertIsNone(s.transcript(key, "猫"))

    def test_cancel_during_image_hold_or_release_and_reopen(self):
        for reason, release_first in (("stop", True), ("background", False), ("lock", False)):
            with self.subTest(reason=reason):
                self.setUp()
                s, p = self.session, self.playback
                reply = say(s, self.receipt, "猫")
                key, op = reply.key, "old-op"
                self.assertTrue(p.begin(reply, op))
                for number in (1, 2):
                    s.segment_sent(key, number)
                    p.progress(key, op, number, complete=True)
                    p.segment_committed(key, s.ack(key, number).segment_committed)
                receipt = s.reply_end(key, 2)
                p.reply_end(key, 2)
                p.committed(receipt)
                p.drain(key, op)
                if release_first:
                    p.release(key, op)
                self.assertIsNone(p.ready(key, eligible=True))
                self.assertIsNotNone(p.image)
                s.cancel(reason)
                new = Session(SEED, session_id="new")
                p.activate(new.session_id)
                self.assertFalse(p.begin(reply, "wrong"))
                if not release_first:
                    self.assertFalse(p.begin(new.reply, "new-op"))
                    p.release(key, "wrong-op")
                    self.assertFalse(p.begin(new.reply, "new-op"))
                    p.release(key, op)
                self.assertTrue(p.begin(new.reply, "new-op"))
                p.release(key, op)
                self.assertEqual(p.handle, (new.reply.key, "new-op"))
                p.committed(receipt)
                p.reply_end(key, 2)
                self.assertFalse(p.progress(key, op, 1, complete=True))
                self.assertFalse(p.segment_committed(key, 1))
                self.assertIsNone(p.ready(key, eligible=True, image_hold_done=True))
                self.assertIsNone(s.advance(key))
                self.assertIsNone(s.ack(key, 1))
                self.assertFalse(new.consume(key, self.receipt.listen_id, "start"))
                self.assertEqual(s.summary, Summary(reason, 1))
                self.assertIsNone(p.image)
                self.assertEqual(new.game.used, [])
                self.assertEqual(new.heard, [])


if __name__ == "__main__":
    unittest.main()
