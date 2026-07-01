package com.midfloridasurgical.calcompose

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Message
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.EventAvailable
import androidx.compose.material.icons.rounded.LocalHospital
import androidx.compose.material.icons.rounded.NotificationsActive
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material.icons.rounded.Today
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            CALComposeTheme {
                CALPracticeShell()
            }
        }
    }
}

private val Ink = Color(0xFF102B31)
private val Muted = Color(0xFF62777D)
private val Mist = Color(0xFFF3FAF7)
private val Clinic = Color(0xFFE7F4FF)
private val Hospital = Color(0xFFFFF1DA)
private val Call = Color(0xFFE8F6EF)
private val Alert = Color(0xFFFFE7A8)
private val Coral = Color(0xFFFFD8D1)
private val Teal = Color(0xFF087967)

@Composable
private fun CALComposeTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = androidx.compose.material3.lightColorScheme(
            primary = Teal,
            onPrimary = Color.White,
            secondary = Color(0xFF426B75),
            background = Mist,
            surface = Color(0xFFFCFFFD),
            onSurface = Ink,
            surfaceVariant = Color(0xFFE6F0EE),
            outline = Color(0xFFC9DEDA),
        ),
        typography = MaterialTheme.typography.copy(
            titleLarge = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Black),
            titleMedium = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.ExtraBold),
            bodyMedium = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold),
        ),
        content = content,
    )
}

@Composable
private fun CALPracticeShell() {
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf(
        NavItem("Today", Icons.Rounded.Today, 0),
        NavItem("Schedule", Icons.Rounded.CalendarMonth, 0),
        NavItem("Messages", Icons.AutoMirrored.Rounded.Message, 3),
        NavItem("Time Off", Icons.Rounded.EventAvailable, 1),
        NavItem("Profile", Icons.Rounded.Person, 0),
    )

    Scaffold(
        containerColor = Mist,
        topBar = { PracticeTopBar() },
        bottomBar = {
            NavigationBar(
                containerColor = Color(0xFFFBFFFC),
                tonalElevation = 8.dp,
            ) {
                tabs.forEachIndexed { index, item ->
                    NavigationBarItem(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        icon = {
                            BadgedBox(
                                badge = {
                                    if (item.badgeCount > 0) {
                                        Badge(containerColor = Color(0xFFD94235)) {
                                            Text(item.badgeCount.toString())
                                        }
                                    }
                                },
                            ) {
                                Icon(item.icon, contentDescription = item.label)
                            }
                        },
                        label = {
                            Text(
                                item.label,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        },
                    )
                }
            }
        },
    ) { padding ->
        when (selectedTab) {
            0 -> TodayDashboard(Modifier.padding(padding))
            1 -> SchedulePreview(Modifier.padding(padding))
            2 -> MessagesPreview(Modifier.padding(padding))
            3 -> TimeOffPreview(Modifier.padding(padding))
            else -> ProfilePreview(Modifier.padding(padding))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PracticeTopBar() {
    TopAppBar(
        title = {
            Column {
                Text("CAL", fontWeight = FontWeight.Black, letterSpacing = 0.sp)
                Text("Practice command center", color = Muted, fontSize = 12.sp)
            }
        },
        actions = {
            Icon(
                Icons.Rounded.NotificationsActive,
                contentDescription = "Notifications",
                tint = Teal,
                modifier = Modifier
                    .padding(end = 18.dp)
                    .size(24.dp),
            )
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = Mist,
            titleContentColor = Ink,
        ),
    )
}

@Composable
private fun TodayDashboard(modifier: Modifier = Modifier) {
    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        HeaderPanel()
        GlanceGrid()
        MyScheduleCard()
        CommunicationCard()
        PatientsCard()
        TimeOffSignalCard()
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun HeaderPanel() {
    Surface(
        shape = RoundedCornerShape(28.dp),
        border = BorderStroke(1.dp, Color(0xFFCDE3DF)),
        shadowElevation = 2.dp,
        color = Color(0xFFFDFEFA),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(18.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("Good evening,", color = Muted, fontSize = 12.sp, fontWeight = FontWeight.Black)
                Text("Chris Johnson", color = Ink, fontSize = 26.sp, fontWeight = FontWeight.Black)
                Text("Monday, June 15", color = Muted, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            }
            StatusOrb("Live")
        }
    }
}

@Composable
private fun GlanceGrid() {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        MetricCard("On call", "WIN", "Kieran", Call, Modifier.weight(1f))
        MetricCard("Off", "CJ LN", "approved", Color(0xFFE1F5DD), Modifier.weight(1f))
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        MetricCard("Meeting", "None", "today", Clinic, Modifier.weight(1f))
        MetricCard("Next", "6/20", "Surgery dept", Alert, Modifier.weight(1f))
    }
}

@Composable
private fun MetricCard(title: String, value: String, detail: String, color: Color, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.height(92.dp),
        shape = RoundedCornerShape(22.dp),
        colors = CardDefaults.cardColors(containerColor = color),
        border = BorderStroke(1.dp, color.copy(alpha = 0.95f)),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.SpaceBetween) {
            Text(title, color = Muted, fontSize = 11.sp, fontWeight = FontWeight.Black)
            Text(value, color = Ink, fontSize = 19.sp, fontWeight = FontWeight.Black, maxLines = 1)
            Text(detail, color = Muted, fontSize = 11.sp, fontWeight = FontWeight.Bold, maxLines = 1)
        }
    }
}

@Composable
private fun MyScheduleCard() {
    PracticeCard("My Schedule", Icons.Rounded.Schedule) {
        TimelineRow("AM", "Winter Garden Clinic", "8:00 - 12:00", Clinic)
        TimelineRow("PM", "Altamonte Hospital", "1:00 - 4:30", Hospital)
    }
}

@Composable
private fun CommunicationCard() {
    PracticeCard("Practice Communications", Icons.AutoMirrored.Rounded.Message) {
        MessageRow("Coverage swap", "AS requested WIN call coverage", "12 min", Coral)
        MessageRow("Admin", "July call schedule needs review", "1 hr", Alert)
        MessageRow("OR update", "Room 4 running 22 minutes behind", "Live", Clinic)
    }
}

@Composable
private fun PatientsCard() {
    PracticeCard("Patient Schedule", Icons.Rounded.LocalHospital) {
        TimelineRow("8:20", "Lucy Woodley", "Winter Garden", Color(0xFFEAF4FF))
        TimelineRow("1:00", "Doulou, Gust", "Altamonte", Color(0xFFFFF3DE))
        TimelineRow("2:30", "New patient consult", "Winter Garden", Color(0xFFEAF4FF))
    }
}

@Composable
private fun TimeOffSignalCard() {
    PracticeCard("Time Off Signals", Icons.Rounded.EventAvailable) {
        DaySignal("Jun 17", requested = listOf("AS"), approved = listOf("CJ", "LN"))
        DaySignal("Jun 18", requested = listOf("NK", "JP"), approved = listOf("CJ"))
        DaySignal("Jun 20", requested = emptyList(), approved = listOf("GY", "NF"))
    }
}

@Composable
private fun PracticeCard(title: String, icon: ImageVector, content: @Composable ColumnScope.() -> Unit) {
    Card(
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFEFFFC)),
        border = BorderStroke(1.dp, Color(0xFFD5E7E2)),
        elevation = CardDefaults.cardElevation(defaultElevation = 3.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(icon, contentDescription = title, tint = Teal, modifier = Modifier.size(19.dp))
                Text(title, color = Ink, fontSize = 16.sp, fontWeight = FontWeight.Black)
            }
            content()
        }
    }
}

@Composable
private fun TimelineRow(time: String, title: String, detail: String, color: Color) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(color)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(time, color = Teal, fontSize = 12.sp, fontWeight = FontWeight.Black, modifier = Modifier.width(48.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = Ink, fontSize = 14.sp, fontWeight = FontWeight.Black, maxLines = 1)
            Text(detail, color = Muted, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
        }
    }
}

@Composable
private fun MessageRow(title: String, detail: String, time: String, color: Color) {
    Row(
        Modifier
            .fillMaxWidth()
            .border(1.dp, color.copy(alpha = 0.8f), RoundedCornerShape(16.dp))
            .background(color.copy(alpha = 0.62f), RoundedCornerShape(16.dp))
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(Teal))
        Column(Modifier.weight(1f)) {
            Text(title, color = Ink, fontSize = 13.sp, fontWeight = FontWeight.Black)
            Text(detail, color = Muted, fontSize = 12.sp, fontWeight = FontWeight.Bold, maxLines = 1)
        }
        Text(time, color = Muted, fontSize = 11.sp, fontWeight = FontWeight.Black)
    }
}

@Composable
private fun DaySignal(date: String, requested: List<String>, approved: List<String>) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Color(0xFFF8FBF8))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(date, color = Ink, fontSize = 13.sp, fontWeight = FontWeight.Black)
        if (requested.isNotEmpty()) {
            SignalPills("Requested", requested, Alert)
        }
        if (approved.isNotEmpty()) {
            SignalPills("Approved", approved, Color(0xFFDFF4DF))
        }
    }
}

@Composable
private fun SignalPills(label: String, initials: List<String>, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, color = Muted, fontSize = 11.sp, fontWeight = FontWeight.Black, modifier = Modifier.width(72.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            initials.forEach {
                Text(
                    it,
                    color = Ink,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Black,
                    modifier = Modifier
                        .clip(CircleShape)
                        .background(color)
                        .padding(horizontal = 10.dp, vertical = 5.dp),
                )
            }
        }
    }
}

@Composable
private fun StatusOrb(text: String) {
    Box(
        Modifier
            .clip(CircleShape)
            .background(Brush.linearGradient(listOf(Color(0xFF0D7D6E), Color(0xFF5EA08D))))
            .padding(horizontal = 14.dp, vertical = 9.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Black)
    }
}

@Composable
private fun SchedulePreview(modifier: Modifier = Modifier) {
    ScreenPlaceholder(modifier, "Schedule", "Daily, week, and month views would live here in native Compose.")
}

@Composable
private fun MessagesPreview(modifier: Modifier = Modifier) {
    ScreenPlaceholder(modifier, "Messages", "Practice-wide communication, call swaps, admin notes, and alerts.")
}

@Composable
private fun TimeOffPreview(modifier: Modifier = Modifier) {
    ScreenPlaceholder(modifier, "Time Off", "Native month pills, request sheets, requested and approved time off.")
}

@Composable
private fun ProfilePreview(modifier: Modifier = Modifier) {
    ScreenPlaceholder(modifier, "Profile", "Device registration, sign out, push status, and account details.")
}

@Composable
private fun ScreenPlaceholder(modifier: Modifier, title: String, detail: String) {
    Column(
        modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        PracticeCard(title, Icons.Rounded.Schedule) {
            Text(detail, color = Muted, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
            AssistChip(
                onClick = {},
                label = { Text("Native Jetpack Compose") },
                colors = AssistChipDefaults.assistChipColors(containerColor = Color(0xFFE4F3EF), labelColor = Teal),
            )
        }
    }
}

private data class NavItem(
    val label: String,
    val icon: ImageVector,
    val badgeCount: Int,
)
