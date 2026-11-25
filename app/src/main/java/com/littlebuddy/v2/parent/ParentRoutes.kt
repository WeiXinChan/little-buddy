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

/** No trusted device binding/owner issuer has been configured. Never substitute an installation
 * ID, Intent extra or test proof for ownership. A reviewed composition provider is still OPEN.
 * Once it exists it must call AndroidParentDomain.open(context, verifiedBinding) on the worker.
 */
internal object AndroidParentRuntime {
    private fun verifiedDeviceBinding(): String? = null // D04: no reviewed issuer/provider yet.
    fun load(activity: Activity): ParentDomain? {
        AndroidParentStore.worker()
        val binding = verifiedDeviceBinding() ?: return null
        return AndroidParentDomain.open(activity.applicationContext, binding)
    }
}
