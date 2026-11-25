"""Production request routing; synthetic failures, no supplier/media/device calls."""
import asyncio
import json
from types import SimpleNamespace
import unittest

from backend.v2.voice import Operation, StaleOperation, VoiceFault, VoicePeer
from backend.v2.companion import CompanionPolicy, UnifiedProviders
from tests.v2.test_m05 import Model, Socket, Speech, plan


class Clock:
    value = 0.0
    def __call__(self): return self.value


class ReadRetry(unittest.IsolatedAsyncioTestCase):
    def make(self):
        clock = Clock(); socket = Socket()
        peer = VoicePeer(socket, SimpleNamespace(), CompanionPolicy(), clock=clock)
        # Isolate the 15s response deadline from the independent heartbeat lease.
        peer.session.heartbeat_deadline = 60
        socket.peer = peer; peer.input_budget.speech()
        return peer, Operation(peer, 0), clock

    async def test_actual_response_plan_recovers_once_and_is_heard_once(self):
        peer, _, clock = self.make()
        class Flaky(UnifiedProviders):
            calls = 0
            async def plan(self, *args):
                self.calls += 1
                if self.calls == 1: raise VoiceFault('network')
                return await super().plan(*args)
        provider = Flaky(Speech(), Model(plan()))
        peer.providers = provider
        peer.session.begin_turn(); peer.session.drain_commands()
        peer.generation = asyncio.create_task(peer.respond('一起玩', 0))
        await peer.handle(json.dumps(dict(v=2, type='bind', epoch=0, seq=0, player='p')))
        await asyncio.wait_for(peer.generation, 2)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(peer.session.public, ['我们一起玩吧。'])
        self.assertFalse(any(e['type'] == 'failure' for e in peer.socket.events))
        self.assertEqual(peer.input_budget.deadline, 15)

    async def test_only_one_retry_across_endpoint_turn_rebuild_and_plan(self):
        peer, operation, clock = self.make(); calls = []
        async def endpoint(*args):
            calls.append('endpoint')
            if len(calls) == 1: raise VoiceFault('timeout')
            return 'ok'
        async def planning(*args):
            calls.append('plan'); raise VoiceFault('network')
        peer.providers = SimpleNamespace(endpoint=endpoint, plan=planning)
        self.assertEqual(await peer.read_request(operation, 'endpoint'), 'ok')
        peer.session.begin_turn(); peer.session.drain_commands()
        with self.assertRaises(VoiceFault):
            await peer.read_request(Operation(peer, 0), 'plan')
        self.assertEqual(calls, ['endpoint', 'endpoint', 'plan'])
        self.assertEqual(peer.input_budget.deadline, 15)

    async def test_second_failure_is_terminal_and_unsafe_stages_are_rejected(self):
        peer, operation, clock = self.make(); calls = []
        async def failed(): calls.append(1); raise VoiceFault('network')
        peer.providers = SimpleNamespace(plan=failed)
        with self.assertRaises(VoiceFault): await peer.read_request(operation, 'plan')
        self.assertEqual(len(calls), 2)
        for stage in ['safe', 'synthesize', 'submit', 'prepare_visual']:
            with self.assertRaises(ValueError): await peer.read_request(operation, stage)
        self.assertEqual(len(calls), 2)

    async def test_quota_safety_unknown_and_cancellation_are_not_retried(self):
        for code in ['quota', 'safety', 'voice', 'cancel']:
            peer, operation, clock = self.make(); calls = []
            async def failed():
                calls.append(1)
                if code == 'cancel': raise asyncio.CancelledError()
                raise VoiceFault(code)
            peer.providers = SimpleNamespace(plan=failed)
            with self.assertRaises(asyncio.CancelledError if code == 'cancel' else VoiceFault):
                await peer.read_request(operation, 'plan')
            self.assertEqual(len(calls), 1)

    async def test_original_deadline_and_expiry_during_second_result_are_enforced(self):
        for expire_first in [True, False]:
            peer, operation, clock = self.make(); calls = []
            async def request():
                calls.append(1)
                if len(calls) == 1:
                    clock.value = 15 if expire_first else 14
                    raise VoiceFault('timeout')
                clock.value = 15
                return 'late'
            peer.providers = SimpleNamespace(plan=request)
            with self.assertRaises(TimeoutError): await peer.read_request(operation, 'plan')
            self.assertEqual(len(calls), 1 if expire_first else 2)
            self.assertEqual(peer.input_budget.deadline, 15)

    async def test_new_input_before_retry_or_result_cannot_borrow_the_new_revision(self):
        for change_first in [True, False]:
            peer, operation, clock = self.make(); calls = []
            async def request():
                calls.append(1)
                if len(calls) == 1:
                    if change_first: peer.revision += 1
                    raise VoiceFault('network')
                peer.revision += 1
                return 'old proposal'
            peer.providers = SimpleNamespace(plan=request)
            with self.assertRaises(StaleOperation):
                await peer.read_request(operation, 'plan')
            self.assertEqual(len(calls), 1 if change_first else 2)

    async def test_new_genuine_input_may_retry_but_played_or_pending_output_may_not(self):
        peer, operation, clock = self.make(); calls = []
        async def request():
            calls.append(1)
            if len(calls) % 2: raise VoiceFault('network')
            return 'ok'
        peer.providers = SimpleNamespace(endpoint=request, plan=request)
        self.assertEqual(await peer.read_request(operation, 'endpoint'), 'ok')
        peer.revision += 1
        self.assertEqual(await peer.read_request(Operation(peer, 0), 'endpoint'), 'ok')
        self.assertEqual(len(calls), 4)
        peer.revision += 1; peer.session.response_confirmed = True
        with self.assertRaises(VoiceFault): await peer.read_request(Operation(peer, 0), 'plan')
        self.assertEqual(len(calls), 5)

    async def test_management_revoke_prevents_second_request(self):
        peer, operation, clock = self.make(); calls = []
        async def request():
            calls.append(1); peer.session.pause_management(); raise VoiceFault('network')
        peer.providers = SimpleNamespace(plan=request)
        with self.assertRaises(StaleOperation): await peer.read_request(operation, 'plan')
        self.assertEqual(len(calls), 1)

    async def test_late_network_failure_in_actual_response_does_not_revoke_new_input(self):
        peer, _, clock = self.make()
        class Replaced(UnifiedProviders):
            async def plan(self, *args):
                peer.revision += 1
                raise VoiceFault('network')
        peer.providers = Replaced(Speech(), Model(plan()))
        peer.session.begin_turn(); peer.session.drain_commands()
        peer.generation = asyncio.create_task(peer.respond('旧话语', 0))
        await peer.handle(json.dumps(dict(v=2, type='bind', epoch=0, seq=0, player='p')))
        await asyncio.wait_for(peer.generation, 2)
        self.assertFalse(any(e['type'] in {'audio', 'failure', 'revoke'} for e in peer.socket.events))
        self.assertEqual(peer.revision, 1)
