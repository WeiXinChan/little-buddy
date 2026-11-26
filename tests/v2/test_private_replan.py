"""Second PLAN action/scope regressions; synthetic providers and playback ACK."""
import asyncio
import json
import unittest
from tests.v2.test_m05 import Model, Speech, Socket, plan
from backend.v2.companion import UnifiedProviders, CompanionPolicy
from backend.v2.voice import VoicePeer


class ReplanModel(Model):
    def __init__(self, action, failure=False):
        super().__init__(plan())
        self.action, self.failure, self.plans = action, failure, []

    async def complete(self, instruction, data, *, schema=None):
        if '严格字段' not in instruction:
            return await super().complete(instruction, data, schema=schema)
        self.plans.append(data)
        if len(self.plans) == 2 and self.failure:
            raise RuntimeError('synthetic replan unavailable')
        value = plan()
        value.update(action='change' if len(self.plans) == 1 else self.action,
                     sentences=['合成回应。'], anchors={}, tools=[])
        return json.dumps(value, ensure_ascii=False)


class PrivateReplan(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, action, failure=False):
        model, socket = ReplanModel(action, failure), Socket()
        peer = VoicePeer(socket, UnifiedProviders(Speech(), model), CompanionPolicy())
        socket.peer = peer
        old = peer.session
        old.private_mode = True
        old.private.append('SYNTHETIC_PRIVATE_CANARY')
        old.begin_turn(); old.drain_commands()
        peer.generation = asyncio.create_task(peer.respond('回到公共故事。', 0))
        await peer.handle(json.dumps(dict(v=2, type='bind', epoch=0, seq=0, player='p')))
        await asyncio.wait_for(peer.generation, 2)
        self.assertEqual(len(model.plans), 2)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', str(model.plans[1]))
        return peer, old, socket

    async def test_shared_continue_publishes_without_old_private_context(self):
        p, old, _ = await self.exercise('continue')
        self.assertIs(p.session, old)
        self.assertFalse(old.private_mode)
        self.assertIn('合成回应。', old.public)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', str(old.context(shared=True)))

    async def test_private_final_action_never_publishes_reply(self):
        p, old, _ = await self.exercise('private')
        self.assertTrue(old.private_mode)
        self.assertIn('合成回应。', old.private)
        self.assertEqual(old.public, [])
        self.assertNotIn('回到公共故事', str(old.context(shared=True)))

    async def test_handoff_final_action_replaces_and_clears_session(self):
        p, old, socket = await self.exercise('handoff')
        self.assertIsNot(p.session, old)
        self.assertFalse(old.active)
        self.assertEqual(old.private, [])
        self.assertFalse(any(e['type'] == 'audio' for e in socket.events))

    async def test_end_final_action_closes_after_ack(self):
        p, old, socket = await self.exercise('end')
        self.assertFalse(old.active)
        self.assertEqual(old.private, [])
        self.assertTrue(any(e['type'] == 'audio' for e in socket.events))

    async def test_replan_failure_preserves_private_scope(self):
        p, old, socket = await self.exercise('continue', failure=True)
        self.assertTrue(old.private_mode)
        self.assertEqual(old.public, [])
        self.assertFalse(any(e['type'] == 'audio' for e in socket.events))
        self.assertTrue(any(e['type'] == 'failure' for e in socket.events))
