from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_input_metadata as m

class MetadataTest(unittest.TestCase):
 def test_capped_owned_child_is_terminated(self):
  data,result=m.bounded([sys.executable,'-c',"import os,time;os.write(1,b'x'*10000);time.sleep(30)"],limit=100,seconds=1)
  self.assertEqual(len(data),100);self.assertTrue(result['capped'])
  self.assertNotEqual(result['exit_code'],0);self.assertEqual(result['status'],'UNAVAILABLE')
 def test_no_credential_or_arbitrary_failure_body_is_exported(self):
  text=b'Input thread session 97 format PCM16\nBearer SECRET audio\nfailed SECRET\n'
  with patch.object(m,'bounded',return_value=(text,dict(status='UNAVAILABLE',exit_code=1,eof=True,capped=False))):
   r=m.query('fixed query')
  self.assertEqual(r['fields'],['Input thread session 97 format PCM16'])
  self.assertNotIn('SECRET',str(r))

 def test_typed_alsa_keeps_card_pcm_and_counter_fields(self):
  sample="""ALSA_PATH /proc/asound/cards
 0 [Intel]: HDA-Intel - HDA Intel
ALSA_PATH /proc/asound/pcm
00-00: HDA Analog : playback 1 : capture 1
ALSA_PATH /proc/asound/card0/pcm0c/sub0/hw_params
access: RW_INTERLEAVED
format: S16_LE
channels: 1
rate: 16000 (16000/1)
period_size: 320
buffer_size: 1280
ALSA_PATH /proc/asound/card0/pcm0c/sub0/status
state: RUNNING
owner_pid: 123
hw_ptr: 64960
appl_ptr: 64640
Bearer SECRET
Permission denied
"""
  fields=m.alsa_fields(sample)
  for key in ['0 [Intel]', '00-00:', 'state: RUNNING','owner_pid: 123','hw_ptr: 64960','appl_ptr: 64640','rate: 16000','period_size: 320','buffer_size: 1280']:
   self.assertTrue(any(line.startswith(key) for line in fields),key)
  self.assertNotIn('SECRET',str(fields));self.assertEqual(sum(x.startswith('ALSA_PATH') for x in fields),4)
