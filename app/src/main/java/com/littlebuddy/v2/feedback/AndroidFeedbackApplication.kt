package com.littlebuddy.v2.feedback

import android.app.Application

/** V2 manifest only: child/parent page visibility never gates local retention maintenance. */
class FeedbackApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        AndroidFeedbackRuntime.start(this)
    }
}
