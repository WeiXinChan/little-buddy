"""Controlled clock at the actual GrpcMic.play journal/RPC-generator boundary.
No authentication, device, RPC, or new audio source is used.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'app/src/androidTest/assets/m06-commands/enter.wav'


def run(path, stall):
    spec = importlib.util.spec_from_file_location('candidate', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    now = [0.0]
    def sleep(seconds): now[0] += seconds
    defaults = (lambda: now[0], sleep, None)
    if 'before_yield' in m.packet_plan.__code__.co_varnames:
        defaults += (None,)
    m.packet_plan.__defaults__ = defaults
    delivered = []
    class Format:
        Mono = 0
        AUD_FMT_S16 = 1
        MODE_UNSPECIFIED = 0
        def __init__(self, **kw): self.__dict__.update(kw)
    class Journal:
        def bridge(self, stage): pass
        def step(self, stage, **kw):
            Path('journal.json').write_text(json.dumps(dict(stage=stage, **kw)))
            if stage == 'FIRST_PACKET_YIELDED': now[0] += stall
    class RpcError(Exception): pass
    class Stub:
        def setMicrophoneState(self, *a, **kw): pass
        def getMicrophoneState(self, *a, **kw): return SimpleNamespace(realAudioEnabled=False)
        def injectAudio(self, packets, **kw):
            for p in packets: delivered.append(len(p.audio))
    mic = m.GrpcMic.__new__(m.GrpcMic)
    mic.stub = Stub()
    mic.auth = ()
    mic.Empty = lambda: None
    mic.grpc = SimpleNamespace(RpcError=RpcError)
    mic.pb = SimpleNamespace(AudioFormat=Format, AudioPacket=lambda **kw: SimpleNamespace(**kw),
                             MicrophoneState=lambda **kw: SimpleNamespace(**kw))
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp, patch.object(m.time, 'monotonic', lambda: now[0]), patch.object(m.time, 'sleep', sleep):
        try:
            os.chdir(tmp)
            Path('render').mkdir()
            failure = None
            try:
                mic.play(SOURCE, dict(nonce='controlled-fixture', sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest()), timing=Journal())
            except m.InjectionTimingError as error:
                failure = dict(reason=error.reason, index=error.index, late_ms=error.late_ms)
            return dict(stall_ms=round(stall * 1000), delivered_packets=len(delivered), failure=failure)
        finally:
            os.chdir(previous)


import unittest
class JournalDeadlineTest(unittest.TestCase):
 def test_slow_journal_never_hands_first_packet_to_consumer(self):
  r=run(ROOT/'scripts/m06/grpc_mic.py',.5)
  self.assertEqual(r['delivered_packets'],0)
  self.assertEqual(r['failure'],dict(reason='PACKET_LATE',index=0,late_ms=500))
 def test_normal_journal_preserves_all_218_packets(self):
  r=run(ROOT/'scripts/m06/grpc_mic.py',0)
  self.assertEqual(r['delivered_packets'],218);self.assertIsNone(r['failure'])
