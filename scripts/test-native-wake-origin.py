#!/usr/bin/env python3
"""Runs under with-build-lock. Source-patched host JNI is a prerequisite; no devices/providers."""
from pathlib import Path
import os,subprocess,tempfile,hashlib
ROOT=Path(__file__).resolve().parents[1];CACHE=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(g,n,v):return str(next((CACHE/g/n/v).glob('*/*.jar')))
compiler=[jar('org.jetbrains.kotlin',n,v) for n,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]+[jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
fixtures=Path('/home/ubuntu/tech/v2-delivery/mac-code29-diagnostics/synthetic-wake.aiff')
assert hashlib.sha256(fixtures.read_bytes()).hexdigest()=='04d5cacf970e6c3e2620d7959c8c0ecb6e68d0483824f54e39da17442611c255','fixed regenerated synthetic fixture only'
lib=Path(os.environ['WALI_KWS_HOST_LIB']).resolve();assert lib.name=='libwali-v2-kws.so'
print('HOST_NATIVE_SHA256',hashlib.sha256(lib.read_bytes()).hexdigest(),flush=True)
with tempfile.TemporaryDirectory(dir=ROOT,prefix='native-wake-replay-') as folder:
 out=Path(folder)
 import zipfile
 with zipfile.ZipFile(ROOT/'app/libs/sherpa-onnx-1.12.27.aar') as z:(out/'sherpa.jar').write_bytes(z.read('classes.jar'))
 runtime=[compiler[1],str(out/'sherpa.jar')]
 sources=list((ROOT/'scripts/testing/wake-origin').glob('*.kt'))
 sources+=[ROOT/'app/src/main/java/com/littlebuddy'/f'{n}.kt' for n in ['WakeReader','SpeechDetector']]
 sources+=[ROOT/'app/src/main/java/com/littlebuddy/v2'/f'{n}.kt' for n in ['AbsoluteWake','V2WakeFiles','KeywordTail','InputGate']]
 subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',str(out/'classes'),*map(str,sources)],check=True)
 pcm=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(fixtures),'-ac','1','-ar','16000','-f','s16le','pipe:1'],timeout=15)
 assert len(pcm)==13747*2
 subprocess.run(['java','-Xmx256m','-Djava.library.path='+str(lib.parent),'-cp',os.pathsep.join([str(out/'classes'),*runtime]),'com.littlebuddy.v2.NativeOriginReplayKt',str(ROOT/'app/src/main/assets'),str(out/'models')],input=pcm,check=True,timeout=130)
