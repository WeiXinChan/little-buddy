package com.littlebuddy.v2.parent

import java.io.DataInputStream
import java.io.InputStream

/** Only present in an explicitly private device build. Not an owner proof or automatic save. */
internal class DeviceConnectionPreset private constructor(val user: String, val address: String,
                                                          private val credential: String) {
    fun tokenChars() = credential.toCharArray()
    override fun toString() = "DeviceConnectionPreset(private)"
    companion object {
        const val ASSET = "v2-device-preset.bin"
        fun read(input: InputStream): DeviceConnectionPreset = DataInputStream(input).use {
            require(it.readUTF() == "LBV2P1")
            val user = it.readUTF(); val address = it.readUTF(); val token = it.readUTF()
            require(it.read() == -1 && user == "v2-device-oppo" && address == "wss://127.0.0.1:19483/v2/voice")
            ParentConnection(address, token, user).requireRunnable()
            DeviceConnectionPreset(user, address, token)
        }
    }
}
