"""Explicitly reviewed Qwen synchronous PNG adapter. Disabled unless separately configured.

No authority is inferred from the speech key. Reviewers are trusted injected ports;
their production policy/service and the account's image permission remain external.
"""
import asyncio
import base64
from dataclasses import dataclass,field
from hashlib import sha256
import json
import math
import re
import httpx
from uuid import uuid4

from backend.v2.image_bytes import MAX_PNG,checked_png

MAX_BODY=3*1024*1024
CANCEL_SECONDS=.3


class ImageFailure(ValueError):
    def __init__(self,reason):
        if reason not in {'disabled','configuration','unreviewed','unavailable','busy','quarantined','prompt',
                          'prompt_review','image_review','payload','png','upstream','timeout','stale','released'}:
            raise ValueError('image failure code')
        self.reason=reason;super().__init__(reason)


@dataclass(frozen=True)
class ImageScope:
    session:str
    turn:int
    epoch:int
    revision:int
    topic:int

    def __post_init__(self):
        if (not isinstance(self.session,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',self.session) or
            any(type(v) is not int or v<0 for v in (self.turn,self.epoch,self.revision,self.topic))):
            raise ImageFailure('configuration')


@dataclass(frozen=True)
class ImageConfig:
    enabled:bool=False
    region:str=''
    workspace:str=field(default='',repr=False)
    model:str=''
    resource_review_id:str=''
    prompt_policy:str=''
    image_policy:str=''
    width:int=512
    height:int=512
    timeout:float=8.
    result_ttl:float=15.


@dataclass(frozen=True)
class ReviewDecision:
    approved:bool
    content_sha256:str
    nonce:str
    policy:str


class GeneratedImage:
    """Single bounded buffer. read_png rechecks owner scope; release/expiry clears it.

    Caller-owned immutable copies and Python allocator memory are not physical-wipe
    guarantees. Consumers must not persist/copy beyond their own media lifetime.
    """
    def __init__(self,png,scope,config,guard):
        self._scope=scope;self.width=config.width;self.height=config.height
        self._sha256=sha256(png).hexdigest();self._image_id=uuid4().hex
        self._png=bytearray(png);self._guard=guard;self._released=False
        self._timer=asyncio.get_running_loop().call_later(config.result_ttl,self.release)

    def read_png(self):
        if self._released:raise ImageFailure('released')
        try:self._guard()
        except BaseException:
            self.release();raise
        return bytes(self._png)

    def remaining_seconds(self):
        return max(0.,self._timer.when()-asyncio.get_running_loop().time()) if not self._released else 0.

    def release(self):
        if not self._released:
            self._released=True;self._timer.cancel()
            self._png[:]=b'\0'*len(self._png);self._png.clear();self._guard=None
            self._scope=None;self._sha256='';self._image_id=''

    @property
    def released(self):return self._released

    @property
    def scope(self):return self._scope

    @property
    def sha256(self):return self._sha256

    @property
    def image_id(self):return self._image_id


@dataclass
class _Lease:
    scope:ImageScope
    serial:int
    current:object=field(repr=False)
    deadline:float
    revoked:bool=False


def _object(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('duplicate field')
        result[key]=value
    return result


class QwenImages:
    def __init__(self,http=None,*,config=None,api_key=None,prompt_reviewer=None,image_reviewer=None):
        self.http=http;self.config=config or ImageConfig();self._key=api_key
        self._prompt_reviewer=prompt_reviewer;self._image_reviewer=image_reviewer
        self._task=None;self._lease=None;self._serial=0;self._last=None;self.quarantined=False;self._closed=False

    def availability(self):
        c=self.config
        if self._closed:return 'unavailable'
        if type(c) is not ImageConfig:return 'configuration'
        if c.enabled is False:return 'disabled'
        if (c.enabled is not True or not isinstance(c.model,str) or not isinstance(c.workspace,str) or
            c.region!='cn-beijing' or c.model not in {'qwen-image-3.0','qwen-image-3.0-pro'} or
            not re.fullmatch('[A-Za-z0-9][A-Za-z0-9-]{0,62}',c.workspace) or
            any(type(n) is not int or not 512<=n<=2048 for n in (c.width,c.height)) or
            type(c.timeout) not in (int,float) or not math.isfinite(c.timeout) or not 0<c.timeout<=15 or
            type(c.result_ttl) not in (int,float) or not math.isfinite(c.result_ttl) or not 0<c.result_ttl<=30):return 'configuration'
        if any(not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,80}',v)
               for v in (c.resource_review_id,c.prompt_policy,c.image_policy)):return 'unreviewed'
        if self._prompt_reviewer is None or self._image_reviewer is None:return 'unreviewed'
        if (self.http is None or not isinstance(self._key,str) or not 1<=len(self._key)<=4096 or
            not self._key.isascii() or any(ch.isspace() for ch in self._key)):return 'unavailable'
        return 'quarantined' if self.quarantined else 'configured'

    def _check(self,lease,*,deadline=True):
        if lease.revoked or lease.serial!=self._serial:raise ImageFailure('stale')
        try:current=lease.current(lease.scope)
        except Exception:current=False
        if current is not True:
            lease.revoked=True;raise ImageFailure('stale')
        if deadline and asyncio.get_running_loop().time()>=lease.deadline:raise ImageFailure('timeout')

    def _reviewed(self,decision,content,nonce,policy):
        return (type(decision) is ReviewDecision and decision.approved is True and
                decision.content_sha256==sha256(content).hexdigest() and decision.nonce==nonce and decision.policy==policy)

    async def _drain(self,task,lease):
        lease.revoked=True
        if not task.done():task.cancel()
        try:done,_=await asyncio.wait({task},timeout=CANCEL_SECONDS)
        except asyncio.CancelledError:
            self.quarantined=True
            if not task.done():task.cancel()
            raise
        if not done:self.quarantined=True
        if done and not task.cancelled():
            try:
                result=task.result()
                if isinstance(result,GeneratedImage):result.release()
            except Exception:pass

    def cancel(self,scope):
        matched=False
        if self._lease is not None and self._lease.scope==scope:
            matched=True;self._lease.revoked=True
            if self._task is not None and not self._task.done():self._task.cancel()
        if self._last is not None and self._last.scope==scope:self._last.release();matched=True
        return matched

    async def aclose(self):
        self._closed=True
        if self._last is not None:self._last.release();self._last=None
        if self._task is not None:
            await self._drain(self._task,self._lease)
            if self._task.done():self._task=self._lease=None

    async def generate(self,description,scope,is_current):
        state=self.availability()
        if state!='configured':raise ImageFailure(state)
        if not isinstance(scope,ImageScope) or not callable(is_current):raise ImageFailure('configuration')
        if (not isinstance(description,str) or not description.strip() or len(description)>160 or
            len(description.encode())>480 or any(ord(ch)<32 for ch in description)):
            raise ImageFailure('prompt')
        if self._task is not None:raise ImageFailure('busy')
        if self._last is not None:self._last.release();self._last=None
        self._serial+=1
        lease=_Lease(scope,self._serial,is_current,asyncio.get_running_loop().time()+self.config.timeout)
        self._check(lease)
        task=asyncio.create_task(self._generate(description,lease));self._task=task;self._lease=lease
        def finished(done):
            if not done.cancelled():
                try:
                    result=done.result()
                    if lease.revoked and isinstance(result,GeneratedImage):result.release()
                except Exception:pass
        task.add_done_callback(finished)
        try:
            done,_=await asyncio.wait({task},timeout=max(0,lease.deadline-asyncio.get_running_loop().time()))
            if not done:
                await self._drain(task,lease);raise ImageFailure('timeout')
            result=task.result()
            try:self._check(lease)
            except BaseException:result.release();raise
            self._last=result;return result
        except asyncio.CancelledError:
            await self._drain(task,lease)
            raise
        finally:
            if task.done() and self._task is task:self._task=self._lease=None

    async def _generate(self,description,lease):
        body=bytearray();candidate=None
        try:
            self._check(lease);nonce=uuid4().hex
            decision=await self._prompt_reviewer(description,nonce)
            self._check(lease)
            if not self._reviewed(decision,description.encode(),nonce,self.config.prompt_policy):raise ImageFailure('prompt_review')
            endpoint=f'https://{self.config.workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/images/generations'
            payload=dict(model=self.config.model,prompt=description,size=f'{self.config.width}x{self.config.height}',
                         n=1,response_format='b64_json',prompt_extend=False,enable_thinking=False)
            self._check(lease)
            # A standalone Request avoids inheriting chat cookies, default query
            # params or identity-bearing client headers. No arbitrary response URL.
            request=httpx.Request('POST',endpoint,json=payload,headers={'Authorization':'Bearer '+self._key,
                'Accept-Encoding':'identity'},extensions={'timeout':{k:self.config.timeout for k in ('connect','read','write','pool')}})
            response=await self.http.send(request,stream=True,auth=None,follow_redirects=False)
            try:
                self._check(lease)
                if response.status_code!=200:raise ImageFailure('upstream')
                if (response.headers.get('content-type','').split(';')[0]!='application/json' or
                    response.headers.get('content-encoding','identity')!='identity'):raise ImageFailure('payload')
                lengths=response.headers.get_list('content-length')
                if lengths and (len(lengths)!=1 or not lengths[0].isdigit() or len(lengths[0])>10 or int(lengths[0])>MAX_BODY):
                    raise ImageFailure('payload')
                async for block in response.aiter_raw(chunk_size=16384):
                    self._check(lease)
                    if len(body)+len(block)>MAX_BODY:raise ImageFailure('payload')
                    body.extend(block)
            finally:await response.aclose()
            self._check(lease)
            data=json.loads(body,object_pairs_hook=_object,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if (not isinstance(data,dict) or set(data)-{'created','data','usage'} or not isinstance(data.get('data'),list) or
                len(data['data'])!=1 or not isinstance(data['data'][0],dict) or set(data['data'][0])!={'b64_json'}):
                raise ImageFailure('payload')
            encoded=data['data'][0]['b64_json']
            if not isinstance(encoded,str) or not encoded.isascii() or len(encoded)>4*((MAX_PNG+2)//3):raise ImageFailure('payload')
            decoded=base64.b64decode(encoded,validate=True)
            if base64.b64encode(decoded).decode()!=encoded:raise ImageFailure('payload')
            try:png=checked_png(decoded,self.config.width,self.config.height)
            except (ValueError,OverflowError):raise ImageFailure('png') from None
            del data,encoded,decoded
            body[:]=b'\0'*len(body);body.clear()
            self._check(lease);nonce=uuid4().hex
            decision=await self._image_reviewer(png,nonce)
            self._check(lease)
            if not self._reviewed(decision,png,nonce,self.config.image_policy):raise ImageFailure('image_review')
            candidate=GeneratedImage(png,lease.scope,self.config,lambda:self._check(lease,deadline=False))
            return candidate
        except asyncio.CancelledError:raise
        except ImageFailure:raise
        except Exception:raise ImageFailure('upstream') from None
        finally:
            body[:]=b'\0'*len(body);body.clear()
