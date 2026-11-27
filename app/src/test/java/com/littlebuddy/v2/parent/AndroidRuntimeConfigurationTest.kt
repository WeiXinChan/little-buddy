package com.littlebuddy.v2.parent

import java.nio.file.Files
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import org.junit.Assert.*
import org.junit.Test

/** Calls the actual AndroidParentRuntime entry after its platform boundary. Real AES/GCM,
 * codec, on-disk record, runtime sequencing, migration and child read; no mocked ParentDomain.
 * Android Keystore/AtomicFile/Context themselves still require target-device evidence. */
class AndroidRuntimeConfigurationTest {
    private class Rig:ParentRuntimePlatform,AutoCloseable {
        val dir=Files.createTempDirectory("runtime-config-").toFile()
        val file=dir.resolve("record");val selector=dir.resolve("selector")
        var certificate:String?="synthetic-public-binding";var certificateError:Exception?=null
        var aliasOverride:Boolean?=null
        override fun legacyAliasPresent()=aliasOverride?: (certificate!=null)
        var key:SecretKey?=KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
        var keyError:Exception?=null;var failCommit=false;var creates=0;var writes=0;var opens=0
        var cached:ParentDomain?=null;var reads=0;var failChildRead=false
        var issued=ParentConnection("wss://127.0.0.1:19483/v2/voice","s".repeat(64),"v2-device-oppo")
        var presetValue:ParentConnection?=issued
        val events=mutableListOf<ConfigurationDiagnostic.Event>()
        init{ConfigurationDiagnostic.install{events.add(it)}}
        override fun requireWorker(){}
        override fun existingStore()=file.exists()||key!=null
        override fun legacyBinding():String? {certificateError?.let{throw it};return certificate}
        override fun marker()=if(selector.exists())selector.readBytes() else null
        override fun createMarker(){selector.writeBytes(byteArrayOf(1))}
        override fun preset()=presetValue
        private fun aad(binding:String)="little-buddy:v2:parent:1:$binding".toByteArray()
        fun seed(record:ParentRecord){file.writeBytes(ParentEnvelope.seal(ParentCodec.encode(record),key!!,aad(certificate!!)))}
        override fun domain(binding:String):ParentDomain {
            opens++
            return cached?:run {
                val sealed=SealedParentStore(object:ParentRecordFile {
                    override fun read()=if(file.exists())file.readBytes() else null
                    override fun commit(bytes:ByteArray,authorized:()->Boolean){check(authorized());publishBytes(bytes)}
                    override fun publish(bytes:ByteArray,transaction:ParentCommit){
                        check(!failCommit);transaction.claim();publishBytes(bytes)
                    }
                    private fun publishBytes(bytes:ByteArray){writes++;val staging=dir.resolve("staged");staging.writeBytes(bytes)
                        Files.move(staging.toPath(),file.toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING,java.nio.file.StandardCopyOption.ATOMIC_MOVE)}
                },object:ParentKeyProvider {
                    override fun exists()=key!=null
                    override fun existing()=ConfigurationDiagnostic.step(ConfigurationDiagnostic.Stage.KEY_LOAD){keyError?.let{throw it};key}.also {
                        ConfigurationDiagnostic.event(ConfigurationDiagnostic.Stage.KEY_LOAD,if(it!=null)ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
                    }
                    override fun create():SecretKey{creates++;return KeyGenerator.getInstance("AES").apply{init(256)}.generateKey().also{key=it}}
                },aad(binding))
                val store=object:ParentStore {
                    override fun read()=ConfigurationDiagnostic.step(ConfigurationDiagnostic.Stage.STORE_READ){
                        reads++;if(failChildRead && reads>1)throw java.io.IOException("synthetic unreadable record")
                        sealed.read()
                    }
                    override fun write(record:ParentRecord,authorized:()->Boolean)=sealed.write(record,authorized)
                    override fun commit(record:ParentRecord,transaction:ParentCommit)=ConfigurationDiagnostic.observe(ConfigurationDiagnostic.Stage.STORE_COMMIT){sealed.commit(record,transaction)}
                }
                ParentDomain(store,{100L},{},binding=binding,localManagement=true).also{cached=it}
            }
        }
        fun result()=AndroidParentRuntime.configuration(this)
        fun seen(s:ConfigurationDiagnostic.Stage,r:ConfigurationDiagnostic.Reason)=events.any{it.stage==s&&it.reason==r}
        override fun close(){ConfigurationDiagnostic.install(null);dir.deleteRecursively()}
    }
    @Test fun realEncryptedLegacyRuntimeMigratesWithoutSystemCredentialAndRetainsConnection()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(16),ByteArray(32),5,60000,35,90,120,r.issued));r.presetValue=null
        val result=r.result();assertEquals(ConfigurationStatus.READY,result.status)
        assertEquals(35,result.configuration!!.playback.volume);assertEquals(90,result.configuration.playback.rate)
        assertEquals(r.issued.credential,result.configuration.connection!!.credential)
        assertEquals(r.issued.sshUser,result.configuration.connection.sshUser);assertEquals(0,r.creates)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.LEGACY_CERT,ConfigurationDiagnostic.Reason.PRESENT))
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.STORE_COMMIT,ConfigurationDiagnostic.Reason.SUCCESS))
        assertNotNull(r.cached!!.enterLocal(r.cached!!.enterPage()))
    }
    @Test fun freshNoLockscreenRuntimeUsesPresetAndReloadsOriginalCiphertext()=Rig().use{r->
        r.certificate=null;r.key=null
        assertEquals(ConfigurationStatus.READY,r.result().status);val bytes=r.file.readBytes();val writes=r.writes
        r.cached=null;assertEquals(ConfigurationStatus.READY,r.result().status)
        assertArrayEquals(bytes,r.file.readBytes());assertEquals(writes,r.writes);assertEquals(1,r.creates)
        assertArrayEquals(byteArrayOf(1),r.selector.readBytes())
    }
    @Test fun absentLegacyCertificateNeverRecreatesOrWritesStore()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(16),ByteArray(32),connection=r.issued));val bytes=r.file.readBytes();r.certificate=null
        assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status);assertEquals(0,r.opens);assertEquals(0,r.creates);assertEquals(0,r.writes)
        assertArrayEquals(bytes,r.file.readBytes());assertFalse(r.selector.exists())
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.LEGACY_CERT,ConfigurationDiagnostic.Reason.ABSENT))
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.ISOLATED_OPEN,ConfigurationDiagnostic.Reason.STATE))
    }
    @Test fun certificateApiFailureDoesNotLeakBodyOrAttemptMigration()=Rig().use{r->
        r.certificateError=SecurityException("never publish synthetic private body")
        assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status);assertEquals(0,r.opens)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.LEGACY_CERT,ConfigurationDiagnostic.Reason.SECURITY))
        assertFalse(r.events.toString().contains("private body"));assertFalse(r.events.toString().contains(r.issued.credential))
    }
    @Test fun invalidatedAesIsDistinctAndCannotBeReinitialized()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(16),ByteArray(32),connection=r.issued));val bytes=r.file.readBytes()
        r.keyError=java.security.UnrecoverableKeyException("synthetic sensitive body")
        assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.KEY_LOAD,ConfigurationDiagnostic.Reason.INVALID_KEY))
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.MIGRATION,ConfigurationDiagnostic.Reason.QUARANTINED))
        assertEquals(0,r.creates);assertEquals(0,r.writes);assertArrayEquals(bytes,r.file.readBytes())
    }
    @Test fun corruptCiphertextGivesBadTagAndKeepsOriginalBytes()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(16),ByteArray(32)));val bytes=r.file.readBytes();bytes[bytes.lastIndex]=(bytes.last().toInt() xor 1).toByte();r.file.writeBytes(bytes)
        assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.STORE_READ,ConfigurationDiagnostic.Reason.BAD_TAG))
        assertArrayEquals(bytes,r.file.readBytes());assertEquals(0,r.writes);assertEquals(0,r.creates)
    }
    @Test fun invalidMarkerStopsBeforeOpeningOrResettingDomain()=Rig().use{r->
        r.selector.writeBytes(byteArrayOf(2));assertEquals(ConfigurationStatus.LOAD_FAILED,r.result().status)
        assertEquals(0,r.opens);assertEquals(0,r.writes);assertArrayEquals(byteArrayOf(2),r.selector.readBytes())
    }
    @Test fun missingPresetAndMissingConnectionAreNotLoadFailure()=Rig().use{r->
        r.presetValue=null;r.seed(ParentRecord(ByteArray(16),ByteArray(32)))
        assertEquals(ConfigurationStatus.NO_CONNECTION,r.result().status)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.PRESET,ConfigurationDiagnostic.Reason.ABSENT))
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.CHILD_READ,ConfigurationDiagnostic.Reason.NO_CONNECTION))
    }
    @Test fun commitFailureDoesNotReportConfigurationReady()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(16),ByteArray(32),connection=r.issued));val bytes=r.file.readBytes();r.failCommit=true
        assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.STORE_COMMIT,ConfigurationDiagnostic.Reason.STATE))
        assertArrayEquals(bytes,r.file.readBytes());assertEquals(0,r.writes)
    }
    @Test fun diagnosticSinkFailureCannotBlockSuccessfulRuntime()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(16),ByteArray(32),connection=r.issued));ConfigurationDiagnostic.install{error("synthetic sink failure")}
        assertEquals(ConfigurationStatus.READY,r.result().status)
    }
    @Test fun childReadFailureIsNotConfusedWithLoadOrMissingConnection()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(0),ByteArray(0),connection=r.issued));val bytes=r.file.readBytes();r.failChildRead=true
        assertEquals(ConfigurationStatus.CHILD_MISSING,r.result().status)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.STORE_READ,ConfigurationDiagnostic.Reason.IO))
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.CHILD_READ,ConfigurationDiagnostic.Reason.EMPTY))
        assertArrayEquals(bytes,r.file.readBytes());assertEquals(0,r.writes);assertEquals(0,r.creates)
    }
    @Test fun configurationReservationSurvivesGeneralNoiseWithinTotal256Rows()=Rig().use{r->
        val budget=ConfigurationEventBudget(true)
        assertEquals(160,(1..1000).count{budget.general()})
        val admitted=mutableListOf<ConfigurationDiagnostic.Event>()
        ConfigurationDiagnostic.install{if(budget.configuration())admitted.add(it)}
        r.seed(ParentRecord(ByteArray(16),ByteArray(32),connection=r.issued))
        assertEquals(ConfigurationStatus.READY,r.result().status)
        assertTrue(admitted.any{it.stage==ConfigurationDiagnostic.Stage.CHILD_READ&&it.reason==ConfigurationDiagnostic.Reason.SUCCESS})
        val spare=(1..200).count{budget.configuration()}
        assertEquals(96,admitted.size+spare)
    }
    @Test fun normalDiagnosticBudgetStillSharesOriginal256Rows() {
        val b=ConfigurationEventBudget(false)
        repeat(128){assertTrue(b.general());assertTrue(b.configuration())}
        assertFalse(b.general());assertFalse(b.configuration())
    }
    @Test fun missingAesHandleCannotRegenerateKeyOrReplaceCiphertext()=Rig().use{r->
        r.seed(ParentRecord(ByteArray(16),ByteArray(32),connection=r.issued));val bytes=r.file.readBytes();r.key=null
        assertEquals(ConfigurationStatus.MIGRATION_FAILED,r.result().status)
        assertTrue(r.seen(ConfigurationDiagnostic.Stage.KEY_LOAD,ConfigurationDiagnostic.Reason.ABSENT))
        assertArrayEquals(bytes,r.file.readBytes());assertEquals(0,r.creates);assertEquals(0,r.writes)
    }
}
