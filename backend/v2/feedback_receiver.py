"""Authenticated device issue protocol; operator actions are never wire commands."""
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

from backend.v2.feedback_store import FeedbackStore, FeedbackError, identity
from backend.v2.files import ConfigurationError
from backend.v2.image_review import unique_object

MAX_MESSAGE = 400_000
COPIES_POLICY = 'single-store-no-exports-v1'


@dataclass(frozen=True, repr=False)
class FeedbackRuntime:
    database: Path
    copies_reviewed: bool


def checked_runtime(path, copies_policy=None):
    if path is None:
        if copies_policy is not None:
            raise ConfigurationError('feedback_configuration_invalid')
        return None
    try:
        value = Path(path)
        parent = value.parent.lstat()
        if (not value.is_absolute() or not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077 or
            os.geteuid() != 0 and parent.st_uid != os.geteuid() or copies_policy not in {None, COPIES_POLICY}):
            raise ValueError()
        if value.exists() or value.is_symlink():
            info = value.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077 or
                os.geteuid() != 0 and info.st_uid != os.geteuid()):
                raise ValueError()
        return FeedbackRuntime(value, copies_policy == COPIES_POLICY)
    except (OSError, ValueError, TypeError):
        raise ConfigurationError('feedback_configuration_invalid') from None


class FeedbackReceiver:
    def __init__(self, store, device, *, copies_reviewed=False):
        self.store, self.device = store, device
        self.copies_reviewed = copies_reviewed
        self.active = False
        self.disabled = False
        self.socket = None

    def request(self, raw):
        request_id = None
        try:
            if self.disabled:raise FeedbackError('storage')
            if not isinstance(raw, str) or len(raw.encode()) > MAX_MESSAGE:
                raise FeedbackError('invalid')
            value = json.loads(raw, object_pairs_hook=unique_object)
            if type(value) is not dict or type(value.get('v')) is not int or value['v'] != 1:
                raise FeedbackError('invalid')
            request_id = value.get('request')
            identity(self.device, request_id)
            key, operation = value.get('id'), value.get('operation')
            identity(self.device, key)
            expected = {'v', 'request', 'operation', 'id'} | ({'category', 'description', 'logs'} if operation == 'submit' else set())
            if set(value) != expected:
                raise FeedbackError('invalid')
            if operation == 'submit':
                encoded = value['logs']
                if not isinstance(encoded, str) or not encoded.isascii() or len(encoded) > 349528:
                    raise FeedbackError('invalid')
                logs = base64.b64decode(encoded, validate=True)
                if base64.b64encode(logs).decode() != encoded:
                    raise FeedbackError('invalid')
                result = self.store.submit(self.device, key, value['category'], value['description'], logs)
            elif operation == 'read':
                result = self.store.read(self.device, key)
                result['logs'] = base64.b64encode(result['logs']).decode()
            elif operation == 'withdraw':
                result = self.store.withdraw(self.device, key)
                result['all_copies_deleted'] = result.pop('store_deleted') and self.copies_reviewed
            else:
                raise FeedbackError('invalid')
            return dict(v=1, request=request_id, ok=True, result=result)
        except Exception as failure:
            code = failure.code if isinstance(failure, FeedbackError) else 'invalid'
            # Malformed IDs/content are never reflected into failure logs or replies.
            if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9-]{36}', request_id):
                request_id = None
            return dict(v=1, request=request_id, ok=False, error=code)

    async def run(self, socket):
        if self.disabled:
            await socket.close(1011,'feedback unavailable')
            return
        if self.active:
            await socket.close(1013, 'busy')
            return
        self.active = True
        self.socket = socket
        try:
            await socket.send(json.dumps(dict(v=1, type='feedback_ready', protocol='feedback-v1')))
            count = 0
            async for raw in socket:
                count += 1
                if count > 128:
                    await socket.close(1008, 'request limit')
                    return
                await socket.send(json.dumps(self.request(raw), ensure_ascii=False))
        finally:
            self.active = False
            self.socket = None


@asynccontextmanager
async def configured_feedback(runtime, token):
    if runtime is None:
        yield None
        return
    store = FeedbackStore(runtime.database)
    receiver = FeedbackReceiver(store, sha256(token.encode()).hexdigest(), copies_reviewed=runtime.copies_reviewed)
    async def expire():
        while True:
            store.sweep()
            deadline = store.next_deadline()
            delay = 60 if deadline is None else max(.01, min(60, (deadline-store.clock())/1000))
            await asyncio.sleep(delay)
    task = asyncio.create_task(expire())
    def failed(done):
        if not done.cancelled() and done.exception() is not None:
            receiver.disabled = True
            if receiver.socket is not None:
                asyncio.create_task(receiver.socket.close(1011,'feedback unavailable'))
    task.add_done_callback(failed)
    try:
        yield receiver
        # A failed expiry service cannot silently be reported healthy on shutdown.
        if task.done():
            task.result()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        store.close()
