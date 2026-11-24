"""Read-only device inventory. Execute only in coordinator-assigned phone slot.

No install, launch, recording, playback, unlock, settings write or service start.
Serial is selected explicitly and never emitted. Timeout/failure stays unknown.
"""
import argparse
import json
import subprocess
import sys


def query(argv):
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=10)
        return {'status': 'observed', 'value': p.stdout.strip()} if p.returncode == 0 else {'status': 'unknown'}
    except (OSError, subprocess.TimeoutExpired):
        return {'status': 'unknown'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    adb = ['adb', '-s', args.serial]
    report = {'scope': 'read-only-inventory-not-acoustic-test',
              'connection': query(adb + ['get-state'])}
    for name, prop in [('model', 'ro.product.model'), ('android', 'ro.build.version.release'),
                       ('sdk', 'ro.build.version.sdk'), ('build', 'ro.build.id')]:
        report[name] = query(adb + ['shell', 'getprop', prop])
    report['host'] = sys.platform
    report['host_audio'] = query(['system_profiler', 'SPAudioDataType', '-json']) if sys.platform == 'darwin' else {'status': 'unknown'}
    for field in ['unlocked', 'aec', 'external_playback_to_phone', 'independent_speaker_observation',
                  'common_clock_error', 'v1_signature_and_install_strategy']:
        report[field] = {'status': 'NOT_VERIFIED'}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
