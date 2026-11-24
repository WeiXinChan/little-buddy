#!/usr/bin/env python3
"""Coordinator/OPPO-agent only. Serial instrumentation; never targets V1.

Permission revocation may kill the instrumentation process. A foreground host
controller must observe its real native-ready marker BEFORE pm revoke, confirm
process death + denied OS permission, then run fresh denied/restored phases.
No recordings, chat bodies, device serials or fixture credentials enter results.
"""
import argparse
import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

PACKAGE='com.littlebuddy.sim.v2'
RUNNER=PACKAGE+'.test/com.littlebuddy.SimUiRunner'
CLASS='com.littlebuddy.V2AudioTest'
PERMISSION='android.permission.RECORD_AUDIO'


def main(args):
    if not args.address.startswith('wss://') or not args.address.endswith('/v2/voice'):
        raise ValueError('fixture TLS endpoint required')
    token=Path(args.token_file).read_text().strip()
    if not re.fullmatch('[A-Za-z0-9]{32,256}',token): raise ValueError('fixture credential')
    adb=[args.adb,'-s',args.serial]
    results=[]
    def command(*parts,timeout=20,check=True):
        try:
            completed=subprocess.run(adb+list(parts),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError('ADB action timeout') from None
        if check and completed.returncode: raise RuntimeError('ADB action failed')
        return completed.stdout.replace(token,'<fixture-token>')
    def invocation(method,**fields):
        command=['shell','am','instrument','-w','-e','class',CLASS+'#'+method,
                 '-e','v2Address',args.address,'-e','v2FixtureToken',token]
        for key,value in fields.items():command+=['-e',key,str(value)]
        return adb+command+[RUNNER]
    def test(method,**fields):
        result=subprocess.run(invocation(method,**fields),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
        text=result.stdout.replace(token,'<fixture-token>')
        if 'INSTRUMENTATION_STATUS_CODE: -3' in text or 'INSTRUMENTATION_STATUS_CODE: -4' in text:
            status='NOT_RUN'
        else:
            status='PASS' if result.returncode==0 and re.search(r'OK \(1 test\)',text) else 'FAIL'
        results.append(dict(case=method,status=status))
        if status=='FAIL': raise RuntimeError('instrumentation assertion failed: '+method)
    try:
        if args.case in ('native','all'):test('nativeTrackAckAndStopReleaseUseProductionPump')
        if args.case in ('tls','all'):
            test('realTlsWebsocketFeedsRealTrackAndAckReturnsToBackend')
            test('suppressedFinalAckCannotPassRoundTripOracle')
        if args.case in ('home','all'):
            test('backgroundReleasesRecorderAndPlayerWithoutAutomaticResume')
            test('startupFailureCannotPassNativeReadiness')
        if args.case in ('lock','all'):test('lockScreenReleasesAndUnlockRequiresExplicitNewConnection')
        if args.case in ('permission','all'):
            command('shell','pm','grant',PACKAGE,PERMISSION)
            process=subprocess.Popen(invocation('permissionRevocationPreparation',v2PermissionPhase='prepare'),
                                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            lines=queue.Queue()
            reader=threading.Thread(target=lambda:[lines.put(line) for line in process.stdout],daemon=True)
            reader.start()
            player=None; ready=False; deadline=time.monotonic()+15
            try:
                while time.monotonic()<deadline and not ready:
                    try:line=lines.get(timeout=.2)
                    except queue.Empty:
                        if process.poll() is not None:break
                        continue
                    match=re.search(r'v2_player=([0-9a-f-]+)',line)
                    if match:player=match.group(1)
                    if 'v2_phase=V2_NATIVE_READY_FOR_REVOKE' in line:ready=True
                if not ready:raise RuntimeError('no real RECORDING/AudioTrack head readiness; startup failure is not PASS')
                # The READY bundle is emitted only after NativeEvidence.requireRunning.
                command('shell','pm','revoke',PACKAGE,PERMISSION)
                end=time.monotonic()+5
                while time.monotonic()<end and command('shell','pidof',PACKAGE,check=False).strip():time.sleep(.1)
                if command('shell','pidof',PACKAGE,check=False).strip():raise RuntimeError('revocation did not terminate target UID process')
                package_dump=command('shell','dumpsys','package',PACKAGE)
                if not re.search(r'android\.permission\.RECORD_AUDIO:\s*granted=false',package_dump):
                    raise RuntimeError('OS did not confirm denied RECORD_AUDIO')
                # Parse the complete readiness bundle, without persisting raw output.
                process.wait(timeout=5);reader.join(timeout=1)
                while not lines.empty():
                    match=re.search(r'v2_player=([0-9a-f-]+)',lines.get_nowait())
                    if match:player=match.group(1)
                if player is None:raise RuntimeError('missing original native player identity')
                results.append(dict(case='permission-revocation',status='PASS',
                    evidence='native-ready precondition; OS permission denied; target native-owner process absent',
                    acoustic='NOT_TESTED'))
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait()
                reader.join(timeout=1)
                command('shell','am','force-stop',PACKAGE,check=False)
            test('permissionDeniedStartupDoesNotRecord',v2PermissionPhase='denied')
            command('shell','pm','grant',PACKAGE,PERMISSION)
            test('permissionRestoredRequiresExplicitNewConnection',v2PermissionPhase='restored',v2PreviousPlayer=player)
    except Exception as error:
        results.append(dict(case='controller',status='FAIL',reason=type(error).__name__))
        raise RuntimeError('device regression failed; see redacted result') from None
    finally:
        # Restore only this test package's requested test permission and stop it.
        # Never uninstall/clear V1, modify lock credentials, or stop adb/Multica.
        command('shell','pm','grant',PACKAGE,PERMISSION,check=False)
        command('shell','am','force-stop',PACKAGE,check=False)
        Path(args.out).write_text(json.dumps(dict(scope='native device software; not acoustic',
            device_serial_redacted=True,results=results),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--adb',default='adb');parser.add_argument('--serial',required=True)
    parser.add_argument('--address',required=True);parser.add_argument('--token-file',required=True)
    parser.add_argument('--case',choices=['native','tls','home','lock','permission','all'],default='all')
    parser.add_argument('--out',required=True)
    main(parser.parse_args())
