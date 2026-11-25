#!/usr/bin/env python3
"""Production provider/core/Grant against immutable PR65 actual authenticated TLS receiver.
Only synthetic material; no persistent service, SSH/device or supplier calls.
"""
import asyncio,os,ssl,subprocess,tempfile,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(group,name,version):
    values=list((CACHE/group/name/version).glob('*/*.jar'));assert len(values)==1;return str(values[0])
def compile_client(out):
    compiler=[jar('org.jetbrains.kotlin',a,v) for a,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),
        ('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]
    compiler += [jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
    runtime=[compiler[1],jar('com.squareup.okhttp3','okhttp','4.12.0'),jar('com.squareup.okio','okio-jvm','3.6.0'),
             jar('com.google.code.gson','gson','2.11.0')]
    android=os.environ.get('ANDROID_JAR')
    assert android and Path(android).is_file(),'ANDROID_JAR must point at the already approved SDK'
    runtime.append(android)
    base=ROOT/'app/src/main/java/com/littlebuddy/v2'
    names=['Contracts','FeedbackKeys','FeedbackCore','FeedbackAuthority','Vault','FeedbackWireProvider','FeedbackJson']
    sources=[base/'feedback'/(n+'.kt') for n in names]
    sources += [base/'parent'/(n+'.kt') for n in ['ParentDomain','ParentCodec','ParentEnvelope','ParentCommit','ParentConfiguration']]
    sources += list((ROOT/'scripts/testing/feedback').glob('*.kt'))
    subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
        '-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
    return os.pathsep.join([str(out/'classes'),*runtime])

async def run():
    backend=Path(os.environ['FEEDBACK_BACKEND_SOURCE']).resolve()
    expected=os.environ.get('FEEDBACK_BACKEND_SHA','98762add2596194cff48213c873172fbd589bf6f')
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=backend,text=True).strip()==expected
    assert subprocess.check_output(['git','status','--porcelain'],cwd=backend,text=True)==''
    sys.path.insert(0,str(backend))
    from backend.v2.feedback_store import FeedbackStore
    from backend.v2.feedback_receiver import FeedbackReceiver
    from backend.v2.server import voice_server
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='feedback-tls-') as directory:
        out=Path(directory);cp=compile_client(out)
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(out/'key'),'-out',str(out/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['keytool','-importcert','-noprompt','-alias','fixture','-file',str(out/'cert'),'-keystore',str(out/'trust.p12'),'-storetype','PKCS12','-storepass','fixture-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(out/'cert',out/'key')
        cases=os.environ.get('FEEDBACK_CASES','normal,logs,false,timeout,revoke,reply-revoke,binding').split(',')
        for mode in cases:
            store=FeedbackStore(out/(mode+'.sqlite'));device=hashlib.sha256(('A'*32).encode()).hexdigest()
            receiver=FeedbackReceiver(store,device,copies_reviewed=mode!='false');requests=[]
            original=receiver.request
            def observed(raw):
                event=json.loads(raw);requests.append((event['operation'],event['id'],event.get('logs','')))
                result=original(raw)
                if event['operation']=='submit' and result['ok']:store.maintain(device,event['id'],reply='synthetic reply')
                return result
            receiver.request=observed
            class Route:
                async def run(self,socket):
                    if mode=='revoke':await asyncio.sleep(.4)
                    class Wire:
                        def __aiter__(self):return socket.__aiter__()
                        async def send(self,text):
                            value=json.loads(text)
                            if mode in {'timeout','binding'} and value.get('request') and requests[-1][0]=='submit':
                                await socket.wait_closed();return
                            if mode=='reply-revoke' and value.get('request') and requests[-1][0]=='read':
                                await socket.wait_closed();return
                            await socket.send(text)
                    await receiver.run(Wire())
            async with voice_server('127.0.0.1',0,tls,'A'*32,object(),object(),feedback=Route()) as server:
                port=server.sockets[0].getsockname()[1]
                proc=await asyncio.create_subprocess_exec('java','-Xmx256m','-Djavax.net.ssl.trustStore='+str(out/'trust.p12'),'-Djavax.net.ssl.trustStorePassword=fixture-only','-cp',cp,'com.littlebuddy.v2.feedback.FeedbackClientKt',f'wss://localhost:{port}/v2/feedback',mode,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                stdout,stderr=await asyncio.wait_for(proc.communicate(),20)
            text=stdout.decode()+stderr.decode();print(text,flush=True)
            assert proc.returncode==0 and f'FEEDBACK_TLS {mode} PASS' in text, (mode,[(op,len(logs)) for op,key,logs in requests])
            submits=[x for x in requests if x[0]=='submit'];withdraws=[x for x in requests if x[0]=='withdraw']
            assert len(submits)==(0 if mode=='revoke' else 1)
            if mode=='logs':assert len(submits[0][2])>0
            elif submits:assert submits[0][2]==''
            if mode not in {'revoke','binding'}:assert len(withdraws)==1 and withdraws[0][1]==submits[0][1]
            else:assert not withdraws
            store.close()
        print(f'FEEDBACK_TLS_NORMAL: {len(cases)}/{len(cases)} fail0 skip0; fixed backend '+expected+'; no device/cloud/material submission')
if __name__=='__main__':asyncio.run(run())
