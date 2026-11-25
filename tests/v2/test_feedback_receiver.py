import asyncio
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import ssl
import tempfile
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from backend.v2.feedback_store import FeedbackStore, FeedbackError
from backend.v2.feedback_receiver import FeedbackReceiver, configured_feedback, checked_runtime, COPIES_POLICY
from backend.v2.feedback_admin import cli as admin
from backend.v2.server import voice_server
from backend.v2.voice import decode, WireError
from test_release import Fixture
from test_feedback_store import key_at


class Receiver(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.fixture = Fixture(self.root)
        self.store = FeedbackStore(self.root/'issues.db'); self.addCleanup(self.store.close)
        self.device = sha256(self.fixture.token.encode()).hexdigest()
        self.receiver = FeedbackReceiver(self.store, self.device)
        self.key = key_at(int(time.time()*1000))

    def message(self, operation, **fields):
        return json.dumps(dict(v=1, request=str(uuid4()), id=self.key, operation=operation, **fields))

    async def test_actual_authenticated_loopback_submit_reply_and_withdraw(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.root/'cert', self.root/'key')
        client = ssl.create_default_context(cafile=str(self.root/'cert'))
        async with voice_server('127.0.0.1', 0, context, self.fixture.token, object(), object(),
                                feedback=self.receiver) as server:
            port = server.sockets[0].getsockname()[1]
            url = f'wss://127.0.0.1:{port}/v2/feedback'
            with self.assertRaises(InvalidStatus):
                async with connect(url, ssl=client, proxy=None):pass
            async with connect(url, ssl=client, proxy=None,
                               additional_headers={'Authorization': 'Bearer '+self.fixture.token}) as socket:
                self.assertEqual(json.loads(await socket.recv())['protocol'], 'feedback-v1')
                raw = self.message('submit', category='IMAGE', description='Synthetic adult report', logs='')
                await socket.send(raw); receipt = json.loads(await socket.recv())
                self.assertTrue(receipt['ok'])
                self.store.maintain(self.device, self.key, reply='Synthetic reply')
                await socket.send(self.message('read')); result = json.loads(await socket.recv())['result']
                self.assertEqual((result['state'], result['reply']), ('REPLIED', 'Synthetic reply'))
                await socket.send(self.message('withdraw')); deleted = json.loads(await socket.recv())['result']
                self.assertFalse(deleted['all_copies_deleted']) # no operator copy-policy decision
                await socket.send(raw); self.assertEqual(json.loads(await socket.recv())['error'], 'deleted')

    async def test_malformed_or_admin_commands_never_echo_private_body(self):
        for raw in [self.message('reply', description='PRIVATE_BODY'),
                    '{"v":1,"v":1,"description":"PRIVATE_BODY"}', 'PRIVATE_BODY',
                    self.message('submit', category='OTHER', description='PRIVATE_BODY', logs='%%%')]:
            result = self.receiver.request(raw)
            self.assertFalse(result['ok']); self.assertNotIn('PRIVATE_BODY', json.dumps(result))
        self.assertEqual(self.store.pending(), [])

    async def test_withdraw_before_upload_and_copy_policy_are_explicit(self):
        self.receiver.copies_reviewed = True
        receipt = self.receiver.request(self.message('withdraw'))['result']
        self.assertTrue(receipt['all_copies_deleted'])
        result = self.receiver.request(self.message('submit', category='OTHER', description='late', logs=''))
        self.assertEqual(result['error'], 'deleted')

    async def test_optional_runtime_is_nonmutating_until_serving_and_sweeps_on_timer(self):
        path = self.root/'runtime.db'
        runtime = checked_runtime(path, COPIES_POLICY)
        self.assertFalse(path.exists())
        async with configured_feedback(runtime, self.fixture.token) as receiver:
            self.assertTrue(path.exists())
            receiver.store.submit(self.device, self.key, 'OTHER', 'synthetic', b'')
            # Exercise actual scheduler without retaining a real issue for a week.
            receiver.store.db.execute('UPDATE issues SET delete_by=?', (int(time.time()*1000)+20,))
            await asyncio.sleep(.08)
            self.assertEqual(receiver.store.pending(), [])
        self.assertIsNone(checked_runtime(None))

    async def test_admin_entry_uses_non_echoed_reply_without_renewing_deadline(self):
        receipt = self.store.submit(self.device, self.key, 'OTHER', 'synthetic', b'')
        with redirect_stdout(io.StringIO()), patch('backend.v2.feedback_admin.getpass', return_value='Synthetic operator reply'):
            self.assertEqual(admin(['--database', str(self.root/'issues.db'), 'reply',
                '--device', self.device, '--id', self.key]), 0)
        row = self.store.read(self.device, self.key)
        self.assertEqual(row['reply'], 'Synthetic operator reply')
        self.assertEqual(row['delete_by'], receipt['delete_by'])

    async def test_voice_size_guard_remains_even_when_listener_allows_feedback_payloads(self):
        with self.assertRaisesRegex(WireError, 'size'):
            decode(' ' * 16001)

    async def test_original_review_counterexample_cannot_resurrect_after_expiry(self):
        now = int(time.time()*1000)+100
        self.store.clock = lambda: now
        self.key = key_at(now)
        upload = self.message('submit', category='IMAGE', description='Synthetic withdrawn report', logs='')
        first = self.receiver.request(upload)
        self.assertTrue(first['ok'])
        self.assertTrue(self.receiver.request(self.message('withdraw'))['ok'])
        now = first['result']['delete_by']
        self.store.sweep()
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM issues').fetchone()[0], 0)
        replay = self.receiver.request(upload)
        self.assertEqual(replay['error'], 'expired')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM issues').fetchone()[0], 0)

    async def test_future_key_withdrawal_never_falsely_acknowledges_deletion(self):
        now = int(time.time()*1000)+100
        self.store.clock = lambda: now
        self.key = key_at(now+120001)
        receipt = self.receiver.request(self.message('withdraw'))
        self.assertFalse(receipt['ok'])
        self.assertEqual(receipt['error'], 'clock')
        self.assertNotIn('result', receipt)
        now += 1
        # A later valid submission is not resurrection of a successful deletion:
        # the earlier operation explicitly failed and cannot display DELETED.
        submitted = self.receiver.request(self.message('submit', category='OTHER', description='synthetic', logs=''))
        self.assertTrue(submitted['ok'])
