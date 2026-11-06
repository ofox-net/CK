package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.example.data.model.MoneyUtils
import com.example.domain.CasinoGame
import com.example.domain.LaunchGameInput
import com.example.domain.LaunchGameResponse
import com.example.ui.MainViewModel
import com.example.ui.components.borderStroke
import com.example.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun CasinoScreen(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier
) {
    val externalGames by viewModel.externalGames.collectAsState()
    val wallet by viewModel.wallet.collectAsState()
    val scope = rememberCoroutineScope()

    var selectedProviderFilter by remember { mutableStateOf("ALL") }
    var launchedGame by remember { mutableStateOf<CasinoGame?>(null) }
    var launchResponse by remember { mutableStateOf<LaunchGameResponse?>(null) }
    var isLaunching by remember { mutableStateOf(false) }

    val filteredGames = when (selectedProviderFilter) {
        "ALL" -> externalGames
        "EVOLUTION" -> externalGames.filter { it.providerId == "provider_evolution" }
        "PRAGMATIC" -> externalGames.filter { it.providerId == "provider_pragmatic" }
        "SPRIBE" -> externalGames.filter { it.providerId == "provider_spribe" }
        else -> externalGames
    }

    if (launchedGame != null && launchResponse != null) {
        GameLauncherDialog(
            game = launchedGame!!,
            response = launchResponse!!,
            balanceCents = wallet?.availableBalance ?: 0L,
            onDismiss = {
                launchedGame = null
                launchResponse = null
            }
        )
    }

    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .background(ObsidianBg)
            .padding(horizontal = 14.dp)
    ) {
        item {
            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = "External Casino Providers",
                color = TextPrimary,
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "Modular integration via CasinoProviderInterface adapters (Evolution, Pragmatic, Spribe)",
                color = TextSecondary,
                fontSize = 12.sp
            )
            Spacer(modifier = Modifier.height(12.dp))

            // Provider filter tabs
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                listOf("ALL" to "All", "PRAGMATIC" to "Pragmatic", "EVOLUTION" to "Evolution", "SPRIBE" to "Spribe").forEach { (id, label) ->
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (selectedProviderFilter == id) GoldAccent else SurfaceDark)
                            .clickable { selectedProviderFilter = id }
                            .padding(horizontal = 12.dp, vertical = 8.dp)
                    ) {
                        Text(
                            text = label,
                            color = if (selectedProviderFilter == id) ObsidianBg else TextSecondary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 12.sp
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(14.dp))
        }

        items(filteredGames) { game ->
            CasinoGameCard(
                game = game,
                onLaunchClick = {
                    scope.launch {
                        isLaunching = true
                        val adapter = when (game.providerId) {
                            "provider_evolution" -> viewModel.evolutionAdapter
                            "provider_pragmatic" -> viewModel.pragmaticAdapter
                            else -> viewModel.spribeAdapter
                        }
                        val resp = adapter.launchGame(
                            LaunchGameInput(
                                tenantId = viewModel.activeTenantId.value,
                                userId = viewModel.activeUserId.value,
                                gameId = game.id,
                                currency = "INR"
                            )
                        )
                        launchedGame = game
                        launchResponse = resp
                        isLaunching = false
                    }
                }
            )
            Spacer(modifier = Modifier.height(10.dp))
        }

        item { Spacer(modifier = Modifier.height(30.dp)) }
    }
}

@Composable
fun CasinoGameCard(
    game: CasinoGame,
    onLaunchClick: () -> Unit
) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(54.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(CardHighlight),
                contentAlignment = Alignment.Center
            ) {
                Text(text = game.iconEmoji, fontSize = 28.sp)
            }

            Spacer(modifier = Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = game.title,
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp
                    )
                    if (game.isLive) {
                        Spacer(modifier = Modifier.width(6.dp))
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(4.dp))
                                .background(NeonRed.copy(alpha = 0.2f))
                                .padding(horizontal = 4.dp, vertical = 1.dp)
                        ) {
                            Text(
                                text = "LIVE",
                                color = NeonRed,
                                fontSize = 9.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = "${game.providerName} • RTP: ${game.rtp}%",
                    color = ElectricCyan,
                    fontSize = 11.sp
                )
                Text(
                    text = "Min: ${MoneyUtils.formatCents(game.minBetCents)}",
                    color = TextMuted,
                    fontSize = 11.sp
                )
            }

            Button(
                onClick = onLaunchClick,
                colors = ButtonDefaults.buttonColors(containerColor = GoldAccent),
                shape = RoundedCornerShape(8.dp),
                modifier = Modifier.testTag("launch_${game.id}")
            ) {
                Text(text = "Play", color = ObsidianBg, fontWeight = FontWeight.Bold, fontSize = 12.sp)
            }
        }
    }
}

@Composable
fun GameLauncherDialog(
    game: CasinoGame,
    response: LaunchGameResponse,
    balanceCents: Long,
    onDismiss: () -> Unit
) {
    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = SurfaceDark,
            border = borderStroke(1.dp, ElectricCyan),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(18.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(text = game.iconEmoji, fontSize = 22.sp)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = game.title,
                            color = TextPrimary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 16.sp
                        )
                    }
                    IconButton(onClick = onDismiss) {
                        Icon(imageVector = Icons.Default.Close, contentDescription = "Close", tint = TextMuted)
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = CardHighlight,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(10.dp)) {
                        Text(
                            text = "Provider Session Initialized ✓",
                            color = NeonGreen,
                            fontWeight = FontWeight.Bold,
                            fontSize = 12.sp
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Seamless Single-Wallet Balance: ${MoneyUtils.formatCents(balanceCents)}",
                            color = GoldAccent,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = "Session Token:\n${response.token}",
                            color = TextSecondary,
                            fontSize = 10.sp,
                            fontFamily = FontFamily.Monospace
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Embed URL:\n${response.sessionUrl}",
                            color = TextMuted,
                            fontSize = 9.sp,
                            fontFamily = FontFamily.Monospace,
                            maxLines = 2
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(140.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(ObsidianBg),
                    contentAlignment = Alignment.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(text = "🎮 ${game.title}", color = TextPrimary, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "External iframe & Webhook bridge running in background",
                            color = TextSecondary,
                            fontSize = 11.sp
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(modifier = Modifier.size(8.dp).clip(CircleShape).background(NeonGreen))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(text = "Socket Connected • Low Latency", color = NeonGreen, fontSize = 11.sp)
                        }
                    }
                }

                Spacer(modifier = Modifier.height(14.dp))
                Button(
                    onClick = onDismiss,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = CardHighlight)
                ) {
                    Text("Exit Game Session", color = TextPrimary)
                }
            }
        }
    }
}
