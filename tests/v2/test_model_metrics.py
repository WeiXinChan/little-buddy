"""Offline injected HTTP timings/usage; no new model sampling or price claims."""
import asyncio
import json
import unittest
import httpx
from backend.dashscope import DashScope
from backend.v2.companion import DashScopeModel
from backend.v2.runtime import manifest
from backend.v2.voice import VoiceFault


class Metrics(unittest.IsolatedAsyncioTestCase):
    def model(self,http):
        return DashScopeModel(DashScope(http,workspace='private-workspace',region='cn-beijing',
            key='PRIVATE_KEY',asr='fun-asr-realtime',llm='qwen3.8-flash',tts='cosyvoice-v3-flash',voice='longanyang'))

    async def test_known_and_missing_usage_are_distinct_from_zero_with_bounded_latency(self):
        usages=[dict(prompt_tokens=12,completion_tokens=3),{},dict(prompt_tokens=True,completion_tokens=-1),[],
                dict(prompt_tokens=0,completion_tokens=0)]
        async def response(request):
            return httpx.Response(200,json=dict(choices=[dict(message=dict(content='PRIVATE_TEXT'))],usage=usages.pop(0)))
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            model=self.model(http)
            for _ in range(5):await model.complete('PRIVATE_INPUT',{})
            metrics=model.metrics()
        self.assertEqual(metrics['usage']['prompt_tokens'],12)
        self.assertEqual(metrics['usage_observed'],dict(prompt_tokens=2,completion_tokens=2))
        self.assertEqual(metrics['usage_missing'],dict(prompt_tokens=3,completion_tokens=3))
        self.assertEqual(sum(metrics['latency']['buckets']),5)
        self.assertEqual(metrics['latency']['count'],5);self.assertEqual(len(metrics['latency']['buckets']),6)
        self.assertIsNone(metrics['cost']['monetary'])
        self.assertNotIn('PRIVATE_',json.dumps(metrics))
        metrics['latency']['buckets'][0]=999
        self.assertNotIn(999,model.metrics()['latency']['buckets'])

    async def test_failure_and_cancellation_timed_without_exception_text_or_success_usage(self):
        started=asyncio.Event()
        async def response(request):
            if not started.is_set():started.set();return httpx.Response(503,json=dict(error='PRIVATE_ERROR'))
            await asyncio.Event().wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            model=self.model(http)
            with self.assertRaises(VoiceFault):await model.complete('PRIVATE_INPUT',{})
            task=asyncio.create_task(model.complete('PRIVATE_INPUT',{}))
            await asyncio.sleep(0);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            metrics=model.metrics()
        self.assertEqual(metrics['usage']['failures'],1);self.assertEqual(metrics['cancelled'],1)
        self.assertEqual(metrics['latency']['count'],2)
        self.assertEqual(metrics['usage_observed']['prompt_tokens'],0)
        self.assertNotIn('PRIVATE_',json.dumps(metrics))

    async def test_manifest_has_actual_runtime_and_parameters_without_credential_scope(self):
        output=manifest(dict(workspace='PRIVATE_WORKSPACE',region='cn-beijing',asr='fun-asr-realtime',
            llm='qwen3.8-flash',tts='cosyvoice-v3-flash',voice='longanyang'))
        self.assertEqual(output['deployment']['context_bytes'],65536)
        self.assertIn('python',output['runtime']);self.assertEqual(output['prices'],'not_verified')
        self.assertNotIn('PRIVATE_',json.dumps(output))

    async def test_negative_control_zero_price_claim_is_detected(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as http:metrics=self.model(http).metrics()
        metrics['cost']['monetary']=0
        with self.assertRaises(AssertionError):self.assertIsNone(metrics['cost']['monetary'])
