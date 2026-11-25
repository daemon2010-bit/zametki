package com.zametki.app

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import com.zametki.app.data.NoteRepository
import com.zametki.app.model.NoteOrigin
import com.zametki.app.ui.ZametkiApp

class MainActivity : ComponentActivity() {
    private lateinit var repo: NoteRepository
    private val incomingNoteId = mutableStateOf<String?>(null)
    private val incomingImageUri = mutableStateOf<Uri?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        repo = NoteRepository(applicationContext)
        if (savedInstanceState == null) {
            handleIncomingIntent(intent)
        }
        setContent {
            ZametkiApp(
                repo = repo,
                incomingNoteId = incomingNoteId.value,
                onIncomingConsumed = { incomingNoteId.value = null },
                incomingImageUri = incomingImageUri.value,
                onIncomingImageConsumed = { incomingImageUri.value = null },
            )
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleIncomingIntent(intent: Intent?) {
        if (intent == null) return
        val action = intent.action ?: return
        if (action == Intent.ACTION_VIEW) {
            val uri = intent.data ?: return
            val note = try { repo.importZametkaUri(uri) } catch (_: Exception) { null }
            if (note != null) {
                incomingNoteId.value = note.id
                intent.action = null
            }
        } else if (action == Intent.ACTION_SEND) {
            val streamUri: Uri? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(Intent.EXTRA_STREAM)
            }
            if (streamUri != null) {
                if (intent.type?.startsWith("image/") == true) {
                    incomingImageUri.value = streamUri
                    intent.action = null
                    return
                }
                val note = try { repo.importZametkaUri(streamUri) } catch (_: Exception) { null }
                if (note != null) {
                    incomingNoteId.value = note.id
                    intent.action = null
                    return
                }
            }
            val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()
            if (!sharedText.isNullOrEmpty()) {
                val note = repo.createNote(
                    plain = sharedText,
                    origin = NoteOrigin(
                        sourceType = "friend",
                        senderName = "Поделились",
                        deviceName = "Android",
                        receivedAt = repo.nowSec(),
                    ),
                )
                incomingNoteId.value = note.id
                intent.action = null
            }
        }
    }
}
