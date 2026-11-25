package com.zametki.app.data

import android.content.Context
import android.net.Uri
import android.os.Build
import android.util.Base64
import com.zametki.app.model.AppSettings
import com.zametki.app.model.NoteItem
import com.zametki.app.model.NoteOrigin
import com.zametki.app.model.ZametkaManifest
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.util.UUID
import java.util.zip.Inflater
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

@Serializable
private data class QrNotePayload(
    val p: String = "",
    val c: String = "",
    val s: String = "",
    val d: String = "",
    val t: Long = 0L,
)

class NoteRepository(private val context: Context) {
    val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        prettyPrint = true
        coerceInputValues = true
    }

    private val notesDir = File(context.filesDir, "notes").apply { mkdirs() }
    private val settingsFile = File(context.filesDir, "settings.json")
    private val validIdRegex = Regex("^[A-Za-z0-9_-]{1,64}$")
    private val ioLock = Any()

    private fun writeAtomic(target: File, content: String) {
        val tmp = File(target.parentFile, "${target.name}.tmp")
        try {
            tmp.writeText(content, Charsets.UTF_8)
            if (!tmp.renameTo(target)) {
                target.writeText(content, Charsets.UTF_8)
                tmp.delete()
            }
        } catch (e: Exception) {
            tmp.delete()
            throw e
        }
    }

    fun isValidId(id: String): Boolean = validIdRegex.matches(id)

    fun nowSec(): Double = System.currentTimeMillis() / 1000.0

    fun defaultDeviceName(): String =
        listOfNotNull(Build.MANUFACTURER, Build.MODEL)
            .joinToString(" ")
            .trim()
            .ifEmpty { "Android" }

    fun loadSettings(): AppSettings {
        return try {
            if (settingsFile.isFile) {
                json.decodeFromString<AppSettings>(settingsFile.readText(Charsets.UTF_8))
            } else {
                AppSettings(deviceName = defaultDeviceName())
            }
        } catch (_: Exception) {
            AppSettings(deviceName = defaultDeviceName())
        }
    }

    fun saveSettings(s: AppSettings) = synchronized(ioLock) {
        writeAtomic(settingsFile, json.encodeToString(s))
    }

    fun loadAllNotes(): List<NoteItem> = synchronized(ioLock) {
        val files = notesDir.listFiles { f -> f.isFile && f.name.endsWith(".json") } ?: return@synchronized emptyList()
        files.mapNotNull { f ->
            try {
                json.decodeFromString<NoteItem>(f.readText(Charsets.UTF_8))
            } catch (_: Exception) {
                null
            }
        }
    }

    fun saveNote(note: NoteItem): NoteItem = synchronized(ioLock) {
        require(isValidId(note.id)) { "Некорректный ID заметки" }
        val (title, snippet) = splitPlainParts(note.plain)
        val html = note.html.ifBlank { plainToHtml(note.plain) }
        val updated = note.copy(
            title = title,
            snippet = snippet,
            html = html,
        )
        writeAtomic(File(notesDir, "${updated.id}.json"), json.encodeToString(updated))
        updated
    }

    fun createNote(plain: String = "", origin: NoteOrigin? = null): NoteItem {
        val now = nowSec()
        val note = NoteItem(
            id = UUID.randomUUID().toString(),
            plain = plain,
            html = plainToHtml(plain),
            created = now,
            modified = now,
            origin = origin,
        )
        return saveNote(note)
    }

    fun trashNote(note: NoteItem): NoteItem {
        val now = nowSec()
        return saveNote(note.copy(deleted = true, deletedAt = now, modified = now, pinned = false))
    }

    fun restoreNote(note: NoteItem): NoteItem =
        saveNote(note.copy(deleted = false, deletedAt = 0.0, modified = nowSec()))

    fun purgeNote(noteId: String) = synchronized(ioLock) {
        if (!isValidId(noteId)) return@synchronized
        File(notesDir, "$noteId.json").delete()
    }

    fun purgeExpiredTrash(days: Int = 30): Int {
        val cutoff = nowSec() - days * 86400.0
        val expired = loadAllNotes().filter { it.deleted && it.deletedAt > 0.0 && it.deletedAt < cutoff }
        expired.forEach { purgeNote(it.id) }
        return expired.size
    }

    fun exportZametka(note: NoteItem, settings: AppSettings): File {
        val sharedDir = File(context.cacheDir, "shared").apply { mkdirs() }
        val safeName = (note.title.ifBlank { "zametka" })
            .replace(Regex("[<>:\"/\\\\|?*\\s]+"), "_")
            .take(40)
            .ifBlank { "zametka" }
        val outFile = File(sharedDir, "$safeName.zametka")
        val sender = settings.ownerName.trim()
        val device = settings.deviceName.trim().ifEmpty { defaultDeviceName() }
        val now = nowSec()
        val manifest = ZametkaManifest(
            format = 1,
            app = "zametki",
            exportedAt = now,
            origin = NoteOrigin(
                sourceType = if (sender.isNotEmpty()) "friend" else "phone",
                senderName = sender,
                deviceName = device,
                sentAt = now,
            ),
        )
        val cleanNote = note.copy(deleted = false, deletedAt = 0.0, reminderAt = 0.0)
        ZipOutputStream(FileOutputStream(outFile)).use { zos ->
            zos.putNextEntry(ZipEntry("zametka-manifest.json"))
            zos.write(json.encodeToString(manifest).toByteArray(Charsets.UTF_8))
            zos.closeEntry()
            zos.putNextEntry(ZipEntry("note.json"))
            zos.write(json.encodeToString(cleanNote).toByteArray(Charsets.UTF_8))
            zos.closeEntry()
        }
        return outFile
    }

    fun importZametkaUri(uri: Uri): NoteItem? {
        return context.contentResolver.openInputStream(uri)?.use { importZametkaStream(it) }
    }

    private fun readZipLimited(zis: ZipInputStream, maxBytes: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(16384)
        var total = 0
        while (true) {
            val n = zis.read(buf)
            if (n <= 0) break
            total += n
            if (total > maxBytes) error("Файл .zametka превышает допустимый размер")
            out.write(buf, 0, n)
        }
        return out.toByteArray()
    }

    fun importZametkaStream(input: InputStream): NoteItem? {
        var manifestText: String? = null
        var noteText: String? = null
        val maxJsonBytes = 2 * 1024 * 1024
        ZipInputStream(input).use { zis ->
            var entry = zis.nextEntry
            while (entry != null) {
                when (entry.name) {
                    "zametka-manifest.json" -> manifestText = readZipLimited(zis, maxJsonBytes).toString(Charsets.UTF_8)
                    "note.json" -> noteText = readZipLimited(zis, maxJsonBytes).toString(Charsets.UTF_8)
                }
                zis.closeEntry()
                entry = zis.nextEntry
            }
        }
        val rawNoteText = noteText ?: return null
        val rawNote = json.decodeFromString<NoteItem>(rawNoteText)
        val manifest = manifestText?.let {
            try { json.decodeFromString<ZametkaManifest>(it) } catch (_: Exception) { null }
        }
        val now = nowSec()
        val mOrigin = manifest?.origin
        val origin = NoteOrigin(
            sourceType = mOrigin?.sourceType?.ifBlank { "friend" } ?: "friend",
            senderName = mOrigin?.senderName.orEmpty(),
            deviceName = mOrigin?.deviceName.orEmpty(),
            sentAt = mOrigin?.sentAt ?: manifest?.exportedAt ?: 0.0,
            receivedAt = now,
        )
        val imported = rawNote.copy(
            id = UUID.randomUUID().toString(),
            created = now,
            modified = now,
            deleted = false,
            deletedAt = 0.0,
            origin = origin,
        )
        return saveNote(imported)
    }

    /** Импортирует офлайн QR-заметку формата zametka1:<urlsafe_base64(zlib(json))>. */
    fun importQrPayload(payload: String): NoteItem? {
        val prefix = "zametka1:"
        if (!payload.startsWith(prefix)) return null
        val b64 = payload.removePrefix(prefix).trim()
        val comp = Base64.decode(b64, Base64.URL_SAFE or Base64.NO_WRAP)
        val inflater = Inflater()
        inflater.setInput(comp)
        val out = ByteArrayOutputStream()
        val buf = ByteArray(4096)
        var total = 0
        try {
            while (!inflater.finished()) {
                val n = inflater.inflate(buf)
                if (n <= 0) break
                total += n
                if (total > 256 * 1024) error("QR data too large")
                out.write(buf, 0, n)
            }
        } finally {
            inflater.end()
        }
        val qr = json.decodeFromString<QrNotePayload>(out.toString("UTF-8"))
        if (qr.p.isBlank()) return null
        val now = nowSec()
        val origin = NoteOrigin(
            sourceType = if (qr.s.isNotBlank()) "friend" else "pc",
            senderName = qr.s,
            deviceName = qr.d.ifBlank { "ПК" },
            sentAt = if (qr.t > 0L) qr.t.toDouble() else now,
            receivedAt = now,
        )
        val created = createNote(plain = qr.p, origin = origin)
        return if (qr.c.isNotBlank()) saveNote(created.copy(color = qr.c)) else created
    }

    companion object {
        fun splitPlainParts(plain: String): Pair<String, String> {
            val lines = plain.lines().map { it.trim() }.filter { it.isNotEmpty() }
            val title = lines.firstOrNull().orEmpty()
            val snippet = lines.drop(1).joinToString(" ").take(200)
            return title to snippet
        }

        fun plainToHtml(plain: String): String {
            fun esc(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            val lines = plain.split("\n")
            if (lines.all { it.isBlank() }) return "<p></p>"
            return lines.joinToString("") { ln ->
                "<p style=\"margin-top:0px;\">${if (ln.isNotEmpty()) esc(ln) else "<br>"}</p>"
            }
        }
    }
}
