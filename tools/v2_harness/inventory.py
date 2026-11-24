"""Minimal read-only inventory; only execute in a coordinator-assigned slot.

No raw subprocess output is returned. Requires an already-authorized ADB
connection (adb may start its host server). No phone operations beyond getprop.
"""
import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time

MAX_BYTES = 65536
MAX_REPORT_BYTES = 4096
TIMEOUT = 10
UNKNOWN = {'status': 'unknown'}
PROPS = ('ro.product.model', 'ro.build.version.release', 'ro.build.version.sdk', 'ro.build.id')


def _allowed(argv):
    return (argv == ['system_profiler', 'SPAudioDataType', '-json']
            or (len(argv) >= 4 and argv[0] == 'adb' and argv[1] == '-s'
                and isinstance(argv[2], str) and bool(argv[2])
                and (argv[3:] == ['get-state']
                     or (len(argv) == 6 and argv[3:5] == ['shell', 'getprop'] and argv[5] in PROPS))))


def _capture(argv, timeout=TIMEOUT):
    """Bound stdout in memory, discard stderr; kill only our exact child.

    The command allowlist cannot launch multica or a workspace daemon.
    """
    if not _allowed(argv):
        return None
    try:
        with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              stdin=subprocess.DEVNULL, shell=False) as child:
            data = bytearray()
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as ready:
                ready.register(child.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not ready.select(remaining):
                        child.kill()
                        child.wait()
                        return None
                    chunk = os.read(child.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    if len(data) + len(chunk) > MAX_BYTES:
                        child.kill()
                        child.wait()
                        return None
                    data.extend(chunk)
            try:
                code = child.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                return None
            if code != 0 or not data.strip():
                return None
            return data.decode('utf-8', errors='strict').strip()
    except (OSError, UnicodeError, ValueError):
        return None


def _integer(value, allowed):
    if type(value) is int:
        number = value
    elif type(value) is str and re.fullmatch(r'[0-9]{1,6}', value):
        number = int(value)
    else:
        return None
    return number if number in allowed else None


def audio_summary(raw):
    """Only anonymized enumerated capabilities, never device names/UIDs."""
    try:
        tree = json.loads(raw)
        if type(tree) is not dict or type(tree.get('SPAudioDataType')) is not list:
            return dict(UNKNOWN)
        devices = []

        def walk(items, depth=0):
            if depth > 5 or len(items) > 64:
                raise ValueError('unsupported inventory shape')
            for item in items:
                if type(item) is not dict:
                    raise ValueError('unsupported entry')
                fields = {}
                for source, target in [('coreaudio_device_input', 'input_channels'),
                                       ('coreaudio_device_output', 'output_channels')]:
                    value = _integer(item.get(source), range(1, 129))
                    if value is not None:
                        fields[target] = value
                rate = _integer(item.get('coreaudio_device_srate'), {8000, 16000, 22050, 24000, 44100, 48000, 96000, 192000})
                if rate is not None:
                    fields['sample_rate_hz'] = rate
                if fields:
                    if len(devices) >= 16:
                        raise ValueError('too many devices')
                    devices.append({'id': f'audio-{len(devices) + 1}', **fields})
                if '_items' in item:
                    if type(item['_items']) is not list:
                        raise ValueError('unsupported children')
                    walk(item['_items'], depth + 1)

        walk(tree['SPAudioDataType'])
        return {'status': 'observed', 'devices': devices} if devices else dict(UNKNOWN)
    except (ValueError, TypeError, RecursionError):
        return dict(UNKNOWN)


def query(argv):
    raw = _capture(argv)
    if raw is None:
        return dict(UNKNOWN)
    if argv[0] == 'system_profiler':
        return audio_summary(raw)
    if argv[3:] == ['get-state'] and raw in {'device', 'offline', 'unauthorized'}:
        return {'status': 'observed', 'value': raw}
    if argv[-1] == 'ro.product.model' and raw == 'PKW110':
        return {'status': 'observed', 'value': 'PKW110'}
    if argv[-1] == 'ro.build.version.release' and re.fullmatch(r'[0-9]{1,2}(\.[0-9]{1,2})?', raw):
        return {'status': 'observed', 'value': raw}
    if argv[-1] == 'ro.build.version.sdk':
        value = _integer(raw, range(26, 101))
        if value is not None:
            return {'status': 'observed', 'value': value}
    # Build strings may contain custom data: retain no value or hash.
    return dict(UNKNOWN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    adb = ['adb', '-s', args.serial]
    report = {'scope': 'read-only-inventory-not-acoustic-test', 'device': 'device-1',
              'connection': query(adb + ['get-state'])}
    for name, prop in zip(('model', 'android', 'sdk', 'build'), PROPS):
        report[name] = query(adb + ['shell', 'getprop', prop])
    report['host'] = sys.platform if sys.platform in {'darwin', 'linux'} else 'other'
    report['host_audio'] = query(['system_profiler', 'SPAudioDataType', '-json']) if sys.platform == 'darwin' else dict(UNKNOWN)
    for field in ['unlocked', 'aec', 'external_playback_to_phone', 'independent_speaker_observation',
                  'common_clock_error', 'v1_signature_and_install_strategy']:
        report[field] = {'status': 'NOT_VERIFIED'}
    text = json.dumps(report, ensure_ascii=True, indent=2)
    print(text if len(text.encode()) <= MAX_REPORT_BYTES else json.dumps(UNKNOWN))


if __name__ == '__main__':
    main()
