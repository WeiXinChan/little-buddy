"""Checked V2-only loopback listener. No V1 defaults, deployment or secret output."""
import argparse
import asyncio
import json
import signal
import socket
import os
import time
import sys
from backend.v2.preflight import prepare
from backend.v2.files import ConfigurationError


def event(code):
    print(json.dumps(dict(service='little-buddy-v2',event=code)),file=sys.stderr,flush=True)


def notify_ready():
    address=os.environ.get('NOTIFY_SOCKET')
    if not address:return
    if address.startswith('@'):address='\0'+address[1:]
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as notifier:
            notifier.connect(address);notifier.sendall(b'READY=1')
    except OSError:raise ConfigurationError('readiness_notify_failed') from None


async def serve_checked(args,prepared,*,stop=None,ready=None):
    from backend.dashscope import http_client
    from backend.v2.speech import V2Speech
    from backend.v2.companion import CompanionPolicy,DashScopeModel,UnifiedProviders
    from backend.v2.server import voice_server
    from backend.v2.files import disable_core_dumps
    from backend.v2.image_runtime import configured_images
    from backend.v2.feedback_receiver import configured_feedback
    disable_core_dumps()
    observation=None
    if getattr(args,'observe_failures',False):
        from backend.v2.failure_observer import FailureWindow,journal_sink
        observation=FailureWindow(journal_sink)
    stop=stop or asyncio.Event()
    loop=asyncio.get_running_loop();installed=[]
    try:
        for sig in (signal.SIGTERM,signal.SIGINT):
            loop.add_signal_handler(sig,stop.set);installed.append(sig)
        async with http_client() as http:
            if time.time()>=prepared.expires_at:raise ConfigurationError('v2_device_scope_expired')
            speech=V2Speech(http,key=prepared.provider_key,**prepared.config)
            async with configured_images(http,getattr(prepared,'images',None)) as images, \
                       configured_feedback(getattr(prepared,'feedback',None),prepared.token) as feedback:
                bundle=UnifiedProviders(speech,DashScopeModel(speech),dynamic_images=images)
                async with voice_server('127.0.0.1',args.port,prepared.tls,prepared.token,bundle,
                                        CompanionPolicy(),expires_at=prepared.expires_at,feedback=feedback,failure_observation=observation,
                                        stream_asr=getattr(args,'stream_asr',False),animal_cards_enabled=getattr(args,'animal_cards',False)) as server:
                    notify_ready()
                    event('ready_loopback')
                    if ready is not None:ready.set_result(server.sockets[0].getsockname()[1])
                    await stop.wait()
    finally:
        for sig in installed:loop.remove_signal_handler(sig)
        event('stopped')


def parser():
    result=argparse.ArgumentParser()
    for name in ('cert','key','token-file','device-scope','ca-file','tls-name','service-env',
                 'credential-directory','apk-contract'):
        result.add_argument('--'+name,required=True)
    result.add_argument('--animal-cards',action='store_true',help='Use the fixed reviewed animal card catalogue for exact game turns')
    result.add_argument('--stream-asr',action='store_true',help='Opt-in first-expression ASR prestream; default off, no client/wire change')
    result.add_argument('--observe-failures',action='store_true',help='Opt-in V2 namespace metadata: 15 minutes, at most 4 peers/16 failures; no content')
    result.add_argument('--port',type=int,default=19483)
    result.add_argument('--check',action='store_true',help='Offline only; never listens or calls providers')
    result.add_argument('--image-config',help='Explicit protected image configuration; omitted means disabled')
    result.add_argument('--feedback-database',help='Explicit private self-hosted issue database; omitted means disabled')
    result.add_argument('--feedback-copies-policy',help='Operator-reviewed single-store retention policy, not an owner grant')
    return result


def cli(argv=None):
    try:
        args=parser().parse_args(argv);checked=prepare(args)
        if args.check:
            print(json.dumps(checked.report,ensure_ascii=False));return 0
        asyncio.run(serve_checked(args,checked));return 0
    except ConfigurationError as failure:
        event(str(failure));return 2
    except (Exception,KeyboardInterrupt):
        event('startup_or_shutdown_failed');return 2


if __name__=='__main__':raise SystemExit(cli())
