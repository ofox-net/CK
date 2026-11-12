package com.example.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.sqlite.db.SupportSQLiteDatabase
import com.example.data.model.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.security.MessageDigest
import java.util.UUID

@Database(
    entities = [
        TenantEntity::class,
        UserEntity::class,
        WalletEntity::class,
        WalletLedgerEntity::class,
        JournalEntryEntity::class,
        GameRoundEntity::class,
        BetEntity::class,
        ReferralRelationshipEntity::class,
        ReferralCommissionEntity::class,
        AuditLogEntity::class,
        WithdrawalRequestEntity::class,
        GameConfigEntity::class
    ],
    version = 1,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun tenantDao(): TenantDao
    abstract fun userDao(): UserDao
    abstract fun walletDao(): WalletDao
    abstract fun ledgerDao(): LedgerDao
    abstract fun gameRoundDao(): GameRoundDao
    abstract fun betDao(): BetDao
    abstract fun referralDao(): ReferralDao
    abstract fun auditDao(): AuditDao
    abstract fun withdrawalDao(): WithdrawalDao
    abstract fun gameConfigDao(): GameConfigDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "apex_gaming_platform.db"
                )
                    .addCallback(object : Callback() {
                        override fun onCreate(db: SupportSQLiteDatabase) {
                            super.onCreate(db)
                            CoroutineScope(Dispatchers.IO).launch {
                                INSTANCE?.seedInitialData()
                            }
                        }
                    })
                    .fallbackToDestructiveMigration()
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }

    suspend fun seedInitialData() {
        val tenantId = "tenant_apex_global"
        val tenant2Id = "tenant_cyber_asia"

        // 1. Tenants
        val tenants = listOf(
            TenantEntity(
                id = tenantId,
                name = "Colour King",
                code = "CKING",
                currency = "INR"
            ),
            TenantEntity(
                id = tenant2Id,
                name = "CyberPlay Asia",
                code = "CYBER",
                currency = "INR"
            )
        )
        tenantDao().insertTenants(tenants)

        // 2. Users (SuperAdmin, Referrers L1..L6, and Player)
        // Hierarchy:
        // L6: user_ref_l6 ("Vikram L6")
        // L5: user_ref_l5 ("Siddharth L5") -> referred by L6
        // L4: user_ref_l4 ("Arjun L4")     -> referred by L5
        // L3: user_ref_l3 ("Pooja L3")     -> referred by L4
        // L2: user_ref_l2 ("Ananya L2")    -> referred by L3
        // L1: user_ref_l1 ("Rohan L1")     -> referred by L2
        // Player: user_player ("Rahul V.") -> referred by L1

        val users = listOf(
            UserEntity(
                id = "user_super_admin",
                tenantId = tenantId,
                username = "ApexSuperAdmin",
                email = "admin@apexplay.io",
                phone = "+919876543210",
                passwordHash = "hash_argon2_admin",
                role = UserRole.SUPER_ADMIN.name,
                referralCode = "APEXROOT"
            ),
            UserEntity(
                id = "user_ref_l6",
                tenantId = tenantId,
                username = "Vikram_L6",
                email = "vikram@apexplay.io",
                phone = "+919800000006",
                passwordHash = "hash_demo",
                role = UserRole.USER.name,
                referralCode = "REF_L6",
                referredBy = null
            ),
            UserEntity(
                id = "user_ref_l5",
                tenantId = tenantId,
                username = "Siddharth_L5",
                email = "siddharth@apexplay.io",
                phone = "+919800000005",
                passwordHash = "hash_demo",
                role = UserRole.USER.name,
                referralCode = "REF_L5",
                referredBy = "user_ref_l6"
            ),
            UserEntity(
                id = "user_ref_l4",
                tenantId = tenantId,
                username = "Arjun_L4",
                email = "arjun@apexplay.io",
                phone = "+919800000004",
                passwordHash = "hash_demo",
                role = UserRole.USER.name,
                referralCode = "REF_L4",
                referredBy = "user_ref_l5"
            ),
            UserEntity(
                id = "user_ref_l3",
                tenantId = tenantId,
                username = "Pooja_L3",
                email = "pooja@apexplay.io",
                phone = "+919800000003",
                passwordHash = "hash_demo",
                role = UserRole.USER.name,
                referralCode = "REF_L3",
                referredBy = "user_ref_l4"
            ),
            UserEntity(
                id = "user_ref_l2",
                tenantId = tenantId,
                username = "Ananya_L2",
                email = "ananya@apexplay.io",
                phone = "+919800000002",
                passwordHash = "hash_demo",
                role = UserRole.USER.name,
                referralCode = "REF_L2",
                referredBy = "user_ref_l3"
            ),
            UserEntity(
                id = "user_ref_l1",
                tenantId = tenantId,
                username = "Rohan_L1",
                email = "rohan@apexplay.io",
                phone = "+919800000001",
                passwordHash = "hash_demo",
                role = UserRole.USER.name,
                referralCode = "REF_L1",
                referredBy = "user_ref_l2"
            ),
            UserEntity(
                id = "user_player_rahul",
                tenantId = tenantId,
                username = "Rahul_Player",
                email = "rahul@gmail.com",
                phone = "+919811112233",
                passwordHash = "hash_demo",
                role = UserRole.USER.name,
                referralCode = "RAHUL99",
                referredBy = "user_ref_l1"
            )
        )
        userDao().insertUsers(users)

        // 3. Wallets with initial balances (in cents)
        val initialWallets = listOf(
            WalletEntity(
                id = "wallet_admin",
                tenantId = tenantId,
                userId = "user_super_admin",
                availableBalance = 1000000000L, // ₹10,000,000.00
                lifetimeDeposit = 1000000000L
            ),
            WalletEntity(
                id = "wallet_ref_l6",
                tenantId = tenantId,
                userId = "user_ref_l6",
                availableBalance = 245000L // ₹2,450.00
            ),
            WalletEntity(
                id = "wallet_ref_l5",
                tenantId = tenantId,
                userId = "user_ref_l5",
                availableBalance = 380000L // ₹3,800.00
            ),
            WalletEntity(
                id = "wallet_ref_l4",
                tenantId = tenantId,
                userId = "user_ref_l4",
                availableBalance = 520000L // ₹5,200.00
            ),
            WalletEntity(
                id = "wallet_ref_l3",
                tenantId = tenantId,
                userId = "user_ref_l3",
                availableBalance = 840000L // ₹8,400.00
            ),
            WalletEntity(
                id = "wallet_ref_l2",
                tenantId = tenantId,
                userId = "user_ref_l2",
                availableBalance = 1250000L // ₹12,500.00
            ),
            WalletEntity(
                id = "wallet_ref_l1",
                tenantId = tenantId,
                userId = "user_ref_l1",
                availableBalance = 2500000L // ₹25,000.00
            ),
            WalletEntity(
                id = "wallet_player_rahul",
                tenantId = tenantId,
                userId = "user_player_rahul",
                availableBalance = 5000000L, // ₹50,000.00 starter balance
                lifetimeDeposit = 5000000L
            )
        )
        walletDao().insertWallets(initialWallets)

        // Seed initial ledger credit for player
        val initTx = UUID.randomUUID().toString()
        val ledger = WalletLedgerEntity(
            id = UUID.randomUUID().toString(),
            tenantId = tenantId,
            walletId = "wallet_player_rahul",
            userId = "user_player_rahul",
            transactionId = initTx,
            entryType = LedgerEntryType.DEPOSIT.name,
            direction = LedgerDirection.CREDIT.name,
            amount = 5000000L,
            balanceBefore = 0L,
            balanceAfter = 5000000L,
            referenceType = "INITIAL_FUNDING",
            referenceId = "WELCOME_BONUS",
            idempotencyKey = "init_deposit_rahul"
        )
        ledgerDao().insertLedger(ledger)

        // 4. Referral Relationships (Closure table up to level 6 for user_player_rahul)
        val relationships = listOf(
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l1", "user_player_rahul", 1),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l2", "user_player_rahul", 2),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l3", "user_player_rahul", 3),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l4", "user_player_rahul", 4),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l5", "user_player_rahul", 5),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l6", "user_player_rahul", 6),

            // Inter-ancestor relationships
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l2", "user_ref_l1", 1),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l3", "user_ref_l1", 2),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l4", "user_ref_l1", 3),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l5", "user_ref_l1", 4),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l6", "user_ref_l1", 5),

            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l3", "user_ref_l2", 1),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l4", "user_ref_l2", 2),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l5", "user_ref_l2", 3),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l6", "user_ref_l2", 4),

            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l4", "user_ref_l3", 1),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l5", "user_ref_l3", 2),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l6", "user_ref_l3", 3),

            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l5", "user_ref_l4", 1),
            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l6", "user_ref_l4", 2),

            ReferralRelationshipEntity(UUID.randomUUID().toString(), tenantId, "user_ref_l6", "user_ref_l5", 1)
        )
        referralDao().insertRelationships(relationships)

        // 5. Game Config for tenant - All 4 Markets + color_prediction
        val marketIds = listOf("market_miami", "market_vegas", "market_paris", "market_dubai", "color_prediction")
        for (gId in marketIds) {
            val config = GameConfigEntity(
                id = "cfg_${tenantId}_$gId",
                tenantId = tenantId,
                gameId = gId,
                redMultiplier = 2.0,
                greenMultiplier = 2.0,
                violetMultiplier = 3.0,
                numberMultiplier = 9.0,
                roundDurationSec = 180, // 3 minutes per round
                bettingCutoffSec = 30, // 30 seconds Bet Close time
                minBet = 1000L, // ₹10
                maxBet = 5000000L, // ₹50,000
                payoutLimit = 50000000L // ₹500,000
            )
            gameConfigDao().insertConfig(config)
        }

        // 6. Audit Log
        val auditLog = AuditLogEntity(
            id = UUID.randomUUID().toString(),
            actorUserId = "user_super_admin",
            tenantId = tenantId,
            action = "PLATFORM_INITIALIZED",
            entityType = "SYSTEM",
            entityId = "TENANT_CONFIG",
            newValue = "Initialized Multi-Market Casino Platform with MIAMI, VEGAS, PARIS, DUBAI separate markets",
            requestId = "req_init_001"
        )
        auditDao().insertLog(auditLog)

        // 7. Seed 50 historical completed rounds for all 4 markets sharing synchronized period numbers & Web-identical results
        val historicalRounds = mutableListOf<GameRoundEntity>()
        val currentTime = System.currentTimeMillis()

        val marketCodeByGameId = mapOf(
            "market_miami" to "MIAMI",
            "market_vegas" to "VEGAS",
            "market_paris" to "PARIS",
            "market_dubai" to "DUBAI",
            "color_prediction" to "MIAMI"
        )

        for ((gId, mCode) in marketCodeByGameId) {
            for (i in 1..50) {
                val roundTime = currentTime - ((51 - i) * 180000L) // 3-minute steps
                val synced = com.example.domain.GlobalRoundClock.getSyncedState(roundTime)
                val periodNum = synced.periodNumber
                val seed = com.example.domain.ProvablyFairEngine.avalancheSeed(mCode, periodNum.toString())
                val hash = com.example.domain.ProvablyFairEngine.hashSha256(seed)
                val result = com.example.domain.ProvablyFairEngine.calculateAvalancheResult(mCode, periodNum.toString())

                historicalRounds.add(
                    GameRoundEntity(
                        roundId = if (gId == "color_prediction") "rnd_${tenantId}_LEGACY_$periodNum" else "rnd_${tenantId}_${mCode}_$periodNum",
                        gameId = gId,
                        tenantId = tenantId,
                        roundNumber = periodNum,
                        startTime = roundTime - 180000L,
                        bettingCloseTime = roundTime - 30000L,
                        resultTime = roundTime,
                        status = com.example.data.model.RoundStatus.COMPLETED.name,
                        resultNumber = result.number,
                        resultColor = result.color.name,
                        multiplier = 1.0,
                        serverSeedHash = hash,
                        serverSeed = seed,
                        nonce = periodNum,
                        clientSeed = "PROVABLY_FAIR_AVALANCHE",
                        createdAt = roundTime - 180000L,
                        settledAt = roundTime
                    )
                )
            }
        }
        gameRoundDao().insertRounds(historicalRounds)
    }
}
