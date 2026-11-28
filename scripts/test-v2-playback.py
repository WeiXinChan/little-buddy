#!/usr/bin/env python3
"""Offline production Playback synthetic FIFO replay; no device or network."""
import os,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(g,a,v):return str(next((cache/g/a/v).glob('*/*.jar')))
compiler=[jar('org.jetbrains.kotlin',a,v) for a,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]+[jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
runtime=[compiler[1],jar('junit','junit','4.13.2'),jar('org.hamcrest','hamcrest-core','1.3')]
sources=[root/'app/src/main/java/com/littlebuddy/v2'/ (n+'.kt') for n in ['Playback','NativeEvidence']]
if os.environ.get('PLAYBACK_SOURCE'):
 sources[0]=Path(os.environ['PLAYBACK_SOURCE'])
sources += [root/'app/src/main/java/com/littlebuddy/v2/Turns.kt']
sources += [root/'app/src/test/java/com/littlebuddy/v2'/(n+'.kt') for n in ['PlaybackFifoTest','PlaybackTest','LocalClarificationTest']]
with tempfile.TemporaryDirectory(dir=root,prefix='playback-tests-') as out:
 subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',out,*map(str,sources)],check=True)
 subprocess.run(['java','-Xmx256m','-cp',os.pathsep.join([out,*runtime]),'org.junit.runner.JUnitCore','com.littlebuddy.v2.PlaybackFifoTest','com.littlebuddy.v2.PlaybackTest','com.littlebuddy.v2.LocalClarificationTest'],check=True)
