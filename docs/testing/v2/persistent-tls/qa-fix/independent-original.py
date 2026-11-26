import sys,pathlib,unittest,asyncio,copy
from unittest.mock import patch,AsyncMock
sys.path.insert(0,str(pathlib.Path(__file__).parent/'source'))
from scripts import v2_persistent_tls as m
from tests.v2.test_persistent_tls_preparation import fixture, state
class Independent(unittest.TestCase):
    def test_internal_driver_must_not_run_without_inherited_lock_and_isolation(self):
        fake=AsyncMock(return_value={'cleanup_confirmed':True})
        with patch.object(m,'run_driver',fake),patch.object(m,'heavy_lock',side_effect=AssertionError('no real lock')):
            code=m.cli(['_driver','--enable','--output','unused','--rounds','1','--source','a'*40])
        self.assertEqual(code,2,'internal driver ran without lock/isolation attestation')
        fake.assert_not_awaited()
    def test_forced_service_exit_cannot_validate_as_confirmed(self):
        r=fixture();r['service_forced_exit']=True
        with self.assertRaises(m.Rejected):m.validate_report(r,3,'a'*40)
    def test_continuous_state_missing_session_identity_must_not_prove_same_session(self):
        r=fixture()
        # Fixture has only constructed count, no Session identity binding at any turn.
        self.assertNotIn('session',r['attempts'][0]['continuous']['final'])
        with self.assertRaises(m.Rejected):m.validate_report(r,3,'a'*40)
class Release(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_connection_lost_does_not_prove_transport_released(self):
        from types import SimpleNamespace as NS
        service=m.Service();lost=asyncio.get_running_loop().create_future();lost.cancel()
        peer=NS(closed=True,quarantined=False,session=NS(active=False,pending=[],game={},head=0,context=lambda:dict(heard=[])),socket=NS(connection_lost_waiter=lost,transport=NS(is_closing=lambda:False)),retired_tasks=set(),generation=None,recognition=None,visual_task=None,epoch=0,sequence=0)
        service.peer=peer
        with patch.object(m,'scalar_resources',return_value=dict(backend_rss_bytes=100,backend_fds=7,backend_threads=1,asyncio_tasks=1)):
            result=await service.dispatch(dict(op='release'))
        self.assertFalse(result['ok'],'cancelled waiter/open transport accepted as confirmed release')
        self.assertIs(service.peer,peer)
if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(Independent),unittest.defaultTestLoader.loadTestsFromTestCase(Release)])
    r=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not r.wasSuccessful())
