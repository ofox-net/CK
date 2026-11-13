package com.example

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.local.AppDatabase
import com.example.domain.BackendSyncService
import com.example.domain.GameEngineService
import com.example.domain.GlobalRoundClock
import com.example.domain.ProvablyFairEngine
import com.example.domain.ReferralCommissionService
import com.example.domain.ServerDeclaredResult
import com.example.domain.ServerRoundOverride
import com.example.domain.WalletService
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class BackendSyncServiceTest {

    private lateinit var context: Context
    private lateinit var database: AppDatabase
    private lateinit var gameEngineService: GameEngineService

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        val walletService = WalletService(database)
        val commissionService = ReferralCommissionService(database)
        gameEngineService = GameEngineService(database, walletService, commissionService)
        GlobalRoundClock.serverOffsetMs = 0L
    }

    @After
    fun tearDown() {
        GlobalRoundClock.serverOffsetMs = 0L
        gameEngineService.stopEngine()
        database.close()
    }

    @Test
    fun parseStateSnapshotJson_parsesAdminActionsAndUserStatus() {
        val syncService = BackendSyncService(context, "http://127.0.0.1:3000")
        val rawJson = """
            {
              "state_version": 42,
              "server_time_ms": 1794600000000,
              "bank_config": {
                "upiId": "adminpay@hdfc",
                "upiName": "Admin Gateway",
                "bankName": "HDFC Bank",
                "accNo": "9988776655",
                "ifsc": "HDFC0001122",
                "holder": "Colour King Ops",
                "minDep": 500,
                "maxDep": 250000
              },
              "draw_overrides": {
                "MIAMI": { "number": 7, "period": "20261113301", "color": "GREEN", "mode": "MANUAL" }
              },
              "declared_results": {
                "VEGAS": {
                  "20261113300": {
                    "period": "20261113300",
                    "number": 5,
                    "color": "GREEN + VIOLET",
                    "colClass": "green-violet",
                    "isBig": true,
                    "mode": "ADMIN_DECLARED",
                    "time": "12:00:00"
                  }
                }
              },
              "users": {
                "USR-1001": {
                  "id": "USR-1001",
                  "name": "Rahul_Player",
                  "phone": "9876543210",
                  "email": "rahul@apexcasino.com",
                  "balance": 61500.50,
                  "totalDeposit": 70000.0,
                  "totalWithdraw": 8500.0,
                  "betsCount": 14,
                  "status": "BLOCKED",
                  "referralCode": "RAHUL777",
                  "referredBy": null
                }
              },
              "deposits": [
                {
                  "id": "DEP-9001",
                  "userId": "USR-1001",
                  "userName": "Rahul_Player",
                  "amount": 2500.0,
                  "method": "UPI Instant",
                  "utr": "123456789012",
                  "time": "12:01:00",
                  "status": "SUCCESS",
                  "reason": null
                }
              ],
              "withdrawals": [
                {
                  "id": "WD-8001",
                  "userId": "USR-1001",
                  "userName": "Rahul_Player",
                  "amount": 1200.0,
                  "upiId": "rahul@okaxis",
                  "bankName": "SBI",
                  "accNo": "11223344",
                  "ifsc": "SBIN0000123",
                  "bankingName": "Rahul",
                  "destination": "UPI",
                  "time": "12:05:00",
                  "status": "FAIL",
                  "reason": "Invalid IFSC"
                }
              ]
            }
        """.trimIndent()

        val snap = syncService.parseStateSnapshotJson(rawJson)
        assertEquals(42L, snap.stateVersion)
        assertEquals("adminpay@hdfc", snap.bankConfig.upiId)
        assertEquals(500L, snap.bankConfig.minDep)
        assertEquals(250000L, snap.bankConfig.maxDep)
        assertEquals(7, snap.drawOverrides["MIAMI"]?.number)
        assertEquals(5, snap.declaredResults["VEGAS"]?.get("20261113300")?.number)
        assertEquals("BLOCKED", snap.usersById["USR-1001"]?.status)
        assertEquals(61500.50, snap.usersById["USR-1001"]!!.balanceRupees, 0.001)
        assertEquals("SUCCESS", snap.deposits.first().status)
        assertEquals("FAIL", snap.withdrawals.first().status)
        assertEquals("Invalid IFSC", snap.withdrawals.first().reason)
    }

    @Test
    fun idAndMarketMappingsMatchBackendConventions() {
        assertEquals("USR-1001", BackendSyncService.mapNativeToServerUserId("user_player_rahul"))
        assertEquals("USR-1002", BackendSyncService.mapNativeToServerUserId("user_ref_l1"))
        assertEquals("market_dubai", BackendSyncService.marketCodeToNativeGameId("DUBAI"))
        assertEquals("PARIS", BackendSyncService.nativeGameIdToMarketCode("market_paris"))
    }

    @Test
    fun applyServerSync_overridesOfficialResultAndUpdatesLatestResult() = runBlocking {
        val declaredPeriod = "20261113310"
        val declared = mapOf(
            "VEGAS" to mapOf(
                declaredPeriod to ServerDeclaredResult(
                    marketCode = "VEGAS",
                    period = declaredPeriod,
                    number = 0,
                    color = "RED + VIOLET",
                    colClass = "red-violet",
                    isBig = false,
                    mode = "ADMIN_DECLARED",
                    time = "13:00:00"
                )
            )
        )
        val overrides = mapOf(
            "MIAMI" to ServerRoundOverride(
                marketCode = "MIAMI",
                number = 9,
                period = "20261113311",
                color = "GREEN",
                mode = "MANUAL"
            )
        )

        gameEngineService.applyServerSync("tenant_apex_global", overrides, declared)

        val vegasResolved = gameEngineService.resolveOfficialResult("VEGAS", declaredPeriod)
        assertEquals(0, vegasResolved.number)
        assertEquals(0, gameEngineService.getLatestResultFlow("market_vegas").value?.number)

        val miamiResolved = gameEngineService.resolveOfficialResult("MIAMI", "20261113311")
        assertEquals(9, miamiResolved.number)

        // Fallback period without override or declared result stays deterministic Avalanche
        val fallbackExpected = ProvablyFairEngine.calculateAvalancheResult("PARIS", "20261113310")
        assertEquals(fallbackExpected.number, gameEngineService.resolveOfficialResult("PARIS", "20261113310").number)
    }

    @Test
    fun serverOffsetShiftsGlobalRoundClockDeterministically() {
        val baseNow = 1794650000000L
        val stateAtBase = GlobalRoundClock.getSyncedState(baseNow)
        val statePlus3Min = GlobalRoundClock.getSyncedState(baseNow + 180_000L)
        assertNotNull(stateAtBase)
        assertEquals(stateAtBase.periodNumber + 1L, statePlus3Min.periodNumber)
        assertTrue(stateAtBase.secondsLeft in 0..180)
    }
}
