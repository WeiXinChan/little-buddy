package com.littlebuddy.v2.parent

import org.junit.Assert.*
import org.junit.Test

/** Local management is explicitly not owner authentication. No Android credentials or PIN needed. */
class LocalManagementTest {
    private class Store(var value: ParentRecord? = null): ParentStore {
        var writes=0; var broken=false
        override fun read()=value
        override fun write(record: ParentRecord, authorized: ()->Boolean) {
            if (broken) error("synthetic storage failure")
            check(authorized()); value=record; writes++
        }
    }
    private val connection=ParentConnection("wss://127.0.0.1:19483/v2/voice", "s".repeat(64), "v2-device-oppo")
    private fun domain(s:Store, now:()->Long={100L}, local:Boolean=true)=ParentDomain(s,now,{},
        object:OwnerProof { override fun consume(challenge:OwnerChallenge):Boolean=error("must not consume owner proof") },
        "test-binding",object:PinHasher(){override fun derive(pin:CharArray,salt:ByteArray):ByteArray=error("must not derive PIN")},local)
    @Test fun freshInstallWithoutPinCreatesExplicitLocalSchemaAndConnection() {
        val s=Store();val d=domain(s);assertTrue(d.initializeLocal(connection))
        assertTrue(s.value!!.salt.isEmpty());assertTrue(s.value!!.hash.isEmpty())
        assertEquals(connection.address,d.childConfiguration()!!.connection!!.address)
        assertNotNull(d.enterLocal(d.enterPage()))
    }
    @Test fun migratesLegacySettingsAndExistingConnectionWithoutHasherOrProof() {
        val s=Store(ParentRecord(ByteArray(16){1},ByteArray(32){2},5,60000,35,90,120,connection))
        val d=domain(s);assertTrue(d.initializeLocal())
        val c=d.childConfiguration()!!;assertEquals(35,c.playback.volume);assertEquals(90,c.playback.rate)
        assertEquals(120,c.playback.durationSeconds);assertSame(connection,c.connection)
        assertEquals(0,s.value!!.failures);assertEquals(0L,s.value!!.cooldownMs)
    }
    @Test fun repeatOpenDoesNotRewriteOrReimportPreset() {
        val s=Store();val d=domain(s);assertTrue(d.initializeLocal(connection));val n=s.writes
        repeat(3){assertTrue(d.initializeLocal());assertNotNull(d.enterLocal(d.enterPage()))}
        assertEquals(n,s.writes)
    }
    @Test fun localCodecRoundTripAndRejectsInvalidLocalRetryState() {
        val r=ParentRecord(ByteArray(0),ByteArray(0),connection=connection)
        val out=ParentCodec.decode(ParentCodec.encode(r));assertTrue(out.hash.isEmpty());assertEquals(connection.sshUser,out.connection!!.sshUser)
        assertEquals(60,ParentCodec.decode(ParentCodec.encode(ParentRecord(ByteArray(0),ByteArray(0)))).volumeLimit)
        assertThrows(IllegalStateException::class.java){ParentCodec.encode(ParentRecord(ByteArray(0),ByteArray(0),failures=1))}
    }
    @Test fun legacyCodecStillReadableAndLocalGrantRequiresExplicitPolicy() {
        val r=ParentRecord(ByteArray(16),ByteArray(32),connection=connection)
        assertEquals(32,ParentCodec.decode(ParentCodec.encode(r)).hash.size)
        val d=domain(Store(r),local=false);assertFalse(d.initializeLocal());assertNull(d.enterLocal(d.enterPage()))
    }
    @Test fun localModeRejectsPinAndSystemChallengePaths() {
        val d=domain(Store());assertTrue(d.initializeLocal());val p=d.enterPage();val g=d.enterLocal(p)!!
        assertNull(d.beginOwnerOperation(OwnerOperation.INITIALIZE_PIN,p))
        val pin="012345".toCharArray();assertNull(d.verify(pin,p));assertTrue(pin.all{it=='\u0000'})
        assertFalse(d.changePin(g,"012345".toCharArray()))
    }
    @Test fun lifecycleRevokesOldPageAndNewEntryCannotBorrowOldGrant() {
        val d=domain(Store());d.initializeLocal();val p=d.enterPage();val old=d.enterLocal(p)!!
        d.invalidatePage(p);assertFalse(d.isAuthorized(old));assertFalse(d.saveVolumeLimit(old,90))
        val fresh=d.enterLocal(d.enterPage())!!;assertTrue(d.isAuthorized(fresh));assertFalse(d.isAuthorized(old))
    }
    @Test fun idleDeadlineStillRejectsSettingsAndFeedbackAdmission() {
        var t=100L;val d=domain(Store(),{t});d.initializeLocal();val g=d.enterLocal(d.enterPage())!!
        t+=ParentDomain.IDLE_MS;assertFalse(d.saveVolumeLimit(g,90));assertFalse(d.acceptProtected(g){fail("late admission")})
    }
    @Test fun failedMigrationKeepsOriginalRecordAndDoesNotGrantOrStartChild() {
        val old=ParentRecord(ByteArray(16),ByteArray(32),connection=connection);val s=Store(old);s.broken=true
        val d=domain(s);assertFalse(d.initializeLocal());assertSame(old,s.value)
        assertNull(d.enterLocal(d.enterPage()));assertNull(d.childConfiguration())
    }
    @Test fun realPanelOpensAndReopensSettingsWithoutPinOrOwnerPrompt() {
        val d=domain(Store());d.initializeLocal(connection)
        val screens=mutableListOf<PanelState>();val m=ParentPanelModel({d},{it()},{it()},{screens.add(it)},{},
            ownerRequest={fail("system prompt")},directManagement=true)
        m.open();assertEquals(PanelMode.SETTINGS,m.state.mode);assertTrue(m.hasSavedConnection)
        assertNull(m.navigate(PanelMode.CHANGE_PIN));m.pause();m.open();assertEquals(PanelMode.SETTINGS,m.state.mode)
        assertFalse(screens.any{it.mode==PanelMode.VERIFY || it.mode==PanelMode.OWNER_PIN})
        m.saveExecutionSettings(ParentPlaybackSettings(40,100,120));assertEquals(40,d.childConfiguration()!!.playback.volume)
    }
    @Test fun queuedOpenCannotGrantAfterHome() {
        val d=domain(Store());d.initializeLocal();val q=java.util.ArrayDeque<()->Unit>()
        val m=ParentPanelModel({d},{q.add(it)},{it()},{},{},directManagement=true)
        m.open();q.removeFirst()();m.pause();while(q.isNotEmpty())q.removeFirst()()
        assertEquals(PanelMode.UNAVAILABLE,m.state.mode);assertNull(m.currentRoute())
    }
    @Test fun emptyLocalSchemaIsExactly33Bytes() {
        assertEquals(33,ParentCodec.encode(ParentRecord(ByteArray(0),ByteArray(0))).size)
    }
    @Test fun allLegacySchemasMigrateWithoutLosingSettingsOrIdentity() {
        val records=listOf(ParentRecord(ByteArray(16),ByteArray(32)),
            ParentRecord(ByteArray(16),ByteArray(32),speechRate=90,durationSeconds=120),
            ParentRecord(ByteArray(16),ByteArray(32),connection=connection))
        records.forEachIndexed { i,r ->
            val bytes=ParentCodec.encode(r);assertEquals(i+1,java.nio.ByteBuffer.wrap(bytes).int)
            val old=ParentCodec.decode(bytes);val d=domain(Store(old));assertTrue(d.initializeLocal())
            val c=d.childConfiguration()!!;assertEquals(r.speechRate,c.playback.rate)
            assertEquals(r.connection?.sshUser,c.connection?.sshUser)
            assertEquals(r.connection?.credential,c.connection?.credential)
        }
    }
    @Test fun missingLegacyCertificateOrUnknownMarkerCannotSelectNewStore() {
        assertThrows(IllegalStateException::class.java){LocalManagementBinding.resolve(true,null,null)}
        assertThrows(IllegalStateException::class.java){LocalManagementBinding.resolve(true,null,byteArrayOf(2))}
        assertThrows(IllegalStateException::class.java){LocalManagementBinding.resolve(false,null,byteArrayOf())}
        assertEquals("old-public-binding",LocalManagementBinding.resolve(true,"old-public-binding",null))
        assertEquals(LocalManagementBinding.LOCAL,LocalManagementBinding.resolve(false,null,null))
        assertEquals(LocalManagementBinding.LOCAL,LocalManagementBinding.resolve(true,null,byteArrayOf(1)))
    }
    @Test fun corruptEncryptedLegacyRecordCannotBeReinitialized() {
        val key=javax.crypto.KeyGenerator.getInstance("AES").apply{init(256)}.generateKey()
        var bytes=ParentEnvelope.seal(ParentCodec.encode(ParentRecord(ByteArray(16),ByteArray(32))),key,"old".toByteArray())
        bytes[bytes.lastIndex]=(bytes.last().toInt() xor 1).toByte()
        val original=bytes.copyOf();var creates=0;var writes=0
        val store=SealedParentStore(object:ParentRecordFile {
            override fun read()=bytes
            override fun commit(value:ByteArray,authorized:()->Boolean){writes++;check(authorized());bytes=value}
        },object:ParentKeyProvider {
            override fun exists()=true
            override fun existing()=key
            override fun create():javax.crypto.SecretKey{creates++;return key}
        },"old".toByteArray())
        val d=ParentDomain(store,{100L},{},binding="old",localManagement=true)
        assertFalse(d.initializeLocal(connection));assertNull(d.childConfiguration())
        assertArrayEquals(original,bytes);assertEquals(0,creates);assertEquals(0,writes)
    }
}
