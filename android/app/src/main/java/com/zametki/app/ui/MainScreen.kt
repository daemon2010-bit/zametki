package com.zametki.app.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.zametki.app.PortraitCaptureActivity
import com.zametki.app.data.NoteRepository
import com.zametki.app.model.AppSettings
import com.zametki.app.model.NoteItem
import com.zametki.app.model.NoteOrigin
import com.zametki.app.sync.QrImageDecoder
import com.zametki.app.sync.SyncClients
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val NOTE_COLORS = listOf(
    "" to "Без цвета",
    "#FFD60A" to "Жёлтый",
    "#FF9F0A" to "Оранжевый",
    "#FF453A" to "Красный",
    "#32D74B" to "Зелёный",
    "#0A84FF" to "Синий",
    "#BF5AF2" to "Фиолетовый",
)

private fun parseColor(hex: String): Color? = try {
    if (hex.isBlank()) null else Color(android.graphics.Color.parseColor(hex))
} catch (_: Exception) { null }

private fun formatDate(tsSec: Double): String {
    if (tsSec <= 0.0) return ""
    return SimpleDateFormat("dd.MM.yy HH:mm", Locale.getDefault()).format(Date((tsSec * 1000).toLong()))
}

private fun formatOrigin(origin: NoteOrigin): String {
    val dt = formatDate(if (origin.receivedAt > 0.0) origin.receivedAt else origin.sentAt)
    val who = when {
        origin.sourceType == "friend" && origin.senderName.isNotBlank() ->
            "От: ${origin.senderName}" + if (origin.deviceName.isNotBlank()) " (${origin.deviceName})" else ""
        origin.sourceType == "phone" ->
            "С телефона: ${origin.deviceName.ifBlank { "Android" }}" + if (origin.senderName.isNotBlank()) " (${origin.senderName})" else ""
        else ->
            "С ПК: ${origin.deviceName.ifBlank { "ПК" }}" + if (origin.senderName.isNotBlank()) " (${origin.senderName})" else ""
    }
    return if (dt.isNotBlank()) "$who · $dt" else who
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ZametkiApp(
    repo: NoteRepository,
    incomingNoteId: String?,
    onIncomingConsumed: () -> Unit,
    incomingImageUri: Uri? = null,
    onIncomingImageConsumed: () -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var settings by remember { mutableStateOf(repo.loadSettings()) }
    var notes by remember { mutableStateOf(repo.loadAllNotes()) }
    var showTrash by rememberSaveable { mutableStateOf(false) }
    var search by rememberSaveable { mutableStateOf("") }
    var colorFilter by rememberSaveable { mutableStateOf("") }
    var openNoteId by rememberSaveable { mutableStateOf<String?>(null) }
    var showSettings by rememberSaveable { mutableStateOf(false) }
    var pendingPurge by remember { mutableStateOf<NoteItem?>(null) }
    var statusMsg by remember { mutableStateOf<String?>(null) }
    var syncing by remember { mutableStateOf(false) }
    var showQrMenu by remember { mutableStateOf(false) }
    val s = remember(settings.lang) { AppStrings.of(settings.lang) }

    fun reload() {
        notes = repo.loadAllNotes()
    }

    fun handleQrContent(raw: String) {
        when {
            raw.startsWith("zametka1:") -> {
                try {
                    val imported = repo.importQrPayload(raw)
                    if (imported != null) {
                        reload()
                        showTrash = false
                        openNoteId = imported.id
                        statusMsg = s.noteAddedMsg
                    }
                } catch (e: Exception) {
                    statusMsg = "QR: ${e.message}"
                }
            }
            (raw.startsWith("http://") || raw.startsWith("https://")) && raw.contains("t=") -> {
                val updated = settings.copy(pcSyncUrl = raw)
                settings = updated
                repo.saveSettings(updated)
                scope.launch {
                    syncing = true
                    try {
                        statusMsg = SyncClients.syncWithPc(repo, updated).message
                        reload()
                    } catch (e: Exception) {
                        statusMsg = "Wi-Fi: ${e.message}"
                    } finally {
                        syncing = false
                    }
                }
            }
            else -> {
                val created = repo.createNote(
                    plain = raw,
                    origin = NoteOrigin(sourceType = "pc", deviceName = "QR", receivedAt = repo.nowSec()),
                )
                reload()
                showTrash = false
                openNoteId = created.id
            }
        }
    }

    fun scanQrImage(uri: Uri) {
        scope.launch {
            val decoded = try {
                withContext(Dispatchers.IO) { QrImageDecoder.decodeFromUri(context, uri) }
            } catch (_: Exception) {
                null
            }
            if (!decoded.isNullOrBlank()) {
                handleQrContent(decoded)
            } else {
                statusMsg = s.qrNotFound
            }
        }
    }

    val qrLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        val raw = result.contents?.trim() ?: return@rememberLauncherForActivityResult
        handleQrContent(raw)
    }

    val qrImageLauncher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) scanQrImage(uri)
    }

    fun launchQrScan() {
        val opts = ScanOptions().apply {
            setCaptureActivity(PortraitCaptureActivity::class.java)
            setDesiredBarcodeFormats(ScanOptions.QR_CODE)
            setPrompt(s.qrPrompt)
            setBeepEnabled(false)
            setOrientationLocked(true)
        }
        qrLauncher.launch(opts)
    }

    LaunchedEffect(Unit) {
        if (settings.autoPurgeTrash && repo.purgeExpiredTrash(30) > 0) reload()
    }

    LaunchedEffect(incomingNoteId) {
        if (incomingNoteId != null) {
            reload()
            showTrash = false
            openNoteId = incomingNoteId
            statusMsg = s.noteAddedMsg
            onIncomingConsumed()
        }
    }

    LaunchedEffect(incomingImageUri) {
        if (incomingImageUri != null) {
            val uri = incomingImageUri
            onIncomingImageConsumed()
            scanQrImage(uri)
        }
    }

    ZametkiTheme(settings.theme) {
        val snackbarHostState = remember { SnackbarHostState() }
        LaunchedEffect(statusMsg) {
            statusMsg?.let {
                snackbarHostState.showSnackbar(it)
                statusMsg = null
            }
        }

        val currentNote = notes.firstOrNull { it.id == openNoteId }

        if (currentNote != null) {
            NoteEditorScreen(
                note = currentNote,
                s = s,
                snackbarHostState = snackbarHostState,
                onBack = {
                    reload()
                    openNoteId = null
                },
                onSave = { updated ->
                    val saved = repo.saveNote(updated.copy(modified = repo.nowSec()))
                    notes = notes.map { if (it.id == saved.id) saved else it }
                },
                onShare = { note ->
                    try {
                        val file = repo.exportZametka(note, settings)
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
                        val sendIntent = Intent(Intent.ACTION_SEND).apply {
                            type = "application/octet-stream"
                            putExtra(Intent.EXTRA_STREAM, uri)
                            putExtra(Intent.EXTRA_SUBJECT, note.title.ifBlank { "Заметка" })
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }
                        context.startActivity(Intent.createChooser(sendIntent, "Поделиться заметкой (.zametka)"))
                    } catch (e: Exception) {
                        statusMsg = "Ошибка отправки: ${e.message}"
                    }
                },
                onTrashToggle = { note ->
                    if (note.deleted) repo.restoreNote(note) else repo.trashNote(note)
                    reload()
                    openNoteId = null
                },
            )
        } else {
            val filtered = notes
                .filter { it.deleted == showTrash }
                .filter { colorFilter.isEmpty() || it.color == colorFilter }
                .filter {
                    val q = search.trim().lowercase()
                    q.isEmpty() || it.title.lowercase().contains(q) || it.plain.lowercase().contains(q)
                }
                .sortedWith(compareByDescending<NoteItem> { it.pinned }.thenByDescending { it.modified })

            Scaffold(
                snackbarHost = { SnackbarHost(snackbarHostState) },
                topBar = {
                    TopAppBar(
                        title = { Text(if (showTrash) s.trash else s.notes, fontWeight = FontWeight.SemiBold) },
                        actions = {
                            Box {
                                IconButton(onClick = { showQrMenu = true }) {
                                    Icon(Icons.Default.QrCodeScanner, contentDescription = "Сканировать QR")
                                }
                                DropdownMenu(
                                    expanded = showQrMenu,
                                    onDismissRequest = { showQrMenu = false },
                                ) {
                                    DropdownMenuItem(
                                        text = { Text(s.qrCamera) },
                                        leadingIcon = { Icon(Icons.Default.PhotoCamera, contentDescription = null) },
                                        onClick = {
                                            showQrMenu = false
                                            launchQrScan()
                                        },
                                    )
                                    DropdownMenuItem(
                                        text = { Text(s.qrFromPhoto) },
                                        leadingIcon = { Icon(Icons.Default.PhotoLibrary, contentDescription = null) },
                                        onClick = {
                                            showQrMenu = false
                                            qrImageLauncher.launch("image/*")
                                        },
                                    )
                                }
                            }
                            IconButton(onClick = { showTrash = !showTrash }) {
                                Icon(
                                    if (showTrash) Icons.Default.Description else Icons.Default.DeleteOutline,
                                    contentDescription = if (showTrash) "Все заметки" else "Корзина",
                                )
                            }
                            IconButton(
                                enabled = !syncing,
                                onClick = {
                                    scope.launch {
                                        syncing = true
                                        try {
                                            val msg = when {
                                                settings.pcSyncUrl.isNotBlank() -> SyncClients.syncWithPc(repo, settings).message
                                                settings.webdavUrl.isNotBlank() -> SyncClients.syncWithWebDav(repo, settings).message
                                                else -> "Настройте Wi-Fi ПК или WebDAV в Настройках"
                                            }
                                            reload()
                                            statusMsg = msg
                                        } catch (e: Exception) {
                                            statusMsg = "Ошибка: ${e.message}"
                                        } finally {
                                            syncing = false
                                        }
                                    }
                                },
                            ) {
                                Icon(Icons.Default.Sync, contentDescription = "Синхронизировать")
                            }
                            IconButton(onClick = { showSettings = true }) {
                                Icon(Icons.Default.Settings, contentDescription = "Настройки")
                            }
                        },
                    )
                },
                floatingActionButton = {
                    if (!showTrash) {
                        FloatingActionButton(
                            onClick = {
                                val created = repo.createNote()
                                reload()
                                openNoteId = created.id
                            },
                            containerColor = MaterialTheme.colorScheme.primary,
                            contentColor = MaterialTheme.colorScheme.onPrimary,
                        ) {
                            Icon(Icons.Default.Add, contentDescription = "Новая заметка")
                        }
                    }
                },
            ) { padding ->
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .padding(horizontal = 12.dp),
                ) {
                    OutlinedTextField(
                        value = search,
                        onValueChange = { search = it },
                        placeholder = { Text(s.searchHint) },
                        singleLine = true,
                        leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                        trailingIcon = {
                            if (search.isNotEmpty()) {
                                IconButton(onClick = { search = "" }) {
                                    Icon(Icons.Default.Close, contentDescription = "Clear")
                                }
                            }
                        },
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
                    )
                    // Полоска фильтров по цветам
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState())
                            .padding(bottom = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        FilterChip(
                            selected = colorFilter.isEmpty(),
                            onClick = { colorFilter = "" },
                            label = { Text("${s.all} (${filtered.size})") },
                        )
                        NOTE_COLORS.drop(1).forEach { (hex, _) ->
                            val col = parseColor(hex) ?: Color.Gray
                            Box(
                                modifier = Modifier
                                    .size(26.dp)
                                    .clip(CircleShape)
                                    .background(col)
                                    .border(
                                        width = if (colorFilter == hex) 2.5.dp else 1.dp,
                                        color = if (colorFilter == hex) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.outline,
                                        shape = CircleShape,
                                    )
                                    .clickable { colorFilter = if (colorFilter == hex) "" else hex },
                            )
                        }
                    }

                    if (filtered.isEmpty()) {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            Text(
                                if (showTrash) s.emptyTrash else s.emptyNotes,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    } else {
                        LazyColumn(
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                            contentPadding = PaddingValues(bottom = 88.dp),
                        ) {
                            items(filtered, key = { it.id }) { item ->
                                NoteCardItem(
                                    note = item,
                                    defaultTitle = s.newNoteTitle,
                                    onClick = { openNoteId = item.id },
                                    onPin = {
                                        repo.saveNote(item.copy(pinned = !item.pinned, modified = repo.nowSec()))
                                        reload()
                                    },
                                    onRestore = {
                                        repo.restoreNote(item)
                                        reload()
                                        statusMsg = s.restoredMsg
                                    },
                                    onDelete = {
                                        if (item.deleted) {
                                            pendingPurge = item
                                        } else {
                                            repo.trashNote(item)
                                            reload()
                                        }
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }

        // Дополнительное подтверждение при безвозвратном удалении из корзины
        pendingPurge?.let { toPurge ->
            AlertDialog(
                onDismissRequest = { pendingPurge = null },
                title = { Text(s.purgeTitle) },
                text = { Text("${toPurge.title.ifBlank { s.newNoteTitle }}\n\n${s.purgeMessage}") },
                confirmButton = {
                    TextButton(onClick = {
                        repo.purgeNote(toPurge.id)
                        pendingPurge = null
                        reload()
                    }) {
                        Text(s.deleteForever, color = MaterialTheme.colorScheme.error)
                    }
                },
                dismissButton = {
                    TextButton(onClick = { pendingPurge = null }) { Text(s.cancel) }
                },
            )
        }

        if (showSettings) {
            SettingsSheet(
                initial = settings,
                s = s,
                syncing = syncing,
                syncStatus = statusMsg,
                onDismiss = { showSettings = false },
                onSave = { stNew ->
                    settings = stNew
                    repo.saveSettings(stNew)
                    showSettings = false
                    statusMsg = AppStrings.of(stNew.lang).settingsSavedMsg
                },
                onSyncPc = { s ->
                    settings = s
                    repo.saveSettings(s)
                    scope.launch {
                        syncing = true
                        try {
                            statusMsg = SyncClients.syncWithPc(repo, s).message
                            reload()
                        } catch (e: Exception) {
                            statusMsg = "Wi-Fi ошибка: ${e.message}"
                        } finally {
                            syncing = false
                        }
                    }
                },
                onSyncWebDav = { s ->
                    settings = s
                    repo.saveSettings(s)
                    scope.launch {
                        syncing = true
                        try {
                            statusMsg = SyncClients.syncWithWebDav(repo, s).message
                            reload()
                        } catch (e: Exception) {
                            statusMsg = "WebDAV ошибка: ${e.message}"
                        } finally {
                            syncing = false
                        }
                    }
                },
            )
        }
    }
}

@Composable
private fun NoteCardItem(
    note: NoteItem,
    defaultTitle: String,
    onClick: () -> Unit,
    onPin: () -> Unit,
    onRestore: () -> Unit,
    onDelete: () -> Unit,
) {
    val barColor = parseColor(note.color)
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
        modifier = Modifier
            .fillMaxWidth()
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (barColor != null) {
                Box(
                    Modifier
                        .width(4.dp)
                        .height(48.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(barColor),
                )
                Spacer(Modifier.width(10.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(
                    text = note.title.ifBlank { defaultTitle },
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 16.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (note.snippet.isNotBlank()) {
                    Text(
                        text = note.snippet,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 13.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = formatDate(if (note.modified > 0) note.modified else note.created),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 11.sp,
                    )
                    if (note.origin != null) {
                        Text(
                            text = formatOrigin(note.origin),
                            color = MaterialTheme.colorScheme.primary,
                            fontSize = 11.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
            if (note.deleted) {
                IconButton(onClick = onRestore) {
                    Icon(Icons.Default.RestoreFromTrash, contentDescription = "Восстановить из корзины")
                }
            } else {
                IconButton(onClick = onPin) {
                    Icon(
                        if (note.pinned) Icons.Default.Star else Icons.Default.StarBorder,
                        contentDescription = "Закрепить",
                        tint = if (note.pinned) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Close, contentDescription = "Удалить", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NoteEditorScreen(
    note: NoteItem,
    s: AppStrings,
    snackbarHostState: SnackbarHostState,
    onBack: () -> Unit,
    onSave: (NoteItem) -> Unit,
    onShare: (NoteItem) -> Unit,
    onTrashToggle: (NoteItem) -> Unit,
) {
    var text by remember(note.id) { mutableStateOf(note.plain) }
    var color by remember(note.id) { mutableStateOf(note.color) }
    var origin by remember(note.id) { mutableStateOf(note.origin) }
    var dirty by remember(note.id) { mutableStateOf(false) }
    var showColors by remember { mutableStateOf(false) }

    fun persist(newText: String = text, newColor: String = color, newOrigin: NoteOrigin? = origin) {
        dirty = false
        val newHtml = if (newText == note.plain && note.html.isNotBlank()) note.html else NoteRepository.plainToHtml(newText)
        onSave(note.copy(plain = newText, html = newHtml, color = newColor, origin = newOrigin))
    }

    // Системная кнопка/жест «Назад» возвращает к списку, а не сворачивает приложение
    BackHandler {
        if (dirty) persist()
        onBack()
    }

    // Автосохранение с задержкой 800 мс после паузы в наборе
    LaunchedEffect(text) {
        if (dirty) {
            delay(800)
            persist(newText = text)
        }
    }

    // Сохранение при сворачивании приложения (ON_STOP) и уходе с экрана редактора
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, note.id) {
        val obs = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP && dirty) {
                persist()
            }
        }
        lifecycleOwner.lifecycle.addObserver(obs)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(obs)
            if (dirty) persist()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                navigationIcon = {
                    IconButton(onClick = {
                        if (dirty) persist()
                        onBack()
                    }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                    }
                },
                title = { Text(s.editor, fontSize = 16.sp) },
                actions = {
                    IconButton(onClick = { showColors = !showColors }) {
                        Icon(Icons.Default.Palette, contentDescription = "Цветная метка")
                    }
                    IconButton(onClick = {
                        if (dirty) persist()
                        val curHtml = if (text == note.plain && note.html.isNotBlank()) note.html else NoteRepository.plainToHtml(text)
                        onShare(note.copy(plain = text, html = curHtml, color = color, origin = origin))
                    }) {
                        Icon(Icons.Default.Share, contentDescription = "Поделиться (.zametka)")
                    }
                    IconButton(onClick = {
                        dirty = false
                        val curHtml = if (text == note.plain && note.html.isNotBlank()) note.html else NoteRepository.plainToHtml(text)
                        onTrashToggle(note.copy(plain = text, html = curHtml, color = color, origin = origin))
                    }) {
                        Icon(
                            if (note.deleted) Icons.Default.RestoreFromTrash else Icons.Default.DeleteOutline,
                            contentDescription = if (note.deleted) "Восстановить" else "В корзину",
                        )
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            if (showColors) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState())
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    NOTE_COLORS.forEach { (hex, label) ->
                        val col = parseColor(hex) ?: MaterialTheme.colorScheme.surfaceVariant
                        FilterChip(
                            selected = color == hex,
                            onClick = {
                                color = hex
                                persist(newColor = hex)
                                showColors = false
                            },
                            label = { Text(label) },
                            leadingIcon = {
                                Box(Modifier.size(12.dp).clip(CircleShape).background(col))
                            },
                        )
                    }
                }
            }

            // Плашка происхождения заметки (от кого / с какого ПК / когда) с кнопкой очистки
            origin?.let { org ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .padding(horizontal = 14.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = formatOrigin(org),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    IconButton(
                        onClick = {
                            origin = null
                            persist(newOrigin = null)
                        },
                        modifier = Modifier.size(24.dp),
                    ) {
                        Icon(Icons.Default.Close, contentDescription = "Очистить источник", modifier = Modifier.size(16.dp))
                    }
                }
            }

            // Быстрая панель списков и чек-листов
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.background)
                    .padding(horizontal = 8.dp, vertical = 2.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                TextButton(onClick = {
                    val nl = if (text.isEmpty() || text.endsWith("\n")) "• " else "\n• "
                    text += nl
                    persist(newText = text)
                }) { Text(s.bullet) }
                TextButton(onClick = {
                    val nl = if (text.isEmpty() || text.endsWith("\n")) "☐ " else "\n☐ "
                    text += nl
                    persist(newText = text)
                }) { Text(s.checklist) }
                TextButton(onClick = {
                    val nl = if (text.isEmpty() || text.endsWith("\n")) "1. " else "\n1. "
                    text += nl
                    persist(newText = text)
                }) { Text(s.numbered) }
            }

            TextField(
                value = text,
                onValueChange = {
                    text = it
                    dirty = true
                },
                placeholder = { Text(s.editorHint) },
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = MaterialTheme.colorScheme.surface,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surface,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
                modifier = Modifier.fillMaxWidth().weight(1f),
            )

            val words = text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.size
            Text(
                text = "${s.words}: $words · ${s.chars}: ${text.length}",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
            )
        }
    }
}

@Composable
private fun SettingsSheet(
    initial: AppSettings,
    s: AppStrings,
    syncing: Boolean,
    syncStatus: String?,
    onDismiss: () -> Unit,
    onSave: (AppSettings) -> Unit,
    onSyncPc: (AppSettings) -> Unit,
    onSyncWebDav: (AppSettings) -> Unit,
) {
    var lang by remember { mutableStateOf(initial.lang) }
    var theme by remember { mutableStateOf(initial.theme) }
    var owner by remember { mutableStateOf(initial.ownerName) }
    var device by remember { mutableStateOf(initial.deviceName) }
    var pcUrl by remember { mutableStateOf(initial.pcSyncUrl) }
    var davUrl by remember { mutableStateOf(initial.webdavUrl) }
    var davUser by remember { mutableStateOf(initial.webdavUser) }
    var davPass by remember { mutableStateOf(initial.webdavPass) }
    val curS = remember(lang) { AppStrings.of(lang) }

    fun current() = initial.copy(
        lang = lang,
        theme = theme,
        ownerName = owner.trim(),
        deviceName = device.trim(),
        pcSyncUrl = pcUrl.trim(),
        webdavUrl = davUrl.trim(),
        webdavUser = davUser.trim(),
        webdavPass = davPass,
    )

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(curS.settingsTitle) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(curS.language, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("ru" to "Русский", "en" to "English").forEach { (k, lbl) ->
                        FilterChip(selected = lang == k, onClick = { lang = k }, label = { Text(lbl) })
                    }
                }
                Text(curS.theme, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("system" to curS.themeSystem, "light" to curS.themeLight, "dark" to curS.themeDark).forEach { (k, lbl) ->
                        FilterChip(selected = theme == k, onClick = { theme = k }, label = { Text(lbl) })
                    }
                }
                OutlinedTextField(value = owner, onValueChange = { owner = it }, label = { Text(curS.ownerName) }, singleLine = true)
                OutlinedTextField(value = device, onValueChange = { device = it }, label = { Text(curS.deviceName) }, singleLine = true)

                HorizontalDivider()
                Text(curS.wifiTitle, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                OutlinedTextField(
                    value = pcUrl,
                    onValueChange = { pcUrl = it },
                    label = { Text(curS.wifiHint) },
                    singleLine = true,
                )
                Button(enabled = !syncing, onClick = { onSyncPc(current()) }, modifier = Modifier.fillMaxWidth()) {
                    Text(curS.syncWifiBtn)
                }

                HorizontalDivider()
                Text(curS.webdavTitle, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                OutlinedTextField(
                    value = davUrl,
                    onValueChange = { davUrl = it },
                    label = { Text(curS.webdavHint) },
                    singleLine = true,
                )
                OutlinedTextField(value = davUser, onValueChange = { davUser = it }, label = { Text(curS.login) }, singleLine = true)
                OutlinedTextField(
                    value = davPass,
                    onValueChange = { davPass = it },
                    label = { Text(curS.appPass) },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                )
                Button(enabled = !syncing, onClick = { onSyncWebDav(current()) }, modifier = Modifier.fillMaxWidth()) {
                    Text(curS.syncWebdavBtn)
                }
                if (!syncStatus.isNullOrBlank()) {
                    Text(syncStatus, fontSize = 12.sp, color = MaterialTheme.colorScheme.primary)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(current()) }) { Text(curS.save) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(curS.cancel) }
        },
    )
}
