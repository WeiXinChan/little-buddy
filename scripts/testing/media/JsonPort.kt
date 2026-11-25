package org.json
import com.google.gson.*

/** JVM-only JSON adapter over the existing cached Gson; production uses Android org.json. */
class JSONObject private constructor(private val value: JsonObject) {
    constructor():this(JsonObject())
    constructor(text: String):this(JsonParser.parseString(text).asJsonObject)
    fun put(key: String,item: Any?): JSONObject {
        value.add(key,when(item) { is JSONObject->item.value; is JSONArray->item.value; else->Gson().toJsonTree(item) });return this
    }
    fun get(key: String): Any? { val n=value.get(key)
        return if(n.isJsonNull)null else if(n.isJsonPrimitive) { val p=n.asJsonPrimitive
            if(p.isNumber) {if(p.asString.contains('.') || p.asString.contains('e'))p.asDouble else p.asLong}
            else if(p.isBoolean)p.asBoolean else p.asString } else n }
    fun optBoolean(key:String,fallback:Boolean=false)=if(has(key) && !isNull(key))value.get(key).asBoolean else fallback
    fun getString(key: String)=value.get(key).asString
    fun getLong(key: String)=value.get(key).asLong
    fun getInt(key: String)=value.get(key).asInt
    fun getJSONObject(key: String)=JSONObject(value.getAsJsonObject(key))
    fun optString(key: String,fallback: String="")=if (has(key) && !isNull(key)) getString(key) else fallback
    fun optLong(key: String,fallback: Long)=if (has(key) && !isNull(key)) getLong(key) else fallback
    fun optInt(key: String,fallback: Int)=if (has(key) && !isNull(key)) getInt(key) else fallback
    fun has(key: String)=value.has(key)
    fun isNull(key: String)=!value.has(key) || value.get(key).isJsonNull
    fun keys(): MutableIterator<String> = value.keySet().iterator()
    override fun toString()=value.toString()
}
class JSONArray {
    internal var value=JsonArray()
    constructor()
    constructor(text:String){value=JsonParser.parseString(text).asJsonArray}
    fun length()=value.size()
    fun getJSONObject(index:Int)=JSONObject(value.get(index).toString())
    fun put(item: String): JSONArray { value.add(item); return this }
}
