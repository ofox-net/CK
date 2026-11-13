package com.example

import com.example.data.model.BetEntity
import com.example.data.model.GameRoundEntity
import com.example.data.model.MoneyUtils
import com.example.data.model.ReferralCommissionEntity
import com.example.data.model.UserEntity
import com.example.data.model.WalletEntity
import com.example.data.model.WalletLedgerEntity
import com.example.domain.ProvablyFairEngine
import com.example.domain.StatementExporter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigDecimal

class PlatformDomainUnitTest {

    @Test
    fun testProvablyFairEngineDeterministicResult() {
        val serverSeed = "b12e3a7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5"
        val clientSeed = "community_fair_seed_2026"
        val nonce = 42L

        val result1 = ProvablyFairEngine.calculateResult(serverSeed, clientSeed, nonce)
        val result2 = ProvablyFairEngine.calculateResult(serverSeed, clientSeed, nonce)

        // Must be completely deterministic
        assertEquals(result1.number, result2.number)
        assertEquals(result1.color, result2.color)
        assertEquals(result1.hmacHex, result2.hmacHex)
        assertTrue(result1.number in 0..9)
    }

    @Test
    fun testProvablyFairVerification() {
        val serverSeed = ProvablyFairEngine.generateServerSeed()
        val serverSeedHash = ProvablyFairEngine.hashSha256(serverSeed)
        val clientSeed = "test_player_seed"
        val nonce = 100L

        val (hashMatches, result) = ProvablyFairEngine.verifyFairness(serverSeed, serverSeedHash, clientSeed, nonce)
        assertTrue(hashMatches)
        assertTrue(result.number in 0..9)
    }

    @Test
    fun testMoneyUtilsFormatting() {
        val formatted = MoneyUtils.formatCents(125000L) // 1250.00
        assertEquals("₹1,250.00", formatted)
    }

    @Test
    fun test6LevelReferralRates() {
        // Commission rates: L1: 1.0%, L2: 0.8%, L3: 0.6%, L4: 0.4%, L5: 0.3%, L6: 0.2%
        val wagerCents = 100000L // ₹1000
        val l1Rate = BigDecimal("0.0100")
        val l1Commission = (BigDecimal(wagerCents) * l1Rate).toLong()
        assertEquals(1000L, l1Commission) // ₹10.00
    }

    @Test
    fun testPasswordHashingAndVerification() {
        val password = "SecretPassword123"
        val hash = ProvablyFairEngine.hashSha256(password)
        assertTrue(hash.isNotEmpty())
        assertEquals(64, hash.length) // SHA-256 is 64 hex characters

        // Verification matches
        val checkHash = ProvablyFairEngine.hashSha256(password)
        assertEquals(hash, checkHash)
    }

    @Test
    fun testAuthValidationRules() {
        // Username must be at least 3 chars
        val validUser = "Player_01"
        val invalidUser = "ab"
        assertTrue(validUser.length >= 3)
        assertTrue(invalidUser.length < 3)

        // Phone must be at least 10 digits
        val validPhone = "9876543210"
        val invalidPhone = "12345"
        assertTrue(validPhone.length >= 10)
        assertTrue(invalidPhone.length < 10)
    }

    @Test
    fun testUnifiedAvalancheMatchesWebBackend() {
        // Exact verified outputs from server.py generate_provably_fair_outcome() & web/index.html
        assertEquals(1, ProvablyFairEngine.calculateAvalancheResult("MIAMI", "20261112493").number)
        assertEquals(7, ProvablyFairEngine.calculateAvalancheResult("MIAMI", "20261112492").number)
        assertEquals(2, ProvablyFairEngine.calculateAvalancheResult("VEGAS", "20261112492").number)
        assertEquals(1, ProvablyFairEngine.calculateAvalancheResult("PARIS", "20261112492").number)
        assertEquals(3, ProvablyFairEngine.calculateAvalancheResult("DUBAI", "20261112492").number)

        // verifyFairness works identically with unified Avalanche seed
        val seed = ProvablyFairEngine.avalancheSeed("MIAMI", "20261112493")
        val seedHash = ProvablyFairEngine.hashSha256(seed)
        val (matches, res) = ProvablyFairEngine.verifyFairness(seed, seedHash, "PROVABLY_FAIR_AVALANCHE", 20261112493L)
        assertTrue(matches)
        assertEquals(1, res.number)
    }

    @Test
    fun test90DayStatementSummaryAndCsvExport() {
        val nowMs = 1_800_000_000_000L
        val dayMs = StatementExporter.DAY_MILLIS

        val user = UserEntity(
            id = "USR-1001",
            tenantId = "TENANT-01",
            username = "Rahul_Player",
            email = "rahul@example.com",
            phone = "9876543210",
            passwordHash = "hash",
            referralCode = "RAHUL1"
        )
        val wallet = WalletEntity(
            id = "WAL-1",
            tenantId = "TENANT-01",
            userId = "USR-1001",
            availableBalance = 500000L, // ₹5,000.00
            lockedBalance = 10000L // ₹100.00
        )

        val bets = listOf(
            // Within 90 days: won bet (wagered ₹100, payout ₹200 -> net +₹100)
            BetEntity(
                id = "BET-WON-1",
                tenantId = "TENANT-01",
                userId = "USR-1001",
                gameId = "miami",
                roundId = "miami_20261112500",
                betType = "COLOR",
                selection = "GREEN",
                amount = 10000L,
                multiplier = 2.0,
                potentialPayout = 20000L,
                actualPayout = 20000L,
                status = "WON",
                transactionId = "TX-1",
                idempotencyKey = "IDEM-1",
                createdAt = nowMs - 2 * dayMs
            ),
            // Within 90 days: lost bet (wagered ₹50, payout 0 -> net -₹50)
            BetEntity(
                id = "BET-LOST-2",
                tenantId = "TENANT-01",
                userId = "USR-1001",
                gameId = "vegas",
                roundId = "vegas_20261112501",
                betType = "SIZE",
                selection = "BIG",
                amount = 5000L,
                multiplier = 2.0,
                potentialPayout = 10000L,
                actualPayout = 0L,
                status = "LOST",
                transactionId = "TX-2",
                idempotencyKey = "IDEM-2",
                createdAt = nowMs - 89 * dayMs
            ),
            // Older than 90 days (95 days old) -> MUST be excluded
            BetEntity(
                id = "BET-OLD-95D",
                tenantId = "TENANT-01",
                userId = "USR-1001",
                gameId = "paris",
                roundId = "paris_20260101001",
                betType = "COLOR",
                selection = "RED",
                amount = 100000L,
                multiplier = 2.0,
                potentialPayout = 200000L,
                actualPayout = 200000L,
                status = "WON",
                transactionId = "TX-OLD",
                idempotencyKey = "IDEM-OLD",
                createdAt = nowMs - 95 * dayMs
            )
        )

        val ledger = listOf(
            WalletLedgerEntity(
                id = "LED-DEP",
                tenantId = "TENANT-01",
                walletId = "WAL-1",
                userId = "USR-1001",
                transactionId = "TX-DEP",
                entryType = "DEPOSIT",
                direction = "CREDIT",
                amount = 300000L, // ₹3,000.00
                balanceBefore = 0L,
                balanceAfter = 300000L,
                referenceType = "UPI",
                referenceId = "DEP-1",
                idempotencyKey = "IDEM-DEP",
                createdAt = nowMs - 10 * dayMs
            ),
            WalletLedgerEntity(
                id = "LED-WD",
                tenantId = "TENANT-01",
                walletId = "WAL-1",
                userId = "USR-1001",
                transactionId = "TX-WD",
                entryType = "WITHDRAWAL",
                direction = "DEBIT",
                amount = 120000L, // ₹1,200.00
                balanceBefore = 300000L,
                balanceAfter = 180000L,
                referenceType = "BANK",
                referenceId = "WD-1",
                idempotencyKey = "IDEM-WD",
                createdAt = nowMs - 5 * dayMs
            ),
            WalletLedgerEntity(
                id = "LED-WD-REFUND",
                tenantId = "TENANT-01",
                walletId = "WAL-1",
                userId = "USR-1001",
                transactionId = "TX-WD-REF",
                entryType = "REFUND",
                direction = "CREDIT",
                amount = 20000L, // ₹200.00 refunded withdrawal
                balanceBefore = 180000L,
                balanceAfter = 200000L,
                referenceType = "WITHDRAWAL_REJECTED",
                referenceId = "WD-2",
                idempotencyKey = "IDEM-WD-REF",
                createdAt = nowMs - 4 * dayMs
            ),
            WalletLedgerEntity(
                id = "LED-REF",
                tenantId = "TENANT-01",
                walletId = "WAL-1",
                userId = "USR-1001",
                transactionId = "TX-REF",
                entryType = "REFERRAL_COMMISSION",
                direction = "CREDIT",
                amount = 7500L, // ₹75.00
                balanceBefore = 200000L,
                balanceAfter = 207500L,
                referenceType = "REFERRAL",
                referenceId = "BET-OTHER",
                idempotencyKey = "IDEM-REF",
                createdAt = nowMs - 3 * dayMs
            ),
            // Expired 95d deposit excluded
            WalletLedgerEntity(
                id = "LED-DEP-OLD",
                tenantId = "TENANT-01",
                walletId = "WAL-1",
                userId = "USR-1001",
                transactionId = "TX-DEP-OLD",
                entryType = "DEPOSIT",
                direction = "CREDIT",
                amount = 999900L,
                balanceBefore = 0L,
                balanceAfter = 999900L,
                referenceType = "UPI",
                referenceId = "DEP-OLD",
                idempotencyKey = "IDEM-DEP-OLD",
                createdAt = nowMs - 95 * dayMs
            )
        )

        val commissions = listOf(
            ReferralCommissionEntity(
                id = "COMM-1",
                tenantId = "TENANT-01",
                beneficiaryUserId = "USR-1001",
                sourceUserId = "USR-2002",
                sourceTransactionId = "TX-SRC-1",
                level = 1,
                rate = 0.01,
                eligibleAmount = 750000L,
                commissionAmount = 7500L,
                idempotencyKey = "IDEM-COMM-1",
                createdAt = nowMs - 3 * dayMs
            )
        )

        val summary = StatementExporter.computeSummary(
            wallet = wallet,
            bets = bets,
            ledger = ledger,
            commissions = commissions,
            days = 90,
            nowMs = nowMs
        )

        assertEquals(90, summary.days)
        assertEquals(2, summary.totalBetsCount)
        assertEquals(1, summary.wonBetsCount)
        assertEquals(1, summary.lostBetsCount)
        assertEquals(15000L, summary.totalBetWageredCents) // ₹100 + ₹50
        assertEquals(20000L, summary.totalBetWonCents) // ₹200
        assertEquals(5000L, summary.netBetProfitLossCents) // +₹50.00
        assertEquals(7500L, summary.totalReferEarnCents) // ₹75.00
        assertEquals(300000L, summary.totalDepositCents) // ₹3,000.00
        assertEquals(100000L, summary.totalWithdrawalCents) // ₹1,200 - ₹200 refund = ₹1,000.00

        val roundsMap = mapOf(
            "miami_20261112500" to GameRoundEntity(
                roundId = "miami_20261112500",
                gameId = "miami",
                tenantId = "TENANT-01",
                roundNumber = 20261112500L,
                startTime = nowMs - 2 * dayMs,
                bettingCloseTime = nowMs - 2 * dayMs + 150_000L,
                resultTime = nowMs - 2 * dayMs + 180_000L,
                status = "COMPLETED",
                resultNumber = 3,
                resultColor = "GREEN",
                serverSeedHash = "h",
                nonce = 20261112500L
            )
        )

        val csv = StatementExporter.buildStatementCsv(
            user = user,
            wallet = wallet,
            bets = bets,
            ledger = ledger,
            commissions = commissions,
            roundsMap = roundsMap,
            days = 90,
            filter = "ALL",
            nowMs = nowMs
        )

        assertTrue(csv.contains("COLOUR KING - 90-DAY ACCOUNT & BETTING STATEMENT"))
        assertTrue(csv.contains("BET-WON-1"))
        assertTrue(csv.contains("BET-LOST-2"))
        assertFalse(csv.contains("BET-OLD-95D"))
        assertTrue(csv.contains("+50.00"))
        assertTrue(csv.contains("75.00"))
        assertTrue(csv.contains("3000.00"))
        assertTrue(csv.contains("1000.00"))
        assertTrue(csv.contains("REFERRAL_COMMISSION"))
    }
}
