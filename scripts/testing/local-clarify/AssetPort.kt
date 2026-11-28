package android.content.res
class AssetManager(private val files:Map<String,ByteArray>) {
 fun open(name:String):java.io.InputStream=java.io.ByteArrayInputStream(checkNotNull(files[name]))
}
