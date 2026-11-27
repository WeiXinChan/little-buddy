"""Trusted-source and actual APK closure for the isolated V2 keyword core; no self-inventory trust."""
from pathlib import Path
import hashlib,json,struct
NAME='libwali-v2-kws.so'
BINARY='app/src/v2Debug/jniLibs/arm64-v8a/'+NAME
LOCK='app/src/v2Debug/cpp/native-lock.json'
def need(ok,code):
 if not ok:raise ValueError(code)
def source_inputs(root):
 root=Path(root);base=root/'app/src/v2Debug/cpp'
 return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(base.rglob('*')) if p.is_file() and p.name!='native-lock.json'}
def elf(raw):
 need(raw[:6]==b'\x7fELF\x02\x01','native_elf_format')
 h=struct.unpack_from('<HHIQQQIHHHHHH',raw,16)
 need(h[0]==3 and h[1]==183,'native_elf_arm64')
 loads=0;execute=False;stack=False;relro=False
 for i in range(h[9]):
  t,flags,off,addr,_,size,mem,align=struct.unpack_from('<IIQQQQQQ',raw,h[4]+i*h[8])
  if t==1:
   loads+=1;execute=execute or bool(flags&1)
   need(not(flags&1 and flags&2),'native_writable_code')
   need(align>=16384 and off%16384==addr%16384,'native_elf_alignment')
  if t==0x6474e551:stack=True;need(not flags&1,'native_executable_stack')
  if t==0x6474e552:relro=True
 need(loads>=2 and execute and stack and relro,'native_load_guards')
 sections=[struct.unpack_from('<IIQQQQIIQQ',raw,h[5]+i*h[10]) for i in range(h[11])]
 def string(sec,index):
  need(0<=index<sec[5],'native_string_index');start=sec[4]+index
  return raw[start:raw.index(b'\0',start,sec[4]+sec[5])].decode('ascii')
 dependencies=set();exports=set();soname=None
 for s in sections:
  if s[1]==6:
   for off in range(s[4],s[4]+s[5],16):
    kind,val=struct.unpack_from('<qQ',raw,off)
    if kind==1:dependencies.add(string(sections[s[6]],val))
    if kind==14:soname=string(sections[s[6]],val)
    need(kind not in (15,22,29),'native_path_or_textrel')
  if s[1]==11:
   for off in range(s[4],s[4]+s[5],s[9]):
    name,info,visibility,index,_,_=struct.unpack_from('<IBBHQQ',raw,off)
    if index and info>>4 in (1,2) and (visibility&3) in (0,3):exports.add(string(sections[s[6]],name))
 expected={'Java_com_littlebuddy_v2_V2KwsNative_'+n for n in ('contextBytes','create','feed','ready','decode','close')}|{'JNI_OnLoad'}
 need(exports==expected,'native_public_symbols')
 need(dependencies=={'libonnxruntime.so','libc.so','libm.so','libdl.so','liblog.so','libandroid.so'},'native_dependencies')
 need(soname==NAME,'native_soname')
 need(b'/home/ubuntu' not in raw,'native_host_path')
 return {'exports':sorted(exports),'dependencies':sorted(dependencies),'page_alignment':16384}
def validate_source(root):
 root=Path(root);lock=json.loads((root/LOCK).read_text())
 need(lock['format']==1 and lock['patch_abi']==1 and lock['abi']=='arm64-v8a' and lock['min_sdk']==26,'native_lock_contract')
 need(lock['source_inputs']==source_inputs(root),'native_source_binding')
 raw=(root/BINARY).read_bytes();need(hashlib.sha256(raw).hexdigest()==lock['library_sha256'],'native_binary_binding')
 return elf(raw)
def validate_apk(root,z):
 validate_source(root);names=[n for n in z.namelist() if n.startswith('lib/') and n.endswith('/'+NAME)]
 expected='lib/arm64-v8a/'+NAME;need(names==[expected],'native_apk_set')
 raw=(Path(root)/BINARY).read_bytes();need(z.getinfo(expected).file_size==len(raw) and z.read(expected)==raw,'native_apk_bytes')
