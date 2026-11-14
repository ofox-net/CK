package com.example.domain

import android.content.Context
import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.concurrent.TimeUnit
import kotlin.math.roundToLong

data class BankConfigState(
    val upiId: String = "colourking@icici",
    val upiName: String = "Colour King Official Pay",
    val bankName: String = "State Bank of India (SBI)",
    val accNo: String = "40928172901",
    val ifsc: String = "SBIN0001824",
    val holder: String = "Colour King Gaming Enterprise Ltd",
    val minDep: Long = 100L,
    val maxDep: Long = 100000L
)

data class ServerRoundOverride(
    val marketCode: String,
    val number: Int,
    val period: String?,
    val color: String,
    val mode: String = "MANUAL"
)

data class ServerDeclaredResult(
    val marketCode: String,
    val period: String,
    val number: Int,
    val color: String,
    val colClass: String,
    val isBig: Boolean,
    val mode: String,
    val time: String
)

data class ServerUserState(
    val id: String,
    val name: String,
    val phone: String,
    val email: String,
    val balanceRupees: Double,
    val totalDepositRupees: Double,
    val totalWithdrawRupees: Double,
    val betsCount: Int,
    val status: String,
    val referralCode: String,
    val referredBy: String?
)

data class ServerDepositItem(
    val id: String,
    val userId: String,
    val userName: String,
    val amountRupees: Double,
    val method: String,
    val utr: String,
    val time: String,
    val status: String,
    val reason: String?
)

data class ServerWithdrawalItem(
    val id: String,
    val userId: String,
    val userName: String,
    val amountRupees: Double,
    val upiId: String,
    val bankName: String,
    val accNo: String,
    val ifsc: String,
    val bankingName: String,
    val destination: String,
    val time: String,
    val status: String,
    val reason: String?
)

data class ServerBetItem(
    val id: String,
    val marketId: String,
    val roundId: String,
    val period: String,
    val amountRupees: Double,
    val platformFeeRupees: Double = 0.0,
    val netAmountRupees: Double = 0.0,
    val type: String,
    val target: String,
    val mult: Double,
    val potentialPayoutRupees: Double,
    val status: String,
    val result: String?,
    val winAmountRupees: Double,
    val lossAmountRupees: Double,
    val time: String,
    val createdAtMs: Long
)

data class ServerPushEvent(
    val version: Long,
    val eventType: String,
    val targetUserId: String? = null,
    val reason: String? = null,
    val marketCode: String? = null,
    val serverTimeMs: Long = System.currentTimeMillis()
)

data class ServerAffiliateMember(
    val id: String,
    val name: String,
    val tier: Int,
    val tierLabel: String,
    val joined: String,
    val totalDepositRupees: Double,
    val turnoverRupees: Double,
    val commissionRupees: Double,
    val status: String
)

data class ServerAffiliateCommission(
    val id: String,
    val sourceUserId: String,
    val sourceUserName: String,
    val sourceBetId: String,
    val level: Int,
    val rate: Double,
    val eligibleAmountRupees: Double,
    val commissionAmountRupees: Double,
    val status: String,
    val createdAt: String,
    val createdAtMs: Long
)

data class ServerAffiliateStats(
    val userId: String,
    val userName: String,
    val referralCode: String,
    val lifetimeCommissionRupees: Double,
    val todayCommissionRupees: Double,
    val networkTurnoverRupees: Double,
    val teamCount: Int,
    val directCount: Int,
    val members: List<ServerAffiliateMember> = emptyList(),
    val recentCommissions: List<ServerAffiliateCommission> = emptyList()
)

data class ServerSyncSnapshot(
    val stateVersion: Long = 0L,
    val serverTimeMs: Long = 0L,
    val bankConfig: BankConfigState = BankConfigState(),
    val drawOverrides: Map<String, ServerRoundOverride> = emptyMap(),
    val declaredResults: Map<String, Map<String, ServerDeclaredResult>> = emptyMap(),
    val usersById: Map<String, ServerUserState> = emptyMap(),
    val deposits: List<ServerDepositItem> = emptyList(),
    val withdrawals: List<ServerWithdrawalItem> = emptyList()
)

data class ServerAuthResult(
    val user: ServerUserState? = null,
    val error: String? = null,
    val isNetworkError: Boolean = false
)

class BackendSyncService(
    private val context: Context? = null,
    initialBaseUrl: String? = null
) {
    companion object {
        private const val TAG = "BackendSyncService"
        private const val PREFS_NAME = "colour_king_sync"
        private const val KEY_BACKEND_URL = "backend_base_url"

        val DEFAULT_CANDIDATE_URLS = listOf(
            "http://10.0.2.2:3000",
            "http://127.0.0.1:3000",
            "https://ais-dev-zgi6cruhcpqtgg5frvcozc-221262354191.asia-southeast1.run.app",
            "https://ais-pre-zgi6cruhcpqtgg5frvcozc-221262354191.asia-southeast1.run.app"
        )

        fun mapNativeToServerUserId(nativeUserId: String, activeUsername: String? = null): String {
            return when (nativeUserId) {
                "user_player_rahul" -> "USR-1001"
                "user_ref_l1" -> "USR-1002"
                "user_ref_l2" -> "USR-1003"
                "user_super_admin" -> "USR-1001"
                else -> nativeUserId
            }
        }

        fun marketCodeToNativeGameId(marketCode: String): String {
            return when (marketCode.uppercase()) {
                "MIAMI" -> "market_miami"
                "VEGAS" -> "market_vegas"
                "PARIS" -> "market_paris"
                "DUBAI" -> "market_dubai"
                else -> "market_miami"
            }
        }

        fun nativeGameIdToMarketCode(gameId: String): String {
            return when (gameId) {
                "market_miami", "color_prediction" -> "MIAMI"
                "market_vegas" -> "VEGAS"
                "market_paris" -> "PARIS"
                "market_dubai" -> "DUBAI"
                else -> gameId.removePrefix("market_").uppercase()
            }
        }

        fun normalizeUrl(raw: String?): String {
            return (raw ?: "").trim().trimEnd('/')
        }
    }

    private val prefs by lazy {
        context?.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(6, TimeUnit.SECONDS)
        .writeTimeout(6, TimeUnit.SECONDS)
        .build()

    private val probeClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .writeTimeout(2, TimeUnit.SECONDS)
        .build()

    private val sseClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS) // Long-lived SSE stream
        .build()

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val initialResolvedUrl: String = normalizeUrl(
        initialBaseUrl ?: prefs?.getString(KEY_BACKEND_URL, null)
    ).ifBlank { DEFAULT_CANDIDATE_URLS.first() }

    private val _activeBackendUrl = MutableStateFlow(initialResolvedUrl)
    val activeBackendUrl: StateFlow<String> = _activeBackendUrl.asStateFlow()

    private val _connectionStatus = MutableStateFlow("CONNECTING")
    val connectionStatus: StateFlow<String> = _connectionStatus.asStateFlow()

    private val _snapshot = MutableStateFlow(ServerSyncSnapshot())
    val snapshot: StateFlow<ServerSyncSnapshot> = _snapshot.asStateFlow()

    private val _pushEvents = MutableSharedFlow<ServerPushEvent>(
        replay = 0,
        extraBufferCapacity = 64,
        onBufferOverflow = BufferOverflow.DROP_OLDEST
    )
    val pushEvents: SharedFlow<ServerPushEvent> = _pushEvents.asSharedFlow()

    @Volatile
    private var lastKnownVersion: Long = -1L

    private var hasCustomOverride: Boolean = !prefs?.getString(KEY_BACKEND_URL, null).isNullOrBlank() || !initialBaseUrl.isNullOrBlank()
    private var sseJob: Job? = null
    private var pollJob: Job? = null
    @Volatile
    private var isStarted: Boolean = false

    fun start() {
        if (isStarted) return
        isStarted = true

        scope.launch {
            if (!hasCustomOverride) {
                resolveReachableBackendUrl()
            }
            fetchStateSnapshot(force = true)
            launchSseListener()
            launchFallbackPolling()
        }
    }

    fun stop() {
        isStarted = false
        sseJob?.cancel()
        pollJob?.cancel()
        sseJob = null
        pollJob = null
    }

    fun setCustomBackendUrl(rawUrl: String) {
        val clean = normalizeUrl(rawUrl)
        if (clean.isBlank()) {
            hasCustomOverride = false
            prefs?.edit()?.remove(KEY_BACKEND_URL)?.apply()
            scope.launch {
                resolveReachableBackendUrl()
                restartStreams()
            }
            return
        }
        hasCustomOverride = true
        prefs?.edit()?.putString(KEY_BACKEND_URL, clean)?.apply()
        _activeBackendUrl.value = clean
        lastKnownVersion = -1L
        scope.launch {
            restartStreams()
        }
    }

    private suspend fun restartStreams() {
        sseJob?.cancel()
        pollJob?.cancel()
        fetchStateSnapshot(force = true)
        launchSseListener()
        launchFallbackPolling()
    }

    suspend fun resolveReachableBackendUrl(): String = withContext(Dispatchers.IO) {
        val saved = normalizeUrl(prefs?.getString(KEY_BACKEND_URL, null))
        val candidates = buildList {
            if (saved.isNotBlank()) add(saved)
            addAll(DEFAULT_CANDIDATE_URLS)
        }.distinct()

        val probeResults = candidates.map { candidate ->
            async { candidate to probeHealth(candidate) }
        }.awaitAll()

        val winner = probeResults.firstOrNull { it.second }?.first
        if (winner != null) {
            _activeBackendUrl.value = winner
            return@withContext winner
        }
        return@withContext _activeBackendUrl.value
    }

    private fun probeHealth(baseUrl: String): Boolean {
        return try {
            val req = Request.Builder()
                .url("$baseUrl/api/state/version")
                .get()
                .build()
            probeClient.newCall(req).execute().use { resp ->
                resp.isSuccessful
            }
        } catch (_: Exception) {
            false
        }
    }

    private fun launchSseListener() {
        sseJob?.cancel()
        sseJob = scope.launch {
            var retryDelayMs = 1000L
            while (isActive && isStarted) {
                val baseUrl = _activeBackendUrl.value
                try {
                    val req = Request.Builder()
                        .url("$baseUrl/api/events")
                        .header("Accept", "text/event-stream")
                        .header("Cache-Control", "no-cache")
                        .get()
                        .build()

                    sseClient.newCall(req).execute().use { resp ->
                        if (!resp.isSuccessful) {
                            throw IllegalStateException("SSE HTTP ${resp.code}")
                        }
                        _connectionStatus.value = "SSE LIVE"
                        retryDelayMs = 1000L

                        val bodyStream = resp.body?.byteStream() ?: throw IllegalStateException("Empty SSE body")
                        val reader = BufferedReader(InputStreamReader(bodyStream, Charsets.UTF_8))
                        var currentEventName = "message"
                        val dataBuf = StringBuilder()

                        while (isActive && isStarted) {
                            val line = reader.readLine() ?: break
                            when {
                                line.startsWith("event:") -> {
                                    currentEventName = line.substringAfter("event:").trim()
                                }
                                line.startsWith("data:") -> {
                                    if (dataBuf.isNotEmpty()) dataBuf.append('\n')
                                    dataBuf.append(line.substringAfter("data:").trim())
                                }
                                line.isEmpty() -> {
                                    if (dataBuf.isNotEmpty()) {
                                        handleSseFrame(currentEventName, dataBuf.toString())
                                        dataBuf.setLength(0)
                                    }
                                    currentEventName = "message"
                                }
                            }
                        }
                    }
                } catch (ce: CancellationException) {
                    throw ce
                } catch (e: Exception) {
                    Log.d(TAG, "SSE disconnected ($baseUrl): ${e.message}")
                    if (_connectionStatus.value == "SSE LIVE") {
                        _connectionStatus.value = "POLLING"
                    }
                    if (!hasCustomOverride) {
                        resolveReachableBackendUrl()
                    }
                }
                delay(retryDelayMs)
                retryDelayMs = (retryDelayMs * 2).coerceAtMost(6000L)
            }
        }
    }

    private suspend fun handleSseFrame(eventName: String, rawJson: String) {
        try {
            val obj = JSONObject(rawJson)
            val version = obj.optLong("version", -1L)
            val eventType = obj.optString("eventType", eventName)
            val detail = obj.optJSONObject("detail")
            val targetUserId = detail?.optString("userId")?.takeIf { it.isNotBlank() }
                ?: obj.optString("userId").takeIf { it.isNotBlank() }
            val reason = detail?.optString("reason")?.takeIf { it.isNotBlank() }
                ?: obj.optString("reason").takeIf { it.isNotBlank() }
            val marketCode = detail?.optString("market")?.takeIf { it.isNotBlank() }
            val serverTimeMs = obj.optLong("serverTimeMs", System.currentTimeMillis())

            if (serverTimeMs > 0L) {
                GlobalRoundClock.serverOffsetMs = serverTimeMs - System.currentTimeMillis()
            }

            val pushEvent = ServerPushEvent(
                version = version,
                eventType = eventType,
                targetUserId = targetUserId,
                reason = reason,
                marketCode = marketCode,
                serverTimeMs = serverTimeMs
            )

            fetchStateSnapshot(force = true)
            _pushEvents.tryEmit(pushEvent)
        } catch (e: Exception) {
            Log.w(TAG, "Failed to parse SSE frame: ${e.message}")
        }
    }

    private fun launchFallbackPolling() {
        pollJob?.cancel()
        pollJob = scope.launch {
            while (isActive && isStarted) {
                try {
                    val baseUrl = _activeBackendUrl.value
                    val versionReq = Request.Builder()
                        .url("$baseUrl/api/state/version")
                        .get()
                        .build()
                    var shouldFetchFull = false
                    httpClient.newCall(versionReq).execute().use { resp ->
                        if (resp.isSuccessful) {
                            val bodyStr = resp.body?.string() ?: "{}"
                            val obj = JSONObject(bodyStr)
                            val srvVer = obj.optLong("state_version", -1L)
                            val srvTime = obj.optLong("server_time_ms", 0L)
                            if (srvTime > 0L) {
                                GlobalRoundClock.serverOffsetMs = srvTime - System.currentTimeMillis()
                            }
                            if (_connectionStatus.value != "SSE LIVE") {
                                _connectionStatus.value = "POLLING"
                            }
                            if (srvVer != lastKnownVersion || srvVer == -1L) {
                                shouldFetchFull = true
                            }
                        } else {
                            if (_connectionStatus.value != "SSE LIVE") {
                                _connectionStatus.value = "OFFLINE"
                            }
                        }
                    }
                    if (shouldFetchFull) {
                        fetchStateSnapshot(force = true)
                    }
                } catch (ce: CancellationException) {
                    throw ce
                } catch (_: Exception) {
                    if (_connectionStatus.value != "SSE LIVE") {
                        _connectionStatus.value = "OFFLINE"
                    }
                }
                delay(3000L)
            }
        }
    }

    suspend fun forceSyncNow(): ServerSyncSnapshot? {
        return fetchStateSnapshot(force = true)
    }

    suspend fun fetchStateSnapshot(force: Boolean = false): ServerSyncSnapshot? = withContext(Dispatchers.IO) {
        val baseUrl = _activeBackendUrl.value
        return@withContext try {
            val req = Request.Builder()
                .url("$baseUrl/api/state?t=${System.currentTimeMillis()}")
                .header("Cache-Control", "no-store")
                .get()
                .build()
            httpClient.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@use null
                val raw = resp.body?.string() ?: return@use null
                val parsed = parseStateSnapshotJson(raw)
                if (parsed.serverTimeMs > 0L) {
                    GlobalRoundClock.serverOffsetMs = parsed.serverTimeMs - System.currentTimeMillis()
                }
                if (force || parsed.stateVersion != lastKnownVersion) {
                    lastKnownVersion = parsed.stateVersion
                    _snapshot.value = parsed
                }
                parsed
            }
        } catch (_: Exception) {
            null
        }
    }

    fun parseStateSnapshotJson(rawJson: String): ServerSyncSnapshot {
        val root = JSONObject(rawJson)
        val version = root.optLong("state_version", 0L)
        val serverTimeMs = root.optLong("server_time_ms", System.currentTimeMillis())

        // 1. Bank Config
        val bcObj = root.optJSONObject("bank_config")
        val bankConfig = if (bcObj != null) {
            BankConfigState(
                upiId = bcObj.optString("upiId", "colourking@icici"),
                upiName = bcObj.optString("upiName", "Colour King Official Pay"),
                bankName = bcObj.optString("bankName", "State Bank of India (SBI)"),
                accNo = bcObj.optString("accNo", "40928172901"),
                ifsc = bcObj.optString("ifsc", "SBIN0001824"),
                holder = bcObj.optString("holder", "Colour King Gaming Enterprise Ltd"),
                minDep = bcObj.optLong("minDep", 100L),
                maxDep = bcObj.optLong("maxDep", 100000L)
            )
        } else BankConfigState()

        // 2. Draw Overrides
        val overridesMap = mutableMapOf<String, ServerRoundOverride>()
        val ovObj = root.optJSONObject("draw_overrides")
        if (ovObj != null) {
            val keys = ovObj.keys()
            while (keys.hasNext()) {
                val mCode = keys.next()
                val item = ovObj.optJSONObject(mCode) ?: continue
                if (!item.isNull("number")) {
                    overridesMap[mCode.uppercase()] = ServerRoundOverride(
                        marketCode = mCode.uppercase(),
                        number = item.optInt("number"),
                        period = item.optString("period").takeIf { it.isNotBlank() && it != "null" },
                        color = item.optString("color", ""),
                        mode = item.optString("mode", "MANUAL")
                    )
                }
            }
        }

        // 3. Declared Results
        val declaredMap = mutableMapOf<String, Map<String, ServerDeclaredResult>>()
        val decObj = root.optJSONObject("declared_results")
        if (decObj != null) {
            val mKeys = decObj.keys()
            while (mKeys.hasNext()) {
                val mCode = mKeys.next()
                val periodObj = decObj.optJSONObject(mCode) ?: continue
                val inner = mutableMapOf<String, ServerDeclaredResult>()
                val pKeys = periodObj.keys()
                while (pKeys.hasNext()) {
                    val periodStr = pKeys.next()
                    val rObj = periodObj.optJSONObject(periodStr) ?: continue
                    inner[periodStr] = ServerDeclaredResult(
                        marketCode = mCode.uppercase(),
                        period = rObj.optString("period", periodStr),
                        number = rObj.optInt("number", 0),
                        color = rObj.optString("color", "green"),
                        colClass = rObj.optString("colClass", "green"),
                        isBig = rObj.optBoolean("isBig", false),
                        mode = rObj.optString("mode", "AUTO_RANDOM"),
                        time = rObj.optString("time", "")
                    )
                }
                declaredMap[mCode.uppercase()] = inner
            }
        }

        // 4. Users
        val usersMap = mutableMapOf<String, ServerUserState>()
        val usersObj = root.optJSONObject("users")
        if (usersObj != null) {
            val uKeys = usersObj.keys()
            while (uKeys.hasNext()) {
                val uId = uKeys.next()
                val uObj = usersObj.optJSONObject(uId) ?: continue
                usersMap[uId] = ServerUserState(
                    id = uObj.optString("id", uId),
                    name = uObj.optString("name", uId),
                    phone = uObj.optString("phone", ""),
                    email = uObj.optString("email", ""),
                    balanceRupees = uObj.optDouble("balance", 0.0),
                    totalDepositRupees = uObj.optDouble("totalDeposit", 0.0),
                    totalWithdrawRupees = uObj.optDouble("totalWithdraw", 0.0),
                    betsCount = uObj.optInt("betsCount", 0),
                    status = uObj.optString("status", "ACTIVE").uppercase(),
                    referralCode = uObj.optString("referralCode", ""),
                    referredBy = uObj.optString("referredBy").takeIf { it.isNotBlank() && it != "null" }
                )
            }
        }

        // 5. Deposits
        val depsList = mutableListOf<ServerDepositItem>()
        val depsArr = root.optJSONArray("deposits") ?: JSONArray()
        for (i in 0 until depsArr.length()) {
            val d = depsArr.optJSONObject(i) ?: continue
            depsList.add(
                ServerDepositItem(
                    id = d.optString("id"),
                    userId = d.optString("userId"),
                    userName = d.optString("userName"),
                    amountRupees = d.optDouble("amount", 0.0),
                    method = d.optString("method", "UPI"),
                    utr = d.optString("utr", ""),
                    time = d.optString("time", ""),
                    status = d.optString("status", "IN PROCESS").uppercase(),
                    reason = d.optString("reason").takeIf { it.isNotBlank() && it != "null" }
                )
            )
        }

        // 6. Withdrawals
        val wdsList = mutableListOf<ServerWithdrawalItem>()
        val wdsArr = root.optJSONArray("withdrawals") ?: JSONArray()
        for (i in 0 until wdsArr.length()) {
            val w = wdsArr.optJSONObject(i) ?: continue
            wdsList.add(
                ServerWithdrawalItem(
                    id = w.optString("id"),
                    userId = w.optString("userId"),
                    userName = w.optString("userName"),
                    amountRupees = w.optDouble("amount", 0.0),
                    upiId = w.optString("upiId", ""),
                    bankName = w.optString("bankName", ""),
                    accNo = w.optString("accNo", ""),
                    ifsc = w.optString("ifsc", ""),
                    bankingName = w.optString("bankingName", ""),
                    destination = w.optString("destination", ""),
                    time = w.optString("time", ""),
                    status = w.optString("status", "IN PROCESS").uppercase(),
                    reason = w.optString("reason").takeIf { it.isNotBlank() && it != "null" }
                )
            )
        }

        return ServerSyncSnapshot(
            stateVersion = version,
            serverTimeMs = serverTimeMs,
            bankConfig = bankConfig,
            drawOverrides = overridesMap,
            declaredResults = declaredMap,
            usersById = usersMap,
            deposits = depsList,
            withdrawals = wdsList
        )
    }

    suspend fun fetchUserBets(serverUserId: String, days: Int = 90): List<ServerBetItem>? = withContext(Dispatchers.IO) {
        val baseUrl = _activeBackendUrl.value
        return@withContext try {
            val req = Request.Builder()
                .url("$baseUrl/api/bets?userId=$serverUserId&days=$days")
                .get()
                .build()
            httpClient.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@use null
                val root = JSONObject(resp.body?.string() ?: return@use null)
                val out = mutableListOf<ServerBetItem>()
                val hist = root.optJSONArray("betHistory") ?: JSONArray()
                for (i in 0 until hist.length()) {
                    val b = hist.optJSONObject(i) ?: continue
                    val grossAmt = b.optDouble("amount", 0.0)
                    val parsedFee = b.optDouble("platformFee", -1.0).let {
                        if (it >= 0.0) it else kotlin.math.round(grossAmt * 3.0) / 100.0
                    }
                    val parsedNet = b.optDouble("netAmount", -1.0).let {
                        if (it > 0.0) it else kotlin.math.max(0.0, kotlin.math.round((grossAmt - parsedFee) * 100.0) / 100.0)
                    }
                    out.add(
                        ServerBetItem(
                            id = b.optString("id"),
                            marketId = b.optString("marketId", "MIAMI"),
                            roundId = b.optString("roundId", ""),
                            period = b.optString("period", ""),
                            amountRupees = grossAmt,
                            platformFeeRupees = parsedFee,
                            netAmountRupees = parsedNet,
                            type = b.optString("type", "COLOR"),
                            target = b.optString("target", ""),
                            mult = b.optDouble("mult", 2.0),
                            potentialPayoutRupees = b.optDouble("potentialPayout", 0.0),
                            status = b.optString("status", "PENDING").uppercase(),
                            result = b.optString("result").takeIf { it.isNotBlank() && it != "null" },
                            winAmountRupees = b.optDouble("winAmount", 0.0),
                            lossAmountRupees = b.optDouble("lossAmount", 0.0),
                            time = b.optString("time", ""),
                            createdAtMs = b.optLong("createdAtMs", System.currentTimeMillis())
                        )
                    )
                }
                out
            }
        } catch (_: Exception) {
            null
        }
    }

    suspend fun fetchUserById(serverUserId: String): ServerUserState? = withContext(Dispatchers.IO) {
        if (serverUserId.isBlank()) return@withContext null
        val baseUrl = _activeBackendUrl.value
        return@withContext try {
            val req = Request.Builder()
                .url("$baseUrl/api/wallet?userId=$serverUserId")
                .get()
                .build()
            httpClient.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@use null
                val root = JSONObject(resp.body?.string() ?: return@use null)
                val uObj = root.optJSONObject("user") ?: root
                if (!uObj.has("id")) return@use null
                ServerUserState(
                    id = uObj.optString("id"),
                    name = uObj.optString("name", uObj.optString("id")),
                    phone = uObj.optString("phone", ""),
                    email = uObj.optString("email", ""),
                    balanceRupees = uObj.optDouble("balance", 0.0),
                    totalDepositRupees = uObj.optDouble("totalDeposit", 0.0),
                    totalWithdrawRupees = uObj.optDouble("totalWithdraw", 0.0),
                    betsCount = uObj.optInt("betsCount", 0),
                    status = uObj.optString("status", "ACTIVE").uppercase(),
                    referralCode = uObj.optString("referralCode", ""),
                    referredBy = uObj.optString("referredBy").takeIf { it.isNotBlank() && it != "null" }
                )
            }
        } catch (_: Exception) {
            null
        }
    }

    suspend fun fetchUserAffiliates(serverUserId: String): ServerAffiliateStats? = withContext(Dispatchers.IO) {
        if (serverUserId.isBlank()) return@withContext null
        val baseUrl = _activeBackendUrl.value
        return@withContext try {
            val req = Request.Builder()
                .url("$baseUrl/api/affiliates?userId=$serverUserId&t=${System.currentTimeMillis()}")
                .get()
                .build()
            httpClient.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return@use null
                val root = JSONObject(resp.body?.string() ?: return@use null)
                if (root.optBoolean("notFound", false)) return@use null

                val membersList = mutableListOf<ServerAffiliateMember>()
                val mArr = root.optJSONArray("members") ?: JSONArray()
                for (i in 0 until mArr.length()) {
                    val m = mArr.optJSONObject(i) ?: continue
                    membersList.add(
                        ServerAffiliateMember(
                            id = m.optString("id"),
                            name = m.optString("name", m.optString("id")),
                            tier = m.optInt("tier", 1),
                            tierLabel = m.optString("tierLabel", "Tier 1"),
                            joined = m.optString("joined", ""),
                            totalDepositRupees = m.optDouble("totalDeposit", 0.0),
                            turnoverRupees = m.optDouble("turnover", 0.0),
                            commissionRupees = m.optDouble("commission", 0.0),
                            status = m.optString("status", "ACTIVE").uppercase()
                        )
                    )
                }

                val commsList = mutableListOf<ServerAffiliateCommission>()
                val cArr = root.optJSONArray("recentCommissions") ?: JSONArray()
                for (i in 0 until cArr.length()) {
                    val c = cArr.optJSONObject(i) ?: continue
                    commsList.add(
                        ServerAffiliateCommission(
                            id = c.optString("id"),
                            sourceUserId = c.optString("sourceUserId", ""),
                            sourceUserName = c.optString("sourceUserName", ""),
                            sourceBetId = c.optString("sourceBetId", ""),
                            level = c.optInt("level", 1),
                            rate = c.optDouble("rate", 0.01),
                            eligibleAmountRupees = c.optDouble("eligibleAmount", 0.0),
                            commissionAmountRupees = c.optDouble("commissionAmount", 0.0),
                            status = c.optString("status", "SETTLED").uppercase(),
                            createdAt = c.optString("createdAt", ""),
                            createdAtMs = c.optLong("createdAtMs", System.currentTimeMillis())
                        )
                    )
                }

                ServerAffiliateStats(
                    userId = root.optString("userId", serverUserId),
                    userName = root.optString("userName", serverUserId),
                    referralCode = root.optString("referralCode", ""),
                    lifetimeCommissionRupees = root.optDouble("lifetimeCommission", 0.0),
                    todayCommissionRupees = root.optDouble("todayCommission", 0.0),
                    networkTurnoverRupees = root.optDouble("networkTurnover", 0.0),
                    teamCount = root.optInt("teamCount", membersList.size),
                    directCount = root.optInt("directCount", membersList.count { it.tier == 1 }),
                    members = membersList,
                    recentCommissions = commsList
                )
            }
        } catch (_: Exception) {
            null
        }
    }

    suspend fun adjustUserBalanceOnServer(
        serverUserId: String,
        amountDeltaRupees: Double,
        reason: String
    ): Boolean = withContext(Dispatchers.IO) {
        if (serverUserId.isBlank()) return@withContext false
        val payload = JSONObject().apply {
            put("userId", serverUserId)
            put("delta", amountDeltaRupees)
            put("type", if (amountDeltaRupees >= 0.0) "CREDIT" else "DEBIT")
            put("amount", kotlin.math.abs(amountDeltaRupees))
            put("reason", reason)
        }
        val resp = postJsonWithStatus("/api/user/adjust", payload)
        return@withContext resp?.optBoolean("success", false) == true
    }

    private fun parseServerUser(uObj: JSONObject): ServerUserState {
        return ServerUserState(
            id = uObj.optString("id"),
            name = uObj.optString("name", uObj.optString("id")),
            phone = uObj.optString("phone", ""),
            email = uObj.optString("email", ""),
            balanceRupees = uObj.optDouble("balance", 0.0),
            totalDepositRupees = uObj.optDouble("totalDeposit", 0.0),
            totalWithdrawRupees = uObj.optDouble("totalWithdraw", 0.0),
            betsCount = uObj.optInt("betsCount", 0),
            status = uObj.optString("status", "ACTIVE").uppercase(),
            referralCode = uObj.optString("referralCode", ""),
            referredBy = uObj.optString("referredBy").takeIf { it.isNotBlank() && it != "null" }
        )
    }

    suspend fun registerUserWithResult(
        userId: String,
        username: String,
        phone: String,
        email: String,
        balanceRupees: Double = 100.0,
        referredBy: String? = null,
        password: String? = null
    ): ServerAuthResult = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            if (userId.isNotBlank()) put("id", userId)
            put("name", username)
            put("phone", phone)
            put("email", email)
            put("balance", balanceRupees)
            if (!referredBy.isNullOrBlank()) put("referredBy", referredBy)
            if (!password.isNullOrBlank()) put("password", password)
        }
        val resp = postJsonWithRetry("/api/users/register", payload)
            ?: return@withContext ServerAuthResult(
                user = null,
                error = "Unable to reach server. Check your connection and try again.",
                isNetworkError = true
            )
        if (!resp.optBoolean("success", false)) {
            return@withContext ServerAuthResult(
                user = null,
                error = resp.optString("error").takeIf { it.isNotBlank() } ?: "Registration failed on server.",
                isNetworkError = false
            )
        }
        val uObj = resp.optJSONObject("user")
            ?: return@withContext ServerAuthResult(
                user = null,
                error = "Invalid registration response from server.",
                isNetworkError = false
            )
        return@withContext ServerAuthResult(user = parseServerUser(uObj))
    }

    suspend fun registerUserOnServer(
        userId: String,
        username: String,
        phone: String,
        email: String,
        balanceRupees: Double = 100.0,
        referredBy: String? = null,
        password: String? = null
    ): Boolean = registerUserWithResult(
        userId = userId,
        username = username,
        phone = phone,
        email = email,
        balanceRupees = balanceRupees,
        referredBy = referredBy,
        password = password
    ).user != null

    suspend fun loginUserWithResult(
        identifier: String,
        password: String
    ): ServerAuthResult = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("identifier", identifier)
            put("password", password)
        }
        val resp = postJsonWithRetry("/api/users/login", payload)
            ?: return@withContext ServerAuthResult(
                user = null,
                error = "Unable to reach server. Check connection.",
                isNetworkError = true
            )
        if (!resp.optBoolean("success", false)) {
            return@withContext ServerAuthResult(
                user = null,
                error = resp.optString("error").takeIf { it.isNotBlank() } ?: "Invalid credentials",
                isNetworkError = false
            )
        }
        val uObj = resp.optJSONObject("user")
            ?: return@withContext ServerAuthResult(
                user = null,
                error = "Invalid server response",
                isNetworkError = false
            )
        return@withContext ServerAuthResult(user = parseServerUser(uObj))
    }

    suspend fun loginUserOnServer(
        identifier: String,
        password: String
    ): Pair<ServerUserState?, String?> {
        val res = loginUserWithResult(identifier, password)
        return res.user to res.error
    }

    suspend fun placeBetOnServer(
        serverUserId: String,
        marketCode: String,
        amountRupees: Double,
        betType: String,
        target: String
    ): Pair<Boolean, String?> = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("userId", serverUserId)
            put("market", marketCode.uppercase())
            put("amount", amountRupees)
            put("type", betType.uppercase())
            put("target", target.uppercase())
        }
        val resp = postJsonWithStatus("/api/bets/place", payload)
        return@withContext if (resp != null && resp.optBoolean("success", false)) {
            true to resp.optJSONObject("bet")?.optString("id")
        } else {
            false to resp?.optString("error")
        }
    }

    suspend fun cancelBetOnServer(
        serverUserId: String,
        betId: String?,
        marketCode: String,
        period: String? = null
    ): Boolean = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("userId", serverUserId)
            if (!betId.isNullOrBlank()) put("betId", betId)
            put("market", marketCode.uppercase())
            if (!period.isNullOrBlank()) put("period", period)
        }
        val resp = postJson("/api/bets/cancel", payload)
        return@withContext resp?.optBoolean("success", false) == true
    }

    suspend fun submitDepositOnServer(
        serverUserId: String,
        userName: String,
        amountRupees: Double,
        utr: String,
        method: String
    ): Pair<Boolean, String?> = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("userId", serverUserId)
            put("userName", userName)
            put("amount", amountRupees)
            put("utr", utr)
            put("method", method)
        }
        val resp = postJsonWithStatus("/api/deposits", payload)
        return@withContext if (resp != null && resp.optBoolean("success", false)) {
            true to resp.optJSONObject("deposit")?.optString("id")
        } else {
            false to resp?.optString("error")
        }
    }

    suspend fun submitWithdrawalOnServer(
        serverUserId: String,
        userName: String,
        amountRupees: Double,
        upiId: String,
        bankName: String,
        accNo: String,
        ifsc: String,
        bankingName: String
    ): Pair<Boolean, String?> = withContext(Dispatchers.IO) {
        val payload = JSONObject().apply {
            put("userId", serverUserId)
            put("userName", userName)
            put("amount", amountRupees)
            put("upiId", upiId)
            put("bankName", bankName)
            put("accNo", accNo)
            put("ifsc", ifsc)
            put("bankingName", bankingName)
        }
        val resp = postJsonWithStatus("/api/withdrawals", payload)
        return@withContext if (resp != null && resp.optBoolean("success", false)) {
            true to resp.optString("withdrawalId")
        } else {
            false to resp?.optString("error")
        }
    }

    private fun postJson(path: String, payload: JSONObject): JSONObject? {
        val resp = postJsonWithStatus(path, payload)
        return if (resp != null && resp.optBoolean("success", true)) resp else null
    }

    private suspend fun postJsonWithRetry(path: String, payload: JSONObject): JSONObject? {
        val first = postJsonWithStatus(path, payload)
        if (first != null) return first
        if (!hasCustomOverride) {
            resolveReachableBackendUrl()
            return postJsonWithStatus(path, payload)
        }
        return null
    }

    private fun postJsonWithStatus(path: String, payload: JSONObject): JSONObject? {
        val baseUrl = _activeBackendUrl.value
        return try {
            val req = Request.Builder()
                .url("$baseUrl$path")
                .post(payload.toString().toRequestBody(jsonMediaType))
                .build()
            httpClient.newCall(req).execute().use { resp ->
                val txt = resp.body?.string()?.trim().orEmpty()
                if (txt.isEmpty()) {
                    if (resp.isSuccessful) JSONObject().put("success", true)
                    else JSONObject().put("success", false).put("error", "Server returned HTTP ${resp.code}")
                } else {
                    try {
                        JSONObject(txt)
                    } catch (_: Exception) {
                        JSONObject().put("success", false).put("error", "Server returned HTTP ${resp.code}")
                    }
                }
            }
        } catch (_: Exception) {
            null
        }
    }

    fun rupeesToCents(rupees: Double): Long = (rupees * 100.0).roundToLong()
}
