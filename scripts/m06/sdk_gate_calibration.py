"""One source7 run, original complete mic assertions, frozen b2 Android packages."""
import hashlib
import json
import os
from pathlib import Path
import wave
from native_input_metadata import preflight
from source_calibration import run_arm,ENTER_SHA,PROTO_SHA

FINGERPRINT='google/sdk_gphone64_x86_64/emu64xa:16/BE2A.250530.026.F3/13894323:userdebug/dev-keys'

def gate_transport_complete(row,nonce):
    source=Path('app/src/androidTest/assets/m06-commands/enter.wav')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=ENTER_SHA:return False
    with wave.open(str(source)) as f:raw=f.readframes(f.getnframes())
    expected=dict(nonce=nonce,name='enter',sha256=ENTER_SHA,backend='EmulatorController.injectAudio',proto_sha256=PROTO_SHA,
                  stage='inject_completed',rpc_code='OK',packets=248,playback_exit=0,source_samples=64960,
                  rate=16000,channels=1,sample_format='s16le',mode='MODE_UNSPECIFIED',drain_ms=300,packet_ms=20,
                  initial_sdk_real_audio_enabled=False,private_null_only=True,prefix_ms=600,prefix_samples=9600,
                  transport_payload_sha256=hashlib.sha256(bytes(19200)+raw+bytes(9600)).hexdigest(),gate_restored_false=True)
    if not all(k in row and type(row[k]) is type(v) and row[k]==v for k,v in expected.items()):return False
    if row.get('generator_failure') or row.get('gate_journal')!='sdk-gate-'+nonce+'.json':return False
    try:
        gate=json.loads((Path('render')/row['gate_journal']).read_text())
        return gate.get('nonce')==nonce and gate.get('fixture_sha256')==ENTER_SHA and gate.get('restored_false') is True and gate.get('observer_stopped') is True and gate.get('enabled_during_stream') is True and type(gate.get('set_true_count')) is int and gate.get('set_true_count') in (0,1) and not any(e.get('event') in ('OBSERVER_FAILED','RESTORE_FAILED') for e in gate['events'])
    except (OSError,ValueError,KeyError):return False


def main():
    assert os.environ.get('M06_SDK_INPUT_GATE')=='1' and os.environ.get('BUDDY_SYNTHETIC_AVD_PROBE')=='1'
    metadata=preflight(Path('render/native-input'))
    path=Path('render/sdk-gate-calibration.json')
    if not metadata['identity_ok'] or metadata['known_stub'] or metadata['properties']['ro.build.fingerprint'].get('value')!=FINGERPRINT:
        path.write_text(json.dumps(dict(status='IDENTITY_OR_KNOWN_STUB_STOP',source=7,source6='NOT_RUN'),indent=2));return 1
    result=run_arm(7,gate_transport_complete)
    path.write_text(json.dumps(dict(status='SOURCE7_ONLY_EXECUTED',source6='NOT_RUN',arm=result),indent=2))
    return 0 if result['test_exit']==0 and result['transport_complete'] and result['alignment_exit']==0 and all(result.get(k) for k in ('finished','released','stopped','worker_done','lease_available')) and not result['recording'] else 1

if __name__=='__main__':
    import sys
    try:sys.exit(main())
    except Exception as error:
        Path('render/sdk-gate-calibration-error.json').write_text(json.dumps(dict(error_class=type(error).__name__,source6='NOT_RUN')))
        raise RuntimeError('source7 SDK gate experiment failed class='+type(error).__name__) from None
