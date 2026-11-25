package com.littlebuddy.v2

/** Capability declarations authorize no identity or configuration. Exact supported release only. */
internal object ReleaseCompatibility {
    const val CONTRACT="v2-voice2-safety1-images1-management1-end1"
    fun accepts(wire: Int, contract: String?, management: Int, session: String, turn: Long,
                epoch: Long, revision: Long, state: String): Boolean =
        wire==2 && contract==CONTRACT && management==1 && session.matches(Regex("[a-f0-9]{32}")) &&
            turn>=0 && epoch>=0 && revision>=0 && state in setOf("active","waiting_wake")
}
