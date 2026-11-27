package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream

class DeviceConnectionPresetTest {
    private fun bytes(user:String="v2-device-oppo",address:String="wss://127.0.0.1:19483/v2/voice",credential:String="a".repeat(32)):ByteArray {
        val out=ByteArrayOutputStream();DataOutputStream(out).use{it.writeUTF("LBV2P1");it.writeUTF(user);it.writeUTF(address);it.writeUTF(credential)};return out.toByteArray()
    }
    @Test fun explicitPrivatePresetIsEditableDataNotAutomaticAuthorization(){
        val value=DeviceConnectionPreset.read(ByteArrayInputStream(bytes()))
        assertEquals("v2-device-oppo",value.user);assertEquals("wss://127.0.0.1:19483/v2/voice",value.address)
        val chars=value.tokenChars();assertEquals("a".repeat(32),String(chars));chars.fill('\u0000')
        assertEquals("a".repeat(32),String(value.tokenChars()))
    }
    @Test fun stringRepresentationNeverContainsCredential(){val value=DeviceConnectionPreset.read(ByteArrayInputStream(bytes()));assertEquals("DeviceConnectionPreset(private)",value.toString())}
    @Test fun differentAccountRefuses(){try{DeviceConnectionPreset.read(ByteArrayInputStream(bytes(user="root")));fail()}catch(_:IllegalArgumentException){}}
    @Test fun differentAddressRefuses(){try{DeviceConnectionPreset.read(ByteArrayInputStream(bytes(address="wss://example.invalid/v2/voice")));fail()}catch(_:IllegalArgumentException){}}
    @Test fun malformedCredentialRefuses(){try{DeviceConnectionPreset.read(ByteArrayInputStream(bytes(credential="synthetic invalid")));fail()}catch(_:IllegalArgumentException){}}
    @Test fun trailingBytesRefuse(){try{DeviceConnectionPreset.read(ByteArrayInputStream(bytes()+byteArrayOf(1)));fail()}catch(_:IllegalArgumentException){}}
}
