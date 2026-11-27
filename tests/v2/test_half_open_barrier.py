"""In-memory scheduling reproduction using frozen c486 TcpRelay.pipe_bytes.
No sockets/listener/TLS/services/worker/lock; preserves two-chunk-before-pause race.
"""
import pathlib,sys,asyncio,unittest
from types import SimpleNamespace

from scripts.v2_tls_soak import TcpRelay
class Source:
 def __init__(self):self.queue=asyncio.Queue();self.waiting=asyncio.Event()
 async def read(self,count):self.waiting.set();return await self.queue.get()
class Dest:
 def __init__(self):self.chunks=[];self.transport=SimpleNamespace(get_write_buffer_size=lambda:0)
 def write(self,data):self.chunks.append(data)
 async def drain(self):await asyncio.sleep(0)
async def until(predicate):
 async with asyncio.timeout(.5):
  while not predicate():await asyncio.sleep(0)
class Reproduction(unittest.IsolatedAsyncioTestCase):
 async def test_pause_after_two_received_chunks_cannot_prove_blocked_without_new_bytes(self):
  relay=TcpRelay(1);source=Source();dest=Dest();task=asyncio.create_task(relay.pipe_bytes(source,dest,'down'))
  try:
   for _ in range(2):source.waiting.clear();source.queue.put_nowait(b'synthetic-tls-chunk');await until(lambda:len(dest.chunks)>_)
   await asyncio.sleep(0);source.waiting.clear();await asyncio.sleep(0)
   relay.pause('up');relay.pause('down')
   with self.assertRaises(TimeoutError):await asyncio.wait_for(relay.blocked['down'].wait(),.02)
   self.assertFalse(relay.blocked['down'].is_set());self.assertFalse(relay.gates['down'].is_set());self.assertEqual(len(dest.chunks),2)
   # Only a future chunk wakes the already-pending read and creates a block witness.
   source.queue.put_nowait(b'future-data');await asyncio.wait_for(relay.blocked['down'].wait(),.5)
   self.assertEqual(len(dest.chunks),2)
  finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
 async def test_arm_downstream_before_first_ack_then_block_next_chunk(self):
  relay=TcpRelay(1);source=Source();dest=Dest();task=asyncio.create_task(relay.pipe_bytes(source,dest,'down'))
  try:
   source.queue.put_nowait(b'first-audio');await until(lambda:len(dest.chunks)==1)
   # Proposed hook before ACK1: downstream armed while upstream remains open.
   relay.pause('down');self.assertTrue(relay.gates['up'].is_set())
   # Synthetic server emits next bytes only after that ACK1 is allowed upstream.
   source.queue.put_nowait(b'next-audio-after-ack');await asyncio.wait_for(relay.blocked['down'].wait(),.5)
   relay.pause('up');self.assertEqual(dest.chunks,[b'first-audio']);self.assertEqual(relay.bytes['down'],len(b'first-audio'))
  finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
 async def test_pause_before_next_read_has_a_real_block_witness(self):
  relay=TcpRelay(1);relay.pause('down');source=Source();dest=Dest();task=asyncio.create_task(relay.pipe_bytes(source,dest,'down'))
  try:
   await asyncio.wait_for(relay.blocked['down'].wait(),.5);self.assertFalse(dest.chunks)
   relay.resume('down');source.queue.put_nowait(b'synthetic');await until(lambda:bool(dest.chunks))
  finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

class DriverBarrier(unittest.IsolatedAsyncioTestCase):
 async def test_actual_paced_hook_arms_down_before_ack_without_blocking_up(self):
  import base64,time
  from scripts.v2_mixed_tls import PacedWire,Timeline
  relay=TcpRelay(1)
  async def observe(_):pass
  wire=PacedWire(None,None,'half_open',None,timeline=Timeline(),observe=observe)
  wire.fault_relay=relay;wire.input_end=time.monotonic();wire.turn_acks=0
  event=dict(pcm=base64.b64encode(b'\x01\x00'*2400).decode(),start=0,end=2400)
  await wire.before_ack(event)
  self.assertFalse(relay.gates['down'].is_set())
  self.assertTrue(relay.gates['up'].is_set())
  self.assertFalse(relay.blocked['down'].is_set()) # arming isn't observed traffic
 async def test_normal_hook_does_not_pause_relay(self):
  import base64,time
  from scripts.v2_mixed_tls import PacedWire,Timeline
  relay=TcpRelay(1)
  async def observe(_):pass
  wire=PacedWire(None,None,'normal_close',None,timeline=Timeline(),observe=observe)
  wire.fault_relay=relay;wire.input_end=time.monotonic();wire.turn_acks=0
  await wire.before_ack(dict(pcm=base64.b64encode(b'\x01\x00'*2400).decode(),start=0,end=2400))
  self.assertTrue(relay.gates['down'].is_set());self.assertTrue(relay.gates['up'].is_set())

if __name__=='__main__':unittest.main(verbosity=2)
