package com.example.data.model

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "tenants",
    indices = [Index(value = ["code"], unique = true)]
)
data class TenantEntity(
    @PrimaryKey val id: String,
    val name: String,
    val code: String,
    val currency: String = "INR",
    val status: String = "ACTIVE",
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "users",
    indices = [
        Index(value = ["tenantId", "username"], unique = true),
        Index(value = ["tenantId", "referralCode"], unique = true),
        Index(value = ["tenantId", "referredBy"])
    ]
)
data class UserEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val username: String,
    val email: String,
    val phone: String,
    val passwordHash: String,
    val status: String = "ACTIVE",
    val role: String = "USER",
    val referralCode: String,
    val referredBy: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
    val lastLoginAt: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "wallets",
    indices = [
        Index(value = ["tenantId", "userId"], unique = true)
    ]
)
data class WalletEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val userId: String,
    val currency: String = "INR",
    val availableBalance: Long = 0L, // in cents (zero floating-point issue)
    val lockedBalance: Long = 0L,
    val lifetimeDeposit: Long = 0L,
    val lifetimeWithdrawal: Long = 0L,
    val lifetimeWager: Long = 0L,
    val lifetimeWin: Long = 0L,
    val status: String = "ACTIVE",
    val version: Long = 1L,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "wallet_ledger",
    indices = [
        Index(value = ["tenantId", "userId"]),
        Index(value = ["walletId"]),
        Index(value = ["transactionId"]),
        Index(value = ["idempotencyKey"], unique = true)
    ]
)
data class WalletLedgerEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val walletId: String,
    val userId: String,
    val transactionId: String,
    val entryType: String, // DEPOSIT, BET, WIN, etc.
    val direction: String, // CREDIT, DEBIT
    val amount: Long, // cents
    val currency: String = "INR",
    val balanceBefore: Long,
    val balanceAfter: Long,
    val referenceType: String,
    val referenceId: String,
    val metadataJson: String = "{}",
    val idempotencyKey: String,
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "journal_entries",
    indices = [
        Index(value = ["transactionId"])
    ]
)
data class JournalEntryEntity(
    @PrimaryKey val id: String,
    val transactionId: String,
    val debitAccountId: String,
    val creditAccountId: String,
    val amount: Long,
    val currency: String = "INR",
    val description: String,
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "game_rounds",
    indices = [
        Index(value = ["tenantId", "gameId", "roundNumber"], unique = true),
        Index(value = ["status"])
    ]
)
data class GameRoundEntity(
    @PrimaryKey val roundId: String,
    val gameId: String,
    val tenantId: String,
    val roundNumber: Long,
    val startTime: Long,
    val bettingCloseTime: Long,
    val resultTime: Long,
    val status: String, // BETTING_OPEN, BETTING_CLOSED, RESULT_GENERATED, SETTLEMENT, COMPLETED
    val resultNumber: Int? = null,
    val resultColor: String? = null, // RED, GREEN, VIOLET, RED_VIOLET, GREEN_VIOLET
    val multiplier: Double = 1.0,
    val serverSeedHash: String,
    val serverSeed: String? = null, // revealed upon result generation
    val nonce: Long,
    val clientSeed: String = "apex_public_seed",
    val createdAt: Long = System.currentTimeMillis(),
    val settledAt: Long? = null
)

@Entity(
    tableName = "bets",
    indices = [
        Index(value = ["tenantId", "userId"]),
        Index(value = ["roundId"]),
        Index(value = ["idempotencyKey"], unique = true)
    ]
)
data class BetEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val userId: String,
    val gameId: String,
    val roundId: String,
    val betType: String, // COLOR, NUMBER
    val selection: String, // RED, GREEN, VIOLET, or "0".."9"
    val amount: Long, // in cents
    val multiplier: Double,
    val potentialPayout: Long,
    val actualPayout: Long = 0L,
    val status: String = "PENDING", // PENDING, ACCEPTED, WON, LOST, REFUNDED, CANCELLED
    val transactionId: String,
    val idempotencyKey: String,
    val createdAt: Long = System.currentTimeMillis(),
    val settledAt: Long? = null
)

@Entity(
    tableName = "referral_relationships",
    indices = [
        Index(value = ["tenantId", "ancestorUserId", "descendantUserId"], unique = true),
        Index(value = ["tenantId", "descendantUserId", "depth"])
    ]
)
data class ReferralRelationshipEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val ancestorUserId: String,
    val descendantUserId: String,
    val depth: Int, // 1 to 6
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "referral_commissions",
    indices = [
        Index(value = ["sourceTransactionId", "beneficiaryUserId", "level"], unique = true),
        Index(value = ["tenantId", "beneficiaryUserId"])
    ]
)
data class ReferralCommissionEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val beneficiaryUserId: String,
    val sourceUserId: String,
    val sourceTransactionId: String,
    val level: Int,
    val rate: Double, // e.g. 0.0100 for L1
    val eligibleAmount: Long, // cents
    val commissionAmount: Long, // cents
    val currency: String = "INR",
    val status: String = "SETTLED",
    val idempotencyKey: String,
    val createdAt: Long = System.currentTimeMillis(),
    val settledAt: Long? = null,
    val reversedAt: Long? = null
)

@Entity(
    tableName = "audit_logs",
    indices = [
        Index(value = ["tenantId", "actorUserId"]),
        Index(value = ["entityType", "entityId"])
    ]
)
data class AuditLogEntity(
    @PrimaryKey val id: String,
    val actorUserId: String,
    val tenantId: String,
    val action: String,
    val entityType: String,
    val entityId: String,
    val oldValue: String? = null,
    val newValue: String? = null,
    val ip: String = "127.0.0.1",
    val userAgent: String = "ApexPlay-Android/1.0",
    val requestId: String,
    val timestamp: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "withdrawal_requests",
    indices = [
        Index(value = ["tenantId", "userId"]),
        Index(value = ["status"])
    ]
)
data class WithdrawalRequestEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val userId: String,
    val amount: Long, // cents
    val currency: String = "INR",
    val bankOrUpi: String,
    val status: String = "REQUESTED",
    val transactionId: String,
    val adminNotes: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis()
)

@Entity(
    tableName = "game_configs",
    indices = [
        Index(value = ["tenantId", "gameId"], unique = true)
    ]
)
data class GameConfigEntity(
    @PrimaryKey val id: String,
    val tenantId: String,
    val gameId: String = "color_prediction",
    val redMultiplier: Double = 2.0,
    val greenMultiplier: Double = 2.0,
    val violetMultiplier: Double = 3.0,
    val numberMultiplier: Double = 9.0,
    val roundDurationSec: Int = 180, // 3 minutes per round
    val bettingCutoffSec: Int = 30, // 30 seconds Bet Close time
    val minBet: Long = 1000L, // ₹10.00
    val maxBet: Long = 5000000L, // ₹50,000.00
    val payoutLimit: Long = 50000000L, // ₹500,000.00
    val isMaintenance: Boolean = false,
    val updatedAt: Long = System.currentTimeMillis()
)
