#!/usr/bin/env python3
"""Actual current VoiceClient source + compiled dependencies + existing JVM Android/JSON ports over TLS.
Requires matching unchanged production dependencies from normal compileV2DebugKotlin (UNKNOWN_INPUT_CLASSES optional). All changed classes are compiled from current source. No device/provider/production credentials.
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
 main=Path(os.environ.get('UNKNOWN_INPUT_CLASSES',str(ROOT/'app/build/tmp/kotlin-classes/v2Debug'))).resolve()
 assert (main/'com/littlebuddy/v2/VoiceClient.class').is_file(),'compile current V2 first'
 runtime=[str(main),compiler[1],jar('com.squareup.okhttp3','okhttp','4.12.0'),jar('com.squareup.okio','okio-jvm','3.6.0'),jar('com.google.code.gson','gson','2.11.0'),os.environ['ANDROID_JAR']]
 # Compile the actual current VoiceClient source against the same Kotlin JSON ports.
 # Other production dependencies come from the matching normal Android compile.
 print('WORKTREE_VOICECLIENT_SOURCE_SHA256',hashlib.sha256((ROOT/'app/src/main/java/com/littlebuddy/v2/VoiceClient.kt').read_bytes()).hexdigest(),flush=True)
 with tempfile.TemporaryDirectory(dir=ROOT,prefix='expiry-tls-') as folder:
  out=Path(folder);ports=ROOT/'scripts/testing/media'
  owner_port=out/'OwnerPorts.kt';owner_port.write_text((ports/'OwnerPorts.kt').read_text().replace('executor.execute(r);return true','if(executor.isShutdown)return false;return try{executor.execute{try{r.run()}catch(t:Throwable){t.printStackTrace();throw t}};true}catch(_:RejectedExecutionException){false}'))
  text=owner_port.read_text().replace('object SystemClock {@JvmStatic fun elapsedRealtime()=System.nanoTime()/1_000_000}', 'object SystemClock {@JvmField var now=100000L;@JvmStatic fun elapsedRealtime()=now;@JvmStatic fun advance(ms:Long){now+=ms}}')
  owner_port.write_text(text)
  media=out/'MediaPorts.kt';media.write_text((ports/'MediaPorts.kt').read_text().replace('val instances=','@JvmField var releaseFails=false;val instances=').replace('fun release(){state=0}','fun release(){if(releaseFails)error("fixture release");state=0}').replace('fun addOnRoutingChangedListener(l:AudioRouting.OnRoutingChangedListener,h:android.os.Handler){}','var savedRoute:AudioRouting.OnRoutingChangedListener?=null;fun addOnRoutingChangedListener(l:AudioRouting.OnRoutingChangedListener,h:android.os.Handler){savedRoute=l}').replace('override val routedDevice=AudioDeviceInfo()','override var routedDevice=AudioDeviceInfo()').replace('val instances=','@JvmField var advanceOnBuild=false;val instances=').replace('fun build()=AudioTrack()','fun build():AudioTrack{if(advanceOnBuild){advanceOnBuild=false;android.os.SystemClock.advance(15001)};return AudioTrack()}'))
  sources=[owner_port]+[media]+[ports/(n+'.kt') for n in ['Base64Port','JsonPort']]+[ROOT/'scripts/testing/unknown-input/RealUnknownClient.kt']
  sources += [ROOT/'app/src/main/java/com/littlebuddy/v2'/(n+'.kt') for n in ['VoiceClient','InputGate','AndroidTrack','ClientPhases','Playback','OutputSlot']]
  sources += [ROOT/'app/src/main/java/com/littlebuddy/v2/parent/PinDiagnostic.kt']
  capture=ROOT/'scripts/testing/capture'
  sources=[p for p in sources if p.name!='RealUnknownClient.kt']
  sources += [ROOT/'scripts/testing/recovery/RealRecoveryClient.kt']
  sources += [capture/(n+'.kt') for n in ['Assets','Aec','Android','AbsoluteWake']]
  wake=out/'WakePort.kt';wake.write_text((capture/'Wake.kt').read_text().replace('val detectedSpeechInRead=true;fun accept(a:ShortArray,n:Int) {}','val detectedSpeechInRead get()=android.media.AudioRecord.capturedFrames<8000;fun accept(a:ShortArray,n:Int) {}'));sources += [wake]
  audio=out/'AudioRecordPort.kt';audio.write_text((capture/'Audio.kt').read_text().replace('object AudioFormat {const val CHANNEL_IN_MONO=1;const val ENCODING_PCM_16BIT=2}',''))
  sources += [audio]
  media.write_text(media.read_text().replace('const val CHANNEL_OUT_MONO=1;','const val CHANNEL_IN_MONO=1;const val CHANNEL_OUT_MONO=1;'))
  owner_port.write_text(owner_port.read_text().replace('object SystemClock {@JvmField var now=100000L;@JvmStatic fun elapsedRealtime()=now;@JvmStatic fun advance(ms:Long){now+=ms}}', 'object SystemClock {@JvmField var realtime=true;@JvmField var manualNow=100000L;@JvmStatic fun elapsedRealtime()=if(realtime)System.nanoTime()/1_000_000 else manualNow;@JvmStatic fun uptimeMillis()=elapsedRealtime();@JvmStatic fun advance(ms:Long){manualNow+=ms}}'))
  sources += [ROOT/'app/src/main/java/com/littlebuddy/v2'/(n+'.kt') for n in ['Capture','CaptureSessionPort','RecoveryHandoff','RecoveryEpisode','CaptureUploads','RecorderLease','WakeSamples','NativeReadLedger','CaptureBootstrap','CaptureClockEnvelope','CaptureClockFailure','CaptureMonotonic','WakeOrigin','NativeEvidence']]
  subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-Xfriend-paths='+str(main),'-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
  subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(out/'key'),'-out',str(out/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  subprocess.run(['keytool','-importcert','-noprompt','-alias','fixture','-file',str(out/'cert'),'-keystore',str(out/'trust.p12'),'-storetype','PKCS12','-storepass','fixture-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(out/'cert',out/'key')
  for mode in ['success','slow','stale_scope','quota','auth','timeout','safety','unknown']:
   connections=[];wire=[]
   async def peer(ws):
    index=len(connections);connections.append(index);epoch=0;revision=0;count=0;player=None;session=('a' if index==0 else 'b')*32
    async def send(kind,**kw):
     event=dict(v=2,type=kind,epoch=epoch,session=session,turn=0,revision=revision);event.update(kw);await ws.send(json.dumps(event))
    try:
     async for raw in ws:
      event=json.loads(raw);kind=event['type'];wire.append((index,kind))
      if kind=='scope':
       if index==1 and mode=='slow':await asyncio.sleep(2.6)
       await send('scope',protocol_contract='v2-voice2-safety1-images2-volume1-management1-end1',management_v=1,state='active')
      elif kind=='wake' and index==0:pass
      elif kind=='advance':
       revision=event['revision']
      elif kind=='input':count+=1
      elif kind=='probe':
       if index==0:await send('failure',code=(mode if mode in ('quota','auth','timeout','safety') else 'synthetic_unknown' if mode=='unknown' else 'voice'),**({'revision':9} if mode=='stale_scope' else {}))
       else:await send('endpoint',completion='complete')
      elif kind=='seal':await send('decision',meaning='new_turn',intent='fixture')
      elif kind=='stop':epoch=event['epoch'];await send('open')
      elif kind=='bind':
       player=event['player'];await send('bound',player=player,stream=1,identity=dict(session=session,turn=0))
       import base64
       await send('audio',player=player,stream=1,segment='fixed',start=0,end=480,pcm=base64.b64encode(bytes(960)).decode())
      elif kind=='ack' and event['head']==480:await send('reply_end',head=480,public_facts=0)
    except Exception as e:
     from websockets.exceptions import ConnectionClosed
     if not isinstance(e,ConnectionClosed):raise
   async with serve(peer,'127.0.0.1',0,ssl=tls) as server:
    port=server.sockets[0].getsockname()[1]
    process=await asyncio.create_subprocess_exec('java','-Xmx256m','-Djavax.net.ssl.trustStore='+str(out/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=fixture-only','-cp',os.pathsep.join([str(out/'classes'),*runtime]),'com.littlebuddy.v2.RealRecoveryClientKt',f'wss://localhost:{port}/v2/voice',mode)
    try:
     code=await asyncio.wait_for(process.wait(),12)
     if code:
      from collections import Counter
      print('RECOVERY_WIRE_COUNTS',Counter(wire),flush=True)
     assert code==0,mode
    finally:
     if process.returncode is None:process.kill();await process.wait()
   assert len(connections)==(2 if mode in ('success','slow') else 1),connections
   assert not any(i==0 and k=='ack' for i,k in wire),'failed generation ACK'
   print('RECOVERY_PEER',mode,'connections',len(connections),'PASS',flush=True)
asyncio.run(run())
