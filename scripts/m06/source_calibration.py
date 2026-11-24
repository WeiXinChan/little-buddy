"""One same-AVD 7->6 pair. A failed live entry is retained and does not gate arm6.
Only identity/isolation or native ownership failure stops the next arm.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid
from native_input_metadata import ADB, bounded, preflight


def pair(perform):
    rows=[]
    for source in (7,6):
        row=perform(source); rows.append(row)
        if not row.get('gates_accepted') or not row.get('transport_complete') or not all(row.get(k) for k in ('finished','released','stopped','worker_done','lease_available')) or row.get('recording'):
            return dict(status='OWNERSHIP_OR_GATE_STOP', reason='GATE_NOT_READY' if not row.get('gates_accepted') else 'TRANSPORT_NOT_COMPLETED' if not row.get('transport_complete') else 'NATIVE_OWNERSHIP_NOT_RETURNED', arms=rows, unexecuted=[s for s in (7,6) if s not in [r['source'] for r in rows]])
    return dict(status='PAIR_EXECUTED', arms=rows, unexecuted=[])


ENTER_SHA='c53eb146203afc87fd8092f60721e49a20d30baaa0811da715788a40fe582e34'
PROTO_SHA='9a4b0f704b0d4cdda652f89fbd50bb3d54da3d46ec8efe6e8b2a2a135ef10e69'
def transport_complete(row,nonce):
    expected=dict(nonce=nonce,name='enter',sha256=ENTER_SHA,backend='EmulatorController.injectAudio',
                  proto_sha256=PROTO_SHA,stage='inject_completed',rpc_code='OK',packets=218,
                  playback_exit=0,source_samples=64960,rate=16000,channels=1,sample_format='s16le',
                  mode='MODE_UNSPECIFIED',drain_ms=300,packet_ms=20,host_mic=False)
    return all(k in row and type(row[k]) is type(v) and row[k]==v for k,v in expected.items()) and not row.get('generator_failure')

def run_arm(source):
    nonce=str(uuid.uuid4()); directory=Path('render')/('source'+str(source)); directory.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ, M06_CALIBRATION_SOURCE=str(source), M06_CALIBRATION_NONCE=nonce,
             M06_AUDIO_INPUT='grpc', BUDDY_SYNTHETIC_AVD_PROBE='1', ANDROID_SERIAL='emulator-5554')
    with (directory/'microphone.txt').open('wb') as out, (directory/'stderr.txt').open('wb') as error:
        code=subprocess.run([sys.executable,'scripts/m06/mic_controller.py'],env=env,stdout=out,stderr=error,timeout=300).returncode
    row=dict(source=source,nonce=nonce,test_exit=code,gates_accepted=False,transport_complete=False)
    transport_file=Path('render')/('mic-grpc-'+nonce+'.json')
    if transport_file.is_file():
        receipt=json.loads(transport_file.read_text());row['transport_complete']=transport_complete(receipt,nonce)
        row['transport_stage']=receipt.get('stage');row['transport_rpc_code']=receipt.get('rpc_code')
    (directory/'result.json').write_text(json.dumps(row,indent=2))
    # The completed test's native/worker/lease proof is required, not a sleep or cleared lease.
    raw, read=bounded(ADB+['shell','run-as','com.littlebuddy.sim.v2','cat',f'files/m06/arm-{source}-{nonce}-cleanup.json'],limit=16384)
    if read['status']=='AVAILABLE':
        proof=json.loads(raw)
        if proof.get('nonce')==nonce and proof.get('source')==source: row.update(proof)
    data, exported=bounded(ADB+['exec-out','run-as','com.littlebuddy.sim.v2','tar','-C','files','-cf','-','m06'],limit=32*1024*1024,seconds=10)
    row['export']=exported
    if exported['status']!='AVAILABLE': raise RuntimeError('bounded arm export failed')
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            path=Path(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='m06' or member.issym() or member.islnk(): raise RuntimeError('invalid arm archive member')
            if len(path.parts)>1 and path.parts[1].startswith('synthetic-') and path.parts[1]!='synthetic-'+nonce: continue
            if member.isdir(): continue
            if not member.isfile(): raise RuntimeError('non-file arm archive member')
            target=directory/path;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as src, target.open('wb') as dst:
                while chunk:=src.read(8192): dst.write(chunk)
    # Export is complete; purge exactly this nonce's synthetic PCM from the AVD.
    _, purge=bounded(ADB+['shell','run-as','com.littlebuddy.sim.v2','rm','-f',f'files/m06/synthetic-{nonce}/capture.s16le'],limit=4096)
    row['guest_pcm_purge']=purge
    if purge['status']!='AVAILABLE': raise RuntimeError('arm synthetic cleanup failed')
    with (directory/'alignment.txt').open('wb') as out:
        row['alignment_exit']=subprocess.run([sys.executable,'scripts/m06/analyze_capture.py',str(directory/'m06')],stdout=out,stderr=subprocess.STDOUT,timeout=30).returncode
    (directory/'result.json').write_text(json.dumps(row,indent=2))
    return row


def main():
    target=Path('render/source-calibration.json')
    assert os.environ.get('BUDDY_SYNTHETIC_AVD_PROBE')=='1'
    metadata=preflight(Path('render/native-input'))
    if not metadata['identity_ok'] or metadata['known_stub']:
        target.write_text(json.dumps(dict(status='FACILITY_STOP',arms=[],source6='NOT_RUN',metadata='native-input/preflight.json'),indent=2));return 1
    result=pair(run_arm);target.write_text(json.dumps(result,indent=2))
    # Original live failure remains a failure even if the other source succeeds.
    return 0 if result['status']=='PAIR_EXECUTED' and all(r['test_exit']==0 and r['alignment_exit']==0 for r in result['arms']) else 1


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as error:
        Path('render/source-calibration-error.json').write_text(json.dumps(dict(error_class=type(error).__name__,source6='NOT_RUN unless recorded in arm result')))
        raise RuntimeError('source calibration failed class='+type(error).__name__) from None
