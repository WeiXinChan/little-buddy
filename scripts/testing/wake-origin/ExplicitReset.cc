#include "sherpa-onnx/csrc/keyword-spotter.h"
#include <iostream>
#include <vector>
#include <string>
#include <algorithm>
#include <chrono>
struct WipedFloats:std::vector<float> {
 using std::vector<float>::vector;
 ~WipedFloats(){for(volatile auto &x:*this)x=0;}
};
int main(int argc,char **argv) {
 if(argc!=2)return 2;
 WipedFloats audio;float sample;
 while(std::cin.read(reinterpret_cast<char*>(&sample),sizeof(sample))){audio.push_back(sample);if(audio.size()>160000)return 3;}
 if(audio.empty())return 4;
 const std::string base=argv[1],suffix="epoch-13-avg-2-chunk-16-left-64";
 sherpa_onnx::KeywordSpotterConfig c;c.feat_config.dither=0;
 c.model_config.transducer.encoder=base+"/encoder-"+suffix+".int8.onnx";
 c.model_config.transducer.decoder=base+"/decoder-"+suffix+".onnx";
 c.model_config.transducer.joiner=base+"/joiner-"+suffix+".int8.onnx";
 c.model_config.tokens=base+"/tokens.txt";c.model_config.num_threads=1;
 c.model_config.provider_config.provider="cpu";c.model_config.model_type="zipformer2";
 c.max_active_paths=4;c.num_trailing_blanks=2;c.keywords_score=1.5;c.keywords_threshold=.25;c.keywords_file=base+"/keywords.txt";
 const auto start=std::chrono::steady_clock::now();long fed=0,previous=0;
 {
  sherpa_onnx::KeywordSpotter kws(c);auto stream=kws.CreateStream();if(!stream)return 5;
  for(int index=0;index<2;index++) {
   if(index)kws.Reset(stream.get());
   WipedFloats input((index?10:30)*16000,0);input.insert(input.end(),audio.begin(),audio.end());input.resize(input.size()+32000,0);
   long cueStart=fed+(index?10:30)*16000;bool hit=false;
   for(size_t cursor=0;cursor<input.size()&&!hit;cursor+=320){
    if(std::chrono::steady_clock::now()-start>std::chrono::seconds(90))return 6;
    int count=std::min<size_t>(320,input.size()-cursor);stream->AcceptWaveform(16000,input.data()+cursor,count);fed+=count;
    while(kws.IsReady(stream.get())){
     kws.DecodeStream(stream.get());auto r=kws.GetResult(stream.get());
     if(!r.keyword.empty()){
      if(r.keyword!="瓦力瓦力" || r.timestamps.empty() || r.start_time!=0)return 7;
      long tail=static_cast<long>((static_cast<double>(r.timestamps.back())+static_cast<double>(.12f))*16000);
      std::cout<<"EXPLICIT_RESET index="<<index<<" fed="<<fed<<" native_tail="<<tail<<" cue_start="<<cueStart<<"\n";
      if(tail<=cueStart || tail>fed || (index&&tail<=previous))return 8;
      previous=tail;hit=true;break;
     }
    }
   }
   for(volatile auto &x:input)x=0;
   if(!hit)return 9;
  }
 }
 for(volatile auto &x:audio)x=0;
 std::cout<<"EXPLICIT_RESET hits=2 release_returned=true provider_calls=0\n";
}
