"""Authenticated loopback synthetic no-application-reply fixture for R97-04.

No ASR/model calls. TLS validation is mandatory at the actual VoiceClient.
"""
import argparse
import asyncio
import hmac
from http import HTTPStatus
import logging
from pathlib import Path
import ssl
from websockets.asyncio.server import serve

async def main(args):
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert,args.key)
    token=Path(args.token_file).read_text().strip()
    if not token.isascii() or not token.isalnum() or not 32<=len(token)<=256:
        raise ValueError('fixture credential')
    async def authenticate(socket,request):
        values=request.headers.get_all('Authorization')
        if request.path!='/v2/voice' or len(values)!=1 or not hmac.compare_digest(values[0], 'Bearer '+token):
            return socket.respond(HTTPStatus.UNAUTHORIZED,'unauthorized\n')
    async def handler(socket):
        async for frame in socket:
            pass  # Intentionally no application decision/open/placeholder/heartbeat.
    logger=logging.Logger('v2-blackhole');logger.addHandler(logging.NullHandler())
    async with serve(handler,'127.0.0.1',args.port,ssl=tls,process_request=authenticate,
                     max_size=16000,max_queue=4,logger=logger):
        await asyncio.Event().wait()

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--cert',required=True);p.add_argument('--key',required=True)
    p.add_argument('--token-file',required=True);p.add_argument('--port',type=int,default=19484)
    asyncio.run(main(p.parse_args()))
