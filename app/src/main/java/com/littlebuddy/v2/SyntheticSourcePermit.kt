package com.littlebuddy.v2

/** No arbitrary AudioRecord integer and no Intent/provisioning surface. */
internal enum class CaptureInput(val value:Int) { COMMUNICATION(7), RECOGNITION(6) }
internal data class SyntheticSourceEnvironment(val enabled:Boolean,val hardware:String,val api:Int,val product:String,val abi:String)
internal data class SyntheticSourcePermit(val source:CaptureInput,val nonce:String,val sha:String,
    val generation:Long,val issuedMs:Long,val windowMs:Long=8000,val sampleLimit:Int=128000) {
    fun valid(environment:SyntheticSourceEnvironment,nowMs:Long,ticket:Long):Boolean =
        environment.enabled && environment.hardware in setOf("ranchu","goldfish") &&
        environment.api==36 && environment.product=="sdk_gphone64_x86_64" && environment.abi=="x86_64" &&
        nonce.matches(Regex("[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}")) && sha==ENTER_SHA &&
        ticket==generation && nowMs>=issuedMs && nowMs-issuedMs<windowMs && windowMs==8000L && sampleLimit==128000
    companion object { const val ENTER_SHA="c53eb146203afc87fd8092f60721e49a20d30baaa0811da715788a40fe582e34" }
}
