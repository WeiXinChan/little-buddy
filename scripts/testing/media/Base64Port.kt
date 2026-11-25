package android.util
object Base64 {
    const val NO_WRAP=2
    @JvmStatic fun encodeToString(bytes: ByteArray, flags: Int)=java.util.Base64.getEncoder().encodeToString(bytes)
    @JvmStatic fun decode(value: String, flags: Int)=java.util.Base64.getDecoder().decode(value)
}
