"""Evidence of real production final-state ACK, including same-value updates."""
import asyncio
import unittest
from unittest.mock import patch
from scripts import v2_multiturn_probe as probe
from tests.v2 import test_multiturn_probe as fixtures

class CommitEvidence(unittest.IsolatedAsyncioTestCase):
    async def test_same_value_game_recommits_each_turn_not_value_change(self):
        p=fixtures.Probe().providers();peers=[];games=[];topics=[];real=probe.VoicePeer
        def peer(*args,**kwargs):value=real(*args,**kwargs);peers.append(value);return value
        def observer(label,snapshot):
            games.append(dict(snapshot['game']));topics.append(peers[0].session.topic)
        with patch.object(probe,'VoicePeer',peer):report=await probe.run_case(fixtures.CASE,p,observer=observer)
        self.assertEqual(len(games),3);self.assertEqual(games[0],games[1]);self.assertEqual(games[1],games[2])
        self.assertEqual(topics[1]-topics[0],1);self.assertEqual(topics[2]-topics[1],1)
        self.assertTrue(all(t['delivery_metadata']['game_committed'] for t in report['turns']))

    async def test_changed_proposal_without_ack_then_cancel_does_not_inherit_old_commit(self):
        p=fixtures.Probe().providers();sinks=[];real=probe.Sink;observations=[]
        def sink(*args,**kwargs):value=real(*args,**kwargs);sinks.append(value);return value
        def observer(label,snapshot):
            observations.append(snapshot)
            p.model.inner.next_plan['rules']='轮流新规则' # synthetic model beneath meter
            sinks[0].ack=False
        original=asyncio.timeout
        def timeout(value):return original(.05 if value==45 else value)
        with patch.object(probe,'Sink',sink),patch.object(probe.asyncio,'timeout',timeout):
            report=await probe.run_case(fixtures.CASE,p,observer=observer)
        self.assertEqual(len(observations),1)
        self.assertTrue(report['turns'][0]['delivery_metadata']['game_committed'])
        self.assertEqual(report['turns'][-1]['failure'],'TimeoutError')
        self.assertGreater(sinks[0].frames,0);self.assertEqual(sinks[0].acks,0);self.assertEqual(sinks[0].game_commits,0)
        self.assertTrue(report['cleanup']['confirmed'])

    async def test_private_final_state_ack_does_not_count_as_public_game_commit(self):
        p=fixtures.Probe().providers();p.model.next_plan['action']='private'
        report=await probe.run_case(fixtures.CASE,p)
        meta=report['turns'][0]['delivery_metadata']
        self.assertGreater(meta['acks_accepted'],0);self.assertFalse(meta['game_committed'])
        self.assertTrue(report['cleanup']['confirmed'])
