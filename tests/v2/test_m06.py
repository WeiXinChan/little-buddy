"""Synthetic management command must bypass child context and endpoint model."""
import asyncio
import unittest
from copy import deepcopy
from test_r99 import Providers
from test_m05 import Socket
from backend.v2.voice import VoicePeer
from backend.v2.companion import CompanionPolicy

class Management(unittest.IsolatedAsyncioTestCase):
    async def test_parent_command_does_not_enter_child_context_or_endpoint(self):
        class Parent(Providers):
            async def finish(self):
                return '瓦力瓦力，进入管理页面。'
        provider = Parent()
        provider.release.set()
        socket = Socket()
        peer = VoicePeer(socket, provider, CompanionPolicy())
        socket.peer = peer
        peer.input_budget.speech()
        before = deepcopy(peer.session.context())
        peer.recognition = asyncio.create_task(peer.analyze(b'\1\0',0,0))
        await peer.recognition
        self.assertEqual(provider.endpoint_calls, [])
        self.assertEqual(peer.session.context(), before)
        self.assertIsNone(peer.analysis)
        self.assertEqual([e['type'] for e in socket.events], ['management'])

    async def test_discussion_about_management_remains_normal_input(self):
        class Discussion(Providers):
            async def finish(self):
                return '故事里的机器人不想进入管理页面'
        provider = Discussion(); provider.release.set()
        socket = Socket(); peer = VoicePeer(socket,provider,CompanionPolicy()); socket.peer = peer
        peer.input_budget.speech()
        peer.recognition = asyncio.create_task(peer.analyze(b'\1\0',0,0))
        await peer.recognition
        self.assertEqual(len(provider.endpoint_calls),1)
        self.assertFalse(any(e['type']=='management' for e in socket.events))
