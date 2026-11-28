package com.littlebuddy.v2.feedback

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.security.KeyStore
import java.util.UUID
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Opt-in real AndroidKeyStore test. Only a fresh test alias/directory; no production data or alias. */
class FeedbackKeystoreProbeTest {
    @Test fun firstEmptyCoreAndExistingRecordUseRandomizedKeystoreIvWithoutScreenCredential() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("feedbackKeystoreProbe")=="true")
        val context=InstrumentationRegistry.getInstrumentation().context
        val suffix=UUID.randomUUID().toString()
        val alias="little-buddy.test.feedback.$suffix"
        val directory=File(context.cacheDir,"feedback-probe-$suffix")
        val keys=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
        try {
            val key=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true).setUserAuthenticationRequired(false).build())
            }.generateKey()
            val files=PrivateVaultFiles(directory)
            val core=FeedbackCore(FeedbackVault(files,key),FeedbackClock{1000L})
            assertNotNull(files.read("materials"));assertNotNull(files.read("ledger"))
            core.record(mapOf("stage" to LogStage.CONNECT,"error" to LogError.NONE,
                "version" to 1,"elapsedMs" to 0L,"usage" to 0L))
            val before=FeedbackVault(files,key).load()!!
            FeedbackCore(FeedbackVault(files,key),FeedbackClock{1000L})
            val after=FeedbackVault(files,key).load()!!
            try {assertArrayEquals(before,after)}finally{before.fill(0);after.fill(0)}
        } finally {
            // Remove only resources minted in this method, never real feedback/PIN/transport keys.
            keys.deleteEntry(alias);directory.deleteRecursively()
        }
    }
}
