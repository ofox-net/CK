package com.example.data.model

data class MarketInfo(
    val id: String,
    val name: String,
    val code: String,
    val emoji: String,
    val tagline: String,
    val accentColorHex: Long,
    val roundDurationSec: Int = 180
)

object GameMarkets {
    val MIAMI = MarketInfo(
        id = "market_miami",
        name = "MIAMI",
        code = "MIA",
        emoji = "🌴",
        tagline = "South Beach Neon • 3 Min",
        accentColorHex = 0xFFFF007F // Neon Pink / Coral
    )

    val VEGAS = MarketInfo(
        id = "market_vegas",
        name = "VEGAS",
        code = "VEG",
        emoji = "🎰",
        tagline = "Sin City High Roller • 3 Min",
        accentColorHex = 0xFFFFD700 // Gold
    )

    val PARIS = MarketInfo(
        id = "market_paris",
        name = "PARIS",
        code = "PAR",
        emoji = "🗼",
        tagline = "Chic Royale Elegance • 3 Min",
        accentColorHex = 0xFFBA68C8 // Lilac / Rose Purple
    )

    val DUBAI = MarketInfo(
        id = "market_dubai",
        name = "DUBAI",
        code = "DUB",
        emoji = "🏙️",
        tagline = "Emirates Luxury Oasis • 3 Min",
        accentColorHex = 0xFF00E5FF // Cyan Luxury
    )

    val ALL = listOf(MIAMI, VEGAS, PARIS, DUBAI)

    fun getById(id: String): MarketInfo = ALL.firstOrNull { it.id == id } ?: MIAMI
    fun getByCode(code: String): MarketInfo = ALL.firstOrNull { it.code.equals(code, ignoreCase = true) } ?: MIAMI
}
