package com.k2fsa.sherpa.onnx
import android.content.res.AssetManager
class OnlineTransducerModelConfig(val encoder:String,val decoder:String,val joiner:String)
class OnlineModelConfig(val transducer:OnlineTransducerModelConfig,val tokens:String,val modelType:String,val numThreads:Int)
class KeywordSpotterConfig(val modelConfig:OnlineModelConfig,val keywordsFile:String)
object DecodeScenario {
 var onAccept:()->Unit={};var onReady:()->Unit={};var onDecode:()->Unit={};var onResult:()->Unit={}
 var ready=false;var decodes=0;var results=0;var floats:FloatArray?=null
 fun reset(){onAccept={};onReady={};onDecode={};onResult={};ready=false;decodes=0;results=0;floats=null}
}
class OnlineStream {fun acceptWaveform(a:FloatArray,b:Int){DecodeScenario.floats=a;DecodeScenario.onAccept()};fun release(){}}
class KeywordResult(val keyword:String="瓦力瓦力",val timestamps:FloatArray=floatArrayOf(0f))
class KeywordSpotter(a:AssetManager,b:KeywordSpotterConfig) {
 fun createStream()=OnlineStream()
 fun isReady(s:OnlineStream):Boolean {DecodeScenario.onReady();return DecodeScenario.ready}
 fun decode(s:OnlineStream){DecodeScenario.decodes++;DecodeScenario.onDecode()}
 fun getResult(s:OnlineStream):KeywordResult{DecodeScenario.results++;DecodeScenario.onResult();return KeywordResult()}
 fun release(){}
}
