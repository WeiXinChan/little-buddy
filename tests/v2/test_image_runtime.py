"""Exercise the real optional live composition without listening or inference."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.v2.files import ConfigurationError
from backend.v2.image_runtime import read_image_runtime, configured_images, PROMPT_POLICY, IMAGE_POLICY
from backend.v2.live import parser, serve_checked
from backend.v2.preflight import MODELS


class Runtime(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config = dict(enabled=True, region='cn-beijing', workspace='synthetic', model='qwen-image-3.0',
            review_model='deepseek-v4.1-flash-1017', resource_review_id='fixture-only', prompt_policy=PROMPT_POLICY,
            image_policy=IMAGE_POLICY, width=512, height=512, timeout=8, result_ttl=15)
        path = root / 'image.json'
        path.write_text(json.dumps(config)); path.chmod(0o600)
        for name in ['dashscope-image-key', 'dashscope-review-key']:
            key = root / name; key.write_text('SYNTHETIC_KEY'); key.chmod(0o600)
        return root, path, config

    async def test_disabled_does_not_read_credentials_or_require_a_file(self):
        self.assertIsNone(read_image_runtime(None, '/missing', 'synthetic'))
        root, path, _ = self.fixture()
        path.write_text('{"enabled":false}')
        self.assertIsNone(read_image_runtime(path, '/missing', 'synthetic'))
        async with configured_images(None, None) as adapter:
            self.assertIsNone(adapter)
        self.assertIn('--image-config', parser().format_help())

    async def test_strict_configuration_and_protected_credentials(self):
        root, path, config = self.fixture()
        runtime = read_image_runtime(path, root, 'synthetic')
        self.assertNotIn('SYNTHETIC_KEY', repr(runtime))
        for name, value in [('workspace', 'another'), ('prompt_policy', 'test-allow-all'),
                            ('review_model', 'unreviewed'), ('enabled', 1), ('extra', 'ignored')]:
            bad = dict(config); bad[name] = value; path.write_text(json.dumps(bad))
            with self.assertRaises(ConfigurationError):
                read_image_runtime(path, root, 'synthetic')
        path.write_text(json.dumps(config))
        (root / 'dashscope-review-key').chmod(0o644)
        with self.assertRaises(ConfigurationError):
            read_image_runtime(path, root, 'synthetic')

    async def test_context_teardown_closes_concrete_adapter_on_failure(self):
        root, path, _ = self.fixture()
        runtime = read_image_runtime(path, root, 'synthetic')
        with self.assertRaisesRegex(RuntimeError, 'stop'):
            async with configured_images(object(), runtime) as adapter:
                self.assertEqual(adapter.availability(), 'configured')
                self.assertTrue(callable(adapter._prompt_reviewer))
                self.assertTrue(callable(adapter._image_reviewer))
                raise RuntimeError('stop')
        self.assertEqual(adapter.availability(), 'unavailable')

    async def test_actual_live_assembly_injects_reviewed_adapter_and_closes_it(self):
        root, path, _ = self.fixture()
        runtime = read_image_runtime(path, root, 'synthetic')
        captured = []
        @asynccontextmanager
        async def http_client():
            yield object()  # Any accidental request fails rather than reaching a supplier.
        @asynccontextmanager
        async def voice_server(host, port, tls, token, providers, policy, **kwargs):
            self.assertEqual((host, port), ('127.0.0.1', 19483))
            captured.append(providers.dynamic_images)
            self.assertEqual(providers.dynamic_images.availability(), 'configured')
            yield object()
        prepared = SimpleNamespace(provider_key='SYNTHETIC_KEY', tls=None, token='a'*64,
            config=dict(workspace='synthetic', region='cn-beijing', **MODELS),
            expires_at=int(time.time())+60, images=runtime)
        stop = asyncio.Event(); stop.set()
        with patch('backend.dashscope.http_client', http_client), \
             patch('backend.v2.server.voice_server', voice_server), \
             patch('backend.v2.files.disable_core_dumps'), patch('backend.v2.live.notify_ready'):
            await serve_checked(SimpleNamespace(port=19483), prepared, stop=stop)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].availability(), 'unavailable')
