package com.littlebuddy.v2.parent

import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Authenticates schema/device binding and every field, including retry metadata. */
internal object ParentEnvelope {
    fun seal(plain: ByteArray, key: SecretKey, aad: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key); cipher.updateAAD(aad)
        check(cipher.iv.size == 12)
        return cipher.iv + cipher.doFinal(plain)
    }
    fun open(bytes: ByteArray, key: SecretKey, aad: ByteArray): ByteArray {
        check(bytes.size in 29..2048) { "parent record invalid" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, bytes, 0, 12))
        cipher.updateAAD(aad)
        return cipher.doFinal(bytes, 12, bytes.size - 12)
    }
}
