"""Optional bounded capture of the private synthetic Pulse MONITOR, never a host mic."""
import hashlib,json,os,selectors,stat,subprocess,threading,time
from pathlib import Path
class MonitorProbe:
 def __init__(self,metadata,directory):
  assert os.environ.get('BUDDY_SYNTHETIC_AVD_PROBE')=='1'
  assert metadata['name']=='enter' and metadata['sha256']=='c53eb146203afc87fd8092f60721e49a20d30baaa0811da715788a40fe582e34'
  server=os.environ['PULSE_SERVER'];assert server.startswith('unix:')
  socket=Path(server[5:]);parent=socket.parent
  assert str(parent)==str(Path(os.environ['RUNNER_TEMP'])/'v2-avd') and stat.S_IMODE(parent.stat().st_mode)==0o700 and parent.stat().st_uid==os.getuid()
  self.path=directory/('mic-host-'+metadata['nonce']+'.s16le')
  self.info=dict(metadata,fixture_sha256=metadata['sha256'],source='private m06_input.monitor, synthetic paplay only',format='s16le',rate=16000,channels=1,byte_cap=256000,wall_limit_s=8,started_unix_ns=time.time_ns(),started_monotonic_ns=time.monotonic_ns())
  self.end=time.monotonic()+8;self.stop_event=threading.Event();self.size=0
  self.process=subprocess.Popen(['parec','--device=m06_input.monitor','--raw','--format=s16le','--rate=16000','--channels=1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  self.worker=threading.Thread(target=self._read,name='synthetic-monitor-bound',daemon=True);self.worker.start()
 def _read(self):
  try:
   with selectors.DefaultSelector() as selector,self.path.open('wb') as out:
    selector.register(self.process.stdout,selectors.EVENT_READ)
    while not self.stop_event.is_set() and self.size<256000 and time.monotonic()<self.end:
     if not selector.select(min(.1,max(0,self.end-time.monotonic()))):continue
     b=os.read(self.process.stdout.fileno(),min(8192,256000-self.size))
     if not b:break
     out.write(b);self.size+=len(b)
  except Exception as e:self.info['read_error']=type(e).__name__
 def finish(self):
  self.stop_event.set();self.worker.join(1)
  assert not self.worker.is_alive(), 'bounded monitor consumer did not exit'
  if self.process.poll() is None:self.process.terminate()
  try:_,err=self.process.communicate(timeout=2)
  except subprocess.TimeoutExpired:self.process.kill();_,err=self.process.communicate(timeout=2)
  self.info.update(bytes=self.size,samples=self.size//2,seconds=self.size/32000,exit=self.process.returncode,stderr=err.decode(errors='replace')[-65536:],ended_unix_ns=time.time_ns(),ended_monotonic_ns=time.monotonic_ns(),capture_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),file=self.path.name,stop='owned probe cleanup or cap; exit is diagnostic')
  self.path.with_suffix('.json').write_text(json.dumps(self.info,indent=2));return self.info
