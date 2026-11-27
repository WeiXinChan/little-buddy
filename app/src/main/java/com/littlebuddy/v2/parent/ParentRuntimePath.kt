package com.littlebuddy.v2.parent

/** Android adapter is the sole production provider; tests replace platform IO, not business classes. */
internal interface ParentRuntimePlatform {
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
    private fun local(p:ParentRuntimePlatform):ParentDomain {
        val D=ConfigurationDiagnostic
        D.step(ConfigurationDiagnostic.Stage.WORKER){p.requireWorker()}
        val existing=D.step(ConfigurationDiagnostic.Stage.STORE_PRESENCE){p.existingStore()}
        D.event(ConfigurationDiagnostic.Stage.STORE_PRESENCE,if(existing) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
        val certificate=D.step(ConfigurationDiagnostic.Stage.LEGACY_CERT){p.legacyBinding()}
        D.event(ConfigurationDiagnostic.Stage.LEGACY_CERT,if(certificate!=null) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
        val marker=D.step(ConfigurationDiagnostic.Stage.MARKER_READ){p.marker()}
        D.event(ConfigurationDiagnostic.Stage.MARKER_READ,if(marker!=null) ConfigurationDiagnostic.Reason.PRESENT else ConfigurationDiagnostic.Reason.ABSENT)
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
