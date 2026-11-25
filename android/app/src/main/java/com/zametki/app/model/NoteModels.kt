package com.zametki.app.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class NoteOrigin(
    @SerialName("source_type") val sourceType: String = "pc",
    @SerialName("sender_name") val senderName: String = "",
    @SerialName("device_name") val deviceName: String = "",
    @SerialName("sent_at") val sentAt: Double = 0.0,
    @SerialName("received_at") val receivedAt: Double = 0.0,
)

@Serializable
data class NoteItem(
    val id: String,
    val folder: String = "notes",
    val title: String = "",
    val html: String = "",
    val plain: String = "",
    val snippet: String = "",
    val created: Double = 0.0,
    val modified: Double = 0.0,
    val deleted: Boolean = false,
    @SerialName("deleted_at") val deletedAt: Double = 0.0,
    val pinned: Boolean = false,
    val color: String = "",
    @SerialName("reminder_at") val reminderAt: Double = 0.0,
    @SerialName("title_size") val titleSize: Double = 0.0,
    val origin: NoteOrigin? = null,
    @SerialName("last_device") val lastDevice: String = "",
    @SerialName("last_device_type") val lastDeviceType: String = "",
    @SerialName("last_sender") val lastSender: String = "",
)

@Serializable
data class ZametkaManifest(
    val format: Int = 1,
    val app: String = "zametki",
    @SerialName("exported_at") val exportedAt: Double = 0.0,
    val origin: NoteOrigin? = null,
)

@Serializable
data class AppSettings(
    val lang: String = "ru",
    val theme: String = "system",
    val ownerName: String = "",
    val deviceName: String = "",
    val pcSyncUrl: String = "",
    val webdavUrl: String = "",
    val webdavUser: String = "",
    val webdavPass: String = "",
    val autoPurgeTrash: Boolean = true,
)
