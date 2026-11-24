"""Original, deterministic vector artwork; optional CairoSVG/Pillow render dependencies."""
from pathlib import Path
import json, hashlib, math
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'assets/v2-default'
INK='#58483f'; CREAM='#fff6e6'; GOLD='#e7ad58'; GREEN='#79a887'; BLUE='#84b5c7'; PINK='#e7a1a0'
def ellipse(x,y,rx,ry,c): return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{c}" stroke="{INK}" stroke-width="2.5"/>'
def circle(x,y,r,c): return ellipse(x,y,r,r,c)
def path(d,c,sw=5): return f'<path d="{d}" fill="{c}" stroke="{INK}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>'
def line(d,c=INK,w=5): return f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'
def rect(x,y,w,h,c,r=15): return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{c}" stroke="{INK}" stroke-width="5"/>'
def eyes(x=256,y=246,gap=36):
 return circle(x-gap,y,7,INK)+circle(x+gap,y,7,INK)+circle(x-gap-2,y-2,2,CREAM)+circle(x+gap-2,y-2,2,CREAM)
def face(c,ears='round',extra=''):
 s=''
 if ears=='round': s=circle(176,177,37,c)+circle(336,177,37,c)
 if ears=='point': s=path('M164 213 L169 125 L222 180',c)+path('M292 180 L343 125 L348 213',c)
 if ears=='long': s=ellipse(210,139,26,82,c)+ellipse(301,139,26,82,c)+ellipse(210,133,11,53,PINK)+ellipse(301,133,11,53,PINK)
 s+=ellipse(256,265,115,109,c)+ellipse(256,307,60,36,CREAM)+eyes()+path('M244 288 Q256 280 268 288 L256 300 Z',INK,2)+line('M256 300 L256 310 Q242 322 231 310 M256 310 Q270 322 282 310',w=3)
 return s+extra
def animal(k):
 if k in ['cat','dog','rabbit','bear','fox','panda','tiger','lion','pig','cow','mouse','monkey']:
  colors=dict(cat=GOLD,dog='#c38e62',rabbit=CREAM,bear='#b28969',fox='#d99058',panda=CREAM,tiger=GOLD,lion=GOLD,pig=PINK,cow=CREAM,mouse='#b9b4ba',monkey='#b88d65')
  s=''
  if k=='lion': s=ellipse(256,256,153,149,'#b77a44')
  if k=='cow': s=path('M170 190 Q139 160 158 129 L197 174',GOLD)+path('M315 174 L354 129 Q373 160 342 190',GOLD)
  if k=='monkey': s+=line('M317 361 Q413 398 404 319 Q396 287 373 307', '#b88d65',15)
  if k in ['cat','fox']: s+=path('M320 373 Q402 368 386 300 Q363 326 342 326',colors[k])
  s+=ellipse(256,349,73,67,colors[k])+ellipse(256,361,43,45,CREAM)+ellipse(211,406,30,15,colors[k])+ellipse(302,406,30,15,colors[k])
  s+='<g transform="translate(38 15) scale(.85)">'
  s+=face(colors[k], 'long' if k=='rabbit' else 'point' if k in ['cat','fox','tiger'] else 'round')
  if k=='monkey': s+=ellipse(217,248,36,46,'#e5c7a2')+ellipse(295,248,36,46,'#e5c7a2')+ellipse(256,298,63,42,'#e5c7a2')+eyes()+line('M229 305 Q256 331 283 305',w=4)
  if k=='fox': s+=path('M147 265 Q166 313 247 324 L212 268',CREAM,0)+path('M365 265 Q346 313 265 324 L300 268',CREAM,0)
  if k=='dog': s+=ellipse(157,242,28,73,'#886546')+ellipse(354,242,28,73,'#886546')
  if k=='panda': s+=ellipse(217,245,23,30,INK)+ellipse(295,245,23,30,INK)+circle(217,243,6,CREAM)+circle(295,243,6,CREAM)+circle(176,177,34,INK)+circle(336,177,34,INK)
  if k=='pig': s+=ellipse(256,298,45,29,'#db8992')+circle(240,297,6,INK)+circle(272,297,6,INK)
  if k=='cow': s+=ellipse(190,208,28,24,INK)+ellipse(256,300,58,34,PINK)+circle(234,300,5,INK)+circle(278,300,5,INK)
  if k=='tiger': s+=line('M227 165 L240 196 M256 159 L256 193 M285 166 L273 195 M149 262 L184 272 M363 262 L328 272',w=10)
  if k=='cat': s+=line('M192 293 L128 279 M191 307 L126 314 M320 293 L384 279 M321 307 L386 314',w=3)
  if k=='mouse': s+=circle(176,177,24,PINK)+circle(336,177,24,PINK)
  return s+'</g>'+(ellipse(201,353,17,32,INK)+ellipse(311,353,17,32,INK)+ellipse(211,406,30,15,INK)+ellipse(302,406,30,15,INK) if k=='panda' else '')
 if k=='elephant': return ellipse(256,275,123,108,'#a5b6be')+ellipse(142,245,54,83,'#a5b6be')+ellipse(370,245,54,83,'#a5b6be')+ellipse(142,245,33,59,'#c5b8bd')+ellipse(370,245,33,59,'#c5b8bd')+eyes(y=255)+path('M231 287 L230 365 Q230 414 278 402 Q300 398 300 374 L279 371 Q274 390 266 372 L279 287','#a5b6be')
 if k=='giraffe':
  return rect(215,248,85,168,GOLD,35)+line('M215 184 L206 133 M296 184 L305 133',w=12)+circle(206,128,13,'#b28657')+circle(305,128,13,'#b28657')+ellipse(170,194,34,17,GOLD)+ellipse(341,194,34,17,GOLD)+ellipse(256,234,78,73,GOLD)+eyes(y=222,gap=27)+ellipse(256,266,59,26,'#f4d39a')+circle(236,266,4,INK)+circle(276,266,4,INK)+path('M234 322 L250 306 L269 323 L256 344 Z','#b28657')+circle(274,382,18,'#b28657')
 if k in ['duck','penguin','owl','chicken']:
  c={'duck':GOLD,'penguin':'#657782','owl':'#b19476','chicken':CREAM}[k]
  s=ellipse(256,283,101,119,c)+ellipse(168,295,28,62,c)+ellipse(344,295,28,62,c)+path('M205 399 L190 417 L238 417 M280 417 L324 417 L307 399',GOLD)
  if k=='penguin': s+=ellipse(256,301,64,86,CREAM)
  if k=='owl': s+=circle(216,246,37,CREAM)+circle(296,246,37,CREAM)+path('M168 205 L174 151 L219 180 M293 180 L338 151 L344 205',c)
  if k=='chicken': s+=circle(238,168,19,'#d58979')+circle(261,156,20,'#d58979')+circle(281,172,17,'#d58979')
  return s+eyes(y=245)+(ellipse(256,281,34,13,'#dc9c53') if k=='duck' else path('M236 272 L276 272 L256 293 Z',GOLD))
 if k in ['fish','whale','turtle']:
  if k=='fish': return path('M349 255 L419 190 L419 322 Z',GOLD)+ellipse(243,256,128,86,BLUE)+path('M226 177 L265 140 L287 181',BLUE)+path('M225 333 L265 370 L284 331',BLUE)+circle(176,238,9,INK)+line('M148 276 Q160 286 174 276')+path('M251 235 Q301 256 251 282', '#b3d4db')
  if k=='whale': return path('M345 294 Q391 289 407 240 L445 218 L439 279 Q424 340 349 349',BLUE)+ellipse(237,300,136,83,BLUE)+ellipse(227,338,111,37,'#c5dfdf')+circle(158,283,9,INK)+path('M251 318 Q316 322 283 377',BLUE)+line('M234 207 Q235 177 211 166 M236 206 Q242 175 264 163',BLUE,9)
  return ellipse(256,281,117,83,GREEN)+ellipse(384,280,43,35,'#acc997')+ellipse(187,352,30,19,'#acc997')+ellipse(309,352,30,19,'#acc997')+ellipse(184,212,28,18,'#acc997')+ellipse(308,211,28,18,'#acc997')+path('M143 270 L102 287 L143 302',GREEN)+path('M226 244 L277 242 L300 280 L277 317 L230 317 L207 279 Z','#99bc91')+circle(398,270,5,INK)
 if k in ['butterfly','bee']:
  # Dorsal view: all three bilateral thoracic leg pairs remain in front of wings.
  # Head has two separate antennae; no foot is hidden behind the abdomen.
  if k=='butterfly':
   wings=ellipse(172,217,68,88,'#dba0a5')+ellipse(340,217,68,88,'#dba0a5')+ellipse(184,328,55,61,GOLD)+ellipse(328,328,55,61,GOLD)+circle(151,202,23,CREAM)+circle(361,202,23,CREAM)
   abdomen=ellipse(256,319,17,68,INK)
  else:
   wings=ellipse(174,225,61,84,'#c9e0df')+ellipse(338,225,61,84,'#c9e0df')+ellipse(187,307,45,50,'#dce9e1')+ellipse(325,307,45,50,'#dce9e1')
   abdomen=ellipse(256,326,49,68,GOLD)+path('M212 300 Q256 312 300 300 L304 317 Q256 329 208 317 Z',INK,0)+path('M210 339 Q256 353 302 339 L296 358 Q256 372 216 358 Z',INK,0)
  legs=''.join(line(d,w=6) for d in [
   'M242 235 L216 212 L192 181','M240 252 L208 253 L180 272','M243 270 L198 312 L175 354',
   'M270 235 L296 212 L320 181','M272 252 L304 253 L332 272','M269 270 L314 312 L337 354'])
  antennae=line('M246 177 Q226 153 225 121 M266 177 Q286 153 287 121',w=5)+(circle(225,119,6,INK)+circle(287,119,6,INK) if k=='butterfly' else '')
  head=circle(256,192,25,INK)+circle(248,187,3,CREAM)+circle(264,187,3,CREAM)
  return wings+abdomen+legs+ellipse(256,251,25,38,INK)+antennae+head
 if k=='frog': return ellipse(256,303,112,83,GREEN)+circle(193,223,40,GREEN)+circle(319,223,40,GREEN)+circle(193,223,23,CREAM)+circle(319,223,23,CREAM)+circle(193,223,9,INK)+circle(319,223,9,INK)+ellipse(256,337,65,38,'#bad29a')+line('M207 287 Q256 321 305 287')+ellipse(157,371,47,23,GREEN)+ellipse(355,371,47,23,GREEN)
 if k=='snail': return path('M102 360 Q117 310 223 324 L342 323 L350 256 Q379 230 396 261 L396 359 Q302 393 102 360', '#c3cb93')+circle(245,288,84,'#d6aa7c')+line('M265 306 Q211 333 203 285 Q200 241 247 242 Q281 241 284 275 Q287 300 264 296 Q249 294 254 279',w=8)+line('M358 254 L348 218 M386 252 L402 216')+circle(348,214,9,INK)+circle(402,213,9,INK)
 raise ValueError(k)
items=[]
def add(k,n,c,b,feature): items.append(dict(id=k,name=n,category=c,body=b,feature=feature))
animals='cat 猫|dog 狗|rabbit 兔|bear 熊|fox 狐狸|panda 熊猫|tiger 老虎|lion 狮子|pig 猪|cow 奶牛|mouse 老鼠|monkey 猴子|elephant 大象|giraffe 长颈鹿|duck 鸭|penguin 企鹅|owl 猫头鹰|chicken 鸡|fish 鱼|whale 鲸|turtle 乌龟|butterfly 蝴蝶|bee 蜜蜂|frog 青蛙'.split('|')
for entry in animals:
 k,n=entry.split(); add(k,n,'animal',animal(k),'背视完整主体：胸部三对共六足、头部一对触角、左右前后翅' if k in ['butterfly','bee'] else '形态辨识；仅表示常见卡通外观，不作物种精细分类')
# Distinct silhouettes for food and everyday objects.
add('apple','苹果','daily',path('M253 205 Q184 163 158 231 Q123 310 192 373 Q223 394 256 377 Q294 395 327 365 Q384 299 348 230 Q318 178 266 207','#d8937f')+line('M258 205 L269 160',w=10)+path('M270 179 Q302 138 330 158 Q320 195 270 179',GREEN),'果梗与叶、凹顶圆果')
add('banana','香蕉','daily',path('M156 195 Q172 330 337 291 L375 259 Q358 366 259 379 Q161 381 130 269 L136 202 Z','#eed18a')+line('M151 225 Q174 355 338 320','#ba9658',4),'弯曲果身')
add('pear','梨','daily',path('M231 195 Q257 167 279 198 L302 252 Q366 315 325 365 Q263 408 196 370 Q148 335 200 267 Z','#c5cb8b')+line('M255 187 L265 151',w=9),'细上宽下')
add('orange','橙子','daily',circle(256,284,104,'#e9ad68')+path('M256 181 Q288 146 322 171 Q299 203 256 181',GREEN)+line('M256 182 L254 159',w=7)+circle(205,273,4,'#c98d53')+circle(224,304,4,'#c98d53'),'圆果与果皮点')
add('watermelon','西瓜片','daily',path('M113 218 L399 218 Q380 394 256 394 Q131 394 113 218',GREEN)+path('M128 221 L384 221 Q365 374 256 374 Q147 374 128 221',CREAM)+path('M144 224 L368 224 Q347 352 256 352 Q164 352 144 224','#de958e')+''.join(ellipse(x,y,4,9,INK) for x,y in [(195,258),(250,270),(314,255),(225,313),(285,313)]),'绿皮红瓤黑籽')
add('carrot','胡萝卜','daily',path('M207 232 Q258 204 303 238 L246 400 Z','#df9e62')+path('M247 225 Q201 166 214 141 Q253 152 257 211 Q264 150 300 149 Q309 181 267 227',GREEN)+line('M218 269 L246 278 M232 317 L258 324','#b67e49',4),'锥形根与叶')
add('bread','面包','daily',path('M153 367 L153 250 Q120 215 152 185 Q177 159 213 180 Q258 144 301 179 Q344 165 368 195 Q388 224 358 250 L358 367 Z','#c99965')+path('M179 344 L179 245 Q162 215 186 208 Q207 202 219 212 Q258 181 294 211 Q334 193 337 225 L332 344 Z','#efd5a7'),'烘焙圆顶与切面')
add('rice','米饭','daily',ellipse(256,256,113,58,CREAM)+''.join(ellipse(x,y,9,4,'#e2d4b8') for x,y in [(190,241),(225,223),(267,245),(307,226),(326,263),(229,269)])+path('M134 272 L378 272 Q359 369 256 376 Q153 369 134 272',BLUE),'饭粒与碗')
add('cup','杯子','daily',ellipse(344,268,59,58,GOLD)+ellipse(344,268,32,32,CREAM)+rect(160,183,163,190,GOLD,30)+ellipse(241,186,80,20,'#a57d56'),'单个把手及杯口')
add('book','书','daily',path('M256 218 Q192 174 118 196 L118 362 Q192 340 256 382 Q320 340 394 362 L394 196 Q320 174 256 218',BLUE)+path('M256 230 Q195 192 136 211 L136 344 Q196 331 256 367 Q316 331 376 344 L376 211 Q317 192 256 230',CREAM)+line('M256 230 L256 366')+line('M161 245 Q199 239 230 254 M161 280 Q197 276 230 290 M282 254 Q315 238 350 245 M282 290 Q314 275 350 280','#b7a991',4),'展开双页不含文字')
add('ball','球','daily',circle(256,277,117,'#e2ac77')+path('M173 195 Q242 244 174 359 M338 194 Q269 247 338 359 M140 277 L373 277','none'),'球面分区')
add('umbrella','雨伞','daily',line('M256 227 L256 363 Q255 404 217 385 L209 371',w=11)+path('M108 250 Q142 123 256 123 Q370 123 404 250 Q369 225 330 250 Q293 225 256 250 Q220 225 182 250 Q144 225 108 250',BLUE)+line('M256 126 Q207 163 182 248 M256 126 Q304 163 330 248', '#678a9a',4),'伞面伞骨弯柄')
add('shoe','鞋','daily',path('M146 210 L224 210 L262 275 L357 292 Q398 311 386 358 L124 358 L124 264 Z',GOLD)+path('M124 343 L386 343 L386 366 L124 366',CREAM)+line('M226 250 L263 232 M244 273 L281 256 M264 292 L301 277',CREAM,9),'鞋底鞋口鞋带')
add('hat','帽子','daily',ellipse(256,329,154,36,'#d1a775')+path('M157 320 L181 194 Q255 158 330 194 L354 320 Z',GOLD)+path('M165 281 L345 281 L352 317 L158 317',BLUE),'帽冠帽檐')
add('clock','时钟','daily',circle(256,275,121,BLUE)+circle(256,275,100,CREAM)+''.join(line(f'M{256+86*math.sin(i*math.pi/6):.1f} {275-86*math.cos(i*math.pi/6):.1f} L{256+77*math.sin(i*math.pi/6):.1f} {275-77*math.cos(i*math.pi/6):.1f}',w=4) for i in range(12))+line('M256 209 L256 275 L301 301',w=9)+circle(256,275,9,INK),'12刻度双指针；无数字')
add('backpack','背包','daily',line('M217 191 Q217 139 256 139 Q295 139 295 191',w=13)+rect(164,190,184,213,GREEN,43)+rect(186,282,140,96,'#9ebc9b',23)+line('M194 304 L318 304')+rect(243,212,26,36,GOLD,6),'提手、主包和前袋')
# Transport and exploration.
def wheels(xs,y=356,r=29): return ''.join(circle(x,y,r,INK)+circle(x,y,r/2,CREAM) for x in xs)
add('bus','公共汽车','tool',rect(100,181,312,172,GOLD,24)+''.join(rect(x,208,48,58,'#cce0dc',7) for x in [124,186,248])+rect(314,208,70,135,'#cce0dc',7)+wheels([167,345]),'四窗、车门双轮；无品牌')
add('train','火车','tool',rect(126,200,241,145,GREEN)+rect(242,148,125,182,GREEN)+rect(263,171,78,67,'#cce0dc')+rect(145,171,34,58,INK,4)+path('M367 306 L417 345 L367 345',GOLD)+wheels([169,240,317],351),'车头驾驶室烟囱三轮')
add('bicycle','自行车','tool',circle(142,332,68,INK)+circle(142,332,57,CREAM)+circle(369,332,68,INK)+circle(369,332,57,CREAM)+line('M142 332 L205 224 L276 332 L142 332 M205 224 L330 224 L276 332 M369 332 L327 184 L351 165 L370 165',GREEN,10)+line('M189 215 L226 215 M331 183 L306 183',w=9)+circle(276,332,12,INK)+line('M276 332 L294 346',w=6),'三角车架双轮脚踏')
add('boat','帆船','tool',path('M109 327 L406 327 L358 386 L160 386',BLUE)+line('M258 327 L258 139',w=8)+path('M247 157 L145 305 L247 305',CREAM)+path('M270 177 L354 294 L270 294',GOLD)+line('M100 406 Q137 388 174 406 Q211 424 248 406 Q285 388 322 406 Q359 424 405 406',BLUE,6),'桅杆帆与船体')
add('airplane','飞机','tool',
 path('M240 223 L99 267 L99 296 L242 266 Z',BLUE)+path('M272 223 L413 267 L413 296 L270 266 Z',BLUE)
 +path('M241 347 L180 371 L180 390 L245 377 Z',BLUE)+path('M271 347 L332 371 L332 390 L267 377 Z',BLUE)
 +path('M256 104 Q234 115 234 157 L238 318 L244 395 Q256 410 268 395 L274 318 L278 157 Q278 115 256 104 Z',BLUE)
 +path('M242 153 Q256 142 270 153 L269 178 L243 178 Z',CREAM,3)
 +line('M256 347 L256 390',INK,5),'俯视飞机：长机身、左右主翼、分离的左右水平尾翼和尾部中线')

add('rocket','火箭','tool',path('M213 329 L176 373 L177 293 L214 255',GOLD)+path('M298 329 L336 373 L335 293 L298 255',GOLD)+path('M215 340 Q191 208 256 124 Q321 208 297 340 Z',CREAM)+circle(256,238,33,BLUE)+circle(256,238,21,'#bfd9de')+path('M226 353 Q256 416 284 353',GOLD),'舷窗尾翼；探索非武器')
add('telescope','望远镜','tool',line('M268 278 L268 298 L208 406 M268 298 L330 406 M268 298 L266 411',w=9)+path('M146 248 L335 159 L369 230 L180 319 Z',BLUE)+path('M327 149 L354 136 L399 228 L370 242',GOLD)+rect(130,270,35,46,INK,5),'三脚架斜筒镜')
add('magnifier','放大镜','tool',line('M302 311 L381 395',GOLD,30)+circle(229,239,100,GREEN)+circle(229,239,78,'#d9e6da')+line('M185 225 Q195 190 224 187',CREAM,11),'完整圆镜与手柄')
# Eight narrative places/events, each composed independently.
def tree(x,y,s=1):
 return f'<g transform="translate({x} {y}) scale({s})">'+rect(-12,0,24,100,'#b18d68',5)+circle(-35,-13,48,GREEN)+circle(30,-20,53,GREEN)+circle(0,-59,51,'#91b697')+'</g>'
def sky(): return circle(375,139,35,'#edd093')+ellipse(143,140,57,21,CREAM)
def ground(): return path('M66 352 Q240 304 446 352 L446 437 L66 437 Z','#c5d4ad',0)
add('forest','森林小路','scene',sky()+ground()+tree(124,280,.72)+tree(370,270,.86)+path('M205 434 Q280 383 251 337 L280 330 Q350 376 293 434','#e6cba2',0),'树丛中一条小路')
add('garden','花园开花','scene',sky()+ground()+''.join(line(f'M{x} 390 L{x} {y}',GREEN,8)+''.join(circle(x+math.sin(a)*20,y+math.cos(a)*20,15,c) for a in [0,1.25,2.5,3.75,5])+circle(x,y,12,GOLD) for x,y,c in [(145,287,PINK),(253,257,'#d4b2cf'),(365,302,'#e5bd78')]),'三株花茎叶和花朵')
add('beach','海边帆影','scene',sky()+path('M66 250 Q240 231 446 250 L446 368 L66 368',BLUE,0)+path('M66 366 Q210 323 446 381 L446 437 L66 437','#e6cba2',0)+path('M231 298 L330 298 L310 320 L247 320',CREAM)+line('M277 296 L277 215')+path('M270 222 L239 286 L270 286',GOLD)+line('M96 300 L169 300 M344 350 L408 350',CREAM,5),'沙岸、海水和远帆')
add('mountain','山间日出','scene',circle(257,187,48,'#edd093')+path('M68 384 L178 175 L292 384', '#9bb6aa')+path('M203 384 L333 151 L446 384',BLUE)+path('M295 220 L333 151 L368 220 L342 208 L323 226','#f3eddd')+ground(),'两座山与山后太阳')
add('rain','小屋雨天','scene',ground()+ellipse(252,154,139,40,'#b2c3c7')+''.join(line(f'M{x} 208 L{x-12} 241',BLUE,5) for x in [113,176,241,307,378])+rect(187,299,145,118,'#e0bd92')+path('M161 300 L259 238 L359 300', '#c58f7a')+rect(240,346,35,71,'#9b846c',5)+rect(290,321,25,28,CREAM,3),'房屋外下雨，非灾难')
add('night','月夜营地','scene',rect(66,85,380,351,'#8c9da8',38)+circle(359,153,39,'#eadbb8') + '<circle cx="376" cy="140" r="35" fill="#8c9da8"/>'+''.join(circle(x,y,3,CREAM) for x,y in [(124,140),(211,174),(296,116),(388,232),(163,235)])+path('M66 378 Q237 340 446 378 L446 436 L66 436', '#889e8d',0)+path('M146 390 L259 253 L369 390',GOLD)+path('M220 390 L259 303 L299 390', '#977e65'),'无火营地帐篷与月亮')
add('snow','雪地雪人','scene',rect(66,85,380,351,'#d7e4e2',38)+path('M66 365 Q231 332 446 365 L446 437 L66 437',CREAM,0)+circle(256,339,68,CREAM)+circle(256,239,46,CREAM)+eyes(y=233,gap=16)+path('M254 245 L291 252 L254 260',GOLD)+rect(214,275,88,18,PINK,5)+rect(273,282,19,43,PINK,5)+line('M193 318 L139 281 M320 317 L374 280', '#967e64',6)+circle(256,325,5,INK)+circle(256,351,5,INK),'两雪球、围巾、树枝手')
add('library','图书角阅读','scene',rect(100,133,312,218,'#c5a17e',8)+line('M112 235 L401 235 M112 335 L401 335',w=7)+''.join(rect(x,161,w,68,c,3) for x,w,c in [(126,28,BLUE),(160,38,GREEN),(204,26,PINK),(245,41,GOLD),(301,28,BLUE),(338,47,GREEN)])+''.join(rect(x,260,35,68,c,3) for x,c in [(125,GOLD),(170,PINK),(215,BLUE),(284,GREEN),(331,GOLD)])+ellipse(258,408,114,28,'#b7cbb5')+path('M192 387 Q225 370 256 390 Q286 370 321 387 L321 419 Q288 405 256 424 Q223 405 192 419 Z',CREAM),'书架前一本打开的书，无文字')
# Four original fantasy identities. Never substitute these for real species.
add('cloud-dragon','云朵龙','fantasy',path('M331 309 Q410 334 395 266 Q433 326 374 362 L318 352',GREEN)+ellipse(256,317,84,88,GREEN)+path('M190 293 L124 216 L128 312 L183 337',BLUE)+path('M323 290 L380 214 L383 310 L333 337',BLUE)+face(GREEN,'point')+path('M221 178 L225 145 L242 177 M275 177 L291 146 L294 181',GOLD)+rect(227,330,59,21,GOLD,6),'薄荷绿龙、蓝翼、金双角、金围巾')
add('star-bunny','星星兔','fantasy',face('#e4d3bd','long')+path('M309 289 L318 309 L341 311 L324 326 L328 348 L309 337 L289 348 L292 326 L277 311 L300 308',GOLD)+rect(206,355,99,19,BLUE,6),'奶油兔、长耳粉内耳、蓝围巾、金星胸针')
add('moon-robot','月亮机器人','fantasy',line('M256 163 L256 132',w=8)+circle(256,124,15,GOLD)+rect(155,172,202,166,BLUE,40)+eyes(y=242,gap=44)+line('M226 286 Q256 303 286 286',w=5)+rect(200,345,112,58,'#a9c9d0')+rect(135,218,19,70,GOLD,8)+rect(358,218,19,70,GOLD,8)+circle(256,373,16,GOLD),'蓝色圆角机身、双眼、金天线球、金胸灯')
add('leaf-spirit','叶子精灵','fantasy',ellipse(256,291,85,108,'#b5c69c')+path('M256 207 Q168 141 193 111 Q269 117 256 207',GREEN)+path('M256 207 Q267 122 325 137 Q335 179 256 207',GREEN)+eyes(y=274,gap=29)+line('M235 309 Q256 326 277 309',w=4)+ellipse(168,304,29,18,GREEN)+ellipse(345,304,29,18,GREEN)+rect(213,344,87,18,GOLD,7),'浅绿椭圆身体、两片深绿顶叶、金腰带')
assert len(items)==60
OUT.mkdir(parents=True,exist_ok=True)
manifest=[]
for i,item in enumerate(items,1):
 k=item['id']; body=item.pop('body')
 svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512"><rect width="512" height="512" fill="#f7efdf"/><ellipse cx="256" cy="428" rx="164" ry="17" fill="#e8deca"/><g stroke="none">{body}</g></svg>\n'
 (OUT/'source'/f'{k}.svg').write_text(svg)
 manifest.append(dict(item,index=i,source=f'source/{k}.svg',png=f'png/{k}.png',width=512,height=512,source_sha256=hashlib.sha256(svg.encode()).hexdigest(),provenance='Original project vector artwork, TITA-85; no downloaded or model-generated imagery',license='Project internal use and modification authorized; third-party-free original contribution',visual_status='pending'))
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':
 import cairosvg
 from PIL import Image,ImageDraw
 for item in manifest:
  p=OUT/item['png']; cairosvg.svg2png(url=str(OUT/item['source']),write_to=str(p))
  item['png_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
 for start in range(0,60,12):
  sheet=Image.new('RGB',(1024,846),'#eee7d8'); draw=ImageDraw.Draw(sheet)
  for pos,item in enumerate(manifest[start:start+12]):
   im=Image.open(OUT/item['png']).convert('RGB').resize((256,256))
   x=pos%4*256; y=pos//4*282
   sheet.paste(im,(x,y)); draw.text((x+10,y+257),f"{item['index']:02} {item['id']}",fill='#58483f')
  sheet.save(ROOT/f"docs/evidence/tita85/sheet-{start//12+1}.png")
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 print('Rendered 60 assets and 5 contact sheets')
