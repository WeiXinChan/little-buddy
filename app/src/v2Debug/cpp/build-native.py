from pathlib import Path
import subprocess,os,sys,hashlib,json,zipfile
import argparse
parser=argparse.ArgumentParser(description='Offline source-patched V2 keyword-only build; run via scripts/with-build-lock')
parser.add_argument('--cache',type=Path,required=True)
parser.add_argument('--arch',choices=['host','android'],required=True)
parser.add_argument('--host-ort',type=Path)
args=parser.parse_args()
ROOT=args.cache.resolve()
APP=Path(__file__).resolve().parents[4]
SH=ROOT/'vendor/sherpa-onnx-1.12.27';C=SH/'sherpa-onnx/csrc'
patch=APP/'app/src/v2Debug/cpp/patches/keyword-global-frame-offset.patch'
pins=json.loads((APP/'app/src/v2Debug/cpp/source-pins.json').read_text())
original=C/'keyword-spotter-transducer-impl.h'
assert hashlib.sha256(original.read_bytes()).hexdigest() in (pins['upstream_header_sha256'],pins['patched_header_sha256'])
if hashlib.sha256(original.read_bytes()).hexdigest()==pins['upstream_header_sha256']:
 subprocess.run(['patch','--forward','-p1','--input',str(patch)],cwd=SH,check=True)
assert hashlib.sha256(original.read_bytes()).hexdigest()==pins['patched_header_sha256']
arch=args.arch
out=ROOT/'build'/arch;out.mkdir(parents=True,exist_ok=True)
cc=ROOT/'extracted/usr/bin/clang-18';lld=ROOT/'extracted/usr/bin/ld.lld'
fb=ROOT/'vendor/kaldi-native-fbank-1.22.3';kd=ROOT/'vendor/kaldi-decoder-0.2.11';fst=ROOT/'vendor/openfst-sherpa-onnx-2024-06-13';kf=ROOT/'vendor/kaldifst-1.7.16';kiss=next((ROOT/'vendor').glob('kissfft-*'))
# Use checked-in upstream static config rather than inventing platform layout.
includes=[ROOT/'vendor/simple-sentencepiece-0.7',ROOT/'vendor/eigen-3.4.1',SH,fb,kd,kf,fst/'src/include',kiss,ROOT/'onnx-headers-1.17.1',APP/'app/src/v2Debug/cpp']
flags=['-O2','-g0','-fPIC','-fvisibility=hidden','-fvisibility-inlines-hidden','-ffunction-sections','-fdata-sections','-DNDEBUG','-DKISS_FFT_STATIC','-DKALDI_NATIVE_FBANK_EXPORT=','-DSHERPA_ONNX_ENABLE_GPU=0','-DSHERPA_ONNX_ENABLE_DIRECTML=0','-DSHERPA_ONNX_ENABLE_RKNN=0','-DSHERPA_ONNX_ENABLE_TTS=0','-DORT_API_MANUAL_INIT=0','-Wno-deprecated-declarations','-ffile-prefix-map='+str(ROOT)+'=/src/wali-v2-native']
# ORT_API_MANUAL_INIT must be undefined: headers initialize the existing runtime API.
flags.remove('-DORT_API_MANUAL_INIT=0')
if arch=='host':
 cpp=['g++'];ccompiler=['gcc'];onnx=args.host_ort.resolve() if args.host_ort else None
 assert onnx and onnx.is_file(),'--host-ort is required for the host-only regression'
 linkflags=['-Wl,-rpath,'+str(onnx.parent),'-Wl,-z,defs','-Wl,--gc-sections','-Wl,--version-script='+str(APP/'app/src/v2Debug/cpp/exports.map')]
 libs=[str(onnx),'-lpthread','-ldl','-lm']
elif arch=='android':
 sysroot=ROOT/'ndk/sysroot';target=['--target=aarch64-linux-android26','--sysroot='+str(sysroot)]
 cpp=[str(cc),'-x','c++',*target];ccompiler=[str(cc),*target]
 includes.insert(0,sysroot/'usr/include/c++/v1');includes.insert(1,sysroot/'usr/include/aarch64-linux-android')
 flags+=['-D__ANDROID_API__=26']
 with zipfile.ZipFile(APP/'app/libs/sherpa-onnx-1.12.27.aar') as z:
  onnx=out/'libonnxruntime.so';onnx.write_bytes(z.read('jni/arm64-v8a/libonnxruntime.so'))
 lib=ROOT/'ndk/sysroot/usr/lib/aarch64-linux-android';api=lib/'26'
 rt=next((ROOT/'ndk/lib/clang').glob('*/lib/linux/libclang_rt.builtins-aarch64-android.a'))
 linkflags=[*target,'--ld-path='+str(lld),'-nostdlib','-Wl,-z,defs','-Wl,--gc-sections','-Wl,-z,max-page-size=16384','-Wl,--exclude-libs,ALL','-Wl,--version-script='+str(APP/'app/src/v2Debug/cpp/exports.map'),'-L'+str(api)]
 unwind=next((ROOT/'ndk/lib/clang').glob('*/lib/linux/aarch64/libunwind.a'))
 libs=[str(onnx),'-Wl,--start-group',str(lib/'libc++_static.a'),str(lib/'libc++abi.a'),str(unwind),str(rt),'-Wl,--end-group','-lc','-lm','-ldl','-llog','-landroid',str(api/'crtend_so.o')]
else:raise AssertionError('fixed target')
name_list=['cat','context-graph','features','file-utils','hypothesis','keyword-spotter-impl','keyword-spotter','math','online-model-config','online-stream','online-transducer-decoder','online-transducer-model','online-conformer-transducer-model','online-ebranchformer-transducer-model','online-lstm-transducer-model','online-zipformer-transducer-model','online-zipformer2-transducer-model','onnx-utils','parse-options','provider','provider-config','resample','session','symbol-table','text-utils','transducer-keyword-decoder','unbind','utils']
sources=[C/(n+'.cc') for n in name_list]
sources+=sorted(C.glob('online-*-model-config.cc'))
sources+=sorted(fb.glob('kaldi-native-fbank/csrc/*.cc'))
sources=[p for p in sources if not p.name.startswith('test-')]
sources+=[kd/'kaldi-decoder/csrc/faster-decoder.cc',ROOT/'vendor/simple-sentencepiece-0.7/ssentencepiece/csrc/ssentencepiece.cc',kiss/'kiss_fft.c',kiss/'kiss_fftr.c',APP/'app/src/v2Debug/cpp/v2_kws.cc']
sources=list(dict.fromkeys(sources))
header_digest=hashlib.sha256(b''.join(p.read_bytes() for base in includes for p in sorted(base.glob('*.h')))).hexdigest()+pins['patched_header_sha256']
objects=[];receipt=[]
for src in sources:
 assert src.is_file(),src
 key=hashlib.sha256((str(src)+header_digest+str(flags)+str(includes)).encode()+src.read_bytes()).hexdigest()
 obj=out/(src.stem+'-'+key[:12]+'.o');objects.append(obj)
 if not obj.exists():
  cmd=[*(ccompiler if src.suffix=='.c' else cpp),*([] if src.suffix=='.c' else ['-std=c++17']),*flags,*sum([['-I',str(i)] for i in includes],[]),'-c',str(src),'-o',str(obj)]
  print('COMPILE',arch,src.name,flush=True);subprocess.run(cmd,check=True)
 receipt.append(dict(source=str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src.relative_to(APP)),sha256=hashlib.sha256(src.read_bytes()).hexdigest(),object_sha256=hashlib.sha256(obj.read_bytes()).hexdigest()))
libpath=out/'libwali-v2-kws.so'
# clang's -x c++ is a compile-only selector, never reinterpret ELF objects as source.
linker=['g++'] if arch=='host' else [str(cc)]
start=[] if arch=='host' else [str(api/'crtbegin_so.o')]
subprocess.run([*linker,'-shared','-Wl,-z,relro','-Wl,-z,now',*linkflags,'-Wl,-soname,libwali-v2-kws.so',*start,*map(str,objects),*libs,'-o',str(libpath)],check=True)
(out/'receipt.json').write_text(json.dumps(dict(arch=arch,patch=pins,flags=flags,includes=list(map(str,includes)),cpp=cpp,linker=linker,linkflags=linkflags,libs=libs,object_paths=list(map(str,objects)),objects=receipt,library_sha256=hashlib.sha256(libpath.read_bytes()).hexdigest()),indent=2)+'\n')
print('BUILT',arch,libpath.stat().st_size,hashlib.sha256(libpath.read_bytes()).hexdigest(),flush=True)
