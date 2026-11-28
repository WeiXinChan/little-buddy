package com.littlebuddy.v2.feedback

import java.security.*
import java.security.spec.AlgorithmParameterSpec
import javax.crypto.*
import javax.crypto.spec.GCMParameterSpec
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

/** JVM negative control for Android's documented randomized-encryption rule, NOT AndroidKeyStore. */
class FeedbackKeystorePolicyTest {
    class PolicyKey(val delegate:SecretKey):SecretKey {
        override fun getAlgorithm()="AES"
        override fun getFormat():String?=null
        override fun getEncoded():ByteArray?=null
    }
    class PolicyCipher:CipherSpi() {
        private val delegate=Cipher.getInstance("AES/GCM/NoPadding","SunJCE")
        override fun engineSetMode(mode:String) {}
        override fun engineSetPadding(padding:String) {}
        override fun engineGetBlockSize()=delegate.blockSize
        override fun engineGetOutputSize(n:Int)=delegate.getOutputSize(n)
        override fun engineGetIV():ByteArray=delegate.iv
        override fun engineGetParameters():AlgorithmParameters=delegate.parameters
        override fun engineInit(op:Int,key:Key,random:SecureRandom?) {delegate.init(op,(key as PolicyKey).delegate,random)}
        override fun engineInit(op:Int,key:Key,params:AlgorithmParameterSpec?,random:SecureRandom?) {
            if(op==Cipher.ENCRYPT_MODE)throw InvalidAlgorithmParameterException("SYNTHETIC_CALLER_IV_REJECTED")
            delegate.init(op,(key as PolicyKey).delegate,params,random)
        }
        override fun engineInit(op:Int,key:Key,params:AlgorithmParameters?,random:SecureRandom?) {
            if(op==Cipher.ENCRYPT_MODE)throw InvalidAlgorithmParameterException("SYNTHETIC_CALLER_IV_REJECTED")
            delegate.init(op,(key as PolicyKey).delegate,params,random)
        }
        override fun engineUpdate(input:ByteArray,offset:Int,len:Int):ByteArray?=delegate.update(input,offset,len)
        override fun engineUpdate(input:ByteArray,offset:Int,len:Int,output:ByteArray,out:Int)=delegate.update(input,offset,len,output,out)
        override fun engineDoFinal(input:ByteArray,offset:Int,len:Int):ByteArray=delegate.doFinal(input,offset,len)
        override fun engineDoFinal(input:ByteArray,offset:Int,len:Int,output:ByteArray,out:Int)=delegate.doFinal(input,offset,len,output,out)
        override fun engineUpdateAAD(input:ByteArray,offset:Int,len:Int){delegate.updateAAD(input,offset,len)}
    }
    private class Policy:Provider("FeedbackTestPolicy",1.0,"Synthetic randomized-encryption policy") {
        init {put("Cipher.AES/GCM/NoPadding",PolicyCipher::class.java.name)}
    }
    private fun underPolicy(action:()->Unit) {
        val provider=Policy()
        check(Security.insertProviderAt(provider,1)==1)
        try {action()} finally {Security.removeProvider(provider.name)}
    }
    @Test fun emptyFirstCorePersistsAndOwnerCanReopenWithoutAuthentication() {
        val dir=Files.createTempDirectory("feedback-policy-").toFile()
        val rawKey=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
        val key=PolicyKey(rawKey)
        try {underPolicy {
            val files=PrivateVaultFiles(dir)
            val lease=java.io.File(dir,"owner")
            FeedbackCoreOwner(lease,{FeedbackVault(files,key)},FeedbackClock{1000L}).use {owner->
                val core=owner.open(DenyParentAuthorizer)
                assertNotNull(FeedbackVault(files,key).load())
                assertNotNull(files.read("materials"));assertNotNull(files.read("ledger"))
                val blocked=FeedbackCoreOwner(lease,{error("must not open second vault")},FeedbackClock{1000L})
                try {blocked.open(DenyParentAuthorizer);fail()}catch(e:FeedbackFailure){assertEquals(Failure.STORAGE,e.reason)}
                finally {blocked.close()}
            }
            FeedbackCoreOwner(lease,{FeedbackVault(files,key)},FeedbackClock{1000L}).use {owner->
                owner.open(DenyParentAuthorizer)
                assertNotNull(FeedbackVault(files,key).load())
            }
        }} finally {dir.deleteRecursively()}
    }
    @Test fun oldIvPrefixedCiphertextIsReadableAndResaveRetainsPayloadAndCorruptionFailsClosed() {
        val dir=Files.createTempDirectory("feedback-legacy-").toFile()
        val rawKey=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
        val key=PolicyKey(rawKey)
        val files=PrivateVaultFiles(dir);val original="fixed synthetic old record".toByteArray()
        fun legacy(bytes:ByteArray):ByteArray {
            val cipher=Cipher.getInstance("AES/GCM/NoPadding","SunJCE")
            val nonce=ByteArray(12).also{SecureRandom().nextBytes(it)}
            cipher.init(Cipher.ENCRYPT_MODE,rawKey,GCMParameterSpec(128,nonce))
            cipher.updateAAD("little-buddy-m09-v1".toByteArray())
            return nonce+cipher.doFinal(bytes)
        }
        try {
            val encrypted=legacy(original);files.replace("materials",encrypted)
            files.replace("ledger",legacy(digest(encrypted).toByteArray(Charsets.US_ASCII)))
            underPolicy {
                val vault=FeedbackVault(files,key)
                assertArrayEquals(original,vault.load())
                vault.save(original)
                assertArrayEquals(original,FeedbackVault(files,key).load())
                assertFalse(encrypted.contentEquals(files.read("materials")))
                val before=files.read("materials")!!
                val ledger=files.read("ledger")!!;ledger[ledger.lastIndex]=(ledger.last().toInt() xor 1).toByte()
                files.replace("ledger",ledger)
                try {FeedbackVault(files,key).load();fail()}catch(e:FeedbackFailure){assertEquals(Failure.QUARANTINED,e.reason)}
                assertArrayEquals(before,files.read("materials"));assertArrayEquals(ledger,files.read("ledger"))
            }
        } finally {original.fill(0);dir.deleteRecursively()}
    }
}
