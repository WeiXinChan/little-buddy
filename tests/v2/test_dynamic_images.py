"""Offline concrete image HTTP/PNG/safety tests. Actual provider requests: zero."""
import asyncio
import base64
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import zlib
import httpx
from backend.v2.dynamic_images import QwenImages,ImageConfig,ImageScope,ReviewDecision,ImageFailure,MAX_BODY
from backend.v2.image_bytes import checked_png,chunk,SIGNATURE
from backend.v2.companion import UnifiedProviders

RAW=(Path(__file__).resolve().parents[2]/'assets/v2-default/png/cat.png').read_bytes()
PNG=checked_png(RAW,512,512)
CONFIG=ImageConfig(enabled=True,region='cn-beijing',workspace='synthetic',model='qwen-image-3.0',
    resource_review_id='synthetic-test-only',prompt_policy='prompt-test-v1',image_policy='image-test-v1')
SCOPE=ImageScope('synthetic-session',1,2,3,4)


class Stream(httpx.AsyncByteStream):
    def __init__(self,body,hook=None):self.body=body;self.closed=False;self.hook=hook
    async def __aiter__(self):
        yield self.body[:32]
        if self.hook:await self.hook()
        yield self.body[32:]
    async def aclose(self):self.closed=True


class Images(unittest.IsolatedAsyncioTestCase):
    async def make(self,*,raw=RAW,payload=None,config=CONFIG,status=200,headers=None,prompt=None,image=None,hook=None):
        self.calls=[];self.streams=[]
        async def transport(request):
            self.calls.append(request)
            body=(json.dumps(dict(data=[dict(b64_json=base64.b64encode(raw).decode())])).encode() if payload is None else payload)
            stream=Stream(body,hook);self.streams.append(stream)
            return httpx.Response(status,headers=headers or {'content-type':'application/json'},stream=stream)
        async def prompt_review(text,nonce):return ReviewDecision(True,sha256(text.encode()).hexdigest(),nonce,CONFIG.prompt_policy)
        async def image_review(png,nonce):return ReviewDecision(True,sha256(png).hexdigest(),nonce,CONFIG.image_policy)
        http=httpx.AsyncClient(transport=httpx.MockTransport(transport),follow_redirects=True,
            headers={'X-Private-Child':'NEVER_SEND_CHILD','Cookie':'NEVER_SEND_COOKIE'},params={'chat':'NEVER_SEND_CHAT'})
        self.addAsyncCleanup(http.aclose)
        adapter=QwenImages(http,config=config,api_key='SYNTHETIC_IMAGE_KEY',prompt_reviewer=prompt or prompt_review,image_reviewer=image or image_review)
        self.addAsyncCleanup(adapter.aclose)
        return adapter

    async def test_concrete_unified_tool_generates_verified_png_from_minimal_catalogue_name(self):
        adapter=await self.make();providers=UnifiedProviders(object(),object(),dynamic_images=adapter)
        result=await providers.prepare_dynamic_visual(dict(kind='generate_image',asset_id='cat'),SCOPE,lambda _:True)
        self.assertEqual(result.read_png(),PNG);self.assertEqual(result.sha256,sha256(PNG).hexdigest())
        self.assertEqual((result.width,result.height),(512,512));self.assertEqual(len(self.calls),1)
        request=self.calls[0];payload=json.loads(request.content)
        self.assertEqual(str(request.url),'https://synthetic.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/images/generations')
        self.assertEqual(payload,dict(model='qwen-image-3.0',prompt='儿童插画：猫',size='512x512',n=1,
            response_format='b64_json',prompt_extend=False,enable_thinking=False))
        for secret in ('NEVER_SEND_CHILD','NEVER_SEND_COOKIE','NEVER_SEND_CHAT',SCOPE.session):
            self.assertNotIn(secret,str(request.headers)+str(request.url)+request.content.decode())
        self.assertTrue(self.streams[0].closed)
        result.release();self.assertTrue(result.released);self.assertEqual(result._png,bytearray())

    async def test_disabled_missing_reviews_and_key_do_not_infer_account_permission(self):
        adapter=await self.make(config=ImageConfig())
        with self.assertRaisesRegex(ImageFailure,'disabled'):await adapter.generate('猫',SCOPE,lambda _:True)
        adapter=await self.make(config=replace(CONFIG,resource_review_id=''))
        with self.assertRaisesRegex(ImageFailure,'unreviewed'):await adapter.generate('猫',SCOPE,lambda _:True)
        adapter=await self.make();adapter._image_reviewer=None
        with self.assertRaisesRegex(ImageFailure,'unreviewed'):await adapter.generate('猫',SCOPE,lambda _:True)
        self.assertEqual(self.calls,[])
        adapter=await self.make(config=replace(CONFIG,region='ap-southeast-1'))
        with self.assertRaisesRegex(ImageFailure,'configuration'):await adapter.generate('猫',SCOPE,lambda _:True)
        self.assertEqual(self.calls,[])

    async def test_prompt_review_must_bind_exact_bytes_nonce_policy_and_literal_bool(self):
        for kind in ('rejected','wrong_hash','wrong_nonce','wrong_policy','truthy'):
            async def reject(text,nonce):
                return ReviewDecision(False if kind=='rejected' else 1 if kind=='truthy' else True,
                    '0'*64 if kind=='wrong_hash' else sha256(text.encode()).hexdigest(),
                    'old' if kind=='wrong_nonce' else nonce,'old' if kind=='wrong_policy' else CONFIG.prompt_policy)
            adapter=await self.make(prompt=reject)
            with self.assertRaisesRegex(ImageFailure,'prompt_review'):await adapter.generate('儿童插画：猫',SCOPE,lambda _:True)
            self.assertEqual(self.calls,[])

    async def test_image_review_missing_or_rejected_never_returns_image(self):
        for kind in ('none','false','wrong_hash','wrong_nonce'):
            async def reject(png,nonce):
                if kind=='none':return None
                return ReviewDecision(kind!='false','0'*64 if kind=='wrong_hash' else sha256(png).hexdigest(),
                                      'old' if kind=='wrong_nonce' else nonce,CONFIG.image_policy)
            adapter=await self.make(image=reject)
            with self.assertRaisesRegex(ImageFailure,'image_review'):await adapter.generate('儿童插画：猫',SCOPE,lambda _:True)
            self.assertIsNone(adapter._last);self.assertEqual(len(self.calls),1)

    async def test_returned_urls_redirects_bad_base64_and_duplicate_fields_are_not_fetched(self):
        for status,payload,headers in [(302,b'',{'content-type':'application/json','location':'http://127.0.0.1/private'}),
            (200,b'{"data":[{"url":"http://127.0.0.1/private"}]}',None),
            (200,b'{"data":[{"b64_json":"%%%"}]}',None),
            (200,b'{"data":[],"data":[]}',None),
            (200,b'{"data":[{"b64_json":"data:image/png;base64,AAAA"}]}',None)]:
            adapter=await self.make(status=status,payload=payload,headers=headers)
            with self.assertRaises(ImageFailure):await adapter.generate('猫',SCOPE,lambda _:True)
            self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0].method,'POST')
            self.assertIsNone(adapter._last)

    async def test_streaming_body_limit_and_http_encoding_are_bounded(self):
        for payload,headers in [(b'x'*(MAX_BODY+1),None),(b'{}',{'content-type':'application/json','content-length':str(MAX_BODY+1)}),
                               (b'{}',{'content-type':'application/json','content-encoding':'gzip'})]:
            adapter=await self.make(payload=payload,headers=headers)
            with self.assertRaisesRegex(ImageFailure,'payload'):await adapter.generate('猫',SCOPE,lambda _:True)
            self.assertTrue(self.streams[0].closed);self.assertIsNone(adapter._last)

    async def test_scope_revocation_at_http_and_review_boundaries_drops_results(self):
        for stage in ('prompt','http','image'):
            live=True
            async def prompt(text,nonce):
                nonlocal live
                if stage=='prompt':live=False
                return ReviewDecision(True,sha256(text.encode()).hexdigest(),nonce,CONFIG.prompt_policy)
            async def hook():
                nonlocal live
                if stage=='http':live=False
            async def image(png,nonce):
                nonlocal live
                if stage=='image':live=False
                return ReviewDecision(True,sha256(png).hexdigest(),nonce,CONFIG.image_policy)
            adapter=await self.make(prompt=prompt,image=image,hook=hook)
            with self.assertRaisesRegex(ImageFailure,'stale'):await adapter.generate('猫',SCOPE,lambda _:live)
            self.assertIsNone(adapter._last)
            self.assertEqual(len(self.calls),0 if stage=='prompt' else 1)

    async def test_ready_buffer_rechecks_scope_and_auto_expiry_erases_owned_material(self):
        live=True;adapter=await self.make(config=replace(CONFIG,result_ttl=.02))
        result=await adapter.generate('猫',SCOPE,lambda _:live)
        live=False
        with self.assertRaisesRegex(ImageFailure,'stale'):result.read_png()
        self.assertTrue(result.released);self.assertEqual(result._png,bytearray())
        self.assertEqual(result.sha256,'');self.assertIsNone(result.scope)
        live=True;result=await adapter.generate('猫',SCOPE,lambda _:live)
        await asyncio.sleep(.03)
        self.assertTrue(result.released);self.assertEqual(result._png,bytearray())

    async def test_only_one_task_and_scoped_cancel_cannot_cancel_later_owner(self):
        started=asyncio.Event();release=asyncio.Event()
        async def prompt(text,nonce):
            started.set();await release.wait()
            return ReviewDecision(True,sha256(text.encode()).hexdigest(),nonce,CONFIG.prompt_policy)
        adapter=await self.make(prompt=prompt);task=asyncio.create_task(adapter.generate('猫',SCOPE,lambda _:True))
        await started.wait()
        with self.assertRaisesRegex(ImageFailure,'busy'):await adapter.generate('狗',replace(SCOPE,topic=5),lambda _:True)
        self.assertFalse(adapter.cancel(replace(SCOPE,topic=0)))
        self.assertTrue(adapter.cancel(SCOPE))
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.calls,[])
        release.set();newscope=replace(SCOPE,topic=5)
        result=await adapter.generate('狗',newscope,lambda _:True)
        self.assertFalse(adapter.cancel(SCOPE));self.assertFalse(result.released)
        self.assertTrue(adapter.cancel(newscope));self.assertTrue(result.released)

    async def test_timeout_and_unconfirmed_cancellation_quarantine_without_retry(self):
        release=asyncio.Event()
        async def refuses(text,nonce):
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()
            return ReviewDecision(True,sha256(text.encode()).hexdigest(),nonce,CONFIG.prompt_policy)
        adapter=await self.make(config=replace(CONFIG,timeout=.02),prompt=refuses)
        try:
            with self.assertRaisesRegex(ImageFailure,'timeout'):await asyncio.wait_for(adapter.generate('猫',SCOPE,lambda _:True),.8)
            self.assertTrue(adapter.quarantined)
            with self.assertRaisesRegex(ImageFailure,'quarantined'):await adapter.generate('猫',SCOPE,lambda _:True)
            self.assertEqual(self.calls,[])
        finally:
            release.set()
            if adapter._task:await asyncio.gather(adapter._task,return_exceptions=True)

    async def test_png_real_dimensions_crc_zlib_and_no_trailing_payload(self):
        ihdr=struct.pack('>IIBBBBB',512,512,8,2,0,0,0)
        bomb=SIGNATURE+chunk(b'IHDR',ihdr)+chunk(b'IDAT',zlib.compress(b'\0'*(512*512*3+512+100)))+chunk(b'IEND',b'')
        wrong=SIGNATURE+chunk(b'IHDR',struct.pack('>IIBBBBB',513,512,8,2,0,0,0))+RAW[33:]
        bad_zlib=SIGNATURE+chunk(b'IHDR',ihdr)+chunk(b'IDAT',b'not-zlib')+chunk(b'IEND',b'')
        badcrc=bytearray(RAW);badcrc[-1]^=1
        for raw in [RAW[:33],RAW+b'PRIVATE_TRAILER',wrong,bytes(badcrc),bomb,bad_zlib]:
            adapter=await self.make(raw=raw)
            with self.assertRaisesRegex(ImageFailure,'png'):await adapter.generate('猫',SCOPE,lambda _:True)
            self.assertIsNone(adapter._last)

    async def test_outer_caller_cancellation_at_network_closes_stream_without_late_result(self):
        started=asyncio.Event()
        async def block():started.set();await asyncio.Event().wait()
        adapter=await self.make(hook=block)
        task=asyncio.create_task(adapter.generate('猫',SCOPE,lambda _:True))
        await started.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,.8)
        self.assertTrue(self.streams[0].closed);self.assertIsNone(adapter._last)
        self.assertFalse(adapter.quarantined);self.assertIsNone(adapter._task)

    async def test_stream_stall_hits_total_budget_with_no_automatic_retry(self):
        async def block():await asyncio.Event().wait()
        adapter=await self.make(config=replace(CONFIG,timeout=.02),hook=block)
        with self.assertRaisesRegex(ImageFailure,'timeout'):await asyncio.wait_for(adapter.generate('猫',SCOPE,lambda _:True),.8)
        self.assertEqual(len(self.calls),1);self.assertTrue(self.streams[0].closed)
        self.assertIsNone(adapter._last);self.assertFalse(adapter.quarantined)

    async def test_upstream_error_and_unknown_asset_do_not_leak_or_dispatch_extra_requests(self):
        adapter=await self.make(status=503,payload=b'{"error":"PRIVATE_UPSTREAM_TEXT"}')
        with self.assertRaisesRegex(ImageFailure,'upstream') as failure:await adapter.generate('猫',SCOPE,lambda _:True)
        self.assertNotIn('PRIVATE',str(failure.exception));self.assertEqual(len(self.calls),1)
        providers=UnifiedProviders(object(),object(),dynamic_images=adapter)
        with self.assertRaisesRegex(ImageFailure,'prompt'):
            await providers.prepare_dynamic_visual(dict(kind='generate_image',asset_id='PRIVATE_CHILD_CHAT'),SCOPE,lambda _:True)
        self.assertEqual(len(self.calls),1)

    async def test_ancillary_text_removed_before_safety_and_no_disk_io(self):
        tagged=RAW[:33]+chunk(b'tEXt',b'Private\0SYNTHETIC_PRIVATE_METADATA')+RAW[33:]
        async def review(png,nonce):
            self.assertNotIn(b'SYNTHETIC_PRIVATE_METADATA',png)
            return ReviewDecision(True,sha256(png).hexdigest(),nonce,CONFIG.image_policy)
        adapter=await self.make(raw=tagged,image=review)
        with patch('builtins.open',side_effect=AssertionError('no image persistence')):
            result=await adapter.generate('猫',SCOPE,lambda _:True)
        self.assertEqual(result.read_png(),PNG)

    async def test_negative_control_bypassing_image_review_is_detected(self):
        async def deny(png,nonce):return ReviewDecision(False,sha256(png).hexdigest(),nonce,CONFIG.image_policy)
        adapter=await self.make(image=deny);original=adapter._reviewed
        def wrong(decision,content,nonce,policy):
            return True if policy==CONFIG.image_policy else original(decision,content,nonce,policy)
        with patch.object(adapter,'_reviewed',wrong):
            with self.assertRaises(AssertionError):
                with self.assertRaises(ImageFailure):await adapter.generate('猫',SCOPE,lambda _:True)
