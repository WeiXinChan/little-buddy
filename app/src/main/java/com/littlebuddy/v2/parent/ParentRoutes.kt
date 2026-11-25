package com.littlebuddy.v2.parent

import android.app.Activity
import android.view.View

/** M08-owned host port. Later composition wraps M09 FeedbackPageHandle; no parallel host edits. */
internal interface ParentRoutePage {
    val view: View
    fun pause()
    fun close()
}
internal fun interface ParentFeedbackRoute {
    fun create(activity: Activity, domain: ParentDomain, grant: ParentDomain.Grant,
               onExit: () -> Unit): ParentRoutePage?
}
internal object PendingFeedbackRoute : ParentFeedbackRoute {
    override fun create(activity: Activity, domain: ParentDomain, grant: ParentDomain.Grant,
                        onExit: () -> Unit): ParentRoutePage? = null
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
