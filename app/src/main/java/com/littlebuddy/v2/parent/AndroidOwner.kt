package com.littlebuddy.v2.parent

import android.app.Activity
import android.app.KeyguardManager
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import android.os.SystemClock
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.concurrent.atomic.AtomicBoolean

/** Local device-credential trust boundary, not a remote family-account ownership assertion. */
internal class AndroidOwner private constructor(val binding: String, private val receipt: OwnerReceipt) : OwnerProof {
    override fun consume(challenge: OwnerChallenge) = receipt.consume(challenge)
    fun discard(challenge: OwnerChallenge) = receipt.discard(challenge)
    fun signature(): Signature {
        AndroidParentStore.worker()
        val key = keys().getKey(ALIAS, null) as PrivateKey
        return Signature.getInstance("SHA256withECDSA").apply { initSign(key) }
    }
    fun approve(challenge: OwnerChallenge, signature: Signature): Boolean {
        AndroidParentStore.worker()
        return receipt.approve(challenge) { signature.update(it); signature.sign() }
    }
    companion object {
        private const val ALIAS = "little-buddy-v2-system-owner-v1"
        private var instance: AndroidOwner? = null
        private fun keys() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        @Synchronized fun open(activity: Activity): AndroidOwner {
            AndroidParentStore.worker()
            instance?.let { return it }
            check(Build.VERSION.SDK_INT >= 30) { "system crypto authentication requires Android 11" }
            check(activity.getSystemService(KeyguardManager::class.java).isDeviceSecure)
            val store = keys()
            if (!store.containsAlias(ALIAS)) {
                // Never regenerate a missing owner key to take over an existing encrypted domain.
                check(!store.containsAlias("little-buddy-v2-parent-v1"))
                check(listOf("v2-parent-v1", "v2-parent-v1.bak", "v2-parent-v1.new")
                    .none { activity.noBackupFilesDir.resolve(it).exists() })
                KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                    initialize(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                        .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                        .setDigests(KeyProperties.DIGEST_SHA256).setUserAuthenticationRequired(true)
                        .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
                        .build())
                }.generateKeyPair() // Key generation alone grants no authority and writes no PIN record.
            }
            val publicKey = keys().getCertificate(ALIAS).publicKey
            val binding = MessageDigest.getInstance("SHA-256").digest(publicKey.encoded)
                .joinToString("") { "%02x".format(it) }
            return AndroidOwner(binding, OwnerReceipt(publicKey, binding, SystemClock::elapsedRealtime))
                .also { instance = it }
        }
    }
}

/** Main-thread prompt. Focus loss revokes panel authority; true Activity pause cancels this flow.
 * A successful crypto operation is delivered only after focus returns, to a fresh model page.
 * Nothing is saved across Activity/process recreation; old callback identities cannot be reused.
 */
internal class AndroidOwnerPrompt(private val activity: Activity, private val work: (() -> Unit) -> Unit,
    private val changed: () -> Unit) {
    private var serial = 0L
    private var signal: CancellationSignal? = null
    private var pending: Pair<OwnerOperation, Signature>? = null
    private var begun = 0L
    fun begin(operation: OwnerOperation) {
        cancel(); val ticket = serial; begun = SystemClock.elapsedRealtime()
        work {
            val result = runCatching { AndroidOwner.open(activity).signature() }
            activity.runOnUiThread {
                if (serial != ticket || activity.isFinishing || !activity.hasWindowFocus()) return@runOnUiThread
                val signature = result.getOrNull() ?: run { changed(); return@runOnUiThread }
                if (Build.VERSION.SDK_INT < 30) { changed(); return@runOnUiThread }
                val cancellation = CancellationSignal(); signal = cancellation
                val title = when (operation) {
                    OwnerOperation.INITIALIZE_PIN -> "系统验证后初始化家长PIN"
                    OwnerOperation.RESET_PIN -> "系统验证后恢复家长PIN"
                    OwnerOperation.PROVISION_ENDPOINT -> "系统验证后导入连接配置"
                }
                val prompt = BiometricPrompt.Builder(activity).setTitle(title)
                    .setDescription("验证后才可初始化、恢复 PIN 或导入已发行的设备连接配置。")
                    .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG or
                        BiometricManager.Authenticators.DEVICE_CREDENTIAL).build()
                try {
                    prompt.authenticate(BiometricPrompt.CryptoObject(signature), cancellation, activity.mainExecutor,
                        object : BiometricPrompt.AuthenticationCallback() {
                            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                                if (serial != ticket || result.cryptoObject?.signature !== signature) return
                                signal = null; pending = operation to signature; changed()
                            }
                            override fun onAuthenticationError(code: Int, text: CharSequence) {
                                if (serial != ticket) return
                                signal = null; pending = null; changed()
                            }
                        })
                } catch (_: Exception) { if (serial == ticket) { signal = null; changed() } }
            }
        }
    }
    fun take(): Pair<OwnerOperation, (OwnerChallenge) -> Boolean>? {
        if (!activity.hasWindowFocus() || SystemClock.elapsedRealtime() - begun >= 60_000) { pending = null; return null }
        val value = pending ?: return null; pending = null
        val once = AtomicBoolean(false); val expires = begun + 60_000
        return value.first to { challenge -> challenge.operation == value.first &&
            SystemClock.elapsedRealtime() < expires && once.compareAndSet(false, true) &&
            AndroidOwner.open(activity).approve(challenge, value.second) }
    }
    fun cancel() { serial++; pending = null; val old = signal; signal = null; old?.cancel() }
}
