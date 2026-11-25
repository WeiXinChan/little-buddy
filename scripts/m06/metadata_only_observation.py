"""Proposed explicit B observer. No fixture, APK, playback or injectAudio entry."""
import json
import os
import re
import time
import traceback
from pathlib import Path
from native_input_metadata import bounded
from native_readonly import NativeReadOnly, complete
from sdk_input_gate import PrivatePulse, MetadataPulseView
from sdk_gate_calibration import FINGERPRINT
from hda_guard import sdk_support, host_hda_evidence

class Stop(RuntimeError):
    def __init__(self,reason): self.reason=reason;super().__init__(reason)

PROPERTIES={'ro.hardware':'ranchu','ro.product.name':'sdk_gphone64_x86_64','ro.product.cpu.abi':'x86_64','ro.build.version.sdk':'36','ro.build.fingerprint':FINGERPRINT}

PUBLICATION_BEFORE='f6f63ac69909bdc4416ad5ea5def8d816d461b89'

def publication_gate(event,attempt,repository,head,parent):
    if attempt!='1' or repository!='WeiXinChan/little-buddy':raise Stop('PUBLICATION_CONTEXT')
    pr=event.get('pull_request',{});ref=pr.get('head',{})
    after=event.get('after')
    if event.get('action')!='synchronize' or event.get('number')!=36 or pr.get('number')!=36:raise Stop('PUBLICATION_EVENT')
    if ref.get('repo',{}).get('full_name')!=repository or ref.get('ref')!='agent/agent/70f7ce4d7235':raise Stop('PUBLICATION_BRANCH')
    if event.get('before')!=PUBLICATION_BEFORE or not isinstance(after,str) or not re.fullmatch('[0-9a-f]{40}',after):raise Stop('PUBLICATION_TRANSITION')
    if after!=ref.get('sha') or after!=head or parent!=PUBLICATION_BEFORE:raise Stop('PUBLICATION_COMMIT')
    return dict(status='ONE_PUBLICATION_ALLOWED',before=PUBLICATION_BEFORE,after=after,attempt=1)

def check_publication():
    import subprocess
    path=Path(os.environ['GITHUB_EVENT_PATH'])
    if os.environ.get('GITHUB_EVENT_NAME')!='pull_request' or path.stat().st_size>1048576:raise Stop('PUBLICATION_PAYLOAD')
    event=json.loads(path.read_text())
    fields=subprocess.check_output(['git','rev-list','--parents','-n','1','HEAD'],text=True,timeout=2).split()
    if len(fields)!=2:raise Stop('PUBLICATION_PARENT')
    return publication_gate(event,os.environ.get('GITHUB_RUN_ATTEMPT'),os.environ.get('GITHUB_REPOSITORY'),*fields)

def identity(run):
    values={}
    for key,expected in PROPERTIES.items():
        raw,info=run(['adb','-s','emulator-5554','shell','getprop',key],limit=2048,seconds=1)
        if not complete(info) or raw.decode('utf-8','strict').strip()!=expected:raise Stop('IMAGE_IDENTITY')
        values[key]=dict(value=expected)
    raw,info=run(['adb','-s','emulator-5554','shell','getprop','ro.boot.audio.tinyalsa.simulate_input'],limit=128,seconds=1)
    if not complete(info) or raw.decode('utf-8','strict').strip().lower() not in ('','0','false','off'):raise Stop('STUB_OR_UNKNOWN')
    return dict(identity_ok=True,known_stub=False,properties=values)

def feature_off(base):
    if not isinstance(base,dict) or base.get('proof_scope')!='BASE_METADATA_ONLY':raise Stop('BASE_SCOPE')
    audio=base.get('audio')
    if not isinstance(audio,dict) or not audio:raise Stop('HOST_REQUEST_MISSING')
    for record in audio.values():
        p=record.get('hda_projection',{})
        if p.get('force_off_count')!=1 or p.get('force_on_count')!=0 or p.get('feature_unknown_count')!=0:raise Stop('NOT_SINGLE_FEATURE_OFF')
        host_hda_evidence(p) # request evidence only, never guest/fixture authorization

def observe(directory=Path('render/metadata-only'),*,run=bounded,proof_factory=PrivatePulse,native_factory=NativeReadOnly,control_factory=None,support=sdk_support):
    directory.mkdir(parents=True,exist_ok=True)
    row=dict(mode='METADATA_ONLY',fixture='NOT_RUN',fixture_authorization=False,root_attempts=0,status='STOP',events=[])
    control=None
    def save(stage,**fields):
        row.update(fields);row['events'].append(dict(stage=stage,monotonic_ns=time.monotonic_ns()))
        (directory/'result.json').write_text(json.dumps(row,indent=2))
    try:
        save('REQUEST')
        if os.environ.get('M06_METADATA_ONLY')!='1' or os.environ.get('M06_NATIVE_READONLY')!='1':raise Stop('MODE_NOT_ALLOWED')
        files=support(Path(os.environ['ANDROID_HOME']));save('SDK_FILES',sdk_files=files)
        if files.get('status')!='AVAILABLE':raise Stop('SDK_FILES_UNAVAILABLE')
        proof=proof_factory();view=MetadataPulseView(proof)
        base=view.verify();feature_off(base);save('BASE_AND_HOST_REQUEST',proof_scope=base['proof_scope'])
        metadata=identity(run);save('IMAGE_IDENTITY')
        if control_factory is None:
            from grpc_mic import GrpcMic
            control_factory=lambda:GrpcMic(state_only_auth=True)
        control=control_factory() # authenticated state-only; anonymous state RPC rejected by existing setup
        def sdk_false():
            control.stub.setMicrophoneState(control.pb.MicrophoneState(realAudioEnabled=False),metadata=control.auth,timeout=.4)
            return not bool(control.stub.getMicrophoneState(control.Empty(),metadata=control.auth,timeout=.4).realAudioEnabled)
        if not sdk_false():raise Stop('SDK_FALSE')
        save('SDK_FALSE_BEFORE',sdk_false_before=True)
        native=native_factory(directory=directory,run=run)
        prepared=native.prepare(metadata,metadata_proof=view)
        save('ROOT_PREPARED',root_attempts=prepared.get('root_attempts',0),prepare_status=prepared.get('status'))
        if prepared.get('status')!='AVAILABLE' or prepared.get('root_uid')!=0:raise Stop('ROOT_OR_HAL_UNAVAILABLE')
        observed=native.enumeration_metadata(metadata_proof=view)
        save('ENUMERATION',observation=observed)
        if observed.get('identity_rechecked') is not True:raise Stop('OBSERVATION_IDENTITY_UNAVAILABLE')
        save('OBSERVED',status='OBSERVED_NOT_PRODUCT_PASS')
    except Exception as error:
        reason=getattr(error,'reason',None)
        save('STOP',status='STOP',failure_phase=row['events'][-1]['stage'] if row['events'] else 'REQUEST',source=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__) if Path(f.filename).name in ('metadata_only_observation.py','native_readonly.py','enumeration_metadata.py','sdk_input_gate.py','hda_guard.py')][-6:],reason=reason if isinstance(reason,str) and re.fullmatch('[A-Z_]{1,80}',reason) else 'OBSERVATION_FAILED',error_class=type(error).__name__)
    finally:
        if control is not None:
            try:
                control.stub.setMicrophoneState(control.pb.MicrophoneState(realAudioEnabled=False),metadata=control.auth,timeout=.4)
                restored=not bool(control.stub.getMicrophoneState(control.Empty(),metadata=control.auth,timeout=.4).realAudioEnabled)
                save('SDK_FINAL_FALSE',sdk_final_false=restored)
                if not restored:row['status']='STOP'
            except Exception as error:save('SDK_FALSE_UNAVAILABLE',status='STOP',sdk_final_false=False,cleanup_error_class=type(error).__name__)
            finally:
                try:control.close()
                except Exception as error:save('CHANNEL_CLOSE_FAILED',status='STOP',cleanup_error_class=type(error).__name__)
        else:save('SDK_NOT_INITIALIZED',sdk_final_false=None)
        save('FINISHED')
    return 0 if row['status']=='OBSERVED_NOT_PRODUCT_PASS' and row.get('sdk_final_false') is True else 1

if __name__=='__main__':
    import signal,sys
    try:publication=check_publication()
    except Exception:
        print('PUBLICATION_GATE_STOP')
        raise SystemExit(1)
    if sys.argv[1:]==['--publication-gate']:
        print(json.dumps(publication))
        raise SystemExit(0)
    if sys.argv[1:]:raise SystemExit(1)
    def expired(*_):raise Stop('TOTAL_OBSERVATION_DEADLINE')
    signal.signal(signal.SIGTERM,expired)
    signal.signal(signal.SIGALRM,expired)
    signal.alarm(75)
    raise SystemExit(observe())
