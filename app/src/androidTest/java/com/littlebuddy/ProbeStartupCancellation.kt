package com.littlebuddy

import com.littlebuddy.v2.CaptureBootstrap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Caller-thread cache erasure shared by foreground, timeout and final cancellation. No native IO. */
internal class ProbeStartupCancellation(private val cancelled:AtomicBoolean) {
    private val prefix=AtomicReference<CaptureBootstrap?>()
    fun install(value:CaptureBootstrap) {
        check(prefix.compareAndSet(null,value))
        if(cancelled.get())value.clear() // Covers cancellation racing or preceding registration.
    }
    fun clear(){prefix.get()?.clear()}
    fun cancel(){cancelled.set(true);clear()}
}
