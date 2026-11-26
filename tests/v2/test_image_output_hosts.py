"""Real httpcore/h11, synthetic network streams: no DNS, TLS or cloud traffic."""
import ssl
import unittest
from unittest.mock import patch
from backend.v2 import image_download as net
from tests.v2.test_free_image_routing import records
from tests.v2.test_dynamic_images import RAW

HOSTS=sorted(net.OUTPUT_HOSTS)

class Wire:
    def __init__(self,status=200,location=None):
        self.written=bytearray();self.tls=[];self.closed=False
        headers=b'Content-Type: image/png\r\nContent-Length: '+str(len(RAW)).encode()+b'\r\n'
        if location:headers+=b'Location: '+location.encode()+b'\r\n'
        self.response=b'HTTP/1.1 '+str(status).encode()+b' Test\r\n'+headers+b'Connection: close\r\n\r\n'+RAW
    async def read(self,max_bytes,timeout=None):
        block=self.response[:max_bytes];self.response=self.response[max_bytes:];return block
    async def write(self,buffer,timeout=None):self.written.extend(buffer)
    async def aclose(self):self.closed=True
    async def start_tls(self,context,server_hostname=None,timeout=None):
        self.tls.append((server_hostname,context.verify_mode,context.check_hostname));return self
    def get_extra_info(self,info):return None

class OutputHosts(unittest.IsolatedAsyncioTestCase):
    async def download(self,host,*,status=200,location=None,ips=('8.8.8.8',)):
        self.wire=Wire(status,location);self.lookups=[];self.connects=[]
        async def resolve(value):self.lookups.append(value);return records(*ips)
        owner=self
        class Backend:
            async def connect_tcp(self,*args):owner.connects.append(args);return owner.wire
        with patch.object(net,'resolve_output',resolve),patch.object(net.httpcore,'AnyIOBackend',Backend):
            return await net.download_png('https://'+host+'/fixture/image.png?signature=SYNTHETIC',lambda:None)

    async def test_both_hosts_real_h11_host_sni_literal_pin_and_isolated_headers(self):
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(await self.download(host),RAW)
                self.assertEqual(self.lookups,[host]);self.assertEqual(self.connects[0][:2],('8.8.8.8',443))
                self.assertEqual(self.wire.tls,[(host,ssl.CERT_REQUIRED,True)])
                lines=bytes(self.wire.written).split(b'\r\n')
                self.assertIn(b'Host: '+host.encode(),lines)
                self.assertEqual(sum(line.lower().startswith(b'host:') for line in lines),1)
                self.assertFalse(any(b'authorization:' in line.lower() or b'cookie:' in line.lower() for line in lines))
                self.assertTrue(self.wire.closed)

    async def test_cross_host_sni_rejected_even_when_other_host_trusted(self):
        for host,other in (HOSTS,HOSTS[::-1]):
            wire=Wire();stream=net.GuardedStream(wire,lambda:None,host)
            with self.assertRaises(net.DownloadRejected):await stream.start_tls(ssl.create_default_context(),other)
            self.assertEqual(wire.tls,[])

    async def test_cross_host_connect_rejected_before_dns(self):
        for host,other in (HOSTS,HOSTS[::-1]):
            with patch.object(net,'resolve_output') as resolver:
                with self.assertRaises(net.DownloadRejected):await net.PublicOutputBackend(lambda:None,host).connect_tcp(other,443)
                resolver.assert_not_called()

    async def test_redirect_to_other_trusted_host_still_rejected_without_second_request(self):
        for host,other in (HOSTS,HOSTS[::-1]):
            with self.assertRaises(net.DownloadRejected):await self.download(host,status=302,location='https://'+other+'/x.png')
            self.assertEqual(self.lookups,[host]);self.assertEqual(len(self.connects),1);self.assertTrue(self.wire.closed)

    async def test_both_hosts_mixed_private_and_site_local_dns_fail_closed(self):
        for host in HOSTS:
            for bad in ('127.0.0.1','10.0.0.1','fec0::1','feff:ffff::1'):
                with self.subTest(host=host,bad=bad):
                    with self.assertRaises(net.DownloadRejected):await self.download(host,ips=('8.8.8.8',bad))
                    self.assertEqual(self.connects,[])

    async def test_exact_authority_only_no_suffix_userinfo_or_other_oss(self):
        for host in HOSTS:
            for authority in (host+'.evil.test',host+'@evil.test','user@'+host,host+':444',host.upper()):
                with self.subTest(authority=authority):
                    with self.assertRaises(net.DownloadRejected):net.validated_url('https://'+authority+'/x.png')
            self.assertEqual(net.validated_url('https://'+host+':443/x.png'),'https://'+host+':443/x.png')
        with self.assertRaises(net.DownloadRejected):net.validated_url('https://dashscope-other.oss-accelerate.aliyuncs.com/x.png')

    async def test_tls_verification_cannot_be_disabled_for_either_host(self):
        for host in HOSTS:
            context=ssl._create_unverified_context();wire=Wire()
            with self.assertRaises(net.DownloadRejected):await net.GuardedStream(wire,lambda:None,host).start_tls(context,host)
            self.assertEqual(wire.tls,[])
