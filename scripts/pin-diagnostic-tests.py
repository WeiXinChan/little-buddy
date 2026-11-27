#!/usr/bin/env python3
"""Offline targeted owner/config/help checks; invoke under scripts/with-build-lock."""
import glob,os,subprocess,tempfile,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(group,artifact,version):
 values=list((cache/group/artifact/version).glob('*/*.jar'));assert len(values)==1;return str(values[0])
compiler=[jar('org.jetbrains.kotlin',a,v) for a,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]
compiler+=[jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
runtime=[compiler[1],jar('junit','junit','4.13.2'),jar('org.hamcrest','hamcrest-core','1.3')]
parent=root/'app/src/main/java/com/littlebuddy/v2/parent'
names=['ParentDomain.kt','ParentCodec.kt','ParentEnvelope.kt','ParentCommit.kt','ParentPanelModel.kt','ParentConfiguration.kt','OwnerReceipt.kt']
sources=[parent/p for p in names]+[parent/'PinDiagnostic.kt',root/'app/src/test/java/com/littlebuddy/v2/parent/PinDiagnosticTest.kt']
regression='--regression' in sys.argv
if regression:
 sources[-1]=root/'docs/testing/pin-init/fixtures/OwnerTickRegressionTest.kt'
with tempfile.TemporaryDirectory(dir=root,prefix='pin-tests-') as out:
 if '--original' in sys.argv:
  for i,source in enumerate(sources):
   if source.parent==parent and source.name!='PinDiagnostic.kt':
    original=Path(out)/source.name
    original.write_bytes(subprocess.check_output(['git','show','cf187d4d35490726e3ce996c6cbe3df678a65a67:'+source.relative_to(root).as_posix()],cwd=root))
    sources[i]=original
 subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',out,*map(str,sources)],check=True)
 subprocess.run(['java','-Xmx256m','-cp',os.pathsep.join([out,*runtime]),'org.junit.runner.JUnitCore','com.littlebuddy.v2.parent.OwnerTickRegressionTest' if regression else 'com.littlebuddy.v2.parent.PinDiagnosticTest'],check=True)
