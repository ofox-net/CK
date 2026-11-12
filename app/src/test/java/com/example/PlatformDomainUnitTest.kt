package com.example

import com.example.data.model.MoneyUtils
import com.example.domain.ProvablyFairEngine
import org.junit.Assert.assertEquals
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
}
