package com.zametki.app.sync

import com.zametki.app.data.NoteRepository
import com.zametki.app.model.AppSettings
import com.zametki.app.model.NoteItem
import com.zametki.app.model.NoteOrigin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import okhttp3.Credentials
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.URI
import java.net.URLDecoder
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

data class SyncResult(val pushed: Int, val pulled: Int, val message: String)

@Serializable
private data class PullResponse(
    @SerialName("device_name") val deviceName: String = "",
    @SerialName("owner_name") val ownerName: String = "",
    val notes: List<NoteItem> = emptyList(),
)

@Serializable
private data class PushRequest(
    @SerialName("device_name") val deviceName: String,
    @SerialName("sender_name") val senderName: String,
    @SerialName("device_type") val deviceType: String = "phone",
    val notes: List<NoteItem>,
)

@Serializable
private data class PushResponse(
    val ok: Boolean = false,
    val accepted: Int = 0,
)

object SyncClients {
    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val xmlMedia = "application/xml; charset=utf-8".toMediaType()

    private fun isPrivateLanHost(host: String?): Boolean {
        val h = host?.lowercase() ?: return false
        if (h == "localhost" || h == "127.0.0.1") return true
        if (h.startsWith("192.168.") || h.startsWith("10.")) return true
        if (h.startsWith("172.")) {
            val second = h.split(".").getOrNull(1)?.toIntOrNull() ?: return false
            return second in 16..31
        }
        return false
    }

    /** Вариант А: локальная Wi-Fi синхронизация с ПК (PhoneServer). */
    suspend fun syncWithPc(repo: NoteRepository, settings: AppSettings): SyncResult =
        withContext(Dispatchers.IO) {
            val rawUrl = settings.pcSyncUrl.trim()
            if (rawUrl.isEmpty()) error("Укажите адрес ПК (из Настроек ПК -> Телефон)")
            val uri = try { URI(rawUrl) } catch (_: Exception) { error("Некорректный адрес ПК") }
            val scheme = uri.scheme?.lowercase()
            if (scheme != "http" && scheme != "https" || uri.host.isNullOrBlank()) {
                error("Укажите полный адрес вида http://192.168.x.x:8787/?t=ТОКЕН")
            }
            if (scheme == "http" && !isPrivateLanHost(uri.host)) {
                error("HTTP разрешён только для локального Wi-Fi (192.168.x.x / 10.x.x.x)")
            }
            val query = uri.rawQuery.orEmpty()
            val token = query.split("&")
                .mapNotNull { kv ->
                    val p = kv.split("=", limit = 2)
                    if (p.size == 2 && p[0] == "t") URLDecoder.decode(p[1], "UTF-8") else null
                }
                .firstOrNull()
                ?.takeIf { it.isNotBlank() }
                ?: error("В адресе отсутствует ?t=ТОКЕН")

            val base = "${uri.scheme}://${uri.host}:${if (uri.port > 0) uri.port else 8787}"
            val encTok = URLEncoder.encode(token, "UTF-8")

            // 1) Pull
            val pullReq = Request.Builder().url("$base/api/sync/pull?t=$encTok").get().build()
            val pullData = client.newCall(pullReq).execute().use { resp ->
                if (!resp.isSuccessful) error("ПК ответил кодом ${resp.code}")
                repo.json.decodeFromString<PullResponse>(resp.body.string())
            }

            val localById = repo.loadAllNotes().associateBy { it.id }.toMutableMap()
            var pulled = 0
            val now = repo.nowSec()
            for (remote in pullData.notes) {
                if (!repo.isValidId(remote.id)) continue
                val local = localById[remote.id]
                if (local == null || remote.modified > local.modified + 0.5) {
                    val orig = remote.origin ?: NoteOrigin(
                        sourceType = "pc",
                        senderName = pullData.ownerName,
                        deviceName = pullData.deviceName.ifBlank { "ПК" },
                        sentAt = remote.modified,
                        receivedAt = now,
                    )
                    val saved = repo.saveNote(remote.copy(origin = orig))
                    localById[saved.id] = saved
                    pulled++
                }
            }

            // 2) Push
            val remoteModById = pullData.notes.associate { it.id to it.modified }
            val toPush = localById.values.filter { n ->
                val rMod = remoteModById[n.id] ?: -1.0
                n.modified > rMod + 0.5
            }
            var pushed = 0
            if (toPush.isNotEmpty()) {
                val body = repo.json.encodeToString(
                    PushRequest(
                        deviceName = settings.deviceName.ifBlank { repo.defaultDeviceName() },
                        senderName = settings.ownerName.trim(),
                        notes = toPush,
                    )
                )
                val pushReq = Request.Builder()
                    .url("$base/api/sync/push?t=$encTok")
                    .post(body.toRequestBody(jsonMedia))
                    .build()
                client.newCall(pushReq).execute().use { resp ->
                    if (!resp.isSuccessful) error("Ошибка отправки на ПК: ${resp.code}")
                    val pr = repo.json.decodeFromString<PushResponse>(resp.body.string())
                    pushed = pr.accepted
                }
            }
            SyncResult(pushed, pulled, "Wi-Fi синхронизация: получено $pulled, отправлено $pushed")
        }

    /** Вариант Б: интернет-синхронизация по WebDAV (Яндекс Диск / Nextcloud). */
    suspend fun syncWithWebDav(repo: NoteRepository, settings: AppSettings): SyncResult =
        withContext(Dispatchers.IO) {
            val base = settings.webdavUrl.trim().trimEnd('/')
            if (base.isEmpty()) error("Укажите адрес WebDAV в настройках")
            if (!base.startsWith("https://", ignoreCase = true)) {
                error("Для интернет-синхронизации WebDAV требуется защищённый адрес https://")
            }
            val auth = Credentials.basic(settings.webdavUser.trim(), settings.webdavPass)

            fun mkcol(url: String) {
                val req = Request.Builder().url(url).header("Authorization", auth)
                    .method("MKCOL", ByteArray(0).toRequestBody(null)).build()
                client.newCall(req).execute().use { /* 201 / 405 ok */ }
            }

            mkcol("$base/")
            mkcol("$base/notes/")

            val propBody = """<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:getlastmodified/></d:prop></d:propfind>"""
            val propReq = Request.Builder()
                .url("$base/notes/")
                .header("Authorization", auth)
                .header("Depth", "1")
                .method("PROPFIND", propBody.toRequestBody(xmlMedia))
                .build()
            val xml = client.newCall(propReq).execute().use { resp ->
                if (!resp.isSuccessful && resp.code != 207) error("WebDAV PROPFIND: ${resp.code}")
                resp.body.string()
            }

            val remoteFiles = Regex("<[^>]*href[^>]*>([^<]+)</[^>]*href>", RegexOption.IGNORE_CASE)
                .findAll(xml)
                .map { URLDecoder.decode(it.groupValues[1].trim().trimEnd('/'), "UTF-8").substringAfterLast('/') }
                .filter { it.endsWith(".json") }
                .toSet()

            val localMap = repo.loadAllNotes().associateBy { it.id }
            val allIds = localMap.keys + remoteFiles.map { it.removeSuffix(".json") }
            val myDevice = settings.deviceName.ifBlank { repo.defaultDeviceName() }
            val mySender = settings.ownerName.trim()
            var pushed = 0
            var pulled = 0
            val now = repo.nowSec()

            for (nid in allIds) {
                if (!repo.isValidId(nid)) continue
                val fname = "$nid.json"
                val local = localMap[nid]
                var remote: NoteItem? = null
                var getFailed = false
                if (fname in remoteFiles) {
                    val getReq = Request.Builder().url("$base/notes/$fname").header("Authorization", auth).get().build()
                    client.newCall(getReq).execute().use { resp ->
                        if (resp.isSuccessful) {
                            remote = try {
                                repo.json.decodeFromString<NoteItem>(resp.body.string())
                            } catch (_: Exception) {
                                getFailed = true
                                null
                            }
                        } else {
                            getFailed = true
                        }
                    }
                }
                if (getFailed) continue
                val r = remote
                val lMod = local?.modified ?: 0.0
                val rMod = r?.modified ?: 0.0
                if (r != null && (local == null || rMod > lMod + 0.5)) {
                    val orig = if (r.origin == null && r.lastDevice.isNotBlank() && r.lastDevice != myDevice) {
                        NoteOrigin(
                            sourceType = r.lastDeviceType.ifBlank { "pc" },
                            senderName = r.lastSender,
                            deviceName = r.lastDevice,
                            sentAt = rMod,
                            receivedAt = now,
                        )
                    } else r.origin
                    repo.saveNote(r.copy(id = nid, origin = orig))
                    pulled++
                } else if (local != null && (r == null || lMod > rMod + 0.5)) {
                    val payload = local.copy(
                        lastDevice = myDevice,
                        lastDeviceType = "phone",
                        lastSender = mySender,
                    )
                    val putReq = Request.Builder()
                        .url("$base/notes/$fname")
                        .header("Authorization", auth)
                        .put(repo.json.encodeToString(payload).toRequestBody(jsonMedia))
                        .build()
                    client.newCall(putReq).execute().use { resp ->
                        if (resp.isSuccessful) pushed++
                    }
                }
            }
            SyncResult(pushed, pulled, "WebDAV: получено $pulled, отправлено $pushed")
        }
}
