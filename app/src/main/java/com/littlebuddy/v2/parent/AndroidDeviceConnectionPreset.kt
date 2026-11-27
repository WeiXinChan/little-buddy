package com.littlebuddy.v2.parent

import android.content.Context
import com.littlebuddy.BuildConfig

internal object AndroidDeviceConnectionPreset {
    /** Worker only; never log a parser exception, payload, token or derived token fingerprint. */
    fun load(context: Context): DeviceConnectionPreset? {
        if (!BuildConfig.V2_DEVICE_PRESET) return null
        return try { DeviceConnectionPreset.read(context.assets.open(DeviceConnectionPreset.ASSET)) }
        catch (_: Exception) { null }
    }
}
