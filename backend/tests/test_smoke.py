import io
import runpy
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from pathlib import Path

from backend.dashscope import GreetingPolicy


probe_answer = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                  "scripts/cloud-voice-smoke.py"))["answer"]


class ProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_probe_requires_the_two_expected_segments_in_order(self):
        class Adapter:
            @asynccontextmanager
            async def answer(self, prompt, *, on_first_text):
                on_first_text()

                async def segments():
                    for text in response:
                        yield text
                yield segments()

        policy = GreetingPolicy()
        for accepted in ("您好，瓦力！", "你好？瓦利。", "你好 瓦里"):
            self.assertEqual(policy.input(accepted), "你好，瓦力。")
        for rejected in ("你好", "你好，瓦力请讲故事", "您好，瓦里和小狗", "你坏瓦力", "瓦力你好"):
            self.assertIsNone(policy.input(rejected))

        for response in (("你好！", "你好。"), ("我是瓦力。", "你好！")):
            with self.subTest(response=response), self.assertRaises(ValueError):
                await probe_answer(Adapter(), policy, "你好，瓦力。")

        response = ("你好！", "我是瓦力。")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(await probe_answer(Adapter(), policy, "你好，瓦力。"), ["你好。", "我是瓦力。"])
