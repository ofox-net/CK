package com.example.domain

import java.util.UUID

data class CasinoGame(
    val id: String,
    val providerId: String,
    val providerName: String,
    val title: String,
    val category: String, // SLOTS, LIVE_ROULETTE, CRASH, BACCARAT
    val rtp: Double, // e.g. 96.5%
    val minBetCents: Long,
    val maxBetCents: Long,
    val iconEmoji: String,
    val isLive: Boolean = false
)

data class LaunchGameInput(
    val tenantId: String,
    val userId: String,
    val gameId: String,
    val currency: String
)

data class LaunchGameResponse(
    val sessionUrl: String,
    val sessionId: String,
    val token: String,
    val status: String
)

data class ProviderBalance(
    val userId: String,
    val availableBalanceCents: Long,
    val currency: String
)

interface CasinoProviderInterface {
    val providerId: String
    val providerName: String
    suspend fun getGames(): List<CasinoGame>
    suspend fun launchGame(input: LaunchGameInput): LaunchGameResponse
    suspend fun getBalance(tenantId: String, userId: String): ProviderBalance
    suspend fun handleWebhook(payload: Map<String, String>): Boolean
}

class EvolutionGamingAdapter : CasinoProviderInterface {
    override val providerId = "provider_evolution"
    override val providerName = "Evolution Live"

    override suspend fun getGames(): List<CasinoGame> = listOf(
        CasinoGame("evo_roulette_01", providerId, providerName, "Lightning Roulette", "LIVE_ROULETTE", 97.30, 2000L, 5000000L, "⚡", true),
        CasinoGame("evo_blackjack_vip", providerId, providerName, "Infinite Blackjack", "LIVE_BLACKJACK", 99.47, 5000L, 10000000L, "🃏", true),
        CasinoGame("evo_crazy_time", providerId, providerName, "Crazy Time Live", "GAME_SHOW", 96.08, 1000L, 2500000L, "🎡", true)
    )

    override suspend fun launchGame(input: LaunchGameInput): LaunchGameResponse {
        val sessionId = "evo_sess_${UUID.randomUUID()}"
        return LaunchGameResponse(
            sessionUrl = "https://live.evolution.com/launcher?session=$sessionId&user=${input.userId}",
            sessionId = sessionId,
            token = "jwt_evo_${System.currentTimeMillis()}",
            status = "READY"
        )
    }

    override suspend fun getBalance(tenantId: String, userId: String): ProviderBalance {
        return ProviderBalance(userId, 5000000L, "INR")
    }

    override suspend fun handleWebhook(payload: Map<String, String>): Boolean {
        // Signature verification & webhook payload processing
        return true
    }
}

class PragmaticPlayAdapter : CasinoProviderInterface {
    override val providerId = "provider_pragmatic"
    override val providerName = "Pragmatic Play"

    override suspend fun getGames(): List<CasinoGame> = listOf(
        CasinoGame("prag_gates_olympus", providerId, providerName, "Gates of Olympus 1000", "SLOTS", 96.50, 1000L, 2000000L, "⚡", false),
        CasinoGame("prag_sweet_bonanza", providerId, providerName, "Sweet Bonanza Xmas", "SLOTS", 96.48, 1000L, 1500000L, "🍬", false),
        CasinoGame("prag_wolf_gold", providerId, providerName, "Wolf Gold Megaways", "SLOTS", 96.01, 1000L, 1000000L, "🐺", false)
    )

    override suspend fun launchGame(input: LaunchGameInput): LaunchGameResponse {
        val sessionId = "prag_sess_${UUID.randomUUID()}"
        return LaunchGameResponse(
            sessionUrl = "https://demogamesfree.pragmaticplay.net/gs2c/openGame.do?gameSymbol=${input.gameId}&token=$sessionId",
            sessionId = sessionId,
            token = "prag_jwt_${UUID.randomUUID()}",
            status = "READY"
        )
    }

    override suspend fun getBalance(tenantId: String, userId: String): ProviderBalance {
        return ProviderBalance(userId, 5000000L, "INR")
    }

    override suspend fun handleWebhook(payload: Map<String, String>): Boolean {
        return true
    }
}

class SpribeAdapter : CasinoProviderInterface {
    override val providerId = "provider_spribe"
    override val providerName = "Spribe Gaming"

    override suspend fun getGames(): List<CasinoGame> = listOf(
        CasinoGame("spribe_aviator", providerId, providerName, "Aviator Real-Time Crash", "CRASH", 97.00, 1000L, 8000000L, "✈️", true),
        CasinoGame("spribe_mines", providerId, providerName, "Mines Crypto Turbo", "TURBO", 97.00, 1000L, 5000000L, "💣", false),
        CasinoGame("spribe_plinko", providerId, providerName, "Plinko Super Drops", "ARCADE", 97.00, 1000L, 3000000L, "🎯", false)
    )

    override suspend fun launchGame(input: LaunchGameInput): LaunchGameResponse {
        val sessionId = "spribe_sess_${UUID.randomUUID()}"
        return LaunchGameResponse(
            sessionUrl = "https://spribe.co/games/launch?game=${input.gameId}&session=$sessionId",
            sessionId = sessionId,
            token = "spribe_token_${UUID.randomUUID()}",
            status = "READY"
        )
    }

    override suspend fun getBalance(tenantId: String, userId: String): ProviderBalance {
        return ProviderBalance(userId, 5000000L, "INR")
    }

    override suspend fun handleWebhook(payload: Map<String, String>): Boolean {
        return true
    }
}
