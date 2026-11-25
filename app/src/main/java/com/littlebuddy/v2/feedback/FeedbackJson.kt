package com.littlebuddy.v2.feedback

import android.util.JsonReader
import android.util.JsonToken
import java.io.StringReader

/** Strict bounded response parser; duplicate keys and permissive numeric coercions deny. */
internal object FeedbackJson {
    fun parse(text:String): Map<String,Any?> {
        if(text.length>400000 || text.toByteArray(Charsets.UTF_8).size>400000)throw FeedbackFailure(Failure.NETWORK)
        return JsonReader(StringReader(text)).use { reader ->
            reader.isLenient=false
            val value=read(reader,0)
            if(reader.peek()!=JsonToken.END_DOCUMENT)throw FeedbackFailure(Failure.NETWORK)
            @Suppress("UNCHECKED_CAST")
            (value as? Map<String,Any?>) ?: throw FeedbackFailure(Failure.NETWORK)
        }
    }
    private fun read(r:JsonReader,depth:Int):Any? {
        if(depth>2)throw FeedbackFailure(Failure.NETWORK)
        return when(r.peek()) {
            JsonToken.BEGIN_OBJECT->{val map=linkedMapOf<String,Any?>();r.beginObject()
                while(r.hasNext()) {val name=r.nextName();if(name.length>32 || map.size>=16 || map.containsKey(name))throw FeedbackFailure(Failure.NETWORK);map[name]=read(r,depth+1)}
                r.endObject();map }
            JsonToken.STRING->r.nextString()
            JsonToken.NUMBER->{val text=r.nextString();if(!text.matches(Regex("0|[1-9][0-9]{0,18}")))throw FeedbackFailure(Failure.NETWORK);text.toLong()}
            JsonToken.BOOLEAN->r.nextBoolean()
            JsonToken.NULL->{r.nextNull();null}
            else->throw FeedbackFailure(Failure.NETWORK)
        }
    }
}
