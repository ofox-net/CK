package com.example.ui.screens

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.components.borderStroke
import com.example.data.model.*
import com.example.domain.RoundResult
import com.example.domain.StatementExporter
import com.example.ui.MainViewModel
import com.example.ui.components.CasinoChip
import com.example.ui.components.ProvablyFairDialog
import com.example.ui.theme.*
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.roundToLong

@Composable
fun GameScreen(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier
) {
    LaunchedEffect(Unit) {
        viewModel.ensureEngineRunning()
    }

    val selectedMarket by viewModel.selectedMarket.collectAsState()
    val currentRound by viewModel.currentRound.collectAsState()
    val isBettingOpen by viewModel.isBettingOpen.collectAsState()
    val latestResult by viewModel.latestResult.collectAsState()
    val recentRounds by viewModel.recentRounds.collectAsState()
    val userBets by viewModel.userBets.collectAsState()
    val activeBetsMap by viewModel.currentRoundActiveBets.collectAsState()
    val allRoundsMap by viewModel.allRoundsMap.collectAsState()
    val gameConfig by viewModel.gameConfig.collectAsState()

    val wallet by viewModel.wallet.collectAsState()
    val context = LocalContext.current
    val statementDays by viewModel.statementDays.collectAsState()
    var pendingBetTarget by remember { mutableStateOf<Pair<BetType, String>?>(null) }
    var showProvablyFairDialog by remember { mutableStateOf(false) }
    var activeTab by remember { mutableStateOf(0) } // 0: Game, 1: My Bets
    var betFilterMarketId by remember { mutableStateOf("ALL") }
    var betSlipsPage by remember { mutableStateOf(0) }

    val csvLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/csv")
    ) { uri ->
        if (uri != null) {
            try {
                val csvData = viewModel.generateStatementCsv(days = statementDays, filter = "PROFIT_LOSS")
                context.contentResolver.openOutputStream(uri)?.use { out ->
                    out.write(csvData.toByteArray(Charsets.UTF_8))
                }
                viewModel.postNotification("90-Day Bet & P&L Statement CSV saved!", true)
            } catch (e: Exception) {
                viewModel.postNotification("Failed to save statement: ${e.message}", false)
            }
        }
    }



    var prevBettingOpen by remember(selectedMarket.id) { mutableStateOf<Boolean?>(null) }
    var phaseBannerLocked by remember { mutableStateOf<Boolean?>(null) }

    LaunchedEffect(isBettingOpen, selectedMarket.id) {
        if (!isBettingOpen) {
            pendingBetTarget = null
        }
        val prev = prevBettingOpen
        if (prev == null) {
            prevBettingOpen = isBettingOpen
        } else if (prev != isBettingOpen) {
            prevBettingOpen = isBettingOpen
            val nowLocked = !isBettingOpen
            viewModel.playBetPhaseSound(nowLocked)
            phaseBannerLocked = nowLocked
        }
    }

    LaunchedEffect(phaseBannerLocked) {
        if (phaseBannerLocked != null) {
            delay(5000L)
            phaseBannerLocked = null
        }
    }

    val pendingType = pendingBetTarget?.first
    val pendingSelection = pendingBetTarget?.second ?: ""
    val pendingMultiplier = when {
        pendingType == BetType.NUMBER -> gameConfig?.numberMultiplier ?: 9.0
        pendingType == BetType.BIG_SMALL -> 2.0
        pendingSelection == "VIOLET" -> gameConfig?.violetMultiplier ?: 3.0
        pendingSelection == "RED" -> gameConfig?.redMultiplier ?: 2.0
        pendingSelection == "GREEN" -> gameConfig?.greenMultiplier ?: 2.0
        else -> 2.0
    }

    if (pendingBetTarget != null && isBettingOpen) {
        BetPlacementDialog(
            betType = pendingType ?: BetType.COLOR,
            selection = pendingSelection,
            multiplier = pendingMultiplier,
            availableBalanceCents = wallet?.availableBalance ?: 0L,
            isBettingOpen = isBettingOpen,
            onConfirm = { amountCents ->
                viewModel.toggleBet(pendingType ?: BetType.COLOR, pendingSelection, amountCents)
                pendingBetTarget = null
            },
            onDismiss = { pendingBetTarget = null }
        )
    }

    if (showProvablyFairDialog && currentRound != null) {
        ProvablyFairDialog(
            serverSeedHash = currentRound?.serverSeedHash ?: "",
            currentServerSeed = currentRound?.serverSeed,
            clientSeed = currentRound?.clientSeed ?: "apex_community_seed",
            nonce = currentRound?.nonce ?: 0L,
            onDismiss = { showProvablyFairDialog = false }
        )
    }

    val filteredBets = remember(userBets, betFilterMarketId, statementDays) {
        val cutoffMs = StatementExporter.cutoffTimestampMs(statementDays)
        userBets.filter { b ->
            val mOk = betFilterMarketId == "ALL" || b.gameId == betFilterMarketId
            mOk && b.createdAt >= cutoffMs
        }
    }
    val betSummary = remember(filteredBets, statementDays, wallet) {
        StatementExporter.computeSummary(
            wallet = wallet,
            bets = filteredBets,
            ledger = emptyList(),
            commissions = emptyList(),
            days = statementDays
        )
    }
    val betsPerPage = 10
    val totalBetPages = maxOf(1, (filteredBets.size + betsPerPage - 1) / betsPerPage)
    val safeBetSlipsPage = betSlipsPage.coerceIn(0, totalBetPages - 1)
    val pagedBets = remember(filteredBets, safeBetSlipsPage) {
        filteredBets.drop(safeBetSlipsPage * betsPerPage).take(betsPerPage)
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(ObsidianBg)
    ) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 14.dp)
    ) {
        item {
            // TAB Switcher: Arena vs My Bets
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(SurfaceDark)
                    .padding(4.dp)
            ) {
                TabButton(
                    title = "🎮 Live Arena",
                    isSelected = activeTab == 0,
                    onClick = { activeTab = 0 },
                    modifier = Modifier.weight(1f)
                )
                TabButton(
                    title = "📋 My Bets (${userBets.size})",
                    isSelected = activeTab == 1,
                    onClick = { activeTab = 1 },
                    modifier = Modifier.weight(1f)
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            // 4 SEPARATE MARKET MODULES: MIAMI, VEGAS, PARIS, DUBAI
            MarketSelectorRow(
                selectedMarket = selectedMarket,
                onMarketSelected = { market ->
                    viewModel.selectMarket(market)
                }
            )

            Spacer(modifier = Modifier.height(12.dp))
        }

        if (activeTab == 0) {
            // Live Round Arena Card
            item {
                RoundStatusCard(
                    round = currentRound,
                    market = selectedMarket,
                    secondsRemainingFlow = viewModel.secondsRemaining,
                    isBettingOpen = isBettingOpen,
                    latestResult = latestResult,
                    lastCompletedRound = recentRounds.firstOrNull(),
                    onVerifyClick = { showProvablyFairDialog = true },
                    onRestartClick = { viewModel.restartEngine() }
                )
                Spacer(modifier = Modifier.height(14.dp))
            }

            // Trend Roadmap (Previous 15 rounds of this market)
            item {
                RoadmapSection(recentRounds = recentRounds, market = selectedMarket)
                Spacer(modifier = Modifier.height(14.dp))
            }



            if (!isBettingOpen) {
                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = NeonRed.copy(alpha = 0.16f),
                        border = borderStroke(1.2.dp, NeonRed.copy(alpha = 0.85f)),
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("betting_locked_notice")
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ) {
                            Icon(
                                imageVector = Icons.Default.Lock,
                                contentDescription = "Betting Locked",
                                tint = NeonRed,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = "BETTING LOCKED • Buttons re-enable after Result Draw",
                                color = Color.White,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.ExtraBold
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(10.dp))
                }
            }

            // Color Selection Pads (RED, VIOLET, GREEN) — Disabled during Bet Lock
            item {
                ColorSelectionPads(
                    activeBets = activeBetsMap,
                    redMultiplier = gameConfig?.redMultiplier ?: 2.0,
                    violetMultiplier = gameConfig?.violetMultiplier ?: 3.0,
                    greenMultiplier = gameConfig?.greenMultiplier ?: 2.0,
                    enabled = isBettingOpen,
                    onToggleColor = { color ->
                        if (!isBettingOpen) return@ColorSelectionPads
                        val existingBet = activeBetsMap[color]
                        if (existingBet != null) {
                            viewModel.toggleBet(BetType.COLOR, color, existingBet.amount)
                        } else {
                            pendingBetTarget = Pair(BetType.COLOR, color)
                        }
                    }
                )
                Spacer(modifier = Modifier.height(10.dp))
            }

            // Big / Small Selection Pads (BIG: 5,6,7,8,9 | SMALL: 0,1,2,3,4) — Disabled during Bet Lock
            item {
                BigSmallSelectionPads(
                    activeBets = activeBetsMap,
                    bigMultiplier = 2.0,
                    smallMultiplier = 2.0,
                    enabled = isBettingOpen,
                    onToggleSelection = { selection ->
                        if (!isBettingOpen) return@BigSmallSelectionPads
                        val existingBet = activeBetsMap[selection]
                        if (existingBet != null) {
                            viewModel.toggleBet(BetType.BIG_SMALL, selection, existingBet.amount)
                        } else {
                            pendingBetTarget = Pair(BetType.BIG_SMALL, selection)
                        }
                    }
                )
                Spacer(modifier = Modifier.height(12.dp))
            }

            // Number Grid Selection (0 to 9) — Disabled during Bet Lock
            item {
                NumberGridSelection(
                    activeBets = activeBetsMap,
                    numberMultiplier = gameConfig?.numberMultiplier ?: 9.0,
                    enabled = isBettingOpen,
                    onToggleNumber = { num ->
                        if (!isBettingOpen) return@NumberGridSelection
                        val selStr = "$num"
                        val existingBet = activeBetsMap[selStr]
                        if (existingBet != null) {
                            viewModel.toggleBet(BetType.NUMBER, selStr, existingBet.amount)
                        } else {
                            pendingBetTarget = Pair(BetType.NUMBER, selStr)
                        }
                    }
                )
                Spacer(modifier = Modifier.height(14.dp))
            }

            // IN-BETWEEN LIST: Current Round Placed Bets
            item {
                CurrentRoundPlacedBetsSection(
                    activeBets = activeBetsMap,
                    isBettingOpen = isBettingOpen,
                    onCancelBet = { bet ->
                        if (!isBettingOpen) return@CurrentRoundPlacedBetsSection
                        val bType = when (bet.betType) {
                            BetType.NUMBER.name -> BetType.NUMBER
                            BetType.BIG_SMALL.name -> BetType.BIG_SMALL
                            else -> BetType.COLOR
                        }
                        viewModel.toggleBet(bType, bet.selection, bet.amount)
                    }
                )
                Spacer(modifier = Modifier.height(16.dp))
            }

            // 24-Hours Period Result Records for Active Market
            item {
                TwentyFourHourResultSection(recentRounds = recentRounds, market = selectedMarket)
                Spacer(modifier = Modifier.height(24.dp))
            }
        } else {
            // User Bets History Tab (90-Day Records + P&L + CSV Export)
            item {
                Surface(
                    shape = RoundedCornerShape(14.dp),
                    color = SurfaceDark,
                    border = borderStroke(1.dp, GoldAccent.copy(alpha = 0.4f)),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column {
                                Text(
                                    text = "90-Day Bet Records (${filteredBets.size})",
                                    color = TextPrimary,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 14.sp
                                )
                                Text(
                                    text = "Stored up to 90 days • All Markets",
                                    color = TextMuted,
                                    fontSize = 10.sp
                                )
                            }
                            OutlinedButton(
                                onClick = {
                                    val df = SimpleDateFormat("yyyyMMdd", Locale.ENGLISH).format(Date())
                                    csvLauncher.launch("ColourKing_${statementDays}Day_Bets_$df.csv")
                                },
                                shape = RoundedCornerShape(8.dp),
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                                border = borderStroke(1.dp, GoldAccent),
                                modifier = Modifier
                                    .height(34.dp)
                                    .testTag("download_bets_statement_btn")
                            ) {
                                Icon(
                                    imageVector = Icons.Default.Download,
                                    contentDescription = "Download Bet Statement CSV",
                                    tint = GoldAccent,
                                    modifier = Modifier.size(14.dp)
                                )
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("CSV Statement", color = GoldAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                            }
                        }

                        Spacer(modifier = Modifier.height(10.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = CardHighlight,
                                modifier = Modifier.weight(1f)
                            ) {
                                Column(modifier = Modifier.padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text("Wagered", color = TextMuted, fontSize = 10.sp)
                                    Text(
                                        text = MoneyUtils.formatCents(betSummary.totalBetWageredCents),
                                        color = GoldAccent,
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 12.sp
                                    )
                                }
                            }
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = CardHighlight,
                                modifier = Modifier.weight(1f)
                            ) {
                                Column(modifier = Modifier.padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text("Won Payout", color = TextMuted, fontSize = 10.sp)
                                    Text(
                                        text = MoneyUtils.formatCents(betSummary.totalBetWonCents),
                                        color = ElectricCyan,
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 12.sp
                                    )
                                }
                            }
                            val netPl = betSummary.netBetProfitLossCents
                            val plColor = if (netPl >= 0L) NeonGreen else NeonRed
                            val plSign = if (netPl >= 0L) "+" else "-"
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = CardHighlight,
                                modifier = Modifier.weight(1f)
                            ) {
                                Column(modifier = Modifier.padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text("Net Bet P&L", color = TextMuted, fontSize = 10.sp)
                                    Text(
                                        text = "$plSign${MoneyUtils.formatCents(kotlin.math.abs(netPl))}",
                                        color = plColor,
                                        fontWeight = FontWeight.ExtraBold,
                                        fontSize = 12.sp
                                    )
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            listOf(90 to "90 Days", 30 to "30 Days", 7 to "7 Days").forEach { (d, label) ->
                                val active = statementDays == d
                                    Box(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(if (active) ElectricCyan else CardHighlight)
                                        .clickable {
                                            betSlipsPage = 0
                                            viewModel.setStatementDays(d)
                                        }
                                        .padding(horizontal = 10.dp, vertical = 6.dp)
                                ) {
                                    Text(
                                        text = label,
                                        color = if (active) ObsidianBg else TextSecondary,
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 11.sp
                                    )
                                }
                            }
                        }
                    }
                }
                Spacer(modifier = Modifier.height(10.dp))

                MarketBetsFilterRow(
                    selectedFilter = betFilterMarketId,
                    onSelectFilter = {
                        betFilterMarketId = it
                        betSlipsPage = 0
                    }
                )
                Spacer(modifier = Modifier.height(10.dp))
            }

            if (filteredBets.isEmpty()) {
                item {
                    val filterName = if (betFilterMarketId == "ALL") "any market" else GameMarkets.getById(betFilterMarketId).name
                    EmptyStateCard(
                        icon = Icons.Default.ReceiptLong,
                        title = "No Bets in $filterName ($statementDays Days)",
                        subtitle = "Select a color or number in the Live Arena to start placing bets!"
                    )
                }
            } else {
                items(pagedBets, key = { it.id }) { bet ->
                    BetHistoryItem(bet = bet, round = allRoundsMap[bet.roundId])
                    Spacer(modifier = Modifier.height(8.dp))
                }
                item {
                    val startNum = safeBetSlipsPage * betsPerPage + 1
                    val endNum = safeBetSlipsPage * betsPerPage + pagedBets.size
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(SurfaceDark)
                            .border(1.dp, CardBorder, RoundedCornerShape(12.dp))
                            .padding(horizontal = 10.dp, vertical = 8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedButton(
                            onClick = { if (safeBetSlipsPage > 0) betSlipsPage = safeBetSlipsPage - 1 },
                            enabled = safeBetSlipsPage > 0,
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = TextPrimary),
                            border = borderStroke(1.dp, if (safeBetSlipsPage > 0) ElectricCyan else CardBorder),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier
                                .defaultMinSize(minHeight = 48.dp)
                                .testTag("bet_slips_prev_btn")
                        ) {
                            Text(text = "◀ Prev 10", fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }

                        Text(
                            text = "$startNum-$endNum / ${filteredBets.size}\nPage ${safeBetSlipsPage + 1}/$totalBetPages",
                            color = GoldAccent,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            fontFamily = FontFamily.Monospace,
                            textAlign = TextAlign.Center
                        )

                        OutlinedButton(
                            onClick = { if (safeBetSlipsPage < totalBetPages - 1) betSlipsPage = safeBetSlipsPage + 1 },
                            enabled = safeBetSlipsPage < totalBetPages - 1,
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = TextPrimary),
                            border = borderStroke(1.dp, if (safeBetSlipsPage < totalBetPages - 1) ElectricCyan else CardBorder),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier
                                .defaultMinSize(minHeight = 48.dp)
                                .testTag("bet_slips_next_btn")
                        ) {
                            Text(text = "Next 10 ▶", fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
            item { Spacer(modifier = Modifier.height(30.dp)) }
        }
    }

    BetPhaseOverlayBanner(
        isLocked = phaseBannerLocked == true,
        visible = phaseBannerLocked != null,
        marketName = selectedMarket.name,
        periodNumber = currentRound?.roundNumber?.toString() ?: "---",
        onDismiss = { phaseBannerLocked = null },
        modifier = Modifier
            .align(Alignment.TopCenter)
            .padding(horizontal = 14.dp, vertical = 10.dp)
    )
    }
}

@Composable
fun BetPhaseOverlayBanner(
    isLocked: Boolean,
    visible: Boolean,
    marketName: String,
    periodNumber: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier
) {
    val accent = if (isLocked) NeonRed else NeonGreen
    val infiniteTransition = rememberInfiniteTransition(label = "phasePulse")
    val pulse by infiniteTransition.animateFloat(
        initialValue = 0.96f,
        targetValue = 1.03f,
        animationSpec = infiniteRepeatable(
            animation = tween(550, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "phaseScale"
    )

    AnimatedVisibility(
        visible = visible,
        enter = slideInVertically(initialOffsetY = { -it }) + fadeIn(animationSpec = tween(250)),
        exit = slideOutVertically(targetOffsetY = { -it }) + fadeOut(animationSpec = tween(250)),
        modifier = modifier
    ) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = if (isLocked) Color(0xFF280B12) else Color(0xFF0A261A),
            border = borderStroke(2.dp, accent),
            shadowElevation = 14.dp,
            modifier = Modifier
                .fillMaxWidth()
                .scale(pulse)
                .clickable { onDismiss() }
                .testTag("bet_phase_banner")
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(accent.copy(alpha = 0.22f))
                        .border(1.5.dp, accent, CircleShape),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = if (isLocked) "🔒" else "🟢",
                        fontSize = 22.sp
                    )
                }
                Spacer(modifier = Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = if (isLocked) "BETTING LOCKED (5s ALERT)" else "BETTING OPEN — DRAW DECLARED!",
                        color = accent,
                        fontWeight = FontWeight.Black,
                        fontSize = 13.sp,
                        letterSpacing = 0.5.sp
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = if (isLocked)
                            "$marketName Period #$periodNumber is locked. Awaiting official draw..."
                        else
                            "$marketName Period #$periodNumber is live! Place your bets now.",
                        color = Color.White,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }
            }
        }
    }
}

@Composable
fun MarketSelectorRow(
    selectedMarket: MarketInfo,
    onMarketSelected: (MarketInfo) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(SurfaceDark)
            .border(1.dp, CardBorder, RoundedCornerShape(14.dp))
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        GameMarkets.ALL.forEach { market ->
            val isSelected = market.id == selectedMarket.id
            val accentColor = Color(market.accentColorHex)

            Box(
                modifier = Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(10.dp))
                    .background(
                        if (isSelected) accentColor.copy(alpha = 0.22f) else Color.Transparent
                    )
                    .border(
                        width = if (isSelected) 1.5.dp else 0.dp,
                        color = if (isSelected) accentColor else Color.Transparent,
                        shape = RoundedCornerShape(10.dp)
                    )
                    .clickable { onMarketSelected(market) }
                    .padding(vertical = 10.dp, horizontal = 2.dp)
                    .testTag("market_tab_${market.code.lowercase()}"),
                contentAlignment = Alignment.Center
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        Text(
                            text = market.emoji,
                            fontSize = 12.sp
                        )
                        Spacer(modifier = Modifier.width(3.dp))
                        Text(
                            text = market.name,
                            color = if (isSelected) accentColor else TextMuted,
                            fontWeight = if (isSelected) FontWeight.Black else FontWeight.Bold,
                            fontSize = 11.sp,
                            letterSpacing = 0.5.sp
                        )
                    }
                    if (isSelected) {
                        Spacer(modifier = Modifier.height(2.dp))
                        Box(
                            modifier = Modifier
                                .width(18.dp)
                                .height(2.dp)
                                .clip(RoundedCornerShape(1.dp))
                                .background(accentColor)
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun MarketBetsFilterRow(
    selectedFilter: String,
    onSelectFilter: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        // "ALL" option
        val isAll = selectedFilter == "ALL"
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = if (isAll) GoldAccent.copy(alpha = 0.2f) else SurfaceDark,
            border = borderStroke(1.dp, if (isAll) GoldAccent else CardBorder),
            modifier = Modifier.clickable { onSelectFilter("ALL") }
        ) {
            Text(
                text = "🌐 All Markets",
                color = if (isAll) GoldAccent else TextMuted,
                fontWeight = if (isAll) FontWeight.Bold else FontWeight.Normal,
                fontSize = 11.sp,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
            )
        }

        // 4 individual markets
        GameMarkets.ALL.forEach { market ->
            val isSelected = selectedFilter == market.id
            val mColor = Color(market.accentColorHex)
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = if (isSelected) mColor.copy(alpha = 0.25f) else SurfaceDark,
                border = borderStroke(1.dp, if (isSelected) mColor else CardBorder),
                modifier = Modifier.clickable { onSelectFilter(market.id) }
            ) {
                Text(
                    text = "${market.emoji} ${market.name}",
                    color = if (isSelected) mColor else TextMuted,
                    fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                    fontSize = 11.sp,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                )
            }
        }
    }
}

@Composable
fun TabButton(
    title: String,
    isSelected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .background(if (isSelected) CardHighlight else Color.Transparent)
            .clickable { onClick() }
            .padding(vertical = 10.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = title,
            color = if (isSelected) GoldAccent else TextSecondary,
            fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
            fontSize = 13.sp
        )
    }
}

@Composable
fun RoundStatusCard(
    round: GameRoundEntity?,
    market: MarketInfo = GameMarkets.MIAMI,
    secondsRemainingFlow: StateFlow<Int>,
    isBettingOpen: Boolean,
    latestResult: RoundResult? = null,
    lastCompletedRound: GameRoundEntity? = null,
    onVerifyClick: () -> Unit,
    onRestartClick: () -> Unit
) {
    val secondsRemaining by secondsRemainingFlow.collectAsState()
    val isClosing = secondsRemaining in 1..30
    val pulseScale = if (secondsRemaining in 1..5) (if (secondsRemaining % 2 == 0) 1.06f else 1.0f) else 1f
    val marketAccentColor = Color(market.accentColorHex)

    Surface(
        shape = RoundedCornerShape(18.dp),
        color = SurfaceDark,
        border = borderStroke(
            1.dp,
            if (!isBettingOpen) NeonRed.copy(alpha = 0.8f) else CardBorder
        ),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // Top Round header with Market Tag & Identity
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Surface(
                            shape = RoundedCornerShape(6.dp),
                            color = marketAccentColor.copy(alpha = 0.2f),
                            border = borderStroke(1.dp, marketAccentColor.copy(alpha = 0.6f))
                        ) {
                            Text(
                                text = "${market.emoji} ${market.name}",
                                color = marketAccentColor,
                                fontWeight = FontWeight.Black,
                                fontSize = 11.sp,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "PERIOD #${round?.roundNumber ?: "---"}",
                            color = GoldAccent,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 13.sp,
                            letterSpacing = 0.6.sp
                        )
                    }
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "${market.tagline} • Provably Fair SHA-256",
                        color = ElectricCyan,
                        fontSize = 10.sp
                    )
                }

                Row(verticalAlignment = Alignment.CenterVertically) {
                    Surface(
                        shape = RoundedCornerShape(20.dp),
                        color = if (isBettingOpen) NeonGreen.copy(alpha = 0.2f) else NeonRed.copy(alpha = 0.2f),
                        border = borderStroke(1.dp, if (isBettingOpen) NeonGreen else NeonRed)
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(6.dp)
                                    .clip(CircleShape)
                                    .background(if (isBettingOpen) NeonGreen else NeonRed)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = if (isBettingOpen) "Bet Open" else "Bet Close",
                                color = if (isBettingOpen) NeonGreen else NeonRed,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(14.dp))

            // Center: Big Animated Countdown & Result Reveal
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceAround,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Countdown Ring (3 Mins MM:SS format)
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    val minutes = secondsRemaining / 60
                    val seconds = secondsRemaining % 60
                    val timerDisplay = "%02d:%02d".format(minutes, seconds)

                    Box(
                        modifier = Modifier
                            .size(84.dp)
                            .graphicsLayer {
                                scaleX = pulseScale
                                scaleY = pulseScale
                            }
                            .clip(CircleShape)
                            .background(
                                Brush.radialGradient(
                                    colors = if (secondsRemaining <= 30)
                                        listOf(NeonRed.copy(alpha = 0.3f), Color.Transparent)
                                    else listOf(ElectricCyan.copy(alpha = 0.2f), Color.Transparent)
                                )
                            )
                            .border(
                                width = 3.dp,
                                color = if (secondsRemaining <= 30) NeonRed else ElectricCyan,
                                shape = CircleShape
                            ),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = timerDisplay,
                            color = if (secondsRemaining <= 30) NeonRed else TextPrimary,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 21.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = if (secondsRemaining <= 30) "Bet Close" else "Time Left (3m)",
                        color = if (secondsRemaining <= 30) NeonRed else TextSecondary,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }

                // Divider
                Box(
                    modifier = Modifier
                        .height(60.dp)
                        .width(1.dp)
                        .background(CardBorder)
                )

                // Current / Latest Result Reveal
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    val displayResultNumber = round?.resultNumber ?: latestResult?.number ?: lastCompletedRound?.resultNumber
                    val displayResultColor = round?.resultColor ?: latestResult?.colorString ?: lastCompletedRound?.resultColor
                    val isRevealingNow = round?.resultNumber != null
                    val lastPeriodNumber: String? = if (isRevealingNow && round?.roundNumber != null) {
                        "#${round.roundNumber}"
                    } else if (lastCompletedRound?.roundNumber != null) {
                        "#${lastCompletedRound.roundNumber}"
                    } else null

                    if (displayResultNumber != null && displayResultColor != null) {
                        val numColor = when {
                            displayResultColor.contains("VIOLET", ignoreCase = true) -> NeonViolet
                            displayResultColor.equals("RED", ignoreCase = true) -> NeonRed
                            displayResultColor.equals("GREEN", ignoreCase = true) -> NeonGreen
                            else -> NeonGreen
                        }
                        Box(
                            modifier = Modifier
                                .size(64.dp)
                                .clip(CircleShape)
                                .background(
                                    if (displayResultColor.contains("VIOLET")) {
                                        Brush.linearGradient(
                                            colors = if (displayResultColor.contains("RED"))
                                                listOf(NeonRed, NeonViolet)
                                            else
                                                listOf(NeonGreen, NeonViolet)
                                        )
                                    } else {
                                        Brush.radialGradient(listOf(numColor, numColor.copy(alpha = 0.85f)))
                                    }
                                )
                                .border(2.5.dp, Color.White, CircleShape),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "$displayResultNumber",
                                color = Color.White,
                                fontWeight = FontWeight.Black,
                                fontSize = 30.sp
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = if (isRevealingNow) "NEW RESULT" else "Last: ${displayResultColor.replace("_", " + ")}",
                            color = if (isRevealingNow) NeonGreen else numColor,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp
                        )
                        if (lastPeriodNumber != null) {
                            Text(
                                text = lastPeriodNumber,
                                color = TextMuted,
                                fontSize = 9.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    } else {
                        Box(
                            modifier = Modifier
                                .size(64.dp)
                                .clip(CircleShape)
                                .background(CardHighlight)
                                .border(1.dp, CardBorder, CircleShape),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "🎲",
                                fontSize = 28.sp
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Spinning...",
                            color = TextMuted,
                            fontSize = 11.sp
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(10.dp))
            // Server Seed hash link
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onVerifyClick() },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                Icon(
                    imageVector = Icons.Default.Lock,
                    contentDescription = null,
                    tint = TextMuted,
                    modifier = Modifier.size(12.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = "Seed Hash: ${round?.serverSeedHash?.take(16) ?: ""}...",
                    color = TextMuted,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = "Verify ↗",
                    color = ElectricCyan,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}



@Composable
fun RoadmapSection(recentRounds: List<GameRoundEntity>, market: MarketInfo = GameMarkets.MIAMI) {
    var graphMode by remember { mutableStateOf(0) } // 0: Area Wave, 1: Candlestick
    var selectedPointIndex by remember { mutableStateOf<Int?>(null) }
    val marketAccentColor = Color(market.accentColorHex)

    // Take last 15 rounds and display chronologically (oldest -> newest on right)
    val displayRounds = remember(recentRounds) {
        val list = recentRounds.take(15).reversed()
        if (list.size >= 3) list
        else {
            // Provide smooth baseline if fewer than 3 rounds recorded yet
            val defaultNumbers = listOf(3, 7, 2, 8, 5, 1, 9, 4, 6, 0, 8, 2, 7, 5, 3)
            defaultNumbers.mapIndexed { idx, num ->
                GameRoundEntity(
                    roundId = "mock_${market.code}_$idx",
                    gameId = market.id,
                    tenantId = "tenant_apex",
                    roundNumber = 202610010000L + idx,
                    startTime = System.currentTimeMillis() - ((15 - idx) * 30000L),
                    bettingCloseTime = System.currentTimeMillis() - ((15 - idx) * 30000L) + 25000L,
                    resultTime = System.currentTimeMillis() - ((15 - idx) * 30000L) + 30000L,
                    status = "COMPLETED",
                    resultNumber = num,
                    resultColor = when (num) {
                        0, 5 -> "VIOLET"
                        1, 3, 7, 9 -> "GREEN"
                        else -> "RED"
                    },
                    serverSeedHash = "seed_hash_$idx",
                    nonce = idx.toLong()
                )
            }
        }
    }

    val latestRound = displayRounds.lastOrNull()
    val previousRound = if (displayRounds.size >= 2) displayRounds[displayRounds.size - 2] else null
    val latestNum = latestRound?.resultNumber ?: 5
    val prevNum = previousRound?.resultNumber ?: 5
    val isBullish = latestNum >= prevNum
    val diffPoints = latestNum - prevNum
    val pctChange = if (prevNum != 0) (diffPoints.toDouble() / prevNum * 100.0) else (diffPoints * 10.0)

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            // Header Row: Live Stock Ticker & Market Value
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        // Glowing Green Live Indicator Dot
                        Box(
                            modifier = Modifier
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(NeonGreen)
                                .border(1.dp, GoldAccent.copy(alpha = 0.5f), CircleShape)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "${market.emoji} ${market.name} MARKET TREND",
                            color = marketAccentColor,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.ExtraBold,
                            letterSpacing = 1.0.sp
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(4.dp))
                                .background(CardHighlight)
                                .padding(horizontal = 5.dp, vertical = 1.5.dp)
                        ) {
                            Text(
                                text = "INDEX: APX-9",
                                color = ElectricCyan,
                                fontSize = 9.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "15-Round Volatility Curve & Heikin Trajectory",
                        color = TextMuted,
                        fontSize = 11.sp
                    )
                }

                // Current Index Level & % Change badge
                Column(horizontalAlignment = Alignment.End) {
                    Text(
                        text = "${(1000 + latestNum * 100)}.00 PTS",
                        color = TextPrimary,
                        fontSize = 15.sp,
                        fontWeight = FontWeight.Black,
                        fontFamily = FontFamily.Monospace
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = if (isBullish) "▲ +${"%.1f".format(Math.abs(pctChange))}%" else "▼ -${"%.1f".format(Math.abs(pctChange))}%",
                            color = if (isBullish) NeonGreen else NeonRed,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.ExtraBold
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text(
                            text = "(${latestRound?.resultColor ?: "GREEN"})",
                            color = when (latestRound?.resultColor) {
                                "RED" -> NeonRed
                                "VIOLET", "RED_VIOLET", "GREEN_VIOLET" -> NeonViolet
                                else -> NeonGreen
                            },
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            // Chart View Mode Switcher + Stats Ribbon
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                        // High / Low / Count stats
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            val maxVal = displayRounds.maxOfOrNull { it.resultNumber ?: 0 } ?: 9
                            val minVal = displayRounds.minOfOrNull { it.resultNumber ?: 0 } ?: 0
                            val avgVal = displayRounds.mapNotNull { it.resultNumber }.average()

                            Text(
                                text = "H: $maxVal  L: $minVal  Avg: ${"%.1f".format(if (avgVal.isNaN()) 5.0 else avgVal)}",
                                color = TextSecondary,
                                fontSize = 10.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }

                        // Mode Switcher Pills: Area Wave vs Candlestick
                        Row(
                            modifier = Modifier
                                .clip(RoundedCornerShape(8.dp))
                                .background(CardHighlight)
                                .padding(2.dp)
                        ) {
                            Box(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(if (graphMode == 0) GoldAccent else Color.Transparent)
                                    .clickable { graphMode = 0 }
                                    .padding(horizontal = 8.dp, vertical = 4.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    text = "📈 Spline Wave",
                                    color = if (graphMode == 0) ObsidianBg else TextSecondary,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 10.sp
                                )
                            }

                            Box(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(if (graphMode == 1) ElectricCyan else Color.Transparent)
                                    .clickable { graphMode = 1 }
                                    .padding(horizontal = 8.dp, vertical = 4.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    text = "🕯️ Candlesticks",
                                    color = if (graphMode == 1) ObsidianBg else TextSecondary,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 10.sp
                                )
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    // Interactive Point Tooltip (if tapped)
                    if (selectedPointIndex != null && selectedPointIndex!! in displayRounds.indices) {
                        val round = displayRounds[selectedPointIndex!!]
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = ObsidianBg,
                            border = borderStroke(1.dp, ElectricCyan.copy(alpha = 0.7f)),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp)
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 10.dp, vertical = 6.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = "Period #${round.roundNumber} • Result: ${round.resultNumber} (${round.resultColor})",
                                    color = ElectricCyan,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
                                )
                                Text(
                                    text = "Index: ${(1000 + (round.resultNumber ?: 0) * 100)} pts",
                                    color = GoldAccent,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                    }

                    // Animated Canvas Live Chart
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(175.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .background(ObsidianBg)
                            .border(0.8.dp, CardBorder, RoundedCornerShape(12.dp))
                            .padding(vertical = 8.dp, horizontal = 4.dp)
                    ) {
                        Canvas(
                            modifier = Modifier
                                .fillMaxSize()
                                .clickable {
                                    // Cycle selected point for inspection
                                    selectedPointIndex = if (selectedPointIndex == null) displayRounds.size - 1 else ((selectedPointIndex!! + 1) % displayRounds.size)
                                }
                        ) {
                            val canvasWidth = size.width
                            val canvasHeight = size.height

                            val leftPad = 28f
                            val rightPad = 52f
                            val topPad = 18f
                            val bottomPad = 22f

                            val chartWidth = canvasWidth - leftPad - rightPad
                            val chartHeight = canvasHeight - topPad - bottomPad

                            // 1. Draw Grid Lines (Horizontal Levels: 9, 6, 3, 0)
                            val gridLevels = listOf(9, 6, 3, 0)
                            val dashEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 8f), 0f)

                            gridLevels.forEach { level ->
                                val y = topPad + ((9 - level) / 9f) * chartHeight
                                drawLine(
                                    color = CardBorder.copy(alpha = 0.5f),
                                    start = Offset(leftPad, y),
                                    end = Offset(canvasWidth - rightPad, y),
                                    strokeWidth = 1f,
                                    pathEffect = dashEffect
                                )
                            }

                            if (displayRounds.isEmpty()) return@Canvas

                            // 2. Calculate coordinates for points
                            val count = displayRounds.size
                            val stepX = if (count > 1) chartWidth / (count - 1) else chartWidth

                            val points = displayRounds.mapIndexed { idx, r ->
                                val num = (r.resultNumber ?: 5).coerceIn(0, 9)
                                val x = leftPad + idx * stepX
                                val y = topPad + ((9 - num) / 9f) * chartHeight
                                Offset(x, y)
                            }

                            if (graphMode == 0) {
                                // MODE 0: AREA SPLINE WAVE GRAPH
                                // Construct smooth cubic Bezier path
                                val splinePath = Path()
                                splinePath.moveTo(points[0].x, points[0].y)

                                for (i in 1 until points.size) {
                                    val prev = points[i - 1]
                                    val curr = points[i]
                                    val cX1 = prev.x + (curr.x - prev.x) / 2f
                                    val cY1 = prev.y
                                    val cX2 = prev.x + (curr.x - prev.x) / 2f
                                    val cY2 = curr.y
                                    splinePath.cubicTo(cX1, cY1, cX2, cY2, curr.x, curr.y)
                                }

                                // Fill area below curve with vertical gradient
                                val areaPath = Path()
                                areaPath.addPath(splinePath)
                                areaPath.lineTo(points.last().x, topPad + chartHeight)
                                areaPath.lineTo(points.first().x, topPad + chartHeight)
                                areaPath.close()

                                val areaGradient = Brush.verticalGradient(
                                    colors = listOf(
                                        if (isBullish) NeonGreen.copy(alpha = 0.38f) else NeonRed.copy(alpha = 0.38f),
                                        ElectricCyan.copy(alpha = 0.12f),
                                        Color.Transparent
                                    ),
                                    startY = topPad,
                                    endY = topPad + chartHeight
                                )
                                drawPath(areaPath, brush = areaGradient)

                                // Draw Neon Spline Line
                                drawPath(
                                    path = splinePath,
                                    color = if (isBullish) NeonGreen else NeonRed,
                                    style = Stroke(width = 3.2.dp.toPx(), cap = StrokeCap.Round)
                                )

                                // Draw Point Halo & Data Dots
                                points.forEachIndexed { idx, pt ->
                                    val r = displayRounds[idx]
                                    val dotColor = when (r.resultColor) {
                                        "RED" -> NeonRed
                                        "VIOLET", "RED_VIOLET", "GREEN_VIOLET" -> NeonViolet
                                        else -> NeonGreen
                                    }

                                    // Outer halo
                                    drawCircle(
                                        color = dotColor.copy(alpha = 0.35f),
                                        radius = 6.dp.toPx(),
                                        center = pt
                                    )
                                    // Inner core
                                    drawCircle(
                                        color = dotColor,
                                        radius = 3.5.dp.toPx(),
                                        center = pt
                                    )
                                    // Center white specular
                                    drawCircle(
                                        color = Color.White,
                                        radius = 1.5.dp.toPx(),
                                        center = pt
                                    )
                                }
                            } else {
                                // MODE 1: CANDLESTICK CHART WITH MOVING AVERAGE
                                val candleWidth = 14f

                                // Draw candlesticks for each round
                                displayRounds.forEachIndexed { idx, round ->
                                    val pt = points[idx]
                                    val closeVal = (round.resultNumber ?: 5).toFloat()
                                    val openVal = if (idx > 0) (displayRounds[idx - 1].resultNumber ?: 5).toFloat() else closeVal
                                    val highVal = Math.min(9f, Math.max(openVal, closeVal) + 0.6f)
                                    val lowVal = Math.max(0f, Math.min(openVal, closeVal) - 0.6f)

                                    val openY = topPad + ((9 - openVal) / 9f) * chartHeight
                                    val closeY = topPad + ((9 - closeVal) / 9f) * chartHeight
                                    val highY = topPad + ((9 - highVal) / 9f) * chartHeight
                                    val lowY = topPad + ((9 - lowVal) / 9f) * chartHeight

                                    val candleBullish = closeVal >= openVal
                                    val candleColor = if (candleBullish) NeonGreen else NeonRed

                                    // Upper and lower wick line
                                    drawLine(
                                        color = candleColor,
                                        start = Offset(pt.x, highY),
                                        end = Offset(pt.x, lowY),
                                        strokeWidth = 1.5.dp.toPx()
                                    )

                                    // Candle Body
                                    val topY = Math.min(openY, closeY)
                                    val bodyHeight = Math.max(4.dp.toPx(), Math.abs(closeY - openY))
                                    drawRect(
                                        color = candleColor,
                                        topLeft = Offset(pt.x - candleWidth / 2, topY),
                                        size = Size(candleWidth, bodyHeight)
                                    )
                                }

                                // 5-Period Moving Average (SMA) Line running through candles
                                val smaPoints = mutableListOf<Offset>()
                                for (i in 0 until displayRounds.size) {
                                    val window = displayRounds.subList(Math.max(0, i - 4), i + 1)
                                    val avg = window.mapNotNull { it.resultNumber }.average().toFloat()
                                    val avgY = topPad + ((9 - avg) / 9f) * chartHeight
                                    smaPoints.add(Offset(points[i].x, avgY))
                                }

                                if (smaPoints.size > 1) {
                                    val smaPath = Path()
                                    smaPath.moveTo(smaPoints[0].x, smaPoints[0].y)
                                    for (i in 1 until smaPoints.size) {
                                        smaPath.lineTo(smaPoints[i].x, smaPoints[i].y)
                                    }
                                    drawPath(
                                        path = smaPath,
                                        color = GoldAccent,
                                        style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round)
                                    )
                                }
                            }

                            // 3. Animated Live Pulsing Price Line at Latest Point (Rightmost)
                            val lastPt = points.last()
                            val latestDotColor = if (isBullish) NeonGreen else NeonRed

                            // Sleek radar glow rings
                            drawCircle(
                                color = latestDotColor.copy(alpha = 0.22f),
                                radius = 10.dp.toPx(),
                                center = lastPt
                            )
                            drawCircle(
                                color = latestDotColor.copy(alpha = 0.45f),
                                radius = 6.dp.toPx(),
                                center = lastPt
                            )

                            // Horizontal dashed current price line across to the right edge
                            drawLine(
                                color = latestDotColor.copy(alpha = 0.8f),
                                start = lastPt,
                                end = Offset(canvasWidth, lastPt.y),
                                strokeWidth = 1.2.dp.toPx(),
                                pathEffect = dashEffect
                            )

                            // Solid center head
                            drawCircle(
                                color = Color.White,
                                radius = 4.5.dp.toPx(),
                                center = lastPt
                            )
                            drawCircle(
                                color = latestDotColor,
                                radius = 3.dp.toPx(),
                                center = lastPt
                            )
                        }

                        // Y-Axis Overlay Labels (Right edge)
                        Column(
                            modifier = Modifier
                                .fillMaxHeight()
                                .align(Alignment.TopEnd)
                                .padding(end = 4.dp),
                            verticalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text("9.0", color = TextMuted, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                            Text("6.0", color = TextMuted, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                            Text("3.0", color = TextMuted, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                            Text("0.0", color = TextMuted, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    // Bottom Horizontal Sequence Ribbon of Outcomes
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        displayRounds.forEachIndexed { idx, r ->
                            val isLast = idx == displayRounds.size - 1
                            val (bgColor, textColor) = when (r.resultColor) {
                                "RED" -> Pair(NeonRed, Color.White)
                                "GREEN" -> Pair(NeonGreen, ObsidianBg)
                                "VIOLET", "RED_VIOLET", "GREEN_VIOLET" -> Pair(NeonViolet, Color.White)
                                else -> Pair(NeonGreen, ObsidianBg)
                            }

                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                modifier = Modifier.clickable { selectedPointIndex = idx }
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(if (isLast) 32.dp else 26.dp)
                                        .clip(CircleShape)
                                        .background(bgColor)
                                        .border(
                                            width = if (isLast) 2.dp else 1.dp,
                                            color = if (isLast) Color.White else Color.White.copy(alpha = 0.3f),
                                            shape = CircleShape
                                        ),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        text = "${r.resultNumber ?: "?"}",
                                        color = textColor,
                                        fontWeight = FontWeight.Black,
                                        fontSize = if (isLast) 13.sp else 11.sp
                                    )
                                }
                                if (isLast) {
                                    Text(
                                        text = "NOW",
                                        color = GoldAccent,
                                        fontSize = 8.sp,
                                        fontWeight = FontWeight.ExtraBold
                                    )
                                } else {
                                    Text(
                                        text = "-${displayRounds.size - 1 - idx}R",
                                        color = TextMuted,
                                        fontSize = 8.sp,
                                        fontFamily = FontFamily.Monospace
                                    )
                                }
                            }
                        }
                    }
        }
    }
}

@Composable
fun BetPlacementDialog(
    betType: BetType,
    selection: String,
    multiplier: Double,
    availableBalanceCents: Long,
    isBettingOpen: Boolean = true,
    onConfirm: (amountCents: Long) -> Unit,
    onDismiss: () -> Unit
) {
    var selectedChipCents by remember { mutableStateOf(10000L) } // default ₹100
    var multiplierFactor by remember { mutableStateOf(1) }

    val totalBetCents = selectedChipCents * multiplierFactor
    val platformFeeCents = (totalBetCents * 3L) / 100L
    val netStakeCents = totalBetCents - platformFeeCents
    val potentialWinCents = (netStakeCents * multiplier).roundToLong()
    val hasSufficientBalance = availableBalanceCents >= totalBetCents && isBettingOpen

    val themeColor = when (selection.uppercase()) {
        "GREEN" -> NeonGreen
        "RED" -> NeonRed
        "VIOLET" -> NeonViolet
        "BIG" -> AmberGlow
        "SMALL" -> ElectricCyan
        "0", "5" -> NeonViolet
        "1", "3", "7", "9" -> NeonGreen
        else -> NeonRed
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Surface(
            shape = RoundedCornerShape(20.dp),
            color = SurfaceDark,
            border = borderStroke(1.5.dp, themeColor.copy(alpha = 0.8f)),
            modifier = Modifier
                .fillMaxWidth(0.92f)
                .padding(vertical = 16.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp)
            ) {
                // Header with Selection Identity & Multiplier
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .size(40.dp)
                                .clip(CircleShape)
                                .background(themeColor)
                                .border(1.5.dp, Color.White, CircleShape),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = if (betType == BetType.NUMBER) selection else selection.take(1),
                                color = if (themeColor == NeonGreen || themeColor == AmberGlow || themeColor == ElectricCyan) ObsidianBg else Color.White,
                                fontWeight = FontWeight.Black,
                                fontSize = 16.sp
                            )
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Column {
                            Text(
                                text = when (betType) {
                                    BetType.NUMBER -> "Number $selection"
                                    BetType.BIG_SMALL -> when (selection.uppercase()) {
                                        "BIG" -> "BIG (5, 6, 7, 8, 9)"
                                        "SMALL" -> "SMALL (0, 1, 2, 3, 4)"
                                        else -> selection
                                    }
                                    else -> selection
                                },
                                color = TextPrimary,
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 16.sp
                            )
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(4.dp))
                                        .background(themeColor.copy(alpha = 0.2f))
                                        .padding(horizontal = 6.dp, vertical = 2.dp)
                                ) {
                                    Text(
                                        text = "${multiplier}x Payout",
                                        color = themeColor,
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 11.sp
                                    )
                                }
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = if (betType == BetType.BIG_SMALL) "Big/Small Bet" else "${betType.name} Bet",
                                    color = TextMuted,
                                    fontSize = 11.sp
                                )
                            }
                        }
                    }

                    IconButton(
                        onClick = onDismiss,
                        modifier = Modifier.size(28.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Close,
                            contentDescription = "Close",
                            tint = TextMuted
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Select Chip Amount
                Text(
                    text = "Contract Money (Chip Amount)",
                    color = TextPrimary,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.height(8.dp))

                val chips = listOf(1000L, 5000L, 10000L, 50000L, 100000L, 500000L)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    chips.forEach { chipCents ->
                        CasinoChip(
                            amountCents = chipCents,
                            isSelected = selectedChipCents == chipCents,
                            onClick = { selectedChipCents = chipCents }
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Multiplier / Quantity Stepper & Quick Multipliers
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Multiplier (Number of Bets)",
                        color = TextPrimary,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold
                    )
                    // Stepper: [-] {count} [+]
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .background(CardHighlight)
                            .padding(2.dp)
                    ) {
                        IconButton(
                            onClick = { if (multiplierFactor > 1) multiplierFactor-- },
                            enabled = multiplierFactor > 1,
                            modifier = Modifier.size(32.dp)
                        ) {
                            Text(
                                text = "−",
                                color = if (multiplierFactor > 1) TextPrimary else TextMuted,
                                fontWeight = FontWeight.Bold,
                                fontSize = 18.sp
                            )
                        }
                        Text(
                            text = "${multiplierFactor}X",
                            color = GoldAccent,
                            fontWeight = FontWeight.Bold,
                            fontSize = 14.sp,
                            modifier = Modifier.padding(horizontal = 8.dp)
                        )
                        IconButton(
                            onClick = { if (multiplierFactor < 100) multiplierFactor++ },
                            modifier = Modifier.size(32.dp)
                        ) {
                            Text(
                                text = "+",
                                color = TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 18.sp
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))

                // Quick Multiplier Pills (1X, 2X, 5X, 10X, 20X)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    listOf(1, 2, 5, 10, 20).forEach { factor ->
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .clip(RoundedCornerShape(8.dp))
                                .background(if (multiplierFactor == factor) GoldAccent else CardHighlight)
                                .clickable { multiplierFactor = factor }
                                .padding(vertical = 8.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "${factor}X",
                                color = if (multiplierFactor == factor) ObsidianBg else TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 12.sp
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Calculation Summary (Total Bet Paid, 3% Platform Fee, Net Bet, Payout on Net)
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = ObsidianBg,
                    border = borderStroke(1.dp, CardBorder),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(text = "Total Bet Amount", color = TextSecondary, fontSize = 12.sp)
                            Text(
                                text = MoneyUtils.formatCents(totalBetCents),
                                color = GoldAccent,
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 14.sp
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(text = "Platform Fee (3%)", color = TextSecondary, fontSize = 12.sp)
                            Text(
                                text = "-${MoneyUtils.formatCents(platformFeeCents)}",
                                color = AmberGlow,
                                fontWeight = FontWeight.Bold,
                                fontSize = 12.sp
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(text = "Net Active Bet (97%)", color = TextSecondary, fontSize = 12.sp)
                            Text(
                                text = MoneyUtils.formatCents(netStakeCents),
                                color = ElectricCyan,
                                fontWeight = FontWeight.Bold,
                                fontSize = 13.sp
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(text = "Win Payout (${multiplier}x on Net)", color = TextSecondary, fontSize = 12.sp)
                            Text(
                                text = MoneyUtils.formatCents(potentialWinCents),
                                color = NeonGreen,
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 14.sp
                            )
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(text = "Available Balance", color = TextSecondary, fontSize = 12.sp)
                            Text(
                                text = MoneyUtils.formatCents(availableBalanceCents),
                                color = if (hasSufficientBalance) TextPrimary else NeonRed,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 12.sp
                            )
                        }
                    }
                }

                if (!isBettingOpen) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "🔒 Betting is locked for this round! Wait for result draw.",
                        color = NeonRed,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold
                    )
                } else if (availableBalanceCents < totalBetCents) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "⚠️ Insufficient wallet balance! Please reduce bet or deposit funds.",
                        color = NeonRed,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Action Buttons: Cancel and Confirm Bet
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    OutlinedButton(
                        onClick = onDismiss,
                        modifier = Modifier
                            .weight(1f)
                            .height(46.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = TextPrimary),
                        border = borderStroke(1.dp, CardBorder),
                        shape = RoundedCornerShape(12.dp)
                    ) {
                        Text(text = "Cancel", fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    }

                    Button(
                        onClick = {
                            if (hasSufficientBalance) {
                                onConfirm(totalBetCents)
                            }
                        },
                        enabled = hasSufficientBalance,
                        modifier = Modifier
                            .weight(1.4f)
                            .height(46.dp)
                            .testTag("confirm_bet_btn"),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = themeColor,
                            contentColor = if (themeColor == NeonGreen) ObsidianBg else Color.White
                        ),
                        shape = RoundedCornerShape(12.dp)
                    ) {
                        Text(
                            text = "Confirm Bet ${MoneyUtils.formatCents(totalBetCents)}",
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 13.sp
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun CurrentRoundPlacedBetsSection(
    activeBets: Map<String, BetEntity>,
    isBettingOpen: Boolean = true,
    onCancelBet: (BetEntity) -> Unit
) {
    val totalDeductedCents = activeBets.values.sumOf { it.amount }
    val timeFormat = remember { SimpleDateFormat("hh:mm:ss a", Locale.ENGLISH) }

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.ReceiptLong,
                        contentDescription = null,
                        tint = GoldAccent,
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = "Current Round Placed Bets",
                        color = TextPrimary,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(4.dp))
                            .background(if (activeBets.isNotEmpty()) NeonGreen.copy(alpha = 0.2f) else CardHighlight)
                            .padding(horizontal = 6.dp, vertical = 2.dp)
                    ) {
                        Text(
                            text = "${activeBets.size} Placed",
                            color = if (activeBets.isNotEmpty()) NeonGreen else TextMuted,
                            fontWeight = FontWeight.Bold,
                            fontSize = 10.sp
                        )
                    }
                }

                if (activeBets.isNotEmpty()) {
                    Text(
                        text = MoneyUtils.formatCents(totalDeductedCents),
                        color = GoldAccent,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.ExtraBold
                    )
                }
            }

            Text(
                text = if (isBettingOpen) "Live bet slips • Includes 3% platform fee breakdown & instant cancel" else "Round Locked • Waiting for official draw outcome",
                color = TextSecondary,
                fontSize = 11.sp
            )

            Spacer(modifier = Modifier.height(10.dp))

            if (activeBets.isEmpty()) {
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = ObsidianBg,
                    border = borderStroke(0.8.dp, CardBorder),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        Icon(
                            imageVector = Icons.Default.TouchApp,
                            contentDescription = null,
                            tint = ElectricCyan,
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "No pending bets. Tap any color or number above to bet!",
                            color = TextMuted,
                            fontSize = 12.sp
                        )
                    }
                }
            } else {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    activeBets.values.forEach { bet ->
                        PlacedBetItemCard(
                            bet = bet,
                            timeFormat = timeFormat,
                            isBettingOpen = isBettingOpen,
                            onCancel = { onCancelBet(bet) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun PlacedBetItemCard(
    bet: BetEntity,
    timeFormat: SimpleDateFormat,
    isBettingOpen: Boolean = true,
    onCancel: () -> Unit
) {
    val themeColor = when (bet.selection.uppercase()) {
        "GREEN" -> NeonGreen
        "RED" -> NeonRed
        "VIOLET" -> NeonViolet
        "BIG" -> AmberGlow
        "SMALL" -> ElectricCyan
        "0", "5" -> NeonViolet
        "1", "3", "7", "9" -> NeonGreen
        else -> NeonRed
    }
    val market = GameMarkets.getById(bet.gameId)
    val marketAccent = Color(market.accentColorHex)
    val periodNumber = bet.roundId.substringAfterLast("_")
    val feeCents = if (bet.platformFeeCents > 0L) bet.platformFeeCents else (bet.amount * 3L) / 100L
    val netCents = if (bet.netAmountCents > 0L) bet.netAmountCents else (bet.amount - feeCents)

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = ObsidianBg,
        border = borderStroke(1.dp, themeColor.copy(alpha = 0.55f)),
        tonalElevation = 4.dp,
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            // Top Strip: Selection Avatar + Name + Market/Period + Status Pill
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .size(38.dp)
                        .clip(CircleShape)
                        .background(themeColor)
                        .border(1.5.dp, Color.White, CircleShape),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = if (bet.betType == BetType.NUMBER.name) bet.selection else bet.selection.take(1),
                        color = if (themeColor == NeonGreen || themeColor == AmberGlow || themeColor == ElectricCyan) ObsidianBg else Color.White,
                        fontWeight = FontWeight.Black,
                        fontSize = 15.sp
                    )
                }

                Spacer(modifier = Modifier.width(10.dp))

                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = when (bet.betType) {
                                BetType.NUMBER.name -> "Number ${bet.selection}"
                                BetType.BIG_SMALL.name -> when (bet.selection.uppercase()) {
                                    "BIG" -> "BIG (5–9)"
                                    "SMALL" -> "SMALL (0–4)"
                                    else -> bet.selection
                                }
                                else -> bet.selection
                            },
                            color = TextPrimary,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 14.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Surface(
                            shape = RoundedCornerShape(5.dp),
                            color = GoldAccent.copy(alpha = 0.16f)
                        ) {
                            Text(
                                text = "${bet.multiplier}x",
                                color = GoldAccent,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.ExtraBold,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.5.dp)
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "${market.emoji} ${market.name} • #$periodNumber",
                        color = marketAccent,
                        fontWeight = FontWeight.Bold,
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = (if (isBettingOpen) AmberGlow else NeonRed).copy(alpha = 0.18f),
                    border = borderStroke(1.dp, (if (isBettingOpen) AmberGlow else NeonRed).copy(alpha = 0.75f))
                ) {
                    Text(
                        text = if (isBettingOpen) "● WAIT" else "🔒 LOCKED",
                        color = if (isBettingOpen) AmberGlow else NeonRed,
                        fontWeight = FontWeight.Black,
                        fontSize = 10.sp,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                    )
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            // 3-Column Metrics Grid: Paid | Fee & Net | Target Win
            Surface(
                shape = RoundedCornerShape(10.dp),
                color = SurfaceDark,
                border = borderStroke(0.8.dp, CardBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("BET PAID", color = TextMuted, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(2.dp))
                        Text(
                            text = MoneyUtils.formatCents(bet.amount),
                            color = TextPrimary,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 12.sp
                        )
                    }
                    Column(modifier = Modifier.weight(1.25f), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("3% FEE / NET", color = TextMuted, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(2.dp))
                        Text(
                            text = "${MoneyUtils.formatCents(feeCents)} / ${MoneyUtils.formatCents(netCents)}",
                            color = ElectricCyan,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp,
                            maxLines = 1
                        )
                    }
                    Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                        Text("TARGET WIN", color = TextMuted, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(2.dp))
                        Text(
                            text = "+${MoneyUtils.formatCents(bet.potentialPayout)}",
                            color = NeonGreen,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 12.sp
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Footer: Placed Timestamp & Cancel / Lock badge
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.AccessTime,
                        contentDescription = null,
                        tint = ElectricCyan,
                        modifier = Modifier.size(12.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = timeFormat.format(Date(bet.createdAt)),
                        color = ElectricCyan,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.SemiBold,
                        fontFamily = FontFamily.Monospace
                    )
                }

                if (isBettingOpen) {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = NeonRed.copy(alpha = 0.18f),
                        border = borderStroke(1.dp, NeonRed),
                        modifier = Modifier
                            .clickable { onCancel() }
                            .testTag("cancel_bet_${bet.selection}")
                    ) {
                        Text(
                            text = "✕ Cancel & Refund",
                            color = NeonRed,
                            fontWeight = FontWeight.Bold,
                            fontSize = 10.sp,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp)
                        )
                    }
                } else {
                    Text(
                        text = "Awaiting Official Draw...",
                        color = TextMuted,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Medium
                    )
                }
            }
        }
    }
}

@Composable
fun ColorSelectionPads(
    activeBets: Map<String, BetEntity>,
    redMultiplier: Double,
    violetMultiplier: Double,
    greenMultiplier: Double,
    enabled: Boolean = true,
    onToggleColor: (String) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .alpha(if (enabled) 1f else 0.45f),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        // GREEN (2x)
        ColorPad(
            name = "GREEN",
            multiplier = "${greenMultiplier}x",
            bgColor = NeonGreen,
            activeBet = activeBets["GREEN"],
            enabled = enabled,
            onClick = { onToggleColor("GREEN") },
            modifier = Modifier.weight(1f)
        )

        // VIOLET (3.0x)
        ColorPad(
            name = "VIOLET",
            multiplier = "${violetMultiplier}x",
            bgColor = NeonViolet,
            activeBet = activeBets["VIOLET"],
            enabled = enabled,
            onClick = { onToggleColor("VIOLET") },
            modifier = Modifier.weight(1f)
        )

        // RED (2x)
        ColorPad(
            name = "RED",
            multiplier = "${redMultiplier}x",
            bgColor = NeonRed,
            activeBet = activeBets["RED"],
            enabled = enabled,
            onClick = { onToggleColor("RED") },
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
fun ColorPad(
    name: String,
    multiplier: String,
    bgColor: Color,
    activeBet: BetEntity?,
    enabled: Boolean = true,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val isPlaced = activeBet != null

    Surface(
        shape = RoundedCornerShape(12.dp),
        color = if (isPlaced) bgColor.copy(alpha = 0.28f) else SurfaceDark,
        border = borderStroke(
            width = if (isPlaced) 2.5.dp else 1.5.dp,
            color = if (isPlaced) Color.White else bgColor
        ),
        modifier = modifier
            .height(68.dp)
            .clickable(enabled = enabled) { onClick() }
            .testTag("bet_color_${name.lowercase()}")
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(vertical = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text(
                text = name,
                color = if (isPlaced) Color.White else bgColor,
                fontWeight = FontWeight.ExtraBold,
                fontSize = 13.sp
            )
            Text(
                text = multiplier,
                color = if (isPlaced) GoldAccent else TextSecondary,
                fontWeight = FontWeight.SemiBold,
                fontSize = 10.sp
            )
            if (isPlaced) {
                Spacer(modifier = Modifier.height(2.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(GoldAccent)
                        .padding(horizontal = 6.dp, vertical = 1.dp)
                ) {
                    Text(
                        text = if (enabled) "₹${activeBet.amount / 100} ✕ Cancel" else "₹${activeBet.amount / 100} 🔒",
                        color = ObsidianBg,
                        fontWeight = FontWeight.Black,
                        fontSize = 9.sp
                    )
                }
            }
        }
    }
}

@Composable
fun BigSmallSelectionPads(
    activeBets: Map<String, BetEntity>,
    bigMultiplier: Double = 2.0,
    smallMultiplier: Double = 2.0,
    enabled: Boolean = true,
    onToggleSelection: (String) -> Unit
) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier
            .fillMaxWidth()
            .alpha(if (enabled) 1f else 0.45f)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(22.dp)
                            .clip(CircleShape)
                            .background(GoldAccent.copy(alpha = 0.2f)),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(text = "⚡", fontSize = 12.sp)
                    }
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = "Big / Small",
                        color = TextPrimary,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.ExtraBold
                    )
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(CardHighlight)
                        .padding(horizontal = 7.dp, vertical = 2.5.dp)
                ) {
                    Text(
                        text = "0–4 Small • 5–9 Big (2X)",
                        color = GoldAccent,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                BigSmallPad(
                    name = "BIG",
                    rangeLabel = "5, 6, 7, 8, 9",
                    multiplier = "${bigMultiplier}x",
                    accentColor = AmberGlow,
                    activeBet = activeBets["BIG"],
                    enabled = enabled,
                    onClick = { onToggleSelection("BIG") },
                    testTag = "bet_big_button",
                    modifier = Modifier.weight(1f)
                )

                BigSmallPad(
                    name = "SMALL",
                    rangeLabel = "0, 1, 2, 3, 4",
                    multiplier = "${smallMultiplier}x",
                    accentColor = ElectricCyan,
                    activeBet = activeBets["SMALL"],
                    enabled = enabled,
                    onClick = { onToggleSelection("SMALL") },
                    testTag = "bet_small_button",
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
}

@Composable
fun BigSmallPad(
    name: String,
    rangeLabel: String,
    multiplier: String,
    accentColor: Color,
    activeBet: BetEntity?,
    enabled: Boolean = true,
    onClick: () -> Unit,
    testTag: String,
    modifier: Modifier = Modifier
) {
    val isPlaced = activeBet != null

    Surface(
        shape = RoundedCornerShape(14.dp),
        color = if (isPlaced) accentColor.copy(alpha = 0.24f) else ObsidianBg,
        border = borderStroke(
            width = if (isPlaced) 2.5.dp else 1.5.dp,
            color = if (isPlaced) Color.White else accentColor.copy(alpha = 0.85f)
        ),
        modifier = modifier
            .height(82.dp)
            .clickable(enabled = enabled) { onClick() }
            .testTag(testTag)
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 10.dp, vertical = 6.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                Text(
                    text = name,
                    color = if (isPlaced) Color.White else accentColor,
                    fontWeight = FontWeight.Black,
                    fontSize = 17.sp,
                    letterSpacing = 1.sp
                )
                Spacer(modifier = Modifier.width(6.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(accentColor.copy(alpha = if (isPlaced) 0.35f else 0.18f))
                        .padding(horizontal = 5.dp, vertical = 1.5.dp)
                ) {
                    Text(
                        text = multiplier,
                        color = if (isPlaced) Color.White else accentColor,
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 10.sp
                    )
                }
            }

            Spacer(modifier = Modifier.height(2.dp))

            Text(
                text = rangeLabel,
                color = if (isPlaced) TextPrimary else TextMuted,
                fontWeight = FontWeight.Medium,
                fontSize = 11.sp
            )

            if (isPlaced) {
                Spacer(modifier = Modifier.height(3.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(GoldAccent)
                        .padding(horizontal = 6.dp, vertical = 1.5.dp)
                ) {
                    Text(
                        text = if (enabled) "₹${activeBet.amount / 100} ✕ Cancel" else "₹${activeBet.amount / 100} 🔒",
                        color = ObsidianBg,
                        fontWeight = FontWeight.Black,
                        fontSize = 9.sp
                    )
                }
            }
        }
    }
}

@Composable
fun NumberGridSelection(
    activeBets: Map<String, BetEntity>,
    numberMultiplier: Double,
    enabled: Boolean = true,
    onToggleNumber: (Int) -> Unit
) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier
            .fillMaxWidth()
            .alpha(if (enabled) 1f else 0.45f)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Numbers 0–9 (Multi-Bet Enabled)",
                    color = TextPrimary,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = "Payout: ${numberMultiplier}x",
                    color = GoldAccent,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.ExtraBold
                )
            }

            Spacer(modifier = Modifier.height(10.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                (0..4).forEach { num ->
                    NumberBall(
                        number = num,
                        activeBet = activeBets["$num"],
                        enabled = enabled,
                        onClick = { onToggleNumber(num) }
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                (5..9).forEach { num ->
                    NumberBall(
                        number = num,
                        activeBet = activeBets["$num"],
                        enabled = enabled,
                        onClick = { onToggleNumber(num) }
                    )
                }
            }
        }
    }
}

@Composable
fun NumberBall(
    number: Int,
    activeBet: BetEntity?,
    enabled: Boolean = true,
    onClick: () -> Unit
) {
    val isPlaced = activeBet != null
    val ballColor = when (number) {
        0 -> NeonViolet
        5 -> NeonViolet
        1, 3, 7, 9 -> NeonGreen
        else -> NeonRed
    }

    Box(
        modifier = Modifier
            .size(50.dp)
            .clip(CircleShape)
            .background(if (isPlaced) ballColor else SurfaceDark)
            .border(
                width = if (isPlaced) 3.dp else 1.5.dp,
                color = if (isPlaced) Color.White else ballColor,
                shape = CircleShape
            )
            .clickable(enabled = enabled) { onClick() }
            .testTag("bet_number_$number"),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "$number",
                color = if (isPlaced) Color.White else ballColor,
                fontWeight = FontWeight.Black,
                fontSize = if (isPlaced) 13.sp else 16.sp
            )
            if (isPlaced) {
                Text(
                    text = if (enabled) "₹${activeBet.amount / 100}✕" else "₹${activeBet.amount / 100}🔒",
                    color = GoldAccent,
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 8.sp
                )
            }
        }
    }
}

@Composable
fun BetHistoryItem(bet: BetEntity, round: GameRoundEntity? = null) {
    val (statusLabel, statusColor, statusBg) = when (bet.status.uppercase()) {
        "WON" -> Triple("WON", NeonGreen, NeonGreen.copy(alpha = 0.2f))
        "LOST" -> Triple("LOST", NeonRed, NeonRed.copy(alpha = 0.2f))
        "REFUNDED", "CANCELLED" -> Triple("REFUNDED", ElectricCyan, ElectricCyan.copy(alpha = 0.2f))
        "ACCEPTED", "PENDING" -> Triple("WAIT", AmberGlow, AmberGlow.copy(alpha = 0.2f))
        else -> Triple(bet.status, TextMuted, CardHighlight)
    }

    val themeColor = when (bet.selection.uppercase()) {
        "GREEN" -> NeonGreen
        "RED" -> NeonRed
        "VIOLET" -> NeonViolet
        "BIG" -> AmberGlow
        "SMALL" -> ElectricCyan
        "0", "5" -> NeonViolet
        "1", "3", "7", "9" -> NeonGreen
        else -> NeonRed
    }

    val market = GameMarkets.getById(bet.gameId)
    val marketAccentColor = Color(market.accentColorHex)
    val periodNumber = round?.roundNumber?.let { "#$it" } ?: ("#" + bet.roundId.substringAfterLast("_"))
    val timeFormatWithSeconds = remember { SimpleDateFormat("dd MMM, hh:mm:ss a", Locale.ENGLISH) }
    val feeCents = if (bet.platformFeeCents > 0L) bet.platformFeeCents else (bet.amount * 3L) / 100L
    val netCents = if (bet.netAmountCents > 0L) bet.netAmountCents else (bet.amount - feeCents)

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        tonalElevation = 4.dp,
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            // Top Row: Selection Badge, Market/Period, Status Pill
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .background(themeColor)
                        .border(1.2.dp, Color.White.copy(alpha = 0.85f), CircleShape),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = if (bet.betType == BetType.NUMBER.name) bet.selection else bet.selection.take(1),
                        color = if (themeColor == NeonGreen || themeColor == AmberGlow || themeColor == ElectricCyan) ObsidianBg else Color.White,
                        fontWeight = FontWeight.Black,
                        fontSize = 14.sp
                    )
                }

                Spacer(modifier = Modifier.width(10.dp))

                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = when (bet.betType) {
                                BetType.NUMBER.name -> "Number ${bet.selection}"
                                BetType.BIG_SMALL.name -> when (bet.selection.uppercase()) {
                                    "BIG" -> "BIG (5–9)"
                                    "SMALL" -> "SMALL (0–4)"
                                    else -> bet.selection
                                }
                                else -> bet.selection
                            },
                            color = TextPrimary,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 14.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Surface(
                            shape = RoundedCornerShape(5.dp),
                            color = CardHighlight
                        ) {
                            Text(
                                text = "${bet.multiplier}x",
                                color = GoldAccent,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.ExtraBold,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.5.dp)
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "${market.emoji} ${market.name} • $periodNumber",
                        color = marketAccentColor,
                        fontWeight = FontWeight.Bold,
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = statusBg,
                    border = borderStroke(1.dp, statusColor.copy(alpha = 0.8f))
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Box(
                            modifier = Modifier
                                .size(5.dp)
                                .clip(CircleShape)
                                .background(statusColor)
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text(
                            text = statusLabel,
                            color = statusColor,
                            fontWeight = FontWeight.Black,
                            fontSize = 10.sp
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            // 3-Column Metrics Strip: Paid | 3% Fee / Net | Result Payout
            Surface(
                shape = RoundedCornerShape(10.dp),
                color = ObsidianBg,
                border = borderStroke(0.8.dp, CardBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("PAID", color = TextMuted, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(2.dp))
                        Text(
                            text = MoneyUtils.formatCents(bet.amount),
                            color = TextPrimary,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 12.sp
                        )
                    }
                    Column(modifier = Modifier.weight(1.25f), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("3% FEE / NET", color = TextMuted, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(2.dp))
                        Text(
                            text = "${MoneyUtils.formatCents(feeCents)} / ${MoneyUtils.formatCents(netCents)}",
                            color = ElectricCyan,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp,
                            maxLines = 1
                        )
                    }
                    Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                        Text(
                            text = when {
                                bet.status.uppercase() in listOf("REFUNDED", "CANCELLED") -> "REFUNDED"
                                bet.status == "WON" -> "PAYOUT"
                                bet.status == "LOST" -> "LOSS"
                                else -> "TARGET"
                            },
                            color = TextMuted,
                            fontSize = 9.sp,
                            fontWeight = FontWeight.Bold
                        )
                        Spacer(modifier = Modifier.height(2.dp))
                        val (valText, valColor) = when {
                            bet.status.uppercase() in listOf("REFUNDED", "CANCELLED") ->
                                "+${MoneyUtils.formatCents(bet.amount)}" to ElectricCyan
                            bet.status == "WON" ->
                                "+${MoneyUtils.formatCents(bet.actualPayout)}" to NeonGreen
                            bet.status == "LOST" ->
                                "-${MoneyUtils.formatCents(bet.amount)}" to NeonRed
                            else ->
                                "+${MoneyUtils.formatCents(bet.potentialPayout)}" to AmberGlow
                        }
                        Text(
                            text = valText,
                            color = valColor,
                            fontWeight = FontWeight.ExtraBold,
                            fontSize = 12.sp
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Bottom Row: Timestamp & Result Outcome
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.AccessTime,
                        contentDescription = null,
                        tint = ElectricCyan,
                        modifier = Modifier.size(12.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = timeFormatWithSeconds.format(Date(bet.createdAt)),
                        color = ElectricCyan,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Medium,
                        fontFamily = FontFamily.Monospace
                    )
                }

                if (bet.status.uppercase() in listOf("REFUNDED", "CANCELLED")) {
                    Text(
                        text = "Result: Refunded",
                        color = ElectricCyan,
                        fontWeight = FontWeight.Bold,
                        fontSize = 11.sp
                    )
                } else if (round != null && round.resultNumber != null) {
                    val outcomeNum = round.resultNumber
                    val outcomeColor = round.resultColor ?: ""
                    val isOutcomeBig = outcomeNum >= 5
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(text = "Draw: ", color = TextMuted, fontSize = 11.sp)
                        Text(
                            text = "$outcomeNum $outcomeColor (${if (isOutcomeBig) "BIG" else "SMALL"})",
                            color = when {
                                outcomeColor.contains("VIOLET") -> NeonViolet
                                outcomeColor.contains("GREEN") -> NeonGreen
                                outcomeColor.contains("RED") -> NeonRed
                                else -> TextPrimary
                            },
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp
                        )
                    }
                } else {
                    Text(
                        text = "Awaiting Draw",
                        color = TextMuted,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Medium
                    )
                }
            }
        }
    }
}

@Composable
fun EmptyStateCard(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    subtitle: String
) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 24.dp)
    ) {
        Column(
            modifier = Modifier.padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = TextMuted,
                modifier = Modifier.size(44.dp)
            )
            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = title,
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = subtitle,
                color = TextSecondary,
                fontSize = 12.sp,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
fun TwentyFourHourResultSection(recentRounds: List<GameRoundEntity>, market: MarketInfo = GameMarkets.MIAMI) {
    var viewMode by remember { mutableStateOf(0) } // 0: 10 per row table, 1: 10x10 matrix
    var currentPage by remember { mutableStateOf(0) }
    var selectedRoundDetail by remember { mutableStateOf<GameRoundEntity?>(null) }
    val marketAccentColor = Color(market.accentColorHex)

    val pageSize = 10
    val totalRounds = recentRounds.size
    val totalPages = maxOf(1, (totalRounds + pageSize - 1) / pageSize)
    val pageItems = recentRounds.drop(currentPage * pageSize).take(pageSize)

    if (selectedRoundDetail != null) {
        PeriodDetailDialog(
            round = selectedRoundDetail!!,
            onDismiss = { selectedRoundDetail = null }
        )
    }

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Surface(
                            shape = RoundedCornerShape(4.dp),
                            color = marketAccentColor.copy(alpha = 0.2f),
                            border = borderStroke(1.dp, marketAccentColor.copy(alpha = 0.6f))
                        ) {
                            Text(
                                text = "${market.emoji} ${market.name}",
                                color = marketAccentColor,
                                fontWeight = FontWeight.Black,
                                fontSize = 10.sp,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                            )
                        }
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "24-Hours Period Records",
                            color = TextPrimary,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Bold
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(4.dp))
                                .background(GoldAccent.copy(alpha = 0.15f))
                                .padding(horizontal = 6.dp, vertical = 2.dp)
                        ) {
                            Text(
                                text = "10/10 Matrix",
                                color = GoldAccent,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                    Text(
                        text = "${market.name} Market • $totalRounds periods recorded • Auto-sync",
                        color = TextSecondary,
                        fontSize = 11.sp
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // View Mode Selector (10-per-row Table vs 10x10 Bead Plate Matrix)
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(CardHighlight)
                    .padding(3.dp)
            ) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (viewMode == 0) GoldAccent else Color.Transparent)
                        .clickable { viewMode = 0 }
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "📜 24H Records (10 per Row)",
                        color = if (viewMode == 0) ObsidianBg else TextSecondary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp
                    )
                }

                Box(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (viewMode == 1) ElectricCyan else Color.Transparent)
                        .clickable { viewMode = 1 }
                        .padding(vertical = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "🎲 10×10 Matrix Bead Plate",
                        color = if (viewMode == 1) ObsidianBg else TextSecondary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp
                    )
                }
            }

            Spacer(modifier = Modifier.height(14.dp))

            if (viewMode == 0) {
                // Table View (10 periods per page)
                PeriodRecordsTable(
                    rounds = pageItems,
                    currentPage = currentPage,
                    totalPages = totalPages,
                    onPrevPage = { if (currentPage > 0) currentPage-- },
                    onNextPage = { if (currentPage < totalPages - 1) currentPage++ },
                    onRoundClick = { selectedRoundDetail = it }
                )
            } else {
                // 10x10 Matrix Bead Plate Grid (10 rows x 10 cols)
                TenByTenMatrixGrid(
                    rounds = recentRounds.take(100),
                    onRoundClick = { selectedRoundDetail = it }
                )
            }
        }
    }
}

@Composable
fun PeriodRecordsTable(
    rounds: List<GameRoundEntity>,
    currentPage: Int,
    totalPages: Int,
    onPrevPage: () -> Unit,
    onNextPage: () -> Unit,
    onRoundClick: (GameRoundEntity) -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        // Table Header
        Surface(
            color = CardHighlight,
            shape = RoundedCornerShape(8.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(text = "Period Number", color = TextMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1.8f))
                Text(text = "Number", color = TextMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.weight(1f))
                Text(text = "Big/Small", color = TextMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.weight(1.2f))
                Text(text = "Color", color = TextMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.weight(1.4f))
            }
        }

        Spacer(modifier = Modifier.height(6.dp))

        if (rounds.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(text = "No period results yet", color = TextMuted, fontSize = 12.sp)
            }
        } else {
            rounds.forEach { round ->
                PeriodRowItem(
                    round = round,
                    onClick = { onRoundClick(round) }
                )
                Divider(color = CardBorder.copy(alpha = 0.5f), thickness = 0.8.dp)
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Pagination Controls (10 rows per page)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedButton(
                onClick = onPrevPage,
                enabled = currentPage > 0,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = TextPrimary),
                border = borderStroke(1.dp, if (currentPage > 0) ElectricCyan else CardBorder),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                shape = RoundedCornerShape(8.dp)
            ) {
                Text(text = "◀ Prev 10", fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }

            Text(
                text = "Page ${currentPage + 1} of $totalPages",
                color = GoldAccent,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )

            OutlinedButton(
                onClick = onNextPage,
                enabled = currentPage < totalPages - 1,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = TextPrimary),
                border = borderStroke(1.dp, if (currentPage < totalPages - 1) ElectricCyan else CardBorder),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                shape = RoundedCornerShape(8.dp)
            ) {
                Text(text = "Next 10 ▶", fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
fun PeriodRowItem(
    round: GameRoundEntity,
    onClick: () -> Unit
) {
    val num = round.resultNumber ?: 0
    val isBig = num >= 5
    val (ballBg, ballText) = when (round.resultColor) {
        "RED" -> Pair(NeonRed, Color.White)
        "GREEN" -> Pair(NeonGreen, ObsidianBg)
        "VIOLET" -> Pair(NeonViolet, Color.White)
        "RED_VIOLET" -> Pair(NeonViolet, Color.White)
        else -> Pair(NeonGreen, ObsidianBg)
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick() }
            .padding(horizontal = 10.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Proper Period Number
        Column(modifier = Modifier.weight(1.8f)) {
            Text(
                text = "${round.roundNumber}",
                color = TextPrimary,
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold
            )
            val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
            Text(
                text = timeFormat.format(Date(round.resultTime)),
                color = TextMuted,
                fontSize = 10.sp
            )
        }

        // Result Number Ball
        Box(
            modifier = Modifier.weight(1f),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(28.dp)
                    .clip(CircleShape)
                    .background(ballBg)
                    .border(1.dp, Color.White.copy(alpha = 0.4f), CircleShape),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "$num",
                    color = ballText,
                    fontWeight = FontWeight.Black,
                    fontSize = 13.sp
                )
            }
        }

        // Big / Small Badge
        Box(
            modifier = Modifier.weight(1.2f),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(4.dp))
                    .background(if (isBig) ElectricCyan.copy(alpha = 0.2f) else AmberGlow.copy(alpha = 0.2f))
                    .padding(horizontal = 6.dp, vertical = 2.dp)
            ) {
                Text(
                    text = if (isBig) "BIG" else "SMALL",
                    color = if (isBig) ElectricCyan else AmberGlow,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        // Color Pill
        Box(
            modifier = Modifier.weight(1.4f),
            contentAlignment = Alignment.Center
        ) {
            val displayColor = round.resultColor?.replace("_", " + ") ?: "GREEN"
            Text(
                text = displayColor,
                color = ballBg,
                fontWeight = FontWeight.Bold,
                fontSize = 11.sp,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
fun TenByTenMatrixGrid(
    rounds: List<GameRoundEntity>,
    onRoundClick: (GameRoundEntity) -> Unit
) {
    // 10 rows x 10 columns grid matrix (100 rounds)
    val rows = 10
    val cols = 10

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(ObsidianBg)
            .padding(10.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = "10×10 Bead Plate (100 Period Outcomes)",
                color = TextSecondary,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold
            )
            Text(
                text = "Tap ball for details ↗",
                color = ElectricCyan,
                fontSize = 10.sp
            )
        }

        Spacer(modifier = Modifier.height(10.dp))

        // Render 10 rows of 10 items
        for (r in 0 until rows) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 2.5.dp),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                for (c in 0 until cols) {
                    val index = r * cols + c
                    if (index < rounds.size) {
                        val round = rounds[index]
                        val num = round.resultNumber ?: 0
                        val ballBg = when (round.resultColor) {
                            "RED" -> NeonRed
                            "GREEN" -> NeonGreen
                            "VIOLET" -> NeonViolet
                            "RED_VIOLET" -> NeonViolet
                            else -> NeonGreen
                        }
                        val ballText = if (ballBg == NeonGreen) ObsidianBg else Color.White

                        Box(
                            modifier = Modifier
                                .size(28.dp)
                                .clip(CircleShape)
                                .background(ballBg)
                                .border(0.8.dp, Color.White.copy(alpha = 0.4f), CircleShape)
                                .clickable { onRoundClick(round) },
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "$num",
                                color = ballText,
                                fontWeight = FontWeight.Black,
                                fontSize = 11.sp
                            )
                        }
                    } else {
                        // Empty placeholder cell
                        Box(
                            modifier = Modifier
                                .size(28.dp)
                                .clip(CircleShape)
                                .background(CardHighlight.copy(alpha = 0.3f))
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun PeriodDetailDialog(
    round: GameRoundEntity,
    onDismiss: () -> Unit
) {
    val timeFormat = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault())
    val num = round.resultNumber ?: 0
    val isBig = num >= 5

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = SurfaceDark,
            border = borderStroke(1.dp, GoldAccent),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(18.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Period Result Audit",
                        color = GoldAccent,
                        fontWeight = FontWeight.Bold,
                        fontSize = 16.sp
                    )
                    IconButton(onClick = onDismiss) {
                        Icon(imageVector = Icons.Default.Close, contentDescription = "Close", tint = TextMuted)
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))

                // Period ID Banner
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = CardHighlight,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(10.dp)) {
                        Text(text = "Period Number:", color = TextMuted, fontSize = 11.sp)
                        Text(
                            text = "${round.roundNumber}",
                            color = TextPrimary,
                            fontWeight = FontWeight.Black,
                            fontSize = 16.sp,
                            fontFamily = FontFamily.Monospace
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Settled: ${timeFormat.format(Date(round.resultTime))}",
                            color = TextSecondary,
                            fontSize = 11.sp
                        )
                    }
                }

                Spacer(modifier = Modifier.height(14.dp))

                // Outcome Metrics
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    MiniDetailCard("Number", "$num", GoldAccent, Modifier.weight(1f))
                    MiniDetailCard("Color", round.resultColor ?: "GREEN", NeonGreen, Modifier.weight(1.3f))
                    MiniDetailCard("Size", if (isBig) "BIG (5-9)" else "SMALL (0-4)", ElectricCyan, Modifier.weight(1.2f))
                }

                Spacer(modifier = Modifier.height(14.dp))

                // Provably Fair Cryptographic Details
                Text(text = "Provably Fair Cryptographic Record:", color = TextSecondary, fontSize = 11.sp)
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "Server Seed Hash:\n${round.serverSeedHash}",
                    color = TextMuted,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace
                )
                if (round.serverSeed != null) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Server Seed (Revealed):\n${round.serverSeed}",
                        color = NeonGreen,
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = onDismiss,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = GoldAccent)
                ) {
                    Text("Close", color = ObsidianBg, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
fun MiniDetailCard(title: String, value: String, color: Color, modifier: Modifier = Modifier) {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = CardHighlight,
        modifier = modifier
    ) {
        Column(modifier = Modifier.padding(8.dp)) {
            Text(text = title, color = TextMuted, fontSize = 10.sp)
            Spacer(modifier = Modifier.height(2.dp))
            Text(text = value, color = color, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        }
    }
}

