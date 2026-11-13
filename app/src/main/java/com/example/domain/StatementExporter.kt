package com.example.domain

import com.example.data.model.BetEntity
import com.example.data.model.GameMarkets
import com.example.data.model.GameRoundEntity
import com.example.data.model.MoneyUtils
import com.example.data.model.ReferralCommissionEntity
import com.example.data.model.UserEntity
import com.example.data.model.WalletEntity
import com.example.data.model.WalletLedgerEntity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class AccountStatementSummary(
    val days: Int = 90,
    val availableBalanceCents: Long = 0L,
    val lockedBalanceCents: Long = 0L,
    val totalBetsCount: Int = 0,
    val wonBetsCount: Int = 0,
    val lostBetsCount: Int = 0,
    val pendingBetsCount: Int = 0,
    val cancelledBetsCount: Int = 0,
    val totalBetWageredCents: Long = 0L,
    val totalBetWonCents: Long = 0L,
    val netBetProfitLossCents: Long = 0L,
    val totalReferEarnCents: Long = 0L,
    val totalDepositCents: Long = 0L,
    val totalWithdrawalCents: Long = 0L
)

object StatementExporter {
    const val RETENTION_DAYS = 90
    const val DAY_MILLIS = 86_400_000L

    fun cutoffTimestampMs(days: Int = RETENTION_DAYS, nowMs: Long = System.currentTimeMillis()): Long {
        val clampedDays = days.coerceIn(1, RETENTION_DAYS)
        return nowMs - (clampedDays.toLong() * DAY_MILLIS)
    }

    fun computeSummary(
        wallet: WalletEntity?,
        bets: List<BetEntity>,
        ledger: List<WalletLedgerEntity>,
        commissions: List<ReferralCommissionEntity>,
        days: Int = RETENTION_DAYS,
        nowMs: Long = System.currentTimeMillis()
    ): AccountStatementSummary {
        val clampedDays = days.coerceIn(1, RETENTION_DAYS)
        val cutoff = cutoffTimestampMs(clampedDays, nowMs)

        val windowBets = bets.filter { it.createdAt >= cutoff }
        var wonCount = 0
        var lostCount = 0
        var pendingCount = 0
        var cancelledCount = 0
        var wageredCents = 0L
        var wonCents = 0L

        for (bet in windowBets) {
            when (bet.status.uppercase()) {
                "WON" -> {
                    wonCount++
                    wageredCents += bet.amount
                    wonCents += bet.actualPayout
                }
                "LOST" -> {
                    lostCount++
                    wageredCents += bet.amount
                }
                "CANCELLED", "REFUNDED" -> {
                    cancelledCount++
                }
                else -> {
                    pendingCount++
                    wageredCents += bet.amount
                }
            }
        }

        val windowLedger = ledger.filter { it.createdAt >= cutoff }
        val depositsCents = windowLedger
            .filter { it.entryType == "DEPOSIT" && it.direction == "CREDIT" }
            .sumOf { it.amount }

        val withdrawalsDebitCents = windowLedger
            .filter { it.entryType == "WITHDRAWAL" && it.direction == "DEBIT" }
            .sumOf { it.amount }
        val withdrawalsRefundedCents = windowLedger
            .filter { it.entryType == "REFUND" && it.referenceType.contains("WITHDRAWAL", ignoreCase = true) }
            .sumOf { it.amount }
        val netWithdrawalCents = (withdrawalsDebitCents - withdrawalsRefundedCents).coerceAtLeast(0L)

        val ledgerCommCents = windowLedger
            .filter { it.entryType == "REFERRAL_COMMISSION" && it.direction == "CREDIT" }
            .sumOf { it.amount }
        val commTableCents = commissions
            .filter { it.createdAt >= cutoff && it.status != "REVERSED" }
            .sumOf { it.commissionAmount }
        val referEarnCents = maxOf(ledgerCommCents, commTableCents)

        return AccountStatementSummary(
            days = clampedDays,
            availableBalanceCents = wallet?.availableBalance ?: 0L,
            lockedBalanceCents = wallet?.lockedBalance ?: 0L,
            totalBetsCount = windowBets.size,
            wonBetsCount = wonCount,
            lostBetsCount = lostCount,
            pendingBetsCount = pendingCount,
            cancelledBetsCount = cancelledCount,
            totalBetWageredCents = wageredCents,
            totalBetWonCents = wonCents,
            netBetProfitLossCents = wonCents - wageredCents,
            totalReferEarnCents = referEarnCents,
            totalDepositCents = depositsCents,
            totalWithdrawalCents = netWithdrawalCents
        )
    }

    fun filterLedgerEntries(
        ledger: List<WalletLedgerEntity>,
        filter: String,
        days: Int = RETENTION_DAYS,
        nowMs: Long = System.currentTimeMillis()
    ): List<WalletLedgerEntity> {
        val cutoff = cutoffTimestampMs(days, nowMs)
        return ledger.filter { entry ->
            if (entry.createdAt < cutoff) return@filter false
            when (filter.uppercase()) {
                "ALL" -> true
                "PROFIT_LOSS" -> entry.entryType in listOf("BET", "WIN", "REFUND")
                "DEPOSIT" -> entry.entryType == "DEPOSIT"
                "WITHDRAWAL" -> entry.entryType == "WITHDRAWAL"
                "BET" -> entry.entryType == "BET"
                "WIN" -> entry.entryType == "WIN"
                "COMMISSION", "REFERRAL", "REFER" -> entry.entryType == "REFERRAL_COMMISSION"
                else -> true
            }
        }
    }

    fun buildStatementCsv(
        user: UserEntity?,
        wallet: WalletEntity?,
        bets: List<BetEntity>,
        ledger: List<WalletLedgerEntity>,
        commissions: List<ReferralCommissionEntity>,
        roundsMap: Map<String, GameRoundEntity>,
        days: Int = RETENTION_DAYS,
        filter: String = "ALL",
        nowMs: Long = System.currentTimeMillis()
    ): String {
        val clampedDays = days.coerceIn(1, RETENTION_DAYS)
        val cutoff = cutoffTimestampMs(clampedDays, nowMs)
        val summary = computeSummary(wallet, bets, ledger, commissions, clampedDays, nowMs)
        val filteredLedger = filterLedgerEntries(ledger, filter, clampedDays, nowMs)
        val windowBets = bets.filter { it.createdAt >= cutoff }
        val df = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ENGLISH)

        val sb = StringBuilder()
        sb.append('\uFEFF') // UTF-8 BOM for Excel

        fun row(vararg cols: Any?) {
            sb.append(cols.joinToString(",") { csvEscape(it?.toString() ?: "") }).append("\r\n")
        }

        fun rupees(cents: Long): String = String.format(Locale.ENGLISH, "%.2f", cents / 100.0)
        fun signedRupees(cents: Long): String {
            val sign = if (cents >= 0) "+" else "-"
            return "$sign${String.format(Locale.ENGLISH, "%.2f", kotlin.math.abs(cents) / 100.0)}"
        }

        row("COLOUR KING - 90-DAY ACCOUNT & BETTING STATEMENT")
        row(
            "User ID", user?.id ?: "USR-1001",
            "Username", user?.username ?: "Player",
            "Window", "Last $clampedDays Days (90-Day Storage)",
            "Generated At", df.format(Date(nowMs))
        )
        row()
        row("FINANCIAL SUMMARY (INR)")
        row("Available Wallet Balance", rupees(summary.availableBalanceCents), "Locked Escrow Balance", rupees(summary.lockedBalanceCents))
        row(
            "Total Bets Played", summary.totalBetsCount,
            "Won", summary.wonBetsCount,
            "Lost", summary.lostBetsCount,
            "Pending", summary.pendingBetsCount,
            "Cancelled", summary.cancelledBetsCount
        )
        row(
            "Total Bet Wagered", rupees(summary.totalBetWageredCents),
            "Total Bet Won", rupees(summary.totalBetWonCents),
            "Net Bet Profit / Loss", signedRupees(summary.netBetProfitLossCents)
        )
        row(
            "Total Refer & Earn", rupees(summary.totalReferEarnCents),
            "Total Deposits", rupees(summary.totalDepositCents),
            "Total Withdrawals", rupees(summary.totalWithdrawalCents)
        )
        row()

        row("WALLET TRANSACTIONS STATEMENT (BET P&L, REFER & EARN, DEPOSIT, WITHDRAWAL)")
        row("Date & Time", "Entry ID", "Type", "Direction", "Reference", "Amount (INR)", "Balance Before", "Balance After")
        for (entry in filteredLedger) {
            val signedAmt = if (entry.direction == "CREDIT") entry.amount else -entry.amount
            row(
                df.format(Date(entry.createdAt)),
                entry.id,
                entry.entryType,
                entry.direction,
                "${entry.referenceType} (${entry.referenceId})",
                signedRupees(signedAmt),
                rupees(entry.balanceBefore),
                rupees(entry.balanceAfter)
            )
        }
        row()

        row("90-DAY BETTING RECORDS HISTORY")
        row("Placed At", "Bet ID", "Market", "Period", "Type", "Selection", "Multiplier", "Stake (INR)", "Status", "Payout Won (INR)", "Net Profit/Loss (INR)", "Official Result")
        for (bet in windowBets) {
            val round = roundsMap[bet.roundId]
            val periodStr = round?.roundNumber?.toString() ?: bet.roundId.substringAfterLast("_")
            val mktName = GameMarkets.getById(bet.gameId).name
            val netPl = when (bet.status.uppercase()) {
                "WON" -> bet.actualPayout - bet.amount
                "LOST" -> -bet.amount
                else -> 0L
            }
            val resultStr = if (round?.resultNumber != null) {
                "Outcome ${round.resultNumber} (${round.resultColor ?: ""})"
            } else {
                bet.status
            }
            row(
                df.format(Date(bet.createdAt)),
                bet.id,
                mktName,
                periodStr,
                bet.betType,
                bet.selection,
                "${bet.multiplier}x",
                rupees(bet.amount),
                bet.status,
                rupees(bet.actualPayout),
                signedRupees(netPl),
                resultStr
            )
        }

        // Ensure MoneyUtils reference stays linked
        if (windowBets.isEmpty() && filteredLedger.isEmpty()) {
            row("Balance Check", MoneyUtils.formatCents(summary.availableBalanceCents))
        }

        return sb.toString()
    }

    private fun csvEscape(raw: String): String {
        val escaped = raw.replace("\"", "\"\"")
        return "\"$escaped\""
    }
}
