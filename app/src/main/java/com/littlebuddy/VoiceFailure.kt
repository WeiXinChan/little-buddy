package com.littlebuddy

internal enum class VoiceFailure(val closeCode: Int) {
    EMPTY_TRANSCRIPT(4401),
    GREETING_MISMATCH(4402),
    PROTOCOL_ERROR(1008),
    PROVIDER_ERROR(1011),
    TIMEOUT(1013),
    USER_STOPPED(4403),
    CONNECTION_ERROR(0);

    val message: String
        get() = when (this) {
            EMPTY_TRANSCRIPT -> "没听清，请再说一次"
            GREETING_MISMATCH -> "可以试着说「你好，瓦力」"
            PROTOCOL_ERROR -> "语音传输中断，请再试一次"
            PROVIDER_ERROR -> "语音服务暂时不可用，请再试一次"
            TIMEOUT -> "语音回复超时，请再试一次"
            USER_STOPPED -> "点按开始说话"
            CONNECTION_ERROR -> "连接失败，请检查私有地址和设备令牌"
        }

    companion object {
        fun fromClose(code: Int) = entries.firstOrNull { it.closeCode == code } ?: CONNECTION_ERROR
    }
}
