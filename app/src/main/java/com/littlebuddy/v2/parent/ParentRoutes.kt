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

/** Local system authentication is the issuer; remote family recovery/endpoint issuance are separate. */
internal object AndroidParentRuntime {
    @Volatile private var authority: AndroidOwner? = null
    fun discard(challenge: OwnerChallenge) { authority?.discard(challenge) }
    fun helpSettings(activity: Activity): ParentPlaybackSettings? {
        if (!AndroidParentStore.hasExistingDomain(activity)) return ParentPlaybackSettings()
        return load(activity).childConfiguration()?.playback
    }
    /** Deletion-only recovery can load existing credentials, never initialize an owner/domain. */
    fun existing(context: android.content.Context): ParentDomain? {
        if(!AndroidParentStore.hasExistingDomain(context))return null
        val owner=AndroidOwner.open(context,create=false)
        return AndroidParentDomain.open(context.applicationContext,owner.binding,owner)
    }
    fun load(activity: Activity): ParentDomain {
        val owner = AndroidOwner.open(activity); authority = owner
        return AndroidParentDomain.open(activity.applicationContext, owner.binding, owner)
    }
}
