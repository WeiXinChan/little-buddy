"""No real lock/worker: exact descriptor/role/native closure fixtures."""
import asyncio,copy,os,unittest
from contextlib import contextmanager,ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from scripts import v2_persistent_tls as m
from tests.v2 import test_persistent_tls_preparation as fixtures

class Authority(unittest.TestCase):
    def enter(self,role='_driver',*,lockline=None,source=None,parent=None,isolated=1):
        args=NS(mode=role,lock_fd=42,supervisor_pid=100,parent_pid=100 if role=='_driver' else 200,driver_pid=200,source='a'*40,run_id='b'*32)
        fdline=lockline if lockline is not None else 'lock:\t1: FLOCK ADVISORY WRITE 100 08:01:123 0 EOF\n'
        raw=parent if parent is not None else b'python\0scripts.v2_persistent_tls\0'+(b'prepare' if role=='_driver' else b'_driver\0'+b'a'*40+b'\0'+b'b'*32)+b'\0'
        calls=[]
        @contextmanager
        def lock(fd):calls.append(fd);yield fd
        with ExitStack() as stack:
            for target,value in [('sys.flags',NS(isolated=isolated)),('os.getppid',lambda:args.parent_pid),('os.getpid',lambda:200 if role=='_driver' else 300),('os.getsid',lambda pid:200),('os.fstat',lambda fd:NS(st_dev=os.makedev(8,1),st_ino=123))]:
                obj,attr=target.split('.');stack.enter_context(patch.object(getattr(m,obj),attr,value))
            stack.enter_context(patch.object(Path,'read_text',return_value=fdline));stack.enter_context(patch.object(Path,'read_bytes',return_value=raw))
            stack.enter_context(patch.object(m,'heavy_lock',lock));stack.enter_context(patch.object(m.subprocess,'check_output',return_value=source if source is not None else 'a'*40))
            with m.internal_authority(args) as stamp:
                self.assertEqual(calls,[42]);self.assertEqual(stamp['run_digest'],m.digest('b'*32));return stamp
    def test_both_internal_roles_use_exact_inherited_fd_and_bound_source(self):
        self.assertEqual(self.enter(),self.enter('_service'))
    def test_flags_or_forged_descriptor_role_source_do_not_attest_lock(self):
        for change in (dict(isolated=0),dict(lockline=''),dict(lockline='lock: 1: FLOCK ADVISORY WRITE 999 08:01:123 0 EOF'),
                       dict(lockline='lock: 1: FLOCK ADVISORY WRITE 100 08:01:999 0 EOF'),dict(source='c'*40),
                       dict(parent=b'python\0unrelated\0prepare\0')):
            with self.subTest(change=change),self.assertRaises(m.Rejected):self.enter(**change)
    def test_direct_service_also_rejects_before_io(self):
        with patch.object(m,'serve_child',side_effect=AssertionError('not entered')):
            self.assertEqual(m.cli(['_service','--enable']),2)
    def test_success_report_requires_exact_nonforced_shutdown_and_identity_witnesses(self):
        mutations=[lambda r:r.update(service_forced_exit=True),lambda r:r.update(service_exit=False),lambda r:r.pop('shutdown'),
            lambda r:r.update(failure_kind='unknown'),lambda r:r['shutdown'].update(pending=1),
            lambda r:r['attempts'][0]['continuous']['turns'][0].pop('binding'),
            lambda r:r['attempts'][0]['continuous']['turns'][1].update(same_session=False),
            lambda r:r['attempts'][0]['continuous']['stop'].update(binding='f'*64),
            lambda r:r['attempts'][0]['continuous']['recovery'].update(played_anchor='f'*64),
            lambda r:r['attempts'][0]['continuous']['final'].update(binding='f'*64),
            lambda r:r['attempts'][1].update(binding=r['attempts'][0]['binding']),
            lambda r:r['attempts'][0]['service_cleanup'].update(transport_closed=False)]
        for i,change in enumerate(mutations):
            with self.subTest(i=i):
                r=fixtures.fixture();change(r)
                with self.assertRaises(m.Rejected):m.validate_report(r,3,'a'*40)
        m.validate_report(fixtures.fixture(),3,'a'*40)

class NativeClosure(unittest.IsolatedAsyncioTestCase):
    async def test_waiter_and_native_socket_must_both_confirm(self):
        from websockets.protocol import State
        def peer():
            lost=asyncio.get_running_loop().create_future();lost.set_result(None)
            return NS(socket=NS(connection_lost_waiter=lost,state=State.CLOSED,transport=NS(is_closing=lambda:True)))
        p=peer();self.assertTrue(m.closure_proof(p,NS(fileno=lambda:-1)))
        cancelled=asyncio.get_running_loop().create_future();cancelled.cancel()
        errored=asyncio.get_running_loop().create_future();errored.set_exception(ValueError('SYNTHETIC'))
        for waiter in (cancelled,errored,asyncio.get_running_loop().create_future()):
            p=peer();p.socket.connection_lost_waiter=waiter;self.assertFalse(m.closure_proof(p,NS(fileno=lambda:-1)))
        for fd in (3,None,True):self.assertFalse(m.closure_proof(peer(),NS(fileno=lambda:fd)))
        self.assertFalse(m.closure_proof(peer(),None))
        p=peer();p.socket.transport.is_closing=lambda:False;self.assertFalse(m.closure_proof(p,NS(fileno=lambda:-1)))
    async def test_service_state_detects_real_session_object_replacement(self):
        import weakref
        from backend.v2.session import Session
        service=m.Service();p=fixtures.Ownership().fake_peer();original=Session(lambda:0);p.session=original
        service.peer=p;service.session_ref=weakref.ref(original)
        with patch.object(m,'scalar_resources',return_value=fixtures.METRICS):
            self.assertTrue(service.state()['same_session'])
            # New actual Session-like object carrying identical semantic values is insufficient.
            p.session=Session(lambda:0);p.session.session=original.session
            self.assertFalse(service.state()['same_session'])
