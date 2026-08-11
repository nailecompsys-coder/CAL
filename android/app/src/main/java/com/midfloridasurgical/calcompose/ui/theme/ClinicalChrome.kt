package com.midfloridasurgical.calcompose.ui.theme

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * OR Whiteboard chrome — solid Material surfaces, fat status rails,
 * generous tap targets. No glass blur / translucent frost stacks.
 */

private val CardRadius = 12.dp
private val ChipRadius = 10.dp

/** Full-bleed mint/teal page wash. */
@Composable
fun ClinicalPageBackground(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(ClinicalPalette.PageGradient),
    )
}

fun Modifier.clinicalPageBackground(): Modifier =
    this.background(ClinicalPalette.PageGradient)

/** Auth wash — solid soft teal, no frost. */
@Composable
fun ClinicalAuthBackground(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(ClinicalPalette.AuthWashGradient),
    )
}

/**
 * Solid whiteboard card — opaque surface + quiet outline.
 * Name kept as LiquidGlassCard for call-site compatibility; glass is gone.
 */
@Composable
fun LiquidGlassCard(
    modifier: Modifier = Modifier,
    tint: Color = ClinicalPalette.CardStrong,
    cornerRadius: Dp = CardRadius,
    content: @Composable BoxScope.() -> Unit,
) {
    WhiteboardCard(
        modifier = modifier,
        tint = tint,
        cornerRadius = cornerRadius,
        content = content,
    )
}

@Composable
fun WhiteboardCard(
    modifier: Modifier = Modifier,
    tint: Color = ClinicalPalette.CardStrong,
    cornerRadius: Dp = CardRadius,
    content: @Composable BoxScope.() -> Unit,
) {
    val shape = RoundedCornerShape(cornerRadius)
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = shape,
        color = tint,
        shadowElevation = 1.dp,
        tonalElevation = 0.dp,
        border = BorderStroke(
            1.dp,
            ClinicalPalette.Stroke.copy(alpha = 0.85f),
        ),
    ) {
        Box(content = content)
    }
}

/** Section with bold label + solid body. */
@Composable
fun DashboardSection(
    title: String,
    modifier: Modifier = Modifier,
    tint: Color = ClinicalPalette.CardStrong,
    railColor: Color? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            title.uppercase(),
            style = ClinicalTypography.sectionLabel,
            color = ClinicalPalette.Muted,
            modifier = Modifier.padding(horizontal = 4.dp),
        )
        WhiteboardCard(tint = tint, cornerRadius = CardRadius) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(IntrinsicSize.Min),
            ) {
                if (railColor != null) {
                    Box(
                        modifier = Modifier
                            .width(6.dp)
                            .fillMaxHeight()
                            .background(railColor),
                    )
                }
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .padding(horizontal = 14.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    content = content,
                )
            }
        }
    }
}

/** Solid surface modifier for toolbars — no translucent stack. */
fun Modifier.liquidGlassSurface(
    tint: Color = ClinicalPalette.CardStrong,
    cornerRadius: Dp = CardRadius,
): Modifier {
    val shape = RoundedCornerShape(cornerRadius)
    return this
        .clip(shape)
        .background(tint)
        .border(1.dp, ClinicalPalette.Stroke.copy(alpha = 0.85f), shape)
}

/** Auth card — solid raised white. */
fun Modifier.authGlassSurface(cornerRadius: Dp = 16.dp): Modifier {
    val shape = RoundedCornerShape(cornerRadius)
    return this
        .clip(shape)
        .background(ClinicalPalette.CardStrong)
        .border(1.5.dp, ClinicalPalette.Stroke, shape)
}

/** Material field chrome — rounded rect, not iOS capsule. */
fun Modifier.authFieldChrome(): Modifier {
    val shape = RoundedCornerShape(12.dp)
    return this
        .clip(shape)
        .background(ClinicalPalette.FieldFill)
        .border(1.5.dp, ClinicalPalette.Stroke, shape)
}

@Composable
fun ClinicalPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    busy: Boolean = false,
) {
    val shape = RoundedCornerShape(14.dp)
    Button(
        onClick = onClick,
        enabled = enabled && !busy,
        modifier = modifier
            .fillMaxWidth()
            .height(52.dp),
        shape = shape,
        colors = ButtonDefaults.buttonColors(
            containerColor = ClinicalPalette.Transparent,
            disabledContainerColor = ClinicalPalette.Transparent,
            contentColor = ClinicalPalette.OnTeal,
            disabledContentColor = ClinicalPalette.OnTeal.copy(alpha = 0.55f),
        ),
        contentPadding = PaddingValues(0.dp),
        elevation = ButtonDefaults.buttonElevation(0.dp, 0.dp, 0.dp, 0.dp, 0.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clip(shape)
                .background(
                    if (enabled && !busy) {
                        ClinicalPalette.AuthPrimaryGradient
                    } else {
                        Brush.horizontalGradient(
                            listOf(
                                ClinicalPalette.Teal.copy(alpha = 0.45f),
                                ClinicalPalette.AuthAccent.copy(alpha = 0.45f),
                            ),
                        )
                    },
                ),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                if (busy) "Please wait…" else text,
                style = ClinicalTypography.headlineStrong,
                color = ClinicalPalette.OnTeal,
            )
        }
    }
}

@Composable
fun ClinicalSendChip(
    onClick: () -> Unit,
    enabled: Boolean,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .heightIn(min = 44.dp)
            .clip(RoundedCornerShape(ChipRadius))
            .background(
                if (enabled) ClinicalPalette.Teal else ClinicalPalette.PorcelainChip,
            )
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 18.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            "Send",
            style = ClinicalTypography.rowTitleStrong,
            color = if (enabled) ClinicalPalette.OnTeal else ClinicalPalette.Muted,
        )
    }
}

@Composable
fun ClinicalScopeChip(
    selected: Boolean,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(ChipRadius)
    Box(
        modifier = modifier
            .heightIn(min = 44.dp)
            .clip(shape)
            .background(if (selected) ClinicalPalette.Teal else ClinicalPalette.CardStrong)
            .border(
                width = if (selected) 0.dp else 1.5.dp,
                color = if (selected) ClinicalPalette.Transparent else ClinicalPalette.Stroke,
                shape = shape,
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            style = ClinicalTypography.caption,
            fontWeight = FontWeight.Bold,
            color = if (selected) ClinicalPalette.OnTeal else ClinicalPalette.Ink,
        )
    }
}

@Composable
fun ClinicalTodayChip(onClick: () -> Unit, modifier: Modifier = Modifier) {
    Text(
        "Today",
        style = ClinicalTypography.caption,
        fontWeight = FontWeight.Bold,
        color = ClinicalPalette.OnTeal,
        modifier = modifier
            .heightIn(min = 36.dp)
            .clip(RoundedCornerShape(ChipRadius))
            .background(ClinicalPalette.Teal)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    )
}

@Composable
fun ClinicalGlassToolbar(
    modifier: Modifier = Modifier,
    content: @Composable RowScope.() -> Unit,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(ClinicalPalette.CardStrong)
            .border(1.dp, ClinicalPalette.Stroke.copy(alpha = 0.7f))
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
        content = content,
    )
}

/** Fat left status rail for day-stack / timeline rows. */
@Composable
fun StatusRail(
    color: Color,
    modifier: Modifier = Modifier,
    width: Dp = 6.dp,
) {
    Box(
        modifier = modifier
            .width(width)
            .fillMaxSize()
            .background(color),
    )
}
