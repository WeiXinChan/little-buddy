package com.littlebuddy.v2

import com.littlebuddy.SpeechDetector

/** Finite local command confirmation, not ASR. Unknown context stays locked.
 * VAD rejects short transients; prefix context survives ordinary thinking pauses.
 * No audio/text leaves this component. Bounds are general safety policy, not fixture offsets.
 */
internal class CommandBoundary {
    data class Hit(val name: String,val start: Long,val end: Long)
    private var position=0L
    private var first: Long?=null
    private var lastSpeech=0L
    private var candidate: Hit?=null
    private var denyNext=false
    private var vad=SpeechDetector(320,36.0)
    fun frame(samples: ShortArray,count: Int,hit: Hit?,managed: Boolean): String? {
        position+=count
        vad.accept(samples,count)
        if(vad.detectedSpeechInRead) {
            if(first==null)first=(position-1280).coerceAtLeast(0)
            lastSpeech=position
        }
        if(hit?.name=="否定" && managed) { denyNext=true; candidate=null }
        else if(hit!=null && first!=null) {
            if(managed && denyNext && hit.name in listOf("取消","退出管理")) { denyNext=false; clear() }
            else candidate=hit
        }
        val c=candidate
        if(c!=null && position-lastSpeech>=24000) { // 1.5s complete-command quiet: retain post-keyword context
            val start=first ?: position
            val valid=c.start-start in -4800L..4800L && lastSpeech-c.end<=7680 && lastSpeech-start<=96000
            clear()
            if(valid && (if(managed)c.name in listOf("取消","退出管理") else c.name=="进入管理"))return c.name
        }
        // A pause alone must not erase the prefix of an unrecognised/negative utterance.
        if(first!=null && position-lastSpeech>=56000)clear() // 3.5s context horizon
        return null
    }
    private fun clear() { first=null;candidate=null;vad=SpeechDetector(320,36.0) }
}
