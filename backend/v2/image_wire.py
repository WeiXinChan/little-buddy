"""One short-lived public image; no URLs, files, identity or renewable retention."""
import asyncio
import base64
from hashlib import sha256
from backend.v2.image_bytes import MAX_PNG, checked_png
from backend.v2.dynamic_images import GeneratedImage, ImageFailure

CHUNK_BYTES=8192
MAX_RETAIN=15.


class PublicImage:
    def __init__(self, metadata, *, session, connection, topic, seconds, png=None):
        self.metadata=dict(metadata);self.session=session;self.connection=connection;self.topic=topic
        self.png=bytearray(png or b'');self.released=False;self.visible_until=0.
        self.deadline=asyncio.get_running_loop().time()+min(MAX_RETAIN,max(0.,seconds))
        self.timer=asyncio.get_running_loop().call_at(self.deadline,self.release)

    @classmethod
    def generated(cls,image,scope,asset_id,connection):
        if type(image) is not GeneratedImage or image.scope!=scope:raise ImageFailure('payload')
        png=image.read_png()
        if (len(png)>MAX_PNG or sha256(png).hexdigest()!=image.sha256 or
            checked_png(png,image.width,image.height)!=png):raise ImageFailure('png')
        return cls(dict(asset_id=asset_id,image_id=image.image_id,sha256=image.sha256,
                        width=image.width,height=image.height,source='dynamic',fallback_reason=None),
                   session=scope.session,connection=connection,topic=scope.topic,
                   seconds=image.remaining_seconds(),png=png)

    def remaining(self):
        return max(0.,self.deadline-asyncio.get_running_loop().time()) if not self.released else 0.

    def fields(self):
        return dict(image_v=2,**self.metadata,retain_ms=int(self.remaining()*1000))

    def packets(self):
        if self.released or not self.png:raise ImageFailure('released')
        for index,offset in enumerate(range(0,len(self.png),CHUNK_BYTES)):
            if self.released:raise ImageFailure('released')
            yield dict(index=index,offset=offset,data=base64.b64encode(self.png[offset:offset+CHUNK_BYTES]).decode())

    def display(self,action,seconds):
        now=asyncio.get_running_loop().time()
        target=max(now,self.visible_until)+seconds if action=='extend' else now+seconds
        self.visible_until=min(self.deadline,target)
        return max(0,int((self.visible_until-now)*1000))

    def release(self):
        if not self.released:
            self.released=True;self.timer.cancel();self.png[:]=b'\0'*len(self.png);self.png.clear()
