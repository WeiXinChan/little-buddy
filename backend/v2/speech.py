"""V2-only speech socket lifetime within VoicePeer's unchanged 0.5s release bound.

Pinned websockets 17.4: wait_closed confirms connection_lost, not just a close
frame or cancellation. V1 DashScope remains unchanged.
"""
import asyncio
from contextlib import asynccontextmanager
from websockets.asyncio.client import connect
from backend.dashscope import DashScope

class SpeechReleaseError(RuntimeError):
    def __init__(self):super().__init__('speech_release_unconfirmed')

class V2Speech(DashScope):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.release_failed=False;self.release_tasks=set();self.last_release=None

    def _track(self,task):
        self.release_tasks.add(task)
        def finished(done):
            self.release_tasks.discard(done)
            if not done.cancelled():done.exception()
        task.add_done_callback(finished)
        return task

    async def _release(self,socket):
        loop=asyncio.get_running_loop();deadline=loop.time()+.35
        # Capture before connection_lost clears the library's keepalive reference.
        keepalive=socket.keepalive_task
        closing=self._track(asyncio.create_task(socket.close()))
        lost=self._track(asyncio.create_task(socket.wait_closed()))
        tasks={closing,lost}
        if keepalive is not None:tasks.add(keepalive)
        interrupted=False;aborted=False;confirmed=False
        try:
            try:await asyncio.wait({closing},timeout=.2)
            except asyncio.CancelledError:interrupted=True
            if interrupted or not closing.done() or not socket.connection_lost_waiter.done():
                aborted=True;socket.transport.abort()
            remaining=max(0.,deadline-loop.time())
            if remaining:
                try:await asyncio.wait(tasks,timeout=remaining)
                except asyncio.CancelledError:interrupted=True
            confirmed=(socket.connection_lost_waiter.done() and not socket.connection_lost_waiter.cancelled()
                       and all(task.done() for task in tasks) and not lost.cancelled()
                       and lost.exception() is None and not closing.cancelled() and closing.exception() is None)
        except BaseException:
            confirmed=False
            raise
        finally:
            if not confirmed:
                self.release_failed=True;socket.transport.abort()
                for task in tasks:
                    if not task.done():
                        self._track(task);task.cancel()
            self.last_release={'confirmed':confirmed,'aborted':aborted,
                               'pending_tasks':sum(not task.done() for task in tasks)}
        if not confirmed:raise SpeechReleaseError()
        if interrupted:raise asyncio.CancelledError()

    @asynccontextmanager
    async def speech_socket(self):
        if self.release_failed:raise SpeechReleaseError()
        # No connect context __aexit__: our release owns close + lost confirmation.
        socket=await connect(self.ws_url,additional_headers=self.headers,proxy=None,
                             open_timeout=3,close_timeout=.15,max_queue=4,max_size=128_000)
        try:yield socket
        finally:await self._release(socket)
