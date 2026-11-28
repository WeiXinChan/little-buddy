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
  sources += [ROOT/'app/src/main/java/com/littlebuddy/v2'/(n+'.kt') for n in ['VoiceClient','InputGate','AndroidTrack','ClientPhases','Playback']]
  sources += [ROOT/'app/src/main/java/com/littlebuddy/v2/parent/PinDiagnostic.kt']
  baseline='--baseline' in os.sys.argv or '--negative' in os.sys.argv
  if baseline:
   for n in ['VoiceClient','InputGate','ClientPhases']:
    frozen=out/(n+'.kt');frozen.write_bytes(subprocess.check_output(['git','show','650cbc859d2bd546cc710d7119fbdf895e32abee:app/src/main/java/com/littlebuddy/v2/'+n+'.kt'],cwd=ROOT))
    sources=[frozen if p.name==n+'.kt' else p for p in sources]
   driver=out/'RealUnknownClient.kt';driver.write_bytes(subprocess.check_output(['git','show','19215a5de3f8ac2e1ca43639e510e32735530085:scripts/testing/unknown-input/RealUnknownClient.kt'],cwd=ROOT))
   sources=[driver if p.name=='RealUnknownClient.kt' else p for p in sources]
   print('BASELINE_SOURCE 650cbc859d2bd546cc710d7119fbdf895e32abee',flush=True)
  chosen=next(p for p in sources if p.name=='VoiceClient.kt');print('SELECTED_VOICECLIENT_SOURCE_SHA256',hashlib.sha256(chosen.read_bytes()).hexdigest(),flush=True)
  subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-Xfriend-paths='+str(main),'-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
  subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(out/'key'),'-out',str(out/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  subprocess.run(['keytool','-importcert','-noprompt','-alias','fixture','-file',str(out/'cert'),'-keystore',str(out/'trust.p12'),'-storetype','PKCS12','-storepass','fixture-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(out/'cert',out/'key')
  contract='v2-voice2-safety1-images2-volume1-management1-end1'
  modes=['unknown'] if baseline else ['unknown','unknown_complete','empty','incomplete','thinking','stop','noise','stale_epoch','stale_revision','stale_new_input','expired','management','cancel','provider','release_failure','late_bound','local_input','local_candidate','local_management','local_close','local_background','local_release_failure','asset_late','local_duplicate','local_route_late','local_route_active','bare_interrupted','track_late']
  if os.environ.get('UNKNOWN_CASE'):
   assert os.environ['UNKNOWN_CASE'] in modes;modes=[os.environ['UNKNOWN_CASE']]
  for mode in modes:
   peer_errors=[];peer_facts=[]
   async def peer(ws):
    revision=0;epoch=0;stream=0;prepared=False;resolved=False;solo_ended=False;old_acks=0
    async def send(kind,**kw):
     event=dict(v=2,type=kind,epoch=epoch,session='a'*32,turn=0,revision=revision);event.update(kw);await ws.send(json.dumps(event))
    try:
     async for raw in ws:
      event=json.loads(raw);kind=event['type']
      if kind=='scope':await send('scope',protocol_contract=contract,management_v=1,state='active')
      elif kind=='advance':revision=event['revision']
      elif kind=='wake_solo':await send('open')
      elif kind=='bind':
       stream+=1;player=event['player']
       await send('bound',player=player,stream=stream,identity=dict(session='a'*32,turn=0))
       if stream==2 and mode=='late_bound':await send('decision',meaning='unknown',intent='')
       if mode=='bare_interrupted' and stream==1:continue
       import base64
       pcm=base64.b64encode(bytes(480)).decode()
       await send('audio',player=player,stream=stream,segment='fixed',start=0,end=240,pcm=pcm)
       await send('audio',player=player,stream=stream,segment='fixed',start=240,end=480,pcm=pcm)
      elif kind=='ack':
       if resolved and event['stream']==1:old_acks+=1
       if event['head']==480:
        solo_ended=True;await send('reply_end',head=480,public_facts=0)
      elif kind=='probe':
       if revision>=2 and mode not in {'stale_new_input'}:await send('endpoint',completion='complete');continue
       if mode in {'incomplete','thinking','unknown_complete','late_bound'}:
        await send('endpoint',completion='complete' if mode in {'unknown_complete','late_bound'} else mode)
       elif mode=='provider':await send('failure',code='voice')
       else:
        meaning='noise' if mode=='noise' else 'stop' if mode=='stop' else 'unknown'
        fields={}
        if mode=='stale_epoch':fields['epoch']=epoch+1
        if mode=='stale_revision':fields['revision']=revision-1
        resolved=True;await send('decision',meaning=meaning,intent='',**fields)
       await send('thinking_wait')
      elif kind=='seal':
       if revision==1 and mode=='unknown_complete':resolved=True;await send('decision',meaning='unknown',intent='');await send('thinking_wait')
       else:prepared=True;await send('decision',meaning='new_turn',intent='fixed-next')
      elif kind=='stop':
       epoch=event['epoch']
       if prepared:prepared=False;await send('open')
       else:
        if mode=='local_duplicate' and resolved:
         await send('decision',meaning='unknown',intent='');await send('decision',meaning='unknown',intent='')
        await send('thinking_wait')
      elif kind=='resume_noise':await send('thinking_wait')
    except Exception as e:
     from websockets.exceptions import ConnectionClosed
     if not isinstance(e,ConnectionClosed):peer_errors.append(type(e).__name__);raise
    finally:
     peer_facts.append(dict(old_acks_after_resolution=old_acks))
     if mode in {'unknown','unknown_complete','empty'} and old_acks!=0:peer_errors.append('OLD_STREAM_ACK')
   async with serve(peer,'127.0.0.1',0,ssl=tls) as server:
    port=server.sockets[0].getsockname()[1]
    process=await asyncio.create_subprocess_exec('java','-Xmx256m','-Djavax.net.ssl.trustStore='+str(out/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=fixture-only','-cp',os.pathsep.join([str(out/'classes'),*runtime]),'com.littlebuddy.v2.RealUnknownClientKt',f'wss://localhost:{port}/v2/voice',mode)
    try: assert await asyncio.wait_for(process.wait(),8)==0,mode
    finally:
     if process.returncode is None:
      process.kill();await process.wait()
   assert not peer_errors and len(peer_facts)==1,(mode,'peer/ACK proof failed')
   print('UNKNOWN_PEER mode='+mode+' old_acks_after_resolution='+str(peer_facts[0]['old_acks_after_resolution']),flush=True)
 print('UNKNOWN_TLS complete; controlled BOOT jumps retain production15s; no provider/phone/model',flush=True)
asyncio.run(run())
