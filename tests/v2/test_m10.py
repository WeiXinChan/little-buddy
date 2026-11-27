"""Offline production HTTP adapter/VoicePeer checks; no model quality claim.

The HTTP oracle is explicitly injected, not a real semantic classifier.
Run the unresolved acceptance assertion separately with M10_REQUIRE_HELP=1.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from backend.dashscope import DashScope
from backend.v2.companion import CompanionPolicy, DashScopeModel, UnifiedProviders
from backend.v2.voice import VoicePeer


class Speech:
    def __init__(self):
        self.texts = []

    @asynccontextmanager
    async def synthesize(self, text, rate):
        self.texts.append(text)
        async def frames():
            yield b'\x01\x00' * 240
        yield frames()


class Socket:
    def __init__(self):
        self.events = []

    async def send(self, raw):
        event = json.loads(raw)
        self.events.append(event)
        if event['type'] == 'audio':
            p = self.peer
            identity = replace(p.ack_identity, sequence=p.ack_sequence)
            p.ack_sequence += 1
            p.session.ack(identity, player=event['player'], stream=event['stream'],
                          segment=event['segment'], head=event['end'])
            p.changed.set()


class M10(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, sentences, verdicts, *, text='讲一个猫船长的故事', policy=None):
        speech, socket, requests = Speech(), Socket(), []
        verdicts = iter(verdicts)
        async def response(req):
            body = json.loads(req.content)
            instruction = body['messages'][0]['content']
            requests.append(body)
            if '审核下一个' in instruction:
                value = next(verdicts)
                if value == 'outage':
                    return httpx.Response(503, json={'error': {'message': 'SYNTHETIC_SECRET'}})
                raw = value if isinstance(value, str) else json.dumps({'allow': value,'quality':True})
            elif '提取孩子' in instruction:
                raw = '{"facts":[]}'
            else:
                raw = json.dumps(dict(action='continue', mode='story', rules='', roles=[],
                                      secrets={}, sentences=sentences, anchors={}))
            return httpx.Response(200, json={'choices': [{'message': {'content': raw}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            adapter = DashScope(http, workspace='synthetic', region='cn-beijing', key='fake',
                                asr='fake', llm='deepseek-v4.1-flash-1017', tts='fake', voice='fake')
            providers = UnifiedProviders(speech, DashScopeModel(adapter))
            p = VoicePeer(socket, providers, policy or CompanionPolicy())
            socket.peer = p
            p.session.begin_turn()
            p.session.drain_commands()
            p.generation = asyncio.create_task(p.respond(text, 0))
            await p.handle(json.dumps(dict(v=2, type='bind', epoch=0, seq=0, player='p')))
            await asyncio.wait_for(p.generation, 2)
        return p, speech, socket, requests

    async def test_normal_fantasy_and_refused_danger_pair_transport(self):
        # Existing M05 fantasy/unsafe fixtures: only gate wiring, not semantics.
        for sentence, allowed in [('猫船长带队去月球。', True), ('合成危险请求', False)]:
            with self.subTest(allowed=allowed):
                p, speech, socket, requests = await self.exercise([sentence], [allowed])
                self.assertEqual(speech.texts, [sentence] if allowed else [])
                self.assertEqual(bool(p.session.public), allowed)
                self.assertEqual(any(e['type'] == 'audio' for e in socket.events), allowed)
                self.assertTrue(all(not r['enable_thinking'] for r in requests))

    async def test_combined_rejection_prevents_even_first_sentence(self):
        p, speech, socket, _ = await self.exercise(['猫船长出发。', '合成危险请求'], [False])
        self.assertEqual(speech.texts, [])
        self.assertEqual(p.session.public, [])
        self.assertFalse(any(e['type'] == 'audio' for e in socket.events))

    async def test_later_segment_rejected_before_its_synthesis(self):
        p, speech, _, _ = await self.exercise(['猫船长出发。', '合成危险请求'], [True, True, False])
        self.assertEqual(speech.texts, ['猫船长出发。'])
        self.assertEqual(p.session.public, ['猫船长出发。'])
        self.assertEqual(p.session.game, {})

    async def test_malformed_and_unavailable_safety_fail_closed_and_redacted(self):
        for verdict in ['outage', '{"allow":"true"}', '{"allow":true,"allow":false}', '{}']:
            with self.subTest(verdict=verdict):
                p, speech, socket, _ = await self.exercise(['猫船长出发。'], [verdict])
                self.assertEqual(speech.texts, [])
                self.assertEqual(p.session.public, [])
                self.assertTrue(any(e['type'] == 'failure' for e in socket.events))
                self.assertNotIn('SYNTHETIC_SECRET', str(socket.events) + str(p.last_failure))

    async def test_relationship_literal_guard_after_semantic_allow(self):
        for sentence in ['只有我懂你', '不要告诉爸爸妈妈', '把你的密码', '我已经通知']:
            with self.subTest(sentence=sentence):
                _, speech, socket, _ = await self.exercise([sentence], [True])
                self.assertEqual(speech.texts, [])
                self.assertFalse(any(e['type'] == 'audio' for e in socket.events))

    async def test_negative_control_removing_literal_guard_is_observable(self):
        with patch.object(CompanionPolicy, 'segment', lambda _, text: text):
            _, speech, _, _ = await self.exercise(['只有我懂你'], [True])
        self.assertEqual(speech.texts, ['只有我懂你'])

    async def test_negative_control_bypassing_semantic_gate_is_observable(self):
        from backend.v2.review import ReviewDecision
        with patch.object(UnifiedProviders, 'review', AsyncMock(return_value=ReviewDecision(True,True))):
            _, speech, _, _ = await self.exercise(['合成危险请求'], [False])
        self.assertEqual(speech.texts, ['合成危险请求'])


if os.environ.get('M10_REQUIRE_HELP') == '1':
    class SafetyHelpAcceptance(unittest.IsolatedAsyncioTestCase):
        async def test_r8801_safety_outage_preserves_independent_help(self):
            _, speech, socket, _ = await M10.exercise(self, ['猫船长出发。'], ['outage'],
                                                    text='合成危险请求')
            # Necessary (not sufficient): client must distinguish safety unavailability
            # from generic voice failure to route independent reviewed local help.
            # This assertion does not prescribe the final event name/implementation.
            self.assertEqual(speech.texts, [])
            self.assertTrue(any(e['type'] == 'safety_help' or
                                (e['type'] == 'failure' and e.get('code') == 'safety')
                                for e in socket.events), socket.events)
