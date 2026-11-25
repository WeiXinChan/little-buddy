package com.littlebuddy.v2.parent

import java.net.URI

/** Existing, independently issued V2 device credential; not an owner issuer or model API key. */
internal class ParentConnection(val address: String, val credential: String, val sshUser: String? = null) {
    init {
        val uri = URI(address)
        require(address.length <= 400 && address.startsWith("wss://") && uri.host != null &&
            uri.path == "/v2/voice" && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null &&
            (uri.port == -1 || uri.port in 1..65535))
        if (sshUser != null) {
            require(address == "wss://127.0.0.1:19483/v2/voice")
            require(sshUser.matches(Regex("[a-z_][a-z0-9_-]{0,30}")) && sshUser != "root" && sshUser != "little-buddy-device")
        }
        require(credential.matches(Regex("[a-zA-Z0-9]{32,256}")))
    }
    /** Old encrypted records remain readable; unusable loopback direct mode never starts a socket. */
    fun requireRunnable() {
        if (sshUser==null) {
            val host=URI(address).host.lowercase()
            require(host !in setOf("localhost","::1","[::1]","0.0.0.0","[::]","::") && !host.startsWith("127."))
        }
    }
}
internal class ParentPlaybackSettings(val volume: Int = 60, val rate: Int = 100, val durationSeconds: Int = 600) {
    init { require(volume in 0..100 && rate in 85..115 && durationSeconds in 60..600) }
}
internal class ParentChildConfiguration(val playback: ParentPlaybackSettings, val connection: ParentConnection?)
