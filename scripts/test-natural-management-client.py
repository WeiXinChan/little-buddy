#!/usr/bin/env python3
"""Actual VoiceClient and production server over TLS; no receive injection or device/media APIs."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
from unittest.mock import patch
from backend.v2.server import voice_server
from backend.v2.companion import UnifiedProviders,CompanionPolicy
from backend.v2.voice import VoicePeer
from tests.v2.test_natural_management import Speech,Model

ROOT=Path(__file__).resolve().parents[1]
CACHE=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(group,name,version):
    values=list((CACHE/group/name/version).glob('*/*.jar'));assert len(values)==1;return str(values[0])
def compile_client(out,negative):
    compiler=[jar('org.jetbrains.kotlin',a,v) for a,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),
        ('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]
    compiler += [jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
    runtime=[compiler[1],jar('com.squareup.okhttp3','okhttp','4.12.0'),jar('com.squareup.okio','okio-jvm','3.6.0'),
             jar('com.google.code.gson','gson','2.11.0')]
    android=os.environ.get('ANDROID_JAR')
    assert android and Path(android).is_file(),'ANDROID_JAR must point at the already approved SDK'
    runtime.append(android)
    base=ROOT/'app/src/main/java/com/littlebuddy/v2'
    names=['VoiceClient','InputGate','Playback','NativeEvidence','AndroidTrack','ManagementState','ManagementEntryGate',
           'ReleaseCompatibility','LocalHelpScope','ImageGate']
    parent=['ParentDomain','ParentCodec','ParentEnvelope','ParentCommit','ParentPanelModel','ParentConfiguration']
    sources=[base/(n+'.kt') for n in names]+[base/'parent'/(n+'.kt') for n in parent]
    sources+=list((ROOT/'scripts/testing/entry').glob('*.kt'))
    if negative:
        original=base/'VoiceClient.kt';mutant=out/'VoiceClient.kt'
        text=original.read_text();needle='        helpScope.bind(scope.session,scope.turn,scope.epoch,scope.revision)'
        assert needle in text;mutant.write_text(text.replace(needle,'        // negative: normal help scope omitted'))
        sources[sources.index(original)]=mutant
    subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
        '-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
    return os.pathsep.join([str(out/'classes'),*runtime])

async def run():
    negative='--negative' in __import__('sys').argv
    late='--late' in __import__('sys').argv
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='entry-client-') as folder:
        out=Path(folder);cp=compile_client(out,negative)
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1',
            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(out/'key'),
            '-out',str(out/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['keytool','-importcert','-noprompt','-alias','fixture','-file',str(out/'cert'),'-keystore',
            str(out/'trust.p12'),'-storetype','PKCS12','-storepass','fixture-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(out/'cert',out/'key')
        events=[];snapshots=[];original=VoicePeer.send;speech=Speech();model=Model()
        async def observed(peer,kind,**fields):
            events.append(kind)
            if kind in {'scope','management','management_state'}:
                snapshots.append(dict(kind=kind,session=peer.session.session,turn=peer.session.turn,
                    epoch=peer.epoch,revision=peer.revision,expires=peer.session.expires,state=fields.get('state')))
            return await original(peer,kind,**fields)
        with patch.object(VoicePeer,'send',observed):
            async with voice_server('127.0.0.1',0,tls,'A'*32,UnifiedProviders(speech,model),CompanionPolicy()) as server:
                port=server.sockets[0].getsockname()[1]
                process=await asyncio.create_subprocess_exec('java','-Xmx256m','-Djavax.net.ssl.trustStore='+str(out/'trust.p12'),
                    '-Djavax.net.ssl.trustStorePassword=fixture-only','-cp',cp,'com.littlebuddy.v2.RealClientKt',
                    f'wss://localhost:{port}/v2/voice',*(['late'] if late else []),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                stdout,stderr=await asyncio.wait_for(process.communicate(),20)
        text=stdout.decode()+stderr.decode();print(text)
        if negative:
            assert process.returncode==1 and 'natural management entry did not reach waiting_wake' in text
            assert 'management' in events
            print('PREBIND NEGATIVE: compiled actual client; 1 real TLS case, 1 expected assertion failure; no device')
        elif late:
            assert process.returncode==0 and 'REAL_CLIENT late_entry_rejected=1 pages=0 grants=0' in text
            assert 'management' in events and 'management_state' not in events
            print('REAL_TLS_LATE: 1/1, failure0, skip0; actual new input invalidates queued entry without opening a page')
        else:
            assert process.returncode==0 and 'REAL_CLIENT ready=1 natural_entry=1' in text
            assert speech.bytes>0 and speech.syntheses==0 and len(model.calls)==1
            assert not any(e in events for e in ('open','bound','audio','reply_end'))
            entered=next(i for i,e in enumerate(snapshots) if e['kind']=='management')
            assert snapshots[entered-1]['kind']=='scope'
            scope=snapshots[entered];paused=next(e for e in snapshots if e['state']=='paused')
            waiting=next(e for e in snapshots if e['state']=='waiting_wake')
            assert scope['session']==paused['session']==waiting['session']
            assert scope['expires']==paused['expires']==waiting['expires']
            assert (paused['epoch'],waiting['epoch'])==(scope['epoch']+1,scope['epoch']+2)
            print('REAL_TLS_NORMAL: 1/1, failure0, skip0; production ASR/semantic/seal/client/model-cancel/resume; synthetic providers/JVM Android ports')

if __name__=='__main__':asyncio.run(run())
