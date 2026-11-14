package com.example.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.data.model.MoneyUtils
import com.example.data.model.ReferralCommissionEntity
import com.example.domain.ServerAffiliateCommission
import com.example.domain.ServerAffiliateMember
import com.example.ui.MainViewModel
import com.example.ui.components.borderStroke
import com.example.ui.theme.*
import java.text.SimpleDateFormat
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
    val context = LocalContext.current

    val totalCommissionCents = serverAffiliateStats?.let {
        (it.lifetimeCommissionRupees * 100.0).roundToLong()
    } ?: commissions.sumOf { it.commissionAmount }

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

    val levelRates = listOf(
        1 to 0.0100,
        2 to 0.0075,
        3 to 0.0060,
        4 to 0.0050,
        5 to 0.0030,
        6 to 0.0020
    )

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
                text = "Earn automated commissions across 6 hierarchical tiers backed by SQLite persistence",
                color = TextSecondary,
                fontSize = 12.sp
            )
            Spacer(modifier = Modifier.height(14.dp))

            // Summary Stats Card
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = SurfaceDark,
                border = borderStroke(1.dp, CardBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "LIFETIME COMMISSION",
                        color = TextSecondary,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        letterSpacing = 1.sp
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = MoneyUtils.formatCents(totalCommissionCents),
                        color = NeonGreen,
                        fontSize = 30.sp,
                        fontWeight = FontWeight.Black
                    )

                    Spacer(modifier = Modifier.height(14.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        MiniStat(
                            title = "Today's Commission",
                            value = MoneyUtils.formatCents(todayCommissionCents),
                            modifier = Modifier.weight(1f)
                        )
                        MiniStat(
                            title = "Network Turnover",
                            value = MoneyUtils.formatCents(totalTurnoverCents),
                            modifier = Modifier.weight(1f)
                        )
                        MiniStat(
                            title = "Subordinates",
                            value = "$subordinateCount",
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(16.dp))

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
                            modifier = Modifier.testTag("copy_ref_link_btn")
                        ) {
                            Icon(imageVector = Icons.Default.Share, contentDescription = null, tint = ObsidianBg, modifier = Modifier.size(16.dp))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("Share Link", color = ObsidianBg, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(18.dp))

            // Interactive 6-Level Hierarchy Tree Visualization
            Text(
                text = "Hierarchical 6-Level Structure",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp
            )
            Spacer(modifier = Modifier.height(8.dp))
            ReferralTreeVisualizer(
                activeUsername = activeUser?.username ?: serverAffiliateStats?.userName ?: "Guest",
                members = serverMembers
            )
            Spacer(modifier = Modifier.height(18.dp))

            // Commission Rate Matrix
            Text(
                text = "Commission Breakdown by Tier",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp
            )
            Spacer(modifier = Modifier.height(8.dp))
            CommissionRateTable(
                levelRates = levelRates,
                commissions = commissions,
                serverCommissions = serverCommissions
            )
            Spacer(modifier = Modifier.height(18.dp))

            // Recent Commission Ledger
            val displayCount = if (serverCommissions.isNotEmpty()) serverCommissions.size else commissions.size
            Text(
                text = "Referral Commission Ledger ($displayCount)",
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
                    "0 referrals yet"
                } else {
                    val names = tierMembers.take(3).joinToString(", ") { it.name }
                    val extra = if (tierMembers.size > 3) " +${tierMembers.size - 3} more" else ""
                    "${tierMembers.size} member(s): $names$extra"
                }
                val title = if (tier == 1) "Tier 1: Direct Referrals" else "Tier $tier: Sub-Level $tier"
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
fun CommissionRateTable(
    levelRates: List<Pair<Int, Double>>,
    commissions: List<ReferralCommissionEntity>,
    serverCommissions: List<ServerAffiliateCommission> = emptyList()
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
                Text(text = "Tier", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(1f))
                Text(text = "Rate %", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(1f))
                Text(text = "Commission Earned", color = TextMuted, fontSize = 11.sp, modifier = Modifier.weight(1.5f))
            }
            Divider(color = CardBorder)

            levelRates.forEach { (level, rate) ->
                val levelEarned = if (serverCommissions.isNotEmpty()) {
                    serverCommissions.filter { it.level == level }.sumOf { (it.commissionAmountRupees * 100.0).roundToLong() }
                } else {
                    commissions.filter { it.level == level }.sumOf { it.commissionAmount }
                }
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Level $level",
                        color = TextPrimary,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1f)
                    )
                    Text(
                        text = "${"%.2f".format(rate * 100)}%",
                        color = GoldAccent,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f)
                    )
                    Text(
                        text = MoneyUtils.formatCents(levelEarned),
                        color = if (levelEarned > 0) NeonGreen else TextSecondary,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1.5f)
                    )
                }
            }
        }
    }
}

@Composable
fun ServerCommissionLedgerItem(commission: ServerAffiliateCommission) {
    val commCents = (commission.commissionAmountRupees * 100.0).roundToLong()
    val eligCents = (commission.eligibleAmountRupees * 100.0).roundToLong()

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
                    text = commission.status,
                    color = ElectricCyan,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@Composable
fun CommissionLedgerItem(commission: ReferralCommissionEntity) {
    val dateFormat = SimpleDateFormat("dd MMM, HH:mm", Locale.getDefault())
    val dateStr = dateFormat.format(Date(commission.createdAt))

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
                    text = "SETTLED",
                    color = ElectricCyan,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}
