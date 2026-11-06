package com.example.data.local

import androidx.room.*
import com.example.data.model.*
import kotlinx.coroutines.flow.Flow

@Dao
interface UserDao {
    @Query("SELECT * FROM users WHERE tenantId = :tenantId")
    fun getUsersByTenant(tenantId: String): Flow<List<UserEntity>>

    @Query("SELECT * FROM users WHERE id = :userId")
    suspend fun getUserById(userId: String): UserEntity?

    @Query("SELECT * FROM users WHERE tenantId = :tenantId AND referralCode = :code LIMIT 1")
    suspend fun getUserByReferralCode(tenantId: String, code: String): UserEntity?

    @Query("SELECT * FROM users WHERE tenantId = :tenantId AND (username = :identifier OR phone = :identifier OR email = :identifier) LIMIT 1")
    suspend fun findUserByIdentifier(tenantId: String, identifier: String): UserEntity?

    @Query("SELECT * FROM users WHERE tenantId = :tenantId AND username = :username LIMIT 1")
    suspend fun getUserByUsername(tenantId: String, username: String): UserEntity?

    @Query("SELECT * FROM users WHERE tenantId = :tenantId AND phone = :phone LIMIT 1")
    suspend fun getUserByPhone(tenantId: String, phone: String): UserEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertUser(user: UserEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertUsers(users: List<UserEntity>)

    @Update
    suspend fun updateUser(user: UserEntity)
}

@Dao
interface WalletDao {
    @Query("SELECT * FROM wallets WHERE tenantId = :tenantId AND userId = :userId LIMIT 1")
    fun getWalletFlow(tenantId: String, userId: String): Flow<WalletEntity?>

    @Query("SELECT * FROM wallets WHERE tenantId = :tenantId AND userId = :userId LIMIT 1")
    suspend fun getWallet(tenantId: String, userId: String): WalletEntity?

    @Query("SELECT * FROM wallets WHERE id = :walletId LIMIT 1")
    suspend fun getWalletById(walletId: String): WalletEntity?

    @Query("SELECT * FROM wallets WHERE tenantId = :tenantId")
    fun getAllWallets(tenantId: String): Flow<List<WalletEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertWallet(wallet: WalletEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertWallets(wallets: List<WalletEntity>)

    @Update
    suspend fun updateWallet(wallet: WalletEntity)
}

@Dao
interface LedgerDao {
    @Query("SELECT * FROM wallet_ledger WHERE tenantId = :tenantId AND userId = :userId ORDER BY createdAt DESC")
    fun getLedgerByUser(tenantId: String, userId: String): Flow<List<WalletLedgerEntity>>

    @Query("SELECT * FROM wallet_ledger WHERE tenantId = :tenantId ORDER BY createdAt DESC LIMIT 100")
    fun getAllLedger(tenantId: String): Flow<List<WalletLedgerEntity>>

    @Query("SELECT * FROM wallet_ledger WHERE idempotencyKey = :key LIMIT 1")
    suspend fun getLedgerByIdempotencyKey(key: String): WalletLedgerEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertLedger(ledger: WalletLedgerEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertJournalEntry(entry: JournalEntryEntity)

    @Query("SELECT * FROM journal_entries WHERE transactionId = :transactionId")
    suspend fun getJournalEntriesByTransaction(transactionId: String): List<JournalEntryEntity>
}

@Dao
interface GameRoundDao {
    @Query("SELECT * FROM game_rounds WHERE tenantId = :tenantId AND gameId = :gameId ORDER BY roundNumber DESC LIMIT 1")
    fun getLatestRoundFlow(tenantId: String, gameId: String): Flow<GameRoundEntity?>

    @Query("SELECT * FROM game_rounds WHERE tenantId = :tenantId AND gameId = :gameId ORDER BY roundNumber DESC LIMIT 1")
    suspend fun getLatestRound(tenantId: String, gameId: String): GameRoundEntity?

    @Query("SELECT * FROM game_rounds WHERE roundId = :roundId LIMIT 1")
    suspend fun getRoundById(roundId: String): GameRoundEntity?

    @Query("SELECT * FROM game_rounds WHERE tenantId = :tenantId AND gameId = :gameId AND status = 'COMPLETED' ORDER BY roundNumber DESC LIMIT 500")
    fun getRecentCompletedRounds(tenantId: String, gameId: String): Flow<List<GameRoundEntity>>

    @Query("SELECT * FROM game_rounds WHERE tenantId = :tenantId ORDER BY roundNumber DESC LIMIT 500")
    fun getAllRoundsFlow(tenantId: String): Flow<List<GameRoundEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertRound(round: GameRoundEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertRounds(rounds: List<GameRoundEntity>)

    @Query("SELECT * FROM game_rounds WHERE tenantId = :tenantId AND gameId = :gameId AND status = 'COMPLETED' ORDER BY roundNumber DESC LIMIT 1")
    suspend fun getLatestCompletedRound(tenantId: String, gameId: String): GameRoundEntity?

    @Query("DELETE FROM game_rounds WHERE tenantId = :tenantId AND roundNumber > :maxRoundNumber")
    suspend fun deleteFutureRounds(tenantId: String, maxRoundNumber: Long)

    @Update
    suspend fun updateRound(round: GameRoundEntity)
}

@Dao
interface BetDao {
    @Query("SELECT * FROM bets WHERE roundId = :roundId")
    suspend fun getBetsForRound(roundId: String): List<BetEntity>

    @Query("SELECT * FROM bets WHERE tenantId = :tenantId AND userId = :userId ORDER BY createdAt DESC LIMIT 50")
    fun getUserBetsFlow(tenantId: String, userId: String): Flow<List<BetEntity>>

    @Query("SELECT * FROM bets WHERE tenantId = :tenantId AND userId = :userId AND gameId = :gameId ORDER BY createdAt DESC LIMIT 50")
    fun getUserBetsByMarketFlow(tenantId: String, userId: String, gameId: String): Flow<List<BetEntity>>

    @Query("SELECT * FROM bets WHERE roundId = :roundId AND userId = :userId")
    fun getUserBetsForRoundFlow(roundId: String, userId: String): Flow<List<BetEntity>>

    @Query("SELECT * FROM bets WHERE idempotencyKey = :key LIMIT 1")
    suspend fun getBetByIdempotencyKey(key: String): BetEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertBet(bet: BetEntity)

    @Query("DELETE FROM bets WHERE id = :betId")
    suspend fun deleteBetById(betId: String)

    @Query("SELECT * FROM bets WHERE roundId = :roundId AND userId = :userId AND selection = :selection AND status = 'ACCEPTED' LIMIT 1")
    suspend fun getActiveBetForSelection(roundId: String, userId: String, selection: String): BetEntity?

    @Update
    suspend fun updateBet(bet: BetEntity)

    @Update
    suspend fun updateBets(bets: List<BetEntity>)
}

@Dao
interface ReferralDao {
    @Query("SELECT * FROM referral_relationships WHERE tenantId = :tenantId AND descendantUserId = :userId ORDER BY depth ASC")
    suspend fun getAncestorsForUser(tenantId: String, userId: String): List<ReferralRelationshipEntity>

    @Query("SELECT * FROM referral_relationships WHERE tenantId = :tenantId AND ancestorUserId = :userId ORDER BY depth ASC")
    fun getDescendantsForUserFlow(tenantId: String, userId: String): Flow<List<ReferralRelationshipEntity>>

    @Query("SELECT * FROM referral_relationships WHERE tenantId = :tenantId AND ancestorUserId = :userId ORDER BY depth ASC")
    suspend fun getDescendantsForUser(tenantId: String, userId: String): List<ReferralRelationshipEntity>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertRelationships(relationships: List<ReferralRelationshipEntity>)

    @Query("SELECT * FROM referral_commissions WHERE tenantId = :tenantId AND beneficiaryUserId = :userId ORDER BY createdAt DESC")
    fun getCommissionsForUserFlow(tenantId: String, userId: String): Flow<List<ReferralCommissionEntity>>

    @Query("SELECT * FROM referral_commissions WHERE idempotencyKey = :key LIMIT 1")
    suspend fun getCommissionByIdempotencyKey(key: String): ReferralCommissionEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertCommission(commission: ReferralCommissionEntity)
}

@Dao
interface AuditDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertLog(log: AuditLogEntity)

    @Query("SELECT * FROM audit_logs WHERE tenantId = :tenantId ORDER BY timestamp DESC LIMIT 100")
    fun getLogsFlow(tenantId: String): Flow<List<AuditLogEntity>>
}

@Dao
interface WithdrawalDao {
    @Query("SELECT * FROM withdrawal_requests WHERE tenantId = :tenantId AND userId = :userId ORDER BY createdAt DESC")
    fun getUserWithdrawals(tenantId: String, userId: String): Flow<List<WithdrawalRequestEntity>>

    @Query("SELECT * FROM withdrawal_requests WHERE tenantId = :tenantId ORDER BY createdAt DESC")
    fun getAllWithdrawals(tenantId: String): Flow<List<WithdrawalRequestEntity>>

    @Query("SELECT * FROM withdrawal_requests WHERE id = :id LIMIT 1")
    suspend fun getWithdrawalById(id: String): WithdrawalRequestEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertWithdrawal(withdrawal: WithdrawalRequestEntity)

    @Update
    suspend fun updateWithdrawal(withdrawal: WithdrawalRequestEntity)
}

@Dao
interface GameConfigDao {
    @Query("SELECT * FROM game_configs WHERE tenantId = :tenantId AND gameId = :gameId LIMIT 1")
    fun getConfigFlow(tenantId: String, gameId: String): Flow<GameConfigEntity?>

    @Query("SELECT * FROM game_configs WHERE tenantId = :tenantId AND gameId = :gameId LIMIT 1")
    suspend fun getConfig(tenantId: String, gameId: String): GameConfigEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertConfig(config: GameConfigEntity)
}

@Dao
interface TenantDao {
    @Query("SELECT * FROM tenants")
    fun getAllTenants(): Flow<List<TenantEntity>>

    @Query("SELECT * FROM tenants WHERE id = :id LIMIT 1")
    suspend fun getTenantById(id: String): TenantEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertTenant(tenant: TenantEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertTenants(tenants: List<TenantEntity>)
}
