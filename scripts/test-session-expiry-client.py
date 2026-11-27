#!/usr/bin/env python3
"""Actual current VoiceClient source + compiled dependencies + existing JVM Android/JSON ports over TLS.
Requires prior normal compileV2DebugKotlin. No device/provider or production credentials.
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
 main=ROOT/'app/build/tmp/kotlin-classes/v2Debug'
 assert (main/'com/littlebuddy/v2/VoiceClient.class').is_file(),'compile current V2 first'
 for name in ['SessionTermination','LocalHelpScope','parent/PinDiagnostic']:
  assert (main/('com/littlebuddy/v2/'+name+'.class')).stat().st_mtime_ns >= (ROOT/('app/src/main/java/com/littlebuddy/v2/'+name+'.kt')).stat().st_mtime_ns,'compile matching current dependencies first'
 runtime=[str(main),compiler[1],jar('com.squareup.okhttp3','okhttp','4.12.0'),jar('com.squareup.okio','okio-jvm','3.6.0'),jar('com.google.code.gson','gson','2.11.0'),os.environ['ANDROID_JAR']]
 # Compile the actual current VoiceClient source against the same Kotlin JSON ports.
 # Other production dependencies come from the matching normal Android compile.
 print('PRODUCTION_VOICECLIENT_SOURCE_SHA256',hashlib.sha256((ROOT/'app/src/main/java/com/littlebuddy/v2/VoiceClient.kt').read_bytes()).hexdigest(),flush=True)
 with tempfile.TemporaryDirectory(dir=ROOT,prefix='expiry-tls-') as folder:
  out=Path(folder);ports=ROOT/'scripts/testing/media'
  owner_port=out/'OwnerPorts.kt';owner_port.write_text((ports/'OwnerPorts.kt').read_text().replace('executor.execute(r);return true','executor.execute{try{r.run()}catch(t:Throwable){t.printStackTrace();throw t}};return true'))
  sources=[owner_port]+[ports/(n+'.kt') for n in ['Base64Port','JsonPort','MediaPorts']]+[ROOT/'scripts/testing/session-expiry/RealExpiryClient.kt',ROOT/'app/src/main/java/com/littlebuddy/v2/VoiceClient.kt']
  if '--negative-stale' in os.sys.argv:
   mutant=out/'SessionTermination.kt'
   mutant.write_text((ROOT/'app/src/main/java/com/littlebuddy/v2/SessionTermination.kt').read_text().replace('!blocked && currentScope &&','!blocked &&'))
   sources.append(mutant)
  subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-Xfriend-paths='+str(main),'-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
  subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(out/'key'),'-out',str(out/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  subprocess.run(['keytool','-importcert','-noprompt','-alias','fixture','-file',str(out/'cert'),'-keystore',str(out/'trust.p12'),'-storetype','PKCS12','-storepass','fixture-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(out/'cert',out/'key')
  contract='v2-voice2-safety1-images2-volume1-management1-end1'
  negative='--negative-stale' in os.sys.argv
  for mode in (['stale'] if negative else ['expire','conversation','stale','management','timeout','pump_endpoint']):
   async def peer(ws):
    assert ws.request.headers['Authorization']=='Bearer '+'A'*32
    async def send(kind,**kw):
     event=dict(v=2,type=kind,epoch=0,session='a'*32,turn=0,revision=0);event.update(kw);await ws.send(json.dumps(event))
    try:
     async for raw in ws:
      event=json.loads(raw)
      print('FIXTURE_RECEIVED',mode,event['type'],flush=True)
      if event['type']!='scope':continue
      await send('scope',protocol_contract=contract,management_v=1,state='active')
      if mode=='pump_endpoint':continue
      if mode=='stale':
       await send('scope',session='b'*32,protocol_contract=contract,management_v=1,state='active')
       for kw in [dict(session='a'*32),dict(turn=1),dict(revision=1),dict(epoch=1)]:
        fields=dict(session='b'*32);fields.update(kw)
        await send('session_end',reason='session_expired',**fields)
       await send('thinking_wait')
       await send('session_end',reason='session_expired',session='b'*32)
      elif mode=='timeout':await send('failure',code='timeout')
      elif mode=='management':
       await send('session_end',reason='session_expired');await send('failure',code='timeout')
      else:
       reason='conversation_ended' if mode=='conversation' else 'session_expired'
       await send('session_end',reason=reason);await send('session_end',reason=reason)
      await ws.close();return
    except Exception as e:
     from websockets.exceptions import ConnectionClosed
     if not isinstance(e,ConnectionClosed):raise
   async with serve(peer,'127.0.0.1',0,ssl=tls) as server:
    port=server.sockets[0].getsockname()[1]
    process=await asyncio.create_subprocess_exec('java','-Xmx256m','-Djavax.net.ssl.trustStore='+str(out/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=fixture-only','-cp',os.pathsep.join([str(out/'classes'),*runtime]),'com.littlebuddy.v2.RealExpiryClientKt',f'wss://localhost:{port}/v2/voice',mode)
    try: assert await asyncio.wait_for(process.wait(),10)==0,mode
    finally:
     if process.returncode is None:
      process.kill();await process.wait()
 print('REAL_CLIENT_TLS 6/6 scenarios (includes actual ENDPOINT_TICK failure); JVM Android ports, no device claims',flush=True)
asyncio.run(run())
