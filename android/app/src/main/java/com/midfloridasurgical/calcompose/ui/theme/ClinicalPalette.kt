package com.midfloridasurgical.calcompose.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

/**
 * OR Whiteboard tokens for Compose — cool slate ink, soft mint/teal wash,
 * high-contrast day cells. One urgency accent; everything else quiet.
 * Prefer these names over raw Color(0x…) at call sites.
 */
object ClinicalPalette {
    // Surfaces — soft mint/teal wash (whiteboard paper)
    val Teal = Color(0xFF0A6B73)
    val TealSoft = Color(0xFFB8E8E0)
    val Mint = Color(0xFFD4F2DC)
    val PageTop = Color(0xFFE8F4F2)
    val PageMiddle = Color(0xFFF2F8F5)
    val PageBottom = Color(0xFFE4F0EC)
    val Card = Color(0xFFFAFCFB)
    val CardStrong = Color(0xFFFFFFFF)
    val Ink = Color(0xFF1A2428)            // cool slate ink
    val Muted = Color(0xFF5A6B72)
    val Stroke = Color(0xFFC5D6D4)
    val OnTeal = Color(0xFFFFFFFF)
    val Amber = Color(0xFFFFE8B8)          // Clinic/OR signal fill
    val Lavender = Color(0xFFEDE4FA)
    val PorcelainChip = Color(0xFFF0F5F0)
    val Scrub = Color(0xFFC8EBD0)
    val ScrubInk = Color(0xFF145C42)
    val Meeting = Color(0xFFDCC9F5)
    val MeetingStrong = Color(0xFF9B6BC9)
    val Block = Color(0xFFFAB8B8)
    val BlockStrong = Color(0xFFE24B4B)
    val Shadow = Color(0xFF1A2E2E)
    val AuthAccent = Color(0xFF1494A3)

    /** Urgency — off / call conflict / warnings (the one loud accent). */
    val WarningText = Color(0xFFE67E00)
    val Denied = Color(0xFFD32F2F)
    val CoverageRed = Color(0xFFD32F2F)
    val Urgency = Color(0xFFE65100)

    // Solid whiteboard fills (no glass translucency)
    val SurfaceRaised = Color(0xFFFFFFFF)
    val SurfaceQuiet = Color(0xFFF4F8F6)
    val FieldFill = Color(0xFFFFFFFF)
    val RailClinic = Color(0xFFE6A817)
    val RailBlock = Color(0xFFE24B4B)
    val RailMeeting = Color(0xFF9B6BC9)
    val RailCall = Color(0xFF0A6B73)
    val RailPersonal = Color(0xFF5A6B72)
    val RailOff = Color(0xFF145C42)

    // Legacy aliases — kept so older call sites compile; map to solids
    val GlassFill = SurfaceRaised
    val GlassFillStrong = CardStrong
    val GlassHighlight = CardStrong
    val Transparent = Color.Transparent

    /** Soft mint/teal page wash — flat, not liquid glass. */
    val PageGradient: Brush
        get() = Brush.verticalGradient(
            colors = listOf(PageTop, PageMiddle, PageBottom),
        )

    /** Solid teal primary for auth CTAs. */
    val AuthPrimaryGradient: Brush
        get() = Brush.horizontalGradient(
            colors = listOf(Teal, AuthAccent),
        )

    /** Soft teal wash behind auth / unlock. */
    val AuthWashGradient: Brush
        get() = Brush.verticalGradient(
            colors = listOf(
                TealSoft.copy(alpha = 0.55f),
                PageMiddle,
                Mint.copy(alpha = 0.35f),
            ),
        )
}

@Composable
fun CALTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = ClinicalPalette.Teal,
            onPrimary = ClinicalPalette.OnTeal,
            primaryContainer = ClinicalPalette.TealSoft,
            onPrimaryContainer = ClinicalPalette.Ink,
            secondary = ClinicalPalette.Muted,
            onSecondary = ClinicalPalette.OnTeal,
            secondaryContainer = ClinicalPalette.PorcelainChip,
            onSecondaryContainer = ClinicalPalette.Ink,
            tertiary = ClinicalPalette.Urgency,
            onTertiary = ClinicalPalette.OnTeal,
            tertiaryContainer = ClinicalPalette.Amber,
            onTertiaryContainer = ClinicalPalette.Ink,
            background = ClinicalPalette.PageMiddle,
            onBackground = ClinicalPalette.Ink,
            surface = ClinicalPalette.CardStrong,
            onSurface = ClinicalPalette.Ink,
            surfaceVariant = ClinicalPalette.SurfaceQuiet,
            onSurfaceVariant = ClinicalPalette.Muted,
            outline = ClinicalPalette.Stroke,
            outlineVariant = ClinicalPalette.Stroke.copy(alpha = 0.6f),
            error = ClinicalPalette.Denied,
            errorContainer = ClinicalPalette.Block,
            onError = ClinicalPalette.OnTeal,
            onErrorContainer = ClinicalPalette.Ink,
        ),
        typography = ClinicalTypography.material,
        content = content,
    )
}
