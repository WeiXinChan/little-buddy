import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from backend.v2.feedback_store import FeedbackStore, FeedbackError, WEEK

DEVICE = 'a' * 64
OTHER = 'b' * 64


class Store(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'feedback.sqlite'
        self.now = 1_800_000_000_000
        self.store = FeedbackStore(self.path, clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.key = str(uuid4())

    def submit(self, key=None, description='Adult synthetic issue', logs=b''):
        return self.store.submit(DEVICE, key or self.key, 'IMAGE', description, logs)

    def test_submit_is_idempotent_and_conflicts_cannot_replace_material(self):
        receipt = self.submit(); self.now += 1000
        self.assertEqual(self.submit(), receipt)
        with self.assertRaisesRegex(FeedbackError, 'conflict'):
            self.submit(description='changed')
        self.assertEqual(self.store.read(DEVICE, self.key)['description'], 'Adult synthetic issue')

    def test_device_scope_and_metadata_index_do_not_leak_issue_content(self):
        self.submit()
        with self.assertRaisesRegex(FeedbackError, 'missing'):
            self.store.read(OTHER, self.key)
        index = self.store.pending()
        self.assertEqual(len(index), 1)
        self.assertNotIn('description', index[0]); self.assertNotIn('logs', index[0])
        self.store.withdraw(OTHER, self.key)
        self.assertEqual(self.store.read(DEVICE, self.key)['state'], 'SUBMITTED')

    def test_reply_and_processing_preserve_original_retention(self):
        deadline = self.submit()['delete_by']; self.now += 1000
        self.store.maintain(DEVICE, self.key)
        self.assertEqual(self.store.read(DEVICE, self.key)['state'], 'PROCESSING')
        self.store.maintain(DEVICE, self.key, reply='Please try the next reviewed build.')
        row = self.store.read(DEVICE, self.key)
        self.assertEqual(row['state'], 'REPLIED'); self.assertEqual(row['delete_by'], deadline)
        self.now = deadline
        with self.assertRaisesRegex(FeedbackError, 'missing'):
            self.store.read(DEVICE, self.key)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM issues').fetchone()[0], 0)
        self.assertEqual(self.store.pending(), [])

    def test_withdraw_erases_store_material_and_stops_operator_access_immediately(self):
        marker = 'SYNTHETIC_ERASE_MARKER_867429'
        self.submit(description=marker)
        self.store.maintain(DEVICE, self.key, reply=marker)
        deadline = self.store.read(DEVICE, self.key)['delete_by']
        receipt = self.store.withdraw(DEVICE, self.key)
        self.assertTrue(receipt['store_deleted']); self.assertEqual(receipt['delete_by'], deadline)
        self.assertNotIn('all_copies_deleted', receipt)
        row = self.store.read(DEVICE, self.key)
        self.assertEqual((row['state'], row['description'], row['logs'], row['reply']), ('DELETED', '', b'', ''))
        with self.assertRaisesRegex(FeedbackError, 'deleted'):
            self.store.maintain(DEVICE, self.key, reply='late response')
        with self.assertRaisesRegex(FeedbackError, 'deleted'):
            self.submit()
        self.assertNotIn(marker.encode(), self.path.read_bytes())

    def test_withdraw_before_upload_and_restart_does_not_resurrect(self):
        self.store.withdraw(DEVICE, self.key)
        other = FeedbackStore(self.path, clock=lambda: self.now); self.addCleanup(other.close)
        with self.assertRaisesRegex(FeedbackError, 'deleted'):
            other.submit(DEVICE, self.key, 'OTHER', 'late upload', b'')
        self.now += WEEK
        other.sweep()
        self.assertEqual(other.db.execute('SELECT count(*) FROM issues').fetchone()[0], 0)

    def test_only_whitelisted_numeric_logs_are_accepted(self):
        good = f'{self.now},PLAY,NONE,17,50,24\n'.encode()
        self.submit(logs=good)
        for logs in [b'PRIVATE_CHILD_TRANSCRIPT\n', good.replace(b'PLAY', b'PRIVATE'),
                     f'{self.now-WEEK},PLAY,NONE,17,50,24\n'.encode(), b'x'*(256*1024+1)]:
            with self.assertRaisesRegex(FeedbackError, 'invalid'):
                self.submit(str(uuid4()), logs=logs)

    def test_clock_rollback_blocks_read_reply_submit_but_allows_redaction(self):
        self.submit(); self.now -= 1000
        with self.assertRaisesRegex(FeedbackError, 'clock'):
            self.store.read(DEVICE, self.key)
        with self.assertRaisesRegex(FeedbackError, 'clock'):
            self.store.maintain(DEVICE, self.key, reply='reply')
        self.assertTrue(self.store.withdraw(DEVICE, self.key)['store_deleted'])
        self.now += 1000
        self.assertEqual(self.store.read(DEVICE, self.key)['description'], '')

    def test_protected_files_and_device_capacity(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        for _ in range(64): self.submit(str(uuid4()))
        with self.assertRaisesRegex(FeedbackError, 'capacity'):
            self.submit(str(uuid4()))
        other = self.path.parent / 'alias'; other.symlink_to(self.path)
        with self.assertRaisesRegex(FeedbackError, 'storage'):
            FeedbackStore(other)
