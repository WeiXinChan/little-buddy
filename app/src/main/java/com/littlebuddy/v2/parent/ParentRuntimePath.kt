package com.littlebuddy.v2.parent

/** Android adapter is the sole production provider; tests replace platform IO, not business classes. */
internal interface ParentRuntimePlatform {
    fun legacyAliasPresent():Boolean = legacyBinding()!=null
    fun isolatedMarker():ByteArray? = null
    fun isolatedExists():Boolean = false
    fun isolatedDomain():ParentDomain = error("isolated runtime unavailable")
    fun publishIsolatedMarker() { error("isolated runtime unavailable") }
    fun requireWorker()
    fun existingStore():Boolean
    fun legacyBinding():String?
    fun marker():ByteArray?
    fun createMarker()
    fun domain(binding:String):ParentDomain
    fun preset():ParentConnection?
}
internal enum class ConfigurationStatus { READY, LOAD_FAILED, MIGRATION_FAILED, CHILD_MISSING, NO_CONNECTION }
internal data class ConfigurationResult(val configuration:ParentChildConfiguration?,val status:ConfigurationStatus)
internal object ParentRuntimePath {
    // Worker-only initialization serialization, separate from every page/authorization monitor.
    private val recoveryInitialization=Any()
    private fun local(p:ParentRuntimePlatform):ParentDomain {
        val D=ConfigurationDiagnostic
        D.step(ConfigurationDiagnostic.Stage.WORKER){p.requireWorker()}
        val isolatedMarker=D.step(ConfigurationDiagnostic.Stage.ISOLATED_MARKER){p.isolatedMarker()}
        val isolatedExists=D.step(ConfigurationDiagnostic.Stage.ISOLATED_PRESENCE){p.isolatedExists()}
        if(isolatedMarker!=null || isolatedExists) {
            D.step(ConfigurationDiagnostic.Stage.ISOLATED_MARKER) {
                check(isolatedMarker==null || isolatedMarker.contentEquals(byteArrayOf(1)))
                check(isolatedMarker==null || isolatedExists)
            }
            return isolated(p)
        }
        val existing=D.step(ConfigurationDiagnostic.Stage.STORE_PRESENCE){p.existingStore()}
        D.event(ConfigurationDiagnostic.Stage.STORE_PRESENCE,if(existing) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
        val alias=D.step(ConfigurationDiagnostic.Stage.LEGACY_ALIAS){p.legacyAliasPresent()}
        D.event(ConfigurationDiagnostic.Stage.LEGACY_ALIAS,if(alias) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
        val certificate=D.step(ConfigurationDiagnostic.Stage.LEGACY_CERT){p.legacyBinding()}
        D.event(ConfigurationDiagnostic.Stage.LEGACY_CERT,if(certificate!=null) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
        val marker=D.step(ConfigurationDiagnostic.Stage.MARKER_READ){p.marker()}
        D.event(ConfigurationDiagnostic.Stage.MARKER_READ,if(marker!=null) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
        if(existing && !alias && certificate==null && marker==null) return isolated(p)
        val binding=D.step(ConfigurationDiagnostic.Stage.BINDING){LocalManagementBinding.resolve(existing,certificate,marker)}
        if(!existing && binding==LocalManagementBinding.LOCAL)
            D.step(ConfigurationDiagnostic.Stage.MARKER_WRITE){p.createMarker()}
        val domain=D.step(ConfigurationDiagnostic.Stage.DOMAIN_OPEN){p.domain(binding)}
        val preset=D.step(ConfigurationDiagnostic.Stage.PRESET){p.preset()}
        D.event(ConfigurationDiagnostic.Stage.PRESET,if(preset!=null) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
        val initialized=D.step(ConfigurationDiagnostic.Stage.MIGRATION){domain.initializeLocal(preset)}
        if(!initialized){D.event(ConfigurationDiagnostic.Stage.MIGRATION,ConfigurationDiagnostic.Reason.REJECTED)
            throw ConfigurationFailure(ConfigurationDiagnostic.Stage.MIGRATION,ConfigurationDiagnostic.Reason.REJECTED)}
        return domain
    }
    /** Only recovery of the missing legacy AAD. Old bytes and identities are never touched. */
    private fun isolated(p:ParentRuntimePlatform):ParentDomain = synchronized(recoveryInitialization) {
        val D=ConfigurationDiagnostic
        // Re-read after acquiring the initializer: another worker may have committed selection.
        val marker=D.step(ConfigurationDiagnostic.Stage.ISOLATED_MARKER){p.isolatedMarker()}
        val existing=D.step(ConfigurationDiagnostic.Stage.ISOLATED_PRESENCE){p.isolatedExists()}
        D.step(ConfigurationDiagnostic.Stage.ISOLATED_MARKER) {
            check(marker==null || marker.contentEquals(byteArrayOf(1)))
            check(marker==null || existing)
        }
        val preset=D.step(ConfigurationDiagnostic.Stage.PRESET){p.preset()}
        if(!existing)D.step(ConfigurationDiagnostic.Stage.PRESET){check(preset!=null)}
        val d=D.step(ConfigurationDiagnostic.Stage.ISOLATED_OPEN){p.isolatedDomain()}
        val ok=D.step(ConfigurationDiagnostic.Stage.MIGRATION){d.initializeLocal(preset)}
        if(!ok)throw ConfigurationFailure(ConfigurationDiagnostic.Stage.MIGRATION,ConfigurationDiagnostic.Reason.REJECTED)
        val ready=D.step(ConfigurationDiagnostic.Stage.CHILD_READ){d.childConfiguration()}
        D.step(ConfigurationDiagnostic.Stage.CHILD_READ){check(ready?.connection!=null)}
        if(marker==null)D.step(ConfigurationDiagnostic.Stage.ISOLATED_COMMIT_MARKER){p.publishIsolatedMarker()}
        D.event(ConfigurationDiagnostic.Stage.ISOLATED_OPEN,ConfigurationDiagnostic.Reason.LEGACY_UNREADABLE_ISOLATED)
        d
    }
    fun load(p:ParentRuntimePlatform):ParentDomain=ConfigurationDiagnostic.attempt{local(p)}
    fun configuration(p:ParentRuntimePlatform):ConfigurationResult=ConfigurationDiagnostic.attempt {
        try {
            val domain=local(p)
            val c=ConfigurationDiagnostic.step(ConfigurationDiagnostic.Stage.CHILD_READ){domain.childConfiguration()}
            val status=when {c==null->ConfigurationStatus.CHILD_MISSING;c.connection==null->ConfigurationStatus.NO_CONNECTION;else->ConfigurationStatus.READY}
            ConfigurationDiagnostic.event(ConfigurationDiagnostic.Stage.CHILD_READ,when(status){
                ConfigurationStatus.CHILD_MISSING->ConfigurationDiagnostic.Reason.EMPTY
                ConfigurationStatus.NO_CONNECTION->ConfigurationDiagnostic.Reason.NO_CONNECTION
                else->ConfigurationDiagnostic.Reason.SUCCESS})
            ConfigurationResult(c,status)
        }catch(e:ConfigurationFailure){ConfigurationResult(null,if(e.stage==ConfigurationDiagnostic.Stage.MIGRATION)
            ConfigurationStatus.MIGRATION_FAILED else ConfigurationStatus.LOAD_FAILED)}
    }
}
