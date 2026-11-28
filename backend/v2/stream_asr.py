"""One expression's raw audio resource, never an authority to publish or commit.

No transcript/partial result log, no clock renewal, no global connection pool.
Only VoicePeer's exact current probe Operation may freeze and finish this writer.
"""
import asyncio


class RawASRLease:
    def __init__(self, peer, ensure_scope, *, check_scope):
        self.peer = peer
        self.ensure_scope = ensure_scope
        self.check_scope = check_scope
        self.changed = asyncio.Event()
        self.offset = 0
        self.available = len(peer.capture)
        self.limit = None
        self.operation = None
        self.revoked = False
        self.task = asyncio.create_task(self.run())
        peer.track_retired(self.task)

    def ensure(self):
        self.ensure_scope()
        if self.operation is not None:
            self.operation.ensure()
        if self.revoked or asyncio.current_task().cancelling():
            raise asyncio.CancelledError()

    def appended(self):
        self.available = len(self.peer.capture)
        self.changed.set()

    def freeze(self, operation):
        self.ensure_scope()
        operation.ensure()
        if self.operation is not None:
            raise RuntimeError('raw_asr_already_claimed')
        self.operation = operation
        self.limit = len(self.peer.capture)
        self.changed.set()

    def revoke(self):
        self.revoked = True
        if self.operation is not None:
            self.operation.cancelled = True
        self.task.cancel()
        self.changed.set()

    async def run(self):
        self.ensure()
        # resource() retains the production acquire and .5s release bounds.
        async with self.peer.resource(self.peer.providers.recognize(16000)) as recognizer:
            self.ensure()
            while True:
                self.ensure()
                self.changed.clear()
                end = self.available if self.limit is None else self.limit
                if self.offset < end:
                    # Capture only includes received/validated PCM. A chunk is an
                    # immutable copy across await; the sole writer owns offset.
                    following = min(end, self.offset + 6400)
                    pcm = bytes(self.peer.capture[self.offset:following])
                    if len(pcm) != following - self.offset:
                        raise RuntimeError('raw_asr_capture_changed')
                    self.ensure()
                    await recognizer.write(pcm)
                    self.ensure()
                    self.offset = following
                    pcm = b''
                elif self.limit is not None:
                    # No finish before a probe; no bytes beyond its frozen N.
                    self.ensure()
                    text = await recognizer.finish()
                    self.ensure()
                    return text
                else:
                    await self.changed.wait()
                    self.ensure()
