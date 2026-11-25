package com.littlebuddy.v2.feedback

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** No UI or Grant adapter is enabled here. Key loss fails closed; never resets PIN/pairing. */
object AndroidFeedbackVault {
    fun open(context: Context): FeedbackVault {
        val alias = "little-buddy.v2.feedback.v1"
        val directory = File(context.noBackupFilesDir, "m09-feedback")
        try {
            val keys = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            val key = if (keys.containsAlias(alias)) keys.getKey(alias, null) as SecretKey else {
                if (directory.exists() && directory.list()?.isNotEmpty() == true)
                    throw FeedbackFailure(Failure.QUARANTINED)
                KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                    init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
                }.generateKey()
            }
            return FeedbackVault(PrivateVaultFiles(directory), key)
        } catch (_: Exception) { throw FeedbackFailure(Failure.QUARANTINED) }
    }
}
