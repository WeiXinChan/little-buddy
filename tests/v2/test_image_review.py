"""Concrete reviewer request/denial/cancellation checks, no supplier calls."""
import asyncio
import base64
from hashlib import sha256
import json
from pathlib import Path
import unittest

import httpx

from backend.v2.dynamic_images import ImageFailure, ImageConfig, ImageScope, QwenImages
from backend.v2.image_bytes import checked_png
from backend.v2.image_review import ModelImageReview, MAX_RESPONSE

NONCE = 'a' * 32
RAW = (Path(__file__).resolve().parents[2] / 'assets/v2-default/png/cat.png').read_bytes()
PNG = checked_png(RAW, 512, 512)


class Stream(httpx.AsyncByteStream):
    def __init__(self, data, gate=None):
        self.data, self.gate, self.closed = data, gate, False

    async def __aiter__(self):
        if self.gate:
            self.gate.set()
            await asyncio.Event().wait()
        yield self.data

    async def aclose(self):
        self.closed = True


class Reviewer(unittest.IsolatedAsyncioTestCase):
    async def make(self, content='{"allow":true}', *, status=200, finish='stop', body=None, gate=None):
        self.calls = []
        envelope = dict(choices=[dict(finish_reason=finish, message=dict(role='assistant', content=content))])
        self.stream = Stream(json.dumps(envelope).encode() if body is None else body, gate)
        async def send(request):
            self.calls.append(request)
            return httpx.Response(status, headers={'content-type': 'application/json'}, stream=self.stream)
        http = httpx.AsyncClient(transport=httpx.MockTransport(send), follow_redirects=True,
            headers={'Cookie': 'PRIVATE_COOKIE', 'X-Child': 'PRIVATE_CHILD'}, params={'chat': 'PRIVATE_CHAT'})
        self.addAsyncCleanup(http.aclose)
        return ModelImageReview(http, workspace='synthetic', region='cn-beijing', api_key='SYNTHETIC_KEY',
                                prompt_policy='prompt-v1', image_policy='image-v1', timeout=.1)

    async def test_prompt_real_request_is_minimal_and_receipt_binds_exact_material(self):
        reviewer = await self.make()
        result = await reviewer.prompt('儿童插画：猫', NONCE)
        self.assertTrue(result.approved)
        self.assertEqual((result.content_sha256, result.nonce, result.policy),
                         (sha256('儿童插画：猫'.encode()).hexdigest(), NONCE, 'prompt-v1'))
        request = self.calls[0]
        data = json.loads(request.content)
        self.assertEqual(data['messages'][1], dict(role='user', content='儿童插画：猫'))
        self.assertFalse(data['stream'])
        self.assertEqual(data['response_format'], {'type': 'json_object'})
        for marker in ['PRIVATE_COOKIE', 'PRIVATE_CHILD', 'PRIVATE_CHAT', NONCE]:
            self.assertNotIn(marker, str(request.headers) + str(request.url) + request.content.decode())
        self.assertTrue(self.stream.closed)

    async def test_image_sends_only_canonical_png_and_binds_image_digest(self):
        reviewer = await self.make()
        result = await reviewer.image(PNG, NONCE)
        self.assertEqual(result.content_sha256, sha256(PNG).hexdigest())
        self.assertEqual(result.policy, 'image-v1')
        message = json.loads(self.calls[0].content)['messages'][1]['content'][0]
        uri = message['image_url']['url']
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(uri.split(',', 1)[1]), PNG)

    async def test_denial_is_real_and_malformed_truncated_truthy_duplicate_decisions_fail_closed(self):
        reviewer = await self.make('{"allow":false}')
        self.assertFalse((await reviewer.prompt('猫', NONCE)).approved)
        for content in ['{"allow":1}', '{"allow":true,"allow":false}',
                        '{"allow":true,"extra":"ignored"}', '[true]', 'approved']:
            reviewer = await self.make(content)
            with self.assertRaises(ImageFailure):
                await reviewer.prompt('猫', NONCE)
        reviewer = await self.make(finish='length')
        with self.assertRaises(ImageFailure):
            await reviewer.prompt('猫', NONCE)

    async def test_bad_input_and_noncanonical_png_do_not_dispatch(self):
        for material in ['', 'x' * 161, '猫\n隐私']:
            reviewer = await self.make()
            with self.assertRaises(ImageFailure):
                await reviewer.prompt(material, NONCE)
            self.assertEqual(self.calls, [])
        reviewer = await self.make()
        with self.assertRaises(ImageFailure):
            await reviewer.image(PNG + b'PRIVATE_TRAILER', NONCE)
        with self.assertRaises(ImageFailure):
            await reviewer.prompt('猫', 'invalid')
        self.assertEqual(self.calls, [])

    async def test_http_redirect_error_and_oversize_are_finite_failures_no_retry(self):
        for status, body in [(302, b''), (503, b'PRIVATE_UPSTREAM'), (200, b'x' * (MAX_RESPONSE + 1))]:
            reviewer = await self.make(status=status, body=body)
            with self.assertRaisesRegex(ImageFailure, '^prompt_review$'):
                await reviewer.prompt('猫', NONCE)
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(self.stream.closed)

    async def test_timeout_and_caller_cancel_close_stream_without_late_approval(self):
        gate = asyncio.Event()
        reviewer = await self.make(gate=gate)
        with self.assertRaisesRegex(ImageFailure, '^prompt_review$'):
            await reviewer.prompt('猫', NONCE)
        self.assertTrue(self.stream.closed)
        gate = asyncio.Event()
        reviewer = await self.make(gate=gate)
        task = asyncio.create_task(reviewer.prompt('猫', NONCE))
        await gate.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.stream.closed)

    async def test_concrete_review_ports_gate_actual_generation_result(self):
        calls = []
        async def send(request):
            calls.append(request)
            if request.url.path.endswith('/images/generations'):
                payload = dict(data=[dict(b64_json=base64.b64encode(PNG).decode())])
            else:
                message = json.loads(request.content)['messages'][1]['content']
                # Prompt may pass; an image denial must still suppress delivery.
                content = json.dumps({'allow': isinstance(message, str)})
                payload = dict(choices=[dict(finish_reason='stop', message=dict(role='assistant', content=content))])
            return httpx.Response(200, headers={'content-type': 'application/json'},
                                  stream=Stream(json.dumps(payload).encode()))
        http = httpx.AsyncClient(transport=httpx.MockTransport(send))
        self.addAsyncCleanup(http.aclose)
        reviewer = ModelImageReview(http, workspace='synthetic', region='cn-beijing',
            api_key='SYNTHETIC_KEY', prompt_policy='prompt-v1', image_policy='image-v1')
        images = QwenImages(http, api_key='SYNTHETIC_IMAGE_KEY', config=ImageConfig(
            enabled=True, workspace='synthetic', region='cn-beijing', model='qwen-image-3.0',
            resource_review_id='fixture-only', prompt_policy='prompt-v1', image_policy='image-v1'),
            prompt_reviewer=reviewer.prompt, image_reviewer=reviewer.image)
        self.addAsyncCleanup(images.aclose)
        with self.assertRaisesRegex(ImageFailure, '^image_review$'):
            await images.generate('儿童插画：猫', ImageScope('synthetic', 1, 1, 1, 1), lambda _: True)
        self.assertEqual(len(calls), 3)
        self.assertIsNone(images._last)
