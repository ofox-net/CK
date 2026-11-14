import http.server
import socketserver
import json
import os
import sqlite3
import threading
import time
import urllib.parse
import hashlib
import random
import math
import csv
import io
import queue
from datetime import datetime, timezone, timedelta

PORT = 3000
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
DB_FILE = os.path.join(DIRECTORY, "colour_king.db")
RETENTION_DAYS = 90

db_lock = threading.Lock()
sse_lock = threading.Lock()
sse_subscribers = []

# Supported Markets
MARKET_KEYS = ["MIAMI", "VEGAS", "PARIS", "DUBAI"]
ROUND_DURATION_SEC = 180  # 3 minutes
LOCK_CUTOFF_SEC = 30      # Last 30 seconds locked

DEFAULT_PLATFORM_SETTINGS = {
    "maintenanceMode": False,
    "announcementBanner": "",
    "minBet": 10.0,
    "maxBet": 100000.0
}

DEFAULT_BANK_CONFIG = {
    "bankName": "State Bank of India (SBI)",
    "holder": "Colour King Gaming Enterprise Ltd",
    "accNo": "40928172901",
    "ifsc": "SBIN0001824",
    "branch": "Corporate Financial Center, BKC Mumbai",
    "upiId": "colourking@icici",
    "upiName": "Colour King Official Pay",
    "minDeposit": 100,
    "maxDeposit": 100000,
    "instructions": "1. Scan QR code or pay to the UPI ID above.\n2. Enter the 12-digit UTR reference number in the app.\n3. Balance will be approved and credited within 2 minutes."
}

DEFAULT_USERS = [
    { "id": "USR-1001", "name": "Rahul_Player", "phone": "+91 98765 43210", "email": "rahul@gmail.com", "balance": 50200.00, "totalDeposit": 75000.00, "totalWithdraw": 28000.00, "betsCount": 142, "status": "ACTIVE" },
    { "id": "USR-1002", "name": "Aman_Trader", "phone": "+91 98221 11223", "email": "aman.trade@yahoo.com", "balance": 14500.00, "totalDeposit": 25000.00, "totalWithdraw": 11000.00, "betsCount": 68, "status": "ACTIVE" },
    { "id": "USR-1003", "name": "Priya_VIP", "phone": "+91 97110 99887", "email": "priya_queen@outlook.com", "balance": 125000.00, "totalDeposit": 200000.00, "totalWithdraw": 95000.00, "betsCount": 310, "status": "ACTIVE" },
    { "id": "USR-1004", "name": "Vikram_99", "phone": "+91 96554 33221", "email": "vikram99@gmail.com", "balance": 3200.00, "totalDeposit": 10000.00, "totalWithdraw": 6000.00, "betsCount": 45, "status": "ACTIVE" },
    { "id": "USR-1005", "name": "Suspicious_Bot1", "phone": "+91 91234 56789", "email": "bot_arb@mail.ru", "balance": 0.00, "totalDeposit": 5000.00, "totalWithdraw": 0.00, "betsCount": 8, "status": "BLOCKED" },
    { "id": "USR-1006", "name": "Karan_Pro", "phone": "+91 99887 76655", "email": "karan_pro@gmail.com", "balance": 38400.00, "totalDeposit": 60000.00, "totalWithdraw": 24000.00, "betsCount": 94, "status": "ACTIVE" }
]

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def get_state_version(conn):
    try:
        row = conn.execute("SELECT value FROM app_state WHERE key = 'state_version'").fetchone()
        return int(row[0]) if row and row[0] is not None else 1
    except Exception:
        return 1

def notify_sse_clients(payload):
    msg = dict(payload)
    with sse_lock:
        dead = []
        for q in sse_subscribers:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            if q in sse_subscribers:
                sse_subscribers.remove(q)

def bump_state_version(conn, event_type="state_update", detail=None):
    c = conn.cursor()
    curr = get_state_version(conn)
    new_ver = curr + 1
    c.execute(
        "INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES ('state_version', ?, CURRENT_TIMESTAMP)",
        (str(new_ver),)
    )
    event_payload = {
        "version": new_ver,
        "eventType": event_type,
        "detail": detail or {},
        "serverTimeMs": int(time.time() * 1000)
    }
    return new_ver, event_payload

def init_database():
    os.makedirs(DIRECTORY, exist_ok=True)
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")

        c.execute("""
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                balance REAL NOT NULL DEFAULT 50200.00,
                total_deposit REAL NOT NULL DEFAULT 0.00,
                total_withdraw REAL NOT NULL DEFAULT 0.00,
                bets_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                current_round_id TEXT,
                current_period TEXT,
                round_duration_sec INTEGER DEFAULT 180,
                lock_cutoff_sec INTEGER DEFAULT 30,
                start_time_ms INTEGER,
                lock_time_ms INTEGER,
                end_time_ms INTEGER,
                status TEXT DEFAULT 'BETTING_OPEN',
                manual_override_num INTEGER,
                manual_override_period TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS rounds (
                round_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                period TEXT NOT NULL,
                start_time_ms INTEGER NOT NULL,
                lock_time_ms INTEGER NOT NULL,
                end_time_ms INTEGER NOT NULL,
                status TEXT NOT NULL,
                result_number INTEGER,
                result_color TEXT,
                result_col_class TEXT,
                is_big INTEGER,
                server_seed TEXT,
                draw_mode TEXT DEFAULT 'AUTO_RANDOM',
                declared_at TIMESTAMP,
                declared_by TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_rounds_market_period ON rounds (market, period)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                bet_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                market TEXT NOT NULL,
                round_id TEXT NOT NULL,
                period TEXT NOT NULL,
                amount REAL NOT NULL,
                prediction_type TEXT NOT NULL,
                prediction_target TEXT NOT NULL,
                multiplier REAL NOT NULL,
                potential_payout REAL NOT NULL,
                status TEXT NOT NULL,
                result_text TEXT DEFAULT 'Awaiting Draw',
                win_amount REAL DEFAULT 0.00,
                loss_amount REAL DEFAULT 0.00,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_ms INTEGER NOT NULL,
                settled_at TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_bets_user_id ON bets (user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bets_user_created ON bets (user_id, created_at_ms DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bets_market_period ON bets (market, period)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bets_status ON bets (status)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                tx_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT,
                ref TEXT,
                amount REAL NOT NULL,
                balance_before REAL NOT NULL,
                balance_after REAL NOT NULL,
                status TEXT DEFAULT 'COMPLETED',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_ms INTEGER DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions (user_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                amount REAL NOT NULL,
                method TEXT NOT NULL,
                utr TEXT NOT NULL,
                time_str TEXT,
                status TEXT NOT NULL DEFAULT 'IN PROCESS',
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_ms INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                amount REAL NOT NULL,
                upi_id TEXT,
                bank_name TEXT,
                acc_no TEXT,
                ifsc TEXT,
                banking_name TEXT,
                destination TEXT,
                time_str TEXT,
                status TEXT NOT NULL DEFAULT 'IN PROCESS',
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_ms INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS referral_commissions (
                id TEXT PRIMARY KEY,
                beneficiary_user_id TEXT NOT NULL,
                source_user_id TEXT NOT NULL,
                source_user_name TEXT,
                source_bet_id TEXT,
                level INTEGER NOT NULL DEFAULT 1,
                rate REAL NOT NULL DEFAULT 0.01,
                eligible_amount REAL NOT NULL,
                commission_amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'SETTLED',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_ms INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ref_comm_user ON referral_commissions (beneficiary_user_id, created_at_ms DESC)")

        # Backward-compatible schema migrations for existing SQLite files
        for alter_sql in [
            "ALTER TABLE users ADD COLUMN referral_code TEXT",
            "ALTER TABLE users ADD COLUMN referred_by TEXT",
            "ALTER TABLE users ADD COLUMN password_hash TEXT",
            "ALTER TABLE transactions ADD COLUMN created_at_ms INTEGER DEFAULT 0",
            "ALTER TABLE deposits ADD COLUMN created_at_ms INTEGER DEFAULT 0",
            "ALTER TABLE withdrawals ADD COLUMN created_at_ms INTEGER DEFAULT 0",
        ]:
            try:
                c.execute(alter_sql)
            except Exception:
                pass
        try:
            default_pw_hash = hashlib.sha256(b"password123").hexdigest()
            c.execute("UPDATE users SET password_hash = ? WHERE password_hash IS NULL OR password_hash = ''", (default_pw_hash,))
            c.execute("UPDATE transactions SET created_at_ms = CAST(strftime('%s', created_at) AS INTEGER) * 1000 WHERE created_at_ms IS NULL OR created_at_ms = 0")
            c.execute("UPDATE deposits SET created_at_ms = CAST(strftime('%s', created_at) AS INTEGER) * 1000 WHERE created_at_ms IS NULL OR created_at_ms = 0")
            c.execute("UPDATE withdrawals SET created_at_ms = CAST(strftime('%s', created_at) AS INTEGER) * 1000 WHERE created_at_ms IS NULL OR created_at_ms = 0")
            c.execute("UPDATE users SET referral_code = 'RAHUL777' WHERE id = 'USR-1001' AND (referral_code IS NULL OR referral_code = '')")
        except Exception:
            pass
        c.execute("CREATE INDEX IF NOT EXISTS idx_tx_user_ms ON transactions (user_id, created_at_ms DESC)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                entity TEXT NOT NULL,
                desc TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed default users if empty
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            for u in DEFAULT_USERS:
                c.execute("""
                    INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (u["id"], u["name"], u.get("phone"), u.get("email"), u["balance"], u["totalDeposit"], u["totalWithdraw"], u["betsCount"], u["status"]))

        # Seed default deposits/withdrawals if empty
        c.execute("SELECT COUNT(*) FROM deposits")
        if c.fetchone()[0] == 0:
            now_seed_ms = int(time.time() * 1000)
            c.execute("""
                INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status, created_at_ms)
                VALUES ('DEP-88401', 'USR-1001', 'Rahul_Player', 5000.00, 'UPI (GooglePay)', '429188402911', 'Today, 11:24 AM', 'IN PROCESS', ?)
            """, (now_seed_ms,))
            c.execute("""
                INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status, created_at_ms)
                VALUES ('DEP-88402', 'USR-1002', 'Aman_Trader', 10000.00, 'IMPS SBI NetBanking', '902184716294', 'Today, 11:18 AM', 'IN PROCESS', ?)
            """, (now_seed_ms,))

        # Ensure app_state defaults exist in SQLite
        c.execute("SELECT value FROM app_state WHERE key = 'bank_config'")
        if not c.fetchone():
            c.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('bank_config', ?)", (json.dumps(DEFAULT_BANK_CONFIG),))

        c.execute("SELECT value FROM app_state WHERE key = 'platform_settings'")
        if not c.fetchone():
            c.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('platform_settings', ?)", (json.dumps(DEFAULT_PLATFORM_SETTINGS),))

        c.execute("SELECT value FROM app_state WHERE key = 'state_version'")
        if not c.fetchone():
            c.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('state_version', '1')")

        conn.commit()
        conn.close()

def get_ist_now():
    # IST is UTC + 5:30
    utc_now = datetime.now(timezone.utc)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return utc_now.astimezone(ist_tz)

def calculate_authoritative_round(market_code, now_ms=None):
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    # Convert to IST
    utc_now = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_now = utc_now.astimezone(ist_tz)

    ref_11am = ist_now.replace(hour=11, minute=0, second=0, microsecond=0)
    diff_sec = math.floor(ist_now.timestamp() - ref_11am.timestamp())
    ref_date = ref_11am
    if diff_sec < 0:
        ref_date = ref_11am - timedelta(days=1)
        diff_sec = math.floor(ist_now.timestamp() - ref_date.timestamp())

    date_str = ref_date.strftime("%Y%m%d")
    round_index = diff_sec // ROUND_DURATION_SEC
    period_num = 221 + round_index
    full_period_id = f"{date_str}{period_num}"

    round_start_sec = ref_date.timestamp() + (round_index * ROUND_DURATION_SEC)
    start_time_ms = int(round_start_sec * 1000)
    lock_time_ms = start_time_ms + ((ROUND_DURATION_SEC - LOCK_CUTOFF_SEC) * 1000)
    end_time_ms = start_time_ms + (ROUND_DURATION_SEC * 1000)

    remaining_sec = min(ROUND_DURATION_SEC, max(0, math.ceil((end_time_ms - now_ms) / 1000.0)))
    is_locked = (now_ms >= lock_time_ms) or (remaining_sec <= LOCK_CUTOFF_SEC)

    if remaining_sec <= 0:
        status = "WAITING_FOR_RESULT"
    elif is_locked:
        status = "BETTING_LOCKED"
    else:
        status = "BETTING_OPEN"

    round_id = f"RND_{market_code}_{full_period_id}"

    return {
        "market": market_code,
        "round_id": round_id,
        "period": full_period_id,
        "period_number": period_num,
        "start_time_ms": start_time_ms,
        "lock_time_ms": lock_time_ms,
        "end_time_ms": end_time_ms,
        "remaining_seconds": remaining_sec,
        "is_betting_locked": is_locked,
        "status": status
    }

def generate_provably_fair_outcome(market_code, period):
    seed_str = f"COLOUR_KING_AVALANCHE_2026_{market_code}_{period}_PROVABLY_FAIR"
    h = 0x811c9dc5
    for ch in seed_str:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    # Murmur3 finalizer avalanche
    h ^= (h >> 16)
    h = (h * 0x85ebca6b) & 0xFFFFFFFF
    h ^= (h >> 13)
    h = (h * 0xc2b2ae35) & 0xFFFFFFFF
    h ^= (h >> 16)
    number = h % 10

    is_big = (number >= 5)
    if number in [1, 3, 7, 9]:
        color = "green"
        col_class = "green"
    elif number in [2, 4, 6, 8]:
        color = "red"
        col_class = "red"
    else:
        color = "violet"
        col_class = "red-violet" if number == 0 else "green-violet"

    return {
        "number": number,
        "color": color,
        "col_class": col_class,
        "is_big": 1 if is_big else 0,
        "seed": seed_str
    }

def settle_round_in_db(conn, market_code, round_id, period, winning_number, draw_mode="AUTO_RANDOM", declared_by="SYSTEM"):
    c = conn.cursor()

    is_big = (winning_number >= 5)
    if winning_number in [1, 3, 7, 9]:
        color = "green"
        col_class = "green"
    elif winning_number in [2, 4, 6, 8]:
        color = "red"
        col_class = "red"
    else:
        color = "violet"
        col_class = "red-violet" if winning_number == 0 else "green-violet"

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Update or Insert round into rounds table
    c.execute("""
        INSERT INTO rounds (round_id, market, period, start_time_ms, lock_time_ms, end_time_ms, status, result_number, result_color, result_col_class, is_big, draw_mode, declared_at, declared_by)
        VALUES (?, ?, ?, ?, ?, ?, 'SETTLED', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(round_id) DO UPDATE SET
            status = 'SETTLED',
            result_number = excluded.result_number,
            result_color = excluded.result_color,
            result_col_class = excluded.result_col_class,
            is_big = excluded.is_big,
            draw_mode = excluded.draw_mode,
            declared_at = excluded.declared_at,
            declared_by = excluded.declared_by
    """, (round_id, market_code, period, 0, 0, 0, winning_number, color, col_class, 1 if is_big else 0, draw_mode, now_ts, declared_by))

    # 2. Fetch all unsettled bets for this market and period
    c.execute("""
        SELECT bet_id, user_id, user_name, amount, prediction_type, prediction_target, multiplier
        FROM bets
        WHERE market = ? AND period = ? AND status IN ('PENDING', 'LOCKED')
    """, (market_code, period))
    unsettled_bets = c.fetchall()

    for b in unsettled_bets:
        bet_id = b["bet_id"]
        uid = b["user_id"]
        amt = b["amount"]
        btype = b["prediction_type"]
        target = b["prediction_target"].upper()
        mult = b["multiplier"]

        won = False
        actual_mult = mult
        if btype == "BIG_SMALL":
            if target == "BIG" and is_big:
                won = True
            elif target == "SMALL" and not is_big:
                won = True
        elif btype == "COLOR":
            if target == "VIOLET" and (winning_number in [0, 5]):
                won = True
                actual_mult = 4.5
            elif target == "GREEN":
                if winning_number in [1, 3, 7, 9]:
                    won = True
                    actual_mult = 2.0
                elif winning_number == 5:
                    won = True
                    actual_mult = 1.5
            elif target == "RED":
                if winning_number in [2, 4, 6, 8]:
                    won = True
                    actual_mult = 2.0
                elif winning_number == 0:
                    won = True
                    actual_mult = 1.5
        elif btype == "NUMBER":
            if target == str(winning_number):
                won = True
                actual_mult = 9.0

        if won:
            win_amount = round(amt * actual_mult, 2)
            res_text = f"Won ₹{win_amount:,.2f} (Outcome {winning_number} {color.upper()})"
            c.execute("""
                UPDATE bets
                SET status = 'WON', win_amount = ?, loss_amount = 0.0, result_text = ?, settled_at = ?
                WHERE bet_id = ?
            """, (win_amount, res_text, now_ts, bet_id))

            # Credit user wallet
            c.execute("SELECT balance FROM users WHERE id = ?", (uid,))
            urow = c.fetchone()
            curr_bal = urow["balance"] if urow else 0.0
            new_bal = curr_bal + win_amount
            c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, uid))

            # Record win transaction
            win_ms = int(time.time() * 1000)
            tx_id = f"TX-WIN-{win_ms}-{random.randint(100, 999)}"
            c.execute("""
                INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                VALUES (?, ?, 'WIN', ?, ?, ?, ?, ?, 'COMPLETED', ?)
            """, (tx_id, uid, f"Win {market_code} #{period}", f"Target {target} ({actual_mult}X) Result {winning_number}", win_amount, curr_bal, new_bal, win_ms))
        else:
            loss_amount = amt
            res_text = f"Lost (Outcome {winning_number} {color.upper()})"
            c.execute("""
                UPDATE bets
                SET status = 'LOST', win_amount = 0.0, loss_amount = ?, result_text = ?, settled_at = ?
                WHERE bet_id = ?
            """, (loss_amount, res_text, now_ts, bet_id))

    # Clear any manual override for this period
    c.execute("""
        UPDATE markets
        SET manual_override_num = NULL, manual_override_period = NULL
        WHERE code = ? AND (manual_override_period = ? OR manual_override_period IS NULL)
    """, (market_code, period))

    conn.commit()

def sync_round_lifecycle_once():
    now_ms = int(time.time() * 1000)
    sse_events = []
    with db_lock:
        conn = get_db()
        c = conn.cursor()

        for m_code in MARKET_KEYS:
            auth_round = calculate_authoritative_round(m_code, now_ms)
            period = auth_round["period"]
            round_id = auth_round["round_id"]
            status = auth_round["status"]

            # Check current market record in DB
            c.execute("SELECT * FROM markets WHERE code = ?", (m_code,))
            m_row = c.fetchone()

            if not m_row:
                c.execute("""
                    INSERT INTO markets (code, name, current_round_id, current_period, round_duration_sec, lock_cutoff_sec, start_time_ms, lock_time_ms, end_time_ms, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (m_code, f"{m_code} MARKET", round_id, period, ROUND_DURATION_SEC, LOCK_CUTOFF_SEC, auth_round["start_time_ms"], auth_round["lock_time_ms"], auth_round["end_time_ms"], status))
                c.execute("SELECT * FROM markets WHERE code = ?", (m_code,))
                m_row = c.fetchone()

            # 0. Ensure immediate previous 50 rounds exist and are settled (prevents stale old result on boot/wake or across 11AM boundary)
            prev_period_id = calculate_authoritative_round(m_code, now_ms - (ROUND_DURATION_SEC * 1000))["period"]
            c.execute("SELECT period FROM rounds WHERE market = ? AND status = 'SETTLED' AND result_number IS NOT NULL AND period = ?", (m_code, prev_period_id))
            if not c.fetchone():
                for back_i in range(1, 51):
                    past_ms = now_ms - (back_i * ROUND_DURATION_SEC * 1000)
                    past_auth = calculate_authoritative_round(m_code, past_ms)
                    past_p = past_auth["period"]
                    past_rid = past_auth["round_id"]
                    if past_p == period:
                        continue
                    c.execute("SELECT status, result_number FROM rounds WHERE round_id = ?", (past_rid,))
                    ex = c.fetchone()
                    if not ex or ex["status"] != "SETTLED" or ex["result_number"] is None:
                        outcome = generate_provably_fair_outcome(m_code, past_p)
                        declared_ts = datetime.fromtimestamp(past_auth["end_time_ms"] / 1000.0, tz=timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M:%S")
                        c.execute("""
                            INSERT INTO rounds (round_id, market, period, start_time_ms, lock_time_ms, end_time_ms, status, result_number, result_color, result_col_class, is_big, draw_mode, declared_at, declared_by)
                            VALUES (?, ?, ?, ?, ?, ?, 'SETTLED', ?, ?, ?, ?, 'AUTO_RANDOM', ?, 'SYSTEM_SYNC')
                            ON CONFLICT(round_id) DO UPDATE SET
                                status = 'SETTLED',
                                result_number = COALESCE(rounds.result_number, excluded.result_number),
                                result_color = COALESCE(rounds.result_color, excluded.result_color),
                                result_col_class = COALESCE(rounds.result_col_class, excluded.result_col_class),
                                is_big = COALESCE(rounds.is_big, excluded.is_big),
                                declared_at = COALESCE(rounds.declared_at, excluded.declared_at)
                        """, (past_rid, m_code, past_p, past_auth["start_time_ms"], past_auth["lock_time_ms"], past_auth["end_time_ms"], outcome["number"], outcome["color"], outcome["col_class"], outcome["is_big"], declared_ts))

            # 1. Check if previous round was not settled yet (with pending bets)
            c.execute("""
                SELECT round_id, period FROM rounds
                WHERE market = ? AND status != 'SETTLED' AND CAST(period AS INTEGER) < CAST(? AS INTEGER)
                ORDER BY CAST(period AS INTEGER) ASC LIMIT 10
            """, (m_code, period))
            unsettled_past = c.fetchall()
            for past in unsettled_past:
                outcome = generate_provably_fair_outcome(m_code, past["period"])
                settle_round_in_db(conn, m_code, past["round_id"], past["period"], outcome["number"], "AUTO_RECOVERY", "SYSTEM")
                _, ev = bump_state_version(conn, "round_settled", {"market": m_code, "period": past["period"], "number": outcome["number"]})
                sse_events.append(ev)

            # 2. Check if active round changed (period transition!)
            last_recorded_period = m_row["current_period"] if m_row else None
            if last_recorded_period and last_recorded_period != period:
                # Period just completed! Settle the old period immediately
                c.execute("SELECT manual_override_num, manual_override_period FROM markets WHERE code = ?", (m_code,))
                ov_row = c.fetchone()
                override_num = ov_row["manual_override_num"] if ov_row else None
                override_period = ov_row["manual_override_period"] if ov_row else None

                if override_num is not None and (override_period == last_recorded_period or not override_period):
                    winning_num = int(override_num)
                    draw_mode = "MANUAL_ADMIN"
                else:
                    outcome = generate_provably_fair_outcome(m_code, last_recorded_period)
                    winning_num = outcome["number"]
                    draw_mode = "AUTO_RANDOM"

                settle_round_in_db(conn, m_code, f"RND_{m_code}_{last_recorded_period}", last_recorded_period, winning_num, draw_mode, "SYSTEM_DAEMON")
                _, ev = bump_state_version(conn, "round_settled", {"market": m_code, "period": last_recorded_period, "number": winning_num})
                sse_events.append(ev)

            # 3. Update active round state for current period
            c.execute("""
                UPDATE markets
                SET current_round_id = ?, current_period = ?, start_time_ms = ?, lock_time_ms = ?, end_time_ms = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
            """, (round_id, period, auth_round["start_time_ms"], auth_round["lock_time_ms"], auth_round["end_time_ms"], status, m_code))

            # 4. If round is locked (last 30s), transition all 'PENDING' bets of this period to 'LOCKED'
            if auth_round["is_betting_locked"]:
                cur_lock = c.execute("""
                    UPDATE bets
                    SET status = 'LOCKED'
                    WHERE market = ? AND period = ? AND status = 'PENDING'
                """, (m_code, period))
                if cur_lock.rowcount and cur_lock.rowcount > 0:
                    _, ev = bump_state_version(conn, "bets_locked", {"market": m_code, "period": period})
                    sse_events.append(ev)

            # 5. Ensure current round exists in rounds table
            c.execute("SELECT round_id FROM rounds WHERE round_id = ?", (round_id,))
            if not c.fetchone():
                c.execute("""
                    INSERT INTO rounds (round_id, market, period, start_time_ms, lock_time_ms, end_time_ms, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (round_id, m_code, period, auth_round["start_time_ms"], auth_round["lock_time_ms"], auth_round["end_time_ms"], status))

        conn.commit()
        conn.close()

    for ev in sse_events:
        notify_sse_clients(ev)

def background_round_lifecycle_daemon():
    """Background engine ensuring continuous 180s countdowns, 30s locks, and atomic settlements across all 4 markets."""
    while True:
        try:
            sync_round_lifecycle_once()
        except Exception as e:
            print(f"Error in background round lifecycle: {e}")

        time.sleep(0.25)

def _parse_ts_ms(ts_str, fallback_ms=0):
    if fallback_ms and int(fallback_ms) > 0:
        return int(fallback_ms)
    if not ts_str:
        return int(time.time() * 1000)
    try:
        dt = datetime.strptime(str(ts_str)[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)

def build_user_statement(conn, uid, days=90, category="ALL", market_filter="ALL"):
    now_ms = int(time.time() * 1000)
    days_clamped = max(1, min(90, int(days)))
    cutoff_ms = now_ms - (days_clamped * 86400 * 1000)
    cat_upper = (category or "ALL").upper().strip()
    mkt_upper = (market_filter or "ALL").upper().strip()

    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    u = c.fetchone()
    user_name = u["name"] if u else uid
    wallet_balance = float(u["balance"]) if u else 0.0
    referral_code = (u["referral_code"] if u and "referral_code" in u.keys() and u["referral_code"] else (uid[-6:] if len(uid) >= 6 else uid).upper())

    # 1. All bet records within window (up to 90 days stored & shown)
    if mkt_upper != "ALL" and mkt_upper in MARKET_KEYS:
        c.execute("""
            SELECT * FROM bets
            WHERE user_id = ? AND created_at_ms >= ? AND market = ?
            ORDER BY created_at_ms DESC
        """, (uid, cutoff_ms, mkt_upper))
    else:
        c.execute("""
            SELECT * FROM bets
            WHERE user_id = ? AND created_at_ms >= ?
            ORDER BY created_at_ms DESC
        """, (uid, cutoff_ms))
    bet_rows = c.fetchall()

    bets_list = []
    total_wagered = 0.0
    total_won = 0.0
    won_count = 0
    lost_count = 0
    pending_count = 0
    cancelled_count = 0

    for r in bet_rows:
        st = str(r["status"] or "PENDING").upper()
        amt = float(r["amount"] or 0.0)
        win_amt = float(r["win_amount"] or 0.0)
        loss_amt = float(r["loss_amount"] or 0.0)
        if st == "WON":
            won_count += 1
            total_wagered += amt
            total_won += win_amt
            net_pl = round(win_amt - amt, 2)
        elif st == "LOST":
            lost_count += 1
            total_wagered += amt
            net_pl = round(-amt, 2)
        elif st in ("CANCELLED", "REFUNDED"):
            cancelled_count += 1
            net_pl = 0.0
        else:
            pending_count += 1
            total_wagered += amt
            net_pl = 0.0

        bets_list.append({
            "id": r["bet_id"],
            "userId": r["user_id"],
            "userName": r["user_name"],
            "marketId": r["market"],
            "marketName": f"{r['market']} MARKET",
            "roundId": r["round_id"],
            "period": r["period"],
            "amount": round(amt, 2),
            "type": r["prediction_type"],
            "target": r["prediction_target"],
            "mult": float(r["multiplier"] or 0.0),
            "potentialPayout": float(r["potential_payout"] or 0.0),
            "status": st,
            "result": r["result_text"],
            "winAmount": round(win_amt, 2),
            "lossAmount": round(loss_amt, 2),
            "netProfitLoss": net_pl,
            "time": r["created_at"],
            "settledAt": r["settled_at"],
            "createdAtMs": int(r["created_at_ms"] or 0)
        })

    net_bet_pl = round(total_won - total_wagered, 2)

    # 2. Transactions + Deposits + Withdrawals + Referral Commissions within window
    c.execute("""
        SELECT * FROM transactions
        WHERE user_id = ? AND (created_at_ms >= ? OR created_at_ms = 0)
        ORDER BY created_at_ms DESC, created_at DESC
    """, (uid, cutoff_ms))
    tx_rows = c.fetchall()

    c.execute("""
        SELECT * FROM deposits
        WHERE user_id = ? AND (created_at_ms >= ? OR created_at_ms = 0)
        ORDER BY created_at_ms DESC, created_at DESC
    """, (uid, cutoff_ms))
    dep_rows = c.fetchall()

    c.execute("""
        SELECT * FROM withdrawals
        WHERE user_id = ? AND (created_at_ms >= ? OR created_at_ms = 0)
        ORDER BY created_at_ms DESC, created_at DESC
    """, (uid, cutoff_ms))
    wd_rows = c.fetchall()

    c.execute("""
        SELECT * FROM referral_commissions
        WHERE beneficiary_user_id = ? AND created_at_ms >= ?
        ORDER BY created_at_ms DESC
    """, (uid, cutoff_ms))
    ref_rows = c.fetchall()

    statement_entries = []
    seen_dep_refs = set()
    seen_wd_refs = set()

    total_deposit_success = 0.0
    total_deposit_pending = 0.0
    total_withdrawal_approved = 0.0
    total_withdrawal_pending = 0.0
    total_refer_earn = 0.0

    for d in dep_rows:
        st_u = str(d["status"] or "IN PROCESS").upper()
        amt = float(d["amount"] or 0.0)
        ts_ms = _parse_ts_ms(d["created_at"], d["created_at_ms"] if "created_at_ms" in d.keys() else 0)
        if ts_ms < cutoff_ms:
            continue
        if st_u == "SUCCESS":
            total_deposit_success += amt
        elif st_u == "IN PROCESS":
            total_deposit_pending += amt
        seen_dep_refs.add(f"UTR {d['utr']}")
        statement_entries.append({
            "id": d["id"],
            "category": "DEPOSIT",
            "type": "DEPOSIT",
            "title": f"Deposit via {d['method'] or 'UPI'}",
            "ref": f"UTR: {d['utr']}" + (f" ({d['reason']})" if d["reason"] else ""),
            "amount": round(amt, 2),
            "balanceBefore": None,
            "balanceAfter": None,
            "status": st_u,
            "reason": d["reason"],
            "time": d["created_at"] or d["time_str"] or "",
            "timestampMs": ts_ms
        })

    for w in wd_rows:
        st_u = str(w["status"] or "IN PROCESS").upper()
        amt = float(w["amount"] or 0.0)
        ts_ms = _parse_ts_ms(w["created_at"], w["created_at_ms"] if "created_at_ms" in w.keys() else 0)
        if ts_ms < cutoff_ms:
            continue
        if st_u == "SUCCESS":
            total_withdrawal_approved += amt
        elif st_u == "IN PROCESS":
            total_withdrawal_pending += amt
        seen_wd_refs.add(str(w["destination"] or ""))
        statement_entries.append({
            "id": w["id"],
            "category": "WITHDRAWAL",
            "type": "WITHDRAWAL",
            "title": f"Withdrawal to {w['bank_name'] or 'Bank / UPI'}",
            "ref": (w["destination"] or f"A/C: {w['acc_no'] or w['upi_id'] or 'N/A'}") + (f" • {w['reason']}" if w["reason"] else ""),
            "amount": round(-amt, 2),
            "balanceBefore": None,
            "balanceAfter": None,
            "status": st_u,
            "reason": w["reason"],
            "time": w["created_at"] or w["time_str"] or "",
            "timestampMs": ts_ms
        })

    for tx in tx_rows:
        tx_type = str(tx["type"] or "").upper()
        amt = float(tx["amount"] or 0.0)
        ts_ms = _parse_ts_ms(tx["created_at"], tx["created_at_ms"] if "created_at_ms" in tx.keys() else 0)
        if ts_ms < cutoff_ms:
            continue

        # Avoid duplicate deposit/withdrawal rows when already tracked via deposits/withdrawals table
        if tx_type == "DEPOSIT" and str(tx["ref"] or "") in seen_dep_refs:
            continue
        if tx_type == "WITHDRAWAL" and str(tx["ref"] or "") in seen_wd_refs:
            continue

        if tx_type in ("COMMISSION", "REFERRAL_COMMISSION"):
            total_refer_earn += amt
            cat = "REFERRAL"
        elif tx_type in ("BET", "WIN"):
            cat = "PROFIT_LOSS"
        elif tx_type == "DEPOSIT":
            if amt > 0:
                total_deposit_success += amt
            cat = "DEPOSIT"
        elif tx_type in ("WITHDRAWAL", "WITHDRAWAL_REFUND"):
            cat = "WITHDRAWAL"
        else:
            cat = tx_type

        statement_entries.append({
            "id": tx["tx_id"],
            "category": cat,
            "type": tx_type,
            "title": tx["title"] or tx_type,
            "ref": tx["ref"] or "",
            "amount": round(amt, 2),
            "balanceBefore": round(float(tx["balance_before"]), 2),
            "balanceAfter": round(float(tx["balance_after"]), 2),
            "status": str(tx["status"] or "COMPLETED").upper(),
            "reason": None,
            "time": tx["created_at"] or "",
            "timestampMs": ts_ms
        })

    for rc in ref_rows:
        comm_amt = float(rc["commission_amount"] or 0.0)
        ts_ms = int(rc["created_at_ms"] or 0)
        # Check if already present via transactions table
        already_in_tx = any(e["id"] == rc["id"] or (e["type"] == "REFERRAL_COMMISSION" and abs(e["timestampMs"] - ts_ms) < 500 and abs(e["amount"] - comm_amt) < 0.01) for e in statement_entries)
        if not already_in_tx:
            total_refer_earn += comm_amt
            statement_entries.append({
                "id": rc["id"],
                "category": "REFERRAL",
                "type": "REFERRAL_COMMISSION",
                "title": f"Tier {rc['level']} Refer & Earn ({float(rc['rate'])*100:.2f}%)",
                "ref": f"From {rc['source_user_name'] or rc['source_user_id']} (Bet {rc['source_bet_id'] or ''})",
                "amount": round(comm_amt, 2),
                "balanceBefore": None,
                "balanceAfter": None,
                "status": str(rc["status"] or "SETTLED").upper(),
                "reason": None,
                "time": rc["created_at"] or "",
                "timestampMs": ts_ms
            })

    statement_entries.sort(key=lambda x: x["timestampMs"], reverse=True)

    # Filter entries by requested category if specified
    if cat_upper == "PROFIT_LOSS":
        filtered_entries = [e for e in statement_entries if e["type"] in ("BET", "WIN", "REFUND", "PROFIT_LOSS")]
    elif cat_upper in ("BETS", "BET"):
        filtered_entries = [e for e in statement_entries if e["type"] == "BET"]
    elif cat_upper == "WIN":
        filtered_entries = [e for e in statement_entries if e["type"] == "WIN"]
    elif cat_upper in ("REFERRAL", "COMMISSION", "REFER"):
        filtered_entries = [e for e in statement_entries if e["category"] == "REFERRAL" or e["type"] in ("COMMISSION", "REFERRAL_COMMISSION")]
    elif cat_upper == "DEPOSIT":
        filtered_entries = [e for e in statement_entries if e["type"] == "DEPOSIT"]
    elif cat_upper == "WITHDRAWAL":
        filtered_entries = [e for e in statement_entries if e["type"] in ("WITHDRAWAL", "WITHDRAWAL_REFUND")]
    else:
        filtered_entries = statement_entries

    summary = {
        "walletBalance": round(wallet_balance, 2),
        "days": days_clamped,
        "retentionDays": RETENTION_DAYS,
        "totalBetsCount": len(bets_list),
        "wonBetsCount": won_count,
        "lostBetsCount": lost_count,
        "pendingBetsCount": pending_count,
        "cancelledBetsCount": cancelled_count,
        "totalWagered": round(total_wagered, 2),
        "totalWon": round(total_won, 2),
        "netBetProfitLoss": net_bet_pl,
        "totalReferEarn": round(total_refer_earn, 2),
        "totalDeposit": round(total_deposit_success, 2),
        "pendingDepositTotal": round(total_deposit_pending, 2),
        "totalWithdrawal": round(total_withdrawal_approved, 2),
        "pendingWithdrawalTotal": round(total_withdrawal_pending, 2),
        "lifetimeDeposit": round(float(u["total_deposit"]) if u else 0.0, 2),
        "lifetimeWithdraw": round(float(u["total_withdraw"]) if u else 0.0, 2),
    }

    return {
        "userId": uid,
        "userName": user_name,
        "referralCode": referral_code,
        "days": days_clamped,
        "retentionDays": RETENTION_DAYS,
        "category": cat_upper,
        "market": mkt_upper,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "bets": bets_list,
        "statementEntries": filtered_entries
    }

def export_statement_csv(stmt):
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM for Microsoft Excel compatibility
    w = csv.writer(buf)
    s = stmt["summary"]

    w.writerow(["COLOUR KING - 90-DAY ACCOUNT & BETTING STATEMENT"])
    w.writerow(["User ID", stmt["userId"], "User Name", stmt["userName"], "Statement Period", f"Last {stmt['days']} Days (Max Retention: {stmt['retentionDays']} Days)", "Generated At", stmt["generatedAt"]])
    w.writerow([])
    w.writerow(["FINANCIAL SUMMARY (INR)"])
    w.writerow(["Current Wallet Balance", f"{s['walletBalance']:.2f}"])
    w.writerow(["Total Bets Played", s["totalBetsCount"], "Won", s["wonBetsCount"], "Lost", s["lostBetsCount"], "Pending", s["pendingBetsCount"], "Cancelled", s["cancelledBetsCount"]])
    w.writerow(["Total Bet Wagered", f"{s['totalWagered']:.2f}", "Total Bet Won", f"{s['totalWon']:.2f}", "Net Bet Profit / Loss", f"{s['netBetProfitLoss']:+.2f}"])
    w.writerow(["Total Refer & Earn", f"{s['totalReferEarn']:.2f}", "Total Approved Deposits", f"{s['totalDeposit']:.2f}", "Total Approved Withdrawals", f"{s['totalWithdrawal']:.2f}"])
    w.writerow(["Pending Deposits", f"{s['pendingDepositTotal']:.2f}", "Pending Withdrawals", f"{s['pendingWithdrawalTotal']:.2f}"])
    w.writerow([])

    w.writerow(["WALLET TRANSACTIONS STATEMENT (BET P&L, REFER EARN, DEPOSIT, WITHDRAWAL)"])
    w.writerow(["Date & Time", "Entry ID", "Category", "Type", "Title", "Reference / UTR / Bank", "Amount (INR)", "Balance Before", "Balance After", "Status", "Reason"])
    for e in stmt["statementEntries"]:
        w.writerow([
            e["time"],
            e["id"],
            e["category"],
            e["type"],
            e["title"],
            e["ref"],
            f"{e['amount']:+.2f}",
            f"{e['balanceBefore']:.2f}" if e["balanceBefore"] is not None else "-",
            f"{e['balanceAfter']:.2f}" if e["balanceAfter"] is not None else "-",
            e["status"],
            e.get("reason") or ""
        ])

    w.writerow([])
    w.writerow(["90-DAY BETTING RECORDS HISTORY"])
    w.writerow(["Placed At", "Bet ID", "Market", "Period Number", "Prediction Type", "Target", "Multiplier", "Stake (INR)", "Status", "Payout Won (INR)", "Net Profit/Loss (INR)", "Official Result"])
    for b in stmt["bets"]:
        w.writerow([
            b["time"],
            b["id"],
            b["marketId"],
            b["period"],
            b["type"],
            b["target"],
            f"{b['mult']}x",
            f"{b['amount']:.2f}",
            b["status"],
            f"{b['winAmount']:.2f}",
            f"{b['netProfitLoss']:+.2f}",
            b["result"]
        ])

    return buf.getvalue()

class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _send_csv(self, csv_text, filename):
        try:
            body = csv_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"Error sending CSV response: {e}")

    def _send_json(self, data, status=200):
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"Error sending response: {e}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ["/admin", "/admin/"]:
            self.send_response(301)
            self.send_header("Location", "/admin.html")
            self.end_headers()
            return

        # 0. Real-Time Server-Sent Events (SSE) Push Stream
        if path == "/api/events":
            q = queue.Queue(maxsize=100)
            with db_lock:
                conn = get_db()
                init_ver = get_state_version(conn)
                conn.close()
            with sse_lock:
                sse_subscribers.append(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                init_msg = json.dumps({
                    "version": init_ver,
                    "eventType": "connected",
                    "serverTimeMs": int(time.time() * 1000)
                })
                self.wfile.write(f"event: connected\ndata: {init_msg}\n\n".encode("utf-8"))
                self.wfile.flush()

                while True:
                    try:
                        ev = q.get(timeout=15.0)
                        line = f"event: state_update\ndata: {json.dumps(ev)}\n\n".encode("utf-8")
                        self.wfile.write(line)
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                with sse_lock:
                    if q in sse_subscribers:
                        sse_subscribers.remove(q)
            return

        # 1. Authoritative Server Clock
        if path == "/api/clock":
            now_ms = int(time.time() * 1000)
            self._send_json({
                "server_time_ms": now_ms,
                "iso": datetime.now(timezone.utc).isoformat(),
                "timezone": "IST"
            })
            return

        # 2. Authoritative Real-Time 4-Markets State
        if path == "/api/markets":
            now_ms = int(time.time() * 1000)
            with db_lock:
                conn = get_db()
                c = conn.cursor()

                markets_data = {}
                for m_code in MARKET_KEYS:
                    auth = calculate_authoritative_round(m_code, now_ms)
                    period = auth["period"]

                    # Check for manual override
                    c.execute("SELECT manual_override_num, manual_override_period FROM markets WHERE code = ?", (m_code,))
                    m_row = c.fetchone()
                    ov_num = m_row["manual_override_num"] if m_row else None
                    ov_period = m_row["manual_override_period"] if m_row else None

                    # Ensure immediate previous period is settled even if polled <250ms after rollover
                    prev_period_id = calculate_authoritative_round(m_code, now_ms - (ROUND_DURATION_SEC * 1000))["period"]
                    c.execute("SELECT status, result_number FROM rounds WHERE market = ? AND period = ?", (m_code, prev_period_id))
                    prev_row = c.fetchone()
                    if not prev_row or prev_row["status"] != "SETTLED" or prev_row["result_number"] is None:
                        if ov_num is not None and (ov_period == prev_period_id or not ov_period):
                            win_num = int(ov_num)
                            d_mode = "MANUAL_ADMIN"
                        else:
                            win_num = generate_provably_fair_outcome(m_code, prev_period_id)["number"]
                            d_mode = "AUTO_RANDOM"
                        settle_round_in_db(conn, m_code, f"RND_{m_code}_{prev_period_id}", prev_period_id, win_num, d_mode, "SYSTEM_ROLLOVER")

                    # Get latest completed result (always strictly before current period, sorted numerically)
                    c.execute("""
                        SELECT period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at
                        FROM rounds
                        WHERE market = ? AND status = 'SETTLED' AND result_number IS NOT NULL AND CAST(period AS INTEGER) < CAST(? AS INTEGER)
                        ORDER BY CAST(period AS INTEGER) DESC LIMIT 1
                    """, (m_code, period))
                    last_res = c.fetchone()
                    latest_result = None
                    if last_res:
                        latest_result = {
                            "period": last_res["period"],
                            "number": last_res["result_number"],
                            "color": last_res["result_color"],
                            "colClass": last_res["result_col_class"],
                            "isBig": bool(last_res["is_big"]),
                            "drawMode": last_res["draw_mode"],
                            "time": last_res["declared_at"]
                        }

                    # Count active bets in current period
                    c.execute("""
                        SELECT COUNT(*), COALESCE(SUM(amount), 0.0)
                        FROM bets
                        WHERE market = ? AND period = ? AND status IN ('PENDING', 'LOCKED')
                    """, (m_code, period))
                    b_count, b_total = c.fetchone()

                    markets_data[m_code] = {
                        "market": m_code,
                        "round_id": auth["round_id"],
                        "period": period,
                        "start_time_ms": auth["start_time_ms"],
                        "lock_time_ms": auth["lock_time_ms"],
                        "end_time_ms": auth["end_time_ms"],
                        "remaining_seconds": auth["remaining_seconds"],
                        "is_betting_locked": auth["is_betting_locked"],
                        "status": auth["status"],
                        "active_bets_count": b_count,
                        "active_bets_total": b_total,
                        "manual_override": {
                            "number": ov_num,
                            "period": ov_period
                        } if ov_num is not None else None,
                        "latest_result": latest_result
                    }

                conn.close()

            self._send_json({
                "server_time_ms": now_ms,
                "markets": markets_data
            })
            return

        # 3. Market History Records (24-Hour table)
        if path == "/api/markets/history":
            m_code = qs.get("market", ["MIAMI"])[0].upper()
            limit = int(qs.get("limit", [50])[0])
            cur_auth = calculate_authoritative_round(m_code)
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("""
                    SELECT period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at
                    FROM rounds
                    WHERE market = ? AND status = 'SETTLED' AND result_number IS NOT NULL AND CAST(period AS INTEGER) < CAST(? AS INTEGER)
                    ORDER BY CAST(period AS INTEGER) DESC LIMIT ?
                """, (m_code, cur_auth["period"], limit))
                rows = c.fetchall()
                records = []
                for r in rows:
                    records.append({
                        "period": r["period"],
                        "number": r["result_number"],
                        "color": r["result_color"],
                        "colClass": r["result_col_class"],
                        "isBig": bool(r["is_big"]),
                        "drawMode": r["draw_mode"],
                        "time": r["declared_at"]
                    })
                conn.close()
            self._send_json({ "market": m_code, "records": records })
            return

        # 4. User Bets (Active bets for round + Bet Slips History)
        if path == "/api/bets":
            uid = qs.get("userId", ["USR-1001"])[0]
            m_code = qs.get("market", [None])[0]
            if m_code:
                m_code = m_code.upper()
            now_ms = int(time.time() * 1000)

            with db_lock:
                conn = get_db()
                c = conn.cursor()

                # Settle any expired PENDING/LOCKED bets on-demand (zero rollover lag)
                cur_period_map = {mk: calculate_authoritative_round(mk, now_ms)["period"] for mk in MARKET_KEYS}
                c.execute("""
                    SELECT DISTINCT market, round_id, period
                    FROM bets
                    WHERE user_id = ? AND status IN ('PENDING', 'LOCKED')
                """, (uid,))
                for pb in c.fetchall():
                    pm = pb["market"]
                    pp = pb["period"]
                    if pm in cur_period_map and int(pp) < int(cur_period_map[pm]):
                        c.execute("SELECT result_number, draw_mode FROM rounds WHERE round_id = ? AND status = 'SETTLED' AND result_number IS NOT NULL", (pb["round_id"],))
                        settled_r = c.fetchone()
                        if settled_r:
                            win_n = int(settled_r["result_number"])
                            d_m = settled_r["draw_mode"] or "AUTO_RANDOM"
                        else:
                            c.execute("SELECT manual_override_num, manual_override_period FROM markets WHERE code = ?", (pm,))
                            ov_r = c.fetchone()
                            ov_num = ov_r["manual_override_num"] if ov_r else None
                            ov_per = ov_r["manual_override_period"] if ov_r else None
                            if ov_num is not None and (ov_per == pp or not ov_per):
                                win_n = int(ov_num)
                                d_m = "MANUAL_ADMIN"
                            else:
                                win_n = generate_provably_fair_outcome(pm, pp)["number"]
                                d_m = "AUTO_RANDOM"
                        settle_round_in_db(conn, pm, pb["round_id"], pp, win_n, d_m, "SYSTEM_ROLLOVER")

                # Active bets (PENDING or LOCKED)
                if m_code:
                    c.execute("""
                        SELECT * FROM bets
                        WHERE user_id = ? AND market = ? AND status IN ('PENDING', 'LOCKED')
                        ORDER BY created_at_ms DESC
                    """, (uid, m_code))
                else:
                    c.execute("""
                        SELECT * FROM bets
                        WHERE user_id = ? AND status IN ('PENDING', 'LOCKED')
                        ORDER BY created_at_ms DESC
                    """, (uid,))
                active_rows = c.fetchall()

                # All user bets history within 90-day retention window (or requested days <= 90)
                try:
                    req_days = max(1, min(RETENTION_DAYS, int(qs.get("days", [str(RETENTION_DAYS)])[0])))
                except Exception:
                    req_days = RETENTION_DAYS
                cutoff_ms = now_ms - (req_days * 86400 * 1000)

                if m_code:
                    c.execute("""
                        SELECT * FROM bets
                        WHERE user_id = ? AND market = ? AND created_at_ms >= ?
                        ORDER BY created_at_ms DESC LIMIT 5000
                    """, (uid, m_code, cutoff_ms))
                else:
                    c.execute("""
                        SELECT * FROM bets
                        WHERE user_id = ? AND created_at_ms >= ?
                        ORDER BY created_at_ms DESC LIMIT 5000
                    """, (uid, cutoff_ms))
                history_rows = c.fetchall()

                conn.close()

            def row_to_dict(r):
                amt = float(r["amount"] or 0.0)
                win_amt = float(r["win_amount"] or 0.0)
                st_u = str(r["status"] or "PENDING").upper()
                net_pl = round(win_amt - amt, 2) if st_u == "WON" else (round(-amt, 2) if st_u == "LOST" else 0.0)
                return {
                    "id": r["bet_id"],
                    "userId": r["user_id"],
                    "userName": r["user_name"],
                    "marketId": r["market"],
                    "marketName": f"{r['market']} MARKET",
                    "roundId": r["round_id"],
                    "period": r["period"],
                    "amount": amt,
                    "type": r["prediction_type"],
                    "target": r["prediction_target"],
                    "mult": r["multiplier"],
                    "potentialPayout": r["potential_payout"],
                    "status": r["status"],
                    "result": r["result_text"],
                    "winAmount": win_amt,
                    "lossAmount": float(r["loss_amount"] or 0.0),
                    "netProfitLoss": net_pl,
                    "time": r["created_at"],
                    "createdAtMs": int(r["created_at_ms"] or 0)
                }

            self._send_json({
                "userId": uid,
                "retentionDays": RETENTION_DAYS,
                "days": req_days,
                "activeBets": [row_to_dict(r) for r in active_rows],
                "betHistory": [row_to_dict(r) for r in history_rows]
            })
            return

        # 4B. Full 90-Day Account Statement (Wallet, Bet P&L, Refer & Earn, Deposit, Withdrawal)
        if path == "/api/statement":
            uid = qs.get("userId", ["USR-1001"])[0]
            try:
                req_days = int(qs.get("days", [str(RETENTION_DAYS)])[0])
            except Exception:
                req_days = RETENTION_DAYS
            cat = qs.get("category", ["ALL"])[0]
            mkt = qs.get("market", ["ALL"])[0]

            with db_lock:
                conn = get_db()
                stmt = build_user_statement(conn, uid, days=req_days, category=cat, market_filter=mkt)
                conn.close()
            self._send_json(stmt)
            return

        # 4C. Downloadable Statement Export (CSV)
        if path == "/api/statement/export":
            uid = qs.get("userId", ["USR-1001"])[0]
            try:
                req_days = int(qs.get("days", [str(RETENTION_DAYS)])[0])
            except Exception:
                req_days = RETENTION_DAYS
            cat = qs.get("category", ["ALL"])[0]
            mkt = qs.get("market", ["ALL"])[0]

            with db_lock:
                conn = get_db()
                stmt = build_user_statement(conn, uid, days=req_days, category=cat, market_filter=mkt)
                conn.close()
            csv_text = export_statement_csv(stmt)
            safe_uid = "".join(ch for ch in uid if ch.isalnum() or ch in ("-", "_")) or "user"
            fname = f"ColourKing_{stmt['days']}Day_Statement_{safe_uid}_{datetime.now().strftime('%Y%m%d')}.csv"
            self._send_csv(csv_text, fname)
            return

        # 5. User Profile & Balance
        if path == "/api/user" or path == "/api/wallet":
            uid = qs.get("id", qs.get("userId", ["USR-1001"]))[0]
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                if not u:
                    name = qs.get("name", [uid])[0]
                    c.execute("""
                        INSERT INTO users (id, name, balance, total_deposit, total_withdraw, bets_count, status)
                        VALUES (?, ?, 50200.00, 0.0, 0.0, 0, 'ACTIVE')
                    """, (uid, name))
                    conn.commit()
                    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                    u = c.fetchone()
                conn.close()

            self._send_json({
                "id": u["id"],
                "userId": u["id"],
                "name": u["name"],
                "balance": u["balance"],
                "totalDeposit": u["total_deposit"],
                "totalWithdraw": u["total_withdraw"],
                "betsCount": u["bets_count"],
                "status": u["status"]
            })
            return

        # 6. Admin Overview Statistics
        if path == "/api/admin/overview":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT COUNT(*), COUNT(CASE WHEN status='ACTIVE' THEN 1 END) FROM users")
                total_users, active_users = c.fetchone()

                c.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0.0) FROM bets")
                total_bets, total_wager = c.fetchone()

                c.execute("SELECT COUNT(*) FROM deposits WHERE status='IN PROCESS'")
                pending_deps = c.fetchone()[0]

                c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='IN PROCESS'")
                pending_wds = c.fetchone()[0]

                conn.close()

            self._send_json({
                "totalUsers": total_users,
                "activeUsers": active_users,
                "totalBets": total_bets,
                "totalWager": total_wager,
                "pendingDeposits": pending_deps,
                "pendingWithdrawals": pending_wds
            })
            return

        # 7. Complete SQLite Real-Time State Snapshot (Admin & User Sync)
        if path == "/api/state/version":
            with db_lock:
                conn = get_db()
                ver = get_state_version(conn)
                conn.close()
            self._send_json({ "state_version": ver, "server_time_ms": int(time.time() * 1000) })
            return

        if path == "/api/state":
            now_ms = int(time.time() * 1000)
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                state_ver = get_state_version(conn)

                c.execute("SELECT * FROM users")
                all_user_rows = c.fetchall()
                users_list = {r["id"]: {
                    "id": r["id"],
                    "name": r["name"],
                    "phone": r["phone"] or "",
                    "email": r["email"] or "",
                    "balance": round(float(r["balance"] or 0.0), 2),
                    "totalDeposit": round(float(r["total_deposit"] or 0.0), 2),
                    "totalWithdraw": round(float(r["total_withdraw"] or 0.0), 2),
                    "betsCount": int(r["bets_count"] or 0),
                    "status": r["status"] or "ACTIVE",
                    "referralCode": (r["referral_code"] if "referral_code" in r.keys() and r["referral_code"] else r["id"][-6:].upper()),
                    "referredBy": (r["referred_by"] if "referred_by" in r.keys() else None)
                } for r in all_user_rows}

                c.execute("SELECT * FROM deposits ORDER BY created_at_ms DESC, created_at DESC LIMIT 100")
                deposits_list = [{
                    "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                    "amount": round(float(r["amount"] or 0.0), 2), "method": r["method"], "utr": r["utr"],
                    "time": r["time_str"] or r["created_at"] or "", "status": r["status"], "reason": r["reason"]
                } for r in c.fetchall()]

                c.execute("SELECT * FROM withdrawals ORDER BY created_at_ms DESC, created_at DESC LIMIT 100")
                withdrawals_list = [{
                    "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                    "amount": round(float(r["amount"] or 0.0), 2), "upiId": r["upi_id"], "bankName": r["bank_name"],
                    "accNo": r["acc_no"], "ifsc": r["ifsc"], "bankingName": r["banking_name"],
                    "destination": r["destination"], "time": r["time_str"] or r["created_at"] or "", "status": r["status"],
                    "reason": r["reason"]
                } for r in c.fetchall()]

                c.execute("SELECT value FROM app_state WHERE key = 'bank_config'")
                bcfg_row = c.fetchone()
                bank_cfg = json.loads(bcfg_row[0]) if bcfg_row else DEFAULT_BANK_CONFIG

                c.execute("SELECT value FROM app_state WHERE key = 'platform_settings'")
                pcfg_row = c.fetchone()
                platform_cfg = json.loads(pcfg_row[0]) if pcfg_row else DEFAULT_PLATFORM_SETTINGS

                c.execute("SELECT code, manual_override_num, manual_override_period FROM markets WHERE manual_override_num IS NOT NULL")
                draw_overrides = {}
                for ov in c.fetchall():
                    ov_num = int(ov["manual_override_num"])
                    ov_col = "VIOLET+RED" if ov_num == 0 else ("VIOLET+GREEN" if ov_num == 5 else ("GREEN" if ov_num in [1,3,7,9] else "RED"))
                    draw_overrides[ov["code"]] = {
                        "market": ov["code"],
                        "number": ov_num,
                        "color": ov_col,
                        "period": ov["manual_override_period"],
                        "mode": "MANUAL"
                    }

                c.execute("""
                    SELECT round_id, market, period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at
                    FROM rounds
                    WHERE status = 'SETTLED' AND result_number IS NOT NULL
                    ORDER BY CAST(period AS INTEGER) DESC, declared_at DESC
                    LIMIT 240
                """)
                declared_results = { m: {} for m in MARKET_KEYS }
                declared_results_list = []
                for rr in c.fetchall():
                    m_k = rr["market"]
                    p_str = str(rr["period"])
                    num_i = int(rr["result_number"])
                    col_raw = rr["result_color"] or ("violet" if num_i in [0, 5] else ("green" if num_i in [1,3,7,9] else "red"))
                    col_cls = rr["result_col_class"] or ("red-violet" if num_i == 0 else ("green-violet" if num_i == 5 else col_raw))
                    col_badge = "VIOLET+RED" if num_i == 0 else ("VIOLET+GREEN" if num_i == 5 else col_raw.upper())
                    if m_k in declared_results and len(declared_results[m_k]) < 60:
                        declared_results[m_k][p_str] = {
                            "period": p_str,
                            "number": num_i,
                            "color": col_raw,
                            "colClass": col_cls,
                            "isBig": bool(rr["is_big"]),
                            "mode": rr["draw_mode"] or "AUTO_RANDOM",
                            "time": rr["declared_at"] or ""
                        }
                    if len(declared_results_list) < 50:
                        c.execute("SELECT COALESCE(SUM(win_amount), 0.0) FROM bets WHERE market = ? AND period = ? AND status = 'WON'", (m_k, p_str))
                        payout_sum = float(c.fetchone()[0] or 0.0)
                        declared_results_list.append({
                            "market": m_k,
                            "period": p_str,
                            "number": num_i,
                            "color": col_badge,
                            "isBig": bool(rr["is_big"]),
                            "mode": rr["draw_mode"] or "AUTO_RANDOM",
                            "payout": round(payout_sum, 2),
                            "time": rr["declared_at"] or ""
                        })

                c.execute("SELECT * FROM bets ORDER BY created_at_ms DESC LIMIT 200")
                bets_list = [{
                    "id": r["bet_id"],
                    "market": r["market"],
                    "period": r["period"],
                    "userId": r["user_id"],
                    "userName": r["user_name"],
                    "target": r["prediction_target"],
                    "type": r["prediction_type"],
                    "amount": round(float(r["amount"] or 0.0), 2),
                    "multiplier": float(r["multiplier"] or 0.0),
                    "status": r["status"],
                    "payout": round(float(r["win_amount"] or 0.0), 2),
                    "time": r["created_at"] or "",
                    "createdAtMs": int(r["created_at_ms"] or 0)
                } for r in c.fetchall()]

                c.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT 100")
                audit_logs = [{
                    "id": r["id"],
                    "actor": r["actor"],
                    "action": r["action"],
                    "entity": r["entity"],
                    "desc": r["desc"],
                    "time": r["created_at"] or ""
                } for r in c.fetchall()]

                # Build affiliate overview dynamically from SQLite users & referral_commissions
                affiliates_list = []
                for u in all_user_rows:
                    uid_cur = u["id"]
                    c.execute("SELECT id, name, total_deposit, status, created_at FROM users WHERE referred_by = ?", (uid_cur,))
                    directs = c.fetchall()
                    c.execute("SELECT COALESCE(SUM(commission_amount), 0.0) FROM referral_commissions WHERE beneficiary_user_id = ? AND status != 'REVERSED'", (uid_cur,))
                    tot_comm = float(c.fetchone()[0] or 0.0)
                    day_ago_ms = now_ms - 86400000
                    c.execute("SELECT COALESCE(SUM(commission_amount), 0.0) FROM referral_commissions WHERE beneficiary_user_id = ? AND created_at_ms >= ? AND status != 'REVERSED'", (uid_cur, day_ago_ms))
                    recent_comm = float(c.fetchone()[0] or 0.0)
                    members_arr = []
                    for dm in directs:
                        c.execute("SELECT COALESCE(SUM(commission_amount), 0.0) FROM referral_commissions WHERE beneficiary_user_id = ? AND source_user_id = ?", (uid_cur, dm["id"]))
                        dm_comm = float(c.fetchone()[0] or 0.0)
                        members_arr.append({
                            "id": dm["id"],
                            "name": dm["name"],
                            "tier": "Tier 1 (Direct)",
                            "joinDate": str(dm["created_at"] or "")[:10],
                            "totalDeposit": round(float(dm["total_deposit"] or 0.0), 2),
                            "commission": round(dm_comm, 2),
                            "status": dm["status"] or "ACTIVE"
                        })
                    affiliates_list.append({
                        "userId": uid_cur,
                        "userName": u["name"],
                        "phone": u["phone"] or "",
                        "refCode": (u["referral_code"] if "referral_code" in u.keys() and u["referral_code"] else uid_cur[-6:].upper()),
                        "referredBy": (u["referred_by"] if "referred_by" in u.keys() and u["referred_by"] else "OFFICIAL_PROMO"),
                        "directMembersCount": len(directs),
                        "teamMembersCount": len(directs),
                        "totalEarnedCommission": round(tot_comm, 2),
                        "yesterdayCommission": round(recent_comm, 2),
                        "members": members_arr
                    })

                conn.close()

            self._send_json({
                "state_version": state_ver,
                "server_time_ms": now_ms,
                "bank_config": bank_cfg,
                "platform_settings": platform_cfg,
                "users": users_list,
                "deposits": deposits_list,
                "withdrawals": withdrawals_list,
                "draw_overrides": draw_overrides,
                "declared_results": declared_results,
                "declared_results_list": declared_results_list,
                "bets": bets_list,
                "audit_logs": audit_logs,
                "affiliates": affiliates_list
            })
            return

        if path == "/api/bank-config":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT value FROM app_state WHERE key = 'bank_config'")
                row = c.fetchone()
                bank_cfg = json.loads(row[0]) if row else DEFAULT_BANK_CONFIG
                conn.close()
            self._send_json(bank_cfg)
            return

        if path == "/api/deposits":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM deposits ORDER BY created_at DESC LIMIT 50")
                deps = [{
                    "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                    "amount": r["amount"], "method": r["method"], "utr": r["utr"],
                    "time": r["time_str"], "status": r["status"], "reason": r["reason"]
                } for r in c.fetchall()]
                conn.close()
            self._send_json(deps)
            return

        if path == "/api/withdrawals":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM withdrawals ORDER BY created_at DESC LIMIT 50")
                wds = [{
                    "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                    "amount": r["amount"], "upiId": r["upi_id"], "bankName": r["bank_name"],
                    "accNo": r["acc_no"], "ifsc": r["ifsc"], "bankingName": r["banking_name"],
                    "destination": r["destination"], "time": r["time_str"], "status": r["status"],
                    "reason": r["reason"]
                } for r in c.fetchall()]
                conn.close()
            self._send_json(wds)
            return

        if path == "/api/admin/draw-override":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT code, manual_override_num, manual_override_period FROM markets WHERE manual_override_num IS NOT NULL")
                rows = c.fetchall()
                overrides = {}
                for r in rows:
                    overrides[r["code"]] = {
                        "market": r["code"],
                        "number": r["manual_override_num"],
                        "period": r["manual_override_period"],
                        "mode": "MANUAL"
                    }
                conn.close()
            self._send_json(overrides)
            return

        if path == "/api/admin/audit-logs":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM admin_audit_logs ORDER BY created_at DESC LIMIT 100")
                logs = [{
                    "id": r["id"], "actor": r["actor"], "action": r["action"],
                    "entity": r["entity"], "desc": r["desc"], "time": r["created_at"]
                } for r in c.fetchall()]
                conn.close()
            self._send_json(logs)
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        now_ms = int(time.time() * 1000)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 1. ATOMIC BET PLACEMENT WITH STRICT 30-SECOND LOCK REJECTION
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/bets/place":
            uid = str(payload.get("userId", "USR-1001")).strip()
            m_code = str(payload.get("market", "MIAMI")).upper().strip()
            amount = float(payload.get("amount", 0.0))
            b_type = str(payload.get("type", "COLOR")).upper().strip()
            target = str(payload.get("target", "GREEN")).upper().strip()
            mult = float(payload.get("mult", 2.0))

            if m_code not in MARKET_KEYS:
                self._send_json({ "success": False, "error": f"Invalid market {m_code}" }, status=400)
                return

            if amount < 1.0:
                self._send_json({ "success": False, "error": "Minimum bet amount is ₹1.00" }, status=400)
                return

            # Check authoritative round & lock status
            auth = calculate_authoritative_round(m_code, now_ms)
            if auth["is_betting_locked"] or auth["remaining_seconds"] <= LOCK_CUTOFF_SEC:
                self._send_json({
                    "success": False,
                    "error": "BETTING LOCKED: Betting is locked for the current round (last 30 seconds). Bet rejected.",
                    "remainingSeconds": auth["remaining_seconds"]
                }, status=400)
                return

            period = auth["period"]
            round_id = auth["round_id"]

            with db_lock:
                conn = get_db()
                c = conn.cursor()

                # 1. Validate user and balance
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                user = c.fetchone()
                if not user:
                    conn.close()
                    self._send_json({ "success": False, "error": "User account not found" }, status=404)
                    return

                if user["status"] == "BLOCKED":
                    conn.close()
                    self._send_json({ "success": False, "error": "Account is blocked by Admin" }, status=403)
                    return

                curr_bal = float(user["balance"])
                if curr_bal < amount:
                    conn.close()
                    self._send_json({ "success": False, "error": "Insufficient wallet balance! Please deposit." }, status=400)
                    return

                # 2. Atomic Balance Deduction
                new_bal = round(curr_bal - amount, 2)
                c.execute("UPDATE users SET balance = ?, bets_count = bets_count + 1 WHERE id = ?", (new_bal, uid))

                # 3. Create Bet Record
                bet_id = f"BET-{int(now_ms)}-{random.randint(1000, 9999)}"
                potential_payout = round(amount * mult, 2)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                c.execute("""
                    INSERT INTO bets (
                        bet_id, user_id, user_name, market, round_id, period,
                        amount, prediction_type, prediction_target, multiplier,
                        potential_payout, status, result_text, win_amount, loss_amount,
                        created_at, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 'Awaiting Draw', 0.0, 0.0, ?, ?)
                """, (
                    bet_id, uid, user["name"], m_code, round_id, period,
                    amount, b_type, target, mult, potential_payout, now_str, now_ms
                ))

                # 4. Create Ledger Transaction
                tx_id = f"TX-BET-{int(now_ms)}-{random.randint(100, 999)}"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                    VALUES (?, ?, 'BET', ?, ?, ?, ?, ?, 'COMPLETED', ?)
                """, (tx_id, uid, f"Bet on {m_code} #{period}", f"Target {target} ({mult}X)", -amount, curr_bal, new_bal, now_ms))

                # 5. Credit Level-1 Refer & Earn Commission if user has sponsor
                sponsor_id = user["referred_by"] if "referred_by" in user.keys() else None
                if sponsor_id:
                    c.execute("SELECT id, name, balance FROM users WHERE id = ?", (sponsor_id,))
                    sp = c.fetchone()
                    if sp:
                        comm_rate = 0.01
                        comm_amt = round(amount * comm_rate, 2)
                        if comm_amt > 0:
                            sp_bal = float(sp["balance"])
                            sp_new = round(sp_bal + comm_amt, 2)
                            c.execute("UPDATE users SET balance = ? WHERE id = ?", (sp_new, sp["id"]))
                            rc_id = f"REF-{int(now_ms)}-{random.randint(100, 999)}"
                            c.execute("""
                                INSERT INTO referral_commissions (id, beneficiary_user_id, source_user_id, source_user_name, source_bet_id, level, rate, eligible_amount, commission_amount, status, created_at_ms)
                                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'SETTLED', ?)
                            """, (rc_id, sp["id"], uid, user["name"], bet_id, comm_rate, amount, comm_amt, now_ms))
                            rtx_id = f"TX-REF-{int(now_ms)}-{random.randint(100, 999)}"
                            c.execute("""
                                INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                                VALUES (?, ?, 'REFERRAL_COMMISSION', ?, ?, ?, ?, ?, 'COMPLETED', ?)
                            """, (rtx_id, sp["id"], "Tier 1 Refer & Earn Reward", f"From {user['name']} ({m_code} Bet ₹{amount:.2f})", comm_amt, sp_bal, sp_new, now_ms))

                _, sse_ev = bump_state_version(conn, "bet_placed", {"userId": uid, "market": m_code, "period": period, "betId": bet_id})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            created_bet = {
                "id": bet_id,
                "userId": uid,
                "userName": user["name"],
                "marketId": m_code,
                "marketName": f"{m_code} MARKET",
                "roundId": round_id,
                "period": period,
                "amount": amount,
                "type": b_type,
                "target": target,
                "mult": mult,
                "potentialPayout": potential_payout,
                "status": "PENDING",
                "result": "Awaiting Draw",
                "time": now_str
            }

            self._send_json({
                "success": True,
                "message": f"Bet placed successfully: ₹{amount:.2f} on {target}",
                "bet": created_bet,
                "newBalance": new_bal
            })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 2. BET CANCELLATION / REFUND (ONLY ALLOWED BEFORE 30s LOCK)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/bets/cancel":
            bet_id = str(payload.get("betId", "")).strip()
            uid = str(payload.get("userId", "")).strip()

            with db_lock:
                conn = get_db()
                c = conn.cursor()

                c.execute("SELECT * FROM bets WHERE bet_id = ? AND user_id = ?", (bet_id, uid))
                bet = c.fetchone()
                if not bet:
                    conn.close()
                    self._send_json({ "success": False, "error": "Bet not found" }, status=404)
                    return

                if bet["status"] != "PENDING":
                    conn.close()
                    self._send_json({ "success": False, "error": f"Cannot cancel bet in {bet['status']} status" }, status=400)
                    return

                # Check if current market round is locked
                auth = calculate_authoritative_round(bet["market"], now_ms)
                if auth["is_betting_locked"] or auth["period"] != bet["period"]:
                    conn.close()
                    self._send_json({ "success": False, "error": "Cannot cancel bet: Round is already locked or finished!" }, status=400)
                    return

                # Refund user balance
                refund_amt = bet["amount"]
                c.execute("SELECT balance FROM users WHERE id = ?", (uid,))
                curr_bal = c.fetchone()["balance"]
                new_bal = round(curr_bal + refund_amt, 2)
                c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, uid))

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("""
                    UPDATE bets
                    SET status = 'CANCELLED', result_text = 'Cancelled & Refunded', win_amount = 0.0, loss_amount = 0.0, settled_at = ?
                    WHERE bet_id = ?
                """, (now_str, bet_id))

                tx_id = f"TX-REF-{int(now_ms)}-{random.randint(100, 999)}"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                    VALUES (?, ?, 'REFUND', ?, ?, ?, ?, ?, 'COMPLETED', ?)
                """, (tx_id, uid, f"Refund {bet['market']} #{bet['period']}", f"Target {bet['prediction_target']} Cancelled", refund_amt, curr_bal, new_bal, now_ms))

                _, sse_ev = bump_state_version(conn, "bet_cancelled", {"userId": uid, "betId": bet_id})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({
                "success": True,
                "message": f"Bet {bet_id} cancelled and ₹{refund_amt:.2f} refunded to your wallet.",
                "newBalance": new_bal
            })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 3. ADMIN RESULT MANUAL DECLARATION & OVERRIDES
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/admin/draw-override":
            m_code = str(payload.get("market", "MIAMI")).upper().strip()
            mode = str(payload.get("mode", "MANUAL")).upper().strip()
            period = str(payload.get("period", "")).strip()

            with db_lock:
                conn = get_db()
                c = conn.cursor()

                if mode == "AUTO" or payload.get("number") is None:
                    c.execute("UPDATE markets SET manual_override_num = NULL, manual_override_period = NULL WHERE code = ?", (m_code,))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'DRAW_MODE_AUTO', ?, 'Switched market to automatic random provably fair draw')
                    """, (m_code,))
                else:
                    num = int(payload.get("number", 0))
                    num = max(0, min(9, num))
                    c.execute("UPDATE markets SET manual_override_num = ?, manual_override_period = ? WHERE code = ?", (num, period if period else None, m_code))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'SET_MANUAL_DRAW', ?, ?)
                    """, (f"{m_code} #{period}", f"Scheduled winning number {num} for next declaration"))

                _, sse_ev = bump_state_version(conn, "draw_override", {"market": m_code, "mode": mode})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({ "success": True, "message": f"Override updated for {m_code}" })
            return

        if path == "/api/admin/declare-result" or path == "/api/results":
            m_code = str(payload.get("market", "MIAMI")).upper().strip()
            period = str(payload.get("period", "")).strip()
            if not period:
                auth = calculate_authoritative_round(m_code, now_ms)
                period = auth["period"]

            num = int(payload.get("number", 0))
            num = max(0, min(9, num))
            round_id = f"RND_{m_code}_{period}"

            with db_lock:
                conn = get_db()
                settle_round_in_db(conn, m_code, round_id, period, num, "MANUAL_ADMIN", "ADMIN_PANEL")
                c = conn.cursor()
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'FORCE_DECLARE_RESULT', ?, ?)
                """, (f"{m_code} #{period}", f"Officially finalized outcome: Number {num}"))
                _, sse_ev = bump_state_version(conn, "result_declared", {"market": m_code, "period": period, "number": num})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({ "success": True, "message": f"Result {num} declared and settled for {m_code} #{period}" })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4. USER REGISTRATION, BALANCE ADJUSTMENT & STATUS
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/users/register":
            uid = str(payload.get("id") or payload.get("userId") or f"USR-{random.randint(2000, 9999)}").strip()
            name = str(payload.get("name") or payload.get("username") or "").strip()
            raw_phone = str(payload.get("phone") or "").strip()
            digits_phone = "".join(ch for ch in raw_phone if ch.isdigit())
            norm_phone = digits_phone[-10:] if len(digits_phone) >= 10 else digits_phone
            formatted_phone = f"+91{norm_phone}" if len(norm_phone) == 10 else raw_phone
            email = str(payload.get("email") or "").strip()
            raw_password = str(payload.get("password") or "").strip()
            pw_hash_in = str(payload.get("passwordHash") or "").strip()
            bal = float(payload.get("balance", 500.00))
            ref_code = str(payload.get("referralCode") or f"{(name[:4] or 'CK').upper()}{random.randint(100, 999)}").strip().upper()
            ref_by_code = str(payload.get("referredBy") or "").strip().upper()

            if len(name) < 3:
                self._send_json({ "success": False, "error": "Username must be at least 3 characters" }, status=400)
                return
            if not payload.get("id") and len(norm_phone) < 10:
                self._send_json({ "success": False, "error": "Please enter a valid 10-digit mobile number" }, status=400)
                return
            if not payload.get("id") and len(raw_password) < 4 and not pw_hash_in:
                self._send_json({ "success": False, "error": "Password must be at least 4 characters" }, status=400)
                return

            pw_hash = pw_hash_in or hashlib.sha256((raw_password or "password123").encode("utf-8")).hexdigest()
            if not email:
                email = f"{name.lower().replace(' ', '_')}@colourking.in"

            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT id FROM users WHERE LOWER(name) = LOWER(?) AND id != ?", (name, uid))
                if c.fetchone():
                    conn.close()
                    self._send_json({ "success": False, "error": "Username already exists. Please choose another." }, status=409)
                    return

                if len(norm_phone) == 10:
                    c.execute("SELECT id, phone FROM users WHERE id != ?", (uid,))
                    for pr in c.fetchall():
                        existing_digits = "".join(ch for ch in str(pr["phone"] or "") if ch.isdigit())
                        if existing_digits[-10:] == norm_phone:
                            conn.close()
                            self._send_json({ "success": False, "error": "Mobile number already registered. Please login." }, status=409)
                            return

                referred_by_uid = None
                if ref_by_code:
                    c.execute("SELECT id FROM users WHERE UPPER(referral_code) = ? OR UPPER(id) = ?", (ref_by_code, ref_by_code))
                    sp = c.fetchone()
                    if sp:
                        referred_by_uid = sp["id"]

                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                existing = c.fetchone()
                if not existing:
                    c.execute("""
                        INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash)
                        VALUES (?, ?, ?, ?, ?, ?, 0.0, 0, 'ACTIVE', ?, ?, ?)
                    """, (uid, name, formatted_phone, email, bal, bal, ref_code, referred_by_uid, pw_hash))
                    c.execute("""
                        INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                        VALUES (?, ?, 'DEPOSIT', 'New Player Sign-Up Bonus', ?, ?, 0.0, ?, 'SUCCESS', ?)
                    """, (f"TX-BONUS-{uid}", uid, f"Welcome Credit ({ref_code})", bal, bal, now_ms))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('System', 'USER_REGISTERED', ?, ?)
                    """, (uid, f"Registered user {name} (Bal ₹{bal:.2f})"))
                else:
                    c.execute("""
                        UPDATE users
                        SET name = ?,
                            phone = COALESCE(NULLIF(?, ''), phone),
                            email = COALESCE(NULLIF(?, ''), email),
                            password_hash = COALESCE(NULLIF(?, ''), password_hash)
                        WHERE id = ?
                    """, (name, formatted_phone, email, pw_hash, uid))
                _, sse_ev = bump_state_version(conn, "user_registered", {"userId": uid, "name": name})
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({
                "success": True,
                "user": {
                    "id": u["id"], "name": u["name"], "phone": u["phone"], "email": u["email"],
                    "balance": u["balance"], "status": u["status"],
                    "referralCode": u["referral_code"] if "referral_code" in u.keys() else ref_code
                }
            })
            return

        if path == "/api/users/login":
            identifier = str(payload.get("identifier") or payload.get("username") or "").strip()
            raw_password = str(payload.get("password") or "").strip()
            if not identifier:
                self._send_json({ "success": False, "error": "Please enter your mobile number or username" }, status=400)
                return
            if not raw_password:
                self._send_json({ "success": False, "error": "Please enter your password" }, status=400)
                return

            ident_digits = "".join(ch for ch in identifier if ch.isdigit())
            ident_last10 = ident_digits[-10:] if len(ident_digits) >= 10 else ""
            pw_hash_input = hashlib.sha256(raw_password.encode("utf-8")).hexdigest()

            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("""
                    SELECT * FROM users
                    WHERE UPPER(id) = UPPER(?) OR LOWER(name) = LOWER(?) OR LOWER(email) = LOWER(?)
                    LIMIT 1
                """, (identifier, identifier, identifier))
                u = c.fetchone()
                if not u and ident_last10:
                    c.execute("SELECT * FROM users")
                    for row in c.fetchall():
                        r_digits = "".join(ch for ch in str(row["phone"] or "") if ch.isdigit())
                        if len(r_digits) >= 10 and r_digits[-10:] == ident_last10:
                            u = row
                            break
                conn.close()

            if not u:
                self._send_json({ "success": False, "error": "User not found. Please register a new account." }, status=404)
                return

            stored_hash = (u["password_hash"] if "password_hash" in u.keys() else "") or ""
            is_valid = (stored_hash == pw_hash_input) or (not stored_hash and raw_password == "password123")
            if not is_valid:
                self._send_json({ "success": False, "error": "Incorrect password. Please try again." }, status=401)
                return

            self._send_json({
                "success": True,
                "user": {
                    "id": u["id"],
                    "name": u["name"],
                    "phone": u["phone"],
                    "email": u["email"],
                    "balance": u["balance"],
                    "status": u["status"],
                    "referralCode": u["referral_code"] if "referral_code" in u.keys() else ""
                }
            })
            return

        if path == "/api/users/change-password":
            uid = str(payload.get("userId") or "").strip()
            new_pw = str(payload.get("newPassword") or "").strip()
            if not uid or len(new_pw) < 4:
                self._send_json({ "success": False, "error": "Password must be at least 4 characters" }, status=400)
                return
            new_hash = hashlib.sha256(new_pw.encode("utf-8")).hexdigest()
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, uid))
                conn.commit()
                conn.close()
            self._send_json({ "success": True, "message": "Password updated successfully" })
            return

        if path == "/api/user/adjust":
            uid = payload.get("userId")
            adj_type = payload.get("type", "CREDIT")
            amount = float(payload.get("amount", 0.0))
            reason = str(payload.get("reason", f"Admin {adj_type}")).strip()

            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                user = c.fetchone()
                if not user:
                    conn.close()
                    self._send_json({ "success": False, "error": "User not found" }, status=404)
                    return

                curr_bal = float(user["balance"])
                if adj_type == "CREDIT":
                    new_bal = round(curr_bal + amount, 2)
                else:
                    new_bal = round(max(0.0, curr_bal - amount), 2)

                c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, uid))
                tx_id = f"TX-ADJ-{int(now_ms)}-{random.randint(100, 999)}"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                    VALUES (?, ?, 'ADJUSTMENT', 'Admin Wallet Adjustment', ?, ?, ?, ?, 'COMPLETED', ?)
                """, (tx_id, uid, reason or f"Admin {adj_type}", amount if adj_type == "CREDIT" else -amount, curr_bal, new_bal, now_ms))

                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'USER_BALANCE_ADJUST', ?, ?)
                """, (uid, f"{adj_type} ₹{amount:.2f} -> New balance ₹{new_bal:.2f} ({reason})"))

                _, sse_ev = bump_state_version(conn, "balance_adjusted", {"userId": uid, "balance": new_bal, "type": adj_type, "amount": amount})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({ "success": True, "userId": uid, "balance": new_bal })
            return

        if path == "/api/user/status":
            uid = payload.get("userId")
            new_status = str(payload.get("status", "ACTIVE")).upper().strip()
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, uid))
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'USER_STATUS_CHANGE', ?, ?)
                """, (uid, f"Status updated to {new_status}"))
                _, sse_ev = bump_state_version(conn, "user_status_changed", {"userId": uid, "status": new_status})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "userId": uid, "status": new_status })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 5. DEPOSITS & WITHDRAWALS LIFECYCLE
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/deposits":
            amount = float(payload.get("amount", 0.0))
            utr = str(payload.get("utr", "")).strip()
            method = str(payload.get("method", "UPI"))
            uid = payload.get("userId", "USR-1001")
            uname = payload.get("userName", "Rahul_Player")

            dep_id = f"DEP-{datetime.now().strftime('%H%M%S')}-{random.randint(10, 99)}"
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT status FROM users WHERE id = ?", (uid,))
                ucheck = c.fetchone()
                if ucheck and ucheck["status"] == "BLOCKED":
                    conn.close()
                    self._send_json({ "success": False, "error": "Account is blocked by Admin" }, status=403)
                    return

                c.execute("""
                    INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status, created_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?, 'Just now', 'IN PROCESS', ?)
                """, (dep_id, uid, uname, amount, method, utr, now_ms))
                _, sse_ev = bump_state_version(conn, "deposit_requested", {"userId": uid, "depositId": dep_id, "amount": amount})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({ "success": True, "deposit": { "id": dep_id, "amount": amount, "utr": utr, "status": "IN PROCESS" } })
            return

        if path == "/api/deposits/approve":
            dep_id = payload.get("depositId")
            affected_uid = None
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM deposits WHERE id = ?", (dep_id,))
                d = c.fetchone()
                if d and d["status"] != "SUCCESS":
                    c.execute("UPDATE deposits SET status = 'SUCCESS' WHERE id = ?", (dep_id,))
                    uid = d["user_id"]
                    affected_uid = uid
                    amt = float(d["amount"])
                    c.execute("UPDATE users SET balance = balance + ?, total_deposit = total_deposit + ? WHERE id = ?", (amt, amt, uid))
                    c.execute("SELECT balance FROM users WHERE id = ?", (uid,))
                    curr_bal = c.fetchone()["balance"]
                    tx_id = f"TX-DEP-{int(now_ms)}-{random.randint(100, 999)}"
                    c.execute("""
                        INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                        VALUES (?, ?, 'DEPOSIT', 'Approved Deposit', ?, ?, ?, ?, 'COMPLETED', ?)
                    """, (tx_id, uid, f"UTR {d['utr']}", amt, curr_bal - amt, curr_bal, now_ms))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'DEPOSIT_APPROVE', ?, ?)
                    """, (dep_id, f"Approved ₹{amt:.2f} for {uid}"))
                _, sse_ev = bump_state_version(conn, "deposit_approved", {"depositId": dep_id, "userId": affected_uid})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True })
            return

        if path == "/api/deposits/reject":
            dep_id = payload.get("depositId")
            reason = payload.get("reason", "Verification failed")
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT user_id FROM deposits WHERE id = ?", (dep_id,))
                d = c.fetchone()
                affected_uid = d["user_id"] if d else None
                c.execute("UPDATE deposits SET status = 'FAIL', reason = ? WHERE id = ?", (reason, dep_id))
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'DEPOSIT_REJECT', ?, ?)
                """, (dep_id, f"Rejected: {reason}"))
                _, sse_ev = bump_state_version(conn, "deposit_rejected", {"depositId": dep_id, "userId": affected_uid, "reason": reason})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True })
            return

        if path == "/api/withdrawals":
            amount = float(payload.get("amount", 0.0))
            upi_id = str(payload.get("upiId", "")).strip()
            bank_name = str(payload.get("bankName", "")).strip()
            acc_no = str(payload.get("accNo", "")).strip()
            ifsc = str(payload.get("ifsc", "")).strip().upper()
            banking_name = str(payload.get("bankingName", "")).strip()
            uid = payload.get("userId", "USR-1001")
            uname = payload.get("userName", "Rahul_Player")

            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT balance, status FROM users WHERE id = ?", (uid,))
                urow = c.fetchone()
                if urow and urow["status"] == "BLOCKED":
                    conn.close()
                    self._send_json({ "success": False, "error": "Account is blocked by Admin" }, status=403)
                    return
                if not urow or urow["balance"] < amount:
                    conn.close()
                    self._send_json({ "success": False, "error": "Insufficient balance for withdrawal" }, status=400)
                    return

                new_bal = round(urow["balance"] - amount, 2)
                c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, uid))

                wd_id = f"WD-{datetime.now().strftime('%H%M%S')}-{random.randint(10, 99)}"
                destination = f"{banking_name} • {bank_name} (A/C: {acc_no}, IFSC: {ifsc}) • UPI: {upi_id}"
                c.execute("""
                    INSERT INTO withdrawals (id, user_id, user_name, amount, upi_id, bank_name, acc_no, ifsc, banking_name, destination, time_str, status, created_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Just now', 'IN PROCESS', ?)
                """, (wd_id, uid, uname, amount, upi_id, bank_name, acc_no, ifsc, banking_name, destination, now_ms))

                tx_id = f"TX-WD-{int(now_ms)}-{random.randint(100, 999)}"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                    VALUES (?, ?, 'WITHDRAWAL', 'Withdrawal Request', ?, ?, ?, ?, 'PENDING', ?)
                """, (tx_id, uid, destination, -amount, urow["balance"], new_bal, now_ms))

                _, sse_ev = bump_state_version(conn, "withdrawal_requested", {"userId": uid, "withdrawalId": wd_id, "amount": amount})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({ "success": True, "withdrawalId": wd_id, "newBalance": new_bal })
            return

        if path == "/api/withdrawals/approve":
            wd_id = payload.get("withdrawalId")
            affected_uid = None
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM withdrawals WHERE id = ?", (wd_id,))
                w = c.fetchone()
                if w and w["status"] != "SUCCESS":
                    affected_uid = w["user_id"]
                    c.execute("UPDATE withdrawals SET status = 'SUCCESS' WHERE id = ?", (wd_id,))
                    c.execute("UPDATE users SET total_withdraw = total_withdraw + ? WHERE id = ?", (w["amount"], w["user_id"]))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'WITHDRAWAL_APPROVE', ?, ?)
                    """, (wd_id, f"Approved ₹{w['amount']:.2f} for {w['user_id']}"))
                _, sse_ev = bump_state_version(conn, "withdrawal_approved", {"withdrawalId": wd_id, "userId": affected_uid})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True })
            return

        if path == "/api/withdrawals/reject":
            wd_id = payload.get("withdrawalId")
            reason = payload.get("reason", "Bank details mismatch")
            affected_uid = None
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM withdrawals WHERE id = ?", (wd_id,))
                w = c.fetchone()
                if w and w["status"] != "FAIL":
                    affected_uid = w["user_id"]
                    c.execute("UPDATE withdrawals SET status = 'FAIL', reason = ? WHERE id = ?", (reason, wd_id))
                    # Refund balance back to user
                    c.execute("SELECT balance FROM users WHERE id = ?", (w["user_id"],))
                    urow = c.fetchone()
                    curr_bal = float(urow["balance"]) if urow else 0.0
                    new_bal = round(curr_bal + float(w["amount"]), 2)
                    c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, w["user_id"]))
                    tx_id = f"TX-WDREF-{int(now_ms)}-{random.randint(100, 999)}"
                    c.execute("""
                        INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                        VALUES (?, ?, 'WITHDRAWAL_REFUND', 'Withdrawal Rejected Refund', ?, ?, ?, ?, 'COMPLETED', ?)
                    """, (tx_id, w["user_id"], f"{wd_id}: {reason}", float(w["amount"]), curr_bal, new_bal, now_ms))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'WITHDRAWAL_REJECT', ?, ?)
                    """, (wd_id, f"Rejected: {reason} (Refunded ₹{w['amount']:.2f})"))
                _, sse_ev = bump_state_version(conn, "withdrawal_rejected", {"withdrawalId": wd_id, "userId": affected_uid, "reason": reason})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True })
            return

        if path == "/api/bank-config":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES ('bank_config', ?, CURRENT_TIMESTAMP)", (json.dumps(payload),))
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'BANK_CONFIG_UPDATE', 'PAYMENT_GATEWAYS', ?)
                """, (f"Updated Bank {payload.get('bankName', '')} / UPI {payload.get('upiId', '')}",))
                _, sse_ev = bump_state_version(conn, "bank_config_updated", {"upiId": payload.get("upiId")})
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "bank_config": payload })
            return

        if path == "/api/admin/sync-state":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                if isinstance(payload.get("bank_config"), dict):
                    c.execute("INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES ('bank_config', ?, CURRENT_TIMESTAMP)", (json.dumps(payload["bank_config"]),))
                if isinstance(payload.get("platform_settings"), dict):
                    c.execute("INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES ('platform_settings', ?, CURRENT_TIMESTAMP)", (json.dumps(payload["platform_settings"]),))
                if isinstance(payload.get("users"), list):
                    for u in payload["users"]:
                        uid_u = str(u.get("id") or "").strip()
                        if not uid_u:
                            continue
                        c.execute("SELECT id FROM users WHERE id = ?", (uid_u,))
                        if not c.fetchone():
                            c.execute("""
                                INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                uid_u, str(u.get("name") or uid_u), u.get("phone"), u.get("email"),
                                float(u.get("balance", 0.0)), float(u.get("totalDeposit", 0.0)),
                                float(u.get("totalWithdraw", 0.0)), int(u.get("betsCount", 0)),
                                str(u.get("status") or "ACTIVE")
                            ))
                if isinstance(payload.get("deposits"), list):
                    for d in payload["deposits"]:
                        did = str(d.get("id") or "").strip()
                        if not did:
                            continue
                        c.execute("SELECT id FROM deposits WHERE id = ?", (did,))
                        if not c.fetchone():
                            c.execute("""
                                INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status, reason, created_at_ms)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                did, str(d.get("userId") or "USR-1001"), str(d.get("userName") or "Player"),
                                float(d.get("amount", 0.0)), str(d.get("method") or "UPI"),
                                str(d.get("utr") or ""), str(d.get("time") or "Just now"),
                                str(d.get("status") or "IN PROCESS"), d.get("reason"), now_ms
                            ))
                if isinstance(payload.get("withdrawals"), list):
                    for w in payload["withdrawals"]:
                        wid = str(w.get("id") or "").strip()
                        if not wid:
                            continue
                        c.execute("SELECT id FROM withdrawals WHERE id = ?", (wid,))
                        if not c.fetchone():
                            c.execute("""
                                INSERT INTO withdrawals (id, user_id, user_name, amount, upi_id, bank_name, acc_no, ifsc, banking_name, destination, time_str, status, reason, created_at_ms)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                wid, str(w.get("userId") or "USR-1001"), str(w.get("userName") or "Player"),
                                float(w.get("amount", 0.0)), w.get("upiId"), w.get("bankName"),
                                w.get("accNo"), w.get("ifsc"), w.get("bankingName"),
                                str(w.get("destination") or ""), str(w.get("time") or "Just now"),
                                str(w.get("status") or "IN PROCESS"), w.get("reason"), now_ms
                            ))
                new_ver, sse_ev = bump_state_version(conn, "admin_sync")
                conn.commit()
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "state_version": new_ver })
            return

        self._send_json({ "error": "Endpoint not found" }, status=404)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    init_database()
    sync_round_lifecycle_once()
    daemon_thread = threading.Thread(target=background_round_lifecycle_daemon, daemon=True)
    daemon_thread.start()

    with ThreadedTCPServer(("", PORT), AppHandler) as httpd:
        print(f"Colour King Master Real-Time Threaded Server running on port {PORT} with SQLite WAL backing.")
        httpd.serve_forever()
