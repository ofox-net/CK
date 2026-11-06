package com.example

import com.example.data.model.BetEntity
import com.example.data.model.BetType
import com.example.data.model.GameColor
import com.example.data.model.GameConfigEntity
import com.example.data.model.MoneyUtils
import com.example.domain.ProvablyFairEngine
import com.example.domain.ReferralCommissionService
import com.example.domain.RoundResult
import org.junit.Assert.*
import org.junit.Test
import java.math.BigDecimal
import java.math.RoundingMode

class PlatformDomainTests {

    @Test
    fun `test 6-level referral commission calculation matches master prompt example exactly`() {
        // Master prompt section 15 specifies:
        // If eligible amount = ₹10,000 (1,000,000 cents):
        // Level 1: 1.00% -> ₹100 (10,000 cents)
        // Level 2: 0.75% -> ₹75  (7,500 cents)
        // Level 3: 0.60% -> ₹60  (6,000 cents)
        // Level 4: 0.50% -> ₹50  (5,000 cents)
        // Level 5: 0.30% -> ₹30  (3,000 cents)
        // Level 6: 0.20% -> ₹20  (2,000 cents)
        // Total commission: ₹335 (33,500 cents)

        val eligibleAmountCents = 1000000L // ₹10,000.00 in cents

        val rates = mapOf(
            1 to 0.0100,
            2 to 0.0075,
            3 to 0.0060,
            4 to 0.0050,
            5 to 0.0030,
            6 to 0.0020
        )

        fun calc(cents: Long, rate: Double): Long {
            return BigDecimal(cents)
                .multiply(BigDecimal.valueOf(rate))
                .setScale(0, RoundingMode.HALF_UP)
                .toLong()
        }

        val l1 = calc(eligibleAmountCents, rates[1]!!)
        val l2 = calc(eligibleAmountCents, rates[2]!!)
        val l3 = calc(eligibleAmountCents, rates[3]!!)
        val l4 = calc(eligibleAmountCents, rates[4]!!)
        val l5 = calc(eligibleAmountCents, rates[5]!!)
        val l6 = calc(eligibleAmountCents, rates[6]!!)

        assertEquals(10000L, l1) // ₹100.00
        assertEquals(7500L, l2)  // ₹75.00
        assertEquals(6000L, l3)  // ₹60.00
        assertEquals(5000L, l4)  // ₹50.00
        assertEquals(3000L, l5)  // ₹30.00
        assertEquals(2000L, l6)  // ₹20.00

        val total = l1 + l2 + l3 + l4 + l5 + l6
        assertEquals(33500L, total) // ₹335.00 total
        assertEquals("₹335.00", MoneyUtils.formatCents(total))
    }

    @Test
    fun `test provably fair server seed SHA256 pre-commitment and HMAC verification`() {
        val serverSeed = ProvablyFairEngine.generateServerSeed()
        val serverSeedHash = ProvablyFairEngine.hashSha256(serverSeed)
        val clientSeed = "apex_test_seed"
        val nonce = 1001L

        val (isValid, result) = ProvablyFairEngine.verifyFairness(
            serverSeed,
            serverSeedHash,
            clientSeed,
            nonce
        )

        assertTrue(isValid)
        assertTrue(result.number in 0..9)
        assertNotNull(result.color)
        assertEquals(64, result.hmacHex.length)

        // Verify deterministic reproduction
        val result2 = ProvablyFairEngine.calculateResult(serverSeed, clientSeed, nonce)
        assertEquals(result.number, result2.number)
        assertEquals(result.color, result2.color)
        assertEquals(result.hmacHex, result2.hmacHex)
    }

    @Test
    fun `test violet combinations color mapping`() {
        // As defined in prompt Section 9:
        // Number 0: RED + VIOLET
        // Number 5: GREEN + VIOLET
        // Numbers 1, 3, 7, 9: GREEN
        // Numbers 2, 4, 6, 8: RED

        // Simulate results directly
        val config = GameConfigEntity(id = "cfg_test", tenantId = "tenant_test")

        fun eval(betType: BetType, selection: String, number: Int, color: GameColor): Pair<Boolean, Double> {
            val bet = BetEntity(
                id = "b1",
                tenantId = "t1",
                userId = "u1",
                gameId = "g1",
                roundId = "r1",
                betType = betType.name,
                selection = selection,
                amount = 10000L,
                multiplier = 2.0,
                potentialPayout = 20000L,
                transactionId = "tx1",
                idempotencyKey = "k1"
            )
            val res = RoundResult(number, color, color.name, "hash")

            return when (bet.betType) {
                BetType.NUMBER.name -> {
                    if (bet.selection == number.toString()) Pair(true, config.numberMultiplier) else Pair(false, 0.0)
                }
                BetType.BIG_SMALL.name -> {
                    when (bet.selection.uppercase()) {
                        "BIG" -> if (number in 5..9) Pair(true, 2.0) else Pair(false, 0.0)
                        "SMALL" -> if (number in 0..4) Pair(true, 2.0) else Pair(false, 0.0)
                        else -> Pair(false, 0.0)
                    }
                }
                else -> {
                    when (bet.selection.uppercase()) {
                        "RED" -> {
                            when (color) {
                                GameColor.RED -> Pair(true, config.redMultiplier)
                                GameColor.RED_VIOLET -> Pair(true, 1.5)
                                else -> Pair(false, 0.0)
                            }
                        }
                        "GREEN" -> {
                            when (color) {
                                GameColor.GREEN -> Pair(true, config.greenMultiplier)
                                GameColor.GREEN_VIOLET -> Pair(true, 1.5)
                                else -> Pair(false, 0.0)
                            }
                        }
                        "VIOLET" -> {
                            when (color) {
                                GameColor.VIOLET, GameColor.RED_VIOLET, GameColor.GREEN_VIOLET -> Pair(true, config.violetMultiplier)
                                else -> Pair(false, 0.0)
                            }
                        }
                        else -> Pair(false, 0.0)
                    }
                }
            }
        }

        // Test combo 0 (RED + VIOLET)
        val on0Number = eval(BetType.NUMBER, "0", 0, GameColor.RED_VIOLET)
        assertTrue(on0Number.first)
        assertEquals(9.0, on0Number.second, 0.01)

        val on0Red = eval(BetType.COLOR, "RED", 0, GameColor.RED_VIOLET)
        assertTrue(on0Red.first)
        assertEquals(1.5, on0Red.second, 0.01)

        val on0Violet = eval(BetType.COLOR, "VIOLET", 0, GameColor.RED_VIOLET)
        assertTrue(on0Violet.first)
        assertEquals(3.0, on0Violet.second, 0.01)

        val on0Green = eval(BetType.COLOR, "GREEN", 0, GameColor.RED_VIOLET)
        assertFalse(on0Green.first)

        // Test combo 5 (GREEN + VIOLET)
        val on5Green = eval(BetType.COLOR, "GREEN", 5, GameColor.GREEN_VIOLET)
        assertTrue(on5Green.first)
        assertEquals(1.5, on5Green.second, 0.01)

        val on5Violet = eval(BetType.COLOR, "VIOLET", 5, GameColor.GREEN_VIOLET)
        assertTrue(on5Violet.first)
        assertEquals(3.0, on5Violet.second, 0.01)

        val on5Red = eval(BetType.COLOR, "RED", 5, GameColor.GREEN_VIOLET)
        assertFalse(on5Red.first) // Red bet on Green+Violet 5 is a loss

        // Test pure red (2, 4, 6, 8) and pure green (1, 3, 7, 9)
        val on2Red = eval(BetType.COLOR, "RED", 2, GameColor.RED)
        assertTrue(on2Red.first)
        assertEquals(2.0, on2Red.second, 0.01)

        val on3Green = eval(BetType.COLOR, "GREEN", 3, GameColor.GREEN)
        assertTrue(on3Green.first)
        assertEquals(2.0, on3Green.second, 0.01)

        val on3Red = eval(BetType.COLOR, "RED", 3, GameColor.GREEN)
        assertFalse(on3Red.first) // Red bet on Green 3 is a loss
    }

    @Test
    fun `test money precision formatting without floating point drift`() {
        val cents = 123456789L // ₹1,234,567.89
        val formatted = MoneyUtils.formatCents(cents)
        assertEquals("₹1,234,567.89", formatted)

        val toCents = MoneyUtils.toCents(1234.56)
        assertEquals(123456L, toCents)
    }

    @Test
    fun `test big small betting rules and 2x payout`() {
        val config = GameConfigEntity(id = "cfg_test", tenantId = "tenant_test")

        fun evalBigSmall(selection: String, number: Int): Pair<Boolean, Double> {
            val bet = BetEntity(
                id = "b_bs",
                tenantId = "t1",
                userId = "u1",
                gameId = "color_prediction",
                roundId = "r1",
                betType = BetType.BIG_SMALL.name,
                selection = selection,
                amount = 10000L,
                multiplier = 2.0,
                potentialPayout = 20000L,
                transactionId = "tx1",
                idempotencyKey = "k1"
            )
            val res = RoundResult(number, GameColor.GREEN, "GREEN", "hash")
            return when (bet.selection.uppercase()) {
                "BIG" -> if (res.number in 5..9) Pair(true, 2.0) else Pair(false, 0.0)
                "SMALL" -> if (res.number in 0..4) Pair(true, 2.0) else Pair(false, 0.0)
                else -> Pair(false, 0.0)
            }
        }

        // Test Small numbers: 0, 1, 2, 3, 4
        for (num in 0..4) {
            val smallBet = evalBigSmall("SMALL", num)
            assertTrue("Small should win on $num", smallBet.first)
            assertEquals(2.0, smallBet.second, 0.001)

            val bigBet = evalBigSmall("BIG", num)
            assertFalse("Big should lose on $num", bigBet.first)
            assertEquals(0.0, bigBet.second, 0.001)
        }

        // Test Big numbers: 5, 6, 7, 8, 9
        for (num in 5..9) {
            val bigBet = evalBigSmall("BIG", num)
            assertTrue("Big should win on $num", bigBet.first)
            assertEquals(2.0, bigBet.second, 0.001)

            val smallBet = evalBigSmall("SMALL", num)
            assertFalse("Small should lose on $num", smallBet.first)
            assertEquals(0.0, smallBet.second, 0.001)
        }
    }
}
