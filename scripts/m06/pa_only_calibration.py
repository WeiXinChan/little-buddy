"""One PA-only source7 experiment, frozen b2 APK, no injectAudio."""
import json,os
from pathlib import Path
from native_input_metadata import preflight
from source_calibration import run_arm,ENTER_SHA
from sdk_gate_calibration import FINGERPRINT

def pa_transport_complete(row,nonce):
    expected=dict(nonce=nonce,name='enter',sha256=ENTER_SHA,backend='private Pulse paplay; no injectAudio',stage='COMPLETED',rate=16000,channels=1,sample_format='s16le',source_samples=64960,prefix_ms=600,prefix_samples=9600,tail_ms=300,payload_samples=79360,payload_sha256='6adff50b69642e42612c417e141e85ece88b4a03f765003cbe2fc363b0f1632a',playback_exit=0,sdk_true=True,sdk_restored_false=True,owned_stopped=True,transport_complete=True)
    return all(type(row.get(k)) is type(v) and row[k]==v for k,v in expected.items()) and row.get('alignment',{}).get('full_source_samples')==64960 and row.get('alignment',{}).get('correlation',0)>=.98

def main():
    assert os.environ.get('M06_SDK_INPUT_GATE')=='1' and os.environ.get('BUDDY_SYNTHETIC_AVD_PROBE')=='1'
    metadata=preflight(Path('render/native-input'));path=Path('render/sdk-gate-calibration.json')
    if not metadata['identity_ok'] or metadata['known_stub'] or metadata['properties']['ro.build.fingerprint'].get('value')!=FINGERPRINT:
        path.write_text(json.dumps(dict(status='IDENTITY_OR_KNOWN_STUB_STOP',source6='NOT_RUN')));return 1
    if os.environ.get('M06_NATIVE_READONLY')=='1':
        from native_readonly import NativeReadOnly
        NativeReadOnly().prepare(metadata)
    result=run_arm(7,pa_transport_complete,input_backend='pa-only',receipt_prefix='mic-pa-')
    path.write_text(json.dumps(dict(status='SOURCE7_PA_ONLY',source6='NOT_RUN',arm=result),indent=2))
    return 0 if result['test_exit']==0 and result['transport_complete'] and result['alignment_exit']==0 and all(result.get(k) for k in ('finished','released','stopped','worker_done','lease_available')) and not result['recording'] else 1

if __name__=='__main__':
    import sys
    sys.exit(main())
