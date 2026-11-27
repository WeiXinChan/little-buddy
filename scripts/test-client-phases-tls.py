#!/usr/bin/env python3
"""Actual current VoiceClient source + compiled dependencies + existing JVM Android/JSON ports over TLS.
Requires matching unchanged production dependencies from normal compileV2DebugKotlin (CLIENT_PHASE_CLASSES optional). All changed classes are compiled from current source. No device/provider/production credentials.
Run under scripts/with-build-lock. Temporary self-signed key never enters app resources.
"""
import asyncio,os,ssl,subprocess,tempfile,json,hashlib
from pathlib import Path
from websockets.asyncio.server import serve
ROOT=Path(__file__).resolve().parents[1]
CACHE=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(g,n,v):return str(next((CACHE/g/n/v).glob('*/*.jar')))
async def run():
 compiler=[jar('org.jetbrains.kotlin',n,v) for n,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]+[jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
 main=Path(os.environ.get('CLIENT_PHASE_CLASSES',str(ROOT/'app/build/tmp/kotlin-classes/v2Debug'))).resolve()
 assert (main/'com/littlebuddy/v2/VoiceClient.class').is_file(),'compile current V2 first'
 runtime=[str(main),compiler[1],jar('com.squareup.okhttp3','okhttp','4.12.0'),jar('com.squareup.okio','okio-jvm','3.6.0'),jar('com.google.code.gson','gson','2.11.0'),os.environ['ANDROID_JAR']]
 # Compile the actual current VoiceClient source against the same Kotlin JSON ports.
 # Other production dependencies come from the matching normal Android compile.
 print('PRODUCTION_VOICECLIENT_SOURCE_SHA256',hashlib.sha256((ROOT/'app/src/main/java/com/littlebuddy/v2/VoiceClient.kt').read_bytes()).hexdigest(),flush=True)
 with tempfile.TemporaryDirectory(dir=ROOT,prefix='expiry-tls-') as folder:
  out=Path(folder);ports=ROOT/'scripts/testing/media'
  owner_port=out/'OwnerPorts.kt';owner_port.write_text((ports/'OwnerPorts.kt').read_text().replace('executor.execute(r);return true','executor.execute{try{r.run()}catch(t:Throwable){t.printStackTrace();throw t}};return true'))
  sources=[owner_port]+[ports/(n+'.kt') for n in ['Base64Port','JsonPort','MediaPorts']]+[ROOT/'scripts/testing/client-phases/RealPhaseClient.kt']
  sources += [ROOT/'app/src/main/java/com/littlebuddy/v2'/(n+'.kt') for n in ['VoiceClient','InputGate','AndroidTrack','ClientPhases']]
  sources += [ROOT/'app/src/main/java/com/littlebuddy/v2/parent/PinDiagnostic.kt']
  subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-Xfriend-paths='+str(main),'-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
  subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(out/'key'),'-out',str(out/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  subprocess.run(['keytool','-importcert','-noprompt','-alias','fixture','-file',str(out/'cert'),'-keystore',str(out/'trust.p12'),'-storetype','PKCS12','-storepass','fixture-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(out/'cert',out/'key')
  contract='v2-voice2-safety1-images2-volume1-management1-end1'
  for mode in ['on','off']:
   async def peer(ws):
    revision=0
    async def send(kind,**kw):
     event=dict(v=2,type=kind,epoch=0,session='a'*32,turn=0,revision=revision);event.update(kw);await ws.send(json.dumps(event))
    try:
     async for raw in ws:
      event=json.loads(raw);kind=event['type']
      if kind=='scope':await send('scope',protocol_contract=contract,management_v=1,state='active')
      elif kind=='advance':revision=event['revision']
      elif kind=='probe':
       await send('endpoint',revision=0,completion='complete');await send('endpoint',completion='complete')
      elif kind=='seal':await send('open')
      elif kind=='bind':
       player=event['player']
       await send('bound',player=player,stream=1,identity=dict(session='a'*32,turn=0))
       import base64
       pcm=base64.b64encode(bytes(480)).decode()
       await send('audio',player=player,stream=777,segment='fixed',start=0,end=240,pcm=pcm)
       await send('audio',epoch=1,player=player,stream=1,segment='fixed',start=0,end=240,pcm=pcm)
       await send('audio',player=player,stream=1,segment='fixed',start=0,end=240,pcm=pcm)
       await send('audio',player=player,stream=1,segment='fixed',start=240,end=480,pcm=pcm)
    except Exception as e:
     from websockets.exceptions import ConnectionClosed
     if not isinstance(e,ConnectionClosed):raise
   async with serve(peer,'127.0.0.1',0,ssl=tls) as server:
    port=server.sockets[0].getsockname()[1]
    process=await asyncio.create_subprocess_exec('java','-Xmx256m','-Djavax.net.ssl.trustStore='+str(out/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=fixture-only','-cp',os.pathsep.join([str(out/'classes'),*runtime]),'com.littlebuddy.v2.RealPhaseClientKt',f'wss://localhost:{port}/v2/voice',mode)
    try: assert await asyncio.wait_for(process.wait(),10)==0,mode
    finally:
     if process.returncode is None:
      process.kill();await process.wait()
 print('REAL_PHASE_TLS 2/2: actual source, JVM platform ports, no recorder/model/provider/device',flush=True)
asyncio.run(run())
