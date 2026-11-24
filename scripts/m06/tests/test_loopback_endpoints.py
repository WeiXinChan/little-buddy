"""Strict endpoint semantics; no wildcard/mapped-prefix shortcut."""
import importlib.util,unittest,json,os
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('grpc_endpoint',Path(__file__).parents[1]/'grpc_mic.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Endpoints(unittest.TestCase):
 def test_loopbacks_including_mapped_ipv4(self):
  for endpoint in ['127.0.0.1:8554','127.8.9.10:8554','127.255.255.255:8554','[::1]:8554','[0:0:0:0:0:0:0:1]:8554','[::ffff:127.0.0.1]:8554','[::ffff:7f08:090a]:8554']:
   with self.subTest(endpoint=endpoint):self.assertTrue(m.listener_endpoint(endpoint)['loopback'])
 def test_unknown_wildcard_non_loopback_and_non_loopback_mapping_rejected(self):
  for endpoint in ['*:8554','0.0.0.0:8554','[::]:8554','[::ffff:192.0.2.1]:8554','192.0.2.1:8554','[2001:db8::1]:8554','[::127.0.0.1]:8554','[::ffff:0:127.0.0.1]:8554','localhost:8554','127.0.0.1:0','127.0.0.1:99999','[::1]evil:8554','127.0.0.01:8554','[::1%SECRET_SENTINEL]:8554','SECRET_SENTINEL:8554']:
   with self.subTest(endpoint=endpoint):
    result=m.listener_endpoint(endpoint);self.assertFalse(result['loopback']);self.assertNotIn('SECRET_SENTINEL',json.dumps(result))
 def test_target_tcp_listen_and_owned_descriptor_pid_required(self):
  text='LISTEN 0 1 [::ffff:127.0.0.1]:8554 [::]:* users:(("qemu",pid=123,fd=9))\nLISTEN 0 1 0.0.0.0:9999 *:* users:(("other",pid=77,fd=8))\n'
  with patch.object(m,'owned_pid',return_value=True):
   rows=m.target_listeners(text,123,123);self.assertEqual(1,len(rows));self.assertTrue(rows[0]['loopback']);self.assertTrue(rows[0]['owned_pid_match'])
   self.assertFalse(m.target_listeners(text,124,124)[0]['owned_pid_match'])
  with patch.object(m,'owned_pid',return_value=False):self.assertFalse(m.target_listeners(text,123,123)[0]['owned_pid_match'])
 def test_unknown_listener_cannot_be_ignored_beside_a_valid_listener(self):
  text='LISTEN 0 1 127.0.0.1:8554 *:* users:(("qemu",pid=123,fd=1))\nLISTEN 0 1 *:8554 *:* users:(("qemu",pid=123,fd=2))\n'
  with patch.object(m,'owned_pid',return_value=True):
   rows=m.target_listeners(text,123,123);self.assertEqual(2,len(rows));self.assertFalse(all(e['loopback'] for e in rows))
if __name__=='__main__':unittest.main()
