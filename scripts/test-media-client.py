#!/usr/bin/env python3
"""Real TLS frames into production VoiceClient/Playback/AndroidTrack/AndroidImageRoute.
Server is a hostile protocol fixture, Android objects are JVM ports. No cloud/device claims.
"""
import asyncio,os,ssl,subprocess,tempfile,json,base64,hashlib,struct,zlib
from pathlib import Path
from websockets.asyncio.server import serve
ROOT=Path(__file__).resolve().parents[1]
CACHE=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(group,name,version):
    values=list((CACHE/group/name/version).glob('*/*.jar'));assert len(values)==1;return str(values[0])
def compile_client(out,negative,timer_negative=False):
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
           'ReleaseCompatibility','LocalHelpScope','ImageGate','ChildVolume','PngAssembly','AndroidImageRoute']
    parent=['ParentDomain','ParentCodec','ParentEnvelope','ParentCommit','ParentPanelModel','ParentConfiguration']
    sources=[base/(n+'.kt') for n in names]+[base/'parent'/(n+'.kt') for n in parent]
    sources+=list((ROOT/'scripts/testing/media').glob('*.kt'))
    if negative:
        path=out/'AndroidTrack.kt';path.write_text((base/'AndroidTrack.kt').read_text().replace('return muted || track.setVolume(percent/100f)==AudioTrack.SUCCESS','return track.setVolume(percent/100f)==AudioTrack.SUCCESS'))
        sources=[path if p.name=='AndroidTrack.kt' else p for p in sources]
    if timer_negative:
        path=out/'AndroidImageRoute.kt'
        path.write_bytes(subprocess.check_output(['git','show','61b78aac44bacda0b3256acaab88fe15e4f1eed0:app/src/main/java/com/littlebuddy/v2/AndroidImageRoute.kt'],cwd=ROOT))
        sources=[path if p.name=='AndroidImageRoute.kt' else p for p in sources]
    subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
        '-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
    return os.pathsep.join([str(out/'classes'),*runtime])

def png():
    def chunk(k,d):return struct.pack('>I',len(d))+k+d+struct.pack('>I',zlib.crc32(k+d)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',512,512,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(bytes((512*4+1)*512)))+chunk(b'IEND',b'')
async def run():
    negative='--negative' in os.sys.argv;timer_negative='--negative-timer' in os.sys.argv
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='media-tls-') as directory:
        out=Path(directory);cp=compile_client(out,negative,timer_negative)
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(out/'key'),'-out',str(out/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['keytool','-importcert','-noprompt','-alias','fixture','-file',str(out/'cert'),'-keystore',str(out/'trust.p12'),'-storetype','PKCS12','-storepass','fixture-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(out/'cert',out/'key')
        contract='v2-voice2-safety1-images2-volume1-management1-end1';session='a'*32;data=png()
        async def peer(ws):
            assert ws.request.headers['Authorization']=='Bearer '+'A'*32
            revision=0;stage=0;player=None
            async def send(kind,**body):await ws.send(json.dumps(dict(v=2,type=kind,epoch=0,session=session,turn=0,revision=revision,**body)))
            async for raw in ws:
                event=json.loads(raw);kind=event['type']
                if kind=='scope':await send('scope',protocol_contract=contract,management_v=1,state='active')
                elif kind=='advance':revision=event['revision']
                elif kind=='input' and stage==0:
                    stage=1;await send('scope',protocol_contract=contract,management_v=1,state='active')
                    await send('endpoint',completion='complete');await send('open')
                elif kind=='bind':
                    assert event['features']==['images_v2'] and event['image_contract']==contract
                    player=event['player'];stream=stage
                    await send('bound',player=player,stream=stream,identity=dict(session=session,turn=0))
                    fields=dict(image_v=2,topic=1,token='b'*32,asset_id='dragon',image_id='c'*32,sha256=hashlib.sha256(data).hexdigest(),width=512,height=512,source='dynamic')
                    if stage==1:
                        await send('image_begin',**fields,bytes=len(data),chunks=1,chunk_bytes=8192,encoding='base64',retain_ms=15000)
                        await send('image_chunk',**fields,index=0,offset=0,data=base64.b64encode(data).decode())
                        await send('image_ready',**fields,retain_ms=14999)
                        await send('image_display',**fields,action='display',duration_ms=6000,retain_ms=14999,player=player,stream=stream,segment='last',end=240)
                        await asyncio.sleep(.3) # test privacy before an actual played head/ACK
                    await send('audio',player=player,stream=stream,segment='last',start=0,end=240,pcm=base64.b64encode(bytes(480)).decode())
                    await send('reply_end',head=240,public_facts=0)
                elif kind=='ack' and stage==1:
                    if event['head']!=240:continue
                    fields=dict(image_v=2,topic=1,token='b'*32,asset_id='dragon',image_id='c'*32,sha256=hashlib.sha256(data).hexdigest(),width=512,height=512,source='dynamic')
                    await send('image_display',**fields,action='display',duration_ms=6000,retain_ms=14500,player=player,stream=1,segment='last',end=240)
                    await send('volume',control_v=1,direction='down',token='e'*32)
                    await send('volume',control_v=1,direction='up',token='e'*32)
                elif kind=='input' and stage==1 and revision==2:
                    stage=2;await send('scope',protocol_contract=contract,management_v=1,state='active')
                    await send('volume',control_v=1,direction='down',token='f'*32)
                    await asyncio.sleep(.2);await send('revoke');await send('open')
        async with serve(peer,'127.0.0.1',0,ssl=tls) as server:
            port=server.sockets[0].getsockname()[1]
            process=await asyncio.create_subprocess_exec('java','-Xmx256m','-Djavax.net.ssl.trustStore='+str(out/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=fixture-only','-cp',cp,'com.littlebuddy.v2.MediaClientKt',f'wss://localhost:{port}/v2/voice',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            stdout,stderr=await asyncio.wait_for(process.communicate(),18)
        text=stdout.decode()+stderr.decode();print(text)
        if negative:
            assert process.returncode==1 and 'volume unmuted track' in text
            print('MUTE_NEGATIVE: 1 expected original assertion failure; actual production adapter compiled')
        elif timer_negative:
            assert process.returncode==1 and 'empty image route kept background timer' in text
            print('TIMER_NEGATIVE: frozen old head61b78aa actual route compiled; 1 expected original assertion failure')
        else:
            assert process.returncode==0 and 'MEDIA_TLS volume_pipeline=1' in text
            print('MEDIA_TLS_NORMAL: 1/1 failure0 skip0; real authenticated loopback TLS; protocol fixture/native JVM ports')
if __name__=='__main__':asyncio.run(run())
