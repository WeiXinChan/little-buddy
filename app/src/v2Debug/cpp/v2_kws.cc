// V2 owns every object in its source-patched keyword-only core. No AAR opaque pointer use.
#include "third_party/android-jni-26.h"
#include "sherpa-onnx/csrc/keyword-spotter.h"
#include <cstdint>
#include <memory>
#include <string>
#include <exception>
#include <new>

struct V2Kws {
  sherpa_onnx::KeywordSpotter *spotter;
  sherpa_onnx::OnlineStream *stream;
};
static void fail(JNIEnv *e) {
  if(e->ExceptionCheck())return;
  jclass cls=e->FindClass("java/lang/IllegalStateException");
  if(cls){e->ThrowNew(cls,"V2 KWS native state");e->DeleteLocalRef(cls);}
}
static V2Kws *context(JNIEnv *e,jobject b) {
  if(!b || e->GetDirectBufferCapacity(b)!=(jlong)sizeof(V2Kws)){fail(e);return nullptr;}
  auto p=static_cast<V2Kws *>(e->GetDirectBufferAddress(b));
  if(!p || reinterpret_cast<uintptr_t>(p)%alignof(V2Kws)){fail(e);return nullptr;}
  return p;
}
extern "C" JNIEXPORT jint JNICALL Java_com_littlebuddy_v2_V2KwsNative_contextBytes(JNIEnv *,jobject) {
  return sizeof(V2Kws);
}
extern "C" JNIEXPORT jboolean JNICALL Java_com_littlebuddy_v2_V2KwsNative_create(JNIEnv *e,jobject,jobject b,jobjectArray paths) {
  auto p=context(e,b);if(!p)return JNI_FALSE;
  // Begin the lifetime of our own trivial object in VM-owned direct storage.
  auto bytes=reinterpret_cast<unsigned char *>(p);
  for(unsigned i=0;i<sizeof(V2Kws);i++)if(bytes[i]){fail(e);return JNI_FALSE;}
  p=new(p) V2Kws{nullptr,nullptr};
  if(!paths || e->GetArrayLength(paths)!=5){fail(e);return JNI_FALSE;}
  try {
    std::string names[5];
    for(int i=0;i<5;i++){
      auto value=static_cast<jstring>(e->GetObjectArrayElement(paths,i));
      if(!value){fail(e);return JNI_FALSE;}
      const char *utf=e->GetStringUTFChars(value,nullptr);
      if(!utf){e->DeleteLocalRef(value);return JNI_FALSE;}
      try {names[i]=utf;} catch(...) {e->ReleaseStringUTFChars(value,utf);e->DeleteLocalRef(value);throw;}
      e->ReleaseStringUTFChars(value,utf);e->DeleteLocalRef(value);
    }
    sherpa_onnx::KeywordSpotterConfig cfg;
    cfg.feat_config.sampling_rate=16000;cfg.feat_config.feature_dim=80;cfg.feat_config.dither=0;
    cfg.model_config.transducer.encoder=names[0];cfg.model_config.transducer.decoder=names[1];
    cfg.model_config.transducer.joiner=names[2];cfg.model_config.tokens=names[3];
    cfg.model_config.num_threads=1;cfg.model_config.provider_config.provider="cpu";
    cfg.model_config.model_type="zipformer2";cfg.model_config.debug=false;
    cfg.max_active_paths=4;cfg.num_trailing_blanks=2;
    cfg.keywords_score=1.5f;cfg.keywords_threshold=0.25f;cfg.keywords_file=names[4];
    auto spotter=std::make_unique<sherpa_onnx::KeywordSpotter>(cfg);
    auto stream=spotter->CreateStream();if(!stream){fail(e);return JNI_FALSE;}
    p->stream=stream.release();p->spotter=spotter.release();return JNI_TRUE;
  } catch(...) {fail(e);return JNI_FALSE;}
}
struct WaveChunk {
  jshort pcm[320]{};float samples[320]{};
  ~WaveChunk(){for(volatile auto &s:pcm)s=0;for(volatile auto &s:samples)s=0;}
};
extern "C" JNIEXPORT void JNICALL Java_com_littlebuddy_v2_V2KwsNative_feed(JNIEnv *e,jobject,jobject b,jshortArray input,jint n) {
  auto p=context(e,b);
  if(!p || !p->stream || !input || n<1 || n>320 || e->GetArrayLength(input)<n){fail(e);return;}
  WaveChunk data;e->GetShortArrayRegion(input,0,n,data.pcm);if(e->ExceptionCheck())return;
  try {for(int i=0;i<n;i++)data.samples[i]=data.pcm[i]/32768.f;p->stream->AcceptWaveform(16000,data.samples,n);}
  catch(...){fail(e);}
}
extern "C" JNIEXPORT jboolean JNICALL Java_com_littlebuddy_v2_V2KwsNative_ready(JNIEnv *e,jobject,jobject b) {
  auto p=context(e,b);if(!p || !p->spotter || !p->stream){fail(e);return JNI_FALSE;}
  try {return p->spotter->IsReady(p->stream)?JNI_TRUE:JNI_FALSE;}
  catch(...){fail(e);return JNI_FALSE;}
}
extern "C" JNIEXPORT jdoubleArray JNICALL Java_com_littlebuddy_v2_V2KwsNative_decode(JNIEnv *e,jobject,jobject b) {
  auto p=context(e,b);if(!p || !p->spotter || !p->stream){fail(e);return nullptr;}
  try {
    if(!p->spotter->IsReady(p->stream)){fail(e);return nullptr;}
    p->spotter->DecodeStream(p->stream);auto r=p->spotter->GetResult(p->stream);
    if(r.keyword!="瓦力瓦力")return nullptr;
    if(r.timestamps.empty() || r.timestamps.size()>64){fail(e);return nullptr;}
    // Patched reset retains the true decoder frame_offset. No clip/now/reference offset.
    jdouble values[2]={r.start_time,r.timestamps.back()};
    auto answer=e->NewDoubleArray(2);if(answer)e->SetDoubleArrayRegion(answer,0,2,values);
    return answer;
  }catch(...){fail(e);return nullptr;}
}
extern "C" JNIEXPORT void JNICALL Java_com_littlebuddy_v2_V2KwsNative_close(JNIEnv *e,jobject,jobject b) {
  auto p=context(e,b);if(!p)return;
  try {delete p->stream;p->stream=nullptr;delete p->spotter;p->spotter=nullptr;}
  catch(...){fail(e);}
}
extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *,void *) {return JNI_VERSION_1_6;}
