package android.util
/** JVM port for Android's streaming reader, delegated to the already cached Gson. */
enum class JsonToken { BEGIN_ARRAY,END_ARRAY,BEGIN_OBJECT,END_OBJECT,NAME,STRING,NUMBER,BOOLEAN,NULL,END_DOCUMENT }
class JsonReader(reader:java.io.Reader):java.io.Closeable {
    private val delegate=com.google.gson.stream.JsonReader(reader)
    var isLenient:Boolean get()=delegate.isLenient;set(value){delegate.isLenient=value}
    fun peek()=JsonToken.valueOf(delegate.peek().name)
    fun beginObject()=delegate.beginObject();fun endObject()=delegate.endObject()
    fun hasNext()=delegate.hasNext();fun nextName()=delegate.nextName();fun nextString()=delegate.nextString()
    fun nextBoolean()=delegate.nextBoolean();fun nextNull()=delegate.nextNull()
    override fun close()=delegate.close()
}
