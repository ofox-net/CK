package com.example.domain

import com.example.data.model.GameColor
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

data class RoundResult(
    val number: Int,
    val color: GameColor,
    val colorString: String,
    val hmacHex: String
)

object ProvablyFairEngine {

    private val secureRandom = SecureRandom()

    fun generateServerSeed(): String {
        val bytes = ByteArray(32)
        secureRandom.nextBytes(bytes)
        return bytes.joinToString("") { "%02x".format(it) }
    }

    fun hashSha256(input: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(input.toByteArray(Charsets.UTF_8))
        return hash.joinToString("") { "%02x".format(it) }
    }

    fun avalancheSeed(marketCode: String, period: String): String {
        val raw = marketCode.removePrefix("market_").uppercase()
        val cleanMarket = when (raw) {
            "MIA" -> "MIAMI"
            "VEG" -> "VEGAS"
            "PAR" -> "PARIS"
            "DUB" -> "DUBAI"
            else -> raw
        }
        return "COLOUR_KING_AVALANCHE_2026_${cleanMarket}_${period}_PROVABLY_FAIR"
    }

    // Matches server.py generate_provably_fair_outcome() and web/index.html getDeterministicPeriodResult() bit-for-bit
    fun calculateAvalancheResult(marketCode: String, period: String): RoundResult {
        val seed = avalancheSeed(marketCode, period)
        return calculateAvalancheFromSeed(seed)
    }

    fun calculateAvalancheFromSeed(seed: String): RoundResult {
        var h: Long = 0x811c9dc5L
        for (ch in seed) {
            h = h xor ch.code.toLong()
            h = (h * 0x01000193L) and 0xFFFFFFFFL
        }
        h = h xor (h ushr 16)
        h = (h * 0x85ebca6bL) and 0xFFFFFFFFL
        h = h xor (h ushr 13)
        h = (h * 0xc2b2ae35L) and 0xFFFFFFFFL
        h = h xor (h ushr 16)
        val absHash = h and 0xFFFFFFFFL
        val number = (absHash % 10L).toInt()
        return buildRoundResult(number, hashSha256(seed))
    }

    fun buildRoundResult(number: Int, proofHex: String = "ADMIN_OVERRIDE"): RoundResult {
        val color = when (number) {
            0 -> GameColor.RED_VIOLET
            5 -> GameColor.GREEN_VIOLET
            1, 3, 7, 9 -> GameColor.GREEN
            2, 4, 6, 8 -> GameColor.RED
            else -> GameColor.GREEN
        }

        val colorString = when (color) {
            GameColor.RED -> "RED"
            GameColor.GREEN -> "GREEN"
            GameColor.VIOLET -> "VIOLET"
            GameColor.RED_VIOLET -> "RED + VIOLET"
            GameColor.GREEN_VIOLET -> "GREEN + VIOLET"
        }

        return RoundResult(number, color, colorString, proofHex)
    }

    fun calculateResult(serverSeed: String, clientSeed: String, nonce: Long): RoundResult {
        if (serverSeed.startsWith("COLOUR_KING_AVALANCHE_2026_")) {
            return calculateAvalancheFromSeed(serverSeed)
        }
        val message = "$clientSeed:$nonce"
        val hmacHex = calculateHmacSha256(serverSeed, message)

        // Take first 8 hex characters (32 bits) and convert to integer
        val hexSub = hmacHex.substring(0, 8)
        val value = hexSub.toLong(16)
        val number = (value % 10).toInt()

        return buildRoundResult(number, hmacHex)
    }

    fun verifyFairness(
        serverSeed: String,
        serverSeedHash: String,
        clientSeed: String,
        nonce: Long
    ): Pair<Boolean, RoundResult> {
        val computedHash = hashSha256(serverSeed)
        val hashMatches = computedHash.equals(serverSeedHash, ignoreCase = true)
        val result = calculateResult(serverSeed, clientSeed, nonce)
        return Pair(hashMatches, result)
    }

    private fun calculateHmacSha256(key: String, data: String): String {
        val sha256Hmac = Mac.getInstance("HmacSHA256")
        val secretKey = SecretKeySpec(key.toByteArray(Charsets.UTF_8), "HmacSHA256")
        sha256Hmac.init(secretKey)
        val signedBytes = sha256Hmac.doFinal(data.toByteArray(Charsets.UTF_8))
        return signedBytes.joinToString("") { "%02x".format(it) }
    }
}
