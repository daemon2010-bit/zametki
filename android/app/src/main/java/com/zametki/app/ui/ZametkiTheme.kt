package com.zametki.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val LightColors = lightColorScheme(
    primary = Color(0xFFB8860B),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFFFE18F),
    onPrimaryContainer = Color(0xFF1D1D1F),
    background = Color(0xFFF3F2EF),
    onBackground = Color(0xFF1D1D1F),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF1D1D1F),
    surfaceVariant = Color(0xFFECEBE8),
    onSurfaceVariant = Color(0xFF6B6A66),
    outline = Color(0xFFDBDAD5),
    error = Color(0xFFC0392B),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFFFD60A),
    onPrimary = Color(0xFF1B1B1E),
    primaryContainer = Color(0xFF5A4A12),
    onPrimaryContainer = Color(0xFFF5F5F7),
    background = Color(0xFF232326),
    onBackground = Color(0xFFF5F5F7),
    surface = Color(0xFF2A2A2E),
    onSurface = Color(0xFFF5F5F7),
    surfaceVariant = Color(0xFF1B1B1E),
    onSurfaceVariant = Color(0xFFA9A9AE),
    outline = Color(0xFF3C3C41),
    error = Color(0xFFFF6B5E),
)

@Composable
fun ZametkiTheme(mode: String, content: @Composable () -> Unit) {
    val dark = when (mode) {
        "dark" -> true
        "light" -> false
        else -> isSystemInDarkTheme()
    }
    MaterialTheme(
        colorScheme = if (dark) DarkColors else LightColors,
        content = content,
    )
}
