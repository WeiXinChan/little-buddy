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
    fun load(activity: Activity): ParentDomain = ParentRuntimePath.load(platform(activity))
    fun configuration(activity: Activity): ConfigurationResult = configuration(platform(activity))
    internal fun configuration(platform: ParentRuntimePlatform): ConfigurationResult = ParentRuntimePath.configuration(platform)
    private fun local(context: android.content.Context): ParentDomain = ParentRuntimePath.load(platform(context))
    private fun platform(context: android.content.Context) = object : ParentRuntimePlatform {
        override fun requireWorker() = AndroidParentStore.worker()
        override fun existingStore() = AndroidParentStore.hasExistingDomain(context)
        override fun legacyBinding() = AndroidOwner.existingBinding()
        private val selector get() = context.noBackupFilesDir.resolve("v2-local-management-binding-v1")
        override fun marker(): ByteArray? {
            val marker=selector
            if(!marker.exists())return null
            check(marker.isFile && marker.length()==1L)
            return marker.readBytes()
        }
        override fun createMarker() {
            java.io.FileOutputStream(selector).use { it.write(byteArrayOf(1));it.fd.sync() }
        }
        override fun domain(binding:String) = AndroidParentDomain.open(context.applicationContext,binding)
        override fun preset(): ParentConnection? = AndroidDeviceConnectionPreset.load(context)?.let {
            val token=it.tokenChars()
            try { ParentConnection(it.address,String(token),it.user).also{c->c.requireRunnable()} }
            finally { token.fill('\u0000') }
        }
    }
}
