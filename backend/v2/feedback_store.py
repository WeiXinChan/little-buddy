"""Device-scoped self-hosted issue storage. No chat, audio, backup or export jobs.

All access sweeps original deadlines first. The receiving service must also run
the expiry scheduler; a disk file alone is not a running retention service.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
from uuid import UUID, RFC_4122

DAY = 86_400_000
WEEK = 7 * DAY
ADMISSION_WINDOW = 3_600_000
FUTURE_SKEW = 120_000
CATEGORIES = {'RECOGNITION', 'CONVERSATION', 'INTERRUPT', 'SOUND_NETWORK', 'IMAGE', 'OTHER'}
STAGES = {'CONNECT', 'RECOGNIZE', 'GENERATE', 'PLAY', 'CANCEL'}
ERRORS = {'NONE', 'TIMEOUT', 'OFFLINE', 'REJECTED', 'INTERNAL'}


class FeedbackError(ValueError):
    def __init__(self, code):
        if code not in {'invalid', 'storage', 'clock', 'expired', 'deleted', 'conflict', 'capacity', 'missing'}:
            raise ValueError('feedback error code')
        self.code = code
        super().__init__(code)


def identity(device, key):
    if not isinstance(device, str) or not re.fullmatch('[a-f0-9]{64}', device):
        raise FeedbackError('invalid')
    try:
        if (not isinstance(key, str) or str(UUID(key)) != key or UUID(key).variant != RFC_4122 or
            UUID(key).version not in {4, 7}):
            raise ValueError()
    except ValueError:
        raise FeedbackError('invalid') from None


def issued_at(key):
    """A UUIDv7's timestamp cannot be changed while preserving the same key.

    UUIDv4 remains readable/deletable for compatibility, but cannot create a new
    record: forgetting its tombstone would otherwise permit indefinite replay.
    """
    value = UUID(key)
    if value.version != 7:
        raise FeedbackError('invalid')
    return value.int >> 80


def admission(key, now):
    created = issued_at(key)
    if created <= 0 or created > now+FUTURE_SKEW:
        raise FeedbackError('clock')
    if now >= created+ADMISSION_WINDOW:
        raise FeedbackError('expired')
    return created+ADMISSION_WINDOW


def text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 2000 or
        any(0xD800 <= ord(c) <= 0xDFFF or ord(c) < 32 and c not in '\n\t' for c in value)):
        raise FeedbackError('invalid')


def logs_checked(logs, now):
    if type(logs) is not bytes or len(logs) > 256 * 1024:
        raise FeedbackError('invalid')
    if not logs:
        return
    try:
        value = logs.decode('ascii')
        lines = value.splitlines()
        if not value.endswith('\n') or len(lines) > 1000:
            raise ValueError()
        previous = 0
        for line in lines:
            fields = line.split(',')
            if len(fields) != 6 or fields[1] not in STAGES or fields[2] not in ERRORS:
                raise ValueError()
            numbers = [fields[n] for n in (0, 3, 4, 5)]
            if any(not re.fullmatch('0|[1-9][0-9]{0,15}', n) for n in numbers):
                raise ValueError()
            at, version, elapsed, usage = map(int, numbers)
            if (not now-WEEK < at <= now+120000 or at < previous or
                not 1 <= version <= 1_000_000 or not 0 <= elapsed <= DAY or not 0 <= usage <= 1_000_000_000):
                raise ValueError()
            previous = at
    except (UnicodeError, ValueError):
        raise FeedbackError('invalid') from None


class FeedbackStore:
    def __init__(self, path, *, clock=lambda: int(time.time()*1000)):
        self.clock, self.lock = clock, threading.RLock()
        self.db = None
        try:
            path = Path(path)
            parent = path.parent.lstat()
            if (stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode) or
                os.geteuid() != 0 and parent.st_uid != os.geteuid() or parent.st_mode & 0o077):
                raise ValueError()
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
            before = path.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                os.geteuid() != 0 and before.st_uid != os.geteuid() or before.st_mode & 0o077):
                raise ValueError()
            self.db = sqlite3.connect(path, isolation_level=None, timeout=1)
            after = path.lstat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError()
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA secure_delete=ON')
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA temp_store=MEMORY')
            if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError()
            self.db.execute('CREATE TABLE IF NOT EXISTS clock_state (id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS issues (device TEXT NOT NULL, id TEXT NOT NULL, '
                'submitted INTEGER, delete_by INTEGER NOT NULL, state TEXT NOT NULL, category TEXT NOT NULL, '
                'description TEXT NOT NULL, logs BLOB NOT NULL, reply TEXT NOT NULL, digest TEXT NOT NULL, '
                'PRIMARY KEY(device,id))')
            self.sweep()
        except Exception:
            if self.db is not None:
                self.db.close()
            raise FeedbackError('storage') from None

    @contextmanager
    def transaction(self, *, deleting=False):
        with self.lock:
            try:
                self.db.execute('BEGIN IMMEDIATE')
                value = self.clock()
                previous = self.db.execute('SELECT value FROM clock_state WHERE id=1').fetchone()
                last = previous[0] if previous else 0
                if type(value) is not int or not 0 < value < 2**63-WEEK:
                    raise FeedbackError('clock')
                if value < last and not deleting:
                    raise FeedbackError('clock')
                now = max(value, last) # withdrawal may redact even while the clock is suspect
                self.db.execute('INSERT OR REPLACE INTO clock_state VALUES (1,?)', (now,))
                self.db.execute('DELETE FROM issues WHERE delete_by<=?', (now,))
                # Autonomous expiry must not roll back when the requested issue
                # is missing/conflicting or the subsequent operation is rejected.
                self.db.execute('COMMIT')
                self.db.execute('BEGIN IMMEDIATE')
                yield now
                self.db.execute('COMMIT')
            except Exception as failure:
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK')
                if isinstance(failure, FeedbackError):
                    raise
                raise FeedbackError('storage') from None

    def sweep(self):
        with self.transaction():
            pass

    def submit(self, device, key, category, description, logs):
        identity(device, key)
        text(description)
        if not isinstance(category, str) or category not in CATEGORIES:
            raise FeedbackError('invalid')
        with self.transaction() as now:
            logs_checked(logs, now)
            digest = sha256(json.dumps([category, description], ensure_ascii=False).encode()+b'\0'+logs).hexdigest()
            old = self.db.execute('SELECT * FROM issues WHERE device=? AND id=?', (device, key)).fetchone()
            if old:
                if old['state'] == 'DELETED':
                    raise FeedbackError('deleted')
                if old['digest'] != digest:
                    raise FeedbackError('conflict')
                return dict(id=key, submitted_at=old['submitted'], delete_by=old['delete_by'])
            admission(key, now)
            if (self.db.execute('SELECT count(*) FROM issues WHERE device=?', (device,)).fetchone()[0] >= 64 or
                self.db.execute('SELECT count(*) FROM issues').fetchone()[0] >= 1024):
                raise FeedbackError('capacity')
            self.db.execute('INSERT INTO issues VALUES (?,?,?,?,?,?,?,?,?,?)',
                (device, key, now, now+WEEK, 'SUBMITTED', category, description, logs, '', digest))
            return dict(id=key, submitted_at=now, delete_by=now+WEEK)

    def read(self, device, key):
        identity(device, key)
        with self.transaction():
            row = self.db.execute('SELECT * FROM issues WHERE device=? AND id=?', (device, key)).fetchone()
            if row is None:
                raise FeedbackError('missing')
            return {name: row[name] for name in ('id', 'submitted', 'delete_by', 'state', 'category', 'description', 'logs', 'reply')}

    def withdraw(self, device, key):
        identity(device, key)
        with self.transaction(deleting=True) as now:
            row = self.db.execute('SELECT submitted,delete_by FROM issues WHERE device=? AND id=?', (device, key)).fetchone()
            # Unknown keys are durably tombstoned before a delayed upload can arrive.
            if row:
                submitted, deadline = row['submitted'], row['delete_by']
            else:
                # A permanently inadmissible key needs no retained identifier.
                try:deadline = admission(key, now)
                except FeedbackError as failure:
                    if failure.code not in {'expired', 'invalid'}:raise
                    return dict(id=key, received_at=now, store_deleted=True, delete_by=now)
                submitted = None
            self.db.execute('INSERT OR REPLACE INTO issues VALUES (?,?,?,?,?,?,?,?,?,?)',
                (device, key, submitted, deadline, 'DELETED', '', '', b'', '', ''))
            return dict(id=key, received_at=now, store_deleted=True, delete_by=deadline)

    def maintain(self, device, key, *, reply=None):
        """Trusted local operator port; never exposed as a device command."""
        identity(device, key)
        if reply is not None:
            text(reply)
        with self.transaction():
            row = self.db.execute('SELECT state,reply FROM issues WHERE device=? AND id=?', (device, key)).fetchone()
            if row is None:
                raise FeedbackError('missing')
            if row['state'] == 'DELETED':
                raise FeedbackError('deleted')
            self.db.execute('UPDATE issues SET state=?, reply=? WHERE device=? AND id=?',
                ('REPLIED' if reply is not None else 'PROCESSING', reply if reply is not None else row['reply'], device, key))

    def pending(self):
        """Local operator index contains only bounded routing/status metadata."""
        with self.transaction():
            return [dict(row) for row in self.db.execute(
                "SELECT device,id,submitted,delete_by,state,category FROM issues WHERE state!='DELETED' ORDER BY submitted LIMIT 1024")]

    def next_deadline(self):
        with self.lock:
            row = self.db.execute('SELECT min(delete_by) FROM issues').fetchone()
            return row[0]

    def close(self):
        with self.lock:
            self.db.close()
