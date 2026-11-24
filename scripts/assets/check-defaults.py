from pathlib import Path
import json,hashlib,collections,xml.etree.ElementTree as ET
from PIL import Image
root=Path(__file__).resolve().parents[2]; out=root/'assets/v2-default'
items=json.loads((out/'manifest.json').read_text())
assert collections.Counter(i['category'] for i in items)=={'animal':24,'daily':16,'tool':8,'scene':8,'fantasy':4}
assert len({i['id'] for i in items})==60
hashes=set()
for i in items:
 for field,hkey in [('source','source_sha256'),('png','png_sha256')]:
  assert hashlib.sha256((out/i[field]).read_bytes()).hexdigest()==i[hkey],i['id']
 tree=ET.parse(out/i['source'])
 assert not any(n.tag.split('}')[-1] in ['text','image','script','foreignObject'] for n in tree.iter())
 for n in tree.iter(): assert not any('href' in k or k.startswith('on') for k in n.attrib)
 im=Image.open(out/i['png']); im.load(); assert im.size==(512,512)
 assert i['png_sha256'] not in hashes; hashes.add(i['png_sha256'])
 assert i['visual_status']=='author_reviewed_independent_pending'
assert next(i for i in items if i['id']=='turtle')['name']=='乌龟'
print('PASS: 60 PNG decode/dimensions; 24/16/8/8/4 counts; 120 hashes; distinct pixels; inert local SVG; author-review coverage. Runtime/phone untested.')
