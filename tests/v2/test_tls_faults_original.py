import sys,pathlib,asyncio,base64,json,ssl,subprocess,tempfile,unittest
sys.path.insert(0,str(pathlib.Path.cwd()))
from contextlib import asynccontextmanager
from unittest.mock import patch
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from backend.v2.server import voice_server
from backend.v2.voice import VoicePeer
from backend.v2.fixture import SyntheticProviders,SyntheticPolicy

async def until(pred):
 async with asyncio.timeout(3):
  while not pred():await asyncio.sleep(.005)

class Provider(SyntheticProviders):
 def __init__(self,stubborn=False):self.stubborn=stubborn;self.release=asyncio.Event();self.entered=0;self.exited=0;self.active=0;self.peak=0
 @asynccontextmanager
 async def synthesize(self,text,rate):
  self.entered+=1;self.active+=1;self.peak=max(self.peak,self.active)
  async def frames():
   yield b'\x01\x00'*2400
  try:yield frames()
  finally:
   self.active-=1;self.exited+=1
 @asynccontextmanager
 async def answer(self,text,context):
  async def sentences():
   yield '合成回答。'
   await self.release.wait()
  try:yield sentences()
  finally:
   if self.stubborn:await self.release.wait()

class Faults(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();root=pathlib.Path(self.temp.name)
  subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-keyout',str(root/'key'),'-out',str(root/'cert')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  self.tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);self.tls.load_cert_chain(root/'cert',root/'key');self.client=ssl.create_default_context(cafile=str(root/'cert'));self.peers=[]
  peers=self.peers
  class ObservedPeer(VoicePeer):
   def __init__(self,*a,**k):super().__init__(*a,**k);self.retained=set();self.retired_peak=0;self.run_finished=False;peers.append(self)
   def track_retired(self,task):
    self.retained.add(task);super().track_retired(task);self.retired_peak=max(self.retired_peak,len(self.retired_tasks))
   async def run(self):
    try:return await super().run()
    finally:self.run_finished=True
  self.patcher=patch('backend.v2.server.VoicePeer',ObservedPeer);self.patcher.start()
 async def asyncTearDown(self):self.patcher.stop();self.temp.cleanup()
 def connect(self,port):return connect(f'wss://localhost:{port}/v2/voice',ssl=self.client,additional_headers={'Authorization':'Bearer '+'SyntheticOnly'*4})
 async def start(self,ws):
  epoch=0;seq=0
  async def send(kind,**kw):
   nonlocal seq
   await ws.send(json.dumps(dict(v=2,type=kind,epoch=epoch,seq=seq,**kw)));seq+=1
  await send('wake');await send('advance',revision=1);await send('input',pcm=base64.b64encode(b'\x01\x00'*320).decode());await send('probe',revision=1)
  async with asyncio.timeout(2):
   while json.loads(await ws.recv())['type']!='endpoint':pass
   await send('seal',revision=1)
   while True:
    e=json.loads(await ws.recv())
    if e['type']=='decision':break
   epoch=1;seq=0;await send('stop',intent=e['intent'])
   while True:
    e=json.loads(await ws.recv())
    if e['type']=='open':await send('bind',player='synthetic-player')
    if e['type']=='bound':bound=e['identity']
    if e['type']=='audio':e['_bound_identity']=bound;return e
 async def test_real_tls_abort_then_new_connection_has_no_old_session_or_output(self):
  p=Provider()
  async with voice_server('127.0.0.1',0,self.tls,'SyntheticOnly'*4,p,SyntheticPolicy()) as server:
   port=server.sockets[0].getsockname()[1]
   async with self.connect(port) as ws:
    audio=await self.start(ws);old=self.peers[0];old_budget=old.input_budget;old_generation=old.generation
    ws.transport.abort()
   await until(lambda:old.run_finished)
   self.assertTrue(old.closed);self.assertFalse(old.quarantined);self.assertEqual(p.active,0)
   self.assertEqual((p.entered,p.exited),(1,1))
   self.assertFalse(old.session.context().get('heard',()));self.assertFalse(old.session.pending)
   self.assertTrue(all(t.done() for t in old.retained));self.assertTrue(old_generation.done())
   async with self.connect(port) as ws2:
    await until(lambda:len(self.peers)==2);fresh=self.peers[1]
    self.assertIsNot(fresh.session,old.session);self.assertIsNot(fresh.input_budget,old_budget)
    self.assertFalse(fresh.session.context().get('heard',()));self.assertFalse(fresh.session.pending)
    # Same player string is deliberately reused: server stream/identity must be new.
    p.release.set();audio2=await self.start(ws2)
    self.assertNotEqual(audio2['_bound_identity']['session'],audio['_bound_identity']['session'])
    await ws2.send(json.dumps(dict(v=2,type='ack',epoch=1,seq=2,identity=dict(audio2['_bound_identity'],sequence=0),player=audio2['player'],stream=audio2['stream'],segment=audio2['segment'],head=audio2['end'])))
    await until(lambda:bool(fresh.session.context().get('heard')))
    self.assertEqual(len(fresh.session.context()['heard']),1)
    await ws2.close()
   await until(lambda:self.peers[1].run_finished)
   self.assertEqual(p.active,0);self.assertEqual(p.entered,p.exited)
   print('TLS_ABORT_RECONNECT',json.dumps({'connections':len(self.peers),'entered':p.entered,'exited':p.exited,'active_peak':p.peak,'retired_peaks':[x.retired_peak for x in self.peers],'all_retained_done':all(t.done() for x in self.peers for t in x.retained)}))
 async def test_unconfirmed_old_close_quarantines_server_instead_of_cross_lease(self):
  p=Provider(stubborn=True)
  try:
   async with voice_server('127.0.0.1',0,self.tls,'SyntheticOnly'*4,p,SyntheticPolicy()) as server:
    port=server.sockets[0].getsockname()[1]
    async with self.connect(port) as ws:
     await self.start(ws);old=self.peers[0];ws.transport.abort()
    await until(lambda:old.run_finished)
    self.assertTrue(old.quarantined)
    async with self.connect(port) as blocked:
     with self.assertRaises(ConnectionClosed) as caught:await blocked.recv()
     self.assertEqual(caught.exception.rcvd.code,1013)
    self.assertEqual(len(self.peers),1)
    self.assertLessEqual(p.peak,1)
  finally:
   p.release.set()
   for peer in self.peers:
    tasks=peer.retained|{t for t in [peer.generation,peer.recognition] if t is not None}
    await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),2)
   self.assertEqual(p.active,0)
if __name__=='__main__':unittest.main(verbosity=2)
