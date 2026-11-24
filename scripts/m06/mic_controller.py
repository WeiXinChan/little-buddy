"""Synthetic Pulse source -> AVD microphone. No replacement of Android AudioRecord."""
import subprocess,json,hashlib,re,sys
from pathlib import Path
root=Path('app/src/androidTest/assets/m06-commands')
allowed={r['name']:r['sha256'] for r in json.loads((root/'cases.json').read_text())['cases']}
allowed.update({r['name']:r['sha256'] for r in json.loads((root/'provenance.json').read_text())['rows']})
p=subprocess.Popen(['adb','shell','am','instrument','-w','-r','-e','class','com.littlebuddy.V2MicrophoneCommandTest','com.littlebuddy.sim.v2.test/com.littlebuddy.SimUiRunner'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
output=[]
try:
 for line in p.stdout:
  print(line,end='',flush=True);output.append(line)
  if line.startswith('INSTRUMENTATION_STATUS: m06_audio='):
   name=line.strip().split('=',1)[1]
   if name not in allowed or not re.fullmatch(r'[a-z0-9_.]+',name):raise ValueError('fixture allowlist')
   path=root/(name+'.wav')
   if hashlib.sha256(path.read_bytes()).hexdigest()!=allowed[name]:raise ValueError('fixture hash')
   subprocess.run(['paplay','--device=m06_input',str(path)],check=True,timeout=20)
   subprocess.run(['adb','shell','run-as','com.littlebuddy.sim.v2','touch','files/m06-audio-'+name+'.done'],check=True,timeout=5)
 result=p.wait(timeout=30)
 if result or not any('OK (1 test)' in x for x in output):sys.exit(1)
finally:
 if p.poll() is None:p.terminate();p.wait(timeout=10)
