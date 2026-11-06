package com.example.data.model

import java.math.BigDecimal
import java.math.RoundingMode

enum class UserRole {
    SUPER_ADMIN,
    TENANT_ADMIN,
    ADMIN,
    MANAGER,
    SUPPORT,
    FINANCE,
    USER
}

enum class UserStatus {
    ACTIVE,
    SUSPENDED,
    LOCKED,
    PENDING_VERIFICATION
}

enum class WalletStatus {
    ACTIVE,
    FROZEN,
    SUSPENDED
}

enum class LedgerEntryType {
    DEPOSIT,
    WITHDRAWAL,
    BET,
    WIN,
    REFUND,
    BONUS,
    REFERRAL_COMMISSION,
    ADMIN_ADJUSTMENT,
    REVERSAL,
    FEE
}

enum class LedgerDirection {
    CREDIT,
    DEBIT
}

enum class RoundStatus {
    CREATED,
    BETTING_OPEN,
    BETTING_CLOSED,
    RESULT_GENERATED,
    SETTLEMENT,
    COMPLETED
}

enum class BetType {
    COLOR,
    NUMBER,
    BIG_SMALL
}

enum class GameColor {
    RED,
    GREEN,
    VIOLET,
    RED_VIOLET,
    GREEN_VIOLET
}

enum class BetStatus {
    PENDING,
    ACCEPTED,
    WON,
    LOST,
    REFUNDED,
    CANCELLED
}

enum class CommissionStatus {
    PENDING,
    SETTLED,
    REVERSED
}

enum class WithdrawalStatus {
    REQUESTED,
    UNDER_REVIEW,
    APPROVED,
    PROCESSING,
    COMPLETED,
    FAILED,
    REFUNDED
}

enum class DepositStatus {
    PENDING,
    SUCCESS,
    FAILED,
    EXPIRED,
    CANCELLED
}

object MoneyUtils {
    fun formatCents(cents: Long, currency: String = "₹"): String {
        val bd = BigDecimal(cents).divide(BigDecimal(100), 2, RoundingMode.HALF_UP)
        return "$currency%,.2f".format(bd)
    }

    fun toCents(rupees: Double): Long {
        return BigDecimal(rupees).multiply(BigDecimal(100)).setScale(0, RoundingMode.HALF_UP).toLong()
    }
}
