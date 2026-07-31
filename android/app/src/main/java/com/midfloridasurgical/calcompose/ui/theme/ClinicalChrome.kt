package com.midfloridasurgical.calcompose.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Soft teal / liquid-glass card chrome approximating iOS `liquidGlassCard`.
 * Tint must come from [ClinicalPalette] — never raw hex at call sites.
 */
@Composable
fun LiquidGlassCard(
    modifier: Modifier = Modifier,
    tint: Color = ClinicalPalette.Card,
    cornerRadius: Dp = 16.dp,
    content: @Composable BoxScope.() -> Unit,
) {
    val shape = RoundedCornerShape(cornerRadius)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .shadow(
                elevation = 10.dp,
                shape = shape,
                ambientColor = ClinicalPalette.Shadow.copy(alpha = 0.12f),
                spotColor = ClinicalPalette.Shadow.copy(alpha = 0.12f),
            )
            .clip(shape)
            .background(ClinicalPalette.Card.copy(alpha = 0.88f))
            .background(tint.copy(alpha = 0.68f))
            .border(
                width = 1.dp,
                brush = Brush.linearGradient(
                    colors = listOf(
                        ClinicalPalette.OnTeal.copy(alpha = 0.96f),
                        ClinicalPalette.Stroke.copy(alpha = 0.44f),
                        tint.copy(alpha = 0.84f),
                    ),
                ),
                shape = shape,
            ),
        content = content,
    )
}

fun Modifier.liquidGlassSurface(
    tint: Color = ClinicalPalette.Card,
    cornerRadius: Dp = 16.dp,
): Modifier {
    val shape = RoundedCornerShape(cornerRadius)
    return this
        .shadow(
            elevation = 10.dp,
            shape = shape,
            ambientColor = ClinicalPalette.Shadow.copy(alpha = 0.12f),
            spotColor = ClinicalPalette.Shadow.copy(alpha = 0.12f),
        )
        .clip(shape)
        .background(ClinicalPalette.Card.copy(alpha = 0.88f))
        .background(tint.copy(alpha = 0.68f))
        .border(
            width = 1.dp,
            brush = Brush.linearGradient(
                colors = listOf(
                    ClinicalPalette.OnTeal.copy(alpha = 0.96f),
                    ClinicalPalette.Stroke.copy(alpha = 0.44f),
                    tint.copy(alpha = 0.84f),
                ),
            ),
            shape = shape,
        )
}
