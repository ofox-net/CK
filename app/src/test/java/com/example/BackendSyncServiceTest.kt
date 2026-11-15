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

    @Test
    fun updateUserProfileFields_preservesPasswordHash_andFindUserIsCaseInsensitive() = runBlocking {
        val tenantId = "tenant_apex_global"
        val userDao = database.userDao()
        val expectedHash = ProvablyFairEngine.hashSha256("MySecret@99")
        userDao.insertUser(
            com.example.data.model.UserEntity(
                id = "USR-900101",
                tenantId = tenantId,
                username = "AryanKing",
                email = "aryan@colourking.in",
                phone = "+919811223344",
                passwordHash = expectedHash,
                referralCode = "ARYA123",
                status = "ACTIVE"
            )
        )

        userDao.updateUserProfileFields(
            userId = "USR-900101",
            username = "AryanKing",
            email = "aryan.updated@colourking.in",
            phone = "+919811223344",
            status = "BLOCKED",
            referralCode = "ARYA123"
        )

        val reloaded = userDao.getUserById("USR-900101")
        assertNotNull(reloaded)
        assertEquals(expectedHash, reloaded!!.passwordHash)
        assertEquals("BLOCKED", reloaded.status)
        assertEquals("aryan.updated@colourking.in", reloaded.email)

        val byUpper = userDao.findUserByIdentifier(tenantId, "  ARYANKING  ")
        assertNotNull(byUpper)
        assertEquals("USR-900101", byUpper!!.id)
    }

    @Test
    fun registerAndLoginWithResult_handlesSuccessAndServerRejections() = runBlocking {
        val server = com.sun.net.httpserver.HttpServer.create(java.net.InetSocketAddress("127.0.0.1", 0), 0)
        val port = server.address.port
        val registeredPasswords = mutableMapOf<String, String>()

        server.createContext("/api/users/register") { ex ->
            val body = ex.requestBody.bufferedReader().readText()
            val req = org.json.JSONObject(body)
            val name = req.optString("name")
            val pw = req.optString("password")
            val (code, respStr) = if (registeredPasswords.containsKey(name.lowercase())) {
                409 to org.json.JSONObject()
                    .put("success", false)
                    .put("error", "Username already registered")
                    .toString()
            } else {
                registeredPasswords[name.lowercase()] = pw
                200 to org.json.JSONObject()
                    .put("success", true)
                    .put(
                        "user",
                        org.json.JSONObject()
                            .put("id", "USR-777001")
                            .put("name", name)
                            .put("phone", req.optString("phone"))
                            .put("email", "$name@colourking.in")
                            .put("balance", 100.0)
                            .put("status", "ACTIVE")
                            .put("referralCode", "TEST777")
                    )
                    .toString()
            }
            val bytes = respStr.toByteArray()
            ex.responseHeaders.add("Content-Type", "application/json")
            ex.sendResponseHeaders(code, bytes.size.toLong())
            ex.responseBody.use { it.write(bytes) }
        }

        server.createContext("/api/users/login") { ex ->
            val req = org.json.JSONObject(ex.requestBody.bufferedReader().readText())
            val idf = req.optString("identifier").lowercase()
            val pw = req.optString("password")
            val (code, respStr) = if (registeredPasswords[idf] == pw) {
                200 to org.json.JSONObject()
                    .put("success", true)
                    .put(
                        "user",
                        org.json.JSONObject()
                            .put("id", "USR-777001")
                            .put("name", idf)
                            .put("phone", "+919900112233")
                            .put("email", "$idf@colourking.in")
                            .put("balance", 100.0)
                            .put("status", "ACTIVE")
                            .put("referralCode", "TEST777")
                    )
                    .toString()
            } else {
                401 to org.json.JSONObject()
                    .put("success", false)
                    .put("error", "Invalid password. Please try again.")
                    .toString()
            }
            val bytes = respStr.toByteArray()
            ex.responseHeaders.add("Content-Type", "application/json")
            ex.sendResponseHeaders(code, bytes.size.toLong())
            ex.responseBody.use { it.write(bytes) }
        }

        server.start()
        try {
            val sync = BackendSyncService(context, "http://127.0.0.1:$port")
            val regOk = sync.registerUserWithResult(
                userId = "USR-777001",
                username = "karan99",
                phone = "+919900112233",
                email = "",
                balanceRupees = 100.0,
                password = "pass@123"
            )
            assertNotNull(regOk.user)
            assertEquals("USR-777001", regOk.user!!.id)
            assertEquals(false, regOk.isNetworkError)

            val regDup = sync.registerUserWithResult(
                userId = "USR-777002",
                username = "Karan99",
                phone = "+919900112233",
                email = "",
                balanceRupees = 100.0,
                password = "pass@123"
            )
            assertEquals(null, regDup.user)
            assertEquals(false, regDup.isNetworkError)
            assertTrue(regDup.error!!.contains("already", ignoreCase = true))

            // Repeated logins succeed cleanly
            repeat(3) {
                val loginOk = sync.loginUserWithResult("karan99", "pass@123")
                assertNotNull(loginOk.user)
                assertEquals("USR-777001", loginOk.user!!.id)
            }

            // Wrong password returns exact server rejection and isNetworkError=false
            val loginBad = sync.loginUserWithResult("karan99", "wrong")
            assertEquals(null, loginBad.user)
            assertEquals(false, loginBad.isNetworkError)
            assertEquals("Invalid password. Please try again.", loginBad.error)
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun parseStateSnapshotJson_preservesOldAndNewUsersFromUsersMapAndUsersList() {
        val syncService = BackendSyncService(context, "http://127.0.0.1:3000")
        val rawJson = """
            {
              "state_version": 99,
              "server_time_ms": 1794600000000,
              "users": {
                "USR-1001": { "id": "USR-1001", "name": "Rahul_Player", "balance": 500.0, "status": "ACTIVE" }
              },
              "users_list": [
                { "id": "USR-1001", "name": "Rahul_Player", "balance": 500.0, "status": "ACTIVE" },
                { "id": "USR-1002", "name": "Vikram_L6", "balance": 2500.0, "status": "ACTIVE" },
                { "id": "USR-888123", "name": "OldRegisteredUser", "balance": 100.0, "status": "ACTIVE" }
              ]
            }
        """.trimIndent()

        val snap = syncService.parseStateSnapshotJson(rawJson)
        assertEquals(3, snap.usersById.size)
        assertEquals("Rahul_Player", snap.usersById["USR-1001"]?.name)
        assertEquals("Vikram_L6", snap.usersById["USR-1002"]?.name)
        assertEquals("OldRegisteredUser", snap.usersById["USR-888123"]?.name)
    }

    @Test
    fun supportThreadAndMessage_parsesSituationAutoReplyAndAdminCustomReply() = runBlocking {
        val server = com.sun.net.httpserver.HttpServer.create(java.net.InetSocketAddress("127.0.0.1", 0), 0)
        val port = server.address.port

        server.createContext("/api/support/thread") { ex ->
            val respStr = org.json.JSONObject()
                .put("success", true)
                .put("unreadUser", 1)
                .put(
                    "ticket",
                    org.json.JSONObject()
                        .put("ticketId", "TKT-USR-1001")
                        .put("userId", "USR-1001")
                        .put("userName", "Rahul_Player")
                        .put("status", "OPEN")
                        .put("unreadUser", 1)
                )
                .put(
                    "situation",
                    org.json.JSONObject()
                        .put("userId", "USR-1001")
                        .put("userName", "Rahul_Player")
                        .put("accountStatus", "ACTIVE")
                        .put("balance", 1500.0)
                        .put("upiId", "colourking@icici")
                        .put("bankName", "SBI")
                        .put(
                            "pendingDeposit",
                            org.json.JSONObject()
                                .put("id", "DEP-101")
                                .put("amount", 500.0)
                                .put("status", "IN PROCESS")
                                .put("utr", "998877665544")
                        )
                )
                .put(
                    "messages",
                    org.json.JSONArray()
                        .put(
                            org.json.JSONObject()
                                .put("id", "MSG-1")
                                .put("ticketId", "TKT-USR-1001")
                                .put("userId", "USR-1001")
                                .put("senderType", "ADMIN")
                                .put("senderName", "ColourPrince")
                                .put("category", "DEPOSIT")
                                .put("message", "Checking your UTR right now.")
                                .put("isAuto", false)
                        )
                )
                .toString()
            val bytes = respStr.toByteArray()
            ex.responseHeaders.add("Content-Type", "application/json")
            ex.sendResponseHeaders(200, bytes.size.toLong())
            ex.responseBody.use { it.write(bytes) }
        }

        server.createContext("/api/support/message") { ex ->
            val req = org.json.JSONObject(ex.requestBody.bufferedReader().readText())
            val msg = req.optString("message")
            val respStr = org.json.JSONObject()
                .put("success", true)
                .put("unreadUser", 0)
                .put(
                    "ticket",
                    org.json.JSONObject()
                        .put("ticketId", "TKT-USR-1001")
                        .put("userId", "USR-1001")
                        .put("userName", "Rahul_Player")
                        .put("status", "OPEN")
                        .put("unreadUser", 0)
                )
                .put(
                    "messages",
                    org.json.JSONArray()
                        .put(
                            org.json.JSONObject()
                                .put("id", "MSG-2")
                                .put("ticketId", "TKT-USR-1001")
                                .put("userId", "USR-1001")
                                .put("senderType", "USER")
                                .put("senderName", "Rahul_Player")
                                .put("category", "DEPOSIT")
                                .put("message", msg)
                                .put("isAuto", false)
                        )
                        .put(
                            org.json.JSONObject()
                                .put("id", "MSG-3")
                                .put("ticketId", "TKT-USR-1001")
                                .put("userId", "USR-1001")
                                .put("senderType", "AUTO_BOT")
                                .put("senderName", "Colour King 24/7 Support Bot")
                                .put("category", "DEPOSIT")
                                .put("message", "Pending Deposit DEP-101 detected for ₹500.00.")
                                .put("isAuto", true)
                                .put("situationTag", "DEPOSIT_IN_PROCESS")
                        )
                )
                .toString()
            val bytes = respStr.toByteArray()
            ex.responseHeaders.add("Content-Type", "application/json")
            ex.sendResponseHeaders(200, bytes.size.toLong())
            ex.responseBody.use { it.write(bytes) }
        }

        server.start()
        try {
            val sync = BackendSyncService(context, "http://127.0.0.1:$port")
            val fetched = sync.fetchSupportThread("USR-1001", markRead = false, initWelcome = true)
            assertNotNull(fetched)
            assertEquals(1, fetched!!.unreadUser)
            assertEquals("DEP-101", fetched.situation?.pendingDeposit?.id)
            assertEquals("ADMIN", fetched.messages.first().senderType)

            val (sent, err) = sync.sendSupportMessage("USR-1001", "Check my deposit UTR", "DEPOSIT")
            assertEquals(null, err)
            assertNotNull(sent)
            assertEquals(2, sent!!.messages.size)
            assertEquals("AUTO_BOT", sent.messages.last().senderType)
            assertEquals("DEPOSIT_IN_PROCESS", sent.messages.last().situationTag)
        } finally {
            server.stop(0)
        }
    }
}
