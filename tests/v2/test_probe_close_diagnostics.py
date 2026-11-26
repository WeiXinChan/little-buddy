"""Production resource/ACK/rechunk causal contrast; no model/TTS network."""
import asyncio
from unittest.mock import patch
import unittest
from backend.v2.companion import UnifiedProviders
from scripts import v2_multiturn_probe as probe
from tests.v2.test_m05 import Model,plan
from tests.v2 import test_multiturn_probe as fixtures

class CloseDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def run_close(self,delay,ack=True):
        calls=[];exits=[];peers=[]
        class Manager:
            async def __aenter__(self):
                async def frames():yield b'\x01\x00'*4800 # 9600-byte real supplier-frame fixture
                return frames()
            async def __aexit__(self,*args):
                calls.append('close_enter');await asyncio.sleep(delay);exits.append('close_confirmed')
        class Speech:
            def synthesize(self,text,rate):calls.append('synthesize');return Manager()
        model=Model(plan());model.next_plan.update(mode='story',rules='轮流编故事',roles=['小猫'],anchors={},sentences=['第一句。','第二句。'])
        providers=UnifiedProviders(Speech(),model);real=probe.VoicePeer
        def peer(*args,**kwargs):value=real(*args,**kwargs);peers.append(value);return value
        with patch.object(probe,'VoicePeer',peer):report=await probe.run_case(fixtures.CASE,providers,ack=ack)
        return report,providers,peers[0],calls,exits

    async def test_fast_close_same_ack_and_large_frame_commits_final_game(self):
        report,p,peer,calls,exits=await self.run_close(0)
        self.assertEqual(len(report['turns']),3);self.assertTrue(report['cleanup']['confirmed'])
        for turn in report['turns']:
            self.assertTrue(all(turn['checks'].values()));self.assertIsNone(turn['peer_failure'])
            meta=turn['delivery_metadata'];self.assertEqual(meta['max_audio_bytes'],4800)
            self.assertEqual((meta['audio_chunks'],meta['acks_accepted']),(4,4));self.assertTrue(meta['game_committed'])
            self.assertTrue(turn['quality_assessable'])
        self.assertEqual(len(exits),6)

    async def test_slow_actual_resource_exit_causes_partial_heard_no_final_game_not_ack_loss(self):
        report,p,peer,calls,exits=await self.run_close(.65)
        turn=report['turns'][0]
        self.assertIsNone(turn['peer_failure']) # quarantine invalidates operation before production last_failure assignment
        resource=next(r for r in turn['resource_diagnostics'] if r['resource']=='synthesize')
        self.assertEqual(resource['failure_kind'],'WireError')
        self.assertEqual(resource['exit_outcome'],'cancelled')
        self.assertGreaterEqual(resource['exit_ms'],490)
        self.assertEqual(turn['control_failures'],[]) # same early-return gate suppresses failure frame;self.assertFalse(turn['quality_assessable'])
        self.assertEqual(turn['delivery_metadata'],{'audio_chunks':2,'audio_bytes':9600,'max_audio_bytes':4800,'acks_accepted':2,'game_committed':False,'resource_quarantined':True})
        self.assertTrue(turn['checks']['played_context']);self.assertFalse(turn['checks']['mode'] or turn['checks']['delivery'])
        self.assertEqual(report['cleanup']['pending_tasks'],0);self.assertFalse(report['cleanup']['confirmed'])
        self.assertEqual(calls.count('synthesize'),1);self.assertEqual(exits,[])
        self.assertEqual(p.probe_cleanup_handle.pending(),())

    async def test_failure_metadata_allowlists_never_emit_arbitrary_exception_or_code(self):
        class Peer:last_failure={'stage':'PRIVATE_STAGE','kind':'SIGNED_URL_OR_SECRET','message':'PRIVATE_MESSAGE'}
        self.assertEqual(probe.peer_failure(Peer()),{'stage':'unknown','kind':'unknown'})
        sink=probe.Sink();await sink.send('{"type":"failure","code":"PRIVATE_CODE","text":"PRIVATE_BODY"}')
        self.assertEqual(sink.events,[{'type':'failure','code':'unknown'}])
