package com.littlebuddy.v2.parent

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.widget.Toast
import java.util.concurrent.Executors

/** Activity-owned public-only export. No Grant/PIN/token/key handle crosses this boundary. */
internal class AndroidPublicKeyFile(private val activity: Activity) {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor { Thread(it, "v2-public-key-file") }
    private class Operation(val file: PublicKeyFile) { var writing = false; var picker = false }
    private var current: Operation? = null // main thread only; worker captures the specific operation
    private var destroyed = false
    private var cleanupUnconfirmed = false
    private val timeout = Runnable {
        current?.let { op ->
            op.file.cancel()
            if (!op.writing && !op.picker) current = null
            message("公钥未保存：操作已到期，请重新验证后重试。")
        }
    }
    fun begin(authorize: ((String) -> Unit, () -> Unit) -> Unit) {
        if (destroyed) return
        if (cleanupUnconfirmed) { message("上次公钥文件清理未确认，请先检查下载目录。"); return }
        if (current != null) { message("正在保存或取消公钥文件，请稍候。"); return }
        val op = Operation(PublicKeyFile(SystemClock::elapsedRealtime)); current = op
        main.postDelayed(timeout, 120_000)
        try {
            authorize({ publicKey ->
                if (current !== op || destroyed) return@authorize
                val accepted = runCatching { op.file.release(publicKey) }.getOrDefault(false)
                if (!accepted) { finish(op, PublicKeyFile.Result.FAILED); return@authorize }
                if (Build.VERSION.SDK_INT >= 29) write(op, null)
                else {
                    op.picker = true
                    try {
                        activity.startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                            addCategory(Intent.CATEGORY_OPENABLE); type = "application/octet-stream"
                            putExtra(Intent.EXTRA_TITLE, PublicKeyFile.NAME)
                            putExtra(Intent.EXTRA_LOCAL_ONLY, true)
                        }, REQUEST)
                    } catch (_: Exception) { op.picker = false; finish(op, PublicKeyFile.Result.FAILED) }
                }
            }, { finish(op, PublicKeyFile.Result.FAILED) })
        } catch (_: Exception) { finish(op, PublicKeyFile.Result.FAILED) }
    }
    /** Picker focus loss revokes the parent normally. Only its already-released public payload
     * survives the picker; no parent authority is retained or restored on return. */
    fun focusLost() {
        val op = current ?: return
        if (op.picker) return
        op.file.cancel()
        if (!op.writing) { current = null; main.removeCallbacks(timeout) }
    }
    fun cancel() {
        current?.let { op ->
            op.file.cancel()
            if (!op.writing && !op.picker) current = null
        }
        main.removeCallbacks(timeout)
    }
    fun close() { destroyed = true; cancel(); io.shutdown() }
    fun result(code: Int, result: Int, data: Intent?): Boolean {
        if (code != REQUEST) return false
        val op = current?.takeIf { it.picker }
        op?.picker = false
        val uri = if (result == Activity.RESULT_OK) data?.data else null
        if (uri == null) { op?.let { finish(it, PublicKeyFile.Result.CANCELLED) }; return true }
        // Only our CREATE_DOCUMENT result, never arbitrary inbound URL/path or persisted permission.
        if (uri.scheme != "content" || !DocumentsContract.isDocumentUri(activity, uri)) {
            op?.let { finish(it, PublicKeyFile.Result.FAILED) }; return true
        }
        if (op == null || destroyed || !op.file.allowed()) {
            io.execute { val clean = runCatching { deleteEmptyDocument(uri) }.isSuccess
                main.post {
                    if (op != null) finish(op, if (clean) PublicKeyFile.Result.CANCELLED else PublicKeyFile.Result.CLEANUP_FAILED)
                    else if (!clean) { cleanupUnconfirmed = true; message("公钥文件清理未确认，请检查所选位置。") }
                } }
        } else write(op, uri)
        return true
    }
    private fun write(op: Operation, document: Uri?) {
        op.writing = true
        io.execute {
            var usedDocument = false
            var actualName = PublicKeyFile.NAME
            var outcome = op.file.save {
                if (document != null) { usedDocument = true; documentDestination(document) }
                else downloadsDestination { actualName = it }
            }
            // CREATE_DOCUMENT has already created a file even if cancellation won before save().
            if (document != null && !usedDocument) {
                if (runCatching { deleteEmptyDocument(document) }.isFailure) outcome = PublicKeyFile.Result.CLEANUP_FAILED
            }
            main.post { finish(op, outcome, if (document == null) "Download/$actualName" else "所选位置的公钥文件") }
        }
    }
    private fun finish(op: Operation, result: PublicKeyFile.Result, location: String = "") {
        op.file.cancel()
        if (current !== op) return
        current = null; main.removeCallbacks(timeout)
        if (result == PublicKeyFile.Result.CLEANUP_FAILED) cleanupUnconfirmed = true
        if (destroyed) return
        message(when (result) {
            PublicKeyFile.Result.SAVED -> "已保存V2公钥：$location。可用USB复制到Mac；仍须管理员登记。"
            PublicKeyFile.Result.CANCELLED -> "已取消保存公钥。"
            PublicKeyFile.Result.FAILED -> "公钥保存失败，请重新验证后重试。"
            PublicKeyFile.Result.CLEANUP_FAILED -> "公钥保存未完成，清理未确认；请检查下载目录，不要使用未完成文件。"
        })
    }
    private fun message(text: String) {
        if (!destroyed && !activity.isFinishing && activity.hasWindowFocus()) Toast.makeText(activity, text, Toast.LENGTH_LONG).show()
    }
    @android.annotation.TargetApi(29)
    private fun downloadsDestination(name: (String) -> Unit): PublicKeyFile.Destination {
        val resolver = activity.contentResolver
        val uri = checkNotNull(resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, PublicKeyFile.NAME)
            put(MediaStore.MediaColumns.MIME_TYPE, "application/octet-stream")
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }))
        // From this point the handle always reaches the core's failure/cancel cleanup.
        return object : PublicKeyFile.Destination {
            override fun write(bytes: ByteArray) {
                resolver.openOutputStream(uri, "w")?.use { it.write(bytes); it.flush() } ?: error("public output unavailable")
                verifyBytes(uri, bytes)
            }
            override fun publish() {
                val actual = resolver.query(uri, arrayOf(MediaStore.MediaColumns.DISPLAY_NAME), null, null, null)?.use {
                    if (it.moveToFirst()) it.getString(0) else null
                } ?: error("public name unavailable")
                check(actual.startsWith("wali-v2-device") && actual.endsWith(".pub") &&
                    actual.length <= 128 && actual.none { it == '/' || it == '\n' || it == '\r' })
                name(actual)
                check(resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null) == 1)
            }
            override fun delete() { check(resolver.delete(uri, null, null) == 1) }
        }
    }
    private fun documentDestination(uri: Uri) = object : PublicKeyFile.Destination {
        private var emptyConfirmed = false
        override fun write(bytes: ByteArray) {
            // ACTION_CREATE_DOCUMENT supplies a new document. Refuse any nonempty pre-existing body.
            activity.contentResolver.openFileDescriptor(uri, "rw")?.use { fd ->
                check(fd.statSize == 0L)
                emptyConfirmed = true
                android.os.ParcelFileDescriptor.AutoCloseOutputStream(fd).use { it.write(bytes); it.flush() }
            } ?: error("public document unavailable")
            verifyBytes(uri, bytes)
        }
        override fun publish() = Unit
        override fun delete() {
            if (emptyConfirmed) deleteDocument(uri) else deleteEmptyDocument(uri)
        }
    }
    private fun verifyBytes(uri: Uri, expected: ByteArray) {
        val data = ByteArray(expected.size + 1)
        try {
            val size = checkNotNull(activity.contentResolver.openInputStream(uri)).use { input ->
                var count = 0
                while (count < data.size) {
                    val n = input.read(data, count, data.size - count)
                    if (n < 0) break
                    check(n > 0); count += n
                }
                count
            }
            check(size == expected.size && expected.indices.all { data[it] == expected[it] })
        } finally { data.fill(0) }
    }
    private fun deleteEmptyDocument(uri: Uri) {
        activity.contentResolver.openFileDescriptor(uri, "r")?.use { check(it.statSize == 0L) }
            ?: error("public cleanup unconfirmed")
        deleteDocument(uri)
    }
    private fun deleteDocument(uri: Uri) { check(DocumentsContract.deleteDocument(activity.contentResolver, uri)) }
    companion object { private const val REQUEST = 0x5632 }
}
