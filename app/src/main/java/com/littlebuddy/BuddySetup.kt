package com.littlebuddy

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal class BuddyConnection(val url: HttpUrl, val token: String) {
    companion object {
        fun parse(address: String, token: String): BuddyConnection? {
            if (!address.startsWith("wss://") || !token.matches(Regex("[a-zA-Z0-9]{32,256}"))) return null
            val url = ("https://" + address.removePrefix("wss://")).toHttpUrlOrNull() ?: return null
            if (url.encodedPath != "/v1/animal" || url.username.isNotEmpty() ||
                url.password.isNotEmpty() || url.query != null || url.fragment != null) return null
            return BuddyConnection(url, token)
        }
    }
}

internal class BuddySetup(private val context: Context, private val ssh: Boolean = false) {
    private val file = android.util.AtomicFile(context.noBackupFilesDir
        .resolve(if (ssh) "buddy-ssh-connection" else "buddy-connection"))

    fun load(): BuddyConnection? = runCatching {
        val bytes = file.readFully()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val key = keyStore().getKey(KEY_ALIAS, null) as SecretKey
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, bytes, 0, IV_BYTES))
        val config = JSONObject(String(cipher.doFinal(bytes, IV_BYTES, bytes.size - IV_BYTES), Charsets.UTF_8))
        BuddyConnection.parse(config.getString("address"), config.getString("token"))
            ?.takeIf { !ssh || it.url == BuddySshProfile.endpoint }
    }.getOrNull()

    private fun save(config: BuddyConnection) {
        val store = keyStore()
        val key = store.getKey(KEY_ALIAS, null) as SecretKey? ?: KeyGenerator
            .getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
                init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build())
                generateKey()
            }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key)
        check(cipher.iv.size == IV_BYTES)
        val plaintext = JSONObject().put("address", config.url.toString().replaceFirst("https:", "wss:"))
            .put("token", config.token).toString().toByteArray(Charsets.UTF_8)
        val encrypted = try {
            cipher.doFinal(plaintext)
        } finally {
            plaintext.fill(0)
        }
        val output = file.startWrite()
        try {
            output.write(cipher.iv)
            output.write(encrypted)
            file.finishWrite(output)
        } catch (failure: Exception) {
            file.failWrite(output)
            throw failure
        }
        check(load() != null)
    }

    fun form(previousAddress: HttpUrl?, complete: (BuddyConnection) -> Unit): View {
        val body = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
        }
        fun field(label: String, variation: Int) = EditText(context).apply {
            hint = label
            inputType = InputType.TYPE_CLASS_TEXT or variation or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            isSingleLine = true
            isSaveEnabled = false
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            if (variation == InputType.TYPE_TEXT_VARIATION_PASSWORD) {
                imeOptions = android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
            }
            body.addView(this, LinearLayout.LayoutParams(-1, -2))
        }
        body.addView(TextView(context).apply {
            text = "安装配置"
            textSize = 26f
        })
        val address = if (ssh) null else field("WSS 服务地址", InputType.TYPE_TEXT_VARIATION_URI)
        previousAddress?.let { address?.setText(it.toString().replaceFirst("https:", "wss:")) }
        val key = if (ssh) runCatching { BuddySshIdentity.load(create = true).registrationKey() } else null
        if (ssh) {
            body.addView(TextView(context).apply {
                text = "请注册这台设备的 SSH 公钥"
            })
            body.addView(TextView(context).apply {
                text = key?.getOrNull() ?: "设备密钥不可用，请重新打开安装配置"
                setTextIsSelectable(true)
            })
        }
        val token = field("设备令牌", InputType.TYPE_TEXT_VARIATION_PASSWORD)
        val feedback = TextView(context).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        if (previousAddress != null) feedback.text = "设备令牌已失效，请输入新令牌"
        body.addView(feedback)
        body.addView(Button(context).apply {
            text = "保存并进入"
            isEnabled = key?.isFailure != true
            setOnClickListener {
                val endpoint = if (ssh) BuddySshProfile.endpoint.toString().replaceFirst("https:", "wss:")
                    else address?.text.toString().trim()
                val config = BuddyConnection.parse(endpoint, token.text.toString().trim())
                if (config == null) {
                    feedback.text = if (ssh) "请检查设备令牌" else "请检查 WSS 地址和设备令牌"
                } else if (runCatching { save(config) }.isFailure) {
                    feedback.text = "保存失败，请再试一次"
                } else {
                    context.getSystemService(android.view.inputmethod.InputMethodManager::class.java)
                        .hideSoftInputFromWindow(token.windowToken, 0)
                    token.text.clear()
                    address?.text?.clear()
                    complete(config)
                }
            }
        })
        return ScrollView(context).apply {
            addView(body)
            applyBuddyInsets(24)
        }
    }

    private fun keyStore() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private companion object {
        const val KEY_ALIAS = "buddy-connection"
        const val IV_BYTES = 12
    }
}
