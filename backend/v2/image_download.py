"""Isolated, pinned public-network retrieval for one documented supplier output host.

No shared HTTP client, ambient proxy, bearer, cookies, arbitrary OSS or redirects.
Lease checks cover async I/O; the owning adapter sanitizes all external failures.
"""
import asyncio
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlsplit

import httpcore
from backend.v2.image_bytes import MAX_PNG

OUTPUT_HOST='dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com'


class DownloadRejected(ValueError):
    def __init__(self):super().__init__('output_rejected')


def validated_url(value):
    if (not isinstance(value,str) or not 1<=len(value)<=4096 or not value.isascii() or
        any(ord(c)<=32 or ord(c)==127 for c in value) or '#' in value):raise DownloadRejected()
    try:
        parsed=urlsplit(value)
        if (parsed.scheme!='https' or parsed.netloc not in {OUTPUT_HOST,OUTPUT_HOST+':443'} or
            parsed.hostname!=OUTPUT_HOST or parsed.port not in (None,443) or parsed.username is not None or
            parsed.password is not None or parsed.fragment or
            not re.fullmatch(r'/[A-Za-z0-9_./-]+\.png',parsed.path) or
            any(p in {'','..','.'} for p in parsed.path.split('/')[1:])):raise DownloadRejected()
    except (ValueError,UnicodeError):raise DownloadRejected() from None
    return value


async def resolve_output(host):
    return await asyncio.get_running_loop().getaddrinfo(host,443,type=socket.SOCK_STREAM,proto=socket.IPPROTO_TCP)


def public_addresses(records):
    if not records or len(records)>16:raise DownloadRejected()
    addresses=[]
    for family,kind,protocol,canonical,address in records:
        if family not in (socket.AF_INET,socket.AF_INET6) or kind!=socket.SOCK_STREAM or protocol!=socket.IPPROTO_TCP:
            raise DownloadRejected()
        if '%' in address[0] or address[1]!=443 or len(address)>2 and address[3]!=0:raise DownloadRejected()
        ip=ipaddress.ip_address(address[0])
        if (family==socket.AF_INET)!=(ip.version==4):raise DownloadRejected()
        if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified or
            ip.is_loopback or ip.is_link_local or
            # is_global alone classifies deprecated fec0::/10 as global on Python 3.12.
            (ip.version==6 and (ip.is_site_local or ip.ipv4_mapped or ip.sixtofour or ip.teredo))):raise DownloadRejected()
        if str(ip) not in addresses:addresses.append(str(ip))
    return sorted(addresses,key=lambda address:ipaddress.ip_address(address).version)


class GuardedStream(httpcore.AsyncNetworkStream):
    def __init__(self,stream,check):self.stream=stream;self.check=check
    async def read(self,max_bytes,timeout=None):
        self.check();value=await self.stream.read(max_bytes,timeout);self.check();return value
    async def write(self,buffer,timeout=None):
        self.check();await self.stream.write(buffer,timeout);self.check()
    async def aclose(self):await self.stream.aclose()
    async def start_tls(self,ssl_context,server_hostname=None,timeout=None):
        if (server_hostname!=OUTPUT_HOST or ssl_context.verify_mode!=ssl.CERT_REQUIRED or
            not ssl_context.check_hostname):raise DownloadRejected()
        self.check();stream=await self.stream.start_tls(ssl_context,server_hostname,timeout)
        try:self.check()
        except BaseException:
            await stream.aclose();raise
        return GuardedStream(stream,self.check)
    def get_extra_info(self,info):return self.stream.get_extra_info(info)


class PublicOutputBackend(httpcore.AsyncNetworkBackend):
    def __init__(self,check):self.check=check;self.backend=httpcore.AnyIOBackend()
    async def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        if host!=OUTPUT_HOST or port!=443 or local_address is not None:raise DownloadRejected()
        self.check();records=await resolve_output(host);self.check()
        addresses=public_addresses(records);self.check()
        # Connect once to a checked literal IP. DNS cannot change the target
        # after validation; httpcore retains original-host SNI/cert verification.
        stream=await self.backend.connect_tcp(addresses[0],443,timeout,None,socket_options)
        try:self.check()
        except BaseException:
            await stream.aclose();raise
        return GuardedStream(stream,self.check)


async def download_png(url,check):
    url=validated_url(url);body=bytearray()
    try:
        check()
        async with httpcore.AsyncConnectionPool(ssl_context=ssl.create_default_context(),proxy=None,
            max_connections=1,max_keepalive_connections=0,retries=0,http1=True,http2=False,
            network_backend=PublicOutputBackend(check)) as pool:
            check()
            async with pool.stream('GET',url,headers=[(b'Accept',b'image/png'),
                (b'Accept-Encoding',b'identity'),(b'Connection',b'close')],
                extensions={'timeout':{name:4. for name in ('connect','read','write','pool')}}) as response:
                check()
                headers={}
                for name,value in response.headers:headers.setdefault(name.lower(),[]).append(value)
                if (response.status!=200 or headers.get(b'content-type')!=[b'image/png'] or
                    headers.get(b'content-encoding',[b'identity'])!=[b'identity']):raise DownloadRejected()
                lengths=headers.get(b'content-length',[])
                if lengths and (len(lengths)!=1 or not lengths[0].isdigit() or len(lengths[0])>10 or
                                int(lengths[0])>MAX_PNG):raise DownloadRejected()
                async for block in response.aiter_stream():
                    check()
                    if len(body)+len(block)>MAX_PNG:raise DownloadRejected()
                    body.extend(block)
                if lengths and len(body)!=int(lengths[0]):raise DownloadRejected()
                check()
            check()
        check();return bytes(body)
    finally:
        body[:]=b'\0'*len(body);body.clear()
