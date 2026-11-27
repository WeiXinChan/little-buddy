package android.content.res
import java.io.File
import java.io.InputStream
class AssetManager(private val root:File,private val beforeOpen:()->Unit={}) {
 fun open(name:String):InputStream {beforeOpen();return File(root,name).inputStream()}
}
