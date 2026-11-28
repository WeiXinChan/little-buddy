#!/usr/bin/env python3
"""Offline production Capture with controlled native/owner substitutes; no device/audio input."""
import os,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
def jar(g,a,v):return str(next((cache/g/a/v).glob('*/*.jar')))
compiler=[jar('org.jetbrains.kotlin',a,v) for a,v in [('kotlin-compiler-embeddable','2.2.21'),('kotlin-stdlib','2.2.21'),('kotlin-script-runtime','2.2.21'),('kotlin-reflect','1.6.10')]]+[jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','13.0')]
runtime=[compiler[1],jar('junit','junit','4.13.2'),jar('org.hamcrest','hamcrest-core','1.3')]
sources=list((root/'scripts/testing/capture').glob('*.kt'))
sources=[s for s in sources if s.name!='NativeEvidence.kt']
if os.environ.get('CAPTURE_RECOVERY_ONLY'):sources+=list((root/'scripts/testing/recovery').glob('*Test.kt'))
if os.environ.get('CAPTURE_SOURCE_BASE'):sources=[s for s in sources if s.name not in ['CaptureSafetyTest.kt','NativeLedgerTest.kt','CaptureBootstrapTest.kt','RetiredCaptureDiagnosticTest.kt','ExpiryStartupTest.kt']]
base=Path(os.environ.get('CAPTURE_SOURCE_BASE',str(root/'app/src/main/java/com/littlebuddy/v2')))
if os.environ.get('CAPTURE_SOURCE_BASE'):sources.append(root/'app/src/main/java/com/littlebuddy/v2/NativeCaptureBuffer.kt')
sources += [base/(n+'.kt') for n in ['Capture','ManagementCapture','WakeSamples']]
sources += [root/'app/src/main/java/com/littlebuddy/v2'/(n+'.kt') for n in ['Playback','NativeEvidence']]
sources += [root/'app/src/main/java/com/littlebuddy/v2/parent/PinDiagnostic.kt']
for n in ['ExpiryCaptureRestart','NativeCaptureBuffer','CaptureSessionPort','RecoveryHandoff','CaptureUploads','RecorderLease','EyeState','WakeOrigin','InputGate','CaptureClockFailure','CaptureClockEnvelope','NativeReadLedger','CaptureBootstrap']:
 if (base/(n+'.kt')).exists():sources.append(base/(n+'.kt'))
with tempfile.TemporaryDirectory(dir=root,prefix='capture-tests-') as out:
 subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',out,*map(str,sources)],check=True)
 subprocess.run(['java','-Xmx256m','-cp',os.pathsep.join([out,*runtime]),'org.junit.runner.JUnitCore',*(['com.littlebuddy.v2.NativeBufferTest'] if os.environ.get('CAPTURE_BUFFER_ONLY') else ['com.littlebuddy.v2.StartupBoundaryTest',*(['com.littlebuddy.v2.ExpiryStartupTest'] if not os.environ.get('CAPTURE_SOURCE_BASE') else [])] if os.environ.get('CAPTURE_START_BOUNDARY_ONLY') else ['com.littlebuddy.v2.HandoffTest','com.littlebuddy.v2.RecoveryCaptureTest'] if os.environ.get('CAPTURE_RECOVERY_ONLY') else ['com.littlebuddy.v2.RearmCaptureTest'] if os.environ.get('CAPTURE_REARM_ONLY') else ['com.littlebuddy.v2.RetiredCaptureDiagnosticTest'] if os.environ.get('CAPTURE_DIAGNOSTIC_ONLY') else ['com.littlebuddy.v2.ContinuousCaptureTest'] if os.environ.get('CAPTURE_CONTINUOUS_ONLY') else ['com.littlebuddy.v2.OriginalCaptureTest','com.littlebuddy.v2.RearmCaptureTest',*(['com.littlebuddy.v2.CaptureSafetyTest','com.littlebuddy.v2.ContinuousCaptureTest','com.littlebuddy.v2.NativeLedgerTest','com.littlebuddy.v2.CaptureBootstrapTest'] if not os.environ.get('CAPTURE_SOURCE_BASE') else [])])],check=True)
if not os.environ.get('CAPTURE_BUFFER_ONLY') and not os.environ.get('CAPTURE_START_BOUNDARY_ONLY') and not os.environ.get('CAPTURE_RECOVERY_ONLY') and not os.environ.get('CAPTURE_SOURCE_BASE') and not os.environ.get('CAPTURE_CONTINUOUS_ONLY') and not os.environ.get('CAPTURE_DIAGNOSTIC_ONLY'):
 sources=[root/'scripts/testing/capture'/n for n in ['Assets.kt','Onnx.kt']]
 sources+=list((root/'scripts/testing/wake-cancel').glob('*.kt'))
 sources+=[root/'app/src/main/java/com/littlebuddy/WakeReader.kt']
 sources+=[root/'app/src/main/java/com/littlebuddy/v2'/(n+'.kt') for n in ['CaptureClockFailure','CaptureClockEnvelope','NativeReadLedger','CaptureBootstrap']]
 with tempfile.TemporaryDirectory(dir=root,prefix='wake-cancel-tests-') as out:
  subprocess.run(['java','-Xmx512m','-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-classpath',os.pathsep.join(runtime),'-d',out,*map(str,sources)],check=True)
  subprocess.run(['java','-Xmx256m','-cp',os.pathsep.join([out,*runtime]),'org.junit.runner.JUnitCore','com.littlebuddy.WakeCancellationTest','com.littlebuddy.BootstrapSherpaTest'],check=True)
