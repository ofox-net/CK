package com.example.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Luxury Dark Gaming Palette
val ObsidianBg = Color(0xFF090D14)
val SurfaceDark = Color(0xFF111726)
val CardBorder = Color(0xFF1E283E)
val CardHighlight = Color(0xFF26334D)

val NeonGreen = Color(0xFF00E676)
val NeonRed = Color(0xFFFF1744)
val NeonViolet = Color(0xFFD500F9)
val GoldAccent = Color(0xFFFFD700)
val AmberGlow = Color(0xFFFFAB00)
val ElectricCyan = Color(0xFF00E5FF)

val TextPrimary = Color(0xFFF0F4F8)
val TextSecondary = Color(0xFF94A3B8)
val TextMuted = Color(0xFF64748B)

private val DarkColorScheme = darkColorScheme(
    primary = GoldAccent,
    onPrimary = ObsidianBg,
    primaryContainer = CardHighlight,
    onPrimaryContainer = GoldAccent,
    secondary = ElectricCyan,
    onSecondary = ObsidianBg,
    tertiary = NeonViolet,
    onTertiary = Color.White,
    background = ObsidianBg,
    onBackground = TextPrimary,
    surface = SurfaceDark,
    onSurface = TextPrimary,
    surfaceVariant = CardBorder,
    onSurfaceVariant = TextSecondary,
    outline = CardBorder
)

@Composable
fun MyApplicationTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography,
        content = content
    )
}
