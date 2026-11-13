package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalContext
import com.example.data.model.MoneyUtils
import com.example.data.model.WalletEntity
import com.example.data.model.WalletLedgerEntity
import com.example.domain.AccountStatementSummary
import com.example.domain.StatementExporter
import com.example.ui.MainViewModel
import com.example.ui.components.borderStroke
import com.example.ui.theme.*
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.abs

@Composable
fun WalletScreen(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val wallet by viewModel.wallet.collectAsState()
    val ledger by viewModel.userLedger.collectAsState()
    val statementSummary by viewModel.statementSummary.collectAsState()
    val statementDays by viewModel.statementDays.collectAsState()
    val bankConfig by viewModel.bankConfig.collectAsState()

    var showDepositDialog by remember { mutableStateOf(false) }
    var showWithdrawDialog by remember { mutableStateOf(false) }
    var showStatementModal by remember { mutableStateOf(false) }
    var selectedFilter by remember { mutableStateOf("ALL") }

    val csvLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/csv")
    ) { uri ->
        if (uri != null) {
            try {
                val csvData = viewModel.generateStatementCsv(days = statementDays, filter = selectedFilter)
                context.contentResolver.openOutputStream(uri)?.use { out ->
                    out.write(csvData.toByteArray(Charsets.UTF_8))
                }
                viewModel.postNotification("Account Statement CSV saved successfully!", true)
            } catch (e: Exception) {
                viewModel.postNotification("Failed to save statement: ${e.message}", false)
            }
        }
    }

    val launchCsvExport: () -> Unit = {
        val df = SimpleDateFormat("yyyyMMdd", Locale.ENGLISH).format(Date())
        csvLauncher.launch("ColourKing_${statementDays}Day_Statement_$df.csv")
    }

    val filteredLedger = remember(ledger, selectedFilter, statementDays) {
        StatementExporter.filterLedgerEntries(
            ledger = ledger,
            filter = selectedFilter,
            days = statementDays
        )
    }

    if (showDepositDialog) {
        DepositDialog(
            bankConfig = bankConfig,
            onDismiss = { showDepositDialog = false },
            onDeposit = { amountCents, provider, utr ->
                viewModel.submitDepositRequest(
                    amountRupees = amountCents / 100.0,
                    utr = utr,
                    method = provider
                )
                showDepositDialog = false
            }
        )
    }

    if (showWithdrawDialog) {
        WithdrawDialog(
            availableBalanceCents = wallet?.availableBalance ?: 0L,
            onDismiss = { showWithdrawDialog = false },
            onWithdraw = { amountCents, upiId, bankName, accNo, ifsc, bankingName ->
                viewModel.submitWithdrawalRequest(
                    amountRupees = amountCents / 100.0,
                    upiId = upiId,
                    bankName = bankName,
                    accNo = accNo,
                    ifsc = ifsc,
                    bankingName = bankingName
                )
                showWithdrawDialog = false
            }
        )
    }

    if (showStatementModal) {
        StatementBreakdownDialog(
            summary = statementSummary,
            onDismiss = { showStatementModal = false },
            onDownloadCsv = {
                showStatementModal = false
                launchCsvExport()
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
                text = "Double-Entry Wallet & 90-Day Statement",
                color = TextPrimary,
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "Real-time accounting with Bet P&L, Refer & Earn, Deposit & Withdrawal statements",
                color = TextSecondary,
                fontSize = 12.sp
            )
            Spacer(modifier = Modifier.height(12.dp))

            // Wallet Balances Card
            WalletBalancesCard(
                wallet = wallet,
                onDepositClick = { showDepositDialog = true },
                onWithdrawClick = { showWithdrawDialog = true }
            )
            Spacer(modifier = Modifier.height(14.dp))

            // 90-Day Financial Statement Summary & CSV Export
            StatementSummaryCard(
                summary = statementSummary,
                selectedDays = statementDays,
                onSelectDays = { viewModel.setStatementDays(it) },
                onDownloadCsvClick = launchCsvExport,
                onViewBreakdownClick = { showStatementModal = true }
            )
            Spacer(modifier = Modifier.height(16.dp))

            // Ledger Section Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Immutable Transaction Statement",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )
                Text(
                    text = "${filteredLedger.size} entries ($statementDays Days)",
                    color = TextMuted,
                    fontSize = 11.sp
                )
            }
            Spacer(modifier = Modifier.height(8.dp))

            // Filters
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                listOf(
                    "ALL" to "All",
                    "PROFIT_LOSS" to "Bet P&L",
                    "BET" to "Bets",
                    "WIN" to "Wins",
                    "COMMISSION" to "Refer & Earn",
                    "DEPOSIT" to "Deposits",
                    "WITHDRAWAL" to "Withdrawals"
                ).forEach { (key, label) ->
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (selectedFilter == key) GoldAccent else SurfaceDark)
                            .clickable { selectedFilter = key }
                            .padding(horizontal = 12.dp, vertical = 6.dp)
                    ) {
                        Text(
                            text = label,
                            color = if (selectedFilter == key) ObsidianBg else TextSecondary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        if (filteredLedger.isEmpty()) {
            item {
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = SurfaceDark,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Box(modifier = Modifier.padding(24.dp), contentAlignment = Alignment.Center) {
                        Text(text = "No ledger entries in this filter ($statementDays days)", color = TextMuted, fontSize = 12.sp)
                    }
                }
            }
        } else {
            items(filteredLedger) { entry ->
                LedgerItemCard(entry = entry)
                Spacer(modifier = Modifier.height(8.dp))
            }
        }

        item { Spacer(modifier = Modifier.height(30.dp)) }
    }
}

@Composable
fun WalletBalancesCard(
    wallet: WalletEntity?,
    onDepositClick: () -> Unit,
    onWithdrawClick: () -> Unit
) {
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(18.dp)) {
            Text(
                text = "AVAILABLE BALANCE",
                color = TextSecondary,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 1.sp
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = MoneyUtils.formatCents(wallet?.availableBalance ?: 0L),
                color = GoldAccent,
                fontSize = 32.sp,
                fontWeight = FontWeight.Black
            )

            if ((wallet?.lockedBalance ?: 0L) > 0L) {
                Spacer(modifier = Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Lock,
                        contentDescription = null,
                        tint = AmberGlow,
                        modifier = Modifier.size(13.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = "Locked in review: ${MoneyUtils.formatCents(wallet?.lockedBalance ?: 0L)}",
                        color = AmberGlow,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Medium
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Action Buttons
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Button(
                    onClick = onDepositClick,
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = NeonGreen),
                    modifier = Modifier
                        .weight(1f)
                        .height(46.dp)
                        .testTag("wallet_deposit_btn")
                ) {
                    Icon(imageVector = Icons.Default.ArrowDownward, contentDescription = null, tint = ObsidianBg)
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(text = "Deposit", color = ObsidianBg, fontWeight = FontWeight.Bold)
                }

                OutlinedButton(
                    onClick = onWithdrawClick,
                    shape = RoundedCornerShape(10.dp),
                    border = borderStroke(1.dp, ElectricCyan),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = ElectricCyan),
                    modifier = Modifier
                        .weight(1f)
                        .height(46.dp)
                        .testTag("wallet_withdraw_btn")
                ) {
                    Icon(imageVector = Icons.Default.ArrowUpward, contentDescription = null, tint = ElectricCyan)
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(text = "Withdraw", color = ElectricCyan, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
fun StatementSummaryCard(
    summary: AccountStatementSummary,
    selectedDays: Int,
    onSelectDays: (Int) -> Unit,
    onDownloadCsvClick: () -> Unit,
    onViewBreakdownClick: () -> Unit
) {
    val pl = summary.netBetProfitLossCents
    val plColor = if (pl >= 0L) NeonGreen else NeonRed
    val plPrefix = if (pl >= 0L) "+" else "-"

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, ElectricCyan.copy(alpha = 0.4f)),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "$selectedDays-Day Statement Summary",
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 14.sp
                    )
                    Text(
                        text = "90-Day Bet Records & Wallet Audit",
                        color = ElectricCyan,
                        fontSize = 10.sp
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    listOf(90, 30, 7).forEach { daysOpt ->
                        val active = selectedDays == daysOpt
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(6.dp))
                                .background(if (active) GoldAccent else CardHighlight)
                                .clickable { onSelectDays(daysOpt) }
                                .padding(horizontal = 8.dp, vertical = 4.dp)
                        ) {
                            Text(
                                text = "${daysOpt}D",
                                color = if (active) ObsidianBg else TextSecondary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 10.sp
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                StatPill(
                    title = "Bet Profit / Loss",
                    value = "$plPrefix${MoneyUtils.formatCents(abs(pl))}",
                    subtitle = "Won ${MoneyUtils.formatCents(summary.totalBetWonCents)} / Wager ${MoneyUtils.formatCents(summary.totalBetWageredCents)}",
                    color = plColor,
                    modifier = Modifier.weight(1f)
                )
                StatPill(
                    title = "Refer & Earn",
                    value = "+${MoneyUtils.formatCents(summary.totalReferEarnCents)}",
                    subtitle = "${summary.totalBetsCount} bets (${summary.wonBetsCount}W / ${summary.lostBetsCount}L)",
                    color = GoldAccent,
                    modifier = Modifier.weight(1f)
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                StatPill(
                    title = "Deposits",
                    value = "+${MoneyUtils.formatCents(summary.totalDepositCents)}",
                    color = NeonGreen,
                    modifier = Modifier.weight(1f)
                )
                StatPill(
                    title = "Withdrawals",
                    value = "-${MoneyUtils.formatCents(summary.totalWithdrawalCents)}",
                    color = ElectricCyan,
                    modifier = Modifier.weight(1f)
                )
            }

            Spacer(modifier = Modifier.height(10.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    onClick = onDownloadCsvClick,
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = GoldAccent),
                    modifier = Modifier
                        .weight(1.3f)
                        .height(42.dp)
                        .testTag("download_statement_btn")
                ) {
                    Icon(
                        imageVector = Icons.Default.Download,
                        contentDescription = "Download Statement CSV",
                        tint = ObsidianBg,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = "Download CSV",
                        color = ObsidianBg,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp
                    )
                }

                OutlinedButton(
                    onClick = onViewBreakdownClick,
                    shape = RoundedCornerShape(10.dp),
                    border = borderStroke(1.dp, ElectricCyan),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = ElectricCyan),
                    modifier = Modifier
                        .weight(1f)
                        .height(42.dp)
                        .testTag("view_statement_btn")
                ) {
                    Icon(
                        imageVector = Icons.Default.Assessment,
                        contentDescription = "View Statement Report",
                        tint = ElectricCyan,
                        modifier = Modifier.size(15.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = "Report",
                        color = ElectricCyan,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp
                    )
                }
            }
        }
    }
}

@Composable
fun StatementBreakdownDialog(
    summary: AccountStatementSummary,
    onDismiss: () -> Unit,
    onDownloadCsv: () -> Unit
) {
    val pl = summary.netBetProfitLossCents
    val plColor = if (pl >= 0L) NeonGreen else NeonRed
    val plPrefix = if (pl >= 0L) "+" else "-"

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(18.dp),
            color = SurfaceDark,
            border = borderStroke(1.dp, GoldAccent.copy(alpha = 0.6f)),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(
                modifier = Modifier
                    .padding(18.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = "${summary.days}-Day Account Statement",
                    color = GoldAccent,
                    fontSize = 17.sp,
                    fontWeight = FontWeight.ExtraBold
                )
                Text(
                    text = "90-Day Bet History, Wallet, Refer & Earn, Deposit & Withdrawal Audit",
                    color = TextSecondary,
                    fontSize = 11.sp
                )
                HorizontalDivider(color = CardBorder)

                StatementRow("Available Wallet Balance", MoneyUtils.formatCents(summary.availableBalanceCents), GoldAccent)
                StatementRow("Locked Escrow Balance", MoneyUtils.formatCents(summary.lockedBalanceCents), AmberGlow)
                StatementRow("Total Bets Played", "${summary.totalBetsCount} (Won: ${summary.wonBetsCount}, Lost: ${summary.lostBetsCount})", TextPrimary)
                StatementRow("Total Bet Wagered", MoneyUtils.formatCents(summary.totalBetWageredCents), TextPrimary)
                StatementRow("Total Bet Won Payout", MoneyUtils.formatCents(summary.totalBetWonCents), NeonGreen)
                StatementRow("Net Bet Profit / Loss", "$plPrefix${MoneyUtils.formatCents(abs(pl))}", plColor)
                StatementRow("Refer & Earn Income", "+${MoneyUtils.formatCents(summary.totalReferEarnCents)}", GoldAccent)
                StatementRow("Total Deposits", "+${MoneyUtils.formatCents(summary.totalDepositCents)}", NeonGreen)
                StatementRow("Total Withdrawals", "-${MoneyUtils.formatCents(summary.totalWithdrawalCents)}", ElectricCyan)

                Spacer(modifier = Modifier.height(6.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlinedButton(
                        onClick = onDismiss,
                        shape = RoundedCornerShape(10.dp),
                        border = borderStroke(1.dp, CardBorder),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Close", color = TextSecondary)
                    }
                    Button(
                        onClick = onDownloadCsv,
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = GoldAccent),
                        modifier = Modifier.weight(1.4f)
                    ) {
                        Text("Download CSV", color = ObsidianBg, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable
private fun StatementRow(label: String, value: String, valueColor: Color) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(CardHighlight)
            .padding(horizontal = 10.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(text = label, color = TextSecondary, fontSize = 12.sp)
        Text(text = value, color = valueColor, fontSize = 12.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
    }
}

@Composable
fun StatPill(
    title: String,
    value: String,
    color: Color,
    modifier: Modifier = Modifier,
    subtitle: String? = null
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = CardHighlight,
        border = borderStroke(1.dp, CardBorder),
        modifier = modifier
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Text(text = title, color = TextMuted, fontSize = 10.sp)
            Spacer(modifier = Modifier.height(2.dp))
            Text(text = value, color = color, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            if (subtitle != null) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(text = subtitle, color = TextMuted, fontSize = 9.sp)
            }
        }
    }
}

@Composable
fun LedgerItemCard(entry: WalletLedgerEntity) {
    val isCredit = entry.direction == "CREDIT"
    val amountColor = if (isCredit) NeonGreen else NeonRed
    val sign = if (isCredit) "+" else "-"
    val dateFormat = SimpleDateFormat("dd MMM, HH:mm:ss", Locale.getDefault())
    val dateStr = dateFormat.format(Date(entry.createdAt))

    Surface(
        shape = RoundedCornerShape(12.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .background(amountColor.copy(alpha = 0.15f)),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = when (entry.entryType) {
                            "DEPOSIT" -> "💳"
                            "WITHDRAWAL" -> "🏦"
                            "BET" -> "🎲"
                            "WIN" -> "🏆"
                            "REFERRAL_COMMISSION" -> "🤝"
                            "REFUND" -> "↩️"
                            else -> "🪙"
                        },
                        fontSize = 16.sp
                    )
                }

                Spacer(modifier = Modifier.width(10.dp))

                Column {
                    Text(
                        text = entry.entryType.replace("_", " "),
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp
                    )
                    Text(
                        text = "$dateStr • ${entry.referenceType}",
                        color = TextMuted,
                        fontSize = 10.sp
                    )
                }
            }

            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "$sign${MoneyUtils.formatCents(entry.amount)}",
                    color = amountColor,
                    fontWeight = FontWeight.ExtraBold,
                    fontSize = 13.sp
                )
                Text(
                    text = "Bal: ${MoneyUtils.formatCents(entry.balanceAfter)}",
                    color = TextSecondary,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace
                )
            }
        }
    }
}

@Composable
fun DepositDialog(
    bankConfig: com.example.domain.BankConfigState = com.example.domain.BankConfigState(),
    onDismiss: () -> Unit,
    onDeposit: (amountCents: Long, provider: String, utr: String) -> Unit
) {
    val clipboardManager = LocalClipboardManager.current
    var selectedAmountCents by remember { mutableStateOf(100000L) } // ₹1,000
    var customAmountText by remember { mutableStateOf("1000") }
    var selectedProvider by remember { mutableStateOf("UPI (GPay / PhonePe / Paytm)") }
    var utrText by remember { mutableStateOf("") }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var copiedLabel by remember { mutableStateOf<String?>(null) }

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = SurfaceDark,
            border = borderStroke(1.dp, NeonGreen),
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 12.dp)
        ) {
            Column(
                modifier = Modifier
                    .padding(16.dp)
                    .verticalScroll(rememberScrollState())
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column {
                        Text(
                            text = "+ Add Deposit Funds",
                            color = TextPrimary,
                            fontSize = 17.sp,
                            fontWeight = FontWeight.Bold
                        )
                        Text(
                            text = "Admin Bank & UPI Gateway",
                            color = NeonGreen,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold
                        )
                    }
                    IconButton(onClick = onDismiss, modifier = Modifier.size(28.dp)) {
                        Icon(imageVector = Icons.Default.Close, contentDescription = "Close", tint = TextMuted)
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))

                // Admin Gateway Details & QR Visual
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = CardHighlight,
                    border = borderStroke(1.dp, GoldAccent.copy(alpha = 0.5f)),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            // QR Visual Box
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = Color.White,
                                modifier = Modifier.size(72.dp)
                            ) {
                                Box(contentAlignment = Alignment.Center) {
                                    Icon(
                                        imageVector = Icons.Default.QrCode2,
                                        contentDescription = "UPI QR Code",
                                        tint = Color.Black,
                                        modifier = Modifier.size(60.dp)
                                    )
                                }
                            }

                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = "UPI ID (Scan QR or Tap Copy):",
                                    color = TextMuted,
                                    fontSize = 10.sp
                                )
                                Text(
                                    text = bankConfig.upiId,
                                    color = GoldAccent,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.ExtraBold,
                                    fontFamily = FontFamily.Monospace
                                )
                                Text(
                                    text = bankConfig.upiName,
                                    color = ElectricCyan,
                                    fontSize = 10.sp
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Button(
                                        onClick = {
                                            clipboardManager.setText(AnnotatedString(bankConfig.upiId))
                                            copiedLabel = "UPI ID Copied!"
                                        },
                                        colors = ButtonDefaults.buttonColors(containerColor = CardBorder),
                                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp),
                                        shape = RoundedCornerShape(6.dp),
                                        modifier = Modifier.height(26.dp)
                                    ) {
                                        Text("📋 Copy UPI", fontSize = 10.sp, color = TextPrimary)
                                    }
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(10.dp))
                        Divider(color = CardBorder, thickness = 0.8.dp)
                        Spacer(modifier = Modifier.height(8.dp))

                        // Bank Details
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Bank Name:", color = TextMuted, fontSize = 11.sp)
                            Text(bankConfig.bankName, color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 11.sp)
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("A/C No:", color = TextMuted, fontSize = 11.sp)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(bankConfig.accNo, color = GoldAccent, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = "Copy",
                                    color = ElectricCyan,
                                    fontSize = 10.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.clickable {
                                        clipboardManager.setText(AnnotatedString(bankConfig.accNo))
                                        copiedLabel = "A/C Copied!"
                                    }
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("IFSC Code:", color = TextMuted, fontSize = 11.sp)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(bankConfig.ifsc, color = ElectricCyan, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = "Copy",
                                    color = ElectricCyan,
                                    fontSize = 10.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.clickable {
                                        clipboardManager.setText(AnnotatedString(bankConfig.ifsc))
                                        copiedLabel = "IFSC Copied!"
                                    }
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Holder Name:", color = TextMuted, fontSize = 11.sp)
                            Text(bankConfig.holder, color = TextPrimary, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Limits:", color = TextMuted, fontSize = 11.sp)
                            Text("₹${bankConfig.minDep} – ₹${bankConfig.maxDep}", color = NeonGreen, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }

                        if (copiedLabel != null) {
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(text = "✅ ${copiedLabel ?: ""}", color = NeonGreen, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Presets
                Text(text = "Deposit Amount (₹):", color = TextSecondary, fontSize = 12.sp)
                Spacer(modifier = Modifier.height(4.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    listOf(50000L to "₹500", 100000L to "₹1,000", 500000L to "₹5,000", 1000000L to "₹10,000").forEach { (cents, label) ->
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .clip(RoundedCornerShape(8.dp))
                                .background(if (selectedAmountCents == cents) NeonGreen else CardHighlight)
                                .clickable {
                                    selectedAmountCents = cents
                                    customAmountText = (cents / 100).toString()
                                }
                                .padding(vertical = 8.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = label,
                                color = if (selectedAmountCents == cents) ObsidianBg else TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 11.sp
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = customAmountText,
                    onValueChange = {
                        customAmountText = it
                        val rupees = it.toDoubleOrNull() ?: 0.0
                        selectedAmountCents = (rupees * 100).toLong()
                    },
                    label = { Text("Custom Amount (₹)") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = NeonGreen,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                Text(text = "Payment Mode:", color = TextSecondary, fontSize = 12.sp)
                Spacer(modifier = Modifier.height(4.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    listOf("UPI Instant", "IMPS Bank", "NEFT / RTGS").forEach { mode ->
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .clip(RoundedCornerShape(8.dp))
                                .background(if (selectedProvider == mode) ElectricCyan else CardHighlight)
                                .clickable { selectedProvider = mode }
                                .padding(vertical = 6.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = mode,
                                color = if (selectedProvider == mode) ObsidianBg else TextPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 11.sp
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))
                Text(
                    text = "12-Digit UTR / Transaction Reference Number:",
                    color = GoldAccent,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.height(4.dp))
                OutlinedTextField(
                    value = utrText,
                    onValueChange = { utrText = it },
                    placeholder = { Text("e.g. 429188402911") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = GoldAccent,
                        unfocusedBorderColor = CardBorder
                    )
                )

                if (errorMsg != null) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(text = errorMsg ?: "", color = NeonRed, fontSize = 11.sp)
                }

                Spacer(modifier = Modifier.height(14.dp))
                Button(
                    onClick = {
                        val amount = customAmountText.toDoubleOrNull() ?: 0.0
                        if (amount <= 0.0) {
                            errorMsg = "Please enter a valid deposit amount"
                            return@Button
                        }
                        if (utrText.trim().length < 6) {
                            errorMsg = "Please enter the 12-digit UTR reference number"
                            return@Button
                        }
                        val cents = (amount * 100).toLong()
                        onDeposit(cents, selectedProvider, utrText.trim())
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = NeonGreen)
                ) {
                    Text(
                        text = "Submit Deposit Request with UTR",
                        color = ObsidianBg,
                        fontWeight = FontWeight.Bold
                    )
                }

                Spacer(modifier = Modifier.height(6.dp))
                OutlinedButton(
                    onClick = {
                        onDeposit(100000L, "Demo Fast Deposit", "DEMO_INSTANT_${System.currentTimeMillis()}")
                    },
                    modifier = Modifier.fillMaxWidth(),
                    border = borderStroke(1.dp, GoldAccent.copy(alpha = 0.5f))
                ) {
                    Text("⚡ Instant Demo Credit (+₹1,000)", color = GoldAccent, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
fun WithdrawDialog(
    availableBalanceCents: Long,
    onDismiss: () -> Unit,
    onWithdraw: (
        amountCents: Long,
        upiId: String,
        bankName: String,
        accNo: String,
        ifsc: String,
        bankingName: String
    ) -> Unit
) {
    var amountText by remember { mutableStateOf("1000") }
    var bankingNameText by remember { mutableStateOf("Rahul Kumar Sharma") }
    var upiIdText by remember { mutableStateOf("rahul@oksbi") }
    var bankNameText by remember { mutableStateOf("State Bank of India (SBI)") }
    var accNoText by remember { mutableStateOf("40928172901") }
    var ifscText by remember { mutableStateOf("SBIN0001824") }
    var errorMsg by remember { mutableStateOf<String?>(null) }

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = SurfaceDark,
            border = borderStroke(1.dp, ElectricCyan),
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 12.dp)
        ) {
            Column(
                modifier = Modifier
                    .padding(16.dp)
                    .verticalScroll(rememberScrollState())
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column {
                        Text(
                            text = "Request Fund Withdrawal",
                            color = TextPrimary,
                            fontSize = 17.sp,
                            fontWeight = FontWeight.Bold
                        )
                        Text(
                            text = "Admin Payout Approval Queue",
                            color = ElectricCyan,
                            fontSize = 11.sp
                        )
                    }
                    IconButton(onClick = onDismiss, modifier = Modifier.size(28.dp)) {
                        Icon(imageVector = Icons.Default.Close, contentDescription = "Close", tint = TextMuted)
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = CardHighlight,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Available to Withdraw:", color = TextMuted, fontSize = 11.sp)
                        Text(
                            text = MoneyUtils.formatCents(availableBalanceCents),
                            color = GoldAccent,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.ExtraBold
                        )
                    }
                }

                Spacer(modifier = Modifier.height(10.dp))
                OutlinedTextField(
                    value = amountText,
                    onValueChange = { amountText = it },
                    label = { Text("Withdrawal Amount (₹)") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = bankingNameText,
                    onValueChange = { bankingNameText = it },
                    label = { Text("Banking Name (Account Holder)") },
                    placeholder = { Text("Full name as per bank records") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = upiIdText,
                    onValueChange = { upiIdText = it },
                    label = { Text("UPI ID") },
                    placeholder = { Text("e.g. rahul@oksbi") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = bankNameText,
                    onValueChange = { bankNameText = it },
                    label = { Text("Bank Name") },
                    placeholder = { Text("e.g. State Bank of India, HDFC") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = accNoText,
                    onValueChange = { accNoText = it },
                    label = { Text("Bank Account Number") },
                    placeholder = { Text("Enter bank account number") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = ifscText,
                    onValueChange = { ifscText = it.uppercase() },
                    label = { Text("IFSC Code") },
                    placeholder = { Text("e.g. SBIN0001824") },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                if (errorMsg != null) {
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(text = errorMsg ?: "", color = NeonRed, fontSize = 11.sp)
                }

                Spacer(modifier = Modifier.height(14.dp))
                Button(
                    onClick = {
                        val rupees = amountText.toDoubleOrNull() ?: 0.0
                        val cents = (rupees * 100).toLong()
                        if (cents <= 0L) {
                            errorMsg = "Please enter a valid amount"
                        } else if (cents > availableBalanceCents) {
                            errorMsg = "Amount exceeds available balance"
                        } else if (bankingNameText.isBlank()) {
                            errorMsg = "Please enter banking / account holder name"
                        } else if (upiIdText.isBlank() && (accNoText.isBlank() || ifscText.isBlank())) {
                            errorMsg = "Please provide UPI ID or Bank Account Number & IFSC"
                        } else {
                            onWithdraw(
                                cents,
                                upiIdText.trim(),
                                bankNameText.trim(),
                                accNoText.trim(),
                                ifscText.trim(),
                                bankingNameText.trim()
                            )
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = ElectricCyan)
                ) {
                    Text(text = "Submit Withdrawal Request to Admin", color = ObsidianBg, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}
