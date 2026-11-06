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

    fun calculateResult(serverSeed: String, clientSeed: String, nonce: Long): RoundResult {
        val message = "$clientSeed:$nonce"
        val hmacHex = calculateHmacSha256(serverSeed, message)
        
        // Take first 8 hex characters (32 bits) and convert to integer
        val hexSub = hmacHex.substring(0, 8)
        val value = hexSub.toLong(16)
        val number = (value % 10).toInt()

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

        return RoundResult(number, color, colorString, hmacHex)
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
