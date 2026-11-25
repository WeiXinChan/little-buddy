"""Read-only, bounded metadata from the owned synthetic AVD; never PCM/logcat."""
import hashlib
import json
import os
import re
from pathlib import Path
import select
import subprocess
import time

ADB = ['adb', '-s', 'emulator-5554']
ALSA_COMMAND='for f in /proc/asound/cards /proc/asound/pcm /proc/asound/card*/pcm*c/sub*/hw_params /proc/asound/card*/pcm*c/sub*/status; do if [ -r "$f" ]; then printf "ALSA_PATH %s\\n" "$f"; cat "$f"; fi; done'

def alsa_fields(text):
    patterns=(r'ALSA_PATH /proc/asound/(?:cards|pcm|card[0-9]+/pcm[0-9]+c/sub[0-9]+/(?:hw_params|status))',
              r'[0-9]+ \[[^\]\r\n]{1,80}\].*',r'[0-9]+-[0-9]+:.*',
              r'(?:state|trigger_time|tstamp|delay|avail|avail_max|hw_ptr|appl_ptr|owner_pid|access|format|subformat|channels|rate|period_size|period_time|buffer_size|boundary):[A-Za-z0-9_+ ./()-]+',
              r'(?:closed|suspended)')
    return [line[:600] for raw in text.splitlines() if (line:=raw.strip()) and
            not any(w in line.lower() for w in ('bearer','token','credential','pubkey','header','error:','permission denied')) and
            any(re.fullmatch(pattern,line) for pattern in patterns)][:180]


def bounded(args, limit=131072, seconds=3):
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = bytearray()
    eof = False
    end = time.monotonic() + seconds
    try:
        while len(data) < limit and time.monotonic() < end:
            if not select.select([p.stdout], [], [], max(0, end-time.monotonic()))[0]: break
            chunk = os.read(p.stdout.fileno(), min(8192, limit-len(data)))
            if not chunk:
                eof = True
                break
            data.extend(chunk)
        if eof: p.wait(timeout=1)
    finally:
        if p.poll() is None:
            p.terminate()
            try: p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait(timeout=1)
        p.stdout.close()
    return bytes(data), dict(exit_code=p.returncode, eof=eof, capped=len(data)==limit,
                             status='AVAILABLE' if eof and p.returncode==0 else 'UNAVAILABLE')


def query(command, kind=None, seconds=3):
    started_ns=time.monotonic_ns()
    try:
        data, result = bounded(ADB + ['shell', command],seconds=seconds)
        text = data.decode('utf-8', 'replace')
        # Never retain arbitrary error bodies or credentials/headers.
        wanted = ('audio', 'input', 'record', 'effect', 'format', 'sample', 'channel', 'source',
                  'device', 'session', 'thread', 'handle', 'gain', 'mute', 'silenc', 'alsa', 'pcm', '<name>', '<version>',
                  '<interface>', '<instance>', '<transport>', '<hal', '<profile', '<route')
        result['fields'] = [line[:600] for line in text.splitlines()
                            if any(w in line.lower() for w in wanted)
                            and not any(w in line.lower() for w in ('bearer', 'token', 'credential', 'pubkey', 'header', 'permission denied', "can't", 'exception', 'failed', 'error:'))][:180]
        if kind=='alsa':result['fields']=alsa_fields(text)
        if kind=='flinger':
            from native_readonly import flinger_fields
            result['input_threads']=flinger_fields(text) if result['status']=='AVAILABLE' and not result.get('capped') else []
            result['input_threads_status']='AVAILABLE' if result['input_threads'] else 'UNAVAILABLE'
        result.update(started_monotonic_ns=started_ns,ended_monotonic_ns=time.monotonic_ns())
        result['observed_sha256'] = hashlib.sha256(data).hexdigest()
        return result
    except Exception as error:
        return dict(status='UNAVAILABLE', error_class=type(error).__name__,started_monotonic_ns=started_ns,ended_monotonic_ns=time.monotonic_ns())


def preflight(directory):
    directory.mkdir(parents=True, exist_ok=True)
    props = {}
    for key in ('ro.hardware', 'ro.product.name', 'ro.product.cpu.abi', 'ro.build.version.sdk',
                'ro.build.fingerprint', 'ro.boot.audio.tinyalsa.simulate_input'):
        try:
            raw, result = bounded(ADB + ['shell', 'getprop', key], limit=4096)
            value = raw.decode().strip()
            props[key] = dict(value=value if result['status']=='AVAILABLE' else None,
                              present=bool(value), **result)
        except Exception as error: props[key] = dict(status='UNAVAILABLE', error_class=type(error).__name__)
    def value(key): return props[key].get('value')
    identity = (value('ro.hardware') in ('ranchu','goldfish') and value('ro.product.name')=='sdk_gphone64_x86_64'
                and value('ro.product.cpu.abi')=='x86_64' and value('ro.build.version.sdk')=='36')
    stub = (value('ro.boot.audio.tinyalsa.simulate_input') or '').lower() in ('1','true','yes','on')
    result = dict(identity_ok=identity, known_stub=stub, properties=props,
                  native_consumed_counter='UNAVAILABLE: SDK public injectAudio response has no consumed-frame field',
                  declarations=query('lshal'), services=query('service list'), hal_processes=query('ps -A -o USER,PID,NAME'),
                  vintf=query('cat /vendor/etc/vintf/manifest.xml /vendor/etc/vintf/manifest/*audio*.xml'),
                  policy_hashes=query('sha256sum /vendor/etc/audio_policy_configuration.xml /vendor/etc/primary_audio_policy_configuration.xml'),
                  policy=query('cat /vendor/etc/audio_policy_configuration.xml /vendor/etc/primary_audio_policy_configuration.xml'),
                  alsa=query(ALSA_COMMAND,kind='alsa'))
    (directory/'preflight.json').write_text(json.dumps(result, indent=2))
    return result


def active(directory, nonce, rpc_done, transport_backend='grpc', native_started=None, source_evidence=None, playback_window=None):
    row = dict(nonce=nonce, scope='metadata only; not native consumption proof',
               started_monotonic_ns=time.monotonic_ns())
    path = directory/('active-'+nonce+'.json')
    for name, command in [('flinger','dumpsys media.audio_flinger'), ('policy','dumpsys media.audio_policy')]:
        row[name] = query(command,kind='flinger' if name=='flinger' and native_started is not None else None,seconds=1)
        row['observed_monotonic_ns'] = time.monotonic_ns()
        path.write_text(json.dumps(row, indent=2))

    if native_started is not None:
        deadline=time.monotonic()+8
        while not native_started.wait(.05):
            if rpc_done.is_set() or time.monotonic()>=deadline:break
        if native_started.is_set():
            from native_readonly import during
            row['native_readonly']=during(directory,nonce,source_evidence or {})
        else:row['native_readonly']=dict(status='UNAVAILABLE',reason='NO_PA_PLAYBACK')
    row['transport_backend']=transport_backend
    row['playback_completion_observed' if transport_backend=='pa-only' else 'rpc_completion_observed']=rpc_done.wait(7)
    row['alsa_after_rpc']=query(ALSA_COMMAND,kind='alsa',seconds=1)
    row['alsa_observed_monotonic_ns']=time.monotonic_ns()
    if playback_window is not None and row.get('native_readonly',{}).get('nonce')==nonce:
        from native_readonly import finalise_during
        finalise_during(directory,nonce,row['native_readonly'],playback_window,row.get('flinger',{}))
    path.write_text(json.dumps(row,indent=2))
