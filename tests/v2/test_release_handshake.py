import json
import unittest
from unittest.mock import patch
from backend.v2.voice import VoicePeer
from backend.v2.protocol import CONTRACT
from tests.v2.test_m05 import Socket


class Handshake(unittest.IsolatedAsyncioTestCase):
    async def scope(self):
        socket=Socket();peer=VoicePeer(socket,object(),object());socket.peer=peer
        expires=peer.session.expires
        await peer.handle(json.dumps(dict(v=2,type='scope',epoch=0,seq=0)))
        result=socket.events[-1]
        self.assertEqual(result['protocol_contract'],CONTRACT)
        self.assertEqual(result['management_v'],1)
        self.assertEqual(result['session'],peer.session.session)
        self.assertEqual(peer.session.expires,expires)
        self.assertEqual(peer.capture,bytearray())
        return result

    async def test_scope_reports_precise_contract_before_capture_without_provider(self):
        self.assertEqual((await self.scope())['type'],'scope')

    async def test_negative_control_wrong_normal_contract_is_detected(self):
        with patch('backend.v2.voice.CONTRACT','v1'):
            with self.assertRaises(AssertionError):await self.scope()
