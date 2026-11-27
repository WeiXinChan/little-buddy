package com.littlebuddy.v2.parent

/** Public storage selector only. Never replaces a lost legacy binding or grants identity. */
internal object LocalManagementBinding {
    const val LOCAL = "v2-app-local-management-v1"
    fun resolve(existingStore: Boolean, legacyCertificateBinding: String?, marker: ByteArray?): String {
        check(marker == null || marker.contentEquals(byteArrayOf(1))) { "local binding marker invalid" }
        if (marker != null) { check(legacyCertificateBinding == null); return LOCAL }
        if (legacyCertificateBinding != null) return legacyCertificateBinding
        check(!existingStore) { "legacy parent binding unavailable" }
        return LOCAL
    }
}
