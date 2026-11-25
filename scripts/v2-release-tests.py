#!/usr/bin/env python3
"""Offline targeted candidate release capability checks; invoke under scripts/with-build-lock."""
import glob,os,subprocess,tempfile,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(group,artifact,version):
 values=list((cache/group/artifact/version).glob('*/*.jar'));assert len(values)==1;return str(values[0])
compiler=[jar('org.jetbrains.kotlin',a,v) for a,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]
compiler+=[jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
runtime=[compiler[1],jar('junit','junit','4.13.2'),jar('org.hamcrest','hamcrest-core','1.3')]
sources=[root/'app/src/main/java/com/littlebuddy/v2/ReleaseCompatibility.kt',root/'app/src/test/java/com/littlebuddy/v2/ReleaseCompatibilityTest.kt']
with tempfile.TemporaryDirectory(dir=root,prefix='image-tests-') as out:
 if '--negative' in sys.argv:
  original=sources[0];mutant=Path(out)/'ReleaseCompatibility.kt'
  mutant.write_text(original.read_text().replace('contract==CONTRACT', 'true'))
  sources[0]=mutant
 subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',out,*map(str,sources)],check=True)
 command=['java','-Xmx256m','-cp',os.pathsep.join([out,*runtime]),'org.junit.runner.JUnitCore','com.littlebuddy.v2.ReleaseCompatibilityTest']
 if '--negative' in sys.argv:
  result=subprocess.run(command,text=True,capture_output=True);print(result.stdout);print(result.stderr)
  assert result.returncode==1 and 'Tests run: 5,  Failures: 1' in result.stdout and 'missingAndUnknownContractAreRejected' in result.stdout
  print('CONTRACT NEGATIVE: mutant compiled; expected original assertions failed (see actual JUnit denominator)')
 else: subprocess.run(command,check=True)
