package com.example.domain

import android.util.Log
import com.example.data.local.AppDatabase
import com.example.data.model.*
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID

sealed class GameSocketEvent {
    data class RoundCreated(val round: GameRoundEntity) : GameSocketEvent()
    data class BettingOpen(val round: GameRoundEntity, val secondsRemaining: Int) : GameSocketEvent()
    data class Countdown(val secondsRemaining: Int, val gameId: String = "") : GameSocketEvent()
    data class BettingClosed(val roundId: String, val gameId: String = "") : GameSocketEvent()
    data class ResultRevealed(val round: GameRoundEntity, val result: RoundResult) : GameSocketEvent()
    data class SettlementCompleted(val roundId: String, val totalPayoutCents: Long, val winningBetsCount: Int) : GameSocketEvent()
}

class MarketEngineState(
    val market: MarketInfo,
    val currentRound: MutableStateFlow<GameRoundEntity?> = MutableStateFlow(null),
    val secondsRemaining: MutableStateFlow<Int> = MutableStateFlow(180),
    val isBettingOpen: MutableStateFlow<Boolean> = MutableStateFlow(false),
    val latestResult: MutableStateFlow<RoundResult?> = MutableStateFlow(null)
)

object GlobalRoundClock {
    const val ROUND_DURATION_SEC = 180
    const val BETTING_CUTOFF_SEC = 30 // Last 30s bets are closed

    data class ClockState(
        val dateStr: String,
        val roundIndex: Long,
        val periodNumber: Long, // e.g. 20261104221
        val secondsPassed: Int,
        val secondsLeft: Int,
        val isBettingOpen: Boolean
    )

    fun getSyncedState(nowMs: Long = System.currentTimeMillis()): ClockState {
        val nowCal = java.util.Calendar.getInstance().apply { timeInMillis = nowMs }
        val ref11Cal = java.util.Calendar.getInstance().apply {
            timeInMillis = nowMs
            set(java.util.Calendar.HOUR_OF_DAY, 11)
            set(java.util.Calendar.MINUTE, 0)
            set(java.util.Calendar.SECOND, 0)
            set(java.util.Calendar.MILLISECOND, 0)
        }

        // Daily 11:00 AM reference point
        // If current time is before 11:00 AM today, reference 11:00 AM of yesterday
        val refCal = if (nowCal.before(ref11Cal)) {
            java.util.Calendar.getInstance().apply {
                timeInMillis = ref11Cal.timeInMillis
                add(java.util.Calendar.DAY_OF_YEAR, -1)
            }
        } else {
            ref11Cal
        }

        val diffSeconds = ((nowMs - refCal.timeInMillis) / 1000L).coerceAtLeast(0L)
        val roundIndex = diffSeconds / ROUND_DURATION_SEC
        val periodIndex = 221L + roundIndex

        val dateStr = java.text.SimpleDateFormat("yyyyMMdd", java.util.Locale.ENGLISH).format(refCal.time)
        val fullPeriodNumber = "$dateStr$periodIndex".toLong()

        val secondsPassed = (diffSeconds % ROUND_DURATION_SEC).toInt()
        val secondsLeft = (ROUND_DURATION_SEC - secondsPassed).coerceIn(1, ROUND_DURATION_SEC)
        val isBettingOpen = secondsLeft > BETTING_CUTOFF_SEC

        return ClockState(
            dateStr = dateStr,
            roundIndex = roundIndex,
            periodNumber = fullPeriodNumber,
            secondsPassed = secondsPassed,
            secondsLeft = secondsLeft,
            isBettingOpen = isBettingOpen
        )
    }
}

class GameEngineService(
    private val database: AppDatabase,
    private val walletService: WalletService,
    private val referralCommissionService: ReferralCommissionService
) {
    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

    // Multi-market engine states for the 4 separate markets: MIAMI, VEGAS, PARIS, DUBAI
    private val _marketStates = GameMarkets.ALL.associate { market ->
        market.id to MarketEngineState(market)
    }.toMutableMap().apply {
        // Also add legacy/fallback mapping
        put("color_prediction", MarketEngineState(GameMarkets.MIAMI))
    }

    // Default / legacy fallback flows (mirrors MIAMI)
    val currentRound: StateFlow<GameRoundEntity?>
        get() = _marketStates["market_miami"]?.currentRound?.asStateFlow()
            ?: MutableStateFlow(null).asStateFlow()

    val secondsRemaining: StateFlow<Int>
        get() = _marketStates["market_miami"]?.secondsRemaining?.asStateFlow()
            ?: MutableStateFlow(180).asStateFlow()

    val isBettingOpen: StateFlow<Boolean>
        get() = _marketStates["market_miami"]?.isBettingOpen?.asStateFlow()
            ?: MutableStateFlow(false).asStateFlow()

    val latestResult: StateFlow<RoundResult?>
        get() = _marketStates["market_miami"]?.latestResult?.asStateFlow()
            ?: MutableStateFlow(null).asStateFlow()

    // Non-blocking SharedFlow with DROP_OLDEST to prevent coroutine suspension when buffer fills
    private val _socketEvents = MutableSharedFlow<GameSocketEvent>(
        replay = 0,
        extraBufferCapacity = 64,
        onBufferOverflow = BufferOverflow.DROP_OLDEST
    )
    val socketEvents = _socketEvents.asSharedFlow()

    private var engineJobs = mutableMapOf<String, Job>()

    fun getMarketState(marketId: String): MarketEngineState {
        return _marketStates[marketId] ?: _marketStates["market_miami"]!!
    }

    fun getCurrentRoundFlow(marketId: String): StateFlow<GameRoundEntity?> {
        return getMarketState(marketId).currentRound.asStateFlow()
    }

    fun getSecondsRemainingFlow(marketId: String): StateFlow<Int> {
        return getMarketState(marketId).secondsRemaining.asStateFlow()
    }

    fun getIsBettingOpenFlow(marketId: String): StateFlow<Boolean> {
        return getMarketState(marketId).isBettingOpen.asStateFlow()
    }

    fun getLatestResultFlow(marketId: String): StateFlow<RoundResult?> {
        return getMarketState(marketId).latestResult.asStateFlow()
    }

    fun startEngine(tenantId: String = "tenant_apex_global", gameId: String? = null) {
        // Start engine for all 4 markets synchronously (MIAMI, VEGAS, PARIS, DUBAI)
        // All markets run on the identical period number starting at 221 daily at 11:00 AM
        val targets = if (gameId != null && gameId != "color_prediction") {
            listOf(GameMarkets.getById(gameId))
        } else {
            GameMarkets.ALL
        }

        targets.forEach { market ->
            if (engineJobs[market.id]?.isActive == true) return@forEach

            val state = getMarketState(market.id)
            val job = scope.launch {
                try {
                    recoverStaleRounds(tenantId, market.id, state)
                } catch (e: Exception) {
                    Log.e("GameEngine", "Error recovering stale rounds for ${market.id}", e)
                }

                while (isActive) {
                    try {
                        runMarketRoundCycle(tenantId, market, state)
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        Log.e("GameEngine", "Error in runMarketRoundCycle for ${market.id}", e)
                        delay(2000)
                    }
                }
            }
            engineJobs[market.id] = job
        }
    }

    val isEngineRunning: Boolean get() = engineJobs.values.any { it.isActive }

    fun stopEngine() {
        engineJobs.values.forEach { it.cancel() }
        engineJobs.clear()
    }

    private suspend fun recoverStaleRounds(tenantId: String, gameId: String, state: MarketEngineState) {
        val roundDao = database.gameRoundDao()
        val currentClock = GlobalRoundClock.getSyncedState()

        // Clean up any stale dummy rounds with numbers ahead of the current live clock
        try {
            roundDao.deleteFutureRounds(tenantId, currentClock.periodNumber)
        } catch (e: Exception) {
            Log.e("GameEngine", "Error cleaning future rounds for $gameId", e)
        }

        // Initialize state.latestResult from the most recent completed round in database
        val lastCompleted = roundDao.getLatestCompletedRound(tenantId, gameId)
        if (lastCompleted != null && lastCompleted.resultNumber != null) {
            val serverSeed = lastCompleted.serverSeed ?: ProvablyFairEngine.generateServerSeed()
            state.latestResult.value = ProvablyFairEngine.calculateResult(serverSeed, lastCompleted.clientSeed, lastCompleted.nonce)
        }

        val latest = roundDao.getLatestRound(tenantId, gameId)
        if (latest != null && latest.status != RoundStatus.COMPLETED.name && latest.roundNumber < currentClock.periodNumber) {
            val serverSeed = latest.serverSeed ?: ProvablyFairEngine.generateServerSeed()
            val result = ProvablyFairEngine.calculateResult(serverSeed, latest.clientSeed, latest.nonce)
            val config = database.gameConfigDao().getConfig(tenantId, gameId)
                ?: GameConfigEntity(id = "cfg_${tenantId}_$gameId", tenantId = tenantId, gameId = gameId)
            val updated = latest.copy(
                status = RoundStatus.RESULT_GENERATED.name,
                resultNumber = result.number,
                resultColor = result.color.name,
                serverSeed = serverSeed
            )
            roundDao.updateRound(updated)
            settleRound(updated, result, config, state)
            state.latestResult.value = result
        }
    }

    private suspend fun runMarketRoundCycle(
        tenantId: String,
        market: MarketInfo,
        state: MarketEngineState
    ) {
        val roundDao = database.gameRoundDao()
        val configDao = database.gameConfigDao()
        var config = configDao.getConfig(tenantId, market.id) ?: GameConfigEntity(
            id = "cfg_${tenantId}_${market.id}",
            tenantId = tenantId,
            gameId = market.id,
            roundDurationSec = 180,
            bettingCutoffSec = 30
        )
        if (config.roundDurationSec != 180 || config.bettingCutoffSec != 30) {
            config = config.copy(roundDurationSec = 180, bettingCutoffSec = 30)
            configDao.insertConfig(config)
        }

        // 1. Unified Global Round Clock State (Daily 11:00 AM period #221 start, identical across all 4 markets)
        val initialClock = GlobalRoundClock.getSyncedState()
        val roundNumber = initialClock.periodNumber
        val roundId = "rnd_${tenantId}_${market.code}_$roundNumber"

        var currentRound = roundDao.getRoundById(roundId)

        // If this round was already settled, wait out the remaining seconds of this period
        if (currentRound != null && currentRound.status == RoundStatus.COMPLETED.name) {
            state.currentRound.value = currentRound
            state.secondsRemaining.value = initialClock.secondsLeft
            state.isBettingOpen.value = false
            delay(initialClock.secondsLeft.coerceAtLeast(1) * 1000L)
            return
        }

        // Provably Fair Seeds
        val serverSeed = ProvablyFairEngine.generateServerSeed()
        val serverSeedHash = ProvablyFairEngine.hashSha256(serverSeed)
        val nonce = roundNumber
        val clientSeed = "apex_${market.code.lowercase()}_seed"

        val duration = 180
        val cutoff = 30
        val now = System.currentTimeMillis()
        val startTime = now - (initialClock.secondsPassed * 1000L)
        val bettingCloseTime = startTime + ((duration - cutoff) * 1000L)
        val resultTime = startTime + (duration * 1000L)

        val activeRound = currentRound ?: GameRoundEntity(
            roundId = roundId,
            gameId = market.id,
            tenantId = tenantId,
            roundNumber = roundNumber,
            startTime = startTime,
            bettingCloseTime = bettingCloseTime,
            resultTime = resultTime,
            status = if (initialClock.isBettingOpen) RoundStatus.BETTING_OPEN.name else RoundStatus.BETTING_CLOSED.name,
            serverSeedHash = serverSeedHash,
            serverSeed = null,
            nonce = nonce,
            clientSeed = clientSeed
        ).also { roundDao.insertRound(it) }

        var currentRoundState: GameRoundEntity = activeRound

        state.currentRound.value = currentRoundState
        state.isBettingOpen.value = initialClock.isBettingOpen
        state.secondsRemaining.value = initialClock.secondsLeft
        _socketEvents.tryEmit(GameSocketEvent.RoundCreated(currentRoundState))
        if (initialClock.isBettingOpen) {
            _socketEvents.tryEmit(GameSocketEvent.BettingOpen(currentRoundState, initialClock.secondsLeft))
        }

        // 2. Synchronous Clock Countdown Phase across all markets
        while (currentCoroutineContext().isActive) {
            val sync = GlobalRoundClock.getSyncedState()
            if (sync.periodNumber != roundNumber) {
                // Round duration expired, transition to settlement
                break
            }

            state.secondsRemaining.value = sync.secondsLeft
            _socketEvents.tryEmit(GameSocketEvent.Countdown(sync.secondsLeft, market.id))

            if (sync.isBettingOpen != state.isBettingOpen.value) {
                state.isBettingOpen.value = sync.isBettingOpen
                if (!sync.isBettingOpen) {
                    val locked = currentRoundState.copy(status = RoundStatus.BETTING_CLOSED.name)
                    roundDao.updateRound(locked)
                    currentRoundState = locked
                    state.currentRound.value = locked
                    _socketEvents.tryEmit(GameSocketEvent.BettingClosed(roundId, market.id))
                }
            }

            if (sync.secondsLeft <= 0) {
                break
            }
            delay(1000)
        }

        state.secondsRemaining.value = 0
        state.isBettingOpen.value = false

        // 3. Result Generation: Deterministic Provably Fair HMAC-SHA256
        val actualServerSeed = currentRoundState.serverSeed ?: serverSeed
        val roundResult = ProvablyFairEngine.calculateResult(actualServerSeed, clientSeed, nonce)
        state.latestResult.value = roundResult

        val revealedRound = currentRoundState.copy(
            status = RoundStatus.RESULT_GENERATED.name,
            resultNumber = roundResult.number,
            resultColor = roundResult.color.name,
            serverSeed = actualServerSeed
        )
        roundDao.updateRound(revealedRound)
        state.currentRound.value = revealedRound
        _socketEvents.tryEmit(GameSocketEvent.ResultRevealed(revealedRound, roundResult))

        // Visual reveal pause (2 seconds)
        delay(2000)

        // 4. Settlement phase: evaluate winning bets, payouts & referral commissions
        settleRound(revealedRound, roundResult, config, state)

        // Brief delay before launching next synchronized period
        delay(1000)
    }

    private suspend fun settleRound(
        round: GameRoundEntity,
        result: RoundResult,
        config: GameConfigEntity,
        state: MarketEngineState
    ) {
        val betDao = database.betDao()
        val roundDao = database.gameRoundDao()

        val bets = betDao.getBetsForRound(round.roundId)
        var totalPayout = 0L
        var winningBetsCount = 0

        for (bet in bets) {
            if (bet.status.uppercase() in listOf("REFUNDED", "CANCELLED")) {
                continue
            }
            try {
                val (isWon, multiplier) = evaluateBet(bet, result, config)
                val payoutCents = if (isWon) {
                    (bet.amount * multiplier).toLong()
                } else 0L

                if (isWon && payoutCents > 0L) {
                    winningBetsCount++
                    totalPayout += payoutCents

                    // Credit win to wallet
                    val winIdempotency = "win_${bet.id}"
                    walletService.creditForWin(
                        tenantId = bet.tenantId,
                        userId = bet.userId,
                        amountCents = payoutCents,
                        roundId = round.roundId,
                        idempotencyKey = winIdempotency
                    )

                    betDao.updateBet(
                        bet.copy(
                            status = BetStatus.WON.name,
                            actualPayout = payoutCents,
                            settledAt = System.currentTimeMillis()
                        )
                    )
                } else {
                    betDao.updateBet(
                        bet.copy(
                            status = BetStatus.LOST.name,
                            actualPayout = 0L,
                            settledAt = System.currentTimeMillis()
                        )
                    )
                }

                // Distribute 6-level referral commission on eligible wager
                referralCommissionService.distributeReferralCommission(
                    tenantId = bet.tenantId,
                    userId = bet.userId,
                    eligibleAmountCents = bet.amount,
                    sourceTransactionId = bet.transactionId
                )
            } catch (e: Exception) {
                Log.e("GameEngine", "Error settling bet ${bet.id}", e)
            }
        }

        val completedRound = round.copy(
            status = RoundStatus.COMPLETED.name,
            settledAt = System.currentTimeMillis()
        )
        roundDao.updateRound(completedRound)
        state.currentRound.value = completedRound
        _socketEvents.tryEmit(GameSocketEvent.SettlementCompleted(round.roundId, totalPayout, winningBetsCount))
    }

    fun evaluateBet(bet: BetEntity, result: RoundResult, config: GameConfigEntity): Pair<Boolean, Double> {
        val number = result.number
        val color = result.color

        return when (bet.betType) {
            BetType.NUMBER.name -> {
                if (bet.selection == number.toString()) {
                    Pair(true, config.numberMultiplier)
                } else {
                    Pair(false, 0.0)
                }
            }
            BetType.BIG_SMALL.name -> {
                when (bet.selection.uppercase()) {
                    "BIG" -> {
                        // 5, 6, 7, 8, 9 is Big -> 2x payout
                        if (number in 5..9) {
                            Pair(true, 2.0)
                        } else {
                            Pair(false, 0.0)
                        }
                    }
                    "SMALL" -> {
                        // 0, 1, 2, 3, 4 is Small -> 2x payout
                        if (number in 0..4) {
                            Pair(true, 2.0)
                        } else {
                            Pair(false, 0.0)
                        }
                    }
                    else -> Pair(false, 0.0)
                }
            }
            else -> {
                // Color bet
                when (bet.selection.uppercase()) {
                    "RED" -> {
                        when (color) {
                            GameColor.RED -> Pair(true, config.redMultiplier)
                            GameColor.RED_VIOLET -> Pair(true, 1.5) // Red + Violet combo (half payout)
                            else -> Pair(false, 0.0)
                        }
                    }
                    "GREEN" -> {
                        when (color) {
                            GameColor.GREEN -> Pair(true, config.greenMultiplier)
                            GameColor.GREEN_VIOLET -> Pair(true, 1.5) // Green + Violet combo (half payout)
                            else -> Pair(false, 0.0)
                        }
                    }
                    "VIOLET" -> {
                        when (color) {
                            GameColor.VIOLET, GameColor.RED_VIOLET, GameColor.GREEN_VIOLET -> Pair(true, config.violetMultiplier)
                            else -> Pair(false, 0.0)
                        }
                    }
                    else -> Pair(false, 0.0)
                }
            }
        }
    }
}
