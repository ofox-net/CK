import base64
import csv
import hashlib
import hmac
import io
import json
import math
import mimetypes
import os
import queue
import random
import re
import shutil
import signal
import ssl
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, jsonify, make_response, redirect, request, send_from_directory
from sqlalchemy import func, text

from models import (
    AdminAuditLog,
    AppState,
    Bet,
    Deposit,
    IST_TZ,
    Market,
    ReferralCommission,
    Round,
    SupportMessage,
    SupportTicket,
    Transaction,
    User,
    Withdrawal,
    db,
    format_ist_datetime,
    format_ist_display,
    now_ms,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORY = os.path.join(BASE_DIR, "web")
LEGACY_DB_FILE = os.path.join(DIRECTORY, "colour_king.db")
PORT = int(os.environ.get("PORT", 3000))
RETENTION_DAYS = 90
PBKDF2_ITERATIONS = 100_000
MAX_SUPPORT_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

CK_AUTH_SECRET = (
    os.environ.get("CK_AUTH_SECRET")
    or os.environ.get("SECRET_KEY")
    or "ck-prod-persistent-hmac-v1-2026-anchor"
)

MARKET_KEYS = ["MIAMI", "VEGAS", "PARIS", "DUBAI"]
ROUND_DURATION_SEC = 180
LOCK_CUTOFF_SEC = 30

DEFAULT_PLATFORM_SETTINGS = {
    "maintenanceMode": False,
    "announcementBanner": "",
    "minBet": 10.0,
    "maxBet": 100000.0,
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
    "qrImage": "",
    "instructions": (
        "1. Scan QR code or pay to the UPI ID above.\n"
        "2. Enter the 12-digit UTR reference number in the app.\n"
        "3. Balance will be approved and credited within 2 minutes."
    ),
}

# 6-Level Downline Commission Rates (Tier 1..6)
REFERRAL_TIER_RATES = [
    (1, 0.0100),
    (2, 0.0075),
    (3, 0.0060),
    (4, 0.0050),
    (5, 0.0030),
    (6, 0.0020),
]

DEFAULT_USERS = [
    {"id": "USR-1001", "name": "Rahul_Player", "phone": "+91 98765 43210", "email": "rahul@gmail.com", "balance": 50200.00, "totalDeposit": 75000.00, "totalWithdraw": 28000.00, "betsCount": 142, "status": "ACTIVE", "referralCode": "RAHUL777"},
    {"id": "USR-1002", "name": "Aman_Trader", "phone": "+91 98221 11223", "email": "aman.trade@yahoo.com", "balance": 14500.00, "totalDeposit": 25000.00, "totalWithdraw": 11000.00, "betsCount": 68, "status": "ACTIVE", "referralCode": "AMAN777"},
    {"id": "USR-1003", "name": "Priya_VIP", "phone": "+91 97110 99887", "email": "priya_queen@outlook.com", "balance": 125000.00, "totalDeposit": 200000.00, "totalWithdraw": 95000.00, "betsCount": 310, "status": "ACTIVE", "referralCode": "PRIYA777"},
    {"id": "USR-1004", "name": "Vikram_99", "phone": "+91 96554 33221", "email": "vikram99@gmail.com", "balance": 3200.00, "totalDeposit": 10000.00, "totalWithdraw": 6000.00, "betsCount": 45, "status": "ACTIVE", "referralCode": "VIKRAM777"},
    {"id": "USR-1005", "name": "Suspicious_Bot1", "phone": "+91 91234 56789", "email": "bot_arb@mail.ru", "balance": 0.00, "totalDeposit": 5000.00, "totalWithdraw": 0.00, "betsCount": 8, "status": "BLOCKED", "referralCode": "BOT777"},
    {"id": "USR-1006", "name": "Karan_Pro", "phone": "+91 99887 76655", "email": "karan_pro@gmail.com", "balance": 38400.00, "totalDeposit": 60000.00, "totalWithdraw": 24000.00, "betsCount": 94, "status": "ACTIVE", "referralCode": "KARAN777"},
]


def resolve_sqlite_file() -> str:
    env_db = (os.environ.get("DB_PATH") or os.environ.get("SQLITE_DB_PATH") or "").strip()
    if env_db:
        os.makedirs(os.path.dirname(os.path.abspath(env_db)), exist_ok=True)
        return env_db
    for mount_dir in ("/var/data", "/data"):
        if os.path.isdir(mount_dir) and os.access(mount_dir, os.W_OK):
            candidate = os.path.join(mount_dir, "colour_king.db")
            if not os.path.exists(candidate) and os.path.exists(LEGACY_DB_FILE):
                try:
                    shutil.copy2(LEGACY_DB_FILE, candidate)
                except Exception:
                    pass
            return candidate
    return LEGACY_DB_FILE


SQLITE_DB_FILE = resolve_sqlite_file()
SUPPORT_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(SQLITE_DB_FILE)), "support_uploads")
os.makedirs(SUPPORT_UPLOAD_DIR, exist_ok=True)


def build_sqlalchemy_database_uri() -> tuple[str, dict, bool]:
    raw_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("RENDER_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
        or ""
    ).strip()

    if not raw_url:
        os.makedirs(os.path.dirname(os.path.abspath(SQLITE_DB_FILE)), exist_ok=True)
        return (
            f"sqlite:///{SQLITE_DB_FILE}",
            {"connect_args": {"check_same_thread": False, "timeout": 15}},
            False,
        )

    # Normalize Render postgres:// -> postgresql+pg8000:// (strip sslmode query param for pg8000)
    parsed = urllib.parse.urlparse(raw_url)
    scheme = parsed.scheme.lower()
    if scheme in ("postgres", "postgresql"):
        target_scheme = "postgresql+pg8000"
    elif scheme.startswith("postgresql+"):
        target_scheme = scheme
    else:
        target_scheme = "postgresql+pg8000"

    q_params = urllib.parse.parse_qs(parsed.query or "")
    sslmode = (q_params.pop("sslmode", [""])[0] or "").lower()
    clean_query = urllib.parse.urlencode(q_params, doseq=True)
    normalized_url = urllib.parse.urlunparse((
        target_scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        clean_query,
        parsed.fragment,
    ))

    host = (parsed.hostname or "").lower()
    use_ssl = (host not in ("localhost", "127.0.0.1", "::1")) and (sslmode != "disable")
    engine_opts: dict = {
        "pool_pre_ping": True,
        "pool_recycle": 240,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 20,
    }
    if target_scheme == "postgresql+pg8000" and use_ssl:
        engine_opts["connect_args"] = {"ssl_context": ssl.create_default_context()}

    return normalized_url, engine_opts, True


DATABASE_URI, ENGINE_OPTIONS, IS_POSTGRES = build_sqlalchemy_database_uri()

app = Flask(__name__, static_folder=None)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = ENGINE_OPTIONS
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

db.init_app(app)

db_lock = threading.RLock()
sse_lock = threading.Lock()
sse_subscribers: list[queue.Queue] = []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PASSWORD HASHING & CRYPTO RECOVERY TOKENS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def hash_password_secure(raw_password: str) -> str:
    clean = str(raw_password or "")
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", clean.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password_secure(raw_password: str, stored_hash: str, stored_plain: str = "") -> bool:
    candidate = str(raw_password or "")
    s_hash = str(stored_hash or "").strip()
    s_plain = str(stored_plain or "")
    if s_hash.startswith("pbkdf2_sha256$"):
        parts = s_hash.split("$")
        if len(parts) == 4:
            try:
                iters = int(parts[1])
                salt = parts[2]
                expected_hex = parts[3]
                dk = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"), salt.encode("utf-8"), iters).hex()
                return hmac.compare_digest(dk, expected_hex)
            except Exception:
                return False
    if len(s_hash) == 64:
        cand_sha = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        if hmac.compare_digest(cand_sha, s_hash.lower()):
            return True
    if s_plain != "" and hmac.compare_digest(candidate, s_plain):
        return True
    if not s_hash and not s_plain and candidate == "password123":
        return True
    return False


def _b64u_encode(raw_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


def _b64u_decode(text_str: str) -> bytes:
    pad = "=" * ((4 - len(text_str) % 4) % 4)
    return base64.urlsafe_b64decode((text_str + pad).encode("ascii"))


def build_user_recovery_token(u: User | None) -> str:
    if not u:
        return ""
    payload = {
        "v": 1,
        "id": str(u.id),
        "name": str(u.name),
        "phone": str(u.phone or ""),
        "email": str(u.email or ""),
        "pwh": str(u.password_hash or ""),
        "bal": round(float(u.balance or 0.0), 2),
        "td": round(float(u.total_deposit or 0.0), 2),
        "tw": round(float(u.total_withdraw or 0.0), 2),
        "bc": int(u.bets_count or 0),
        "st": str(u.status or "ACTIVE"),
        "rc": str(u.referral_code or ""),
        "rb": u.referred_by,
        "ts": now_ms(),
    }
    raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64u_encode(raw_json)
    sig = hmac.new(CK_AUTH_SECRET.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"CKT1.{body_b64}.{_b64u_encode(sig)}"


def verify_user_recovery_token(token_str: str):
    if not token_str or not isinstance(token_str, str):
        return None
    parts = token_str.strip().split(".")
    if len(parts) != 3 or parts[0] != "CKT1":
        return None
    body_b64, sig_b64 = parts[1], parts[2]
    try:
        expected_sig = _b64u_encode(
            hmac.new(CK_AUTH_SECRET.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig_b64, expected_sig):
            return None
        payload = json.loads(_b64u_decode(body_b64).decode("utf-8"))
        if not isinstance(payload, dict) or not payload.get("id") or not payload.get("name"):
            return None
        return payload
    except Exception:
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IST CLOCK & TIME HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_ist_now(ms: int | None = None) -> datetime:
    if ms is not None and int(ms) > 0:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).astimezone(IST_TZ)
    return datetime.now(timezone.utc).astimezone(IST_TZ)


def _parse_ts_ms(ts_str, fallback_ms=0) -> int:
    if fallback_ms and int(fallback_ms) > 0:
        return int(fallback_ms)
    if not ts_str:
        return now_ms()
    raw = str(ts_str).strip()
    try:
        if raw.endswith(" IST") or "+05:30" in raw:
            clean = raw[:-4].strip() if raw.endswith(" IST") else raw
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d %b, %I:%M:%S %p", "%d %b %Y, %I:%M:%S %p"):
                try:
                    dt = datetime.strptime(clean, fmt)
                    if "%Y" not in fmt:
                        dt = dt.replace(year=get_ist_now().year)
                    return int(dt.replace(tzinfo=IST_TZ).timestamp() * 1000)
                except ValueError:
                    continue
        if "T" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return now_ms()


def to_ist_display(ts_str=None, ms=0, mode="datetime") -> str:
    epoch_ms = _parse_ts_ms(ts_str, ms)
    if mode == "display":
        return format_ist_display(epoch_ms)
    if mode == "time":
        return get_ist_now(epoch_ms).strftime("%I:%M:%S %p IST")
    if mode == "clock24":
        return get_ist_now(epoch_ms).strftime("%H:%M:%S IST")
    return format_ist_datetime(epoch_ms)


def ist_date_str(ts_str=None, ms=0) -> str:
    return get_ist_now(_parse_ts_ms(ts_str, ms)).strftime("%d %b %Y")


def calculate_authoritative_round(market_code: str, curr_ms: int | None = None) -> dict:
    if curr_ms is None:
        curr_ms = now_ms()
    ist_now = get_ist_now(curr_ms)
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

    remaining_sec = min(ROUND_DURATION_SEC, max(0, math.ceil((end_time_ms - curr_ms) / 1000.0)))
    is_locked = (curr_ms >= lock_time_ms) or (remaining_sec <= LOCK_CUTOFF_SEC)
    if remaining_sec <= 0:
        status = "WAITING_FOR_RESULT"
    elif is_locked:
        status = "BETTING_LOCKED"
    else:
        status = "BETTING_OPEN"

    return {
        "market": market_code,
        "round_id": f"RND_{market_code}_{full_period_id}",
        "period": full_period_id,
        "period_number": period_num,
        "start_time_ms": start_time_ms,
        "lock_time_ms": lock_time_ms,
        "end_time_ms": end_time_ms,
        "remaining_seconds": remaining_sec,
        "is_betting_locked": is_locked,
        "status": status,
    }


def get_period_window_ms_ist(period_str: str) -> tuple[int, int, int]:
    try:
        s = str(period_str or "").strip()
        if len(s) < 11 or not s.isdigit():
            return (0, 0, 0)
        y, m, d, p_num = int(s[0:4]), int(s[4:6]), int(s[6:8]), int(s[8:])
        ref_11am = datetime(y, m, d, 11, 0, 0, tzinfo=IST_TZ)
        round_index = p_num - 221
        start_ms = int((ref_11am.timestamp() + (round_index * ROUND_DURATION_SEC)) * 1000)
        lock_ms = start_ms + ((ROUND_DURATION_SEC - LOCK_CUTOFF_SEC) * 1000)
        end_ms = start_ms + (ROUND_DURATION_SEC * 1000)
        return (start_ms, lock_ms, end_ms)
    except Exception:
        return (0, 0, 0)


def generate_provably_fair_outcome(market_code: str, period: str) -> dict:
    seed_str = f"COLOUR_KING_AVALANCHE_2026_{market_code}_{period}_PROVABLY_FAIR"
    h = 0x811C9DC5
    for ch in seed_str:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    number = h % 10
    is_big = number >= 5
    if number in (1, 3, 7, 9):
        color, col_class = "green", "green"
    elif number in (2, 4, 6, 8):
        color, col_class = "red", "red"
    else:
        color = "violet"
        col_class = "red-violet" if number == 0 else "green-violet"
    return {"number": number, "is_big": 1 if is_big else 0, "color": color, "col_class": col_class}


def normalize_bet_target_num(btype: str, target: str):
    if btype != "NUMBER":
        return None
    t = str(target or "").upper().strip()
    if t.isdigit():
        return int(t)
    m = re.search(r"(\d)", t)
    return int(m.group(1)) if m else None


def _import_sqlite_file_into_sqlalchemy(sqlite_path: str):
    """Non-destructively merges all historical users, bets, deposits, withdrawals, commissions, transactions,
    rounds, support tickets, and app_state from a legacy SQLite snapshot into PostgreSQL ORM tables."""
    import sqlite3
    import zlib
    import tempfile
    if not sqlite_path or not os.path.exists(sqlite_path):
        return 0
    sconn = sqlite3.connect(sqlite_path)
    sconn.row_factory = sqlite3.Row
    migrated = 0
    try:
        cur = sconn.cursor()

        def _tbl_exists(name):
            return cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

        def _merge_rows(tbl, model_cls, pk_col):
            nonlocal migrated
            if not _tbl_exists(tbl):
                return
            valid_cols = {c.name for c in model_cls.__table__.columns}
            for row in cur.execute(f"SELECT * FROM {tbl}").fetchall():
                d = {k: row[k] for k in row.keys() if k in valid_cols}
                pk_val = d.get(pk_col)
                if pk_val is None:
                    continue
                if not db.session.get(model_cls, pk_val):
                    if "created_at" in valid_cols and not d.get("created_at"):
                        d["created_at"] = format_ist_datetime(d.get("created_at_ms") or now_ms())
                    if "created_at_ms" in valid_cols and (d.get("created_at_ms") is None or int(d.get("created_at_ms") or 0) == 0):
                        d["created_at_ms"] = _parse_ts_ms(d.get("created_at"), 0)
                    db.session.add(model_cls(**d))
                    migrated += 1

        _merge_rows("users", User, "id")
        _merge_rows("markets", Market, "code")
        _merge_rows("rounds", Round, "round_id")
        _merge_rows("bets", Bet, "bet_id")
        _merge_rows("transactions", Transaction, "tx_id")
        _merge_rows("deposits", Deposit, "id")
        _merge_rows("withdrawals", Withdrawal, "id")
        _merge_rows("referral_commissions", ReferralCommission, "id")
        _merge_rows("support_tickets", SupportTicket, "ticket_id")
        _merge_rows("support_messages", SupportMessage, "id")
        _merge_rows("app_state", AppState, "key")
        if _tbl_exists("admin_audit_logs") and AdminAuditLog.query.count() == 0:
            valid_cols = {c.name for c in AdminAuditLog.__table__.columns} - {"id"}
            for row in cur.execute("SELECT * FROM admin_audit_logs ORDER BY id ASC").fetchall():
                d = {k: row[k] for k in row.keys() if k in valid_cols}
                if not d.get("created_at"):
                    d["created_at"] = format_ist_datetime()
                if not d.get("created_at_ms"):
                    d["created_at_ms"] = _parse_ts_ms(d.get("created_at"), 0)
                db.session.add(AdminAuditLog(**d))
                migrated += 1
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"[Migration] SQLite import warning: {exc}")
    finally:
        sconn.close()
    return migrated


def _migrate_legacy_postgres_backup():
    """If PostgreSQL has legacy ck_sqlite_backup / ck_users tables from prior server.py versions,
    safely import every historical user, bet, commission, deposit, and withdrawal permanently."""
    import zlib
    import tempfile
    try:
        has_ck_backup = db.session.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'ck_sqlite_backup'")
        ).fetchone()
        if has_ck_backup:
            row = db.session.execute(text("SELECT db_b64 FROM ck_sqlite_backup WHERE id = 1")).fetchone()
            if row and row[0]:
                raw_bytes = zlib.decompress(base64.b64decode(row[0]))
                if raw_bytes.startswith(b"SQLite format 3"):
                    fd, tmp_path = tempfile.mkstemp(prefix="ck_pg_mig_", suffix=".db")
                    os.close(fd)
                    try:
                        with open(tmp_path, "wb") as f:
                            f.write(raw_bytes)
                        migrated_cnt = _import_sqlite_file_into_sqlalchemy(tmp_path)
                        print(f"[Migration] Migrated {migrated_cnt} historical records from ck_sqlite_backup.")
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)

        has_ck_users = db.session.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'ck_users'")
        ).fetchone()
        if has_ck_users:
            rows = db.session.execute(text(
                "SELECT id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash, password_plain, created_at FROM ck_users"
            )).fetchall()
            added_u = 0
            for r in rows:
                if not db.session.get(User, str(r[0])):
                    db.session.add(User(
                        id=str(r[0]), name=r[1] or str(r[0]), phone=r[2] or "", email=r[3] or "",
                        balance=float(r[4] or 0.0), total_deposit=float(r[5] or 0.0), total_withdraw=float(r[6] or 0.0),
                        bets_count=int(r[7] or 0), status=r[8] or "ACTIVE",
                        referral_code=r[9], referred_by=r[10],
                        password_hash=r[11] or "", password_plain=r[12] or "",
                        created_at=r[13] or format_ist_datetime(), created_at_ms=_parse_ts_ms(r[13], 0),
                    ))
                    added_u += 1
            if added_u:
                db.session.commit()
                print(f"[Migration] Restored {added_u} users from ck_users.")
    except Exception as exc:
        db.session.rollback()
        print(f"[Migration] Legacy PG check note: {exc}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SAFE NON-DESTRUCTIVE INITIALIZATION (NEVER db.drop_all())
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def init_database():
    """Creates tables if missing using db.create_all() ONLY. Never calls db.drop_all()."""
    os.makedirs(DIRECTORY, exist_ok=True)
    with app.app_context():
        db.create_all()

        # Non-destructive column check/migration for pre-existing tables
        if not IS_POSTGRES:
            for alter_sql in [
                "ALTER TABLE users ADD COLUMN created_at_ms INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE admin_audit_logs ADD COLUMN created_at_ms INTEGER NOT NULL DEFAULT 0",
            ]:
                try:
                    db.session.execute(text(alter_sql))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        # Auto-migrate any existing data from legacy PostgreSQL backup or local SQLite file
        if IS_POSTGRES:
            _migrate_legacy_postgres_backup()
            if Bet.query.count() == 0 and os.path.exists(SQLITE_DB_FILE):
                _import_sqlite_file_into_sqlalchemy(SQLITE_DB_FILE)

        # Seed default users ONLY if users table is completely empty
        if User.query.count() == 0:
            default_pw_hash = hash_password_secure("password123")
            seed_ms = now_ms()
            for idx, du in enumerate(DEFAULT_USERS):
                u = User(
                    id=du["id"],
                    name=du["name"],
                    phone=du.get("phone") or "",
                    email=du.get("email") or "",
                    balance=du["balance"],
                    total_deposit=du["totalDeposit"],
                    total_withdraw=du["totalWithdraw"],
                    bets_count=du["betsCount"],
                    status=du["status"],
                    referral_code=du["referralCode"],
                    password_hash=default_pw_hash,
                    password_plain="password123",
                    created_at=format_ist_datetime(seed_ms),
                    created_at_ms=seed_ms + idx,
                )
                db.session.add(u)
            db.session.commit()

        # Seed default pending deposits ONLY if deposits table is empty
        if Deposit.query.count() == 0 and User.query.filter_by(id="USR-1001").first():
            seed_ms = now_ms()
            db.session.add(Deposit(
                id="DEP-88401", user_id="USR-1001", user_name="Rahul_Player",
                amount=5000.00, method="UPI (GooglePay)", utr="429188402911",
                time_str=format_ist_display(seed_ms - 6 * 60 * 1000),
                status="IN PROCESS", created_at=format_ist_datetime(seed_ms - 6 * 60 * 1000),
                created_at_ms=seed_ms - 6 * 60 * 1000,
            ))
            db.session.add(Deposit(
                id="DEP-88402", user_id="USR-1002", user_name="Aman_Trader",
                amount=10000.00, method="IMPS SBI NetBanking", utr="902184716294",
                time_str=format_ist_display(seed_ms - 12 * 60 * 1000),
                status="IN PROCESS", created_at=format_ist_datetime(seed_ms - 12 * 60 * 1000),
                created_at_ms=seed_ms - 12 * 60 * 1000,
            ))
            db.session.commit()

        # Ensure app_state defaults exist safely
        defaults = {
            "bank_config": json.dumps(DEFAULT_BANK_CONFIG),
            "platform_settings": json.dumps(DEFAULT_PLATFORM_SETTINGS),
            "state_version": "1",
        }
        changed_state = False
        for k, v in defaults.items():
            if not AppState.query.get(k):
                db.session.add(AppState(key=k, value=v, updated_at=format_ist_datetime()))
                changed_state = True
        if changed_state:
            db.session.commit()


def get_app_state_json(key: str, default_obj):
    row = AppState.query.get(key)
    if row and row.value:
        try:
            return json.loads(row.value)
        except Exception:
            pass
    return default_obj


def set_app_state_value(key: str, value_str: str):
    row = AppState.query.get(key)
    ts = format_ist_datetime()
    if row:
        row.value = value_str
        row.updated_at = ts
    else:
        db.session.add(AppState(key=key, value=value_str, updated_at=ts))


def get_state_version() -> int:
    row = AppState.query.get("state_version")
    try:
        return int(row.value) if row and row.value is not None else 1
    except Exception:
        return 1


def bump_state_version(event_type="state_update", detail=None) -> tuple[int, dict]:
    new_ver = get_state_version() + 1
    set_app_state_value("state_version", str(new_ver))
    return new_ver, {
        "version": new_ver,
        "eventType": event_type,
        "detail": detail or {},
        "serverTimeMs": now_ms(),
    }


def notify_sse_clients(payload: dict):
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


def log_admin_action(actor: str, action: str, entity: str, desc: str):
    db.session.add(AdminAuditLog(
        actor=actor,
        action=action,
        entity=entity,
        desc=desc,
        created_at=format_ist_datetime(),
        created_at_ms=now_ms(),
    ))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ROUND SETTLEMENT & LIFECYCLE (PERSISTENT DB COMMITS)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def settle_round_in_db(market_code: str, round_id: str, period: str, winning_number: int, draw_mode="AUTO_RANDOM", declared_by="SYSTEM"):
    winning_number = max(0, min(9, int(winning_number)))
    is_big = winning_number >= 5
    if winning_number in (1, 3, 7, 9):
        color, col_class = "green", "green"
    elif winning_number in (2, 4, 6, 8):
        color, col_class = "red", "red"
    else:
        color = "violet"
        col_class = "red-violet" if winning_number == 0 else "green-violet"

    p_start_ms, p_lock_ms, p_end_ms = get_period_window_ms_ist(period)
    if draw_mode == "MANUAL_ADMIN":
        eff_end_ms = now_ms()
        now_ts = format_ist_datetime(eff_end_ms)
    else:
        eff_end_ms = p_end_ms if p_end_ms > 0 else now_ms()
        now_ts = format_ist_datetime(eff_end_ms)

    rnd = Round.query.get(round_id)
    if not rnd:
        rnd = Round(
            round_id=round_id,
            market=market_code,
            period=period,
            start_time_ms=p_start_ms,
            lock_time_ms=p_lock_ms,
            end_time_ms=eff_end_ms,
            status="SETTLED",
            result_number=winning_number,
            result_color=color,
            result_col_class=col_class,
            is_big=1 if is_big else 0,
            draw_mode=draw_mode,
            declared_at=now_ts,
            declared_by=declared_by,
        )
        db.session.add(rnd)
    else:
        rnd.start_time_ms = p_start_ms
        rnd.lock_time_ms = p_lock_ms
        rnd.end_time_ms = eff_end_ms
        rnd.status = "SETTLED"
        rnd.result_number = winning_number
        rnd.result_color = color
        rnd.result_col_class = col_class
        rnd.is_big = 1 if is_big else 0
        rnd.draw_mode = draw_mode
        rnd.declared_at = now_ts
        rnd.declared_by = declared_by

    unsettled_bets = Bet.query.filter(
        Bet.market == market_code,
        Bet.period == period,
        Bet.status.in_(["PENDING", "LOCKED"]),
    ).all()

    for b in unsettled_bets:
        amt = float(b.amount or 0.0)
        net_amt_db = float(b.net_amount or 0.0)
        stake_base = net_amt_db if net_amt_db > 0.0 else round(amt - round(amt * 0.03, 2), 2)
        btype = str(b.prediction_type or "").upper().strip()
        target = str(b.prediction_target or "").upper().strip()
        actual_mult = float(b.multiplier or 2.0)

        won = False
        if btype in ("BIG_SMALL", "SIZE"):
            if (target == "BIG" and is_big) or (target == "SMALL" and not is_big):
                won = True
        elif btype == "COLOR":
            if target == "VIOLET" and winning_number in (0, 5):
                won, actual_mult = True, 4.5
            elif target == "GREEN":
                if winning_number in (1, 3, 7, 9):
                    won, actual_mult = True, 2.0
                elif winning_number == 5:
                    won, actual_mult = True, 1.5
            elif target == "RED":
                if winning_number in (2, 4, 6, 8):
                    won, actual_mult = True, 2.0
                elif winning_number == 0:
                    won, actual_mult = True, 1.5
        elif btype == "NUMBER":
            t_num = normalize_bet_target_num(btype, target)
            if t_num is not None and t_num == winning_number:
                won, actual_mult = True, 9.0

        if won:
            win_amount = round(stake_base * actual_mult, 2)
            b.status = "WON"
            b.win_amount = win_amount
            b.loss_amount = 0.0
            b.result_text = f"Won ₹{win_amount:,.2f} (Outcome {winning_number} {color.upper()})"
            b.settled_at = now_ts

            u = User.query.get(b.user_id)
            curr_bal = float(u.balance) if u else 0.0
            new_bal = round(curr_bal + win_amount, 2)
            if u:
                u.balance = new_bal

            win_ms = now_ms()
            db.session.add(Transaction(
                tx_id=f"TX-WIN-{win_ms}-{random.randint(100, 999)}",
                user_id=b.user_id,
                type="WIN",
                title=f"Win {market_code} #{period}",
                ref=f"Target {target} ({actual_mult}X) Result {winning_number}",
                amount=win_amount,
                balance_before=curr_bal,
                balance_after=new_bal,
                status="COMPLETED",
                created_at=format_ist_datetime(win_ms),
                created_at_ms=win_ms,
            ))
        else:
            b.status = "LOST"
            b.win_amount = 0.0
            b.loss_amount = amt
            b.result_text = f"Lost (Outcome {winning_number} {color.upper()})"
            b.settled_at = now_ts

    mkt = Market.query.get(market_code)
    if mkt and (mkt.manual_override_period == period or mkt.manual_override_period is None):
        mkt.manual_override_num = None
        mkt.manual_override_period = None

    db.session.commit()


def sync_round_lifecycle_once():
    curr_ms = now_ms()
    sse_events = []
    with db_lock:
        with app.app_context():
            try:
                for m_code in MARKET_KEYS:
                    auth = calculate_authoritative_round(m_code, curr_ms)
                    period = auth["period"]
                    round_id = auth["round_id"]
                    status = auth["status"]

                    mkt = Market.query.get(m_code)
                    if not mkt:
                        mkt = Market(
                            code=m_code,
                            name=f"{m_code} MARKET",
                            current_round_id=round_id,
                            current_period=period,
                            round_duration_sec=ROUND_DURATION_SEC,
                            lock_cutoff_sec=LOCK_CUTOFF_SEC,
                            start_time_ms=auth["start_time_ms"],
                            lock_time_ms=auth["lock_time_ms"],
                            end_time_ms=auth["end_time_ms"],
                            status=status,
                        )
                        db.session.add(mkt)
                        db.session.flush()

                    # Backfill immediate 50 past rounds if missing
                    prev_p = calculate_authoritative_round(m_code, curr_ms - ROUND_DURATION_SEC * 1000)["period"]
                    has_prev = Round.query.filter_by(market=m_code, period=prev_p, status="SETTLED").first()
                    if not has_prev:
                        for back_i in range(1, 51):
                            p_auth = calculate_authoritative_round(m_code, curr_ms - back_i * ROUND_DURATION_SEC * 1000)
                            if p_auth["period"] == period:
                                continue
                            ex = Round.query.get(p_auth["round_id"])
                            if not ex or ex.status != "SETTLED" or ex.result_number is None:
                                out = generate_provably_fair_outcome(m_code, p_auth["period"])
                                dec_ts = format_ist_datetime(p_auth["end_time_ms"])
                                if not ex:
                                    db.session.add(Round(
                                        round_id=p_auth["round_id"],
                                        market=m_code,
                                        period=p_auth["period"],
                                        start_time_ms=p_auth["start_time_ms"],
                                        lock_time_ms=p_auth["lock_time_ms"],
                                        end_time_ms=p_auth["end_time_ms"],
                                        status="SETTLED",
                                        result_number=out["number"],
                                        result_color=out["color"],
                                        result_col_class=out["col_class"],
                                        is_big=out["is_big"],
                                        draw_mode="AUTO_RANDOM",
                                        declared_at=dec_ts,
                                        declared_by="SYSTEM_SYNC",
                                    ))
                                else:
                                    ex.status = "SETTLED"
                                    ex.result_number = ex.result_number if ex.result_number is not None else out["number"]
                                    ex.result_color = ex.result_color or out["color"]
                                    ex.result_col_class = ex.result_col_class or out["col_class"]
                                    ex.is_big = ex.is_big if ex.is_big is not None else out["is_big"]
                                    ex.declared_at = ex.declared_at or dec_ts

                    # Settle any expired unsettled rounds cleanly
                    unsettled_past = Round.query.filter(
                        Round.market == m_code,
                        Round.status != "SETTLED",
                        Round.period < period,
                    ).order_by(Round.period.asc()).limit(10).all()
                    for past in unsettled_past:
                        out = generate_provably_fair_outcome(m_code, past.period)
                        settle_round_in_db(m_code, past.round_id, past.period, out["number"], "AUTO_RECOVERY", "SYSTEM")
                        _, ev = bump_state_version("round_settled", {"market": m_code, "period": past.period, "number": out["number"]})
                        sse_events.append(ev)

                    # Settle period rollover
                    last_p = mkt.current_period
                    if last_p and last_p != period:
                        if mkt.manual_override_num is not None and (mkt.manual_override_period == last_p or not mkt.manual_override_period):
                            win_num = int(mkt.manual_override_num)
                            d_mode = "MANUAL_ADMIN"
                        else:
                            win_num = generate_provably_fair_outcome(m_code, last_p)["number"]
                            d_mode = "AUTO_RANDOM"
                        settle_round_in_db(m_code, f"RND_{m_code}_{last_p}", last_p, win_num, d_mode, "SYSTEM_DAEMON")
                        _, ev = bump_state_version("round_settled", {"market": m_code, "period": last_p, "number": win_num})
                        sse_events.append(ev)

                    mkt.current_round_id = round_id
                    mkt.current_period = period
                    mkt.start_time_ms = auth["start_time_ms"]
                    mkt.lock_time_ms = auth["lock_time_ms"]
                    mkt.end_time_ms = auth["end_time_ms"]
                    mkt.status = status
                    mkt.updated_at = format_ist_datetime(curr_ms)

                    if auth["is_betting_locked"]:
                        updated_cnt = Bet.query.filter_by(market=m_code, period=period, status="PENDING").update(
                            {"status": "LOCKED"}, synchronize_session=False
                        )
                        if updated_cnt:
                            _, ev = bump_state_version("bets_locked", {"market": m_code, "period": period})
                            sse_events.append(ev)

                    if not Round.query.get(round_id):
                        db.session.add(Round(
                            round_id=round_id,
                            market=m_code,
                            period=period,
                            start_time_ms=auth["start_time_ms"],
                            lock_time_ms=auth["lock_time_ms"],
                            end_time_ms=auth["end_time_ms"],
                            status=status,
                        ))

                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                print(f"[Lifecycle] Sync error: {exc}")

    for ev in sse_events:
        notify_sse_clients(ev)


def background_round_lifecycle_daemon():
    while True:
        try:
            sync_round_lifecycle_once()
        except Exception as exc:
            print(f"[Daemon] Error: {exc}")
        time.sleep(0.5)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AFFILIATES, STATEMENT, LIVE STATS & 24/7 SUPPORT HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def find_user_by_identifier(identifier: str):
    ident = str(identifier or "").strip()
    if not ident:
        return None
    ident_l = ident.lower()
    u = User.query.filter(
        (func.upper(func.trim(User.id)) == ident.upper())
        | (func.lower(func.trim(User.name)) == ident_l)
        | (func.lower(func.trim(User.email)) == ident_l)
        | (func.trim(User.phone) == ident)
    ).first()
    if u:
        return u
    digits = "".join(ch for ch in ident if ch.isdigit())
    last10 = digits[-10:] if len(digits) >= 10 else ""
    if last10:
        for row in User.query.all():
            r_digits = "".join(ch for ch in str(row.phone or "") if ch.isdigit())
            if len(r_digits) >= 10 and r_digits[-10:] == last10:
                return row
    return None


def build_user_affiliates(uid: str):
    root_u = User.query.get(uid)
    if not root_u:
        return None

    ref_code = root_u.referral_code or uid[-6:].upper()
    members = []
    visited = {uid}
    frontier = [uid]
    for tier in range(1, 7):
        if not frontier:
            break
        children = User.query.filter(User.referred_by.in_(frontier)).all()
        next_frontier = []
        for ch in children:
            if ch.id in visited:
                continue
            visited.add(ch.id)
            next_frontier.append(ch.id)
            ch_turnover = float(
                db.session.query(func.coalesce(func.sum(Bet.amount), 0.0))
                .filter(Bet.user_id == ch.id, ~Bet.status.in_(["CANCELLED", "REFUNDED"]))
                .scalar() or 0.0
            )
            ch_comm = float(
                db.session.query(func.coalesce(func.sum(ReferralCommission.commission_amount), 0.0))
                .filter(
                    ReferralCommission.beneficiary_user_id == uid,
                    ReferralCommission.source_user_id == ch.id,
                    ReferralCommission.status != "REVERSED",
                )
                .scalar() or 0.0
            )
            members.append({
                "id": ch.id,
                "name": ch.name,
                "tier": tier,
                "tierLabel": f"Tier {tier} (Direct)" if tier == 1 else f"Tier {tier}",
                "joined": ist_date_str(ch.created_at, ch.created_at_ms or 0),
                "totalDeposit": round(float(ch.total_deposit or 0.0), 2),
                "turnover": round(ch_turnover, 2),
                "commission": round(ch_comm, 2),
                "status": ch.status or "ACTIVE",
            })
        frontier = next_frontier

    # Fetch all non-reversed commissions for this user once for exact L1-L6 breakdown
    all_comm_rows = (
        ReferralCommission.query
        .filter(ReferralCommission.beneficiary_user_id == uid, ReferralCommission.status != "REVERSED")
        .order_by(ReferralCommission.created_at_ms.desc())
        .all()
    )

    level_breakdown = []
    for lvl, rate_val in REFERRAL_TIER_RATES:
        lvl_members = [m for m in members if m["tier"] == lvl]
        lvl_comms = [r for r in all_comm_rows if int(r.level or 1) == lvl]
        lvl_earned = round(sum(float(r.commission_amount or 0.0) for r in lvl_comms), 2)
        lvl_unclaimed = round(sum(float(r.commission_amount or 0.0) for r in lvl_comms if str(r.status or "").upper() in ("UNCLAIMED", "PENDING")), 2)
        lvl_claimed = round(sum(float(r.commission_amount or 0.0) for r in lvl_comms if str(r.status or "").upper() in ("CLAIMED", "SETTLED", "COMPLETED")), 2)
        lvl_turnover = round(sum(m["turnover"] for m in lvl_members), 2)
        if lvl_turnover <= 0 and lvl_comms:
            lvl_turnover = round(sum(float(r.eligible_amount or 0.0) for r in lvl_comms), 2)
        level_breakdown.append({
            "level": lvl,
            "label": f"Level {lvl} (Direct)" if lvl == 1 else f"Level {lvl}",
            "rate": rate_val,
            "ratePercent": round(rate_val * 100.0, 2),
            "membersCount": len(lvl_members),
            "turnover": lvl_turnover,
            "earnedCommission": lvl_earned,
            "unclaimedCommission": lvl_unclaimed,
            "claimedCommission": lvl_claimed,
        })

    lifetime_comm = round(sum(float(r.commission_amount or 0.0) for r in all_comm_rows), 2)
    claimable_balance = round(sum(float(r.commission_amount or 0.0) for r in all_comm_rows if str(r.status or "").upper() in ("UNCLAIMED", "PENDING")), 2)

    ist_mid = get_ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ms = int(ist_mid.timestamp() * 1000)
    today_comm = round(sum(
        float(r.commission_amount or 0.0)
        for r in all_comm_rows
        if _parse_ts_ms(r.created_at, r.created_at_ms or 0) >= today_start_ms
    ), 2)

    network_turnover = round(sum(m["turnover"] for m in members), 2)
    if network_turnover <= 0:
        network_turnover = round(sum(float(r.eligible_amount or 0.0) for r in all_comm_rows), 2)

    recent_commissions = [{
        "id": r.id,
        "beneficiaryUserId": r.beneficiary_user_id,
        "sourceUserId": r.source_user_id,
        "sourceUserName": r.source_user_name or r.source_user_id,
        "sourceBetId": r.source_bet_id or "",
        "level": int(r.level or 1),
        "rate": float(r.rate or 0.01),
        "eligibleAmount": round(float(r.eligible_amount or 0.0), 2),
        "commissionAmount": round(float(r.commission_amount or 0.0), 2),
        "status": str(r.status or "UNCLAIMED").upper(),
        "createdAt": to_ist_display(r.created_at, r.created_at_ms, mode="datetime"),
        "createdAtMs": _parse_ts_ms(r.created_at, r.created_at_ms),
    } for r in all_comm_rows[:1000]]

    # Permanent Affiliate Claim Transactions Ledger (every Claim action with exact IST date & time)
    claim_tx_rows = (
        Transaction.query
        .filter(Transaction.user_id == uid, Transaction.type == "AFFILIATE_CLAIM")
        .order_by(Transaction.created_at_ms.desc())
        .all()
    )
    claim_history = [{
        "id": tx.tx_id,
        "title": tx.title or "Affiliate Bonus Claimed",
        "ref": tx.ref or "Credited to Main Wallet",
        "amount": round(float(tx.amount or 0.0), 2),
        "balanceBefore": round(float(tx.balance_before or 0.0), 2),
        "balanceAfter": round(float(tx.balance_after or 0.0), 2),
        "status": "CREDITED",
        "createdAt": to_ist_display(tx.created_at, tx.created_at_ms, mode="datetime"),
        "createdAtMs": _parse_ts_ms(tx.created_at, tx.created_at_ms or 0),
    } for tx in claim_tx_rows]
    total_claimed = round(sum(c["amount"] for c in claim_history), 2)

    return {
        "userId": uid,
        "userName": root_u.name,
        "referralCode": ref_code,
        "lifetimeCommission": lifetime_comm,
        "claimableBalance": claimable_balance,
        "unclaimedCommission": claimable_balance,
        "totalClaimed": total_claimed,
        "claimCount": len(claim_history),
        "todayCommission": today_comm,
        "networkTurnover": network_turnover,
        "teamCount": len(members),
        "directCount": sum(1 for m in members if m["tier"] == 1),
        "levelBreakdown": level_breakdown,
        "members": members,
        "recentCommissions": recent_commissions,
        "claimHistory": claim_history,
    }


def bet_to_dict(b: Bet) -> dict:
    amt = float(b.amount or 0.0)
    fee_amt = round(float(b.platform_fee or 0.0), 2) if b.platform_fee is not None else round(amt * 0.03, 2)
    net_amt = round(float(b.net_amount or 0.0), 2) if (b.net_amount or 0.0) > 0.0 else round(amt - fee_amt, 2)
    win_amt = float(b.win_amount or 0.0)
    st_u = str(b.status or "PENDING").upper()
    net_pl = round(win_amt - amt, 2) if st_u == "WON" else (round(-amt, 2) if st_u == "LOST" else 0.0)
    return {
        "id": b.bet_id,
        "userId": b.user_id,
        "userName": b.user_name,
        "marketId": b.market,
        "marketName": f"{b.market} MARKET",
        "roundId": b.round_id,
        "period": b.period,
        "amount": amt,
        "platformFee": fee_amt,
        "netAmount": net_amt,
        "type": b.prediction_type,
        "target": b.prediction_target,
        "mult": float(b.multiplier or 0.0),
        "potentialPayout": float(b.potential_payout or 0.0),
        "status": b.status,
        "result": b.result_text,
        "winAmount": win_amt,
        "lossAmount": float(b.loss_amount or 0.0),
        "netProfitLoss": net_pl,
        "time": to_ist_display(b.created_at, b.created_at_ms, mode="datetime"),
        "createdAtMs": _parse_ts_ms(b.created_at, b.created_at_ms),
    }


def _parse_days_arg(raw_days, default_all=True):
    s = str(raw_days if raw_days is not None else "").strip().upper()
    if s in ("", "ALL", "0", "FOREVER", "PERMANENT"):
        return None if default_all else RETENTION_DAYS
    try:
        val = int(s)
        return None if val <= 0 else min(36500, val)
    except Exception:
        return None if default_all else RETENTION_DAYS


def build_user_statement(uid: str, days="ALL", category="ALL", market_filter="ALL") -> dict:
    curr_ms = now_ms()
    parsed_days = _parse_days_arg(days, default_all=True)
    cutoff_ms = (curr_ms - (parsed_days * 86400 * 1000)) if parsed_days else None
    cat_upper = str(category or "ALL").upper().strip()
    mkt_upper = str(market_filter or "ALL").upper().strip()

    u = User.query.get(uid)
    wallet_balance = float(u.balance) if u else 0.0
    user_name = u.name if u else uid
    referral_code = (u.referral_code or uid[-6:].upper()) if u else uid[-6:].upper()

    bets_q = Bet.query.filter(Bet.user_id == uid)
    if cutoff_ms is not None:
        bets_q = bets_q.filter((Bet.created_at_ms >= cutoff_ms) | (Bet.created_at_ms == 0))
    if mkt_upper in MARKET_KEYS:
        bets_q = bets_q.filter(Bet.market == mkt_upper)
    bet_rows = bets_q.order_by(Bet.created_at_ms.desc()).all()

    bets_list = []
    total_wagered = total_won = 0.0
    won_count = lost_count = pending_count = cancelled_count = 0
    for b in bet_rows:
        bd = bet_to_dict(b)
        st_u = str(b.status or "PENDING").upper()
        if st_u == "WON":
            won_count += 1
            total_wagered += bd["amount"]
            total_won += bd["winAmount"]
        elif st_u == "LOST":
            lost_count += 1
            total_wagered += bd["amount"]
        elif st_u in ("CANCELLED", "REFUNDED"):
            cancelled_count += 1
        else:
            pending_count += 1
            total_wagered += bd["amount"]
        bets_list.append(bd)

    settled_wagered = sum(b["amount"] for b in bets_list if str(b["status"]).upper() in ("WON", "LOST"))
    net_bet_pl = round(total_won - settled_wagered, 2)

    tx_q = Transaction.query.filter(Transaction.user_id == uid)
    dep_q = Deposit.query.filter(Deposit.user_id == uid)
    wd_q = Withdrawal.query.filter(Withdrawal.user_id == uid)
    ref_q = ReferralCommission.query.filter(ReferralCommission.beneficiary_user_id == uid)
    if cutoff_ms is not None:
        tx_q = tx_q.filter((Transaction.created_at_ms >= cutoff_ms) | (Transaction.created_at_ms == 0))
        dep_q = dep_q.filter((Deposit.created_at_ms >= cutoff_ms) | (Deposit.created_at_ms == 0))
        wd_q = wd_q.filter((Withdrawal.created_at_ms >= cutoff_ms) | (Withdrawal.created_at_ms == 0))
        ref_q = ref_q.filter((ReferralCommission.created_at_ms >= cutoff_ms) | (ReferralCommission.created_at_ms == 0))

    tx_rows = tx_q.order_by(Transaction.created_at_ms.desc()).all()
    dep_rows = dep_q.order_by(Deposit.created_at_ms.desc()).all()
    wd_rows = wd_q.order_by(Withdrawal.created_at_ms.desc()).all()
    ref_rows = ref_q.order_by(ReferralCommission.created_at_ms.desc()).all()

    entries = []
    seen_dep_refs, seen_wd_refs = set(), set()
    tot_dep_ok = tot_dep_pend = tot_wd_ok = tot_wd_pend = tot_ref_earn = 0.0

    for d in dep_rows:
        st_u = str(d.status or "IN PROCESS").upper()
        amt = float(d.amount or 0.0)
        ts_ms = _parse_ts_ms(d.created_at, d.created_at_ms or 0)
        if st_u == "SUCCESS":
            tot_dep_ok += amt
        elif st_u == "IN PROCESS":
            tot_dep_pend += amt
        seen_dep_refs.add(f"UTR {d.utr}")
        entries.append({
            "id": d.id, "category": "DEPOSIT", "type": "DEPOSIT",
            "title": f"Deposit via {d.method or 'UPI'}",
            "ref": f"UTR: {d.utr}" + (f" ({d.reason})" if d.reason else ""),
            "amount": round(amt, 2), "balanceBefore": None, "balanceAfter": None,
            "status": st_u, "reason": d.reason,
            "time": format_ist_datetime(ts_ms), "timestampMs": ts_ms,
        })

    for w in wd_rows:
        st_u = str(w.status or "IN PROCESS").upper()
        amt = float(w.amount or 0.0)
        ts_ms = _parse_ts_ms(w.created_at, w.created_at_ms or 0)
        if st_u == "SUCCESS":
            tot_wd_ok += amt
        elif st_u == "IN PROCESS":
            tot_wd_pend += amt
        seen_wd_refs.add(str(w.destination or ""))
        entries.append({
            "id": w.id, "category": "WITHDRAWAL", "type": "WITHDRAWAL",
            "title": f"Withdrawal to {w.bank_name or 'Bank / UPI'}",
            "ref": (w.destination or f"A/C: {w.acc_no or w.upi_id or 'N/A'}") + (f" • {w.reason}" if w.reason else ""),
            "amount": round(-amt, 2), "balanceBefore": None, "balanceAfter": None,
            "status": st_u, "reason": w.reason,
            "time": format_ist_datetime(ts_ms), "timestampMs": ts_ms,
        })

    for tx in tx_rows:
        tx_type = str(tx.type or "").upper()
        amt = float(tx.amount or 0.0)
        ts_ms = _parse_ts_ms(tx.created_at, tx.created_at_ms or 0)
        if tx_type == "DEPOSIT" and str(tx.ref or "") in seen_dep_refs:
            continue
        if tx_type == "WITHDRAWAL" and str(tx.ref or "") in seen_wd_refs:
            continue
        if tx_type in ("COMMISSION", "REFERRAL_COMMISSION", "AFFILIATE_CLAIM"):
            tot_ref_earn += amt
            cat = "REFERRAL"
        elif tx_type in ("BET", "WIN"):
            cat = "PROFIT_LOSS"
        elif tx_type == "DEPOSIT":
            if amt > 0:
                tot_dep_ok += amt
            cat = "DEPOSIT"
        elif tx_type in ("WITHDRAWAL", "WITHDRAWAL_REFUND"):
            cat = "WITHDRAWAL"
        else:
            cat = tx_type
        entries.append({
            "id": tx.tx_id, "category": cat, "type": tx_type,
            "title": tx.title or tx_type, "ref": tx.ref or "",
            "amount": round(amt, 2),
            "balanceBefore": round(float(tx.balance_before), 2),
            "balanceAfter": round(float(tx.balance_after), 2),
            "status": str(tx.status or "COMPLETED").upper(), "reason": None,
            "time": format_ist_datetime(ts_ms), "timestampMs": ts_ms,
        })

    for rc in ref_rows:
        rc_st = str(rc.status or "").upper()
        # Unclaimed commissions live in the Claim Vault (not main wallet); Claimed rows already have an AFFILIATE_CLAIM wallet tx.
        if rc_st in ("UNCLAIMED", "PENDING", "CLAIMED", "REVERSED"):
            continue
        comm_amt = float(rc.commission_amount or 0.0)
        ts_ms = int(rc.created_at_ms or 0)
        already = any(
            e["id"] == rc.id or (e["type"] == "REFERRAL_COMMISSION" and abs(e["timestampMs"] - ts_ms) < 500 and abs(e["amount"] - comm_amt) < 0.01)
            for e in entries
        )
        if not already:
            tot_ref_earn += comm_amt
            entries.append({
                "id": rc.id, "category": "REFERRAL", "type": "REFERRAL_COMMISSION",
                "title": f"Tier {rc.level} Refer & Earn ({float(rc.rate)*100:.2f}%)",
                "ref": f"From {rc.source_user_name or rc.source_user_id} (Bet {rc.source_bet_id or ''})",
                "amount": round(comm_amt, 2), "balanceBefore": None, "balanceAfter": None,
                "status": rc_st or "SETTLED", "reason": None,
                "time": format_ist_datetime(ts_ms), "timestampMs": ts_ms,
            })

    entries.sort(key=lambda x: x["timestampMs"], reverse=True)
    if cat_upper == "PROFIT_LOSS":
        filtered = [e for e in entries if e["type"] in ("BET", "WIN", "REFUND", "PROFIT_LOSS")]
    elif cat_upper in ("BETS", "BET"):
        filtered = [e for e in entries if e["type"] == "BET"]
    elif cat_upper == "WIN":
        filtered = [e for e in entries if e["type"] == "WIN"]
    elif cat_upper in ("REFERRAL", "COMMISSION", "REFER"):
        filtered = [e for e in entries if e["category"] == "REFERRAL" or e["type"] in ("COMMISSION", "REFERRAL_COMMISSION", "AFFILIATE_CLAIM")]
    elif cat_upper == "DEPOSIT":
        filtered = [e for e in entries if e["type"] == "DEPOSIT"]
    elif cat_upper == "WITHDRAWAL":
        filtered = [e for e in entries if e["type"] in ("WITHDRAWAL", "WITHDRAWAL_REFUND")]
    else:
        filtered = entries

    return {
        "userId": uid,
        "userName": user_name,
        "referralCode": referral_code,
        "days": parsed_days if parsed_days else "ALL",
        "retentionDays": "PERMANENT",
        "category": cat_upper,
        "market": mkt_upper,
        "generatedAt": format_ist_datetime(curr_ms),
        "summary": {
            "walletBalance": round(wallet_balance, 2),
            "days": parsed_days if parsed_days else "ALL",
            "retentionDays": "PERMANENT",
            "totalBetsCount": len(bets_list),
            "wonBetsCount": won_count,
            "lostBetsCount": lost_count,
            "pendingBetsCount": pending_count,
            "cancelledBetsCount": cancelled_count,
            "totalWagered": round(total_wagered, 2),
            "totalWon": round(total_won, 2),
            "netBetProfitLoss": net_bet_pl,
            "totalReferEarn": round(tot_ref_earn, 2),
            "totalDeposit": round(tot_dep_ok, 2),
            "pendingDepositTotal": round(tot_dep_pend, 2),
            "totalWithdrawal": round(tot_wd_ok, 2),
            "pendingWithdrawalTotal": round(tot_wd_pend, 2),
            "lifetimeDeposit": round(float(u.total_deposit) if u else 0.0, 2),
            "lifetimeWithdraw": round(float(u.total_withdraw) if u else 0.0, 2),
        },
        "bets": bets_list,
        "statementEntries": filtered,
    }


def export_statement_csv(stmt: dict) -> str:
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf)
    s = stmt["summary"]
    w.writerow(["COLOUR KING - 90-DAY ACCOUNT & BETTING STATEMENT"])
    w.writerow(["User ID", stmt["userId"], "User Name", stmt["userName"], "Statement Period", f"Last {stmt['days']} Days", "Generated At", stmt["generatedAt"]])
    w.writerow([])
    w.writerow(["Current Wallet Balance", f"{s['walletBalance']:.2f}", "Total Bet Wagered", f"{s['totalWagered']:.2f}", "Total Bet Won", f"{s['totalWon']:.2f}", "Refer & Earn", f"{s['totalReferEarn']:.2f}"])
    w.writerow([])
    w.writerow(["Date & Time", "Entry ID", "Category", "Type", "Title", "Reference / UTR / Bank", "Amount (INR)", "Balance Before", "Balance After", "Status", "Reason"])
    for e in stmt["statementEntries"]:
        w.writerow([
            e["time"], e["id"], e["category"], e["type"], e["title"], e["ref"],
            f"{e['amount']:+.2f}",
            f"{e['balanceBefore']:.2f}" if e["balanceBefore"] is not None else "-",
            f"{e['balanceAfter']:.2f}" if e["balanceAfter"] is not None else "-",
            e["status"], e.get("reason") or "",
        ])
    w.writerow([])
    w.writerow(["Placed At", "Bet ID", "Market", "Period", "Type", "Target", "Mult", "Amount", "3% Fee", "Net Stake", "Status", "Won", "Net P&L", "Result"])
    for b in stmt["bets"]:
        w.writerow([
            b["time"], b["id"], b["marketId"], b["period"], b["type"], b["target"], f"{b['mult']}x",
            f"{b['amount']:.2f}", f"{b['platformFee']:.2f}", f"{b['netAmount']:.2f}",
            b["status"], f"{b['winAmount']:.2f}", f"{b['netProfitLoss']:+.2f}", b["result"],
        ])
    return buf.getvalue()


def compute_live_wagers_and_market_stats(curr_ms: int | None = None):
    if curr_ms is None:
        curr_ms = now_ms()
    live_wagers, market_stats = {}, {}
    for m_code in MARKET_KEYS:
        auth = calculate_authoritative_round(m_code, curr_ms)
        cur_p = auth["period"]
        pool = {
            "market": m_code, "period": cur_p,
            "green": 0.0, "greenBets": 0, "violet": 0.0, "violetBets": 0,
            "red": 0.0, "redBets": 0, "big": 0.0, "bigBets": 0,
            "small": 0.0, "smallBets": 0,
            "numbers": [0.0] * 10, "numberBets": [0] * 10,
            "totalPool": 0.0, "totalBets": 0,
        }
        active_bets = Bet.query.filter(
            Bet.market == m_code, Bet.period == cur_p, Bet.status.in_(["PENDING", "LOCKED"])
        ).all()
        for b in active_bets:
            amt = round(float(b.amount or 0.0), 2)
            btype = str(b.prediction_type or "").upper().strip()
            target = str(b.prediction_target or "").upper().strip()
            t_num = normalize_bet_target_num(btype, target)
            if t_num is not None and 0 <= t_num <= 9:
                pool["numbers"][t_num] = round(pool["numbers"][t_num] + amt, 2)
                pool["numberBets"][t_num] += 1
            elif target == "GREEN":
                pool["green"] = round(pool["green"] + amt, 2)
                pool["greenBets"] += 1
            elif target == "VIOLET":
                pool["violet"] = round(pool["violet"] + amt, 2)
                pool["violetBets"] += 1
            elif target == "RED":
                pool["red"] = round(pool["red"] + amt, 2)
                pool["redBets"] += 1
            elif target == "BIG":
                pool["big"] = round(pool["big"] + amt, 2)
                pool["bigBets"] += 1
            elif target == "SMALL":
                pool["small"] = round(pool["small"] + amt, 2)
                pool["smallBets"] += 1
            pool["totalPool"] = round(pool["totalPool"] + amt, 2)
            pool["totalBets"] += 1
        live_wagers[m_code] = pool

        mkt_bets = Bet.query.filter(Bet.market == m_code, ~Bet.status.in_(["CANCELLED", "REFUNDED"])).all()
        turnover = round(sum(float(x.amount or 0.0) for x in mkt_bets), 2)
        settled_turnover = round(sum(float(x.amount or 0.0) for x in mkt_bets if str(x.status or "").upper() in ("WON", "LOST")), 2)
        payout = round(sum(float(x.win_amount or 0.0) for x in mkt_bets if str(x.status or "").upper() == "WON"), 2)
        net_house = round(settled_turnover - payout, 2)
        market_stats[m_code] = {
            "market": m_code, "period": cur_p,
            "activePool": pool["totalPool"], "activeBetsCount": pool["totalBets"],
            "turnover": turnover, "settledTurnover": settled_turnover,
            "payout": payout, "netHouseProfit": net_house,
            "marginPct": round((net_house / settled_turnover) * 100.0, 1) if settled_turnover > 0 else 0.0,
            "totalBetsCount": len(mkt_bets),
        }
    return live_wagers, market_stats


def compute_admin_kpis() -> dict:
    all_deps = Deposit.query.all()
    total_dep = round(sum(float(d.amount or 0.0) for d in all_deps if str(d.status or "").upper() in ("SUCCESS", "APPROVED")), 2)
    approved_dep_cnt = sum(1 for d in all_deps if str(d.status or "").upper() in ("SUCCESS", "APPROVED"))
    pending_dep_cnt = sum(1 for d in all_deps if str(d.status or "").upper() in ("IN PROCESS", "PENDING"))

    all_wds = Withdrawal.query.all()
    total_wd = round(sum(float(w.amount or 0.0) for w in all_wds if str(w.status or "").upper() in ("SUCCESS", "APPROVED")), 2)
    pending_wd_cnt = sum(1 for w in all_wds if str(w.status or "").upper() in ("IN PROCESS", "PENDING"))

    valid_bets = Bet.query.filter(~Bet.status.in_(["CANCELLED", "REFUNDED"])).all()
    turnover = round(sum(float(b.amount or 0.0) for b in valid_bets), 2)

    all_users = User.query.all()
    active_users = sum(1 for u in all_users if str(u.status or "").upper() == "ACTIVE")
    blocked_users = sum(1 for u in all_users if str(u.status or "").upper() == "BLOCKED")
    net_profit = round(total_dep - total_wd, 2)

    return {
        "totalDeposits": total_dep,
        "approvedDepositsCount": approved_dep_cnt,
        "pendingDepositsCount": pending_dep_cnt,
        "totalWithdrawals": total_wd,
        "pendingWithdrawalsCount": pending_wd_cnt,
        "netProfit": net_profit,
        "marginPct": round((net_profit / total_dep) * 100.0, 2) if total_dep > 0 else 0.0,
        "totalTurnover": turnover,
        "totalBetsCount": len(valid_bets),
        "totalUsers": len(all_users),
        "activeUsers": active_users,
        "blockedUsers": blocked_users,
    }


def get_storage_status_dict() -> dict:
    return {
        "mode": "POSTGRESQL_SQLALCHEMY" if IS_POSTGRES else "SQLITE_SQLALCHEMY",
        "label": "Render PostgreSQL + SQLAlchemy ORM (Zero Drop)" if IS_POSTGRES else "SQLite + SQLAlchemy ORM",
        "isDurableCloud": IS_POSTGRES,
        "dbFile": "PostgreSQL" if IS_POSTGRES else SQLITE_DB_FILE,
        "stateVersion": get_state_version(),
        "totalUsers": User.query.count(),
        "totalBets": Bet.query.count(),
        "totalDeposits": Deposit.query.count(),
        "totalWithdrawals": Withdrawal.query.count(),
        "totalCommissions": ReferralCommission.query.count(),
        "pgConfigured": IS_POSTGRES,
        "pgConnected": IS_POSTGRES,
        "warning": "",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 24/7 SUPPORT HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_user_support_situation(uid: str):
    u = User.query.get(uid)
    if not u:
        return None
    bank_cfg = get_app_state_json("bank_config", DEFAULT_BANK_CONFIG)
    deps = Deposit.query.filter_by(user_id=uid).order_by(Deposit.created_at_ms.desc()).limit(5).all()
    wds = Withdrawal.query.filter_by(user_id=uid).order_by(Withdrawal.created_at_ms.desc()).limit(5).all()
    last_adj = Transaction.query.filter(Transaction.user_id == uid, func.upper(Transaction.type) == "ADJUSTMENT").order_by(Transaction.created_at_ms.desc()).first()
    latest_bet = Bet.query.filter_by(user_id=uid).order_by(Bet.created_at_ms.desc()).first()
    active_bets_cnt = Bet.query.filter(Bet.user_id == uid, Bet.status.in_(["PENDING", "LOCKED"])).count()

    def dep_d(d):
        if not d:
            return None
        ms = _parse_ts_ms(d.created_at, d.created_at_ms or 0)
        return {"id": d.id, "amount": round(float(d.amount), 2), "method": d.method, "utr": d.utr, "status": d.status.upper(), "reason": d.reason or "", "time": to_ist_display(d.created_at, ms, mode="display"), "createdAtMs": ms}

    def wd_d(w):
        if not w:
            return None
        ms = _parse_ts_ms(w.created_at, w.created_at_ms or 0)
        return {"id": w.id, "amount": round(float(w.amount), 2), "destination": w.destination or "", "status": w.status.upper(), "reason": w.reason or "", "time": to_ist_display(w.created_at, ms, mode="display"), "createdAtMs": ms}

    return {
        "userId": u.id, "userName": u.name, "phone": u.phone or "", "accountStatus": (u.status or "ACTIVE").upper(),
        "balance": round(float(u.balance or 0.0), 2), "totalDeposit": round(float(u.total_deposit or 0.0), 2), "totalWithdraw": round(float(u.total_withdraw or 0.0), 2),
        "activeBetsCount": active_bets_cnt,
        "latestDeposit": dep_d(deps[0] if deps else None),
        "pendingDeposit": dep_d(next((d for d in deps if d.status.upper() in ("IN PROCESS", "PENDING")), None)),
        "failedDeposit": dep_d(next((d for d in deps if d.status.upper() in ("FAIL", "REJECTED")), None)),
        "latestWithdrawal": wd_d(wds[0] if wds else None),
        "pendingWithdrawal": wd_d(next((w for w in wds if w.status.upper() in ("IN PROCESS", "PENDING")), None)),
        "failedWithdrawal": wd_d(next((w for w in wds if w.status.upper() in ("FAIL", "REJECTED")), None)),
        "lastAdjustment": {"txId": last_adj.tx_id, "amount": round(float(last_adj.amount), 2), "ref": last_adj.ref or "", "time": to_ist_display(last_adj.created_at, last_adj.created_at_ms, mode="display")} if last_adj else None,
        "latestBet": {"id": latest_bet.bet_id, "market": latest_bet.market, "period": latest_bet.period, "target": latest_bet.prediction_target, "amount": round(float(latest_bet.amount), 2), "status": latest_bet.status.upper(), "result": latest_bet.result_text or ""} if latest_bet else None,
        "upiId": bank_cfg.get("upiId", DEFAULT_BANK_CONFIG["upiId"]),
        "bankName": bank_cfg.get("bankName", DEFAULT_BANK_CONFIG["bankName"]),
        "minDeposit": bank_cfg.get("minDeposit", 100),
        "maxDeposit": bank_cfg.get("maxDeposit", 100000),
    }


def generate_support_auto_reply(uid: str, user_message="", category="GENERAL"):
    sit = build_user_support_situation(uid)
    if not sit:
        return "SUPPORT_GENERAL", "Welcome to Colour King 24/7 Support!"
    msg_l = str(user_message or "").lower()
    cat_u = str(category or "GENERAL").upper().strip()
    bal_str = f"₹{sit['balance']:,.2f}"
    parts, tag = [], "SUPPORT_GENERAL"
    if sit["accountStatus"] == "BLOCKED" or cat_u == "ACCOUNT" or any(k in msg_l for k in ("block", "ban", "account")):
        tag = "ACCOUNT_BLOCKED" if sit["accountStatus"] == "BLOCKED" else "ACCOUNT_ACTIVE"
        parts.append(f"Account Status ({sit['userId']}): {sit['accountStatus']} • Balance: {bal_str}.")
    if cat_u == "DEPOSIT" or any(k in msg_l for k in ("deposit", "utr", "recharge", "upi")):
        pd = sit["pendingDeposit"] or sit["failedDeposit"] or sit["latestDeposit"]
        if pd:
            tag = f"DEPOSIT_{pd['status']}"
            parts.append(f"Deposit {pd['id']} (₹{pd['amount']:,.2f}, UTR: {pd['utr']}): {pd['status']}.")
        else:
            tag = "DEPOSIT_GUIDE"
            parts.append(f"Send via UPI {sit['upiId']} ({sit['bankName']}) and enter your 12-digit UTR.")
    if cat_u == "WITHDRAWAL" or any(k in msg_l for k in ("withdraw", "payout", "bank", "cashout")):
        wd = sit["pendingWithdrawal"] or sit["failedWithdrawal"] or sit["latestWithdrawal"]
        if wd:
            tag = f"WITHDRAWAL_{wd['status']}"
            parts.append(f"Withdrawal {wd['id']} (₹{wd['amount']:,.2f}): {wd['status']}.")
        else:
            tag = "WITHDRAWAL_GUIDE"
            parts.append(f"Wallet Balance: {bal_str}. Submit IMPS/UPI payout in Wallet → Withdraw.")
    if not parts:
        tag = "SUPPORT_OVERVIEW"
        parts.append(f"🤖 24/7 Live Auto-Support for {sit['userName']} ({sit['userId']}) — Account: {sit['accountStatus']} • Balance: {bal_str}.")
    parts.append("💬 Delivered to 24/7 Admin Desk — an Admin can send a custom reply directly here.")
    return tag, "\n".join(parts)


def ensure_support_ticket_and_add_message(
    uid, user_name, sender_type, sender_name, message,
    category="GENERAL", is_auto=0, situation_tag="", curr_ms=None,
    attachment_name="", attachment_mime="", attachment_size=0, attachment_url="",
):
    if curr_ms is None:
        curr_ms = now_ms()
    clean_msg = str(message or "").strip()
    preview = (clean_msg if clean_msg else (f"📎 {attachment_name}" if attachment_name else "📎 Media"))[:200]
    trow = SupportTicket.query.filter_by(user_id=uid).order_by(SupportTicket.updated_at_ms.desc()).first()
    if trow:
        tid = trow.ticket_id
    else:
        tid = f"TKT-{uid}"
        trow = SupportTicket(
            ticket_id=tid, user_id=uid, user_name=user_name, status="OPEN",
            category=category, last_message=preview, last_sender=sender_type,
            unread_admin=0, unread_user=0, updated_at=format_ist_datetime(curr_ms),
            updated_at_ms=curr_ms, created_at=format_ist_datetime(curr_ms),
        )
        db.session.add(trow)

    mid = f"MSG-{int(curr_ms)}-{random.randint(1000, 9999)}"
    db.session.add(SupportMessage(
        id=mid, ticket_id=tid, user_id=uid, sender_type=sender_type, sender_name=sender_name,
        category=category, message=clean_msg, is_auto=1 if is_auto else 0, situation_tag=situation_tag,
        attachment_name=str(attachment_name or "")[:160], attachment_mime=str(attachment_mime or "")[:120],
        attachment_size=max(0, int(attachment_size or 0)), attachment_url=str(attachment_url or "")[:300],
        created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
    ))

    trow.user_name = user_name
    trow.last_message = preview
    trow.last_sender = sender_type
    trow.updated_at = format_ist_datetime(curr_ms)
    trow.updated_at_ms = curr_ms
    if sender_type == "USER":
        trow.status = "OPEN"
        trow.category = category
        trow.unread_admin = int(trow.unread_admin or 0) + 1
    elif sender_type == "ADMIN":
        trow.status = "OPEN"
        trow.unread_admin = 0
        trow.unread_user = int(trow.unread_user or 0) + 1
    else:
        trow.unread_user = int(trow.unread_user or 0) + 1
    return tid, mid


def record_admin_situation_support_message(uid, situation_tag, message, category="ADMIN_ALERT", create_if_missing=True, curr_ms=None):
    u = User.query.get(uid)
    if not u:
        return None
    if not create_if_missing and not SupportTicket.query.filter_by(user_id=uid).first():
        return None
    tid, _ = ensure_support_ticket_and_add_message(
        uid=uid, user_name=u.name, sender_type="AUTO_BOT",
        sender_name="Colour King 24/7 Support Bot", message=message,
        category=category, is_auto=1, situation_tag=situation_tag, curr_ms=curr_ms,
    )
    return tid


def fetch_support_thread_payload(uid: str, mark_read_for=None, auto_welcome=False):
    u = User.query.get(uid)
    if not u:
        return None
    trow = SupportTicket.query.filter_by(user_id=uid).order_by(SupportTicket.updated_at_ms.desc()).first()
    if not trow and auto_welcome:
        tag, greeting = generate_support_auto_reply(uid, "", category="WELCOME")
        ensure_support_ticket_and_add_message(uid, u.name, "AUTO_BOT", "Colour King 24/7 Support Bot", greeting, "WELCOME", 1, tag)
        trow = SupportTicket.query.filter_by(user_id=uid).order_by(SupportTicket.updated_at_ms.desc()).first()
        if trow and mark_read_for == "USER":
            trow.unread_user = 0
        db.session.commit()
    elif trow and mark_read_for == "USER" and int(trow.unread_user or 0) > 0:
        trow.unread_user = 0
        db.session.commit()

    ticket_dict, messages = None, []
    if trow:
        ticket_dict = {
            "ticketId": trow.ticket_id, "userId": trow.user_id, "userName": trow.user_name or u.name,
            "status": trow.status, "category": trow.category, "lastMessage": trow.last_message,
            "lastSender": trow.last_sender, "unreadAdmin": int(trow.unread_admin or 0), "unreadUser": int(trow.unread_user or 0),
            "updatedAt": to_ist_display(trow.updated_at, trow.updated_at_ms, mode="display"), "updatedAtMs": int(trow.updated_at_ms or 0),
        }
        msgs = SupportMessage.query.filter_by(ticket_id=trow.ticket_id).order_by(SupportMessage.created_at_ms.asc(), SupportMessage.id.asc()).all()
        messages = [{
            "id": m.id, "ticketId": m.ticket_id, "userId": m.user_id,
            "senderType": m.sender_type, "senderName": m.sender_name, "category": m.category,
            "message": m.message, "isAuto": bool(m.is_auto), "situationTag": m.situation_tag,
            "attachmentName": m.attachment_name, "attachmentMime": m.attachment_mime,
            "attachmentSize": int(m.attachment_size or 0), "attachmentUrl": m.attachment_url,
            "createdAt": to_ist_display(m.created_at, m.created_at_ms, mode="display"), "createdAtMs": int(m.created_at_ms or 0),
        } for m in msgs]

    return {
        "success": True, "ticket": ticket_dict, "messages": messages,
        "situation": build_user_support_situation(uid),
        "unreadUser": ticket_dict["unreadUser"] if ticket_dict else 0,
    }


def list_admin_support_tickets():
    trows = SupportTicket.query.order_by(SupportTicket.updated_at_ms.desc()).all()
    tickets, unread_total = [], 0
    for t in trows:
        u = User.query.get(t.user_id)
        unread_a = int(t.unread_admin or 0)
        unread_total += unread_a
        msgs = SupportMessage.query.filter_by(ticket_id=t.ticket_id).order_by(SupportMessage.created_at_ms.asc()).limit(200).all()
        msgs_arr = [{
            "id": m.id, "ticketId": m.ticket_id, "userId": m.user_id,
            "senderType": m.sender_type, "senderName": m.sender_name, "category": m.category,
            "message": m.message, "isAuto": bool(m.is_auto), "situationTag": m.situation_tag,
            "attachmentName": m.attachment_name, "attachmentMime": m.attachment_mime,
            "attachmentSize": int(m.attachment_size or 0), "attachmentUrl": m.attachment_url,
            "createdAt": to_ist_display(m.created_at, m.created_at_ms, mode="display"),
            "created_at_ms": int(m.created_at_ms or 0), "createdAtMs": int(m.created_at_ms or 0),
        } for m in msgs]
        tickets.append({
            "ticketId": t.ticket_id, "userId": t.user_id, "userName": t.user_name or (u.name if u else t.user_id),
            "phone": u.phone if u else "", "balance": round(float(u.balance or 0.0), 2) if u else 0.0,
            "userStatus": (u.status or "ACTIVE").upper() if u else "ACTIVE",
            "status": (t.status or "OPEN").upper(), "category": t.category or "GENERAL",
            "lastMessage": t.last_message or "", "lastSender": t.last_sender or "AUTO_BOT",
            "unreadAdmin": unread_a, "unreadUser": int(t.unread_user or 0),
            "attachmentCount": sum(1 for m in msgs_arr if m.get("attachmentUrl")),
            "updatedAt": to_ist_display(t.updated_at, t.updated_at_ms, mode="display"),
            "updatedAtMs": int(t.updated_at_ms or 0),
            "situation": build_user_support_situation(t.user_id),
            "messages": msgs_arr,
        })
    return tickets, unread_total


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CORS & SESSION COOKIE HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.after_request
def add_cors_and_cache_headers(resp):
    origin = request.headers.get("Origin")
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Vary"] = "Origin"
    else:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-File-Name, X-File-Mime, X-User-Id"
    if request.path.startswith("/api/") and not request.path.startswith("/api/support/files/"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


def get_cookie_uid():
    val = request.cookies.get("ck_uid", "").strip()
    return val if (val and val != "Guest") else None


def attach_session_cookie(resp, uid: str, max_age=2592000):
    proto = (request.headers.get("X-Forwarded-Proto") or "").lower()
    origin = (request.headers.get("Origin") or "").lower()
    is_https = (proto == "https") or origin.startswith("https://") or request.is_secure
    resp.set_cookie(
        "ck_uid", str(uid or ""), max_age=max_age, path="/",
        samesite="None" if is_https else "Lax", secure=is_https,
    )
    return resp


def user_to_dict(u: User) -> dict:
    return {
        "id": u.id, "userId": u.id, "name": u.name,
        "phone": u.phone or "", "email": u.email or "",
        "balance": round(float(u.balance or 0.0), 2),
        "totalDeposit": round(float(u.total_deposit or 0.0), 2),
        "totalWithdraw": round(float(u.total_withdraw or 0.0), 2),
        "betsCount": int(u.bets_count or 0),
        "status": u.status or "ACTIVE",
        "referralCode": u.referral_code or u.id[-6:].upper(),
        "referredBy": u.referred_by,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATIC ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/")
def serve_index():
    return send_from_directory(DIRECTORY, "index.html")


@app.route("/admin")
@app.route("/admin/")
def redirect_admin():
    return redirect("/admin.html", code=301)


@app.route("/<path:filename>")
def serve_static(filename):
    if filename.startswith("api/"):
        return jsonify({"error": "Endpoint not found"}), 404
    return send_from_directory(DIRECTORY, filename)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLOCK, MARKETS, HISTORY & REAL-TIME SSE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/clock", methods=["GET"])
def api_clock():
    curr_ms = now_ms()
    ist_dt = get_ist_now(curr_ms)
    utc_dt = datetime.fromtimestamp(curr_ms / 1000.0, tz=timezone.utc)
    return jsonify({
        "server_time_ms": curr_ms,
        "iso": utc_dt.isoformat(),
        "ist_iso": ist_dt.isoformat(),
        "ist_time": ist_dt.strftime("%I:%M:%S %p IST"),
        "ist_time_24": ist_dt.strftime("%H:%M:%S IST"),
        "ist_date": ist_dt.strftime("%d %b %Y"),
        "ist_formatted": ist_dt.strftime("%d %b %Y, %I:%M:%S %p IST"),
        "timezone": "IST",
        "utc_offset": "+05:30",
    })


@app.route("/api/events", methods=["GET"])
def api_events():
    q: queue.Queue = queue.Queue(maxsize=100)
    with db_lock:
        init_ver = get_state_version()
    with sse_lock:
        sse_subscribers.append(q)

    def stream():
        try:
            init_msg = json.dumps({"version": init_ver, "eventType": "connected", "serverTimeMs": now_ms()})
            yield f"event: connected\ndata: {init_msg}\n\n"
            while True:
                try:
                    ev = q.get(timeout=15.0)
                    yield f"event: state_update\ndata: {json.dumps(ev)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with sse_lock:
                if q in sse_subscribers:
                    sse_subscribers.remove(q)

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache, no-store"})


@app.route("/api/markets", methods=["GET"])
def api_markets():
    curr_ms = now_ms()
    markets_data = {}
    with db_lock:
        for m_code in MARKET_KEYS:
            auth = calculate_authoritative_round(m_code, curr_ms)
            period = auth["period"]
            mkt = Market.query.get(m_code)
            ov_num = mkt.manual_override_num if mkt else None
            ov_per = mkt.manual_override_period if mkt else None

            prev_p = calculate_authoritative_round(m_code, curr_ms - ROUND_DURATION_SEC * 1000)["period"]
            prev_row = Round.query.filter_by(market=m_code, period=prev_p).first()
            if not prev_row or prev_row.status != "SETTLED" or prev_row.result_number is None:
                if ov_num is not None and (ov_per == prev_p or not ov_per):
                    w_num, d_mode = int(ov_num), "MANUAL_ADMIN"
                else:
                    w_num, d_mode = generate_provably_fair_outcome(m_code, prev_p)["number"], "AUTO_RANDOM"
                settle_round_in_db(m_code, f"RND_{m_code}_{prev_p}", prev_p, w_num, d_mode, "SYSTEM_ROLLOVER")

            last_res = (
                Round.query.filter(
                    Round.market == m_code,
                    Round.status == "SETTLED",
                    Round.result_number.isnot(None),
                    Round.period < period,
                )
                .order_by(Round.period.desc())
                .first()
            )
            latest_result = None
            if last_res:
                r_end = int(last_res.end_time_ms or 0)
                if r_end <= 0 and str(last_res.draw_mode or "") != "MANUAL_ADMIN":
                    r_end = get_period_window_ms_ist(last_res.period)[2]
                latest_result = {
                    "period": last_res.period, "number": last_res.result_number,
                    "color": last_res.result_color, "colClass": last_res.result_col_class,
                    "isBig": bool(last_res.is_big), "drawMode": last_res.draw_mode,
                    "time": to_ist_display(last_res.declared_at, r_end, mode="datetime"),
                    "timestampMs": r_end,
                }

            active_bets = Bet.query.filter(Bet.market == m_code, Bet.period == period, Bet.status.in_(["PENDING", "LOCKED"])).all()
            markets_data[m_code] = {
                "market": m_code, "round_id": auth["round_id"], "period": period,
                "start_time_ms": auth["start_time_ms"], "lock_time_ms": auth["lock_time_ms"],
                "end_time_ms": auth["end_time_ms"], "remaining_seconds": auth["remaining_seconds"],
                "is_betting_locked": auth["is_betting_locked"], "status": auth["status"],
                "active_bets_count": len(active_bets),
                "active_bets_total": round(sum(float(b.amount or 0.0) for b in active_bets), 2),
                "manual_override": {"number": ov_num, "period": ov_per} if ov_num is not None else None,
                "latest_result": latest_result,
            }
    return jsonify({"server_time_ms": curr_ms, "markets": markets_data})


@app.route("/api/markets/history", methods=["GET"])
def api_markets_history():
    m_code = (request.args.get("market") or "MIAMI").upper()
    limit = min(200, max(1, int(request.args.get("limit", 50))))
    cur_p = calculate_authoritative_round(m_code)["period"]
    with db_lock:
        rows = (
            Round.query.filter(
                Round.market == m_code, Round.status == "SETTLED",
                Round.result_number.isnot(None), Round.period < cur_p,
            )
            .order_by(Round.period.desc())
            .limit(limit)
            .all()
        )
        records = []
        for r in rows:
            r_end = int(r.end_time_ms or 0)
            if r_end <= 0 and str(r.draw_mode or "") != "MANUAL_ADMIN":
                r_end = get_period_window_ms_ist(r.period)[2]
            records.append({
                "period": r.period, "number": r.result_number,
                "color": r.result_color, "colClass": r.result_col_class,
                "isBig": bool(r.is_big), "drawMode": r.draw_mode,
                "time": to_ist_display(r.declared_at, r_end, mode="datetime"),
                "timestampMs": r_end,
            })
    return jsonify({"market": m_code, "records": records})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BET HISTORY, PLACEMENT (+ 6-LEVEL COMMISSION) & CANCEL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/bets", methods=["GET"])
def api_bets():
    uid = (request.args.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"userId": None, "retentionDays": "PERMANENT", "days": "ALL", "activeBets": [], "betHistory": []})

    m_code = request.args.get("market")
    m_code = m_code.upper() if m_code else None
    curr_ms = now_ms()
    parsed_days = _parse_days_arg(request.args.get("days", "ALL"), default_all=True)

    with db_lock:
        cur_p_map = {mk: calculate_authoritative_round(mk, curr_ms)["period"] for mk in MARKET_KEYS}
        pending_bets = Bet.query.filter(Bet.user_id == uid, Bet.status.in_(["PENDING", "LOCKED"])).all()
        checked_rounds = set()
        for pb in pending_bets:
            key = (pb.market, pb.round_id, pb.period)
            if key in checked_rounds:
                continue
            checked_rounds.add(key)
            if pb.market in cur_p_map and str(pb.period).isdigit() and int(pb.period) < int(cur_p_map[pb.market]):
                sr = Round.query.filter_by(round_id=pb.round_id, status="SETTLED").first()
                if sr and sr.result_number is not None:
                    win_n, d_m = int(sr.result_number), sr.draw_mode or "AUTO_RANDOM"
                else:
                    mkt = Market.query.get(pb.market)
                    if mkt and mkt.manual_override_num is not None and (mkt.manual_override_period == pb.period or not mkt.manual_override_period):
                        win_n, d_m = int(mkt.manual_override_num), "MANUAL_ADMIN"
                    else:
                        win_n, d_m = generate_provably_fair_outcome(pb.market, pb.period)["number"], "AUTO_RANDOM"
                settle_round_in_db(pb.market, pb.round_id, pb.period, win_n, d_m, "SYSTEM_ROLLOVER")

        aq = Bet.query.filter(Bet.user_id == uid, Bet.status.in_(["PENDING", "LOCKED"]))
        hq = Bet.query.filter(Bet.user_id == uid)
        if m_code:
            aq = aq.filter(Bet.market == m_code)
            hq = hq.filter(Bet.market == m_code)
        if parsed_days:
            cutoff_ms = curr_ms - (parsed_days * 86400 * 1000)
            hq = hq.filter((Bet.created_at_ms >= cutoff_ms) | (Bet.created_at_ms == 0))

        active_rows = aq.order_by(Bet.created_at_ms.desc()).all()
        history_rows = hq.order_by(Bet.created_at_ms.desc()).all()

    return jsonify({
        "userId": uid,
        "retentionDays": "PERMANENT",
        "days": parsed_days if parsed_days else "ALL",
        "activeBets": [bet_to_dict(b) for b in active_rows],
        "betHistory": [bet_to_dict(b) for b in history_rows],
    })


@app.route("/api/bets/recover", methods=["POST"])
def api_bets_recover():
    """Idempotently restores any historical user bet slips into PostgreSQL without modifying wallet balance."""
    payload = request.get_json(silent=True) or {}
    uid = str(payload.get("userId") or get_cookie_uid() or "").strip()
    slips = payload.get("slips")
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Missing userId"}), 400
    if not isinstance(slips, list):
        return jsonify({"success": True, "recovered": 0})

    recovered = 0
    curr_ms = now_ms()
    with db_lock:
        try:
            u = User.query.get(uid)
            if not u:
                return jsonify({"success": False, "error": "User not found"}), 404
            cur_p_map = {mk: calculate_authoritative_round(mk, curr_ms)["period"] for mk in MARKET_KEYS}
            rounds_to_settle = set()

            for s in slips[:1000]:
                if not isinstance(s, dict):
                    continue
                bid = str(s.get("id") or "").strip()
                if not bid or Bet.query.get(bid):
                    continue
                m_code = str(s.get("marketId") or s.get("market") or "MIAMI").upper().strip()
                if m_code not in MARKET_KEYS:
                    continue
                period = str(s.get("period") or "").strip()
                if not period:
                    continue
                amt = round(float(s.get("amount") or 0.0), 2)
                if amt <= 0:
                    continue
                fee = round(float(s.get("platformFee") if s.get("platformFee") is not None else round(amt * 0.03, 2)), 2)
                net_amt = round(float(s.get("netAmount") if s.get("netAmount") else round(amt - fee, 2)), 2)
                mult = float(s.get("mult") or s.get("multiplier") or 2.0)
                pot = round(float(s.get("potentialPayout") or round(net_amt * mult, 2)), 2)
                st = str(s.get("status") or "PENDING").upper().strip()
                if st not in ("PENDING", "LOCKED", "WON", "LOST", "CANCELLED", "REFUNDED"):
                    st = "PENDING"
                ts_ms = int(s.get("createdAtMs") or 0) or _parse_ts_ms(s.get("time"), curr_ms)
                rid = str(s.get("roundId") or f"RND_{m_code}_{period}")

                db.session.add(Bet(
                    bet_id=bid, user_id=uid, user_name=u.name, market=m_code,
                    round_id=rid, period=period, amount=amt,
                    platform_fee=fee, net_amount=net_amt,
                    prediction_type=str(s.get("type") or "COLOR").upper(),
                    prediction_target=str(s.get("target") or "GREEN").upper(),
                    multiplier=mult, potential_payout=pot, status=st,
                    result_text=str(s.get("result") or "Awaiting Draw"),
                    win_amount=round(float(s.get("winAmount") or 0.0), 2),
                    loss_amount=round(float(s.get("lossAmount") or 0.0), 2),
                    created_at=format_ist_datetime(ts_ms), created_at_ms=ts_ms,
                ))
                recovered += 1
                if st in ("PENDING", "LOCKED") and m_code in cur_p_map and period.isdigit() and int(period) < int(cur_p_map[m_code]):
                    rounds_to_settle.add((m_code, rid, period))

            if recovered > 0:
                u.bets_count = max(int(u.bets_count or 0), Bet.query.filter_by(user_id=uid).count())
                db.session.commit()
                for m_code, rid, period in rounds_to_settle:
                    sr = Round.query.filter_by(round_id=rid, status="SETTLED").first()
                    win_n = int(sr.result_number) if (sr and sr.result_number is not None) else generate_provably_fair_outcome(m_code, period)["number"]
                    settle_round_in_db(m_code, rid, period, win_n, sr.draw_mode if sr else "AUTO_RANDOM", "SYSTEM_RECOVERY")
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify({"success": True, "recovered": recovered})


@app.route("/api/bets/place", methods=["POST"])
def api_bets_place():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    uid = str(payload.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Please login or register before placing a bet"}), 401

    m_code = str(payload.get("market", "MIAMI")).upper().strip()
    amount = float(payload.get("amount", 0.0))
    b_type = str(payload.get("type", "COLOR")).upper().strip()
    target = str(payload.get("target", "GREEN")).upper().strip()
    mult = float(payload.get("mult", 2.0))

    if m_code not in MARKET_KEYS:
        return jsonify({"success": False, "error": f"Invalid market {m_code}"}), 400
    if amount < 1.0:
        return jsonify({"success": False, "error": "Minimum bet amount is ₹1.00"}), 400

    auth = calculate_authoritative_round(m_code, curr_ms)
    if auth["is_betting_locked"] or auth["remaining_seconds"] <= LOCK_CUTOFF_SEC:
        return jsonify({
            "success": False,
            "error": "BETTING LOCKED: Betting is locked for the current round (last 30 seconds).",
            "remainingSeconds": auth["remaining_seconds"],
        }), 400

    period, round_id = auth["period"], auth["round_id"]

    with db_lock:
        try:
            u = User.query.get(uid)
            if not u:
                return jsonify({"success": False, "error": "User account not found"}), 404
            if u.status == "BLOCKED":
                return jsonify({"success": False, "error": "Account is blocked by Admin"}), 403
            curr_bal = float(u.balance)
            if curr_bal < amount:
                return jsonify({"success": False, "error": "Insufficient wallet balance! Please deposit."}), 400

            new_bal = round(curr_bal - amount, 2)
            u.balance = new_bal
            u.bets_count = int(u.bets_count or 0) + 1

            bet_id = f"BET-{curr_ms}-{random.randint(1000, 9999)}"
            platform_fee = round(amount * 0.03, 2)
            net_amount = round(amount - platform_fee, 2)
            potential_payout = round(net_amount * mult, 2)
            now_str = format_ist_datetime(curr_ms)

            bet_row = Bet(
                bet_id=bet_id, user_id=uid, user_name=u.name, market=m_code,
                round_id=round_id, period=period, amount=amount,
                platform_fee=platform_fee, net_amount=net_amount,
                prediction_type=b_type, prediction_target=target, multiplier=mult,
                potential_payout=potential_payout, status="PENDING",
                result_text="Awaiting Draw", win_amount=0.0, loss_amount=0.0,
                created_at=now_str, created_at_ms=curr_ms,
            )
            db.session.add(bet_row)

            db.session.add(Transaction(
                tx_id=f"TX-BET-{curr_ms}-{random.randint(100, 999)}",
                user_id=uid, type="BET", title=f"Bet on {m_code} #{period}",
                ref=f"Target {target} ({mult}X) • 3% Fee ₹{platform_fee:.2f} • Net ₹{net_amount:.2f}",
                amount=-amount, balance_before=curr_bal, balance_after=new_bal,
                status="COMPLETED", created_at=now_str, created_at_ms=curr_ms,
            ))

            # 6-Level Downline Commission Accrual (held in UNCLAIMED affiliate vault until sponsor explicitly claims to wallet)
            cur_sponsor_id = u.referred_by
            visited = {uid}
            for tier_lvl, comm_rate in REFERRAL_TIER_RATES:
                if not cur_sponsor_id or cur_sponsor_id in visited:
                    break
                visited.add(cur_sponsor_id)
                sp = User.query.get(cur_sponsor_id)
                if not sp:
                    break
                comm_amt = round(amount * comm_rate, 2)
                if comm_amt > 0:
                    db.session.add(ReferralCommission(
                        id=f"REF-L{tier_lvl}-{curr_ms}-{random.randint(100, 999)}",
                        beneficiary_user_id=sp.id, source_user_id=uid, source_user_name=u.name,
                        source_bet_id=bet_id, level=tier_lvl, rate=comm_rate,
                        eligible_amount=amount, commission_amount=comm_amt,
                        status="UNCLAIMED", created_at=now_str, created_at_ms=curr_ms,
                    ))
                cur_sponsor_id = sp.referred_by

            _, sse_ev = bump_state_version("bet_placed", {"userId": uid, "market": m_code, "period": period, "betId": bet_id})
            db.session.commit()
            created_bet = bet_to_dict(bet_row)
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": f"Database error placing bet: {exc}"}), 500

    notify_sse_clients(sse_ev)
    return jsonify({
        "success": True,
        "message": f"Bet placed: ₹{amount:.2f} (3% Fee ₹{platform_fee:.2f}, Net ₹{net_amount:.2f}) on {target}",
        "bet": created_bet,
        "newBalance": new_bal,
    })


@app.route("/api/bets/cancel", methods=["POST"])
def api_bets_cancel():
    return jsonify({
        "success": False,
        "error": "Once a bet is submitted, it cannot be cancelled or refunded."
    }), 403


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# USER AUTHENTICATION, PROFILE & ADMIN USER CONTROLS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/session", methods=["GET"])
def api_session():
    uid = (request.args.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"authenticated": False, "user": None})
    u = User.query.get(uid)
    if not u:
        resp = make_response(jsonify({"authenticated": False, "user": None, "canRestoreWithToken": True}))
        return attach_session_cookie(resp, "", max_age=0)
    return jsonify({"authenticated": True, "recoveryToken": build_user_recovery_token(u), "user": user_to_dict(u)})


@app.route("/api/user", methods=["GET"])
@app.route("/api/wallet", methods=["GET"])
def api_user_profile():
    uid = (request.args.get("id") or request.args.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Not authenticated", "notFound": True}), 404
    u = User.query.get(uid)
    if not u:
        return jsonify({"success": False, "error": "User not found", "notFound": True}), 404
    d = user_to_dict(u)
    d["recoveryToken"] = build_user_recovery_token(u)
    return jsonify(d)


@app.route("/api/users/register", methods=["POST"])
def api_users_register():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    requested_uid = str(payload.get("id") or payload.get("userId") or "").strip()
    name = str(payload.get("name") or payload.get("username") or "").strip()
    raw_phone = str(payload.get("phone") or "").strip()
    digits = "".join(ch for ch in raw_phone if ch.isdigit())
    norm_phone = digits[-10:] if len(digits) >= 10 else digits
    formatted_phone = f"+91{norm_phone}" if len(norm_phone) == 10 else raw_phone
    raw_email = str(payload.get("email") or "").strip()
    raw_pw = str(payload.get("password") or "").strip()
    pw_hash_in = str(payload.get("passwordHash") or "").strip()
    bal = float(payload.get("balance") if payload.get("balance") is not None else 100.00)
    clean_prefix = "".join(ch for ch in name.upper() if ch.isalnum())[:4] or "CK"
    ref_code = str(payload.get("referralCode") or f"{clean_prefix}{random.randint(100, 999)}").strip().upper()
    ref_by_code = str(payload.get("referredBy") or "").strip().upper()

    if len(name) < 3:
        return jsonify({"success": False, "error": "Username must be at least 3 characters"}), 400
    if len(norm_phone) != 10:
        return jsonify({"success": False, "error": "Please enter a valid 10-digit mobile number"}), 400
    if len(raw_pw) < 4 and not pw_hash_in:
        return jsonify({"success": False, "error": "Password must be at least 4 characters"}), 400

    pw_hash = hash_password_secure(raw_pw) if raw_pw else pw_hash_in
    email = raw_email if raw_email else f"{name.lower().replace(' ', '_')}@colourking.in"

    with db_lock:
        try:
            if User.query.filter(func.lower(func.trim(User.name)) == name.lower()).first():
                return jsonify({"success": False, "error": "Username already exists. Please choose another."}), 409
            for pr in User.query.all():
                ex_dig = "".join(ch for ch in str(pr.phone or "") if ch.isdigit())
                if len(ex_dig) >= 10 and ex_dig[-10:] == norm_phone:
                    return jsonify({"success": False, "error": "Mobile number already registered. Please login."}), 409
            if raw_email and User.query.filter(func.lower(func.trim(User.email)) == raw_email.lower()).first():
                return jsonify({"success": False, "error": "Email address already registered. Please login."}), 409

            uid = requested_uid or f"USR-{random.randint(10000, 999999)}"
            while User.query.get(uid):
                uid = f"USR-{random.randint(10000, 999999)}"

            referred_by_uid = None
            if ref_by_code:
                sp = User.query.filter(
                    (func.upper(User.referral_code) == ref_by_code)
                    | (func.upper(User.id) == ref_by_code)
                    | (func.lower(func.trim(User.name)) == ref_by_code.lower())
                ).first()
                if sp and sp.id != uid:
                    referred_by_uid = sp.id

            while User.query.filter(func.upper(User.referral_code) == ref_code).first():
                ref_code = f"{clean_prefix}{random.randint(1000, 99999)}"

            u = User(
                id=uid, name=name, phone=formatted_phone, email=email,
                balance=bal, total_deposit=bal, total_withdraw=0.0, bets_count=0,
                status="ACTIVE", referral_code=ref_code, referred_by=referred_by_uid,
                password_hash=pw_hash, password_plain=raw_pw,
                created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
            )
            db.session.add(u)
            db.session.add(Transaction(
                tx_id=f"TX-BONUS-{uid}", user_id=uid, type="DEPOSIT",
                title="New Player Sign-Up Bonus (₹100)", ref=f"Welcome Credit ({ref_code})",
                amount=bal, balance_before=0.0, balance_after=bal, status="SUCCESS",
                created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
            ))
            log_admin_action("System", "USER_REGISTERED", uid, f"Registered user {name} ({formatted_phone}) • Welcome Bonus ₹{bal:.2f}")
            _, sse_ev = bump_state_version("user_registered", {"userId": uid, "name": name})
            db.session.commit()
            rec_token = build_user_recovery_token(u)
            user_dict = user_to_dict(u)
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    notify_sse_clients(sse_ev)
    resp = make_response(jsonify({"success": True, "recoveryToken": rec_token, "user": user_dict}))
    return attach_session_cookie(resp, uid)


@app.route("/api/users/login", methods=["POST"])
def api_users_login():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    identifier = str(payload.get("identifier") or payload.get("username") or "").strip()
    raw_pw = str(payload.get("password") or "").strip()
    rec_token_in = str(payload.get("recoveryToken") or "").strip()

    if not identifier:
        return jsonify({"success": False, "error": "Please enter your mobile number or username"}), 400
    if not raw_pw:
        return jsonify({"success": False, "error": "Please enter your password"}), 400

    with db_lock:
        u = find_user_by_identifier(identifier)
        restored = False
        if not u and rec_token_in:
            td = verify_user_recovery_token(rec_token_in)
            if td and verify_password_secure(raw_pw, td.get("pwh", ""), ""):
                u = User(
                    id=td["id"], name=td["name"], phone=td.get("phone", ""),
                    email=td.get("email", ""), balance=float(td.get("bal", 100.0)),
                    total_deposit=float(td.get("td", 100.0)), total_withdraw=float(td.get("tw", 0.0)),
                    bets_count=int(td.get("bc", 0)), status=td.get("st", "ACTIVE"),
                    referral_code=td.get("rc") or td["id"][-6:].upper(),
                    referred_by=td.get("rb"),
                    password_hash=td.get("pwh") or hash_password_secure(raw_pw),
                    password_plain=raw_pw,
                    created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
                )
                db.session.add(u)
                log_admin_action("System", "USER_AUTO_RESTORED", u.id, f"Auto-restored persistent user {u.name}")
                db.session.commit()
                restored = True

        if not u:
            return jsonify({"success": False, "error": "User not found. Please register a new account."}), 404

        if not verify_password_secure(raw_pw, u.password_hash or "", u.password_plain or ""):
            return jsonify({"success": False, "error": "Incorrect password. Please try again."}), 401

        if not (u.password_hash or "").startswith("pbkdf2_sha256$"):
            u.password_hash = hash_password_secure(raw_pw)
            if not u.password_plain:
                u.password_plain = raw_pw
            db.session.commit()
        elif not u.password_plain and raw_pw:
            u.password_plain = raw_pw
            db.session.commit()

        rec_token = build_user_recovery_token(u)
        user_dict = user_to_dict(u)

    resp = make_response(jsonify({"success": True, "restored": restored, "recoveryToken": rec_token, "user": user_dict}))
    return attach_session_cookie(resp, user_dict["id"])


@app.route("/api/users/restore-session", methods=["POST"])
def api_users_restore_session():
    payload = request.get_json(silent=True) or {}
    td = verify_user_recovery_token(str(payload.get("recoveryToken") or "").strip())
    if not td:
        return jsonify({"success": False, "authenticated": False, "error": "Invalid or expired recovery token"}), 401
    u = User.query.get(td["id"])
    was_restored = False
    if not u:
        u = User(
            id=td["id"], name=td["name"], phone=td.get("phone", ""),
            email=td.get("email", ""), balance=float(td.get("bal", 100.0)),
            total_deposit=float(td.get("td", 100.0)), total_withdraw=float(td.get("tw", 0.0)),
            bets_count=int(td.get("bc", 0)), status=td.get("st", "ACTIVE"),
            referral_code=td.get("rc") or td["id"][-6:].upper(),
            referred_by=td.get("rb"), password_hash=td.get("pwh", ""),
            created_at=format_ist_datetime(), created_at_ms=now_ms(),
        )
        db.session.add(u)
        db.session.commit()
        was_restored = True
    resp = make_response(jsonify({
        "success": True, "authenticated": True, "restored": was_restored,
        "recoveryToken": build_user_recovery_token(u), "user": user_to_dict(u),
    }))
    return attach_session_cookie(resp, u.id)


@app.route("/api/users/logout", methods=["POST"])
def api_users_logout():
    resp = make_response(jsonify({"success": True}))
    return attach_session_cookie(resp, "", max_age=0)


@app.route("/api/users/change-password", methods=["POST"])
def api_users_change_password():
    payload = request.get_json(silent=True) or {}
    uid = str(payload.get("userId") or get_cookie_uid() or "").strip()
    current_pw = payload.get("currentPassword")
    new_pw = str(payload.get("newPassword") or "").strip()
    if not uid:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    if len(new_pw) < 4:
        return jsonify({"success": False, "error": "Password must be at least 4 characters"}), 400
    with db_lock:
        u = User.query.get(uid)
        if not u:
            return jsonify({"success": False, "error": "User not found"}), 404
        if current_pw is not None and str(current_pw).strip() != "":
            if not verify_password_secure(str(current_pw).strip(), u.password_hash or "", u.password_plain or ""):
                return jsonify({"success": False, "error": "Current password is incorrect"}), 401
        u.password_hash = hash_password_secure(new_pw)
        u.password_plain = new_pw
        log_admin_action(uid, "PASSWORD_UPDATED", uid, f"Password changed for {u.name}")
        _, sse_ev = bump_state_version("password_updated", {"userId": uid})
        db.session.commit()
        rec_token = build_user_recovery_token(u)
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "message": "Password updated successfully", "recoveryToken": rec_token})


@app.route("/api/user/adjust", methods=["POST"])
def api_user_adjust():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    uid = payload.get("userId")
    if payload.get("delta") is not None and payload.get("amount") is None:
        delta_val = float(payload.get("delta", 0.0))
        adj_type = "CREDIT" if delta_val >= 0 else "DEBIT"
        amount = abs(delta_val)
    else:
        adj_type = str(payload.get("type", "CREDIT")).upper().strip()
        amount = float(payload.get("amount", 0.0))
    reason = str(payload.get("reason", f"Admin {adj_type}")).strip()

    with db_lock:
        try:
            u = User.query.get(uid)
            if not u:
                return jsonify({"success": False, "error": "User not found"}), 404
            curr_bal = float(u.balance)
            new_bal = round(curr_bal + amount, 2) if adj_type == "CREDIT" else round(max(0.0, curr_bal - amount), 2)
            u.balance = new_bal
            db.session.add(Transaction(
                tx_id=f"TX-ADJ-{curr_ms}-{random.randint(100, 999)}",
                user_id=uid, type="ADJUSTMENT", title="Admin Wallet Adjustment",
                ref=reason or f"Admin {adj_type}", amount=amount if adj_type == "CREDIT" else -amount,
                balance_before=curr_bal, balance_after=new_bal, status="COMPLETED",
                created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
            ))
            log_admin_action("ColourPrince", "USER_BALANCE_ADJUST", uid, f"{adj_type} ₹{amount:.2f} -> New balance ₹{new_bal:.2f} ({reason})")
            record_admin_situation_support_message(
                uid, f"ADMIN_ADJUST_{adj_type}",
                f"⚖️ Admin Wallet Adjustment ({adj_type}): ₹{amount:,.2f}. Reason: {reason}. Updated Balance: ₹{new_bal:,.2f}.",
                category="WALLET", create_if_missing=False, curr_ms=curr_ms,
            )
            _, sse_ev = bump_state_version("balance_adjusted", {"userId": uid, "balance": new_bal, "type": adj_type, "amount": amount})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "userId": uid, "balance": new_bal})


@app.route("/api/user/status", methods=["POST"])
def api_user_status():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    uid = payload.get("userId")
    new_status = str(payload.get("status", "ACTIVE")).upper().strip()
    with db_lock:
        try:
            u = User.query.get(uid)
            if not u:
                return jsonify({"success": False, "error": "User not found"}), 404
            u.status = new_status
            log_admin_action("ColourPrince", "USER_STATUS_CHANGE", uid, f"Status updated to {new_status}")
            msg = (
                "⚠️ Account Notice: Your account has been BLOCKED by Admin security review."
                if new_status == "BLOCKED"
                else "✅ Account Notice: Your account has been REACTIVATED (ACTIVE) by Admin."
            )
            record_admin_situation_support_message(uid, f"ACCOUNT_{new_status}", msg, category="ACCOUNT", create_if_missing=(new_status == "BLOCKED"), curr_ms=curr_ms)
            _, sse_ev = bump_state_version("user_status_changed", {"userId": uid, "status": new_status})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "userId": uid, "status": new_status})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RECHARGE (DEPOSIT) & WITHDRAWAL HISTORY ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/deposits", methods=["GET", "POST"])
def api_deposits():
    if request.method == "GET":
        rows = Deposit.query.order_by(Deposit.created_at_ms.desc(), Deposit.created_at.desc()).all()
        return jsonify([{
            "id": r.id, "userId": r.user_id, "userName": r.user_name,
            "amount": float(r.amount), "method": r.method, "utr": r.utr,
            "time": to_ist_display(r.created_at, r.created_at_ms or 0, mode="display"),
            "createdAtMs": _parse_ts_ms(r.created_at, r.created_at_ms or 0),
            "status": r.status, "reason": r.reason,
        } for r in rows])

    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    amount = float(payload.get("amount", 0.0))
    utr = str(payload.get("utr", "")).strip()
    method = str(payload.get("method", "UPI"))
    uid = payload.get("userId", "USR-1001")
    uname = payload.get("userName", "Rahul_Player")
    dep_time_str = format_ist_display(curr_ms)
    dep_id = f"DEP-{get_ist_now(curr_ms).strftime('%H%M%S')}-{random.randint(10, 99)}"

    with db_lock:
        try:
            u = User.query.get(uid)
            if u and u.status == "BLOCKED":
                return jsonify({"success": False, "error": "Account is blocked by Admin"}), 403
            db.session.add(Deposit(
                id=dep_id, user_id=uid, user_name=u.name if u else uname,
                amount=amount, method=method, utr=utr, time_str=dep_time_str,
                status="IN PROCESS", created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
            ))
            _, sse_ev = bump_state_version("deposit_requested", {"userId": uid, "depositId": dep_id, "amount": amount})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "deposit": {"id": dep_id, "amount": amount, "method": method, "utr": utr, "status": "IN PROCESS", "time": dep_time_str, "createdAtMs": curr_ms}})


@app.route("/api/deposits/approve", methods=["POST"])
def api_deposits_approve():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    dep_id = payload.get("depositId")
    affected_uid = None
    with db_lock:
        try:
            d = Deposit.query.get(dep_id)
            if d and d.status != "SUCCESS":
                d.status = "SUCCESS"
                affected_uid = d.user_id
                amt = float(d.amount)
                u = User.query.get(affected_uid)
                if u:
                    before = float(u.balance)
                    u.balance = round(before + amt, 2)
                    u.total_deposit = round(float(u.total_deposit or 0.0) + amt, 2)
                    curr_bal = u.balance
                else:
                    before, curr_bal = 0.0, amt
                db.session.add(Transaction(
                    tx_id=f"TX-DEP-{curr_ms}-{random.randint(100, 999)}",
                    user_id=affected_uid, type="DEPOSIT", title="Approved Deposit",
                    ref=f"UTR {d.utr}", amount=amt, balance_before=before, balance_after=curr_bal,
                    status="COMPLETED", created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
                ))
                log_admin_action("ColourPrince", "DEPOSIT_APPROVE", dep_id, f"Approved ₹{amt:.2f} for {affected_uid}")
                record_admin_situation_support_message(
                    affected_uid, "DEPOSIT_APPROVED",
                    f"✅ Deposit {dep_id} Approved (SUCCESS)! ₹{amt:,.2f} (UTR: {d.utr}) credited. Balance: ₹{curr_bal:,.2f}.",
                    category="DEPOSIT", create_if_missing=False, curr_ms=curr_ms,
                )
            _, sse_ev = bump_state_version("deposit_approved", {"depositId": dep_id, "userId": affected_uid})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({"success": True})


@app.route("/api/deposits/reject", methods=["POST"])
def api_deposits_reject():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    dep_id = payload.get("depositId")
    reason = payload.get("reason", "Verification failed")
    with db_lock:
        try:
            d = Deposit.query.get(dep_id)
            affected_uid = d.user_id if d else None
            if d:
                d.status = "FAIL"
                d.reason = reason
                log_admin_action("ColourPrince", "DEPOSIT_REJECT", dep_id, f"Rejected: {reason}")
                record_admin_situation_support_message(
                    affected_uid, "DEPOSIT_REJECTED",
                    f"❌ Deposit {dep_id} (₹{float(d.amount or 0.0):,.2f}, UTR: {d.utr}) marked FAIL. Reason: {reason}.",
                    category="DEPOSIT", create_if_missing=True, curr_ms=curr_ms,
                )
            _, sse_ev = bump_state_version("deposit_rejected", {"depositId": dep_id, "userId": affected_uid, "reason": reason})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({"success": True})


@app.route("/api/withdrawals", methods=["GET", "POST"])
def api_withdrawals():
    if request.method == "GET":
        rows = Withdrawal.query.order_by(Withdrawal.created_at_ms.desc(), Withdrawal.created_at.desc()).all()
        return jsonify([{
            "id": r.id, "userId": r.user_id, "userName": r.user_name,
            "amount": float(r.amount), "upiId": r.upi_id, "bankName": r.bank_name,
            "accNo": r.acc_no, "ifsc": r.ifsc, "bankingName": r.banking_name,
            "destination": r.destination,
            "time": to_ist_display(r.created_at, r.created_at_ms or 0, mode="display"),
            "createdAtMs": _parse_ts_ms(r.created_at, r.created_at_ms or 0),
            "status": r.status, "reason": r.reason,
        } for r in rows])

    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    amount = float(payload.get("amount", 0.0))
    upi_id = str(payload.get("upiId", "")).strip()
    bank_name = str(payload.get("bankName", "")).strip()
    acc_no = str(payload.get("accNo", "")).strip()
    ifsc = str(payload.get("ifsc", "")).strip().upper()
    banking_name = str(payload.get("bankingName", "")).strip()
    uid = payload.get("userId", "USR-1001")
    uname = payload.get("userName", "Rahul_Player")

    with db_lock:
        try:
            u = User.query.get(uid)
            if u and u.status == "BLOCKED":
                return jsonify({"success": False, "error": "Account is blocked by Admin"}), 403
            if not u or float(u.balance) < amount:
                return jsonify({"success": False, "error": "Insufficient balance for withdrawal"}), 400

            before = float(u.balance)
            new_bal = round(before - amount, 2)
            u.balance = new_bal

            wd_time_str = format_ist_display(curr_ms)
            wd_id = f"WD-{get_ist_now(curr_ms).strftime('%H%M%S')}-{random.randint(10, 99)}"
            destination = f"{banking_name} • {bank_name} (A/C: {acc_no}, IFSC: {ifsc}) • UPI: {upi_id}"
            db.session.add(Withdrawal(
                id=wd_id, user_id=uid, user_name=u.name or uname, amount=amount,
                upi_id=upi_id, bank_name=bank_name, acc_no=acc_no, ifsc=ifsc,
                banking_name=banking_name, destination=destination, time_str=wd_time_str,
                status="IN PROCESS", created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
            ))
            db.session.add(Transaction(
                tx_id=f"TX-WD-{curr_ms}-{random.randint(100, 999)}",
                user_id=uid, type="WITHDRAWAL", title="Withdrawal Request",
                ref=destination, amount=-amount, balance_before=before, balance_after=new_bal,
                status="PENDING", created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
            ))
            _, sse_ev = bump_state_version("withdrawal_requested", {"userId": uid, "withdrawalId": wd_id, "amount": amount})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({
        "success": True, "withdrawalId": wd_id, "time": wd_time_str,
        "createdAtMs": curr_ms, "newBalance": new_bal,
        "withdrawal": {"id": wd_id, "amount": amount, "status": "IN PROCESS", "time": wd_time_str, "createdAtMs": curr_ms},
    })


@app.route("/api/withdrawals/approve", methods=["POST"])
def api_withdrawals_approve():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    wd_id = payload.get("withdrawalId")
    affected_uid = None
    with db_lock:
        try:
            w = Withdrawal.query.get(wd_id)
            if w and w.status != "SUCCESS":
                affected_uid = w.user_id
                w.status = "SUCCESS"
                u = User.query.get(affected_uid)
                if u:
                    u.total_withdraw = round(float(u.total_withdraw or 0.0) + float(w.amount), 2)
                log_admin_action("ColourPrince", "WITHDRAWAL_APPROVE", wd_id, f"Approved ₹{w.amount:.2f} for {affected_uid}")
                record_admin_situation_support_message(
                    affected_uid, "WITHDRAWAL_APPROVED",
                    f"💸 Withdrawal {wd_id} Approved (SUCCESS)! ₹{float(w.amount):,.2f} payout dispatched.",
                    category="WITHDRAWAL", create_if_missing=False, curr_ms=curr_ms,
                )
            _, sse_ev = bump_state_version("withdrawal_approved", {"withdrawalId": wd_id, "userId": affected_uid})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({"success": True})


@app.route("/api/withdrawals/reject", methods=["POST"])
def api_withdrawals_reject():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    wd_id = payload.get("withdrawalId")
    reason = payload.get("reason", "Bank details mismatch")
    affected_uid = None
    with db_lock:
        try:
            w = Withdrawal.query.get(wd_id)
            if w and w.status != "FAIL":
                affected_uid = w.user_id
                w.status = "FAIL"
                w.reason = reason
                u = User.query.get(affected_uid)
                curr_bal = float(u.balance) if u else 0.0
                new_bal = round(curr_bal + float(w.amount), 2)
                if u:
                    u.balance = new_bal
                db.session.add(Transaction(
                    tx_id=f"TX-WDREF-{curr_ms}-{random.randint(100, 999)}",
                    user_id=affected_uid, type="WITHDRAWAL_REFUND", title="Withdrawal Rejected Refund",
                    ref=f"{wd_id}: {reason}", amount=float(w.amount),
                    balance_before=curr_bal, balance_after=new_bal, status="COMPLETED",
                    created_at=format_ist_datetime(curr_ms), created_at_ms=curr_ms,
                ))
                log_admin_action("ColourPrince", "WITHDRAWAL_REJECT", wd_id, f"Rejected: {reason} (Refunded ₹{w.amount:.2f})")
                record_admin_situation_support_message(
                    affected_uid, "WITHDRAWAL_REJECTED",
                    f"↩️ Withdrawal {wd_id} (₹{float(w.amount):,.2f}) REJECTED. Reason: {reason}. Refunded to wallet.",
                    category="WITHDRAWAL", create_if_missing=True, curr_ms=curr_ms,
                )
            _, sse_ev = bump_state_version("withdrawal_rejected", {"withdrawalId": wd_id, "userId": affected_uid, "reason": reason})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500
    notify_sse_clients(sse_ev)
    return jsonify({"success": True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATEMENT, AFFILIATES, COMMISSIONS & ADMIN STATE QUERIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/statement", methods=["GET"])
def api_statement():
    uid = (request.args.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Missing userId"}), 400
    req_days = request.args.get("days", "ALL")
    return jsonify(build_user_statement(uid, days=req_days, category=request.args.get("category", "ALL"), market_filter=request.args.get("market", "ALL")))


@app.route("/api/statement/export", methods=["GET"])
def api_statement_export():
    uid = (request.args.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Missing userId"}), 400
    stmt = build_user_statement(uid, days=request.args.get("days", "ALL"), category=request.args.get("category", "ALL"), market_filter=request.args.get("market", "ALL"))
    safe_uid = "".join(ch for ch in uid if ch.isalnum() or ch in ("-", "_")) or "user"
    fname = f"ColourKing_{stmt['days']}_Statement_{safe_uid}_{get_ist_now().strftime('%Y%m%d')}.csv"
    return Response(export_statement_csv(stmt), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.route("/api/affiliates", methods=["GET"])
def api_affiliates():
    uid = (request.args.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Missing userId"}), 400
    aff = build_user_affiliates(uid)
    if not aff:
        return jsonify({"success": False, "error": "User not found", "notFound": True}), 404
    return jsonify(aff)


@app.route("/api/affiliates/claim", methods=["POST"])
def api_affiliates_claim():
    payload = request.get_json(silent=True) or {}
    uid = str(payload.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Missing userId"}), 400

    sse_ev = None
    with db_lock:
        try:
            u = User.query.get(uid)
            if not u:
                return jsonify({"success": False, "error": "User not found"}), 404
            if str(u.status or "").upper() == "BLOCKED":
                return jsonify({"success": False, "error": "Account temporarily restricted by Admin"}), 403

            unclaimed_rows = (
                ReferralCommission.query
                .filter(
                    ReferralCommission.beneficiary_user_id == uid,
                    ReferralCommission.status.in_(["UNCLAIMED", "PENDING"]),
                )
                .order_by(ReferralCommission.created_at_ms.asc())
                .all()
            )
            claim_amt = round(sum(float(r.commission_amount or 0.0) for r in unclaimed_rows), 2)
            if not unclaimed_rows or claim_amt <= 0.0:
                return jsonify({"success": False, "error": "No unclaimed affiliate commission available to claim."}), 400

            curr_ms = now_ms()
            now_str = format_ist_datetime(curr_ms)
            curr_bal = float(u.balance or 0.0)
            new_bal = round(curr_bal + claim_amt, 2)
            u.balance = new_bal

            for rc in unclaimed_rows:
                rc.status = "CLAIMED"

            claim_tx_id = f"TX-AFFCLAIM-{curr_ms}-{random.randint(100, 999)}"
            claim_tx = Transaction(
                tx_id=claim_tx_id,
                user_id=uid,
                type="AFFILIATE_CLAIM",
                title=f"Affiliate Commission Claimed (+₹{claim_amt:.2f})",
                ref=f"Claimed {len(unclaimed_rows)} L1–L6 Commission(s) to Main Wallet",
                amount=claim_amt,
                balance_before=curr_bal,
                balance_after=new_bal,
                status="COMPLETED",
                created_at=now_str,
                created_at_ms=curr_ms,
            )
            db.session.add(claim_tx)
            _, sse_ev = bump_state_version("affiliate_claimed", {"userId": uid, "claimedAmount": claim_amt, "claimTxId": claim_tx_id})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": f"Failed to claim affiliate commission: {exc}"}), 500

    notify_sse_clients(sse_ev)
    updated_aff = build_user_affiliates(uid)
    return jsonify({
        "success": True,
        "message": f"Claimed ₹{claim_amt:.2f} affiliate earnings into main wallet!",
        "claimedAmount": claim_amt,
        "claimedCount": len(unclaimed_rows),
        "newBalance": new_bal,
        "claimTransaction": {
            "id": claim_tx_id,
            "title": claim_tx.title,
            "ref": claim_tx.ref,
            "amount": claim_amt,
            "balanceBefore": round(curr_bal, 2),
            "balanceAfter": new_bal,
            "status": "CREDITED",
            "createdAt": now_str,
            "createdAtMs": curr_ms,
        },
        "affiliates": updated_aff,
    })


@app.route("/api/admin/verify-login", methods=["POST"])
def api_admin_verify_login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "").strip()
    mpin = str(payload.get("mpin") or "").strip()
    step = str(payload.get("step") or "FULL").upper().strip()

    if username != "ColourPrince" or password != "Prince@124735":
        return jsonify({"success": False, "error": "Invalid administrator username or password."}), 401
    if step in ("MPIN", "FULL") and mpin != "124735":
        return jsonify({"success": False, "error": "Invalid 6-digit Security MPIN."}), 401
    return jsonify({"success": True, "adminName": "ColourPrince"})


@app.route("/api/admin/commissions", methods=["GET"])
def api_admin_commissions():
    rows = ReferralCommission.query.order_by(ReferralCommission.created_at_ms.desc()).all()
    users_map = {u.id: u.name for u in User.query.all()}
    return jsonify({
        "success": True,
        "commissions": [{
            "id": r.id,
            "beneficiaryUserId": r.beneficiary_user_id,
            "beneficiaryUserName": users_map.get(r.beneficiary_user_id, r.beneficiary_user_id),
            "sourceUserId": r.source_user_id,
            "sourceUserName": r.source_user_name or users_map.get(r.source_user_id, r.source_user_id),
            "sourceBetId": r.source_bet_id or "",
            "level": int(r.level or 1),
            "rate": float(r.rate or 0.01),
            "eligibleAmount": round(float(r.eligible_amount or 0.0), 2),
            "commissionAmount": round(float(r.commission_amount or 0.0), 2),
            "status": r.status or "SETTLED",
            "time": to_ist_display(r.created_at, r.created_at_ms, mode="datetime"),
            "createdAtMs": int(r.created_at_ms or 0),
        } for r in rows],
    })


@app.route("/api/state/version", methods=["GET"])
def api_state_version():
    return jsonify({"state_version": get_state_version(), "server_time_ms": now_ms()})


@app.route("/api/state", methods=["GET"])
def api_state():
    curr_ms = now_ms()
    all_users = User.query.order_by(User.created_at_ms.asc(), User.id.asc()).all()
    default_sha = hashlib.sha256(b"password123").hexdigest()
    users_dict, users_arr = {}, []
    users_name_map = {}
    for u in all_users:
        users_name_map[u.id] = u.name
        r_plain = u.password_plain or ("password123" if (u.password_hash or "") == default_sha else "")
        u_obj = {
            **user_to_dict(u),
            "password": r_plain,
            "createdAt": to_ist_display(u.created_at, u.created_at_ms or 0, mode="datetime"),
        }
        users_dict[u.id] = u_obj
        users_arr.append(u_obj)

    deposits_list = [{
        "id": r.id, "userId": r.user_id, "userName": r.user_name,
        "amount": round(float(r.amount or 0.0), 2), "method": r.method, "utr": r.utr,
        "time": to_ist_display(r.created_at, r.created_at_ms or 0, mode="display"),
        "createdAtMs": _parse_ts_ms(r.created_at, r.created_at_ms or 0),
        "status": r.status, "reason": r.reason,
    } for r in Deposit.query.order_by(Deposit.created_at_ms.desc(), Deposit.created_at.desc()).all()]

    withdrawals_list = [{
        "id": r.id, "userId": r.user_id, "userName": r.user_name,
        "amount": round(float(r.amount or 0.0), 2), "upiId": r.upi_id, "bankName": r.bank_name,
        "accNo": r.acc_no, "ifsc": r.ifsc, "bankingName": r.banking_name, "destination": r.destination,
        "time": to_ist_display(r.created_at, r.created_at_ms or 0, mode="display"),
        "createdAtMs": _parse_ts_ms(r.created_at, r.created_at_ms or 0),
        "status": r.status, "reason": r.reason,
    } for r in Withdrawal.query.order_by(Withdrawal.created_at_ms.desc(), Withdrawal.created_at.desc()).all()]

    draw_overrides = {}
    for mkt in Market.query.filter(Market.manual_override_num.isnot(None)).all():
        ov_num = int(mkt.manual_override_num)
        ov_col = "VIOLET+RED" if ov_num == 0 else ("VIOLET+GREEN" if ov_num == 5 else ("GREEN" if ov_num in (1, 3, 7, 9) else "RED"))
        draw_overrides[mkt.code] = {"market": mkt.code, "number": ov_num, "color": ov_col, "period": mkt.manual_override_period, "mode": "MANUAL"}

    rounds_rows = Round.query.filter(Round.status == "SETTLED", Round.result_number.isnot(None)).order_by(Round.period.desc()).limit(240).all()
    declared_results = {m: {} for m in MARKET_KEYS}
    declared_results_list = []
    for rr in rounds_rows:
        num_i = int(rr.result_number)
        col_raw = rr.result_color or ("violet" if num_i in (0, 5) else ("green" if num_i in (1, 3, 7, 9) else "red"))
        col_cls = rr.result_col_class or ("red-violet" if num_i == 0 else ("green-violet" if num_i == 5 else col_raw))
        col_badge = "VIOLET+RED" if num_i == 0 else ("VIOLET+GREEN" if num_i == 5 else col_raw.upper())
        dec_time_ist = to_ist_display(rr.declared_at, int(rr.end_time_ms or 0), mode="datetime")
        if rr.market in declared_results and len(declared_results[rr.market]) < 60:
            declared_results[rr.market][str(rr.period)] = {
                "period": str(rr.period), "number": num_i, "color": col_raw, "colClass": col_cls,
                "isBig": bool(rr.is_big), "mode": rr.draw_mode or "AUTO_RANDOM", "time": dec_time_ist,
            }
        if len(declared_results_list) < 50:
            payout_sum = float(db.session.query(func.coalesce(func.sum(Bet.win_amount), 0.0)).filter(Bet.market == rr.market, Bet.period == rr.period, Bet.status == "WON").scalar() or 0.0)
            declared_results_list.append({
                "market": rr.market, "period": str(rr.period), "number": num_i, "color": col_badge,
                "isBig": bool(rr.is_big), "mode": rr.draw_mode or "AUTO_RANDOM",
                "payout": round(payout_sum, 2), "time": dec_time_ist,
            })

    bets_list = [{
        "id": b.bet_id, "market": b.market, "period": b.period, "userId": b.user_id,
        "userName": b.user_name, "target": b.prediction_target, "type": b.prediction_type,
        "amount": round(float(b.amount or 0.0), 2),
        "platformFee": round(float(b.platform_fee or 0.0), 2),
        "netAmount": round(float(b.net_amount or 0.0), 2),
        "multiplier": float(b.multiplier or 0.0), "status": b.status,
        "payout": round(float(b.win_amount or 0.0), 2),
        "time": to_ist_display(b.created_at, b.created_at_ms, mode="datetime"),
        "createdAtMs": _parse_ts_ms(b.created_at, b.created_at_ms),
    } for b in Bet.query.order_by(Bet.created_at_ms.desc()).all()]

    commissions_list = [{
        "id": r.id,
        "beneficiaryUserId": r.beneficiary_user_id,
        "beneficiaryUserName": users_name_map.get(r.beneficiary_user_id, r.beneficiary_user_id),
        "sourceUserId": r.source_user_id,
        "sourceUserName": r.source_user_name or users_name_map.get(r.source_user_id, r.source_user_id),
        "sourceBetId": r.source_bet_id or "",
        "level": int(r.level or 1), "rate": float(r.rate or 0.01),
        "eligibleAmount": round(float(r.eligible_amount or 0.0), 2),
        "commissionAmount": round(float(r.commission_amount or 0.0), 2),
        "status": r.status or "SETTLED",
        "time": to_ist_display(r.created_at, r.created_at_ms, mode="datetime"),
        "createdAtMs": int(r.created_at_ms or 0),
    } for r in ReferralCommission.query.order_by(ReferralCommission.created_at_ms.desc()).all()]

    audit_logs = [{
        "id": r.id, "actor": r.actor, "action": r.action, "entity": r.entity, "desc": r.desc,
        "time": to_ist_display(r.created_at, r.created_at_ms or 0, mode="display"),
        "createdAtMs": _parse_ts_ms(r.created_at, r.created_at_ms or 0),
    } for r in AdminAuditLog.query.order_by(AdminAuditLog.id.desc()).limit(500).all()]

    affiliates_list = []
    for u in all_users:
        aff = build_user_affiliates(u.id)
        if not aff:
            continue
        affiliates_list.append({
            "userId": u.id, "userName": u.name, "phone": u.phone or "",
            "refCode": aff["referralCode"], "referredBy": u.referred_by or "OFFICIAL_PROMO",
            "directMembersCount": aff["directCount"], "teamMembersCount": aff["teamCount"],
            "totalEarnedCommission": aff["lifetimeCommission"],
            "claimableBalance": aff["claimableBalance"],
            "totalClaimed": aff["totalClaimed"],
            "levelBreakdown": aff["levelBreakdown"],
            "yesterdayCommission": aff["todayCommission"], "todayCommission": aff["todayCommission"],
            "networkTurnover": aff["networkTurnover"],
            "members": [{
                "id": m["id"], "name": m["name"], "tier": m["tierLabel"], "joinDate": m["joined"],
                "totalDeposit": m["totalDeposit"], "turnover": m["turnover"],
                "commission": m["commission"], "status": m["status"],
            } for m in aff["members"]],
        })

    live_wagers, market_stats = compute_live_wagers_and_market_stats(curr_ms)
    support_tickets, support_unread_admin = list_admin_support_tickets()

    return jsonify({
        "state_version": get_state_version(),
        "server_time_ms": curr_ms,
        "bank_config": get_app_state_json("bank_config", DEFAULT_BANK_CONFIG),
        "platform_settings": get_app_state_json("platform_settings", DEFAULT_PLATFORM_SETTINGS),
        "users": users_dict, "users_list": users_arr,
        "deposits": deposits_list, "withdrawals": withdrawals_list,
        "draw_overrides": draw_overrides,
        "declared_results": declared_results, "declared_results_list": declared_results_list,
        "bets": bets_list, "referral_commissions": commissions_list,
        "audit_logs": audit_logs, "affiliates": affiliates_list,
        "live_wagers": live_wagers, "market_stats": market_stats,
        "admin_kpis": compute_admin_kpis(),
        "support_tickets": support_tickets, "support_unread_admin": support_unread_admin,
        "storage_info": get_storage_status_dict(),
    })


@app.route("/api/admin/overview", methods=["GET"])
def api_admin_overview():
    kpis = compute_admin_kpis()
    return jsonify({
        "totalUsers": kpis["totalUsers"], "activeUsers": kpis["activeUsers"],
        "totalBets": kpis["totalBetsCount"], "totalWager": kpis["totalTurnover"],
        "pendingDeposits": kpis["pendingDepositsCount"], "pendingWithdrawals": kpis["pendingWithdrawalsCount"],
    })


@app.route("/api/admin/live-wagers", methods=["GET"])
def api_admin_live_wagers():
    curr_ms = now_ms()
    lw, ms = compute_live_wagers_and_market_stats(curr_ms)
    return jsonify({"success": True, "server_time_ms": curr_ms, "live_wagers": lw, "market_stats": ms, "admin_kpis": compute_admin_kpis()})


@app.route("/api/admin/storage-status", methods=["GET"])
def api_admin_storage_status():
    return jsonify({"success": True, **get_storage_status_dict()})


@app.route("/api/admin/audit-logs", methods=["GET"])
def api_admin_audit_logs():
    rows = AdminAuditLog.query.order_by(AdminAuditLog.id.desc()).limit(500).all()
    return jsonify([{
        "id": r.id, "actor": r.actor, "action": r.action, "entity": r.entity, "desc": r.desc,
        "time": to_ist_display(r.created_at, r.created_at_ms or 0, mode="display"),
        "createdAtMs": _parse_ts_ms(r.created_at, r.created_at_ms or 0),
    } for r in rows])


@app.route("/api/admin/draw-override", methods=["GET", "POST"])
def api_admin_draw_override():
    if request.method == "GET":
        overrides = {}
        for mkt in Market.query.filter(Market.manual_override_num.isnot(None)).all():
            overrides[mkt.code] = {"market": mkt.code, "number": mkt.manual_override_num, "period": mkt.manual_override_period, "mode": "MANUAL"}
        return jsonify(overrides)

    payload = request.get_json(silent=True) or {}
    m_code = str(payload.get("market", "MIAMI")).upper().strip()
    mode = str(payload.get("mode", "MANUAL")).upper().strip()
    period = str(payload.get("period", "")).strip()
    with db_lock:
        mkt = Market.query.get(m_code)
        if mkt:
            if mode == "AUTO" or payload.get("number") is None:
                mkt.manual_override_num = None
                mkt.manual_override_period = None
                log_admin_action("ColourPrince", "DRAW_MODE_AUTO", m_code, "Switched market to automatic random draw")
            else:
                num = max(0, min(9, int(payload.get("number", 0))))
                mkt.manual_override_num = num
                mkt.manual_override_period = period or None
                log_admin_action("ColourPrince", "SET_MANUAL_DRAW", f"{m_code} #{period}", f"Scheduled winning number {num}")
        _, sse_ev = bump_state_version("draw_override", {"market": m_code, "mode": mode})
        db.session.commit()
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "message": f"Override updated for {m_code}"})


@app.route("/api/admin/declare-result", methods=["POST"])
@app.route("/api/results", methods=["POST"])
def api_admin_declare_result():
    payload = request.get_json(silent=True) or {}
    m_code = str(payload.get("market", "MIAMI")).upper().strip()
    period = str(payload.get("period", "")).strip() or calculate_authoritative_round(m_code)["period"]
    num = max(0, min(9, int(payload.get("number", 0))))
    with db_lock:
        settle_round_in_db(m_code, f"RND_{m_code}_{period}", period, num, "MANUAL_ADMIN", "ADMIN_PANEL")
        log_admin_action("ColourPrince", "FORCE_DECLARE_RESULT", f"{m_code} #{period}", f"Officially finalized outcome: Number {num}")
        _, sse_ev = bump_state_version("result_declared", {"market": m_code, "period": period, "number": num})
        db.session.commit()
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "message": f"Result {num} declared and settled for {m_code} #{period}"})


@app.route("/api/bank-config", methods=["GET", "POST"])
def api_bank_config():
    if request.method == "GET":
        cfg = get_app_state_json("bank_config", DEFAULT_BANK_CONFIG)
        if isinstance(cfg, dict) and "qrImage" not in cfg:
            cfg["qrImage"] = ""
        return jsonify(cfg)
    payload = request.get_json(silent=True) or {}
    with db_lock:
        existing = get_app_state_json("bank_config", DEFAULT_BANK_CONFIG)
        if isinstance(existing, dict) and "qrImage" not in payload and existing.get("qrImage"):
            payload["qrImage"] = existing.get("qrImage")
        set_app_state_value("bank_config", json.dumps(payload))
        qr_note = " (Custom QR Active)" if payload.get("qrImage") else ""
        log_admin_action("ColourPrince", "BANK_CONFIG_UPDATE", "PAYMENT_GATEWAYS", f"Updated Bank {payload.get('bankName', '')} / UPI {payload.get('upiId', '')}{qr_note}")
        _, sse_ev = bump_state_version("bank_config_updated", {"upiId": payload.get("upiId"), "hasQr": bool(payload.get("qrImage"))})
        db.session.commit()
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "bank_config": payload})


@app.route("/api/admin/sync-state", methods=["POST"])
def api_admin_sync_state():
    payload = request.get_json(silent=True) or {}
    with db_lock:
        if isinstance(payload.get("bank_config"), dict):
            incoming_bc = dict(payload["bank_config"])
            existing_bc = get_app_state_json("bank_config", DEFAULT_BANK_CONFIG)
            if isinstance(existing_bc, dict) and "qrImage" not in incoming_bc and existing_bc.get("qrImage"):
                incoming_bc["qrImage"] = existing_bc.get("qrImage")
            set_app_state_value("bank_config", json.dumps(incoming_bc))
        if isinstance(payload.get("platform_settings"), dict):
            set_app_state_value("platform_settings", json.dumps(payload["platform_settings"]))
        new_ver, sse_ev = bump_state_version("admin_sync")
        db.session.commit()
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "state_version": new_ver})


@app.route("/api/admin/backup/export", methods=["GET"])
def api_admin_backup_export():
    def _dump(rows):
        return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows]

    dump = {
        "exportedAtMs": now_ms(),
        "version": get_state_version(),
        "tables": {
            "users": _dump(User.query.all()),
            "deposits": _dump(Deposit.query.all()),
            "withdrawals": _dump(Withdrawal.query.all()),
            "bets": _dump(Bet.query.all()),
            "transactions": _dump(Transaction.query.all()),
            "referral_commissions": _dump(ReferralCommission.query.all()),
            "support_tickets": _dump(SupportTicket.query.all()),
            "support_messages": _dump(SupportMessage.query.all()),
            "app_state": _dump(AppState.query.all()),
        },
    }
    return jsonify({"success": True, "backup": dump})


@app.route("/api/admin/backup/import", methods=["POST"])
def api_admin_backup_import():
    payload = request.get_json(silent=True) or {}
    backup_obj = payload.get("backup") if isinstance(payload.get("backup"), dict) else payload
    tables = backup_obj.get("tables") if isinstance(backup_obj, dict) else None
    if not isinstance(tables, dict):
        return jsonify({"success": False, "error": "Invalid backup JSON format (expected tables map)"}), 400

    model_map = {
        "users": (User, "id"),
        "deposits": (Deposit, "id"),
        "withdrawals": (Withdrawal, "id"),
        "bets": (Bet, "bet_id"),
        "transactions": (Transaction, "tx_id"),
        "referral_commissions": (ReferralCommission, "id"),
        "support_tickets": (SupportTicket, "ticket_id"),
        "support_messages": (SupportMessage, "id"),
        "app_state": (AppState, "key"),
    }
    imported_counts = {}
    with db_lock:
        try:
            for tbl_name, (model_cls, pk_col) in model_map.items():
                rows = tables.get(tbl_name)
                if not isinstance(rows, list):
                    continue
                valid_cols = {c.name for c in model_cls.__table__.columns}
                cnt = 0
                for row in rows:
                    if not isinstance(row, dict) or row.get(pk_col) is None:
                        continue
                    filtered = {k: v for k, v in row.items() if k in valid_cols}
                    existing = db.session.get(model_cls, filtered[pk_col])
                    if existing:
                        if tbl_name in ("users", "app_state"):
                            for k, v in filtered.items():
                                setattr(existing, k, v)
                    else:
                        db.session.add(model_cls(**filtered))
                    cnt += 1
                imported_counts[tbl_name] = cnt
            _, sse_ev = bump_state_version("backup_imported", {"counts": imported_counts})
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "imported": imported_counts})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 24/7 LIVE SUPPORT ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/support/thread", methods=["GET"])
def api_support_thread():
    uid = (request.args.get("userId") or get_cookie_uid() or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Missing userId"}), 400
    mark_read = request.args.get("markRead", "0") in ("1", "true", "yes")
    auto_welcome = request.args.get("init", "0") in ("1", "true", "yes")
    with db_lock:
        out = fetch_support_thread_payload(uid, mark_read_for="USER" if mark_read else None, auto_welcome=auto_welcome)
    if not out:
        return jsonify({"success": False, "error": "User not found"}), 404
    return jsonify(out)


@app.route("/api/support/upload", methods=["POST"])
def api_support_upload():
    curr_ms = now_ms()
    uid = str(request.args.get("userId") or request.headers.get("X-User-Id") or get_cookie_uid() or "").strip()
    file_name = str(request.args.get("fileName") or urllib.parse.unquote(request.headers.get("X-File-Name") or "")).strip()
    file_mime = str(request.args.get("mime") or request.headers.get("X-File-Mime") or "").strip()
    file_bytes = None

    if "file" in request.files:
        f = request.files["file"]
        file_bytes = f.read()
        file_name = file_name or f.filename or "attachment"
        file_mime = file_mime or f.mimetype or ""
    elif request.is_json:
        j = request.get_json(silent=True) or {}
        uid = str(j.get("userId") or uid).strip()
        file_name = str(j.get("fileName") or file_name or "attachment").strip()
        file_mime = str(j.get("fileMime") or file_mime).strip()
        b64_raw = str(j.get("fileDataBase64") or "").strip()
        if "," in b64_raw and b64_raw.startswith("data:"):
            b64_raw = b64_raw.split(",", 1)[1]
        file_bytes = base64.b64decode(b64_raw) if b64_raw else b""
    else:
        file_bytes = request.get_data()

    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Please login to upload support files"}), 401
    if not file_bytes:
        return jsonify({"success": False, "error": "Empty file cannot be uploaded"}), 400
    if len(file_bytes) > MAX_SUPPORT_FILE_BYTES:
        return jsonify({"success": False, "error": "File exceeds 10 MB limit"}), 413

    safe_orig = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(file_name or "attachment")).strip("._") or "attachment"
    stored_name = f"SUP-{curr_ms}-{random.randint(1000, 9999)}_{safe_orig[:96]}"
    with open(os.path.join(SUPPORT_UPLOAD_DIR, stored_name), "wb") as fout:
        fout.write(file_bytes)
    if not file_mime:
        file_mime = mimetypes.guess_type(safe_orig)[0] or "application/octet-stream"
    return jsonify({
        "success": True,
        "attachmentName": file_name or safe_orig,
        "attachmentMime": file_mime,
        "attachmentSize": len(file_bytes),
        "attachmentUrl": f"/api/support/files/{urllib.parse.quote(stored_name)}",
    })


@app.route("/api/support/files/<path:filename>", methods=["GET"])
def api_support_files(filename):
    safe_name = os.path.basename(filename)
    return send_from_directory(SUPPORT_UPLOAD_DIR, safe_name, as_attachment=(request.args.get("download") in ("1", "true", "yes")))


@app.route("/api/support/message", methods=["POST"])
def api_support_message():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    uid = str(payload.get("userId") or get_cookie_uid() or "").strip()
    message = str(payload.get("message") or "").strip()
    category = str(payload.get("category") or "GENERAL").upper().strip()
    att_name = str(payload.get("attachmentName") or "").strip()
    att_mime = str(payload.get("attachmentMime") or "").strip()
    att_size = max(0, int(payload.get("attachmentSize") or 0))
    att_url = str(payload.get("attachmentUrl") or "").strip()
    if not uid or uid == "Guest":
        return jsonify({"success": False, "error": "Please login to send a support message"}), 401
    if not message and not att_url:
        return jsonify({"success": False, "error": "Please enter a message or attach a file"}), 400

    with db_lock:
        u = User.query.get(uid)
        if not u:
            return jsonify({"success": False, "error": "User not found"}), 404
        tid, _ = ensure_support_ticket_and_add_message(
            uid, u.name, "USER", u.name, message, category, 0,
            "USER_MEDIA" if att_url else "USER_MESSAGE", curr_ms,
            att_name, att_mime, att_size, att_url,
        )
        auto_tag, auto_reply = generate_support_auto_reply(uid, message, category)
        ensure_support_ticket_and_add_message(uid, u.name, "AUTO_BOT", "Colour King 24/7 Support Bot", auto_reply, category, 1, auto_tag, curr_ms + 1)
        trow = SupportTicket.query.get(tid)
        if trow:
            trow.unread_user = 0
        _, sse_ev = bump_state_version("support_message", {"userId": uid, "ticketId": tid})
        db.session.commit()
        thread_data = fetch_support_thread_payload(uid, mark_read_for="USER", auto_welcome=False)
    notify_sse_clients(sse_ev)
    return jsonify({**(thread_data or {"success": True}), "autoReply": auto_reply, "situationTag": auto_tag})


@app.route("/api/support/mark-read", methods=["POST"])
def api_support_mark_read():
    payload = request.get_json(silent=True) or {}
    uid = str(payload.get("userId") or get_cookie_uid() or "").strip()
    role = str(payload.get("role") or "USER").upper().strip()
    tid = str(payload.get("ticketId") or "").strip()
    with db_lock:
        if role == "ADMIN" and tid:
            t = SupportTicket.query.get(tid)
            if t:
                t.unread_admin = 0
        elif uid:
            for t in SupportTicket.query.filter_by(user_id=uid).all():
                t.unread_user = 0
        _, sse_ev = bump_state_version("support_read", {"userId": uid, "ticketId": tid, "role": role})
        db.session.commit()
    notify_sse_clients(sse_ev)
    return jsonify({"success": True})


@app.route("/api/admin/support/tickets", methods=["GET"])
def api_admin_support_tickets():
    tickets, unread_total = list_admin_support_tickets()
    return jsonify({"success": True, "tickets": tickets, "unreadTotal": unread_total})


@app.route("/api/admin/support/reply", methods=["POST"])
def api_admin_support_reply():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    tid = str(payload.get("ticketId") or "").strip()
    uid = str(payload.get("userId") or "").strip()
    message = str(payload.get("message") or "").strip()
    admin_name = str(payload.get("adminName") or "ColourPrince").strip() or "ColourPrince"
    att_name = str(payload.get("attachmentName") or "").strip()
    att_mime = str(payload.get("attachmentMime") or "").strip()
    att_size = max(0, int(payload.get("attachmentSize") or 0))
    att_url = str(payload.get("attachmentUrl") or "").strip()
    if not message and not att_url:
        return jsonify({"success": False, "error": "Reply cannot be empty"}), 400

    with db_lock:
        if not uid and tid:
            tr = SupportTicket.query.get(tid)
            uid = tr.user_id if tr else ""
        u = User.query.get(uid)
        if not u:
            return jsonify({"success": False, "error": "Target user not found"}), 404
        tid, msg_id = ensure_support_ticket_and_add_message(
            uid, u.name, "ADMIN", f"Admin ({admin_name})", message, "ADMIN_CUSTOM", 0, "ADMIN_CUSTOM_REPLY", curr_ms,
            att_name, att_mime, att_size, att_url,
        )
        log_admin_action(admin_name, "ADMIN_SUPPORT_REPLY", f"{uid} ({tid})", (message or f"📎 {att_name}")[:180])
        _, sse_ev = bump_state_version("support_reply", {"userId": uid, "ticketId": tid})
        db.session.commit()
        thread_data = fetch_support_thread_payload(uid)
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "ticketId": tid, "messageId": msg_id, "thread": thread_data})


@app.route("/api/admin/support/status", methods=["POST"])
def api_admin_support_status():
    payload = request.get_json(silent=True) or {}
    curr_ms = now_ms()
    tid = str(payload.get("ticketId") or "").strip()
    new_status = str(payload.get("status") or "RESOLVED").upper().strip()
    if new_status not in ("OPEN", "RESOLVED"):
        new_status = "RESOLVED"
    with db_lock:
        t = SupportTicket.query.get(tid)
        uid = t.user_id if t else ""
        if t:
            t.status = new_status
            t.unread_admin = 0
            t.updated_at = format_ist_datetime(curr_ms)
            t.updated_at_ms = curr_ms
        if uid:
            record_admin_situation_support_message(
                uid, f"TICKET_{new_status}",
                f"📌 Support Ticket {tid} marked {new_status} by Admin.",
                category="SYSTEM", create_if_missing=False, curr_ms=curr_ms + 1,
            )
        _, sse_ev = bump_state_version("support_updated", {"ticketId": tid, "userId": uid, "status": new_status})
        db.session.commit()
    notify_sse_clients(sse_ev)
    return jsonify({"success": True, "ticketId": tid, "status": new_status})


def start_background_daemon():
    init_database()
    sync_round_lifecycle_once()
    t = threading.Thread(target=background_round_lifecycle_daemon, daemon=True)
    t.start()


def run_flask_server():
    start_background_daemon()
    print(f"Colour King Flask + {'PostgreSQL' if IS_POSTGRES else 'SQLite'} Server running on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run_flask_server()
