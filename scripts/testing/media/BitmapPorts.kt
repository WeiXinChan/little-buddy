package android.graphics
class Bitmap(val width:Int,val height:Int) {var isRecycled=false;fun recycle(){isRecycled=true}}
object BitmapFactory {
    class Options {var inJustDecodeBounds=false;var inScaled=true;var outWidth=0;var outHeight=0;var outMimeType:String?=null}
    @JvmStatic fun decodeByteArray(data:ByteArray,offset:Int,size:Int,o:Options):Bitmap? {
        val b=java.nio.ByteBuffer.wrap(data);b.position(offset+16);o.outWidth=b.int;o.outHeight=b.int;o.outMimeType="image/png"
        return if(o.inJustDecodeBounds)null else Bitmap(o.outWidth,o.outHeight)
    }
}
