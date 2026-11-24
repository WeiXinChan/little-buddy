"""Versioned protocol PCM replay manifest, real model hits; historical corpus unchanged."""
import sys,array,wave,json,hashlib
from pathlib import Path
from reset_probe import model
old=Path('app/src/androidTest/assets/m06-commands');out=Path('app/src/androidTest/assets/m06-protocol-v2');out.mkdir(exist_ok=True)
source=Path('../protocol-tts')
for p in source.glob('*.wav'):(out/p.name).write_bytes(p.read_bytes())
(out/'provenance.json').write_bytes((source/'provenance.json').read_bytes())
def read(name):
 p=(out if (out/(name+'.wav')).exists() else old)/(name+'.wav')
 with wave.open(str(p)) as w:return array.array('h',w.readframes(w.getnframes()))
# Each complete fixture retains recorded padding; physical sample coordinates are explicit.
cases=[('clear_cancel',['cancel'],['取消']),('clear_exit',['exit'],['退出管理']),('uncertain_prompt_confirm',['negative_pause_cancel_1.6','confirm_exit'],['确认退出提示','取消']),('deny_confirm_stays',['negative_pause_cancel_1.6','deny_confirm'],['确认退出提示']),('quote_confirm_stays',['negative_pause_cancel_1.6','quote_confirm'],['确认退出提示']),('continue_then_cancel',['negative_pause_cancel_1.6','continue_management','cancel'],['确认退出提示','继续管理','取消']),('old_confirm_rejected',['confirm_exit'],[])]
cases += [('bie_confirm_stays',['negative_pause_cancel_1.6','short_bie_confirm'],['确认退出提示']),('bu_confirm_stays',['negative_pause_cancel_1.6','short_bu_confirm'],['确认退出提示']),('buffered_old_confirm_rejected',['negative_pause_cancel_1.6','confirm_exit'],['确认退出提示'])]
# DSP negative controls only: source cut points are from the preserved paths8
# raw KWS timestamp table; these are not natural speech or production constants.
q=json.loads((out/'evidence.json').read_text())
quote=next(x for x in q['cases'] if x['name']=='quote_confirm_stays')
offset=quote['segments'][1]['start_sample'];h=next(x for x in quote['hits'] if x['name']=='确认退出')
recipes=[]
for name,base,cut in [('splice_bu_continue','short_bu_confirm',17279),('splice_quote_continue','quote_confirm',h['start']-offset)]:
 data=read(base)[:cut]+read('continue_management')[8000:-32000]
 p=out/(name+'.wav')
 with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(data.tobytes())
 recipes.append(dict(name=name,prefix_source=base,prefix_end_sample=cut,continuation_source='continue_management',continuation_start_sample=8000,continuation_trim_tail=32000,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),scope='DSP-only synthetic negative; no claim natural pronunciation'))
(out/'splice-provenance.json').write_text(json.dumps(recipes,ensure_ascii=False,indent=2)+'\n')
cases += [('negative_continue_does_not_clear',['negative_pause_cancel_1.6','splice_bu_continue','cancel','confirm_exit'],['确认退出提示','确认退出提示','取消']),('quoted_continue_does_not_clear',['negative_pause_cancel_1.6','splice_quote_continue','cancel','confirm_exit'],['确认退出提示','确认退出提示','取消'])]
rows=[];lines=[]
for name,parts,expected in cases:
 pcm=array.array('h')
 segments=[]
 for part in parts:
  a=read(part);segments.append({'source':part,'start_sample':len(pcm),'samples':len(a)});pcm.extend(a);pcm.extend([0]*32000)
 archive=Path('../protocol-v2-combined');archive.mkdir(exist_ok=True);p=archive/(name+'.wav')
 with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm.tobytes())
 k=model();s=k.create_stream();hits=[];last=-1
 for pos in range(0,len(pcm),320):
  s.accept_waveform(16000,[x/32768 for x in pcm[pos:pos+320]])
  while k.is_ready(s):
   k.decode_stream(s);r=k.keyword_spotter.get_result(s)
   if r.keyword:
    tail=int((r.timestamps[-1]+.12)*16000)
    if tail>last:last=tail;hits.append(dict(frame=pos//320,name=r.keyword,start=int(r.timestamps[0]*16000),end=tail));break
 rows.append(dict(name=name,expected=expected,segments=segments,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),hits=hits))
 lines.append('case\t'+name+'\ttrue\t'+(','.join(expected) or 'NONE')+'\t'+','.join(parts))
 for h in hits:lines.append('hit\t'+str(h['frame'])+'\t'+h['name']+'\t'+str(h['start'])+'\t'+str(h['end']))
(out/'native-replay.tsv').write_text('\n'.join(lines)+'\n');(out/'evidence.json').write_text(json.dumps({'protocol':2,'paths':8,'score':1.5,'threshold':.25,'trailing':2,'prompt_ack':'Kotlin replay acknowledges at prompt event; device uses actual UI acknowledgment and current captured sample','cases':rows},ensure_ascii=False,indent=2)+'\n');print('native protocol cases',len(rows))
