package com.littlebuddy.v2.parent

import android.app.Activity
import android.view.View
import com.littlebuddy.v2.feedback.FeedbackPageFactory

/** M08-owned host port wrapping the M09 handle; feedback owns its view, host owns the route. */
internal interface ParentRoutePage {
    val view: View
    fun pause()
    fun close()
}
internal fun interface ParentFeedbackRoute {
    fun create(activity: Activity, domain: ParentDomain, grant: ParentDomain.Grant,
               onExit: () -> Unit): ParentRoutePage?
}
/** Only this host adapter supplies the production gate. The binding is captured per real page. */
internal object AndroidParentFeedbackRoute : ParentFeedbackRoute {
    override fun create(activity: Activity, domain: ParentDomain, grant: ParentDomain.Grant,
                        onExit: () -> Unit): ParentRoutePage? {
        val binding = ParentFeedbackBinding(domain, grant)
        return binding.build {
            val handle = FeedbackPageFactory.create(activity, domain, grant, binding.gate, onExit)
            object : ParentRoutePage {
                override val view get() = handle.view
                override fun pause() = binding.pause { handle.pause() }
                override fun close() = binding.close { handle.close() }
            }
        }
    }
}

/** Local management needs no lock-screen credential. Transport identity remains independent. */
internal object AndroidParentRuntime {
    fun discard(challenge: OwnerChallenge) { /* Legacy receipts are never issued in local mode. */ }
    fun helpSettings(activity: Activity): ParentPlaybackSettings? = load(activity).childConfiguration()?.playback
    fun existing(context: android.content.Context): ParentDomain? {
        if (!AndroidParentStore.hasExistingDomain(context)) return null
        return local(context)
    }
    fun load(activity: Activity): ParentDomain = local(activity)
    private fun local(context: android.content.Context): ParentDomain {
        AndroidParentStore.worker()
        val existing = AndroidParentStore.hasExistingDomain(context)
        // Preserve old AAD exactly. Never replace an unreadable existing record/key.
        val marker = context.noBackupFilesDir.resolve("v2-local-management-binding-v1")
        val binding = LocalManagementBinding.resolve(existing, AndroidOwner.existingBinding(),
            if (marker.exists()) { check(marker.isFile && marker.length() == 1L); marker.readBytes() } else null)
        if (!existing && binding == "v2-app-local-management-v1") {
            java.io.FileOutputStream(marker).use { it.write(byteArrayOf(1)); it.fd.sync() }
        }
        val domain = AndroidParentDomain.open(context.applicationContext, binding)
        val preset = AndroidDeviceConnectionPreset.load(context)?.let {
            val token = it.tokenChars()
            try { ParentConnection(it.address, String(token), it.user).also { c -> c.requireRunnable() } }
            finally { token.fill('\u0000') }
        }
        check(domain.initializeLocal(preset)) { "local parent storage unavailable" }
        return domain
    }
}
