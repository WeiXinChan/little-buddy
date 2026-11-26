"""Offline API/URL, public DNS pinning and free-only failover contract. Cloud calls: zero."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
import json
import socket
import ssl
import unittest
from unittest.mock import patch

import httpx
from backend.v2 import image_download as net
from backend.v2.dynamic_images import QwenImages,ImageFailure,ReviewDecision,ERROR_BODY
from backend.v2.image_bytes import MAX_PNG
from tests.v2.test_dynamic_images import CONFIG,SCOPE,RAW,PNG,Stream

TURBO='qwen-image-2.1-turbo';PRO='qwen-image-2.1-pro'
FREE=replace(CONFIG,model=TURBO,fallback_model=PRO,free_tier_only=True)
URL='https://'+net.OUTPUT_HOST+'/fixture/image.png?Expires=9999999999&Signature=SYNTHETIC_URL_SIGNATURE'
QUOTA={'error':{'code':'AllocationQuota.FreeTierOnly','message':'synthetic quota'}}


class Pool:
    def __init__(self,owner,**options):self.owner=owner;self.options=options;self.closed=False;owner.pools.append(self)
    async def __aenter__(self):return self
    async def __aexit__(self,*args):self.closed=True
    @asynccontextmanager
    async def stream(self,method,url,**args):
        self.owner.downloads.append((method,url,args));owner=self.owner
        class Response:
            status=owner.download_status
            headers=owner.download_headers
            async def aiter_stream(self):
                for index in range(0,len(owner.png),1024):
                    if owner.download_hook:await owner.download_hook()
                    yield owner.png[index:index+1024]
        try:yield Response()
        finally:owner.response_closed=True


class FreeImages(unittest.IsolatedAsyncioTestCase):
    async def make(self,replies=None,*,config=FREE,png=RAW,status=200,headers=None,prompt_ok=True,image_ok=True,hook=None,api_hook=None):
        self.api=[];self.downloads=[];self.pools=[];self.prompt_count=0;self.image_count=0;self.response_closed=False
        self.download_status=status;self.download_headers=headers or [(b'content-type',b'image/png')]
        self.png=png;self.download_hook=hook
        replies=list(replies or [(200,{'data':[{'url':URL}]})])
        async def transport(request):
            self.api.append(request)
            if api_hook:await api_hook()
            status,payload=replies[min(len(self.api)-1,len(replies)-1)]
            body=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
            return httpx.Response(status,headers={'content-type':'application/json'},stream=Stream(body))
        async def prompt(text,nonce):
            self.prompt_count+=1
            return ReviewDecision(prompt_ok,sha256(text.encode()).hexdigest(),nonce,CONFIG.prompt_policy)
        async def image(png,nonce):
            self.image_count+=1
            return ReviewDecision(image_ok,sha256(png).hexdigest(),nonce,CONFIG.image_policy)
        http=httpx.AsyncClient(transport=httpx.MockTransport(transport),headers={'Cookie':'PRIVATE_COOKIE','X-Child':'PRIVATE_ID'},
            params={'chat':'PRIVATE_CHAT'},auth=('PRIVATE_AUTH','PRIVATE_PASSWORD'),follow_redirects=True)
        self.addAsyncCleanup(http.aclose)
        adapter=QwenImages(http,config=config,api_key='SYNTHETIC_BEARER',prompt_reviewer=prompt,image_reviewer=image)
        self.addAsyncCleanup(adapter.aclose)
        patched=patch('backend.v2.image_download.httpcore.AsyncConnectionPool',side_effect=lambda **options:Pool(self,**options))
        patched.start();self.addCleanup(patched.stop)
        return adapter

    async def generate(self,adapter):return await adapter.generate('儿童插画：猫',SCOPE,lambda _:True)
    def models(self):return [json.loads(r.content)['model'] for r in self.api]

    async def test_turbo_uses_url_specific_isolated_download_then_original_png_review(self):
        adapter=await self.make()
        with patch.dict('os.environ',{'HTTPS_PROXY':'http://127.0.0.1:1','HTTP_PROXY':'http://127.0.0.1:1'}):
            result=await self.generate(adapter)
        self.assertEqual(self.models(),[TURBO]);self.assertEqual(result.read_png(),PNG)
        payload=json.loads(self.api[0].content)
        self.assertEqual((payload['response_format'],payload['n'],payload['size']),('url',1,'512x512'))
        self.assertEqual((self.prompt_count,self.image_count),(1,1))
        self.assertEqual(len(self.downloads),1);method,url,args=self.downloads[0]
        self.assertEqual((method,url),('GET',URL));headers=args['headers']
        self.assertEqual(headers,[(b'Accept',b'image/png'),(b'Accept-Encoding',b'identity'),(b'Connection',b'close')])
        for secret in ('PRIVATE_COOKIE','PRIVATE_ID','PRIVATE_CHAT','PRIVATE_AUTH','SYNTHETIC_BEARER'):
            self.assertNotIn(secret,str(headers)+str(self.pools[0].options))
        self.assertIsNone(self.pools[0].options['proxy']);self.assertEqual(self.pools[0].options['retries'],0)
        self.assertEqual(self.pools[0].options['max_keepalive_connections'],0)
        self.assertIsInstance(self.pools[0].options['network_backend'],net.PublicOutputBackend)
        self.assertTrue(self.pools[0].closed and self.response_closed)
        result.release();self.assertEqual(result._png,bytearray())

    async def test_only_explicit_quota_error_switches_once_to_pro_shared_one_review(self):
        adapter=await self.make([(403,QUOTA),(200,{'data':[{'url':URL}]})])
        result=await self.generate(adapter);result.release()
        self.assertEqual(self.models(),[TURBO,PRO]);self.assertEqual(self.prompt_count,1);self.assertEqual(self.image_count,1)
        self.assertEqual(len(self.downloads),1)
        result=await self.generate(adapter);result.release()
        self.assertEqual(self.models(),[TURBO,PRO,PRO]) # observed exhaustion, not successful-image counting
        self.assertNotIn('qwen-image-3.0',self.models())

    async def test_flat_official_error_envelope_and_both_exhausted_stop_future_calls(self):
        flat={'code':'AllocationQuota.FreeTierOnly','message':'synthetic','request_id':'fixture'}
        adapter=await self.make([(403,flat),(403,QUOTA)])
        with self.assertRaisesRegex(ImageFailure,'quota'):await self.generate(adapter)
        self.assertEqual(adapter.availability(),'quota')
        with self.assertRaisesRegex(ImageFailure,'quota'):await self.generate(adapter)
        self.assertEqual(self.models(),[TURBO,PRO]);self.assertEqual(self.prompt_count,1)
        self.assertEqual(self.downloads,[])

    async def test_unknown_403_balance_429_produced_data_and_malformed_errors_never_fallback(self):
        cases=[(403,{'error':{'code':'AccountOverdue','message':'AllocationQuota.FreeTierOnly'}}),
            (403,{'message':'AllocationQuota.FreeTierOnly'}),(429,QUOTA),
            (403,dict(QUOTA,data=[{'url':URL}])),(403,dict(QUOTA,usage={'image_count':1})),
            (200,QUOTA),(403,b'{"code":"AllocationQuota.FreeTierOnly","code":"AccountOverdue"}'),
            (403,b'x'*(ERROR_BODY+1))]
        for reply in cases:
            adapter=await self.make([reply])
            with self.assertRaises(ImageFailure) as error:await self.generate(adapter)
            self.assertNotIn(URL,str(error.exception));self.assertEqual(self.models(),[TURBO]);self.assertEqual(self.downloads,[])

    async def test_url_security_rejections_happen_without_any_get_or_fallback(self):
        for url in ('http://'+net.OUTPUT_HOST+'/x.png','https://127.0.0.1/x.png',
            'https://evil.oss-cn-shenzhen.aliyuncs.com/x.png','https://'+net.OUTPUT_HOST+'.evil/x.png',
            'https://user@'+net.OUTPUT_HOST+'/x.png','https://'+net.OUTPUT_HOST+':8443/x.png',
            'https://'+net.OUTPUT_HOST+'/x.png#fragment','https://'+net.OUTPUT_HOST+'/../x.png',
            'https://'+net.OUTPUT_HOST+'/%2e%2e/x.png','https://'+net.OUTPUT_HOST+'/x.jpg',
            'https://'+net.OUTPUT_HOST+'/x.png\r\nX:yes','https://'+net.OUTPUT_HOST+'/x.png?q='+'a'*4096):
            adapter=await self.make([(200,{'data':[{'url':url}]})])
            with self.assertRaises(ImageFailure):await self.generate(adapter)
            self.assertEqual(self.models(),[TURBO]);self.assertEqual(self.downloads,[])

    async def test_redirect_mime_encoding_body_size_or_wrong_png_never_retries_model(self):
        for options in (dict(status=302,headers=[(b'content-type',b'image/png'),(b'location',b'http://127.0.0.1')]),
            dict(headers=[(b'content-type',b'image/jpeg')]),
            dict(headers=[(b'content-type',b'image/png'),(b'content-encoding',b'gzip')]),
            dict(headers=[(b'content-type',b'image/png'),(b'content-length',str(MAX_PNG+1).encode())]),
            dict(headers=[(b'content-type',b'image/png'),(b'content-length',b'1'),(b'content-length',b'1')]),
            dict(headers=[(b'content-type',b'image/png'),(b'content-length',b'1')]),
            dict(png=b'not a PNG'),dict(png=b'x'*(MAX_PNG+1))):
            adapter=await self.make(**options)
            with self.assertRaises(ImageFailure):await self.generate(adapter)
            self.assertEqual(self.models(),[TURBO]);self.assertTrue(self.pools[0].closed)
            self.assertEqual(self.image_count,0)

    async def test_prompt_or_image_rejection_does_not_generate_a_replacement(self):
        adapter=await self.make(prompt_ok=False)
        with self.assertRaisesRegex(ImageFailure,'prompt_review'):await self.generate(adapter)
        self.assertEqual(self.api,[]);self.assertEqual(self.downloads,[])
        adapter=await self.make(image_ok=False)
        with self.assertRaisesRegex(ImageFailure,'image_review'):await self.generate(adapter)
        self.assertEqual(self.models(),[TURBO]);self.assertEqual(len(self.downloads),1)
        self.assertIsNone(adapter._last)

    async def test_revoked_or_cancelled_download_closes_and_cannot_publish_or_fallback(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def block():entered.set();await release.wait()
        adapter=await self.make(hook=block)
        task=asyncio.create_task(self.generate(adapter));await entered.wait()
        adapter.cancel(SCOPE);release.set()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(self.response_closed and self.pools[0].closed);self.assertIsNone(adapter._last)
        self.assertEqual(self.models(),[TURBO])
        current=[True]
        async def revoke():current[0]=False
        adapter=await self.make(hook=revoke)
        with self.assertRaisesRegex(ImageFailure,'stale'):await adapter.generate('猫',SCOPE,lambda _:current[0])
        self.assertTrue(self.pools[0].closed);self.assertIsNone(adapter._last)

    async def test_download_stall_and_fallback_share_original_deadline_without_reset(self):
        async def stall():await asyncio.sleep(1)
        adapter=await self.make([(403,QUOTA),(200,{'data':[{'url':URL}]})],config=replace(FREE,timeout=.025),hook=stall)
        start=asyncio.get_running_loop().time()
        with self.assertRaisesRegex(ImageFailure,'timeout'):await self.generate(adapter)
        self.assertLess(asyncio.get_running_loop().time()-start,.5)
        self.assertEqual(self.models(),[TURBO,PRO]);self.assertIsNone(adapter._last)
        self.assertTrue(self.pools[0].closed)

    async def test_first_model_timeout_or_transport_error_never_tries_pro(self):
        async def stall():await asyncio.sleep(1)
        adapter=await self.make(config=replace(FREE,timeout=.025),api_hook=stall)
        with self.assertRaisesRegex(ImageFailure,'timeout'):await self.generate(adapter)
        self.assertEqual(self.models(),[TURBO]);self.assertEqual(self.downloads,[])
        async def unknown():raise httpx.ConnectError('synthetic network')
        adapter=await self.make(api_hook=unknown)
        with self.assertRaises(ImageFailure):await self.generate(adapter)
        self.assertEqual(self.models(),[TURBO]);self.assertEqual(self.downloads,[])

    async def test_actual_unified_port_returns_png_never_vendor_url(self):
        from backend.v2.companion import UnifiedProviders
        adapter=await self.make();providers=UnifiedProviders(object(),object(),dynamic_images=adapter)
        result=await providers.prepare_dynamic_visual({'kind':'generate_image','asset_id':'cat'},SCOPE,lambda _:True)
        self.assertEqual(result.read_png(),PNG);self.assertEqual(len(providers.image_allowance.attempts),1)
        self.assertNotIn('url',result.__dict__);self.assertNotIn(URL,str(result.__dict__))
        result.release()

    async def test_free_config_explicit_512_only_no_paid_or_translation_model_fallback(self):
        for config in (replace(FREE,free_tier_only=False),replace(FREE,free_tier_only=1),
            replace(FREE,fallback_model='qwen-image-3.0'),replace(FREE,model=PRO,fallback_model=TURBO),
            replace(FREE,model='qwen-mt-image-2.0'),replace(FREE,width=1024)):
            adapter=await self.make(config=config)
            self.assertEqual(adapter.availability(),'configuration');self.assertEqual(self.api,[])
        adapter=await self.make(config=replace(FREE,model=PRO,fallback_model=''))
        result=await self.generate(adapter);result.release();self.assertEqual(self.models(),[PRO])

    async def test_runtime_and_example_require_explicit_free_only_routing_config(self):
        from pathlib import Path
        import tempfile
        from backend.v2.image_runtime import read_image_runtime
        from backend.v2.files import ConfigurationError
        root=Path(__file__).resolve().parents[2]
        config=json.loads((root/'backend/deploy/v2-image-free.example.json').read_text())
        config.update(workspace='synthetic',resource_review_id='synthetic-review-only')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'image.json'
            path.write_text(json.dumps(config));path.chmod(0o600)
            for name in ('dashscope-image-key','dashscope-review-key'):
                key=Path(directory)/name;key.write_text('SYNTHETIC_ONLY');key.chmod(0o600)
            runtime=read_image_runtime(path,directory,'synthetic')
            self.assertEqual((runtime.config.model,runtime.config.fallback_model),(TURBO,PRO))
            self.assertTrue(runtime.config.free_tier_only)
            config.pop('free_tier_only');path.write_text(json.dumps(config))
            with self.assertRaises(ConfigurationError):read_image_runtime(path,directory,'synthetic')

    async def test_scope_revocation_after_quota_close_blocks_pro_and_leaked_result(self):
        adapter=await self.make([(403,QUOTA),(200,{'data':[{'url':URL}]})])
        original=adapter._generate_once;current=[True]
        async def revoke(*args):
            try:return await original(*args)
            finally:current[0]=False
        adapter._generate_once=revoke
        with self.assertRaisesRegex(ImageFailure,'stale'):await adapter.generate('猫',SCOPE,lambda _:current[0])
        self.assertEqual(self.models(),[TURBO]);self.assertEqual(self.downloads,[])

    async def test_png_dimension_or_hash_review_failure_is_terminal_after_output(self):
        from backend.v2.image_bytes import SIGNATURE,chunk
        import struct
        # CRC-correct IHDR with wrong real width, not merely an invalid signature.
        modified=SIGNATURE+chunk(b'IHDR',struct.pack('>IIBBBBB',1024,512,8,2,0,0,0))+RAW[33:]
        adapter=await self.make(png=modified)
        with self.assertRaisesRegex(ImageFailure,'png'):await self.generate(adapter)
        self.assertEqual(self.models(),[TURBO]);self.assertEqual(self.image_count,0)
        adapter=await self.make()
        async def wrong_hash(png,nonce):return ReviewDecision(True,'0'*64,nonce,CONFIG.image_policy)
        adapter._image_reviewer=wrong_hash
        with self.assertRaisesRegex(ImageFailure,'image_review'):await self.generate(adapter)
        self.assertEqual(self.models(),[TURBO]);self.assertIsNone(adapter._last)


class FakeStream:
    def __init__(self):self.closed=False;self.writes=[];self.sni=None
    async def read(self,max_bytes,timeout=None):return b'ok'
    async def write(self,buffer,timeout=None):self.writes.append(buffer)
    async def aclose(self):self.closed=True
    async def start_tls(self,context,server_hostname,timeout):self.sni=server_hostname;return self
    def get_extra_info(self,key):return None


def records(*ips):
    return [(socket.AF_INET6 if ':' in ip else socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',
             (ip,443,0,0) if ':' in ip else (ip,443)) for ip in ips]


class PublicPin(unittest.IsolatedAsyncioTestCase):
    async def test_dns_all_addresses_must_be_public_before_literal_connect(self):
        for ips in (('127.0.0.1',),('10.1.2.3',),('169.254.169.254',),('::1',),('fc00::1',),
                    ('100.64.0.1',),('224.0.0.1',),('2606:4700:4700::1111%eth0',),('::ffff:8.8.8.8',),('8.8.8.8','192.168.1.1')):
            backend=net.PublicOutputBackend(lambda:None);calls=[]
            async def connect(*args):calls.append(args);return FakeStream()
            backend.backend.connect_tcp=connect
            async def resolve(host):return records(*ips)
            with patch('backend.v2.image_download.resolve_output',resolve):
                with self.assertRaises(net.DownloadRejected):await backend.connect_tcp(net.OUTPUT_HOST,443)
            self.assertEqual(calls,[])

    async def test_ip_pinned_once_and_tls_verifies_original_supplier_name(self):
        backend=net.PublicOutputBackend(lambda:None);stream=FakeStream();calls=[]
        async def connect(*args):calls.append(args);return stream
        backend.backend.connect_tcp=connect
        resolved=[]
        async def resolve(host):
            resolved.append(host);return records('8.8.8.8' if len(resolved)==1 else '127.0.0.1')
        with patch('backend.v2.image_download.resolve_output',resolve):
            wrapped=await backend.connect_tcp(net.OUTPUT_HOST,443)
            wrapped=await wrapped.start_tls(ssl.create_default_context(),net.OUTPUT_HOST)
        self.assertEqual(resolved,[net.OUTPUT_HOST])
        self.assertEqual(calls[0][0],'8.8.8.8');self.assertEqual(calls[0][1],443)
        self.assertEqual(stream.sni,net.OUTPUT_HOST)
        await wrapped.aclose();self.assertTrue(stream.closed)
        context=ssl.create_default_context();context.check_hostname=False
        with self.assertRaises(net.DownloadRejected):await wrapped.start_tls(context,net.OUTPUT_HOST)

    async def test_scope_rechecked_after_dns_and_before_stream_io(self):
        current=[True]
        def check():
            if not current[0]:raise ImageFailure('stale')
        backend=net.PublicOutputBackend(check);calls=[]
        async def connect(*args):calls.append(args);return FakeStream()
        backend.backend.connect_tcp=connect
        async def revoke(host):current[0]=False;return records('8.8.8.8')
        with patch('backend.v2.image_download.resolve_output',revoke):
            with self.assertRaises(ImageFailure):await backend.connect_tcp(net.OUTPUT_HOST,443)
        self.assertEqual(calls,[])
        raw=FakeStream();wrapped=net.GuardedStream(raw,check)
        with self.assertRaises(ImageFailure):await wrapped.write(b'GET / HTTP/1.1')
        self.assertEqual(raw.writes,[])
