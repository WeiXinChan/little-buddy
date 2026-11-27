package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import javax.crypto.SecretKey
import javax.crypto.KeyGenerator

class IsolatedRecoveryRuntimeTest {
    private class Rig:ParentRuntimePlatform,AutoCloseable {
        val dir=Files.createTempDirectory("isolated-runtime-").toFile()
        val old=dir.resolve("legacy");val oldBackup=dir.resolve("legacy.bak")
        val local=dir.resolve("local");val selected=dir.resolve("selected")
        val oldKey=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
        var localKey:SecretKey?=null;var localCreates=0;var localWrites=0;var legacyOpens=0;var certReads=0
        var alias=false;var certificate:String?=null;var corruptMarker=false;var markerFailure=false;var failCommit=false
        var cached:ParentDomain?=null
        var presetValue:ParentConnection?=ParentConnection("wss://127.0.0.1:19483/v2/voice","s".repeat(64),"v2-device-oppo")
        init {
            // Old bytes are deliberately unreadable without their lost AAD; recovery never reads them.
            old.writeBytes(ParentEnvelope.seal(ParentCodec.encode(ParentRecord(ByteArray(16),ByteArray(32),volumeLimit=25)),oldKey,"lost-binding".toByteArray()))
            oldBackup.writeBytes(old.readBytes())
        }
        override fun requireWorker(){}
        override fun existingStore()=old.exists()
        override fun legacyAliasPresent()=alias
        override fun legacyBinding():String?{certReads++;return certificate}
        override fun marker():ByteArray?=null
        override fun createMarker(){fail("must not create original selector")}
        override fun domain(binding:String):ParentDomain{legacyOpens++;error("must not open legacy store")}
        override fun preset()=presetValue
        override fun isolatedMarker()=if(corruptMarker)byteArrayOf(2) else if(selected.exists())selected.readBytes() else null
        override fun isolatedExists()=local.exists()||localKey!=null
        override fun publishIsolatedMarker(){if(markerFailure)throw java.io.IOException("synthetic marker failure");selected.writeBytes(byteArrayOf(1))}
        override fun isolatedDomain():ParentDomain= cached?:run {
            val sealed=SealedParentStore(object:ParentRecordFile{
                override fun read()=if(local.exists())local.readBytes() else null
                override fun commit(bytes:ByteArray,authorized:()->Boolean){check(authorized());local.writeBytes(bytes);localWrites++}
                override fun publish(bytes:ByteArray,transaction:ParentCommit){
                    if(failCommit)throw java.io.IOException("synthetic interrupted initialization")
                    val staging=dir.resolve("prepared");staging.writeBytes(bytes);transaction.claim()
                    Files.move(staging.toPath(),local.toPath(),java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING);localWrites++
                }
            },object:ParentKeyProvider{
                override fun exists()=localKey!=null
                override fun existing()=localKey
                override fun create():SecretKey{check(localKey==null);localCreates++;return KeyGenerator.getInstance("AES").apply{init(256)}.generateKey().also{localKey=it}}
            },"stable-local-aad".toByteArray())
            ParentDomain(sealed,{100L},{},binding="isolated",localManagement=true).also{cached=it}
        }
        fun result()=AndroidParentRuntime.configuration(this)
        fun snapshot()=listOf(old.readBytes(),oldBackup.readBytes())
        fun assertLegacyUnchanged(before:List<ByteArray>){assertArrayEquals(before[0],old.readBytes());assertArrayEquals(before[1],oldBackup.readBytes());assertEquals(0,legacyOpens)}
        override fun close(){dir.deleteRecursively()}
    }
    @Test fun exactObservedMissingLegacyBindingUsesIssuedIdentityAndDefaultSettings()=Rig().use{r->
        val old=r.snapshot();val token=r.presetValue!!.credential
        val result=r.result();assertEquals(ConfigurationStatus.READY,result.status)
        assertEquals(60,result.configuration!!.playback.volume);assertEquals(100,result.configuration.playback.rate);assertEquals(600,result.configuration.playback.durationSeconds)
        assertEquals(token,result.configuration.connection!!.credential);assertEquals("v2-device-oppo",result.configuration.connection.sshUser)
        assertEquals(1,r.localCreates);assertEquals(1,r.localWrites);assertArrayEquals(byteArrayOf(1),r.selected.readBytes());r.assertLegacyUnchanged(old)
    }
    @Test fun committedSelectionReopensWithoutLegacyCertificateOrReimportingPreset()=Rig().use{r->
        val old=r.snapshot();assertEquals(ConfigurationStatus.READY,r.result().status);val bytes=r.local.readBytes();val certReads=r.certReads
        r.cached=null;r.presetValue=null
        repeat(3){assertEquals(ConfigurationStatus.READY,r.result().status);r.cached=null}
        assertEquals(certReads,r.certReads);assertArrayEquals(bytes,r.local.readBytes());assertEquals(1,r.localCreates);assertEquals(1,r.localWrites);r.assertLegacyUnchanged(old)
    }
    @Test fun committedStoreWithoutMarkerFinishesSelectionOnNextProcess()=Rig().use{r->
        val old=r.snapshot();r.markerFailure=true;assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status)
        assertTrue(r.local.exists());assertFalse(r.selected.exists());val bytes=r.local.readBytes()
        r.cached=null;r.markerFailure=false;r.presetValue=null
        assertEquals(ConfigurationStatus.READY,r.result().status);assertArrayEquals(bytes,r.local.readBytes());assertEquals(1,r.localCreates);assertEquals(1,r.localWrites);r.assertLegacyUnchanged(old)
    }
    @Test fun aliasOnlyInterruptedInitializationNeverRegeneratesOrPublishesMarker()=Rig().use{r->
        val old=r.snapshot();r.failCommit=true;assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status)
        assertNotNull(r.localKey);assertFalse(r.local.exists());assertFalse(r.selected.exists())
        r.cached=null;r.failCommit=false
        assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status);assertEquals(1,r.localCreates);assertEquals(0,r.localWrites);r.assertLegacyUnchanged(old)
    }
    @Test fun corruptedNewCiphertextFailsClosedWithoutOverwrite()=Rig().use{r->
        val old=r.snapshot();assertEquals(ConfigurationStatus.READY,r.result().status)
        val bytes=r.local.readBytes();bytes[bytes.lastIndex]=(bytes.last().toInt() xor 1).toByte();r.local.writeBytes(bytes);r.cached=null
        assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status);assertArrayEquals(bytes,r.local.readBytes());assertEquals(1,r.localCreates);assertEquals(1,r.localWrites);r.assertLegacyUnchanged(old)
    }
    @Test fun missingNewKeyNeverCreatesReplacement()=Rig().use{r->
        val old=r.snapshot();assertEquals(ConfigurationStatus.READY,r.result().status);val bytes=r.local.readBytes();r.localKey=null;r.cached=null
        assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status);assertArrayEquals(bytes,r.local.readBytes());assertEquals(1,r.localCreates);r.assertLegacyUnchanged(old)
    }
    @Test fun committedMarkerWithMissingWholeNamespaceCannotInitializeAgain()=Rig().use{r->
        val old=r.snapshot();r.selected.writeBytes(byteArrayOf(1))
        assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status);assertEquals(0,r.localCreates);assertFalse(r.local.exists());r.assertLegacyUnchanged(old)
    }
    @Test fun invalidSelectionNeverFallsBackToLegacyOrResets()=Rig().use{r->
        val old=r.snapshot();r.corruptMarker=true
        assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status);assertEquals(0,r.localCreates);r.assertLegacyUnchanged(old)
    }
    @Test fun absentIssuedPresetDoesNotCreateLocalKeyOrSelector()=Rig().use{r->
        val old=r.snapshot();r.presetValue=null
        assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status);assertEquals(0,r.localCreates);assertFalse(r.selected.exists());r.assertLegacyUnchanged(old)
    }
    @Test fun aliasStillPresentWithMissingCertificateIsNotAuthorizedRecoveryCase()=Rig().use{r->
        val old=r.snapshot();r.alias=true
        assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status);assertEquals(0,r.localCreates);r.assertLegacyUnchanged(old)
    }
    @Test fun managementReentryAndNewSettingsWriteUseOnlyRecoveredNamespace()=Rig().use{r->
        val old=r.snapshot();val model=ParentPanelModel({check(r.result().status==ConfigurationStatus.READY);r.cached},
            {it()},{it()},{},{},ownerRequest={fail("must not prompt")},directManagement=true)
        model.open();assertEquals(PanelMode.SETTINGS,model.state.mode);assertTrue(model.hasSavedConnection)
        model.saveExecutionSettings(ParentPlaybackSettings(40,100,120));model.pause();model.open()
        assertEquals(PanelMode.SETTINGS,model.state.mode);assertEquals(40,model.state.settings!!.volume)
        model.exit();r.cached=null;assertEquals(40,r.result().configuration!!.playback.volume);r.assertLegacyUnchanged(old)
    }
    @Test fun competingWorkersDoNotCreateTwoKeysOrCorruptSelection()=Rig().use{r->
        val old=r.snapshot();val results=java.util.Collections.synchronizedList(mutableListOf<ConfigurationStatus>())
        val start=java.util.concurrent.CountDownLatch(1)
        val workers=(1..2).map{Thread{start.await();results.add(r.result().status)}}
        workers.forEach{it.start()};start.countDown();workers.forEach{it.join(5000);assertFalse(it.isAlive)}
        assertTrue(results.contains(ConfigurationStatus.READY));assertEquals(ConfigurationStatus.READY,r.result().status)
        assertEquals(1,r.localCreates);assertEquals(1,r.localWrites);assertArrayEquals(byteArrayOf(1),r.selected.readBytes());r.assertLegacyUnchanged(old)
    }
}
