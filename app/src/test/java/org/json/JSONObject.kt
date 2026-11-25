package org.json
import com.google.gson.*

/** JVM-only JSON adapter over the existing cached Gson; production uses Android org.json. */
class JSONObject private constructor(private val value: JsonObject) {
    constructor():this(JsonObject())
    constructor(text: String):this(JsonParser.parseString(text).asJsonObject)
    fun put(key: String,item: Any?): JSONObject {
        value.add(key,when(item) { is JSONObject->item.value; is JSONArray->item.value; else->Gson().toJsonTree(item) });return this
    }
    // Android callers are compiled before this JVM substitute, so preserve primitive descriptors.
    fun put(key: String,item: Int): JSONObject = put(key,item as Any)
    fun put(key: String,item: Long): JSONObject = put(key,item as Any)
    fun put(key: String,item: Double): JSONObject = put(key,item as Any)
    fun put(key: String,item: Boolean): JSONObject = put(key,item as Any)
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
    internal val value=JsonArray()
    fun put(item: String): JSONArray { value.add(item); return this }
}
