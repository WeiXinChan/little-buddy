package com.littlebuddy.v2.transport

import com.littlebuddy.v2.parent.PinDiagnostic
import java.net.Proxy
import java.net.Socket
import java.net.SocketAddress

/** Logical endpoint remains pinned; only the owned local SSH listener port is mapped. */
internal class V2MappedSocket(private val port: () -> Int) : Socket(Proxy.NO_PROXY) {
    override fun setSoTimeout(timeout: Int) {
        PinDiagnostic.event(PinDiagnostic.Stage.SOCKET_OPTIONS, PinDiagnostic.Reason.BEGIN)
        try { super.setSoTimeout(timeout) }
        catch (error: Exception) { PinDiagnostic.runtimeError(PinDiagnostic.Stage.SOCKET_OPTIONS,error); throw error }
        PinDiagnostic.event(PinDiagnostic.Stage.SOCKET_OPTIONS, PinDiagnostic.Reason.SUCCESS)
    }
    override fun connect(endpoint: SocketAddress, timeout: Int) {
        PinDiagnostic.event(PinDiagnostic.Stage.SOCKET_MAP, PinDiagnostic.Reason.BEGIN)
        val mapped = try { V2Forwarding.mapped(endpoint, port()) }
        catch (error: Exception) { PinDiagnostic.runtimeError(PinDiagnostic.Stage.SOCKET_MAP,error); throw error }
        PinDiagnostic.event(PinDiagnostic.Stage.SOCKET_MAP, PinDiagnostic.Reason.SUCCESS)
        PinDiagnostic.event(PinDiagnostic.Stage.SOCKET_CONNECT, PinDiagnostic.Reason.BEGIN)
        try { super.connect(mapped,timeout) }
        catch (error: Exception) { PinDiagnostic.runtimeError(PinDiagnostic.Stage.SOCKET_CONNECT,error); throw error }
        PinDiagnostic.event(PinDiagnostic.Stage.SOCKET_CONNECT, PinDiagnostic.Reason.SUCCESS)
    }
}
