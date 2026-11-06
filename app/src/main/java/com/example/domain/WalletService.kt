package com.example.domain

import com.example.data.local.AppDatabase
import com.example.data.model.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.UUID

sealed class WalletResult<out T> {
    data class Success<out T>(val data: T) : WalletResult<T>()
    data class Error(val code: String, val message: String) : WalletResult<Nothing>()
}

class WalletService(private val database: AppDatabase) {

    // Process-level mutex to simulate row-level locking for wallet mutations
    private val walletMutex = Mutex()

    suspend fun debitForBet(
        tenantId: String,
        userId: String,
        amountCents: Long,
        roundId: String,
        idempotencyKey: String
    ): WalletResult<WalletLedgerEntity> = walletMutex.withLock {
        val ledgerDao = database.ledgerDao()
        val walletDao = database.walletDao()

        // 1. Idempotency Check
        val existingLedger = ledgerDao.getLedgerByIdempotencyKey(idempotencyKey)
        if (existingLedger != null) {
            return WalletResult.Success(existingLedger)
        }

        // 2. Fetch Wallet with lock
        val wallet = walletDao.getWallet(tenantId, userId)
            ?: return WalletResult.Error("WALLET_NOT_FOUND", "Wallet not found for user $userId")

        if (wallet.status != "ACTIVE") {
            return WalletResult.Error("WALLET_INACTIVE", "Wallet is not active")
        }

        if (wallet.availableBalance < amountCents) {
            return WalletResult.Error("INSUFFICIENT_BALANCE", "Insufficient available balance")
        }

        val balanceBefore = wallet.availableBalance
        val balanceAfter = balanceBefore - amountCents
        val txId = UUID.randomUUID().toString()

        // 3. Update Wallet snapshot
        val updatedWallet = wallet.copy(
            availableBalance = balanceAfter,
            lifetimeWager = wallet.lifetimeWager + amountCents,
            version = wallet.version + 1,
            updatedAt = System.currentTimeMillis()
        )
        walletDao.updateWallet(updatedWallet)

        // 4. Create Immutable Ledger Entry
        val ledgerEntry = WalletLedgerEntity(
            id = UUID.randomUUID().toString(),
            tenantId = tenantId,
            walletId = wallet.id,
            userId = userId,
            transactionId = txId,
            entryType = LedgerEntryType.BET.name,
            direction = LedgerDirection.DEBIT.name,
            amount = amountCents,
            currency = wallet.currency,
            balanceBefore = balanceBefore,
            balanceAfter = balanceAfter,
            referenceType = "GAME_ROUND",
            referenceId = roundId,
            metadataJson = """{"roundId":"$roundId"}""",
            idempotencyKey = idempotencyKey,
            createdAt = System.currentTimeMillis()
        )
        ledgerDao.insertLedger(ledgerEntry)

        // 5. Create Double-Entry Journal Entry
        val journalEntry = JournalEntryEntity(
            id = UUID.randomUUID().toString(),
            transactionId = txId,
            debitAccountId = "account_game_settlement",
            creditAccountId = "account_user_wallet_${wallet.id}",
            amount = amountCents,
            currency = wallet.currency,
            description = "Bet wagered on Round $roundId"
        )
        ledgerDao.insertJournalEntry(journalEntry)

        return WalletResult.Success(ledgerEntry)
    }

    suspend fun cancelAndRefundBet(
        tenantId: String,
        userId: String,
        amountCents: Long,
        roundId: String,
        betId: String
    ): WalletResult<WalletLedgerEntity> = walletMutex.withLock {
        val ledgerDao = database.ledgerDao()
        val walletDao = database.walletDao()

        val wallet = walletDao.getWallet(tenantId, userId)
            ?: return WalletResult.Error("WALLET_NOT_FOUND", "Wallet not found for user $userId")

        val balanceBefore = wallet.availableBalance
        val balanceAfter = balanceBefore + amountCents
        val txId = UUID.randomUUID().toString()

        val updatedWallet = wallet.copy(
            availableBalance = balanceAfter,
            lifetimeWager = maxOf(0L, wallet.lifetimeWager - amountCents),
            version = wallet.version + 1,
            updatedAt = System.currentTimeMillis()
        )
        walletDao.updateWallet(updatedWallet)

        val idempotencyKey = "cancel_${betId}_${System.currentTimeMillis()}"
        val ledgerEntry = WalletLedgerEntity(
            id = UUID.randomUUID().toString(),
            tenantId = tenantId,
            walletId = wallet.id,
            userId = userId,
            transactionId = txId,
            entryType = LedgerEntryType.REFUND.name,
            direction = LedgerDirection.CREDIT.name,
            amount = amountCents,
            currency = wallet.currency,
            balanceBefore = balanceBefore,
            balanceAfter = balanceAfter,
            referenceType = "BET_CANCELLATION",
            referenceId = betId,
            metadataJson = """{"roundId":"$roundId","betId":"$betId"}""",
            idempotencyKey = idempotencyKey,
            createdAt = System.currentTimeMillis()
        )
        ledgerDao.insertLedger(ledgerEntry)

        val journalEntry = JournalEntryEntity(
            id = UUID.randomUUID().toString(),
            transactionId = txId,
            debitAccountId = "account_user_wallet_${wallet.id}",
            creditAccountId = "account_game_settlement",
            amount = amountCents,
            currency = wallet.currency,
            description = "Refund for cancelled bet on Round $roundId"
        )
        ledgerDao.insertJournalEntry(journalEntry)

        return WalletResult.Success(ledgerEntry)
    }

    suspend fun creditForWin(
        tenantId: String,
        userId: String,
        amountCents: Long,
        roundId: String,
        idempotencyKey: String
    ): WalletResult<WalletLedgerEntity> = walletMutex.withLock {
        val ledgerDao = database.ledgerDao()
        val walletDao = database.walletDao()

        val existingLedger = ledgerDao.getLedgerByIdempotencyKey(idempotencyKey)
        if (existingLedger != null) {
            return WalletResult.Success(existingLedger)
        }

        val wallet = walletDao.getWallet(tenantId, userId)
            ?: return WalletResult.Error("WALLET_NOT_FOUND", "Wallet not found for user $userId")

        val balanceBefore = wallet.availableBalance
        val balanceAfter = balanceBefore + amountCents
        val txId = UUID.randomUUID().toString()

        val updatedWallet = wallet.copy(
            availableBalance = balanceAfter,
            lifetimeWin = wallet.lifetimeWin + amountCents,
            version = wallet.version + 1,
            updatedAt = System.currentTimeMillis()
        )
        walletDao.updateWallet(updatedWallet)

        val ledgerEntry = WalletLedgerEntity(
            id = UUID.randomUUID().toString(),
            tenantId = tenantId,
            walletId = wallet.id,
            userId = userId,
            transactionId = txId,
            entryType = LedgerEntryType.WIN.name,
            direction = LedgerDirection.CREDIT.name,
            amount = amountCents,
            currency = wallet.currency,
            balanceBefore = balanceBefore,
            balanceAfter = balanceAfter,
            referenceType = "GAME_ROUND",
            referenceId = roundId,
            metadataJson = """{"roundId":"$roundId"}""",
            idempotencyKey = idempotencyKey,
            createdAt = System.currentTimeMillis()
        )
        ledgerDao.insertLedger(ledgerEntry)

        val journalEntry = JournalEntryEntity(
            id = UUID.randomUUID().toString(),
            transactionId = txId,
            debitAccountId = "account_platform_reserve",
            creditAccountId = "account_user_wallet_${wallet.id}",
            amount = amountCents,
            currency = wallet.currency,
            description = "Win payout credited for Round $roundId"
        )
        ledgerDao.insertJournalEntry(journalEntry)

        return WalletResult.Success(ledgerEntry)
    }

    suspend fun creditDeposit(
        tenantId: String,
        userId: String,
        amountCents: Long,
        provider: String,
        idempotencyKey: String
    ): WalletResult<WalletLedgerEntity> = walletMutex.withLock {
        val ledgerDao = database.ledgerDao()
        val walletDao = database.walletDao()

        val existing = ledgerDao.getLedgerByIdempotencyKey(idempotencyKey)
        if (existing != null) return WalletResult.Success(existing)

        val wallet = walletDao.getWallet(tenantId, userId)
            ?: return WalletResult.Error("WALLET_NOT_FOUND", "Wallet not found")

        val balanceBefore = wallet.availableBalance
        val balanceAfter = balanceBefore + amountCents
        val txId = UUID.randomUUID().toString()

        walletDao.updateWallet(
            wallet.copy(
                availableBalance = balanceAfter,
                lifetimeDeposit = wallet.lifetimeDeposit + amountCents,
                version = wallet.version + 1,
                updatedAt = System.currentTimeMillis()
            )
        )

        val ledger = WalletLedgerEntity(
            id = UUID.randomUUID().toString(),
            tenantId = tenantId,
            walletId = wallet.id,
            userId = userId,
            transactionId = txId,
            entryType = LedgerEntryType.DEPOSIT.name,
            direction = LedgerDirection.CREDIT.name,
            amount = amountCents,
            currency = wallet.currency,
            balanceBefore = balanceBefore,
            balanceAfter = balanceAfter,
            referenceType = "PAYMENT_GATEWAY",
            referenceId = provider,
            metadataJson = """{"provider":"$provider"}""",
            idempotencyKey = idempotencyKey,
            createdAt = System.currentTimeMillis()
        )
        ledgerDao.insertLedger(ledger)

        ledgerDao.insertJournalEntry(
            JournalEntryEntity(
                id = UUID.randomUUID().toString(),
                transactionId = txId,
                debitAccountId = "account_payment_gateway_$provider",
                creditAccountId = "account_user_wallet_${wallet.id}",
                amount = amountCents,
                currency = wallet.currency,
                description = "External deposit via $provider"
            )
        )

        return WalletResult.Success(ledger)
    }

    suspend fun requestWithdrawal(
        tenantId: String,
        userId: String,
        amountCents: Long,
        bankOrUpi: String
    ): WalletResult<WithdrawalRequestEntity> = walletMutex.withLock {
        val walletDao = database.walletDao()
        val ledgerDao = database.ledgerDao()
        val withdrawalDao = database.withdrawalDao()

        val wallet = walletDao.getWallet(tenantId, userId)
            ?: return WalletResult.Error("WALLET_NOT_FOUND", "Wallet not found")

        if (wallet.availableBalance < amountCents) {
            return WalletResult.Error("INSUFFICIENT_FUNDS", "Insufficient available balance to withdraw")
        }

        val txId = UUID.randomUUID().toString()
        val balanceBefore = wallet.availableBalance
        val balanceAfter = balanceBefore - amountCents

        // Move from available to locked
        walletDao.updateWallet(
            wallet.copy(
                availableBalance = balanceAfter,
                lockedBalance = wallet.lockedBalance + amountCents,
                version = wallet.version + 1,
                updatedAt = System.currentTimeMillis()
            )
        )

        val withdrawal = WithdrawalRequestEntity(
            id = UUID.randomUUID().toString(),
            tenantId = tenantId,
            userId = userId,
            amount = amountCents,
            currency = wallet.currency,
            bankOrUpi = bankOrUpi,
            status = WithdrawalStatus.REQUESTED.name,
            transactionId = txId
        )
        withdrawalDao.insertWithdrawal(withdrawal)

        val ledger = WalletLedgerEntity(
            id = UUID.randomUUID().toString(),
            tenantId = tenantId,
            walletId = wallet.id,
            userId = userId,
            transactionId = txId,
            entryType = LedgerEntryType.WITHDRAWAL.name,
            direction = LedgerDirection.DEBIT.name,
            amount = amountCents,
            currency = wallet.currency,
            balanceBefore = balanceBefore,
            balanceAfter = balanceAfter,
            referenceType = "WITHDRAWAL_LOCK",
            referenceId = withdrawal.id,
            idempotencyKey = "withdraw_req_${withdrawal.id}",
            createdAt = System.currentTimeMillis()
        )
        ledgerDao.insertLedger(ledger)

        return WalletResult.Success(withdrawal)
    }

    suspend fun approveWithdrawal(
        withdrawalId: String,
        adminUserId: String
    ): WalletResult<Unit> = walletMutex.withLock {
        val withdrawalDao = database.withdrawalDao()
        val walletDao = database.walletDao()
        val ledgerDao = database.ledgerDao()

        val withdrawal = withdrawalDao.getWithdrawalById(withdrawalId)
            ?: return WalletResult.Error("NOT_FOUND", "Withdrawal request not found")

        if (withdrawal.status != WithdrawalStatus.REQUESTED.name && withdrawal.status != WithdrawalStatus.UNDER_REVIEW.name) {
            return WalletResult.Error("INVALID_STATE", "Withdrawal cannot be approved in state ${withdrawal.status}")
        }

        val wallet = walletDao.getWallet(withdrawal.tenantId, withdrawal.userId)
            ?: return WalletResult.Error("WALLET_NOT_FOUND", "Wallet not found")

        // Deduct from locked balance permanently and record lifetime withdrawal
        walletDao.updateWallet(
            wallet.copy(
                lockedBalance = maxOf(0L, wallet.lockedBalance - withdrawal.amount),
                lifetimeWithdrawal = wallet.lifetimeWithdrawal + withdrawal.amount,
                version = wallet.version + 1,
                updatedAt = System.currentTimeMillis()
            )
        )

        withdrawalDao.updateWithdrawal(
            withdrawal.copy(
                status = WithdrawalStatus.COMPLETED.name,
                adminNotes = "Approved by admin $adminUserId",
                updatedAt = System.currentTimeMillis()
            )
        )

        ledgerDao.insertJournalEntry(
            JournalEntryEntity(
                id = UUID.randomUUID().toString(),
                transactionId = withdrawal.transactionId,
                debitAccountId = "account_user_wallet_locked_${wallet.id}",
                creditAccountId = "account_banking_payout",
                amount = withdrawal.amount,
                currency = withdrawal.currency,
                description = "Withdrawal payout executed to ${withdrawal.bankOrUpi}"
            )
        )

        return WalletResult.Success(Unit)
    }

    suspend fun rejectWithdrawal(
        withdrawalId: String,
        adminUserId: String,
        reason: String
    ): WalletResult<Unit> = walletMutex.withLock {
        val withdrawalDao = database.withdrawalDao()
        val walletDao = database.walletDao()
        val ledgerDao = database.ledgerDao()

        val withdrawal = withdrawalDao.getWithdrawalById(withdrawalId)
            ?: return WalletResult.Error("NOT_FOUND", "Withdrawal not found")

        val wallet = walletDao.getWallet(withdrawal.tenantId, withdrawal.userId)
            ?: return WalletResult.Error("WALLET_NOT_FOUND", "Wallet not found")

        // Restore funds back to available
        val balanceBefore = wallet.availableBalance
        val balanceAfter = balanceBefore + withdrawal.amount

        walletDao.updateWallet(
            wallet.copy(
                availableBalance = balanceAfter,
                lockedBalance = maxOf(0L, wallet.lockedBalance - withdrawal.amount),
                version = wallet.version + 1,
                updatedAt = System.currentTimeMillis()
            )
        )

        withdrawalDao.updateWithdrawal(
            withdrawal.copy(
                status = WithdrawalStatus.REFUNDED.name,
                adminNotes = "Rejected: $reason",
                updatedAt = System.currentTimeMillis()
            )
        )

        val txId = UUID.randomUUID().toString()
        val ledger = WalletLedgerEntity(
            id = UUID.randomUUID().toString(),
            tenantId = withdrawal.tenantId,
            walletId = wallet.id,
            userId = wallet.userId,
            transactionId = txId,
            entryType = LedgerEntryType.REFUND.name,
            direction = LedgerDirection.CREDIT.name,
            amount = withdrawal.amount,
            currency = wallet.currency,
            balanceBefore = balanceBefore,
            balanceAfter = balanceAfter,
            referenceType = "WITHDRAWAL_REVERSAL",
            referenceId = withdrawal.id,
            idempotencyKey = "withdraw_reversal_${withdrawal.id}",
            createdAt = System.currentTimeMillis()
        )
        ledgerDao.insertLedger(ledger)

        return WalletResult.Success(Unit)
    }
}
