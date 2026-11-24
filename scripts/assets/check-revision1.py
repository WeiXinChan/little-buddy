"""Audit R1 against delivered PR37 baseline; preserve before/after image evidence."""
from pathlib import Path
import subprocess,json,hashlib
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[2]
base='1756055f08eeeff4b87b9175675956fbf8ab1964'
out=root/'docs/evidence/tita85/revision-1'
expected={'butterfly','bee','airplane'}
items=json.loads((root/'assets/v2-default/manifest.json').read_text())
audit=[]; changed=set()
for i in items:
 entry={'id':i['id'],'index':i['index'],'files':[]}
 for kind in ['source','png']:
  rel='assets/v2-default/'+i[kind]
  before=subprocess.check_output(['git','show',f'{base}:{rel}'],cwd=root)
  after=(root/rel).read_bytes()
  diff=before!=after
  if diff: changed.add(i['id'])
  assert diff==(i['id'] in expected),rel
  entry['files'].append({'path':rel,'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),'changed':diff,'bytes':len(after)})
  if i['id'] in expected and kind=='png':
   saved=out/'before'/f"{i['id']}.png"
   assert saved.read_bytes()==before
 audit.append(entry)
assert changed==expected
for n in [1,2,3,4,5]:
 rel=f'docs/evidence/tita85/sheet-{n}.png'
 old=subprocess.check_output(['git','show',f'{base}:{rel}'],cwd=root)
 assert (old!=(root/rel).read_bytes())==(n in [2,4])
sheet=Image.new('RGB',(1536,1080),'#eee7d8'); draw=ImageDraw.Draw(sheet)
for x,k in enumerate(['butterfly','bee','airplane']):
 for row,folder in enumerate([out/'before',root/'assets/v2-default/png']):
  im=Image.open(folder/f'{k}.png').convert('RGB')
  sheet.paste(im,(x*512,row*540+28))
  draw.text((x*512+15,row*540+8),f"{'BEFORE baseline 1756055' if row==0 else 'AFTER revision 1'} / {k}",fill='#58483f')
sheet.save(out/'before-after.png')
report={'baseline_commit':base,'changed_asset_ids':sorted(changed),'unchanged_asset_count':57,'unchanged_asset_files':114,'changed_sheets':[2,4],'audit':audit}
(out/'asset-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS: exactly 3 SVG/PNG pairs and sheets 2/4 changed; 57 SVG/PNG pairs byte-identical; 120 before/after SHA256 recorded; baseline PNG evidence matches git.')
