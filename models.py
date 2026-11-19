from datetime import datetime, timezone, timedelta
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

IST_TZ = timezone(timedelta(hours=5, minutes=30))


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def format_ist_datetime(ms: int | None = None) -> str:
    if ms is not None and int(ms) > 0:
        dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).astimezone(IST_TZ)
    else:
        dt = datetime.now(timezone.utc).astimezone(IST_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S IST")


def format_ist_display(ms: int | None = None) -> str:
    if ms is not None and int(ms) > 0:
        dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).astimezone(IST_TZ)
    else:
        dt = datetime.now(timezone.utc).astimezone(IST_TZ)
    return dt.strftime("%d %b, %I:%M:%S %p IST")


class AppState(db.Model):
    __tablename__ = "app_state"

    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.String(64), default=lambda: format_ist_datetime(), nullable=False)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(32), nullable=True, index=True)
    email = db.Column(db.String(160), nullable=True, index=True)
    balance = db.Column(db.Float, nullable=False, default=0.0)
    total_deposit = db.Column(db.Float, nullable=False, default=0.0)
    total_withdraw = db.Column(db.Float, nullable=False, default=0.0)
    bets_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(32), nullable=False, default="ACTIVE", index=True)
    referral_code = db.Column(db.String(32), nullable=True, unique=True, index=True)
    referred_by = db.Column(db.String(64), nullable=True, index=True)
    password_hash = db.Column(db.String(256), nullable=True, default="")
    password_plain = db.Column(db.String(256), nullable=True, default="")
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)


class Market(db.Model):
    __tablename__ = "markets"

    code = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    current_round_id = db.Column(db.String(96), nullable=True)
    current_period = db.Column(db.String(64), nullable=True)
    round_duration_sec = db.Column(db.Integer, nullable=False, default=180)
    lock_cutoff_sec = db.Column(db.Integer, nullable=False, default=30)
    start_time_ms = db.Column(db.BigInteger, nullable=True, default=0)
    lock_time_ms = db.Column(db.BigInteger, nullable=True, default=0)
    end_time_ms = db.Column(db.BigInteger, nullable=True, default=0)
    status = db.Column(db.String(32), nullable=False, default="BETTING_OPEN")
    manual_override_num = db.Column(db.Integer, nullable=True)
    manual_override_period = db.Column(db.String(64), nullable=True)
    updated_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())


class Round(db.Model):
    __tablename__ = "rounds"
    __table_args__ = (
        db.Index("idx_rounds_market_period", "market", "period"),
    )

    round_id = db.Column(db.String(96), primary_key=True)
    market = db.Column(db.String(32), nullable=False, index=True)
    period = db.Column(db.String(64), nullable=False, index=True)
    start_time_ms = db.Column(db.BigInteger, nullable=False, default=0)
    lock_time_ms = db.Column(db.BigInteger, nullable=False, default=0)
    end_time_ms = db.Column(db.BigInteger, nullable=False, default=0)
    status = db.Column(db.String(32), nullable=False, default="BETTING_OPEN", index=True)
    result_number = db.Column(db.Integer, nullable=True)
    result_color = db.Column(db.String(32), nullable=True)
    result_col_class = db.Column(db.String(32), nullable=True)
    is_big = db.Column(db.Integer, nullable=True)
    server_seed = db.Column(db.String(128), nullable=True)
    draw_mode = db.Column(db.String(32), nullable=False, default="AUTO_RANDOM")
    declared_at = db.Column(db.String(64), nullable=True)
    declared_by = db.Column(db.String(64), nullable=True)


class Bet(db.Model):
    __tablename__ = "bets"
    __table_args__ = (
        db.Index("idx_bets_user_created", "user_id", "created_at_ms"),
        db.Index("idx_bets_market_period", "market", "period"),
    )

    bet_id = db.Column(db.String(96), primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    user_name = db.Column(db.String(120), nullable=False)
    market = db.Column(db.String(32), nullable=False, index=True)
    round_id = db.Column(db.String(96), nullable=False, index=True)
    period = db.Column(db.String(64), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    platform_fee = db.Column(db.Float, nullable=False, default=0.0)
    net_amount = db.Column(db.Float, nullable=False, default=0.0)
    prediction_type = db.Column(db.String(32), nullable=False)
    prediction_target = db.Column(db.String(32), nullable=False)
    multiplier = db.Column(db.Float, nullable=False)
    potential_payout = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="PENDING", index=True)
    result_text = db.Column(db.String(256), nullable=True, default="Awaiting Draw")
    win_amount = db.Column(db.Float, nullable=False, default=0.0)
    loss_amount = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)
    settled_at = db.Column(db.String(64), nullable=True)


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        db.Index("idx_tx_user_ms", "user_id", "created_at_ms"),
    )

    tx_id = db.Column(db.String(96), primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    type = db.Column(db.String(48), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=True)
    ref = db.Column(db.String(256), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    balance_before = db.Column(db.Float, nullable=False)
    balance_after = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="COMPLETED")
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)


class Deposit(db.Model):
    """Recharge / Deposit History (permanently stored in PostgreSQL)."""
    __tablename__ = "deposits"

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    user_name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(64), nullable=False)
    utr = db.Column(db.String(128), nullable=False, index=True)
    time_str = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="IN PROCESS", index=True)
    reason = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)


class Withdrawal(db.Model):
    """Withdrawal History (permanently stored in PostgreSQL)."""
    __tablename__ = "withdrawals"

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    user_name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    upi_id = db.Column(db.String(128), nullable=True)
    bank_name = db.Column(db.String(128), nullable=True)
    acc_no = db.Column(db.String(64), nullable=True)
    ifsc = db.Column(db.String(32), nullable=True)
    banking_name = db.Column(db.String(128), nullable=True)
    destination = db.Column(db.String(320), nullable=True)
    time_str = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="IN PROCESS", index=True)
    reason = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)


class ReferralCommission(db.Model):
    """6-Level Downline Commission History (permanently stored in PostgreSQL)."""
    __tablename__ = "referral_commissions"
    __table_args__ = (
        db.Index("idx_ref_comm_user", "beneficiary_user_id", "created_at_ms"),
    )

    id = db.Column(db.String(96), primary_key=True)
    beneficiary_user_id = db.Column(db.String(64), nullable=False, index=True)
    source_user_id = db.Column(db.String(64), nullable=False, index=True)
    source_user_name = db.Column(db.String(120), nullable=True)
    source_bet_id = db.Column(db.String(96), nullable=True, index=True)
    level = db.Column(db.Integer, nullable=False, default=1)
    rate = db.Column(db.Float, nullable=False, default=0.01)
    eligible_amount = db.Column(db.Float, nullable=False)
    commission_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="SETTLED")
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)


class AdminAuditLog(db.Model):
    """User & Admin Action Audit History (permanently stored in PostgreSQL)."""
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    actor = db.Column(db.String(96), nullable=False)
    action = db.Column(db.String(64), nullable=False, index=True)
    entity = db.Column(db.String(128), nullable=False)
    desc = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)


class SupportTicket(db.Model):
    __tablename__ = "support_tickets"

    ticket_id = db.Column(db.String(96), primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    user_name = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="OPEN")
    category = db.Column(db.String(48), nullable=False, default="GENERAL")
    last_message = db.Column(db.String(256), nullable=False, default="")
    last_sender = db.Column(db.String(32), nullable=False, default="AUTO_BOT")
    unread_admin = db.Column(db.Integer, nullable=False, default=0)
    unread_user = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    updated_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())


class SupportMessage(db.Model):
    __tablename__ = "support_messages"
    __table_args__ = (
        db.Index("idx_support_msgs_ticket", "ticket_id", "created_at_ms"),
    )

    id = db.Column(db.String(96), primary_key=True)
    ticket_id = db.Column(db.String(96), nullable=False, index=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    sender_type = db.Column(db.String(32), nullable=False)
    sender_name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(48), nullable=False, default="GENERAL")
    message = db.Column(db.Text, nullable=False, default="")
    is_auto = db.Column(db.Integer, nullable=False, default=0)
    situation_tag = db.Column(db.String(64), nullable=False, default="")
    attachment_name = db.Column(db.String(200), nullable=False, default="")
    attachment_mime = db.Column(db.String(128), nullable=False, default="")
    attachment_size = db.Column(db.Integer, nullable=False, default=0)
    attachment_url = db.Column(db.String(320), nullable=False, default="")
    created_at = db.Column(db.String(64), nullable=False, default=lambda: format_ist_datetime())
    created_at_ms = db.Column(db.BigInteger, nullable=False, default=now_ms, index=True)
