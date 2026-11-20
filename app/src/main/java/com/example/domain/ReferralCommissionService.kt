package com.example.domain

import com.example.data.local.AppDatabase
import com.example.data.model.*
import java.math.BigDecimal
import java.math.RoundingMode
import java.util.UUID

data class CommissionDistributionResult(
    val totalDistributedCents: Long,
    val commissions: List<ReferralCommissionEntity>
)

class ReferralCommissionService(private val database: AppDatabase) {

    // Configurable 6-level rates (Level 1 to 6)
    val commissionRates = mapOf(
        1 to 0.0100, // 1.00%
        2 to 0.0075, // 0.75%
        3 to 0.0060, // 0.60%
        4 to 0.0050, // 0.50%
        5 to 0.0030, // 0.30%
        6 to 0.0020  // 0.20%
    )

    fun calculateCommissionCents(eligibleAmountCents: Long, rate: Double): Long {
        return BigDecimal(eligibleAmountCents)
            .multiply(BigDecimal.valueOf(rate))
            .setScale(0, RoundingMode.HALF_UP)
            .toLong()
    }

    suspend fun distributeReferralCommission(
        tenantId: String,
        userId: String,
        eligibleAmountCents: Long,
        sourceTransactionId: String
    ): CommissionDistributionResult {
        val referralDao = database.referralDao()
        val walletDao = database.walletDao()
        val ledgerDao = database.ledgerDao()

        // 1. Load ancestors up to level 6 from closure table
        val ancestors = referralDao.getAncestorsForUser(tenantId, userId)
            .filter { it.depth in 1..6 }
            .sortedBy { it.depth }

        val createdCommissions = mutableListOf<ReferralCommissionEntity>()
        var totalDistributed = 0L

        for (ancestorRel in ancestors) {
            val level = ancestorRel.depth
            val beneficiaryUserId = ancestorRel.ancestorUserId
            val rate = commissionRates[level] ?: continue
            val commissionCents = calculateCommissionCents(eligibleAmountCents, rate)

            if (commissionCents <= 0L) continue

            // 2. Enforce idempotency key
            val idempotencyKey = "commission:${sourceTransactionId}:$level"
            val existing = referralDao.getCommissionByIdempotencyKey(idempotencyKey)
            if (existing != null) {
                createdCommissions.add(existing)
                totalDistributed += existing.commissionAmount
                continue
            }

            // 3. Verify beneficiary wallet exists & accrue commission in UNCLAIMED vault (credited when user claims)
            val wallet = walletDao.getWallet(tenantId, beneficiaryUserId)
            if (wallet != null) {
                val commissionRecord = ReferralCommissionEntity(
                    id = UUID.randomUUID().toString(),
                    tenantId = tenantId,
                    beneficiaryUserId = beneficiaryUserId,
                    sourceUserId = userId,
                    sourceTransactionId = sourceTransactionId,
                    level = level,
                    rate = rate,
                    eligibleAmount = eligibleAmountCents,
                    commissionAmount = commissionCents,
                    currency = wallet.currency,
                    status = CommissionStatus.UNCLAIMED.name,
                    idempotencyKey = idempotencyKey,
                    createdAt = System.currentTimeMillis(),
                    settledAt = null
                )
                referralDao.insertCommission(commissionRecord)
                createdCommissions.add(commissionRecord)
                totalDistributed += commissionCents
            }
        }

        return CommissionDistributionResult(totalDistributed, createdCommissions)
    }
}
