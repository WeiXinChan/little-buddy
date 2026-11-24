"""Loopback TLS websocket test, synthetic PCM; no phone/acoustic claim."""
import asyncio
import base64
import json
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from backend.v2.server import voice_server
from backend.v2.fixture import SyntheticProviders, SyntheticPolicy


class TlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_duplex_wire_stream_coordinates_and_auth(self):
        with tempfile.TemporaryDirectory(prefix='v2-tls-') as directory:
            root = Path(directory)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
                            '-keyout',str(root/'key'),'-out',str(root/'cert')],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(root/'cert',root/'key')
            client_tls = ssl.create_default_context(cafile=str(root/'cert'))
            token = 'SyntheticOnly' * 4
            async with voice_server('127.0.0.1',0,tls,token,SyntheticProviders(),SyntheticPolicy()) as server:
                port = server.sockets[0].getsockname()[1]
                with self.assertRaises(InvalidStatus) as rejected:
                    async with connect(f'wss://localhost:{port}/v2/voice',ssl=client_tls,
                                       additional_headers={'Authorization': 'Bearer wrong'}):
                        self.fail('unauthenticated peer admitted')
                self.assertEqual(rejected.exception.response.status_code,401)
                async with connect(f'wss://localhost:{port}/v2/voice',ssl=client_tls,
                                   additional_headers={'Authorization': 'Bearer '+token}) as socket:
                    epoch, sequence = 0, 0
                    async def send(kind, **fields):
                        nonlocal sequence
                        await socket.send(json.dumps(dict(v=2,type=kind,epoch=epoch,seq=sequence,**fields)))
                        sequence += 1
                    await send('wake'); await send('advance',revision=1)
                    await send('input',pcm=base64.b64encode(b'\x01\x00'*320).decode())
                    await send('probe',revision=1)
                    async with asyncio.timeout(3):
                        endpoint = json.loads(await socket.recv())
                        self.assertEqual(endpoint['type'],'endpoint')
                        await send('seal',revision=1)
                        decision = json.loads(await socket.recv())
                        self.assertEqual(decision['meaning'],'new_turn')
                        epoch, sequence = 1, 0
                        await send('stop',intent=decision['intent'])
                        frames, head, ack_seq = 0, 0, 0
                        bound = None
                        while True:
                            event = json.loads(await socket.recv())
                            if event['type']=='open': await send('bind',player='test-native-coordinate')
                            elif event['type']=='bound': bound = event
                            elif event['type']=='audio':
                                pcm=base64.b64decode(event['pcm'])
                                self.assertEqual(event['start'],head)
                                self.assertEqual(len(pcm),4800)
                                head += 2400; frames += 1
                                self.assertEqual(event['end'],head)
                                identity = dict(bound['identity'],sequence=ack_seq); ack_seq += 1
                                await send('ack',identity=identity,player=bound['player'],stream=bound['stream'],
                                           segment=event['segment'],head=head)
                            elif event['type']=='reply_end': break
                        self.assertEqual((frames,head),(5,12000))
                        await send('end')
