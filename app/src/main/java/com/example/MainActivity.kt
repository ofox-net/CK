package com.example

import android.content.pm.ActivityInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.MainViewModel
import com.example.ui.components.AppHeader
import com.example.ui.components.ProvablyFairDialog
import com.example.ui.components.borderStroke
import com.example.ui.screens.*
import com.example.ui.theme.*

enum class AppNavDestination(val label: String, val icon: ImageVector) {
    GAME("Arena", Icons.Default.Casino),
    CASINO("Providers", Icons.Default.SportsEsports),
    WALLET("Wallet", Icons.Default.AccountBalanceWallet),
    AFFILIATE("Affiliate", Icons.Default.Groups),
    PROFILE("Profile", Icons.Default.AccountCircle)
}

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        enableEdgeToEdge()

        setContent {
            MyApplicationTheme {
                MainAppScaffold(viewModel = viewModel)
            }
        }
    }
}

@Composable
fun MainAppScaffold(viewModel: MainViewModel) {
    val isLoggedIn by viewModel.isLoggedIn.collectAsState()

    if (!isLoggedIn) {
        AuthScreen(viewModel = viewModel)
        return
    }

    var currentDestination by remember { mutableStateOf(AppNavDestination.GAME) }
    var showProvablyFairDialog by remember { mutableStateOf(false) }
    var showLogoutDialog by remember { mutableStateOf(false) }

    val activeUser by viewModel.activeUser.collectAsState()
    val activeTenantId by viewModel.activeTenantId.collectAsState()
    val allTenants by viewModel.allTenants.collectAsState()
    val wallet by viewModel.wallet.collectAsState()
    val currentRound by viewModel.currentRound.collectAsState()
    val notification by viewModel.notification.collectAsState()
    val isSoundEnabled by viewModel.isSoundEnabled.collectAsState()
    val serverAccountStatus by viewModel.serverAccountStatus.collectAsState()

    val currentTenantName = allTenants.firstOrNull { it.id == activeTenantId }?.name ?: "Colour King"

    if (showProvablyFairDialog && currentRound != null) {
        ProvablyFairDialog(
            serverSeedHash = currentRound?.serverSeedHash ?: "",
            currentServerSeed = currentRound?.serverSeed,
            clientSeed = currentRound?.clientSeed ?: "apex_community_seed",
            nonce = currentRound?.nonce ?: 0L,
            onDismiss = { showProvablyFairDialog = false }
        )
    }

    if (showLogoutDialog) {
        AlertDialog(
            onDismissRequest = { showLogoutDialog = false },
            title = {
                Text(
                    text = "Log Out",
                    fontWeight = FontWeight.Bold,
                    color = TextPrimary
                )
            },
            text = {
                Text(
                    text = "Are you sure you want to log out of Colour King?",
                    color = TextSecondary
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showLogoutDialog = false
                        viewModel.logout()
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = NeonRed),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.testTag("confirm_logout_btn")
                ) {
                    Text("Yes, Log Out", color = Color.White, fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                OutlinedButton(
                    onClick = { showLogoutDialog = false },
                    border = borderStroke(1.dp, CardBorder),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Cancel", color = TextSecondary)
                }
            },
            containerColor = SurfaceDark,
            shape = RoundedCornerShape(16.dp)
        )
    }

    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .background(ObsidianBg),
        topBar = {
            Column(modifier = Modifier.statusBarsPadding()) {
                AppHeader(
                    tenantName = currentTenantName,
                    username = activeUser?.username ?: "Rahul_Player",
                    userRole = activeUser?.role ?: "USER",
                    walletBalanceCents = wallet?.availableBalance ?: 0L,
                    onDepositClick = { currentDestination = AppNavDestination.WALLET },
                    onVerifyClick = { showProvablyFairDialog = true },
                    onLogoutClick = { showLogoutDialog = true }
                )

                if (serverAccountStatus == "BLOCKED") {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = NeonRed.copy(alpha = 0.22f),
                        border = borderStroke(1.dp, NeonRed),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 4.dp)
                    ) {
                        Text(
                            text = "⛔ Account temporarily restricted by Admin. Betting & wallet actions paused.",
                            color = Color.White,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                        )
                    }
                }

                // Notification Toast
                AnimatedVisibility(
                    visible = notification != null,
                    enter = slideInVertically() + fadeIn(),
                    exit = slideOutVertically() + fadeOut()
                ) {
                    notification?.let { notif ->
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = if (notif.isSuccess) NeonGreen else NeonRed,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 14.dp, vertical = 6.dp)
                                .clickable { viewModel.dismissNotification() }
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = if (notif.isSuccess) "✓ " else "✕ ",
                                    color = ObsidianBg,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 13.sp
                                )
                                Text(
                                    text = notif.message,
                                    color = ObsidianBg,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 12.sp,
                                    modifier = Modifier.weight(1f)
                                )
                            }
                        }
                    }
                }
            }
        },
        bottomBar = {
            CustomBottomNavigationBar(
                currentDestination = currentDestination,
                onSelectDestination = { currentDestination = it },
                modifier = Modifier.navigationBarsPadding()
            )
        },
        containerColor = ObsidianBg
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            when (currentDestination) {
                AppNavDestination.GAME -> GameScreen(viewModel = viewModel)
                AppNavDestination.CASINO -> CasinoScreen(viewModel = viewModel)
                AppNavDestination.WALLET -> WalletScreen(viewModel = viewModel)
                AppNavDestination.AFFILIATE -> AffiliateScreen(viewModel = viewModel)
                AppNavDestination.PROFILE -> ProfileScreen(viewModel = viewModel)
            }
        }
    }
}

@Composable
fun CustomBottomNavigationBar(
    currentDestination: AppNavDestination,
    onSelectDestination: (AppNavDestination) -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = SurfaceDark,
        tonalElevation = 8.dp
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceAround,
            verticalAlignment = Alignment.CenterVertically
        ) {
            AppNavDestination.values().forEach { destination ->
                val isSelected = currentDestination == destination

                Column(
                    modifier = Modifier
                        .clip(RoundedCornerShape(12.dp))
                        .clickable { onSelectDestination(destination) }
                        .padding(horizontal = 10.dp, vertical = 6.dp)
                        .testTag("nav_${destination.name.lowercase()}"),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Box(
                        modifier = Modifier
                            .size(36.dp)
                            .clip(CircleShape)
                            .background(if (isSelected) GoldAccent.copy(alpha = 0.2f) else Color.Transparent),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = destination.icon,
                            contentDescription = destination.label,
                            tint = if (isSelected) GoldAccent else TextMuted,
                            modifier = Modifier.size(22.dp)
                        )
                    }
                    Text(
                        text = destination.label,
                        color = if (isSelected) GoldAccent else TextMuted,
                        fontSize = 10.sp,
                        fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal
                    )
                }
            }
        }
    }
}
