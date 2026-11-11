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
from datetime import datetime, timezone, timedelta

PORT = 3000
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATE_FILE = os.path.join(DIRECTORY, "server_state.json")
DB_FILE = os.path.join(DIRECTORY, "colour_king.db")

db_lock = threading.Lock()

# Supported Markets
MARKET_KEYS = ["MIAMI", "VEGAS", "PARIS", "DUBAI"]
ROUND_DURATION_SEC = 180  # 3 minutes
LOCK_CUTOFF_SEC = 30      # Last 30 seconds locked

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

def init_database():
    os.makedirs(DIRECTORY, exist_ok=True)
    with db_lock:
        conn = get_db()
        c = conn.cursor()

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

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
            c.execute("""
                INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status)
                VALUES ('DEP-88401', 'USR-1001', 'Rahul_Player', 5000.00, 'UPI (GooglePay)', '429188402911', 'Today, 11:24 AM', 'IN PROCESS')
            """)
            c.execute("""
                INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status)
                VALUES ('DEP-88402', 'USR-1002', 'Aman_Trader', 10000.00, 'IMPS SBI NetBanking', '902184716294', 'Today, 11:18 AM', 'IN PROCESS')
            """)

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
    diff_sec = int((ist_now.timestamp() - ref_11am.timestamp()))
    ref_date = ref_11am
    if diff_sec < 0:
        ref_date = ref_11am - timedelta(days=1)
        diff_sec = int((ist_now.timestamp() - ref_date.timestamp()))

    date_str = ref_date.strftime("%Y%m%d")
    round_index = diff_sec // ROUND_DURATION_SEC
    period_num = 221 + round_index
    full_period_id = f"{date_str}{period_num}"

    round_start_sec = ref_date.timestamp() + (round_index * ROUND_DURATION_SEC)
    start_time_ms = int(round_start_sec * 1000)
    lock_time_ms = start_time_ms + ((ROUND_DURATION_SEC - LOCK_CUTOFF_SEC) * 1000)
    end_time_ms = start_time_ms + (ROUND_DURATION_SEC * 1000)

    remaining_sec = max(0, int((end_time_ms - now_ms) / 1000))
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
            tx_id = f"TX-WIN-{int(time.time() * 1000)}-{random.randint(100, 999)}"
            c.execute("""
                INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status)
                VALUES (?, ?, 'WIN', ?, ?, ?, ?, ?, 'COMPLETED')
            """, (tx_id, uid, f"Win {market_code} #{period}", f"Target {target} ({actual_mult}X) Result {winning_number}", win_amount, curr_bal, new_bal))
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

def background_round_lifecycle_daemon():
    """Background engine ensuring continuous 180s countdowns, 30s locks, and atomic settlements across all 4 markets."""
    time.sleep(1)
    while True:
        try:
            now_ms = int(time.time() * 1000)
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
                        m_row = c.fetchone()

                    # 1. Check if previous round was not settled yet
                    c.execute("""
                        SELECT round_id, period FROM rounds
                        WHERE market = ? AND status != 'SETTLED' AND period < ?
                        ORDER BY period ASC LIMIT 5
                    """, (m_code, period))
                    unsettled_past = c.fetchall()
                    for past in unsettled_past:
                        outcome = generate_provably_fair_outcome(m_code, past["period"])
                        settle_round_in_db(conn, m_code, past["round_id"], past["period"], outcome["number"], "AUTO_RECOVERY", "SYSTEM")

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

                    # 3. Update active round state for current period
                    c.execute("""
                        UPDATE markets
                        SET current_round_id = ?, current_period = ?, start_time_ms = ?, lock_time_ms = ?, end_time_ms = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE code = ?
                    """, (round_id, period, auth_round["start_time_ms"], auth_round["lock_time_ms"], auth_round["end_time_ms"], status, m_code))

                    # 4. If round is locked (last 30s), transition all 'PENDING' bets of this period to 'LOCKED'
                    if auth_round["is_betting_locked"]:
                        c.execute("""
                            UPDATE bets
                            SET status = 'LOCKED'
                            WHERE market = ? AND period = ? AND status = 'PENDING'
                        """, (m_code, period))

                    # 5. Ensure current round exists in rounds table
                    c.execute("SELECT round_id FROM rounds WHERE round_id = ?", (round_id,))
                    if not c.fetchone():
                        c.execute("""
                            INSERT INTO rounds (round_id, market, period, start_time_ms, lock_time_ms, end_time_ms, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (round_id, m_code, period, auth_round["start_time_ms"], auth_round["lock_time_ms"], auth_round["end_time_ms"], status))

                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Error in background round lifecycle: {e}")

        time.sleep(1.0)

class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

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

                    # Get latest completed result
                    c.execute("""
                        SELECT period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at
                        FROM rounds
                        WHERE market = ? AND status = 'SETTLED' AND result_number IS NOT NULL
                        ORDER BY period DESC LIMIT 1
                    """, (m_code,))
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
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("""
                    SELECT period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at
                    FROM rounds
                    WHERE market = ? AND status = 'SETTLED' AND result_number IS NOT NULL
                    ORDER BY period DESC LIMIT ?
                """, (m_code, limit))
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

            with db_lock:
                conn = get_db()
                c = conn.cursor()

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

                # All user bets history (limit 100)
                if m_code:
                    c.execute("""
                        SELECT * FROM bets
                        WHERE user_id = ? AND market = ?
                        ORDER BY created_at_ms DESC LIMIT 100
                    """, (uid, m_code))
                else:
                    c.execute("""
                        SELECT * FROM bets
                        WHERE user_id = ?
                        ORDER BY created_at_ms DESC LIMIT 100
                    """, (uid,))
                history_rows = c.fetchall()

                conn.close()

            def row_to_dict(r):
                return {
                    "id": r["bet_id"],
                    "userId": r["user_id"],
                    "userName": r["user_name"],
                    "marketId": r["market"],
                    "marketName": f"{r['market']} MARKET",
                    "roundId": r["round_id"],
                    "period": r["period"],
                    "amount": r["amount"],
                    "type": r["prediction_type"],
                    "target": r["prediction_target"],
                    "mult": r["multiplier"],
                    "potentialPayout": r["potential_payout"],
                    "status": r["status"],
                    "result": r["result_text"],
                    "winAmount": r["win_amount"],
                    "lossAmount": r["loss_amount"],
                    "time": r["created_at"]
                }

            self._send_json({
                "userId": uid,
                "activeBets": [row_to_dict(r) for r in active_rows],
                "betHistory": [row_to_dict(r) for r in history_rows]
            })
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

        # 7. Backward compatible state endpoint
        if path == "/api/state":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM users")
                users_list = {r["id"]: {
                    "id": r["id"], "name": r["name"], "balance": r["balance"],
                    "totalDeposit": r["total_deposit"], "totalWithdraw": r["total_withdraw"],
                    "betsCount": r["bets_count"], "status": r["status"]
                } for r in c.fetchall()}

                c.execute("SELECT * FROM deposits ORDER BY created_at DESC LIMIT 50")
                deposits_list = [{
                    "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                    "amount": r["amount"], "method": r["method"], "utr": r["utr"],
                    "time": r["time_str"], "status": r["status"], "reason": r["reason"]
                } for r in c.fetchall()]

                c.execute("SELECT * FROM withdrawals ORDER BY created_at DESC LIMIT 50")
                withdrawals_list = [{
                    "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                    "amount": r["amount"], "upiId": r["upi_id"], "bankName": r["bank_name"],
                    "accNo": r["acc_no"], "ifsc": r["ifsc"], "bankingName": r["banking_name"],
                    "destination": r["destination"], "time": r["time_str"], "status": r["status"],
                    "reason": r["reason"]
                } for r in c.fetchall()]

                c.execute("SELECT value FROM app_state WHERE key = 'bank_config'")
                bcfg_row = c.fetchone()
                bank_cfg = json.loads(bcfg_row[0]) if bcfg_row else DEFAULT_BANK_CONFIG

                conn.close()

            self._send_json({
                "bank_config": bank_cfg,
                "users": users_list,
                "deposits": deposits_list,
                "withdrawals": withdrawals_list
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
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status)
                    VALUES (?, ?, 'BET', ?, ?, ?, ?, ?, 'COMPLETED')
                """, (tx_id, uid, f"Bet on {m_code}", f"Target {target} ({mult}X)", -amount, curr_bal, new_bal))

                conn.commit()
                conn.close()

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
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status)
                    VALUES (?, ?, 'REFUND', ?, ?, ?, ?, ?, 'COMPLETED')
                """, (tx_id, uid, f"Refund {bet['market']} #{bet['period']}", f"Target {bet['prediction_target']} Cancelled", refund_amt, curr_bal, new_bal))

                conn.commit()
                conn.close()

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

                conn.commit()
                conn.close()

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
                conn.commit()
                conn.close()

            self._send_json({ "success": True, "message": f"Result {num} declared and settled for {m_code} #{period}" })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4. USER BALANCE ADJUSTMENT & STATUS
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/user/adjust":
            uid = payload.get("userId")
            adj_type = payload.get("type", "CREDIT")
            amount = float(payload.get("amount", 0.0))

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
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status)
                    VALUES (?, ?, 'ADJUSTMENT', 'Admin Wallet Adjustment', ?, ?, ?, ?, 'COMPLETED')
                """, (tx_id, uid, f"Admin {adj_type}", amount if adj_type == "CREDIT" else -amount, curr_bal, new_bal))

                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'USER_BALANCE_ADJUST', ?, ?)
                """, (uid, f"{adj_type} ₹{amount:.2f} -> New balance ₹{new_bal:.2f}"))

                conn.commit()
                conn.close()

            self._send_json({ "success": True, "userId": uid, "balance": new_bal })
            return

        if path == "/api/user/status":
            uid = payload.get("userId")
            new_status = payload.get("status", "ACTIVE")
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, uid))
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'USER_STATUS_CHANGE', ?, ?)
                """, (uid, f"Status updated to {new_status}"))
                conn.commit()
                conn.close()
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

            dep_id = f"DEP-{datetime.now().strftime('%H%M%S')}"
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("""
                    INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'Just now', 'IN PROCESS')
                """, (dep_id, uid, uname, amount, method, utr))
                conn.commit()
                conn.close()

            self._send_json({ "success": True, "deposit": { "id": dep_id, "amount": amount, "utr": utr, "status": "IN PROCESS" } })
            return

        if path == "/api/deposits/approve":
            dep_id = payload.get("depositId")
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM deposits WHERE id = ?", (dep_id,))
                d = c.fetchone()
                if d and d["status"] != "SUCCESS":
                    c.execute("UPDATE deposits SET status = 'SUCCESS' WHERE id = ?", (dep_id,))
                    uid = d["user_id"]
                    amt = float(d["amount"])
                    c.execute("UPDATE users SET balance = balance + ?, total_deposit = total_deposit + ? WHERE id = ?", (amt, amt, uid))
                    c.execute("SELECT balance FROM users WHERE id = ?", (uid,))
                    curr_bal = c.fetchone()["balance"]
                    tx_id = f"TX-DEP-{int(now_ms)}-{random.randint(100, 999)}"
                    c.execute("""
                        INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status)
                        VALUES (?, ?, 'DEPOSIT', 'Approved Deposit', ?, ?, ?, ?, 'COMPLETED')
                    """, (tx_id, uid, f"UTR {d['utr']}", amt, curr_bal - amt, curr_bal))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'DEPOSIT_APPROVE', ?, ?)
                    """, (dep_id, f"Approved ₹{amt:.2f} for {uid}"))
                conn.commit()
                conn.close()
            self._send_json({ "success": True })
            return

        if path == "/api/deposits/reject":
            dep_id = payload.get("depositId")
            reason = payload.get("reason", "Verification failed")
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE deposits SET status = 'FAIL', reason = ? WHERE id = ?", (reason, dep_id))
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'DEPOSIT_REJECT', ?, ?)
                """, (dep_id, f"Rejected: {reason}"))
                conn.commit()
                conn.close()
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
                c.execute("SELECT balance FROM users WHERE id = ?", (uid,))
                urow = c.fetchone()
                if not urow or urow["balance"] < amount:
                    conn.close()
                    self._send_json({ "success": False, "error": "Insufficient balance for withdrawal" }, status=400)
                    return

                new_bal = round(urow["balance"] - amount, 2)
                c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, uid))

                wd_id = f"WD-{datetime.now().strftime('%H%M%S')}"
                destination = f"{banking_name} • {bank_name} (A/C: {acc_no}, IFSC: {ifsc}) • UPI: {upi_id}"
                c.execute("""
                    INSERT INTO withdrawals (id, user_id, user_name, amount, upi_id, bank_name, acc_no, ifsc, banking_name, destination, time_str, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Just now', 'IN PROCESS')
                """, (wd_id, uid, uname, amount, upi_id, bank_name, acc_no, ifsc, banking_name, destination))

                tx_id = f"TX-WD-{int(now_ms)}-{random.randint(100, 999)}"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status)
                    VALUES (?, ?, 'WITHDRAWAL', 'Withdrawal Request', ?, ?, ?, ?, 'PENDING')
                """, (tx_id, uid, destination, -amount, urow["balance"], new_bal))

                conn.commit()
                conn.close()

            self._send_json({ "success": True, "withdrawalId": wd_id, "newBalance": new_bal })
            return

        if path == "/api/withdrawals/approve":
            wd_id = payload.get("withdrawalId")
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM withdrawals WHERE id = ?", (wd_id,))
                w = c.fetchone()
                if w and w["status"] != "SUCCESS":
                    c.execute("UPDATE withdrawals SET status = 'SUCCESS' WHERE id = ?", (wd_id,))
                    c.execute("UPDATE users SET total_withdraw = total_withdraw + ? WHERE id = ?", (w["amount"], w["user_id"]))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'WITHDRAWAL_APPROVE', ?, ?)
                    """, (wd_id, f"Approved ₹{w['amount']:.2f} for {w['user_id']}"))
                conn.commit()
                conn.close()
            self._send_json({ "success": True })
            return

        if path == "/api/withdrawals/reject":
            wd_id = payload.get("withdrawalId")
            reason = payload.get("reason", "Bank details mismatch")
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM withdrawals WHERE id = ?", (wd_id,))
                w = c.fetchone()
                if w and w["status"] != "FAIL":
                    c.execute("UPDATE withdrawals SET status = 'FAIL', reason = ? WHERE id = ?", (reason, wd_id))
                    # Refund balance back to user
                    c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (w["amount"], w["user_id"]))
                    c.execute("""
                        INSERT INTO admin_audit_logs (actor, action, entity, desc)
                        VALUES ('ColourPrince', 'WITHDRAWAL_REJECT', ?, ?)
                    """, (wd_id, f"Rejected: {reason} (Refunded ₹{w['amount']:.2f})"))
                conn.commit()
                conn.close()
            self._send_json({ "success": True })
            return

        if path == "/api/bank-config":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('bank_config', ?)", (json.dumps(payload),))
                conn.commit()
                conn.close()
            self._send_json({ "success": True, "bank_config": payload })
            return

        self._send_json({ "error": "Endpoint not found" }, status=404)

if __name__ == "__main__":
    init_database()
    daemon_thread = threading.Thread(target=background_round_lifecycle_daemon, daemon=True)
    daemon_thread.start()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), AppHandler) as httpd:
        print(f"Colour King Master Real-Time Server running on port {PORT} with SQLite database backing.")
        httpd.serve_forever()
