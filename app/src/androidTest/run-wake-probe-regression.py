#!/usr/bin/env python3
"""Offline test-only failure regressions; execute under scripts/with-build-lock."""
from pathlib import Path
import subprocess,os,tempfile,json
root=Path(__file__).resolve().parents[3]
cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(g,a,v):return str(next((cache/g/a/v).glob('*/*.jar')))
compiler=[jar('org.jetbrains.kotlin',a,v) for a,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]+[jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
runtime=[compiler[1],jar('junit','junit','4.13.2'),jar('org.hamcrest','hamcrest-core','1.3')]
base=root/'app/src/androidTest/java/com/littlebuddy'
with tempfile.TemporaryDirectory(dir=root,prefix='native-probe-tests-') as out:
 subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',out,*[str(base/(n+'.kt')) for n in ['NativeProbeSafety','NativeProbeWindow','WakeFixtureKernel','WakeFixtureKernelTest']],str(root/'app/src/main/java/com/littlebuddy/v2/RecorderLease.kt')],check=True)
 result=subprocess.run(['java','-Xmx256m','-Dwake.repo='+str(root),'-cp',os.pathsep.join([out,*runtime]),'org.junit.runner.JUnitCore','com.littlebuddy.WakeFixtureKernelTest'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 print(result.stdout,end='');assert 'PRIVATE_SYNTHETIC_MESSAGE' not in result.stdout
 result.check_returncode()
