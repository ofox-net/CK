package com.example.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.data.model.MoneyUtils
import com.example.data.model.ReferralCommissionEntity
import com.example.domain.GlobalRoundClock
import com.example.domain.ServerAffiliateClaim
import com.example.domain.ServerAffiliateCommission
import com.example.domain.ServerAffiliateLevelBreakdown
import com.example.domain.ServerAffiliateMember
import com.example.ui.MainViewModel
import com.example.ui.components.borderStroke
import com.example.ui.theme.*
import java.util.*
import kotlin.math.roundToLong

@Composable
fun AffiliateScreen(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier
) {
    val activeUser by viewModel.activeUser.collectAsState()
    val commissions by viewModel.userCommissions.collectAsState()
    val descendants by viewModel.userDescendants.collectAsState()
    val serverAffiliateStats by viewModel.serverAffiliateStats.collectAsState()
    val isClaiming by viewModel.isClaimingAffiliate.collectAsState()
    val context = LocalContext.current

    var selectedSection by remember { mutableStateOf("ALL") } // ALL, CLAIMS, TEAM, COMMISSIONS
    var selectedTeamLevel by remember { mutableStateOf<Int?>(null) }

    val totalCommissionCents = serverAffiliateStats?.let {
        (it.lifetimeCommissionRupees * 100.0).roundToLong()
    } ?: commissions.sumOf { it.commissionAmount }

    val claimableCents = serverAffiliateStats?.let {
        (it.claimableBalanceRupees * 100.0).roundToLong()
    } ?: commissions.filter { it.status.uppercase() in listOf("UNCLAIMED", "PENDING") }.sumOf { it.commissionAmount }

    val totalClaimedCents = serverAffiliateStats?.let {
        (it.totalClaimedRupees * 100.0).roundToLong()
    } ?: 0L

    val todayCommissionCents = serverAffiliateStats?.let {
        (it.todayCommissionRupees * 100.0).roundToLong()
    } ?: commissions.filter {
        val cal1 = Calendar.getInstance().apply { timeInMillis = it.createdAt }
        val cal2 = Calendar.getInstance()
        cal1.get(Calendar.DAY_OF_YEAR) == cal2.get(Calendar.DAY_OF_YEAR) &&
                cal1.get(Calendar.YEAR) == cal2.get(Calendar.YEAR)
    }.sumOf { it.commissionAmount }

    val totalTurnoverCents = serverAffiliateStats?.let {
        (it.networkTurnoverRupees * 100.0).roundToLong()
    } ?: commissions.sumOf { it.eligibleAmount }

    val subordinateCount = serverAffiliateStats?.teamCount ?: descendants.size
    val serverMembers = serverAffiliateStats?.members.orEmpty()
    val serverCommissions = serverAffiliateStats?.recentCommissions.orEmpty()
    val claimHistory = serverAffiliateStats?.claimHistory.orEmpty()

    val levelRates = listOf(
        1 to 0.0100,
        2 to 0.0075,
        3 to 0.0060,
        4 to 0.0050,
        5 to 0.0030,
        6 to 0.0020
    )

    val breakdownRows = remember(serverAffiliateStats, serverMembers, serverCommissions, commissions) {
        val srv = serverAffiliateStats?.levelBreakdown.orEmpty()
        if (srv.size == 6) srv else levelRates.map { (lvl, rt) ->
            val mems = serverMembers.filter { it.tier == lvl }
            val lvlEarned = if (serverCommissions.isNotEmpty()) {
                serverCommissions.filter { it.level == lvl }.sumOf { it.commissionAmountRupees }
            } else {
                commissions.filter { it.level == lvl }.sumOf { it.commissionAmount / 100.0 }
            }
            ServerAffiliateLevelBreakdown(
                level = lvl,
                label = if (lvl == 1) "Level 1 (Direct)" else "Level $lvl",
                rate = rt,
                ratePercent = rt * 100.0,
                membersCount = mems.size,
                turnoverRupees = mems.sumOf { it.turnoverRupees },
                earnedCommissionRupees = lvlEarned,
                unclaimedCommissionRupees = 0.0,
                claimedCommissionRupees = lvlEarned
            )
        }
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
                text = "6-Level Affiliate Multi-Tier Network",
                color = TextPrimary,
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "Commissions accumulate across Levels 1–6 and credit to your Main Wallet when you claim.",
                color = TextSecondary,
                fontSize = 12.sp
            )
            Spacer(modifier = Modifier.height(14.dp))

            // Claim-Based Affiliate Vault Card
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = SurfaceDark,
                border = borderStroke(1.dp, NeonGreen.copy(alpha = 0.5f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "CLAIMABLE AFFILIATE BONUS",
                                color = NeonGreen,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                letterSpacing = 0.8.sp
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = MoneyUtils.formatCents(claimableCents),
                                color = TextPrimary,
                                fontSize = 28.sp,
                                fontWeight = FontWeight.Black
                            )
                            Text(
                                text = if (claimableCents > 0) "Ready to claim to Main Wallet" else "No pending claimable bonus yet",
                                color = TextMuted,
                                fontSize = 10.sp
                            )
                        }

                        Button(
                            onClick = { viewModel.claimAffiliateEarnings() },
                            enabled = !isClaiming && claimableCents > 0,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = GoldAccent,
                                disabledContainerColor = CardHighlight
                            ),
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier
                                .heightIn(min = 48.dp)
                                .testTag("claim_affiliate_btn")
                        ) {
                            Icon(
                                imageVector = Icons.Default.AccountBalanceWallet,
                                contentDescription = "Claim to Wallet",
                                tint = if (claimableCents > 0) ObsidianBg else TextMuted,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = if (isClaiming) "Claiming..." else "Claim",
                                color = if (claimableCents > 0) ObsidianBg else TextMuted,
                                fontWeight = FontWeight.Black,
                                fontSize = 13.sp
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(14.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        MiniStat(
                            title = "Lifetime Earned",
                            value = MoneyUtils.formatCents(totalCommissionCents),
                            modifier = Modifier.weight(1f)
                        )
                        MiniStat(
                            title = "Total Claimed",
                            value = MoneyUtils.formatCents(totalClaimedCents),
                            modifier = Modifier.weight(1f)
                        )
                        MiniStat(
                            title = "Today's Earned",
                            value = MoneyUtils.formatCents(todayCommissionCents),
                            modifier = Modifier.weight(1f)
                        )
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        MiniStat(
                            title = "Network Turnover",
                            value = MoneyUtils.formatCents(totalTurnoverCents),
                            modifier = Modifier.weight(1f)
                        )
                        MiniStat(
                            title = "Total Team",
                            value = "$subordinateCount Users",
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(14.dp))

            // Referral Link & Code
            val referralCode = serverAffiliateStats?.referralCode?.takeIf { it.isNotBlank() }
                ?: activeUser?.referralCode?.takeIf { it.isNotBlank() }
                ?: "----"
            val referralLink = if (referralCode != "----") "https://ais-pre-zgi6cruhcpqtgg5frvcozc-221262354191.asia-southeast1.run.app/?ref=$referralCode" else ""

            Surface(
                shape = RoundedCornerShape(14.dp),
                color = SurfaceDark,
                border = borderStroke(1.dp, GoldAccent.copy(alpha = 0.5f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column {
                            Text(text = "Your Referral Code", color = TextSecondary, fontSize = 11.sp)
                            Text(
                                text = referralCode,
                                color = GoldAccent,
                                fontSize = 18.sp,
                                fontWeight = FontWeight.Black,
                                letterSpacing = 2.sp
                            )
                        }

                        Button(
                            onClick = {
                                if (referralLink.isNotBlank()) {
                                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                    clipboard.setPrimaryClip(ClipData.newPlainText("Referral Link", referralLink))
                                    viewModel.postNotification("Referral link copied to clipboard!")
                                } else {
                                    viewModel.postNotification("Sign in to share your referral link!", false)
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = GoldAccent),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier
                                .heightIn(min = 48.dp)
                                .testTag("copy_ref_link_btn")
                        ) {
                            Icon(imageVector = Icons.Default.Share, contentDescription = "Share referral link", tint = ObsidianBg, modifier = Modifier.size(16.dp))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Share Link", color = ObsidianBg, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(16.dp))

            // Column-Wise Level 1 - Level 6 Breakdown Table
            Text(
                text = "Level 1–6 Member & Earning Breakdown",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp
            )
            Spacer(modifier = Modifier.height(8.dp))
            LevelBreakdownMatrixTable(
                rows = breakdownRows,
                onSelectLevel = { lvl ->
                    selectedTeamLevel = lvl
                    selectedSection = "TEAM"
                }
            )
            Spacer(modifier = Modifier.height(16.dp))

            // Interactive Section Switcher Pills
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                listOf(
                    "ALL" to "All Sections",
                    "CLAIMS" to "Claim History (${claimHistory.size})",
                    "TEAM" to "Team ($subordinateCount)",
                    "COMMISSIONS" to "Commission Log (${serverCommissions.size})"
                ).forEach { (key, label) ->
                    FilterChip(
                        selected = selectedSection == key,
                        onClick = { selectedSection = key },
                        label = { Text(label, fontSize = 11.sp, fontWeight = FontWeight.Bold) },
                        modifier = Modifier.testTag("aff_section_$key")
                    )
                }
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        // Section 1: Affiliate Claim Transactions Ledger
        if (selectedSection == "ALL" || selectedSection == "CLAIMS") {
            item {
                Surface(
                    shape = RoundedCornerShape(14.dp),
                    color = SurfaceDark,
                    border = borderStroke(1.dp, NeonGreen.copy(alpha = 0.4f)),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Text(
                            text = "Affiliate Claim Transactions",
                            color = TextPrimary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 15.sp
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            MiniStat(
                                title = "Total Claimed to Wallet",
                                value = MoneyUtils.formatCents(totalClaimedCents),
                                modifier = Modifier.weight(1f)
                            )
                            MiniStat(
                                title = "Pending Claim",
                                value = MoneyUtils.formatCents(claimableCents),
                                modifier = Modifier.weight(1f)
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.height(8.dp))
            }
            if (claimHistory.isEmpty()) {
                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = SurfaceDark,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Box(modifier = Modifier.padding(16.dp), contentAlignment = Alignment.Center) {
                            Text(
                                text = "No affiliate claim transactions yet. Tap Claim above to move rewards to your wallet.",
                                color = TextMuted,
                                fontSize = 12.sp
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(12.dp))
                }
            } else {
                items(claimHistory, key = { "claim_${it.id}" }) { claim ->
                    AffiliateClaimLedgerItem(claim = claim)
                    Spacer(modifier = Modifier.height(8.dp))
                }
            }
        }

        // Section 2: L1-L6 Members Directory
        if (selectedSection == "ALL" || selectedSection == "TEAM") {
            item {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "6-Level Team Directory",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )
                Spacer(modifier = Modifier.height(6.dp))
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    FilterChip(
                        selected = selectedTeamLevel == null,
                        onClick = { selectedTeamLevel = null },
                        label = { Text("All", fontSize = 11.sp) }
                    )
                    (1..6).forEach { lvl ->
                        FilterChip(
                            selected = selectedTeamLevel == lvl,
                            onClick = { selectedTeamLevel = lvl },
                            label = { Text("L$lvl", fontSize = 11.sp) }
                        )
                    }
                }
                Spacer(modifier = Modifier.height(8.dp))
                ReferralTreeVisualizer(
                    activeUsername = activeUser?.username ?: serverAffiliateStats?.userName ?: "Guest",
                    members = serverMembers
                )
                Spacer(modifier = Modifier.height(10.dp))
            }

            val filteredMembers = if (selectedTeamLevel == null) {
                serverMembers
            } else {
                serverMembers.filter { it.tier == selectedTeamLevel }
            }
            if (filteredMembers.isEmpty()) {
                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = SurfaceDark,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Box(modifier = Modifier.padding(16.dp), contentAlignment = Alignment.Center) {
                            Text(
                                text = if (selectedTeamLevel == null) "No team members yet." else "No members in Level $selectedTeamLevel yet.",
                                color = TextMuted,
                                fontSize = 12.sp
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(12.dp))
                }
            } else {
                items(filteredMembers, key = { "mem_${it.id}" }) { member ->
                    MemberRowCard(member = member)
                    Spacer(modifier = Modifier.height(8.dp))
                }
            }
        }

        // Section 3: 6-Level Commission Log
        if (selectedSection == "ALL" || selectedSection == "COMMISSIONS") {
            item {
                val displayCount = if (serverCommissions.isNotEmpty()) serverCommissions.size else commissions.size
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "6-Level Commission History ($displayCount)",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )
                Spacer(modifier = Modifier.height(8.dp))
            }

            if (serverCommissions.isNotEmpty()) {
                items(serverCommissions, key = { it.id }) { comm ->
                    ServerCommissionLedgerItem(commission = comm)
                    Spacer(modifier = Modifier.height(8.dp))
                }
            } else if (commissions.isEmpty()) {
                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = SurfaceDark,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Box(modifier = Modifier.padding(20.dp), contentAlignment = Alignment.Center) {
                            Text(
                                text = "No commissions recorded yet. Share your referral code to earn 6-tier commissions!",
                                color = TextMuted,
                                fontSize = 12.sp
                            )
                        }
                    }
                }
            } else {
                items(commissions, key = { it.id }) { comm ->
                    CommissionLedgerItem(commission = comm)
                    Spacer(modifier = Modifier.height(8.dp))
                }
            }
        }

        item { Spacer(modifier = Modifier.height(30.dp)) }
    }
}

@Composable
fun MiniStat(
    title: String,
    value: String,
    modifier: Modifier = Modifier
) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = CardHighlight,
        modifier = modifier
    ) {
        Column(modifier = Modifier.padding(8.dp)) {
            Text(text = title, color = TextMuted, fontSize = 10.sp)
            Spacer(modifier = Modifier.height(2.dp))
            Text(text = value, color = TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
fun LevelBreakdownMatrixTable(
    rows: List<ServerAffiliateLevelBreakdown>,
    onSelectLevel: (Int) -> Unit
) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(text = "Level", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(1.2f))
                Text(text = "Rate", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(0.8f))
                Text(text = "Members", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(1f))
                Text(text = "Turnover", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(1.1f))
                Text(text = "Earned", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(1.1f))
            }
            HorizontalDivider(color = CardBorder)

            rows.forEach { row ->
                val earnedCents = (row.earnedCommissionRupees * 100.0).roundToLong()
                val turnCents = (row.turnoverRupees * 100.0).roundToLong()
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSelectLevel(row.level) }
                        .padding(vertical = 9.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = if (row.level == 1) "L1 Direct" else "Level ${row.level}",
                        color = TextPrimary,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1.2f)
                    )
                    Text(
                        text = "${"%.2f".format(row.ratePercent)}%",
                        color = GoldAccent,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(0.8f)
                    )
                    Text(
                        text = "${row.membersCount} Users",
                        color = ElectricCyan,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1f)
                    )
                    Text(
                        text = MoneyUtils.formatCents(turnCents),
                        color = TextSecondary,
                        fontSize = 11.sp,
                        modifier = Modifier.weight(1.1f)
                    )
                    Text(
                        text = "+${MoneyUtils.formatCents(earnedCents)}",
                        color = if (earnedCents > 0) NeonGreen else TextSecondary,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1.1f)
                    )
                }
            }
        }
    }
}

@Composable
fun AffiliateClaimLedgerItem(claim: ServerAffiliateClaim) {
    val amtCents = (claim.amountRupees * 100.0).roundToLong()
    val afterCents = (claim.balanceAfterRupees * 100.0).roundToLong()
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, NeonGreen.copy(alpha = 0.25f)),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = claim.title.ifBlank { "Affiliate Commission Claimed" },
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp
                )
                Text(
                    text = "${claim.createdAt} • ${claim.id}",
                    color = ElectricCyan,
                    fontSize = 10.sp
                )
                Text(
                    text = claim.ref,
                    color = TextMuted,
                    fontSize = 10.sp
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "+${MoneyUtils.formatCents(amtCents)}",
                    color = NeonGreen,
                    fontWeight = FontWeight.Black,
                    fontSize = 14.sp
                )
                Text(
                    text = "Bal: ${MoneyUtils.formatCents(afterCents)}",
                    color = GoldAccent,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.SemiBold
                )
            }
        }
    }
}

@Composable
fun MemberRowCard(member: ServerAffiliateMember) {
    val turnCents = (member.turnoverRupees * 100.0).roundToLong()
    val commCents = (member.commissionRupees * 100.0).roundToLong()
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
            Column(modifier = Modifier.weight(1f)) {
                Text(text = "${member.name} (Level ${member.tier})", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                Text(text = "Joined ${member.joined} • Turnover ${MoneyUtils.formatCents(turnCents)}", color = TextMuted, fontSize = 10.sp)
            }
            Text(
                text = "+${MoneyUtils.formatCents(commCents)}",
                color = NeonGreen,
                fontWeight = FontWeight.Bold,
                fontSize = 13.sp
            )
        }
    }
}

@Composable
fun ReferralTreeVisualizer(
    activeUsername: String,
    members: List<ServerAffiliateMember> = emptyList()
) {
    val tierColors = mapOf(
        1 to NeonGreen,
        2 to ElectricCyan,
        3 to NeonViolet,
        4 to AmberGlow,
        5 to TextSecondary,
        6 to TextMuted
    )
    val tierRates = mapOf(
        1 to "1.00%",
        2 to "0.75%",
        3 to "0.60%",
        4 to "0.50%",
        5 to "0.30%",
        6 to "0.20%"
    )

    Surface(
        shape = RoundedCornerShape(14.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            TreeRow(depth = 0, title = "👑 You ($activeUsername)", subtitle = "Root Beneficiary", rate = "--", color = GoldAccent)
            for (tier in 1..6) {
                val tierMembers = members.filter { it.tier == tier }
                val subtitle = if (tierMembers.isEmpty()) {
                    "0 members"
                } else {
                    val names = tierMembers.take(3).joinToString(", ") { it.name }
                    val extra = if (tierMembers.size > 3) " +${tierMembers.size - 3} more" else ""
                    "${tierMembers.size} member(s): $names$extra"
                }
                val title = if (tier == 1) "Level 1: Direct Referrals" else "Level $tier: Sub-Level $tier"
                TreeRow(
                    depth = tier,
                    title = title,
                    subtitle = subtitle,
                    rate = tierRates[tier] ?: "0.20%",
                    color = tierColors[tier] ?: TextMuted
                )
            }
        }
    }
}

@Composable
fun TreeRow(depth: Int, title: String, subtitle: String, rate: String, color: androidx.compose.ui.graphics.Color) {
    val indent = (depth * 14).dp
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = indent, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = if (depth == 0) "●" else "└──",
            color = color,
            fontSize = 12.sp,
            fontFamily = FontFamily.Monospace
        )
        Spacer(modifier = Modifier.width(6.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, color = TextPrimary, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
            Text(text = subtitle, color = TextMuted, fontSize = 10.sp)
        }
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(4.dp))
                .background(color.copy(alpha = 0.2f))
                .padding(horizontal = 6.dp, vertical = 2.dp)
        ) {
            Text(text = rate, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
fun ServerCommissionLedgerItem(commission: ServerAffiliateCommission) {
    val commCents = (commission.commissionAmountRupees * 100.0).roundToLong()
    val eligCents = (commission.eligibleAmountRupees * 100.0).roundToLong()
    val stUpper = commission.status.uppercase()
    val statusColor = if (stUpper == "UNCLAIMED" || stUpper == "PENDING") AmberGlow else ElectricCyan

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
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.weight(1f)) {
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .background(NeonGreen.copy(alpha = 0.15f)),
                    contentAlignment = Alignment.Center
                ) {
                    Text(text = "L${commission.level}", color = NeonGreen, fontWeight = FontWeight.Black, fontSize = 12.sp)
                }
                Spacer(modifier = Modifier.width(10.dp))
                Column {
                    Text(
                        text = "L${commission.level} from ${commission.sourceUserName}",
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp
                    )
                    Text(
                        text = "${commission.createdAt} • Wager: ${MoneyUtils.formatCents(eligCents)}",
                        color = TextMuted,
                        fontSize = 10.sp
                    )
                }
            }

            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "+${MoneyUtils.formatCents(commCents)}",
                    color = NeonGreen,
                    fontWeight = FontWeight.Black,
                    fontSize = 14.sp
                )
                Text(
                    text = stUpper,
                    color = statusColor,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@Composable
fun CommissionLedgerItem(commission: ReferralCommissionEntity) {
    val dateStr = GlobalRoundClock.formatIstShort(commission.createdAt)
    val stUpper = commission.status.uppercase()
    val statusColor = if (stUpper == "UNCLAIMED" || stUpper == "PENDING") AmberGlow else ElectricCyan

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
                        .background(NeonGreen.copy(alpha = 0.15f)),
                    contentAlignment = Alignment.Center
                ) {
                    Text(text = "L${commission.level}", color = NeonGreen, fontWeight = FontWeight.Black, fontSize = 12.sp)
                }
                Spacer(modifier = Modifier.width(10.dp))
                Column {
                    Text(
                        text = "Level ${commission.level} Commission",
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp
                    )
                    Text(
                        text = "$dateStr • Source Wager: ${MoneyUtils.formatCents(commission.eligibleAmount)}",
                        color = TextMuted,
                        fontSize = 10.sp
                    )
                }
            }

            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "+${MoneyUtils.formatCents(commission.commissionAmount)}",
                    color = NeonGreen,
                    fontWeight = FontWeight.Black,
                    fontSize = 14.sp
                )
                Text(
                    text = stUpper,
                    color = statusColor,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}
