"""Synthetic Pulse source -> AVD microphone. No replacement of Android AudioRecord."""
import subprocess,json,hashlib,re,sys
from pathlib import Path
root=Path('app/src/androidTest/assets/m06-commands')
allowed={r['name']:r['sha256'] for r in json.loads((root/'cases.json').read_text())['cases']}
allowed.update({r['name']:r['sha256'] for r in json.loads((root/'provenance.json').read_text())['rows']})
paths={name:root/(name+'.wav') for name in allowed}
protocol=Path('app/src/androidTest/assets/m06-protocol-v2')
for row in json.loads((protocol/'provenance.json').read_text()):
 name='v2_'+row['name'];allowed[name]=row['sha256'];paths[name]=protocol/(row['name']+'.wav')
short=json.loads((protocol/'derived-confirm.json').read_text());allowed[short['name']]=short['sha256'];paths[short['name']]=protocol/'confirm_exit_short.wav'
production=Path('app/src/main/assets/management')
for row in json.loads((production/'provenance.json').read_text())['rows']:
 name='prod_'+row['name'];allowed[name]=row['sha256'];paths[name]=production/(row['name']+'.wav')
p=subprocess.Popen(['adb','shell','am','instrument','-w','-r','-e','class','com.littlebuddy.V2MicrophoneCommandTest','com.littlebuddy.sim.v2.test/com.littlebuddy.SimUiRunner'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
output=[]
try:
 for line in p.stdout:
  print(line,end='',flush=True);output.append(line)
  if line.startswith('INSTRUMENTATION_STATUS: m06_request='):
   q=json.loads(line.strip().split('=',1)[1]);name=q['name'];nonce=q['nonce'];private=q['root'];pkg=q['package']
   if pkg!='com.littlebuddy.sim.v2' or q['user']!=0:raise ValueError('target user/package')
   if name not in allowed or not re.fullmatch(r'[a-z0-9_.]+',name) or not re.fullmatch(r'[a-f0-9-]{36}',nonce):raise ValueError('fixture/nonce allowlist')
   if not re.fullmatch(r'/[A-Za-z0-9_./]+',private) or not private.endswith('/'+pkg+'/files'):raise ValueError('private root')
   pwd=subprocess.check_output(['adb','shell','run-as',pkg,'pwd'],text=True,timeout=5).strip()
   canonical=subprocess.check_output(['adb','shell','run-as',pkg,'readlink','-f',private],text=True,timeout=5).strip()
   subprocess.run(['adb','shell','run-as',pkg,'test','-d',private],check=True,timeout=5)
   if canonical!=private:raise ValueError('private root mismatch')
   print(json.dumps(dict(event='handshake_ready',nonce=nonce,root=private,run_as_pwd=pwd)),flush=True)
   path=paths[name]
   if hashlib.sha256(path.read_bytes()).hexdigest()!=allowed[name] or q['sha256']!=allowed[name]:raise ValueError('fixture hash')
   subprocess.run(['paplay','--device=m06_input',str(path)],check=True,timeout=20)
   reply=json.dumps(dict(nonce=nonce,name=name,sha256=allowed[name],state='completed',playback_exit=0))
   subprocess.run(['adb','shell','run-as',pkg,'tee',private+'/m06-'+nonce+'.json'],input=reply,text=True,stdout=subprocess.PIPE,check=True,timeout=5)
 result=p.wait(timeout=30)
 if result or not any('OK (1 test)' in x for x in output):sys.exit(1)
except Exception:
 # Let the bounded instrumentation await write real timeline/proof before cleanup.
 try:p.wait(timeout=40)
 except subprocess.TimeoutExpired:pass
 raise
finally:
 if p.poll() is None:p.terminate();p.wait(timeout=10)
