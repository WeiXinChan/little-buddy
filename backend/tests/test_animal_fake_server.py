import json
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from animal.fake_server import game
from animal.rules import CARDS, CATALOG_VERSION


class FakeGameTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_full_game_and_replay_with_both_receipt_orders(self):
        async with serve(game, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            for ack_first in (False, True):
                with self.subTest(ack_first=ack_first):
                    async with connect(f"ws://127.0.0.1:{port}/animal") as socket:
                        await self.play(socket, ack_first)

    async def play(self, socket, ack_first):
        async def send(event, **fields):
            await socket.send(json.dumps(dict(event=event, **fields)))

        async def receive(event):
            import asyncio
            value = json.loads(await asyncio.wait_for(socket.recv(), 2))
            self.assertEqual(value["event"], event)
            return value

        async def drain():
            reply = await receive("reply")
            key = reply["key"]
            size = len(reply["segments"])
            if not ack_first:
                self.assertEqual((await receive("reply.end"))["count"], size)
            for number in range(1, size + 1):
                await send("playback.segment_completed", key=key, number=number)
                for _ in range(2):
                    confirmed = await receive("playback.segment_committed")
                    self.assertEqual((confirmed["key"], confirmed["number"]), (key, number))
            if ack_first:
                self.assertEqual((await receive("reply.end"))["count"], size)
            commit = await receive("turn.committed")
            self.assertEqual(await receive("turn.committed"), commit)
            self.assertEqual(commit["key"], key)
            return reply, commit

        async def answer(commit, text):
            fields = dict(key=commit["key"], listen_id=commit["listen_id"])
            await send("turn.start", **fields, text=text)
            await send("listen.silence", **fields)

        await send("session.start", catalog=CATALOG_VERSION, images=[card.image_id for card in CARDS],
                   ack_first=ack_first, duplicate=True)
        _, commit = await drain()
        for completed in range(1, 4):
            self.assertEqual(commit["next_action"], "listen")
            await answer(commit, "告诉我答案")
            reply, commit = await drain()
            self.assertEqual(sum(segment["image_id"] is not None for segment in reply["segments"]), 1)
            self.assertEqual(commit["completed"], completed)
            self.assertEqual(commit["next_action"], "advance")
            await send("turn.advance", key=commit["key"])
            _, commit = await drain()
        await answer(commit, "再玩")
        reply, commit = await drain()
        self.assertEqual(commit["completed"], 0)
        self.assertEqual(commit["next_action"], "listen")
        self.assertTrue(all(segment["image_id"] is None for segment in reply["segments"]))
