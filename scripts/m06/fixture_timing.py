"""Metadata-only clock brackets for the isolated synthetic AVD fixture.

/proc/uptime is guest boottime, comparable to elapsedRealtime, not host monotonic.
The bracket includes adb latency and 10ms uptime quantization; no offset is assumed.
"""
import json
import re
import subprocess
import time
from pathlib import Path


class FixtureTiming:
    def __init__(self, request, directory=Path('render'), run=subprocess.run,
                 clock=time.monotonic_ns):
        self.run = run
        self.clock = clock
        self.path = directory / ('mic-timing-' + request['nonce'] + '.json')
        self.data = dict(nonce=request['nonce'], source_sha256=request['sha256'],
                         scope='authorized synthetic fixture metadata only', events=[],
                         request={k: request.get(k) for k in (
                             'request_guest_elapsed_ms', 'request_guest_monotonic_ns',
                             'request_native_session', 'request_native_read_end_frame')})
        self.step('REQUEST_RECEIVED')

    def step(self, stage, **fields):
        self.data['events'].append(dict(stage=stage, host_monotonic_ns=self.clock(), **fields))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, indent=2))
        temp.replace(self.path)

    def bridge(self, stage):
        before = self.clock()
        try:
            r = self.run(['adb', 'shell', 'cat', '/proc/uptime'], capture_output=True,
                         text=True, timeout=2, check=False)
            after = self.clock()
            fields = dict(host_before_ns=before, host_after_ns=after, exit_code=r.returncode)
            # Never retain arbitrary stdout, stderr, or exception messages.
            match = re.fullmatch(r'([0-9]+\.[0-9]{2}) [0-9]+\.[0-9]{2}\s*', r.stdout)
            if r.returncode == 0 and match:
                fields.update(guest_boottime_ms=round(float(match[1]) * 1000), quantization_ms=10)
            else:
                fields['clock_status'] = 'UNAVAILABLE'
            self.step(stage, **fields)
        except Exception as error:
            self.step(stage, host_before_ns=before, host_after_ns=self.clock(),
                      clock_status='UNAVAILABLE', error_class=type(error).__name__)
