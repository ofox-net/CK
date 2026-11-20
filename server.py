import http.server
import socketserver
import json
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import hashlib
import hmac
import base64
import zlib
import shutil
import signal
import ssl
import sys
import tempfile
import random
import math
import csv
import io
import queue
import mimetypes
import re
from email.parser import BytesParser
from email.policy import default as email_default_policy
from datetime import datetime, timezone, timedelta

try:
    import flask as _flask_pkg  # noqa: F401
    import flask_sqlalchemy as _fsql_pkg  # noqa: F401
    HAS_FLASK_ORM = True
except Exception:
    HAS_FLASK_ORM = False

if HAS_FLASK_ORM:
    from app import app as flask_app, run_flask_server as _run_flask_server  # noqa: F401
    app = flask_app

try:
    import pg8000.dbapi as _pg8000
except Exception:
    _pg8000 = None

try:
    import psycopg as _psycopg3
except Exception:
    _psycopg3 = None

try:
    import psycopg2 as _psycopg2
except Exception:
    _psycopg2 = None

PBKDF2_ITERATIONS = 100_000

def hash_password_secure(raw_password):
    clean = str(raw_password or "")
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", clean.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"

def verify_password_secure(raw_password, stored_hash, stored_plain=""):
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

PORT = int(os.environ.get("PORT", 3000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORY = os.path.join(BASE_DIR, "web")
LEGACY_DB_FILE = os.path.join(DIRECTORY, "colour_king.db")
RETENTION_DAYS = 90
CK_AUTH_SECRET = os.environ.get("CK_AUTH_SECRET") or os.environ.get("SECRET_KEY") or "ck-prod-persistent-hmac-v1-2026-anchor"

def resolve_db_file():
    env_db = (os.environ.get("DB_PATH") or os.environ.get("SQLITE_DB_PATH") or "").strip()
    if env_db:
        try:
            parent = os.path.dirname(os.path.abspath(env_db))
            os.makedirs(parent, exist_ok=True)
            return env_db
        except Exception:
            pass
    for mount_dir in ("/var/data", "/data"):
        try:
            if os.path.isdir(mount_dir) and os.access(mount_dir, os.W_OK):
                candidate = os.path.join(mount_dir, "colour_king.db")
                if not os.path.exists(candidate) and os.path.exists(LEGACY_DB_FILE):
                    try:
                        shutil.copy2(LEGACY_DB_FILE, candidate)
                    except Exception:
                        pass
                return candidate
        except Exception:
            pass
    return LEGACY_DB_FILE

DB_FILE = resolve_db_file()
SUPPORT_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_FILE)), "support_uploads")
os.makedirs(SUPPORT_UPLOAD_DIR, exist_ok=True)
MAX_SUPPORT_FILE_BYTES = 10 * 1024 * 1024  # Strictly 10 MB max

def sanitize_support_filename(raw_name):
    base = os.path.basename(str(raw_name or "attachment").replace("\\", "/")).strip()
    if not base:
        base = "attachment"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    if not cleaned:
        cleaned = "attachment"
    return cleaned[:96]

def format_file_size_human(size_bytes):
    sz = max(0, int(size_bytes or 0))
    if sz >= 1024 * 1024:
        return f"{sz / (1024 * 1024):.2f} MB"
    if sz >= 1024:
        return f"{sz / 1024:.1f} KB"
    return f"{sz} B"
DATABASE_URL = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("RENDER_POSTGRES_URL")
    or os.environ.get("POSTGRES_URL")
    or ""
).strip()
FIREBASE_DB_URL = (os.environ.get("FIREBASE_DB_URL") or "").strip().rstrip("/")
FIREBASE_DB_SECRET = (os.environ.get("FIREBASE_DB_SECRET") or "").strip()

db_lock = threading.Lock()
cloud_sync_lock = threading.Lock()
sse_lock = threading.Lock()
sse_subscribers = []
_cloud_status = {
    "pgConfigured": bool(DATABASE_URL),
    "pgDriver": "pg8000" if _pg8000 else ("psycopg3" if _psycopg3 else ("psycopg2" if _psycopg2 else "none")),
    "pgConnected": False,
    "pgLastSyncMs": 0,
    "pgLastError": "",
    "firebaseConfigured": bool(FIREBASE_DB_URL),
    "firebaseConnected": False,
    "firebaseLastSyncMs": 0,
    "lastSnapshotVersion": 0,
    "lastSnapshotTimeMs": 0,
    "persistentDisk": (DB_FILE != LEGACY_DB_FILE),
}

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
    "qrImage": "",
    "instructions": "1. Scan QR code or pay to the UPI ID above.\n2. Enter the 12-digit UTR reference number in the app.\n3. Balance will be approved and credited within 2 minutes."
}

REFERRAL_TIER_RATES = [
    (1, 0.0100),
    (2, 0.0075),
    (3, 0.0060),
    (4, 0.0050),
    (5, 0.0030),
    (6, 0.0020),
]

DEFAULT_USERS = [
    { "id": "USR-1001", "name": "Rahul_Player", "phone": "+91 98765 43210", "email": "rahul@gmail.com", "balance": 50200.00, "totalDeposit": 75000.00, "totalWithdraw": 28000.00, "betsCount": 142, "status": "ACTIVE", "referralCode": "RAHUL777" },
    { "id": "USR-1002", "name": "Aman_Trader", "phone": "+91 98221 11223", "email": "aman.trade@yahoo.com", "balance": 14500.00, "totalDeposit": 25000.00, "totalWithdraw": 11000.00, "betsCount": 68, "status": "ACTIVE", "referralCode": "AMAN777" },
    { "id": "USR-1003", "name": "Priya_VIP", "phone": "+91 97110 99887", "email": "priya_queen@outlook.com", "balance": 125000.00, "totalDeposit": 200000.00, "totalWithdraw": 95000.00, "betsCount": 310, "status": "ACTIVE", "referralCode": "PRIYA777" },
    { "id": "USR-1004", "name": "Vikram_99", "phone": "+91 96554 33221", "email": "vikram99@gmail.com", "balance": 3200.00, "totalDeposit": 10000.00, "totalWithdraw": 6000.00, "betsCount": 45, "status": "ACTIVE", "referralCode": "VIKRAM777" },
    { "id": "USR-1005", "name": "Suspicious_Bot1", "phone": "+91 91234 56789", "email": "bot_arb@mail.ru", "balance": 0.00, "totalDeposit": 5000.00, "totalWithdraw": 0.00, "betsCount": 8, "status": "BLOCKED", "referralCode": "BOT777" },
    { "id": "USR-1006", "name": "Karan_Pro", "phone": "+91 99887 76655", "email": "karan_pro@gmail.com", "balance": 38400.00, "totalDeposit": 60000.00, "totalWithdraw": 24000.00, "betsCount": 94, "status": "ACTIVE", "referralCode": "KARAN777" }
]

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn

def _b64u_encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")

def _b64u_decode(text_str):
    pad = "=" * ((4 - len(text_str) % 4) % 4)
    return base64.urlsafe_b64decode((text_str + pad).encode("ascii"))

def build_user_recovery_token(u_row):
    if not u_row:
        return ""
    keys = u_row.keys() if hasattr(u_row, "keys") else u_row
    def _val(k, default=None):
        try:
            return u_row[k] if k in keys else default
        except Exception:
            return default
    payload = {
        "v": 1,
        "id": str(_val("id", "")),
        "name": str(_val("name", "")),
        "phone": str(_val("phone", "") or ""),
        "email": str(_val("email", "") or ""),
        "pwh": str(_val("password_hash", "") or ""),
        "bal": round(float(_val("balance", 0.0) or 0.0), 2),
        "td": round(float(_val("total_deposit", 0.0) or 0.0), 2),
        "tw": round(float(_val("total_withdraw", 0.0) or 0.0), 2),
        "bc": int(_val("bets_count", 0) or 0),
        "st": str(_val("status", "ACTIVE") or "ACTIVE"),
        "rc": str(_val("referral_code", "") or ""),
        "rb": _val("referred_by", None),
        "ts": int(time.time() * 1000),
    }
    raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64u_encode(raw_json)
    sig = hmac.new(CK_AUTH_SECRET.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"CKT1.{body_b64}.{_b64u_encode(sig)}"

def verify_user_recovery_token(token_str):
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

def _find_user_matching_identifier(c, identifier):
    ident = str(identifier or "").strip()
    if not ident:
        return None
    c.execute("""
        SELECT * FROM users
        WHERE UPPER(TRIM(id)) = UPPER(?) OR LOWER(TRIM(name)) = LOWER(?) OR LOWER(TRIM(email)) = LOWER(?) OR TRIM(phone) = ?
        LIMIT 1
    """, (ident, ident, ident, ident))
    u = c.fetchone()
    if u:
        return u
    digits = "".join(ch for ch in ident if ch.isdigit())
    last10 = digits[-10:] if len(digits) >= 10 else ""
    if last10:
        c.execute("SELECT * FROM users")
        for row in c.fetchall():
            r_digits = "".join(ch for ch in str(row["phone"] or "") if ch.isdigit())
            if len(r_digits) >= 10 and r_digits[-10:] == last10:
                return row
    return None

def _token_matches_identifier(token_data, identifier):
    ident = str(identifier or "").strip()
    if not ident or not token_data:
        return False
    ident_l = ident.lower()
    if (
        str(token_data.get("id", "")).strip().lower() == ident_l
        or str(token_data.get("name", "")).strip().lower() == ident_l
        or str(token_data.get("email", "")).strip().lower() == ident_l
        or str(token_data.get("phone", "")).strip().lower() == ident_l
    ):
        return True
    i_digits = "".join(ch for ch in ident if ch.isdigit())
    t_digits = "".join(ch for ch in str(token_data.get("phone", "")) if ch.isdigit())
    if len(i_digits) >= 10 and len(t_digits) >= 10 and i_digits[-10:] == t_digits[-10:]:
        return True
    return False

def restore_user_from_token_if_missing(conn, token_data, now_ms, verified_plain_pw=""):
    if not token_data:
        return None, False
    c = conn.cursor()
    uid = str(token_data.get("id", "")).strip()
    uname = str(token_data.get("name", "")).strip()
    uphone = str(token_data.get("phone", "") or "").strip()
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    existing = c.fetchone()
    if existing:
        return existing, False
    existing = _find_user_matching_identifier(c, uname)
    if existing:
        return existing, False
    if uphone:
        existing = _find_user_matching_identifier(c, uphone)
        if existing:
            return existing, False

    pw_hash = str(token_data.get("pwh") or "").strip()
    if not pw_hash and verified_plain_pw:
        pw_hash = hash_password_secure(verified_plain_pw)
    bal = round(float(token_data.get("bal") or 100.0), 2)
    td = round(float(token_data.get("td") or bal), 2)
    tw = round(float(token_data.get("tw") or 0.0), 2)
    bc = int(token_data.get("bc") or 0)
    st = str(token_data.get("st") or "ACTIVE").upper()
    rc = str(token_data.get("rc") or uid[-6:]).upper()
    rb = token_data.get("rb")
    email = str(token_data.get("email") or f"{uname.lower().replace(' ', '_')}@colourking.in")

    # Resolve referral code uniqueness cleanly
    c.execute("SELECT 1 FROM users WHERE UPPER(referral_code) = ?", (rc,))
    if c.fetchone():
        rc = f"{rc[:4]}{random.randint(1000, 9999)}"

    c.execute("""
        INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash, password_plain)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid, uname, uphone, email, bal, td, tw, bc, st, rc, rb, pw_hash, verified_plain_pw))

    c.execute("""
        INSERT OR IGNORE INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
        VALUES (?, ?, 'DEPOSIT', 'Restored Cloud Account Balance', ?, ?, 0.0, ?, 'SUCCESS', ?)
    """, (f"TX-RESTORE-{uid}", uid, f"Session Continuity ({rc})", bal, bal, now_ms))
    c.execute("""
        INSERT INTO admin_audit_logs (actor, action, entity, desc)
        VALUES ('System', 'USER_AUTO_RESTORED', ?, ?)
    """, (uid, f"Auto-restored persistent user {uname} ({uphone}) with balance ₹{bal:.2f}"))
    bump_state_version(conn, "user_restored", {"userId": uid, "name": uname})
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    return c.fetchone(), True

def _get_pg_connection(retries=1):
    if not DATABASE_URL:
        return None
    parsed = urllib.parse.urlparse(DATABASE_URL)
    host = parsed.hostname or "localhost"
    port = int(parsed.port or 5432)
    database = (parsed.path or "").lstrip("/") or "postgres"
    user = urllib.parse.unquote(parsed.username or "postgres")
    password = urllib.parse.unquote(parsed.password or "")
    query_params = urllib.parse.parse_qs(parsed.query or "")
    sslmode = (query_params.get("sslmode", [""])[0] or "").lower()
    use_ssl = (host not in ("localhost", "127.0.0.1", "::1")) and (sslmode != "disable")

    last_err = ""
    for attempt in range(max(1, int(retries))):
        try:
            if _pg8000:
                kwargs = {
                    "host": host,
                    "port": port,
                    "database": database,
                    "user": user,
                    "password": password,
                    "timeout": 12,
                }
                if use_ssl:
                    kwargs["ssl_context"] = ssl.create_default_context()
                conn = _pg8000.connect(**kwargs)
                _cloud_status["pgConnected"] = True
                _cloud_status["pgLastError"] = ""
                return conn
            if _psycopg3:
                conn = _psycopg3.connect(DATABASE_URL, connect_timeout=12)
                _cloud_status["pgConnected"] = True
                _cloud_status["pgLastError"] = ""
                return conn
            if _psycopg2:
                conn = _psycopg2.connect(DATABASE_URL, connect_timeout=12)
                _cloud_status["pgConnected"] = True
                _cloud_status["pgLastError"] = ""
                return conn
            _cloud_status["pgLastError"] = "No PostgreSQL Python driver installed"
            return None
        except Exception as e:
            last_err = str(e)[:220]
            if attempt + 1 < retries:
                time.sleep(1.5)
    _cloud_status["pgConnected"] = False
    _cloud_status["pgLastError"] = last_err
    return None

def _ensure_pg_schema(pg_conn):
    cur = pg_conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ck_sqlite_backup (
            id INTEGER PRIMARY KEY,
            version BIGINT NOT NULL,
            updated_at_ms BIGINT NOT NULL,
            db_b64 TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ck_users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            total_deposit DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            total_withdraw DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            bets_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            referral_code TEXT,
            referred_by TEXT,
            password_hash TEXT,
            password_plain TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at_ms BIGINT NOT NULL DEFAULT 0
        )
    """)
    pg_conn.commit()
    cur.close()

def _firebase_rest_request(method, path_suffix, data=None):
    if not FIREBASE_DB_URL:
        return None
    url = f"{FIREBASE_DB_URL}/{path_suffix.lstrip('/')}.json"
    if FIREBASE_DB_SECRET:
        url += f"?auth={urllib.parse.quote(FIREBASE_DB_SECRET, safe='')}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            _cloud_status["firebaseConnected"] = True
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except Exception:
        return None

def _sync_to_cloud_worker(db_b64, version, users_rows):
    now_ms = int(time.time() * 1000)
    with cloud_sync_lock:
        if DATABASE_URL:
            pg = _get_pg_connection()
            if pg:
                try:
                    _ensure_pg_schema(pg)
                    cur = pg.cursor()
                    for ur in users_rows:
                        cur.execute("""
                            INSERT INTO ck_users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash, password_plain, created_at, updated_at_ms)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                name = EXCLUDED.name,
                                phone = EXCLUDED.phone,
                                email = EXCLUDED.email,
                                balance = EXCLUDED.balance,
                                total_deposit = EXCLUDED.total_deposit,
                                total_withdraw = EXCLUDED.total_withdraw,
                                bets_count = EXCLUDED.bets_count,
                                status = EXCLUDED.status,
                                referral_code = EXCLUDED.referral_code,
                                referred_by = EXCLUDED.referred_by,
                                password_hash = COALESCE(NULLIF(EXCLUDED.password_hash, ''), ck_users.password_hash),
                                password_plain = COALESCE(NULLIF(EXCLUDED.password_plain, ''), ck_users.password_plain),
                                updated_at_ms = EXCLUDED.updated_at_ms
                        """, (
                            ur["id"], ur["name"], ur["phone"], ur["email"],
                            ur["balance"], ur["total_deposit"], ur["total_withdraw"], ur["bets_count"],
                            ur["status"], ur["referral_code"], ur["referred_by"],
                            ur["password_hash"], ur["password_plain"], ur["created_at"], now_ms
                        ))
                    if db_b64:
                        cur.execute("""
                            INSERT INTO ck_sqlite_backup (id, version, updated_at_ms, db_b64)
                            VALUES (1, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                version = EXCLUDED.version,
                                updated_at_ms = EXCLUDED.updated_at_ms,
                                db_b64 = EXCLUDED.db_b64
                            WHERE ck_sqlite_backup.version <= EXCLUDED.version
                        """, (int(version), now_ms, db_b64))
                    pg.commit()
                    cur.close()
                    _cloud_status["pgConnected"] = True
                    _cloud_status["pgLastSyncMs"] = now_ms
                    _cloud_status["pgLastError"] = ""
                    _cloud_status["lastSnapshotVersion"] = int(version)
                    _cloud_status["lastSnapshotTimeMs"] = now_ms
                except Exception as e:
                    try:
                        pg.rollback()
                    except Exception:
                        pass
                    _cloud_status["pgLastError"] = str(e)[:220]
                finally:
                    try:
                        pg.close()
                    except Exception:
                        pass
        if FIREBASE_DB_URL:
            res = _firebase_rest_request("PUT", "colour_king_users", {ur["id"]: ur for ur in users_rows})
            if res is not None:
                _cloud_status["firebaseLastSyncMs"] = now_ms

def _capture_sqlite_snapshot_b64(conn):
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="ck_snap_", suffix=".db")
    os.close(tmp_fd)
    try:
        dst = sqlite3.connect(tmp_path)
        conn.backup(dst)
        dst.close()
        with open(tmp_path, "rb") as f:
            raw = f.read()
        compressed = zlib.compress(raw, level=6)
        return base64.b64encode(compressed).decode("ascii")
    finally:
        for ext in ("", "-wal", "-shm"):
            p = tmp_path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

def _collect_users_for_cloud(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users")
    out = []
    for r in cur.fetchall():
        keys = r.keys()
        out.append({
            "id": r["id"],
            "name": r["name"],
            "phone": r["phone"] or "",
            "email": r["email"] or "",
            "balance": round(float(r["balance"] or 0.0), 2),
            "total_deposit": round(float(r["total_deposit"] or 0.0), 2),
            "total_withdraw": round(float(r["total_withdraw"] or 0.0), 2),
            "bets_count": int(r["bets_count"] or 0),
            "status": r["status"] or "ACTIVE",
            "referral_code": (r["referral_code"] if "referral_code" in keys and r["referral_code"] else ""),
            "referred_by": (r["referred_by"] if "referred_by" in keys else None),
            "password_hash": (r["password_hash"] if "password_hash" in keys else ""),
            "password_plain": (r["password_plain"] if "password_plain" in keys else ""),
            "created_at": str(r["created_at"] or ""),
        })
    return out

def sync_to_cloud(conn, critical=False):
    if not DATABASE_URL and not FIREBASE_DB_URL:
        return
    try:
        ver = get_state_version(conn)
        now_ms = int(time.time() * 1000)
        if not critical and (now_ms - _cloud_status.get("lastSnapshotTimeMs", 0)) < 12000:
            return
        users_rows = _collect_users_for_cloud(conn)
        db_b64 = _capture_sqlite_snapshot_b64(conn) if DATABASE_URL else ""
        if critical:
            _sync_to_cloud_worker(db_b64, ver, users_rows)
        else:
            t = threading.Thread(target=_sync_to_cloud_worker, args=(db_b64, ver, users_rows), daemon=True)
            t.start()
    except Exception as e:
        _cloud_status["pgLastError"] = str(e)[:220]

def commit_and_persist(conn, critical=False):
    conn.commit()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)" if critical else "PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:
        pass
    sync_to_cloud(conn, critical=critical)

def restore_from_cloud_if_needed(conn):
    restored_any = False
    if DATABASE_URL:
        pg = _get_pg_connection(retries=3)
        if pg:
            try:
                _ensure_pg_schema(pg)
                cur = pg.cursor()
                local_ver = get_state_version(conn)
                local_users_cnt = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                is_local_fresh = (local_users_cnt <= len(DEFAULT_USERS) and local_ver <= 10)

                cur.execute("SELECT version, updated_at_ms, db_b64 FROM ck_sqlite_backup WHERE id = 1")
                snap = cur.fetchone()
                if snap and snap[2]:
                    remote_ver = int(snap[0] or 0)
                    if is_local_fresh or remote_ver > local_ver:
                        raw_bytes = zlib.decompress(base64.b64decode(snap[2]))
                        if raw_bytes.startswith(b"SQLite format 3"):
                            tmp_fd, tmp_path = tempfile.mkstemp(prefix="ck_restore_", suffix=".db")
                            os.close(tmp_fd)
                            try:
                                with open(tmp_path, "wb") as f:
                                    f.write(raw_bytes)
                                src = sqlite3.connect(tmp_path)
                                src.backup(conn)
                                src.close()
                                conn.commit()
                                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                                restored_any = True
                                print(f"[CloudSync] Restored full SQLite state v{remote_ver} from PostgreSQL.")
                            finally:
                                if os.path.exists(tmp_path):
                                    os.remove(tmp_path)

                # Merge any incremental users from ck_users missing locally
                cur.execute("SELECT id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash, password_plain FROM ck_users")
                for pr in cur.fetchall():
                    pid = str(pr[0])
                    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (pid,)).fetchone():
                        conn.execute("""
                            INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash, password_plain)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (pid, pr[1], pr[2], pr[3], float(pr[4] or 0.0), float(pr[5] or 0.0), float(pr[6] or 0.0), int(pr[7] or 0), pr[8] or "ACTIVE", pr[9], pr[10], pr[11], pr[12] or ""))
                        restored_any = True
                if restored_any:
                    conn.commit()
                _cloud_status["pgLastSyncMs"] = int(time.time() * 1000)
                cur.close()
            except Exception as e:
                _cloud_status["pgLastError"] = str(e)[:220]
            finally:
                try:
                    pg.close()
                except Exception:
                    pass
    elif FIREBASE_DB_URL:
        fb_users = _firebase_rest_request("GET", "colour_king_users")
        if isinstance(fb_users, dict) and fb_users:
            c = conn.cursor()
            for uid_k, u in fb_users.items():
                if not isinstance(u, dict) or not u.get("id"):
                    continue
                if not c.execute("SELECT 1 FROM users WHERE id = ?", (u["id"],)).fetchone():
                    c.execute("""
                        INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash, password_plain)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        u["id"], u.get("name", "Player"), u.get("phone", ""), u.get("email", ""),
                        float(u.get("balance", 100.0)), float(u.get("total_deposit", 100.0)),
                        float(u.get("total_withdraw", 0.0)), int(u.get("bets_count", 0)),
                        u.get("status", "ACTIVE"), u.get("referral_code"), u.get("referred_by"),
                        u.get("password_hash", ""), u.get("password_plain", "")
                    ))
                    restored_any = True
            if restored_any:
                conn.commit()
            _cloud_status["firebaseLastSyncMs"] = int(time.time() * 1000)
    return restored_any

def get_storage_status_dict(conn):
    c = conn.cursor()
    total_users = int(c.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0)
    default_ids = {u["id"] for u in DEFAULT_USERS}
    placeholders = ",".join("?" for _ in default_ids)
    custom_users = int(c.execute(f"SELECT COUNT(*) FROM users WHERE id NOT IN ({placeholders})", tuple(default_ids)).fetchone()[0] or 0)
    total_bets = int(c.execute("SELECT COUNT(*) FROM bets").fetchone()[0] or 0)
    total_deps = int(c.execute("SELECT COUNT(*) FROM deposits").fetchone()[0] or 0)
    if DATABASE_URL and _cloud_status.get("pgConnected"):
        mode = "POSTGRESQL_CLOUD"
        label = "PostgreSQL Cloud DB + SQLite WAL"
        is_durable = True
    elif _cloud_status.get("persistentDisk"):
        mode = "PERSISTENT_DISK"
        label = "Persistent Disk Volume + SQLite WAL"
        is_durable = True
    elif FIREBASE_DB_URL:
        mode = "FIREBASE_RTDB"
        label = "Firebase RTDB + SQLite WAL"
        is_durable = True
    else:
        mode = "SQLITE_WITH_TOKEN_RECOVERY"
        label = "SQLite WAL + Cryptographic Account Recovery"
        is_durable = False
    return {
        "mode": mode,
        "label": label,
        "isDurableCloud": is_durable,
        "dbFile": DB_FILE,
        "stateVersion": get_state_version(conn),
        "totalUsers": total_users,
        "registeredUsers": custom_users,
        "totalBets": total_bets,
        "totalDeposits": total_deps,
        "pgConfigured": bool(DATABASE_URL),
        "pgConnected": bool(_cloud_status.get("pgConnected")),
        "pgLastSyncMs": int(_cloud_status.get("pgLastSyncMs") or 0),
        "pgLastError": _cloud_status.get("pgLastError") or "",
        "persistentDisk": bool(_cloud_status.get("persistentDisk")),
        "firebaseConfigured": bool(FIREBASE_DB_URL),
        "warning": "" if is_durable else "No external cloud DB env (DATABASE_URL) or Render Persistent Disk attached yet. HMAC client recovery tokens protect accounts on ephemeral container restarts; attach Render PostgreSQL or Persistent Disk for multi-device cloud durability.",
    }

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
    os.makedirs(os.path.dirname(os.path.abspath(DB_FILE)), exist_ok=True)
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=FULL;")
        c.execute("PRAGMA wal_autocheckpoint=100;")

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
                balance REAL NOT NULL DEFAULT 0.00,
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
                platform_fee REAL DEFAULT 0.00,
                net_amount REAL DEFAULT 0.00,
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
            "ALTER TABLE users ADD COLUMN password_plain TEXT DEFAULT ''",
            "ALTER TABLE bets ADD COLUMN platform_fee REAL DEFAULT 0.00",
            "ALTER TABLE bets ADD COLUMN net_amount REAL DEFAULT 0.00",
            "ALTER TABLE transactions ADD COLUMN created_at_ms INTEGER DEFAULT 0",
            "ALTER TABLE deposits ADD COLUMN created_at_ms INTEGER DEFAULT 0",
            "ALTER TABLE withdrawals ADD COLUMN created_at_ms INTEGER DEFAULT 0",
            "ALTER TABLE support_messages ADD COLUMN attachment_name TEXT DEFAULT ''",
            "ALTER TABLE support_messages ADD COLUMN attachment_mime TEXT DEFAULT ''",
            "ALTER TABLE support_messages ADD COLUMN attachment_size INTEGER DEFAULT 0",
            "ALTER TABLE support_messages ADD COLUMN attachment_url TEXT DEFAULT ''",
        ]:
            try:
                c.execute(alter_sql)
            except Exception:
                pass
        try:
            default_pw_sha = hashlib.sha256(b"password123").hexdigest()
            c.execute("UPDATE users SET password_hash = ? WHERE password_hash IS NULL OR password_hash = ''", (default_pw_sha,))
            c.execute("UPDATE users SET password_plain = 'password123' WHERE (password_plain IS NULL OR password_plain = '') AND password_hash = ?", (default_pw_sha,))
            c.execute("UPDATE bets SET created_at_ms = CAST(strftime('%s', created_at) AS INTEGER) * 1000 WHERE created_at_ms IS NULL OR created_at_ms = 0")
            c.execute("UPDATE transactions SET created_at_ms = CAST(strftime('%s', created_at) AS INTEGER) * 1000 WHERE created_at_ms IS NULL OR created_at_ms = 0")
            c.execute("UPDATE deposits SET created_at_ms = CAST(strftime('%s', created_at) AS INTEGER) * 1000 WHERE created_at_ms IS NULL OR created_at_ms = 0")
            c.execute("UPDATE withdrawals SET created_at_ms = CAST(strftime('%s', created_at) AS INTEGER) * 1000 WHERE created_at_ms IS NULL OR created_at_ms = 0")
            for du in DEFAULT_USERS:
                c.execute("UPDATE users SET referral_code = ? WHERE id = ? AND (referral_code IS NULL OR referral_code = '')", (du["referralCode"], du["id"]))
            c.execute("SELECT id, name FROM users WHERE referral_code IS NULL OR referral_code = ''")
            for row_u in c.fetchall():
                prefix = "".join(ch for ch in str(row_u["name"] or "CK").upper() if ch.isalnum())[:4] or "CK"
                suffix = "".join(ch for ch in str(row_u["id"]).upper() if ch.isalnum())[-4:] or "777"
                c.execute("UPDATE users SET referral_code = ? WHERE id = ?", (f"{prefix}{suffix}", row_u["id"]))
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

        c.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                ticket_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_name TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                category TEXT DEFAULT 'GENERAL',
                last_message TEXT DEFAULT '',
                last_sender TEXT DEFAULT 'AUTO_BOT',
                unread_admin INTEGER NOT NULL DEFAULT 0,
                unread_user INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at_ms INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON support_tickets (user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_updated ON support_tickets (updated_at_ms DESC)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                sender_type TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                category TEXT DEFAULT 'GENERAL',
                message TEXT NOT NULL,
                is_auto INTEGER NOT NULL DEFAULT 0,
                situation_tag TEXT DEFAULT '',
                attachment_name TEXT DEFAULT '',
                attachment_mime TEXT DEFAULT '',
                attachment_size INTEGER DEFAULT 0,
                attachment_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at_ms INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_support_msgs_ticket ON support_messages (ticket_id, created_at_ms ASC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_support_msgs_user ON support_messages (user_id, created_at_ms ASC)")

        # Seed default users if empty
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            default_pw_hash = hashlib.sha256(b"password123").hexdigest()
            for u in DEFAULT_USERS:
                c.execute("""
                    INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, password_hash, password_plain)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (u["id"], u["name"], u.get("phone"), u.get("email"), u["balance"], u["totalDeposit"], u["totalWithdraw"], u["betsCount"], u["status"], u["referralCode"], default_pw_hash, "password123"))

        # Seed default deposits/withdrawals if empty
        c.execute("SELECT COUNT(*) FROM deposits")
        if c.fetchone()[0] == 0:
            now_seed_ms = int(time.time() * 1000)
            seed_dep_1_ts = format_ist_display(now_seed_ms - 6 * 60 * 1000)
            seed_dep_2_ts = format_ist_display(now_seed_ms - 12 * 60 * 1000)
            c.execute("""
                INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status, created_at_ms)
                VALUES ('DEP-88401', 'USR-1001', 'Rahul_Player', 5000.00, 'UPI (GooglePay)', '429188402911', ?, 'IN PROCESS', ?)
            """, (seed_dep_1_ts, now_seed_ms - 6 * 60 * 1000))
            c.execute("""
                INSERT INTO deposits (id, user_id, user_name, amount, method, utr, time_str, status, created_at_ms)
                VALUES ('DEP-88402', 'USR-1002', 'Aman_Trader', 10000.00, 'IMPS SBI NetBanking', '902184716294', ?, 'IN PROCESS', ?)
            """, (seed_dep_2_ts, now_seed_ms - 12 * 60 * 1000))

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
        restore_from_cloud_if_needed(conn)
        try:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        sync_to_cloud(conn, critical=True)
        conn.close()

IST_TZ = timezone(timedelta(hours=5, minutes=30))

def get_ist_now(ms=None):
    # IST is always UTC + 05:30 regardless of host OS timezone
    if ms is not None and int(ms) > 0:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).astimezone(IST_TZ)
    return datetime.now(timezone.utc).astimezone(IST_TZ)

def format_ist_datetime(ms=None):
    return get_ist_now(ms).strftime("%Y-%m-%d %H:%M:%S IST")

def format_ist_display(ms=None):
    return get_ist_now(ms).strftime("%d %b, %I:%M:%S %p IST")

def format_ist_time(ms=None):
    return get_ist_now(ms).strftime("%I:%M:%S %p IST")

def format_ist_clock24(ms=None):
    return get_ist_now(ms).strftime("%H:%M:%S IST")

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

def get_period_window_ms_ist(period_str):
    try:
        s = str(period_str or "").strip()
        if len(s) < 11 or not s.isdigit():
            return (0, 0, 0)
        y = int(s[0:4])
        m = int(s[4:6])
        d = int(s[6:8])
        p_num = int(s[8:])
        ref_11am = datetime(y, m, d, 11, 0, 0, tzinfo=IST_TZ)
        round_index = p_num - 221
        start_ms = int((ref_11am.timestamp() + (round_index * ROUND_DURATION_SEC)) * 1000)
        lock_ms = start_ms + ((ROUND_DURATION_SEC - LOCK_CUTOFF_SEC) * 1000)
        end_ms = start_ms + (ROUND_DURATION_SEC * 1000)
        return (start_ms, lock_ms, end_ms)
    except Exception:
        return (0, 0, 0)

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

def normalize_bet_target_num(btype, target):
    t = str(target or "").upper().strip()
    if t.startswith("NUM "):
        t = t[4:].strip()
    elif t.startswith("NUM_"):
        t = t[4:].strip()
    elif t.startswith("NUMBER "):
        t = t[7:].strip()
    elif t.startswith("#"):
        t = t[1:].strip()
    if len(t) == 1 and t.isdigit():
        return int(t)
    if str(btype or "").upper().strip() == "NUMBER":
        digits = "".join(ch for ch in t if ch.isdigit())
        if len(digits) == 1:
            return int(digits)
    return None

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

    p_start_ms, p_lock_ms, p_end_ms = get_period_window_ms_ist(period)
    if draw_mode == "MANUAL_ADMIN":
        now_ts = format_ist_datetime()
        eff_end_ms = int(time.time() * 1000)
    else:
        eff_end_ms = p_end_ms if p_end_ms > 0 else int(time.time() * 1000)
        now_ts = format_ist_datetime(eff_end_ms)

    # 1. Update or Insert round into rounds table
    c.execute("""
        INSERT INTO rounds (round_id, market, period, start_time_ms, lock_time_ms, end_time_ms, status, result_number, result_color, result_col_class, is_big, draw_mode, declared_at, declared_by)
        VALUES (?, ?, ?, ?, ?, ?, 'SETTLED', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(round_id) DO UPDATE SET
            start_time_ms = excluded.start_time_ms,
            lock_time_ms = excluded.lock_time_ms,
            end_time_ms = excluded.end_time_ms,
            status = 'SETTLED',
            result_number = excluded.result_number,
            result_color = excluded.result_color,
            result_col_class = excluded.result_col_class,
            is_big = excluded.is_big,
            draw_mode = excluded.draw_mode,
            declared_at = excluded.declared_at,
            declared_by = excluded.declared_by
    """, (round_id, market_code, period, p_start_ms, p_lock_ms, eff_end_ms, winning_number, color, col_class, 1 if is_big else 0, draw_mode, now_ts, declared_by))

    # 2. Fetch all unsettled bets for this market and period
    c.execute("""
        SELECT bet_id, user_id, user_name, amount, platform_fee, net_amount, prediction_type, prediction_target, multiplier
        FROM bets
        WHERE market = ? AND period = ? AND status IN ('PENDING', 'LOCKED')
    """, (market_code, period))
    unsettled_bets = c.fetchall()

    for b in unsettled_bets:
        bet_id = b["bet_id"]
        uid = b["user_id"]
        amt = float(b["amount"] or 0.0)
        net_amt_db = float(b["net_amount"] or 0.0) if "net_amount" in b.keys() else 0.0
        stake_base = net_amt_db if net_amt_db > 0.0 else round(amt - round(amt * 0.03, 2), 2)
        btype = str(b["prediction_type"] or "").upper().strip()
        target = str(b["prediction_target"] or "").upper().strip()
        mult = b["multiplier"]

        won = False
        actual_mult = mult
        if btype in ("BIG_SMALL", "SIZE"):
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
            t_num = normalize_bet_target_num(btype, target)
            if t_num is not None and t_num == winning_number:
                won = True
                actual_mult = 9.0

        if won:
            win_amount = round(stake_base * actual_mult, 2)
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

    commit_and_persist(conn, critical=False)

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
                        declared_ts = format_ist_datetime(past_auth["end_time_ms"])
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

        commit_and_persist(conn, critical=False)
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
    raw = str(ts_str).strip()
    try:
        if raw.endswith(" IST") or "+05:30" in raw:
            cleaned = raw.replace(" IST", "").strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d %b, %I:%M:%S %p", "%d %b %Y, %I:%M:%S %p"):
                try:
                    dt = datetime.strptime(cleaned, fmt)
                    if "%Y" not in fmt:
                        dt = dt.replace(year=get_ist_now().year)
                    return int(dt.replace(tzinfo=IST_TZ).timestamp() * 1000)
                except Exception:
                    pass
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    except Exception:
        try:
            dt_iso = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt_iso.tzinfo is None:
                dt_iso = dt_iso.replace(tzinfo=timezone.utc)
            return int(dt_iso.timestamp() * 1000)
        except Exception:
            return int(time.time() * 1000)

def to_ist_display(ts_str=None, ms=0, mode="datetime"):
    raw = str(ts_str or "").strip()
    if ms and int(ms) > 0:
        epoch_ms = int(ms)
    elif raw and raw.lower() not in ("just now",) and not raw.lower().startswith("today,"):
        # Handle bare HH:MM:SS already computed in IST
        if len(raw) == 8 and raw[2] == ":" and raw[5] == ":":
            return f"{raw} IST"
        epoch_ms = _parse_ts_ms(raw, 0)
    else:
        epoch_ms = int(time.time() * 1000)
    if mode == "display":
        return format_ist_display(epoch_ms)
    if mode == "time12":
        return format_ist_time(epoch_ms)
    if mode == "clock24":
        return format_ist_clock24(epoch_ms)
    return format_ist_datetime(epoch_ms)

def ist_date_str(ts_str=None, ms=0):
    epoch_ms = _parse_ts_ms(ts_str, ms)
    return get_ist_now(epoch_ms).strftime("%Y-%m-%d")

def _parse_days_arg_server(raw_days, default_all=True):
    if raw_days is None:
        return None if default_all else RETENTION_DAYS
    s = str(raw_days).strip().upper()
    if s in ("", "ALL", "PERMANENT", "FOREVER", "0"):
        return None
    try:
        v = int(s)
        return v if v > 0 else None
    except Exception:
        return None if default_all else RETENTION_DAYS

def build_user_statement(conn, uid, days="ALL", category="ALL", market_filter="ALL"):
    now_ms = int(time.time() * 1000)
    parsed_days = _parse_days_arg_server(days, default_all=True)
    cutoff_ms = (now_ms - (parsed_days * 86400 * 1000)) if parsed_days else 0
    cat_upper = (category or "ALL").upper().strip()
    mkt_upper = (market_filter or "ALL").upper().strip()

    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    u = c.fetchone()
    user_name = u["name"] if u else uid
    wallet_balance = float(u["balance"]) if u else 0.0
    referral_code = (u["referral_code"] if u and "referral_code" in u.keys() and u["referral_code"] else (uid[-6:] if len(uid) >= 6 else uid).upper())

    # 1. All bet records permanently stored (optional window filter only if days explicitly numeric)
    if mkt_upper != "ALL" and mkt_upper in MARKET_KEYS:
        if cutoff_ms > 0:
            c.execute("""
                SELECT * FROM bets
                WHERE user_id = ? AND (created_at_ms >= ? OR created_at_ms = 0) AND market = ?
                ORDER BY created_at_ms DESC
            """, (uid, cutoff_ms, mkt_upper))
        else:
            c.execute("""
                SELECT * FROM bets
                WHERE user_id = ? AND market = ?
                ORDER BY created_at_ms DESC
            """, (uid, mkt_upper))
    else:
        if cutoff_ms > 0:
            c.execute("""
                SELECT * FROM bets
                WHERE user_id = ? AND (created_at_ms >= ? OR created_at_ms = 0)
                ORDER BY created_at_ms DESC
            """, (uid, cutoff_ms))
        else:
            c.execute("""
                SELECT * FROM bets
                WHERE user_id = ?
                ORDER BY created_at_ms DESC
            """, (uid,))
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

        fee_amt = round(float(r["platform_fee"] or 0.0), 2) if "platform_fee" in r.keys() else round(amt * 0.03, 2)
        net_amt = round(float(r["net_amount"] or 0.0), 2) if "net_amount" in r.keys() and float(r["net_amount"] or 0.0) > 0.0 else round(amt - fee_amt, 2)

        bet_ts_ms = _parse_ts_ms(r["created_at"], r["created_at_ms"] if "created_at_ms" in r.keys() else 0)
        bets_list.append({
            "id": r["bet_id"],
            "userId": r["user_id"],
            "userName": r["user_name"],
            "marketId": r["market"],
            "marketName": f"{r['market']} MARKET",
            "roundId": r["round_id"],
            "period": r["period"],
            "amount": round(amt, 2),
            "platformFee": fee_amt,
            "netAmount": net_amt,
            "type": r["prediction_type"],
            "target": r["prediction_target"],
            "mult": float(r["multiplier"] or 0.0),
            "potentialPayout": float(r["potential_payout"] or 0.0),
            "status": st,
            "result": r["result_text"],
            "winAmount": round(win_amt, 2),
            "lossAmount": round(loss_amt, 2),
            "netProfitLoss": net_pl,
            "time": to_ist_display(r["created_at"], bet_ts_ms, mode="datetime"),
            "settledAt": to_ist_display(r["settled_at"], 0, mode="datetime") if r["settled_at"] else None,
            "createdAtMs": bet_ts_ms
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
            "time": format_ist_datetime(ts_ms),
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
            "time": format_ist_datetime(ts_ms),
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

        if tx_type in ("COMMISSION", "REFERRAL_COMMISSION", "AFFILIATE_CLAIM"):
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
            "time": format_ist_datetime(ts_ms),
            "timestampMs": ts_ms
        })

    for rc in ref_rows:
        rc_st = str(rc["status"] or "").upper()
        if rc_st in ("UNCLAIMED", "PENDING", "CLAIMED", "REVERSED"):
            continue
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
                "status": rc_st or "SETTLED",
                "reason": None,
                "time": format_ist_datetime(ts_ms),
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
        filtered_entries = [e for e in statement_entries if e["category"] == "REFERRAL" or e["type"] in ("COMMISSION", "REFERRAL_COMMISSION", "AFFILIATE_CLAIM")]
    elif cat_upper == "DEPOSIT":
        filtered_entries = [e for e in statement_entries if e["type"] == "DEPOSIT"]
    elif cat_upper == "WITHDRAWAL":
        filtered_entries = [e for e in statement_entries if e["type"] in ("WITHDRAWAL", "WITHDRAWAL_REFUND")]
    else:
        filtered_entries = statement_entries

    summary = {
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
        "days": parsed_days if parsed_days else "ALL",
        "retentionDays": "PERMANENT",
        "category": cat_upper,
        "market": mkt_upper,
        "generatedAt": format_ist_datetime(now_ms),
        "summary": summary,
        "bets": bets_list,
        "statementEntries": filtered_entries
    }

def export_statement_csv(stmt):
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM for Microsoft Excel compatibility
    w = csv.writer(buf)
    s = stmt["summary"]

    period_lbl = "All Permanent Records" if str(stmt.get("days")) == "ALL" else f"Last {stmt['days']} Days (Permanent Vault)"
    w.writerow(["COLOUR KING - PERMANENT ACCOUNT & BETTING STATEMENT"])
    w.writerow(["User ID", stmt["userId"], "User Name", stmt["userName"], "Statement Period", period_lbl, "Generated At", stmt["generatedAt"]])
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
    w.writerow(["Placed At", "Bet ID", "Market", "Period Number", "Prediction Type", "Target", "Multiplier", "Gross Stake (INR)", "Platform Fee 3% (INR)", "Net Stake (INR)", "Status", "Payout Won (INR)", "Net Profit/Loss (INR)", "Official Result"])
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
            f"{b.get('platformFee', 0.0):.2f}",
            f"{b.get('netAmount', b['amount']):.2f}",
            b["status"],
            f"{b['winAmount']:.2f}",
            f"{b['netProfitLoss']:+.2f}",
            b["result"]
        ])

    return buf.getvalue()

def build_user_affiliates(conn, uid):
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    root_u = c.fetchone()
    if not root_u:
        return None

    ref_code = (root_u["referral_code"] if "referral_code" in root_u.keys() and root_u["referral_code"] else uid[-6:].upper())

    # BFS up to 6 subordinate tiers
    members = []
    visited = {uid}
    frontier = [uid]
    for tier in range(1, 7):
        if not frontier:
            break
        placeholders = ",".join("?" for _ in frontier)
        c.execute(f"SELECT id, name, total_deposit, status, created_at FROM users WHERE referred_by IN ({placeholders})", tuple(frontier))
        children = c.fetchall()
        next_frontier = []
        for ch in children:
            cid = ch["id"]
            if cid in visited:
                continue
            visited.add(cid)
            next_frontier.append(cid)
            c.execute("""
                SELECT COALESCE(SUM(amount), 0.0) FROM bets
                WHERE user_id = ? AND status NOT IN ('CANCELLED', 'REFUNDED')
            """, (cid,))
            ch_turnover = float(c.fetchone()[0] or 0.0)
            c.execute("""
                SELECT COALESCE(SUM(commission_amount), 0.0) FROM referral_commissions
                WHERE beneficiary_user_id = ? AND source_user_id = ? AND status != 'REVERSED'
            """, (uid, cid))
            ch_comm = float(c.fetchone()[0] or 0.0)
            members.append({
                "id": cid,
                "name": ch["name"],
                "tier": tier,
                "tierLabel": f"Tier {tier} (Direct)" if tier == 1 else f"Tier {tier}",
                "joined": ist_date_str(ch["created_at"], 0),
                "totalDeposit": round(float(ch["total_deposit"] or 0.0), 2),
                "turnover": round(ch_turnover, 2),
                "commission": round(ch_comm, 2),
                "status": ch["status"] or "ACTIVE"
            })
        frontier = next_frontier

    c.execute("""
        SELECT * FROM referral_commissions
        WHERE beneficiary_user_id = ? AND status != 'REVERSED'
        ORDER BY created_at_ms DESC
    """, (uid,))
    all_comm_rows = c.fetchall()

    level_breakdown = []
    for lvl, rate_val in REFERRAL_TIER_RATES:
        lvl_members = [m for m in members if m["tier"] == lvl]
        lvl_comms = [r for r in all_comm_rows if int(r["level"] or 1) == lvl]
        lvl_earned = round(sum(float(r["commission_amount"] or 0.0) for r in lvl_comms), 2)
        lvl_unclaimed = round(sum(float(r["commission_amount"] or 0.0) for r in lvl_comms if str(r["status"] or "").upper() in ("UNCLAIMED", "PENDING")), 2)
        lvl_claimed = round(sum(float(r["commission_amount"] or 0.0) for r in lvl_comms if str(r["status"] or "").upper() in ("CLAIMED", "SETTLED", "COMPLETED")), 2)
        lvl_turnover = round(sum(m["turnover"] for m in lvl_members), 2)
        if lvl_turnover <= 0 and lvl_comms:
            lvl_turnover = round(sum(float(r["eligible_amount"] or 0.0) for r in lvl_comms), 2)
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

    lifetime_comm = round(sum(float(r["commission_amount"] or 0.0) for r in all_comm_rows), 2)
    claimable_balance = round(sum(float(r["commission_amount"] or 0.0) for r in all_comm_rows if str(r["status"] or "").upper() in ("UNCLAIMED", "PENDING")), 2)

    ist_now = get_ist_now()
    ist_midnight = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ms = int(ist_midnight.timestamp() * 1000)
    today_comm = round(sum(
        float(r["commission_amount"] or 0.0)
        for r in all_comm_rows
        if _parse_ts_ms(r["created_at"], r["created_at_ms"] if "created_at_ms" in r.keys() else 0) >= today_start_ms
    ), 2)

    network_turnover = round(sum(m["turnover"] for m in members), 2)
    if network_turnover <= 0:
        network_turnover = round(sum(float(r["eligible_amount"] or 0.0) for r in all_comm_rows), 2)

    recent_commissions = [{
        "id": r["id"],
        "beneficiaryUserId": r["beneficiary_user_id"],
        "sourceUserId": r["source_user_id"],
        "sourceUserName": r["source_user_name"] or r["source_user_id"],
        "sourceBetId": r["source_bet_id"] or "",
        "level": int(r["level"] or 1),
        "rate": float(r["rate"] or 0.01),
        "eligibleAmount": round(float(r["eligible_amount"] or 0.0), 2),
        "commissionAmount": round(float(r["commission_amount"] or 0.0), 2),
        "status": str(r["status"] or "UNCLAIMED").upper(),
        "createdAt": to_ist_display(r["created_at"], r["created_at_ms"], mode="datetime"),
        "createdAtMs": _parse_ts_ms(r["created_at"], r["created_at_ms"])
    } for r in all_comm_rows[:1000]]

    c.execute("""
        SELECT * FROM transactions
        WHERE user_id = ? AND type = 'AFFILIATE_CLAIM'
        ORDER BY created_at_ms DESC
    """, (uid,))
    claim_tx_rows = c.fetchall()
    claim_history = [{
        "id": tx["tx_id"],
        "title": tx["title"] or "Affiliate Bonus Claimed",
        "ref": tx["ref"] or "Credited to Main Wallet",
        "amount": round(float(tx["amount"] or 0.0), 2),
        "balanceBefore": round(float(tx["balance_before"] or 0.0), 2),
        "balanceAfter": round(float(tx["balance_after"] or 0.0), 2),
        "status": "CREDITED",
        "createdAt": to_ist_display(tx["created_at"], tx["created_at_ms"] if "created_at_ms" in tx.keys() else 0, mode="datetime"),
        "createdAtMs": _parse_ts_ms(tx["created_at"], tx["created_at_ms"] if "created_at_ms" in tx.keys() else 0)
    } for tx in claim_tx_rows]
    total_claimed = round(sum(ch["amount"] for ch in claim_history), 2)

    return {
        "userId": uid,
        "userName": root_u["name"],
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

def compute_live_wagers_and_market_stats(conn, now_ms=None):
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    c = conn.cursor()
    live_wagers = {}
    market_stats = {}

    for m_code in MARKET_KEYS:
        auth = calculate_authoritative_round(m_code, now_ms)
        cur_period = auth["period"]

        pool = {
            "market": m_code,
            "period": cur_period,
            "green": 0.0,
            "greenBets": 0,
            "violet": 0.0,
            "violetBets": 0,
            "red": 0.0,
            "redBets": 0,
            "big": 0.0,
            "bigBets": 0,
            "small": 0.0,
            "smallBets": 0,
            "numbers": [0.0] * 10,
            "numberBets": [0] * 10,
            "totalPool": 0.0,
            "totalBets": 0,
        }

        c.execute("""
            SELECT prediction_type, prediction_target, amount
            FROM bets
            WHERE market = ? AND period = ? AND UPPER(status) IN ('PENDING', 'LOCKED')
        """, (m_code, cur_period))
        for row in c.fetchall():
            amt = round(float(row["amount"] or 0.0), 2)
            btype = str(row["prediction_type"] or "").upper().strip()
            target = str(row["prediction_target"] or "").upper().strip()

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

        c.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN UPPER(status) NOT IN ('CANCELLED', 'REFUNDED') THEN amount ELSE 0.0 END), 0.0) AS turnover,
                COALESCE(SUM(CASE WHEN UPPER(status) IN ('WON', 'LOST') THEN amount ELSE 0.0 END), 0.0) AS settled_turnover,
                COALESCE(SUM(CASE WHEN UPPER(status) = 'WON' THEN win_amount ELSE 0.0 END), 0.0) AS payout,
                COUNT(CASE WHEN UPPER(status) NOT IN ('CANCELLED', 'REFUNDED') THEN 1 END) AS total_bets
            FROM bets
            WHERE market = ?
        """, (m_code,))
        srow = c.fetchone()
        turnover = round(float(srow["turnover"] or 0.0), 2) if srow else 0.0
        settled_turnover = round(float(srow["settled_turnover"] or 0.0), 2) if srow else 0.0
        payout = round(float(srow["payout"] or 0.0), 2) if srow else 0.0
        total_bets_mkt = int(srow["total_bets"] or 0) if srow else 0
        net_house = round(settled_turnover - payout, 2)
        margin_pct = round((net_house / settled_turnover) * 100.0, 1) if settled_turnover > 0.0 else 0.0

        market_stats[m_code] = {
            "market": m_code,
            "period": cur_period,
            "activePool": pool["totalPool"],
            "activeBetsCount": pool["totalBets"],
            "turnover": turnover,
            "settledTurnover": settled_turnover,
            "payout": payout,
            "netHouseProfit": net_house,
            "marginPct": margin_pct,
            "totalBetsCount": total_bets_mkt,
        }

    return live_wagers, market_stats

def compute_admin_kpis(conn):
    c = conn.cursor()
    c.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN UPPER(status) IN ('SUCCESS', 'APPROVED') THEN amount ELSE 0.0 END), 0.0) AS total_dep,
            COUNT(CASE WHEN UPPER(status) IN ('SUCCESS', 'APPROVED') THEN 1 END) AS approved_dep_count,
            COUNT(CASE WHEN UPPER(status) IN ('IN PROCESS', 'PENDING') THEN 1 END) AS pending_dep_count
        FROM deposits
    """)
    drow = c.fetchone()
    total_dep = round(float(drow["total_dep"] or 0.0), 2) if drow else 0.0
    approved_dep_count = int(drow["approved_dep_count"] or 0) if drow else 0
    pending_dep_count = int(drow["pending_dep_count"] or 0) if drow else 0

    c.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN UPPER(status) IN ('SUCCESS', 'APPROVED') THEN amount ELSE 0.0 END), 0.0) AS total_wd,
            COUNT(CASE WHEN UPPER(status) IN ('IN PROCESS', 'PENDING') THEN 1 END) AS pending_wd_count
        FROM withdrawals
    """)
    wrow = c.fetchone()
    total_wd = round(float(wrow["total_wd"] or 0.0), 2) if wrow else 0.0
    pending_wd_count = int(wrow["pending_wd_count"] or 0) if wrow else 0

    c.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN UPPER(status) NOT IN ('CANCELLED', 'REFUNDED') THEN amount ELSE 0.0 END), 0.0) AS turnover,
            COUNT(CASE WHEN UPPER(status) NOT IN ('CANCELLED', 'REFUNDED') THEN 1 END) AS bets_count
        FROM bets
    """)
    brow = c.fetchone()
    turnover = round(float(brow["turnover"] or 0.0), 2) if brow else 0.0
    bets_count = int(brow["bets_count"] or 0) if brow else 0

    c.execute("""
        SELECT
            COUNT(*) AS total_users,
            COUNT(CASE WHEN UPPER(status) = 'ACTIVE' THEN 1 END) AS active_users,
            COUNT(CASE WHEN UPPER(status) = 'BLOCKED' THEN 1 END) AS blocked_users
        FROM users
    """)
    urow = c.fetchone()
    total_users = int(urow["total_users"] or 0) if urow else 0
    active_users = int(urow["active_users"] or 0) if urow else 0
    blocked_users = int(urow["blocked_users"] or 0) if urow else 0

    net_profit = round(total_dep - total_wd, 2)
    margin_pct = round((net_profit / total_dep) * 100.0, 2) if total_dep > 0.0 else 0.0

    return {
        "totalDeposits": total_dep,
        "approvedDepositsCount": approved_dep_count,
        "pendingDepositsCount": pending_dep_count,
        "totalWithdrawals": total_wd,
        "pendingWithdrawalsCount": pending_wd_count,
        "netProfit": net_profit,
        "marginPct": margin_pct,
        "totalTurnover": turnover,
        "totalBetsCount": bets_count,
        "totalUsers": total_users,
        "activeUsers": active_users,
        "blockedUsers": blocked_users,
    }

def build_user_support_situation(conn, uid):
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    u = c.fetchone()
    if not u:
        return None

    c.execute("SELECT value FROM app_state WHERE key = 'bank_config'")
    bcfg_row = c.fetchone()
    bank_cfg = json.loads(bcfg_row[0]) if bcfg_row else DEFAULT_BANK_CONFIG

    c.execute("SELECT * FROM deposits WHERE user_id = ? ORDER BY created_at_ms DESC, created_at DESC LIMIT 5", (uid,))
    deps = c.fetchall()
    latest_dep = deps[0] if deps else None
    pending_dep = next((d for d in deps if str(d["status"] or "").upper() in ("IN PROCESS", "PENDING")), None)
    failed_dep = next((d for d in deps if str(d["status"] or "").upper() in ("FAIL", "REJECTED")), None)

    c.execute("SELECT * FROM withdrawals WHERE user_id = ? ORDER BY created_at_ms DESC, created_at DESC LIMIT 5", (uid,))
    wds = c.fetchall()
    latest_wd = wds[0] if wds else None
    pending_wd = next((w for w in wds if str(w["status"] or "").upper() in ("IN PROCESS", "PENDING")), None)
    failed_wd = next((w for w in wds if str(w["status"] or "").upper() in ("FAIL", "REJECTED")), None)

    c.execute("""
        SELECT * FROM transactions
        WHERE user_id = ? AND UPPER(type) = 'ADJUSTMENT'
        ORDER BY created_at_ms DESC, created_at DESC LIMIT 1
    """, (uid,))
    last_adj = c.fetchone()

    c.execute("SELECT * FROM bets WHERE user_id = ? ORDER BY created_at_ms DESC LIMIT 1", (uid,))
    latest_bet = c.fetchone()
    c.execute("SELECT COUNT(*) FROM bets WHERE user_id = ? AND UPPER(status) IN ('PENDING', 'LOCKED')", (uid,))
    active_bets_count = int(c.fetchone()[0] or 0)

    def dep_to_dict(d):
        if not d:
            return None
        d_ms = _parse_ts_ms(d["created_at"], d["created_at_ms"] if "created_at_ms" in d.keys() else 0)
        return {
            "id": d["id"],
            "amount": round(float(d["amount"] or 0.0), 2),
            "method": d["method"] or "UPI",
            "utr": d["utr"] or "",
            "status": str(d["status"] or "IN PROCESS").upper(),
            "reason": d["reason"] or "",
            "time": to_ist_display(d["created_at"], d_ms, mode="display"),
            "createdAtMs": d_ms,
        }

    def wd_to_dict(w):
        if not w:
            return None
        w_ms = _parse_ts_ms(w["created_at"], w["created_at_ms"] if "created_at_ms" in w.keys() else 0)
        return {
            "id": w["id"],
            "amount": round(float(w["amount"] or 0.0), 2),
            "destination": w["destination"] or "",
            "status": str(w["status"] or "IN PROCESS").upper(),
            "reason": w["reason"] or "",
            "time": to_ist_display(w["created_at"], w_ms, mode="display"),
            "createdAtMs": w_ms,
        }

    return {
        "userId": u["id"],
        "userName": u["name"],
        "phone": u["phone"] or "",
        "accountStatus": str(u["status"] or "ACTIVE").upper(),
        "balance": round(float(u["balance"] or 0.0), 2),
        "totalDeposit": round(float(u["total_deposit"] or 0.0), 2),
        "totalWithdraw": round(float(u["total_withdraw"] or 0.0), 2),
        "activeBetsCount": active_bets_count,
        "latestDeposit": dep_to_dict(latest_dep),
        "pendingDeposit": dep_to_dict(pending_dep),
        "failedDeposit": dep_to_dict(failed_dep),
        "latestWithdrawal": wd_to_dict(latest_wd),
        "pendingWithdrawal": wd_to_dict(pending_wd),
        "failedWithdrawal": wd_to_dict(failed_wd),
        "lastAdjustment": {
            "txId": last_adj["tx_id"],
            "amount": round(float(last_adj["amount"] or 0.0), 2),
            "ref": last_adj["ref"] or "",
            "time": to_ist_display(last_adj["created_at"], last_adj["created_at_ms"] if "created_at_ms" in last_adj.keys() else 0, mode="display"),
        } if last_adj else None,
        "latestBet": {
            "id": latest_bet["bet_id"],
            "market": latest_bet["market"],
            "period": latest_bet["period"],
            "target": latest_bet["prediction_target"],
            "amount": round(float(latest_bet["amount"] or 0.0), 2),
            "status": str(latest_bet["status"] or "PENDING").upper(),
            "result": latest_bet["result_text"] or "",
        } if latest_bet else None,
        "upiId": bank_cfg.get("upiId", DEFAULT_BANK_CONFIG["upiId"]),
        "bankName": bank_cfg.get("bankName", DEFAULT_BANK_CONFIG["bankName"]),
        "minDeposit": bank_cfg.get("minDeposit", 100),
        "maxDeposit": bank_cfg.get("maxDeposit", 100000),
    }

def generate_support_auto_reply(conn, uid, user_message="", category="GENERAL"):
    sit = build_user_support_situation(conn, uid)
    if not sit:
        return "SUPPORT_GENERAL", "Welcome to Colour King 24/7 Support! Please log in or share your User ID so an Admin agent can assist you."

    msg_l = str(user_message or "").lower()
    cat_u = str(category or "GENERAL").upper().strip()
    bal_str = f"₹{sit['balance']:,.2f}"
    parts = []
    tag = "SUPPORT_GENERAL"

    # 1. Blocked account priority
    if sit["accountStatus"] == "BLOCKED" or cat_u == "ACCOUNT" or any(k in msg_l for k in ("block", "ban", "suspend", "unblock", "locked", "account")):
        if sit["accountStatus"] == "BLOCKED":
            tag = "ACCOUNT_BLOCKED"
            parts.append(f"⚠️ Account Alert ({sit['userId']}): Your account is currently RESTRICTED / BLOCKED by Admin security review.")
            parts.append("Your ticket has been marked high-priority for Admin review. An Admin will inspect your compliance check and reply here shortly.")
        else:
            tag = "ACCOUNT_ACTIVE"
            parts.append(f"✅ Account Status: {sit['userName']} ({sit['userId']}) is ACTIVE & verified. Current Wallet Balance: {bal_str}.")

    # 2. Deposit / UTR situation
    asks_deposit = cat_u == "DEPOSIT" or any(k in msg_l for k in ("deposit", "utr", "add money", "recharge", "upi", "payment", "credit"))
    if asks_deposit or (not msg_l and (sit["failedDeposit"] or sit["pendingDeposit"])):
        dep = sit["failedDeposit"] if (sit["failedDeposit"] and (not sit["pendingDeposit"] or "reject" in msg_l or "fail" in msg_l)) else (sit["pendingDeposit"] or sit["latestDeposit"])
        if sit["pendingDeposit"] and asks_deposit:
            pd = sit["pendingDeposit"]
            tag = "DEPOSIT_IN_PROCESS"
            parts.append(f"⏳ Pending Deposit Detected: {pd['id']} for ₹{pd['amount']:,.2f} (UTR: {pd['utr']} via {pd['method']}) is currently IN PROCESS in the Admin verification queue.")
            parts.append(f"Current Admin UPI Gateway: {sit['upiId']} ({sit['bankName']}). Once Admin verifies the UTR, balance credits automatically.")
        elif sit["failedDeposit"] and (asks_deposit or not parts):
            fd = sit["failedDeposit"]
            tag = "DEPOSIT_REJECTED"
            parts.append(f"❌ Recent Deposit {fd['id']} (₹{fd['amount']:,.2f}, UTR: {fd['utr']}) was REJECTED (FAIL). Reason: {fd['reason'] or 'Verification failed'}.")
            parts.append(f"Please double-check your payment UTR and pay to current UPI ID: {sit['upiId']} ({sit['bankName']}), or wait for Admin custom assistance below.")
        elif dep and asks_deposit:
            tag = "DEPOSIT_STATUS"
            parts.append(f"💳 Latest Deposit {dep['id']}: ₹{dep['amount']:,.2f} (UTR: {dep['utr']}) • Status: {dep['status']}. Active UPI ID: {sit['upiId']} (Min ₹{sit['minDeposit']}).")
        elif asks_deposit:
            tag = "DEPOSIT_GUIDE"
            parts.append(f"💳 Deposit Help: Send ₹{sit['minDeposit']}–₹{sit['maxDeposit']} via UPI ({sit['upiId']}) or {sit['bankName']}, then submit your 12-digit UTR in Wallet → Deposit.")

    # 3. Withdrawal / Payout situation
    asks_wd = cat_u == "WITHDRAWAL" or any(k in msg_l for k in ("withdraw", "payout", "bank", "cashout", "refund", "imps"))
    if asks_wd or (not msg_l and not parts and (sit["failedWithdrawal"] or sit["pendingWithdrawal"])):
        wd = sit["pendingWithdrawal"] or sit["failedWithdrawal"] or sit["latestWithdrawal"]
        if sit["pendingWithdrawal"] and asks_wd:
            pw = sit["pendingWithdrawal"]
            tag = "WITHDRAWAL_IN_PROCESS"
            parts.append(f"⏳ Pending Withdrawal {pw['id']}: ₹{pw['amount']:,.2f} is IN PROCESS in the Admin escrow payout queue ({pw['destination']}).")
        elif sit["failedWithdrawal"] and (asks_wd or not parts):
            fw = sit["failedWithdrawal"]
            tag = "WITHDRAWAL_REJECTED_REFUNDED"
            parts.append(f"↩️ Withdrawal {fw['id']} (₹{fw['amount']:,.2f}) was REJECTED (FAIL). Reason: {fw['reason'] or 'Bank details mismatch'}. The full ₹{fw['amount']:,.2f} has been refunded to your wallet (Current Balance: {bal_str}).")
        elif wd and asks_wd:
            tag = "WITHDRAWAL_STATUS"
            parts.append(f"🏦 Latest Withdrawal {wd['id']}: ₹{wd['amount']:,.2f} • Status: {wd['status']}. Current Wallet Balance: {bal_str}.")
        elif asks_wd:
            tag = "WITHDRAWAL_GUIDE"
            parts.append(f"🏦 Withdrawal Help: Current Wallet Balance is {bal_str}. You can submit IMPS/UPI payouts from Wallet → Withdraw and track live Admin approval status.")

    # 4. Bet / Draw / 3% Platform Fee
    asks_bet = cat_u == "BET" or any(k in msg_l for k in ("bet", "win", "loss", "result", "draw", "period", "fee", "multiplier", "round"))
    if asks_bet:
        tag = "BET_STATUS"
        if sit["latestBet"]:
            lb = sit["latestBet"]
            parts.append(f"🎲 Latest Bet {lb['id']}: {lb['market']} #{lb['period']} on {lb['target']} for ₹{lb['amount']:,.2f} • Status: {lb['status']} ({lb['result']}). Active open bets: {sit['activeBetsCount']}.")
        parts.append("Note: Every wager carries a 3% platform fee (97% active stake × decided multiplier), locks in the final 30 seconds of each 3-minute round, and settles via Provably Fair SHA-256 / Admin draw.")

    # 5. Fallback / General Greeting with live snapshot
    if not parts:
        tag = "SUPPORT_OVERVIEW"
        summary_bits = [f"Account: {sit['accountStatus']}", f"Balance: {bal_str}"]
        if sit["pendingDeposit"]:
            summary_bits.append(f"Pending Deposit ₹{sit['pendingDeposit']['amount']:,.2f}")
        elif sit["failedDeposit"]:
            summary_bits.append(f"Rejected Deposit {sit['failedDeposit']['id']}")
        if sit["pendingWithdrawal"]:
            summary_bits.append(f"Pending Withdrawal ₹{sit['pendingWithdrawal']['amount']:,.2f}")
        elif sit["failedWithdrawal"]:
            summary_bits.append(f"Rejected Withdrawal {sit['failedWithdrawal']['id']} (Refunded)")
        if sit["lastAdjustment"]:
            adj = sit["lastAdjustment"]
            summary_bits.append(f"Last Admin Adj: {adj['amount']:+.2f} ({adj['ref']})")
        parts.append(f"🤖 24/7 Live Auto-Support for {sit['userName']} ({sit['userId']}) — " + " • ".join(summary_bits) + ".")
        parts.append("Your message has been delivered to Admin Support. An Admin agent can send a custom reply directly in this chat anytime.")
    elif cat_u != "WELCOME":
        parts.append("💬 Delivered to 24/7 Admin Desk — an Admin can also send a custom reply right here.")

    return tag, "\n".join(parts)

def ensure_support_ticket_and_add_message(
    conn,
    uid,
    user_name,
    sender_type,
    sender_name,
    message,
    category="GENERAL",
    is_auto=0,
    situation_tag="",
    now_ms=None,
    attachment_name="",
    attachment_mime="",
    attachment_size=0,
    attachment_url="",
):
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    att_name = str(attachment_name or "").strip()[:160]
    att_mime = str(attachment_mime or "").strip()[:120]
    att_size = max(0, int(attachment_size or 0))
    att_url = str(attachment_url or "").strip()[:300]
    clean_msg = str(message or "").strip()
    preview_text = clean_msg if clean_msg else (f"📎 {att_name}" if att_name else "📎 Media Attachment")
    preview_text = preview_text[:200]

    c = conn.cursor()
    c.execute("SELECT * FROM support_tickets WHERE user_id = ? ORDER BY updated_at_ms DESC LIMIT 1", (uid,))
    trow = c.fetchone()
    if trow:
        ticket_id = trow["ticket_id"]
    else:
        ticket_id = f"TKT-{uid}"
        c.execute("""
            INSERT INTO support_tickets (ticket_id, user_id, user_name, status, category, last_message, last_sender, unread_admin, unread_user, updated_at_ms)
            VALUES (?, ?, ?, 'OPEN', ?, ?, ?, 0, 0, ?)
        """, (ticket_id, uid, user_name, category, preview_text, sender_type, now_ms))

    msg_id = f"MSG-{int(now_ms)}-{random.randint(1000, 9999)}"
    c.execute("""
        INSERT INTO support_messages (
            id, ticket_id, user_id, sender_type, sender_name, category, message, is_auto, situation_tag,
            attachment_name, attachment_mime, attachment_size, attachment_url, created_at_ms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        msg_id, ticket_id, uid, sender_type, sender_name, category, clean_msg, 1 if is_auto else 0, situation_tag,
        att_name, att_mime, att_size, att_url, now_ms
    ))

    if sender_type == "USER":
        c.execute("""
            UPDATE support_tickets
            SET user_name = ?, status = 'OPEN', category = ?, last_message = ?, last_sender = ?,
                unread_admin = unread_admin + 1, updated_at = CURRENT_TIMESTAMP, updated_at_ms = ?
            WHERE ticket_id = ?
        """, (user_name, category, preview_text, sender_type, now_ms, ticket_id))
    elif sender_type == "ADMIN":
        c.execute("""
            UPDATE support_tickets
            SET user_name = ?, status = 'OPEN', last_message = ?, last_sender = 'ADMIN',
                unread_admin = 0, unread_user = unread_user + 1, updated_at = CURRENT_TIMESTAMP, updated_at_ms = ?
            WHERE ticket_id = ?
        """, (user_name, preview_text, now_ms, ticket_id))
    else:  # AUTO_BOT
        c.execute("""
            UPDATE support_tickets
            SET user_name = ?, last_message = ?, last_sender = 'AUTO_BOT',
                unread_user = unread_user + 1, updated_at = CURRENT_TIMESTAMP, updated_at_ms = ?
            WHERE ticket_id = ?
        """, (user_name, preview_text, now_ms, ticket_id))

    return ticket_id, msg_id

def record_admin_situation_support_message(conn, uid, situation_tag, message, category="ADMIN_ALERT", create_if_missing=True, now_ms=None):
    if not uid:
        return None
    c = conn.cursor()
    c.execute("SELECT id, name FROM users WHERE id = ?", (uid,))
    u = c.fetchone()
    if not u:
        return None
    if not create_if_missing:
        c.execute("SELECT 1 FROM support_tickets WHERE user_id = ? LIMIT 1", (uid,))
        if not c.fetchone():
            return None
    tid, _ = ensure_support_ticket_and_add_message(
        conn,
        uid=uid,
        user_name=u["name"],
        sender_type="AUTO_BOT",
        sender_name="Colour King 24/7 Support Bot",
        message=message,
        category=category,
        is_auto=1,
        situation_tag=situation_tag,
        now_ms=now_ms,
    )
    return tid

def fetch_support_thread_payload(conn, uid, mark_read_for=None, auto_welcome=False):
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    u = c.fetchone()
    if not u:
        return None

    c.execute("SELECT * FROM support_tickets WHERE user_id = ? ORDER BY updated_at_ms DESC LIMIT 1", (uid,))
    trow = c.fetchone()
    if not trow and auto_welcome:
        tag, greeting = generate_support_auto_reply(conn, uid, "", category="WELCOME")
        ensure_support_ticket_and_add_message(
            conn,
            uid=uid,
            user_name=u["name"],
            sender_type="AUTO_BOT",
            sender_name="Colour King 24/7 Support Bot",
            message=greeting,
            category="WELCOME",
            is_auto=1,
            situation_tag=tag,
        )
        # Do not leave initial welcome counted as unread if user is opening it right now
        if mark_read_for == "USER":
            c.execute("UPDATE support_tickets SET unread_user = 0 WHERE user_id = ?", (uid,))
        commit_and_persist(conn, critical=True)
        c.execute("SELECT * FROM support_tickets WHERE user_id = ? ORDER BY updated_at_ms DESC LIMIT 1", (uid,))
        trow = c.fetchone()
    elif trow and mark_read_for == "USER" and int(trow["unread_user"] or 0) > 0:
        c.execute("UPDATE support_tickets SET unread_user = 0 WHERE ticket_id = ?", (trow["ticket_id"],))
        commit_and_persist(conn, critical=False)
        c.execute("SELECT * FROM support_tickets WHERE ticket_id = ?", (trow["ticket_id"],))
        trow = c.fetchone()

    ticket_dict = None
    messages = []
    if trow:
        ticket_dict = {
            "ticketId": trow["ticket_id"],
            "userId": trow["user_id"],
            "userName": trow["user_name"] or u["name"],
            "status": trow["status"] or "OPEN",
            "category": trow["category"] or "GENERAL",
            "lastMessage": trow["last_message"] or "",
            "lastSender": trow["last_sender"] or "AUTO_BOT",
            "unreadAdmin": int(trow["unread_admin"] or 0),
            "unreadUser": int(trow["unread_user"] or 0),
            "updatedAt": to_ist_display(trow["updated_at"], trow["updated_at_ms"], mode="display"),
            "updatedAtMs": _parse_ts_ms(trow["updated_at"], trow["updated_at_ms"]),
        }
        c.execute("""
            SELECT * FROM support_messages
            WHERE ticket_id = ?
            ORDER BY created_at_ms ASC, id ASC
        """, (trow["ticket_id"],))
        messages = [{
            "id": m["id"],
            "ticketId": m["ticket_id"],
            "userId": m["user_id"],
            "senderType": m["sender_type"],
            "senderName": m["sender_name"],
            "category": m["category"] or "GENERAL",
            "message": m["message"],
            "isAuto": bool(m["is_auto"]),
            "situationTag": m["situation_tag"] or "",
            "attachmentName": (m["attachment_name"] if "attachment_name" in m.keys() and m["attachment_name"] else ""),
            "attachmentMime": (m["attachment_mime"] if "attachment_mime" in m.keys() and m["attachment_mime"] else ""),
            "attachmentSize": int(m["attachment_size"] or 0) if "attachment_size" in m.keys() else 0,
            "attachmentUrl": (m["attachment_url"] if "attachment_url" in m.keys() and m["attachment_url"] else ""),
            "createdAt": to_ist_display(m["created_at"], m["created_at_ms"], mode="display"),
            "createdAtMs": _parse_ts_ms(m["created_at"], m["created_at_ms"]),
        } for m in c.fetchall()]

    situation = build_user_support_situation(conn, uid)
    return {
        "success": True,
        "ticket": ticket_dict,
        "messages": messages,
        "situation": situation,
        "unreadUser": ticket_dict["unreadUser"] if ticket_dict else 0,
    }

def list_admin_support_tickets(conn):
    c = conn.cursor()
    c.execute("""
        SELECT t.*, u.phone, u.balance, u.status AS user_status
        FROM support_tickets t
        LEFT JOIN users u ON u.id = t.user_id
        ORDER BY (CASE WHEN UPPER(t.status) = 'OPEN' THEN 0 ELSE 1 END) ASC, t.unread_admin DESC, t.updated_at_ms DESC
    """)
    tickets = []
    total_unread_admin = 0
    for r in c.fetchall():
        unread_a = int(r["unread_admin"] or 0)
        total_unread_admin += unread_a
        tid = r["ticket_id"]
        uid = r["user_id"]
        c.execute("""
            SELECT * FROM support_messages
            WHERE ticket_id = ?
            ORDER BY created_at_ms ASC, id ASC
            LIMIT 200
        """, (tid,))
        msgs = [{
            "id": m["id"],
            "ticketId": m["ticket_id"],
            "userId": m["user_id"],
            "senderType": m["sender_type"],
            "senderName": m["sender_name"],
            "category": m["category"] or "GENERAL",
            "message": m["message"],
            "isAuto": bool(m["is_auto"]),
            "situationTag": m["situation_tag"] or "",
            "attachmentName": (m["attachment_name"] if "attachment_name" in m.keys() and m["attachment_name"] else ""),
            "attachmentMime": (m["attachment_mime"] if "attachment_mime" in m.keys() and m["attachment_mime"] else ""),
            "attachmentSize": int(m["attachment_size"] or 0) if "attachment_size" in m.keys() else 0,
            "attachmentUrl": (m["attachment_url"] if "attachment_url" in m.keys() and m["attachment_url"] else ""),
            "createdAt": to_ist_display(m["created_at"], m["created_at_ms"], mode="display"),
            "created_at_ms": _parse_ts_ms(m["created_at"], m["created_at_ms"]),
            "createdAtMs": _parse_ts_ms(m["created_at"], m["created_at_ms"]),
        } for m in c.fetchall()]
        att_count = sum(1 for mm in msgs if mm.get("attachmentUrl"))
        sit = build_user_support_situation(conn, uid)
        tickets.append({
            "ticketId": tid,
            "userId": uid,
            "userName": r["user_name"] or (sit["userName"] if sit else uid),
            "phone": r["phone"] or "",
            "balance": round(float(r["balance"] or 0.0), 2) if r["balance"] is not None else 0.0,
            "userStatus": str(r["user_status"] or "ACTIVE").upper(),
            "status": str(r["status"] or "OPEN").upper(),
            "category": r["category"] or "GENERAL",
            "lastMessage": r["last_message"] or "",
            "lastSender": r["last_sender"] or "AUTO_BOT",
            "unreadAdmin": unread_a,
            "unreadUser": int(r["unread_user"] or 0),
            "attachmentCount": att_count,
            "updatedAt": to_ist_display(r["updated_at"], r["updated_at_ms"], mode="display"),
            "updatedAtMs": _parse_ts_ms(r["updated_at"], r["updated_at_ms"]),
            "situation": sit,
            "messages": msgs,
        })
    return tickets, total_unread_admin

class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _get_cookie_uid(self):
        cookie_hdr = self.headers.get("Cookie", "")
        if not cookie_hdr:
            return None
        for part in cookie_hdr.split(";"):
            part = part.strip()
            if part.startswith("ck_uid="):
                val = urllib.parse.unquote(part[len("ck_uid="):].strip())
                if val and val != "Guest":
                    return val
        return None

    def _build_session_cookie(self, uid, max_age=2592000):
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        origin = (self.headers.get("Origin") or "").lower()
        is_https = (proto == "https") or origin.startswith("https://")
        encoded = urllib.parse.quote(str(uid or ""), safe="")
        if is_https:
            return f"ck_uid={encoded}; Path=/; Max-Age={max_age}; SameSite=None; Secure"
        return f"ck_uid={encoded}; Path=/; Max-Age={max_age}; SameSite=Lax"

    def _send_cors_headers(self):
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-File-Name, X-File-Mime, X-User-Id")

    def _send_csv(self, csv_text, filename):
        try:
            body = csv_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self._send_cors_headers()
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"Error sending CSV response: {e}")

    def _send_json(self, data, status=200, cookies=None):
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            if cookies:
                for ck in cookies:
                    self.send_header("Set-Cookie", ck)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"Error sending response: {e}")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
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

        # 1. Authoritative Server Clock (Always Asia/Kolkata IST UTC+05:30)
        if path == "/api/clock":
            now_ms = int(time.time() * 1000)
            ist_dt = get_ist_now(now_ms)
            self._send_json({
                "server_time_ms": now_ms,
                "iso": datetime.now(timezone.utc).isoformat(),
                "ist_iso": ist_dt.isoformat(),
                "ist_time": ist_dt.strftime("%I:%M:%S %p IST"),
                "ist_time_24": ist_dt.strftime("%H:%M:%S IST"),
                "ist_date": ist_dt.strftime("%d %b %Y"),
                "ist_formatted": ist_dt.strftime("%d %b %Y, %I:%M:%S %p IST"),
                "timezone": "IST",
                "utc_offset": "+05:30"
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
                        SELECT period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at, end_time_ms
                        FROM rounds
                        WHERE market = ? AND status = 'SETTLED' AND result_number IS NOT NULL AND CAST(period AS INTEGER) < CAST(? AS INTEGER)
                        ORDER BY CAST(period AS INTEGER) DESC LIMIT 1
                    """, (m_code, period))
                    last_res = c.fetchone()
                    latest_result = None
                    if last_res:
                        res_end_ms = int(last_res["end_time_ms"] or 0) if "end_time_ms" in last_res.keys() else 0
                        if res_end_ms <= 0 and str(last_res["draw_mode"] or "") != "MANUAL_ADMIN":
                            res_end_ms = get_period_window_ms_ist(last_res["period"])[2]
                        latest_result = {
                            "period": last_res["period"],
                            "number": last_res["result_number"],
                            "color": last_res["result_color"],
                            "colClass": last_res["result_col_class"],
                            "isBig": bool(last_res["is_big"]),
                            "drawMode": last_res["draw_mode"],
                            "time": to_ist_display(last_res["declared_at"], res_end_ms, mode="datetime"),
                            "timestampMs": res_end_ms
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
                    SELECT period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at, end_time_ms
                    FROM rounds
                    WHERE market = ? AND status = 'SETTLED' AND result_number IS NOT NULL AND CAST(period AS INTEGER) < CAST(? AS INTEGER)
                    ORDER BY CAST(period AS INTEGER) DESC LIMIT ?
                """, (m_code, cur_auth["period"], limit))
                rows = c.fetchall()
                records = []
                for r in rows:
                    r_end_ms = int(r["end_time_ms"] or 0) if "end_time_ms" in r.keys() else 0
                    if r_end_ms <= 0 and str(r["draw_mode"] or "") != "MANUAL_ADMIN":
                        r_end_ms = get_period_window_ms_ist(r["period"])[2]
                    records.append({
                        "period": r["period"],
                        "number": r["result_number"],
                        "color": r["result_color"],
                        "colClass": r["result_col_class"],
                        "isBig": bool(r["is_big"]),
                        "drawMode": r["draw_mode"],
                        "time": to_ist_display(r["declared_at"], r_end_ms, mode="datetime"),
                        "timestampMs": r_end_ms
                    })
                conn.close()
            self._send_json({ "market": m_code, "records": records })
            return

        # 4. User Bets (Active bets for round + Bet Slips History)
        if path == "/api/bets":
            uid = (qs.get("userId", [None])[0] or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({
                    "userId": None,
                    "retentionDays": RETENTION_DAYS,
                    "days": RETENTION_DAYS,
                    "activeBets": [],
                    "betHistory": []
                })
                return
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

                # All permanent user bets history (never deleted; optional days filter if numeric)
                parsed_days = _parse_days_arg_server(qs.get("days", ["ALL"])[0], default_all=True)
                cutoff_ms = (now_ms - (parsed_days * 86400 * 1000)) if parsed_days else 0

                if m_code:
                    if cutoff_ms > 0:
                        c.execute("""
                            SELECT * FROM bets
                            WHERE user_id = ? AND market = ? AND (created_at_ms >= ? OR created_at_ms = 0)
                            ORDER BY created_at_ms DESC
                        """, (uid, m_code, cutoff_ms))
                    else:
                        c.execute("""
                            SELECT * FROM bets
                            WHERE user_id = ? AND market = ?
                            ORDER BY created_at_ms DESC
                        """, (uid, m_code))
                else:
                    if cutoff_ms > 0:
                        c.execute("""
                            SELECT * FROM bets
                            WHERE user_id = ? AND (created_at_ms >= ? OR created_at_ms = 0)
                            ORDER BY created_at_ms DESC
                        """, (uid, cutoff_ms))
                    else:
                        c.execute("""
                            SELECT * FROM bets
                            WHERE user_id = ?
                            ORDER BY created_at_ms DESC
                        """, (uid,))
                history_rows = c.fetchall()

                conn.close()

            def row_to_dict(r):
                amt = float(r["amount"] or 0.0)
                fee_amt = round(float(r["platform_fee"] or 0.0), 2) if "platform_fee" in r.keys() else round(amt * 0.03, 2)
                net_amt = round(float(r["net_amount"] or 0.0), 2) if "net_amount" in r.keys() and float(r["net_amount"] or 0.0) > 0.0 else round(amt - fee_amt, 2)
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
                    "platformFee": fee_amt,
                    "netAmount": net_amt,
                    "type": r["prediction_type"],
                    "target": r["prediction_target"],
                    "mult": r["multiplier"],
                    "potentialPayout": r["potential_payout"],
                    "status": r["status"],
                    "result": r["result_text"],
                    "winAmount": win_amt,
                    "lossAmount": float(r["loss_amount"] or 0.0),
                    "netProfitLoss": net_pl,
                    "time": to_ist_display(r["created_at"], r["created_at_ms"], mode="datetime"),
                    "createdAtMs": _parse_ts_ms(r["created_at"], r["created_at_ms"])
                }

            self._send_json({
                "userId": uid,
                "retentionDays": "PERMANENT",
                "days": parsed_days if parsed_days else "ALL",
                "activeBets": [row_to_dict(r) for r in active_rows],
                "betHistory": [row_to_dict(r) for r in history_rows]
            })
            return

        # 4B. Full Permanent Account Statement (Wallet, Bet P&L, Refer & Earn, Deposit, Withdrawal)
        if path == "/api/statement":
            uid = (qs.get("userId", [None])[0] or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Missing userId" }, status=400)
                return
            req_days = qs.get("days", ["ALL"])[0]
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
            uid = (qs.get("userId", [None])[0] or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Missing userId" }, status=400)
                return
            req_days = qs.get("days", ["ALL"])[0]
            cat = qs.get("category", ["ALL"])[0]
            mkt = qs.get("market", ["ALL"])[0]

            with db_lock:
                conn = get_db()
                stmt = build_user_statement(conn, uid, days=req_days, category=cat, market_filter=mkt)
                conn.close()
            csv_text = export_statement_csv(stmt)
            safe_uid = "".join(ch for ch in uid if ch.isalnum() or ch in ("-", "_")) or "user"
            fname = f"ColourKing_{stmt['days']}_Statement_{safe_uid}_{get_ist_now().strftime('%Y%m%d')}.csv"
            self._send_csv(csv_text, fname)
            return

        # 4D. 6-Tier User Affiliate Stats & Downline Directory
        if path == "/api/affiliates":
            uid = (qs.get("userId", [None])[0] or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Missing userId" }, status=400)
                return
            with db_lock:
                conn = get_db()
                aff = build_user_affiliates(conn, uid)
                conn.close()
            if not aff:
                self._send_json({ "success": False, "error": "User not found", "notFound": True }, status=404)
                return
            self._send_json(aff)
            return

        # 4E. Cookie / Session Restore Endpoint
        if path == "/api/session":
            uid = (qs.get("userId", [None])[0] or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "authenticated": False, "user": None })
                return
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                rec_token = build_user_recovery_token(u) if u else ""
                conn.close()
            if not u:
                self._send_json({ "authenticated": False, "user": None, "canRestoreWithToken": True }, cookies=[self._build_session_cookie("", max_age=0)])
                return
            self._send_json({
                "authenticated": True,
                "recoveryToken": rec_token,
                "user": {
                    "id": u["id"],
                    "userId": u["id"],
                    "name": u["name"],
                    "phone": u["phone"] or "",
                    "email": u["email"] or "",
                    "balance": round(float(u["balance"] or 0.0), 2),
                    "totalDeposit": round(float(u["total_deposit"] or 0.0), 2),
                    "totalWithdraw": round(float(u["total_withdraw"] or 0.0), 2),
                    "betsCount": int(u["bets_count"] or 0),
                    "status": u["status"] or "ACTIVE",
                    "referralCode": (u["referral_code"] if "referral_code" in u.keys() and u["referral_code"] else u["id"][-6:].upper()),
                    "referredBy": (u["referred_by"] if "referred_by" in u.keys() else None)
                }
            })
            return

        # 5. User Profile & Balance (Strict SQLite Lookup — NEVER auto-create 50,200 ghost users)
        if path == "/api/user" or path == "/api/wallet":
            uid = (qs.get("id", qs.get("userId", [None]))[0] or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Not authenticated", "notFound": True }, status=404)
                return
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                rec_token = build_user_recovery_token(u) if u else ""
                conn.close()

            if not u:
                self._send_json({ "success": False, "error": "User not found", "notFound": True }, status=404)
                return

            self._send_json({
                "id": u["id"],
                "userId": u["id"],
                "name": u["name"],
                "phone": u["phone"] or "",
                "email": u["email"] or "",
                "balance": round(float(u["balance"] or 0.0), 2),
                "totalDeposit": round(float(u["total_deposit"] or 0.0), 2),
                "totalWithdraw": round(float(u["total_withdraw"] or 0.0), 2),
                "betsCount": int(u["bets_count"] or 0),
                "status": u["status"] or "ACTIVE",
                "referralCode": (u["referral_code"] if "referral_code" in u.keys() and u["referral_code"] else u["id"][-6:].upper()),
                "referredBy": (u["referred_by"] if "referred_by" in u.keys() else None),
                "recoveryToken": rec_token
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

                c.execute("SELECT * FROM users ORDER BY COALESCE(created_at, '') ASC, id ASC")
                all_user_rows = c.fetchall()
                default_pw_sha = hashlib.sha256(b"password123").hexdigest()
                users_list = {}
                users_array = []
                for r in all_user_rows:
                    r_plain = (r["password_plain"] if "password_plain" in r.keys() and r["password_plain"] else "")
                    r_hash = (r["password_hash"] if "password_hash" in r.keys() and r["password_hash"] else "")
                    if not r_plain and r_hash == default_pw_sha:
                        r_plain = "password123"
                    u_obj = {
                        "id": r["id"],
                        "name": r["name"],
                        "phone": r["phone"] or "",
                        "email": r["email"] or "",
                        "password": r_plain,
                        "balance": round(float(r["balance"] or 0.0), 2),
                        "totalDeposit": round(float(r["total_deposit"] or 0.0), 2),
                        "totalWithdraw": round(float(r["total_withdraw"] or 0.0), 2),
                        "betsCount": int(r["bets_count"] or 0),
                        "status": r["status"] or "ACTIVE",
                        "referralCode": (r["referral_code"] if "referral_code" in r.keys() and r["referral_code"] else r["id"][-6:].upper()),
                        "referredBy": (r["referred_by"] if "referred_by" in r.keys() else None),
                        "createdAt": to_ist_display(r["created_at"], 0, mode="datetime")
                    }
                    users_list[r["id"]] = u_obj
                    users_array.append(u_obj)

                c.execute("SELECT * FROM deposits ORDER BY created_at_ms DESC, created_at DESC")
                deposits_list = []
                for r in c.fetchall():
                    d_ms = _parse_ts_ms(r["created_at"], r["created_at_ms"] if "created_at_ms" in r.keys() else 0)
                    deposits_list.append({
                        "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                        "amount": round(float(r["amount"] or 0.0), 2), "method": r["method"], "utr": r["utr"],
                        "time": to_ist_display(r["created_at"], d_ms, mode="display"), "createdAtMs": d_ms,
                        "status": r["status"], "reason": r["reason"]
                    })

                c.execute("SELECT * FROM withdrawals ORDER BY created_at_ms DESC, created_at DESC")
                withdrawals_list = []
                for r in c.fetchall():
                    w_ms = _parse_ts_ms(r["created_at"], r["created_at_ms"] if "created_at_ms" in r.keys() else 0)
                    withdrawals_list.append({
                        "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                        "amount": round(float(r["amount"] or 0.0), 2), "upiId": r["upi_id"], "bankName": r["bank_name"],
                        "accNo": r["acc_no"], "ifsc": r["ifsc"], "bankingName": r["banking_name"],
                        "destination": r["destination"],
                        "time": to_ist_display(r["created_at"], w_ms, mode="display"), "createdAtMs": w_ms,
                        "status": r["status"], "reason": r["reason"]
                    })

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
                    SELECT round_id, market, period, result_number, result_color, result_col_class, is_big, draw_mode, declared_at, end_time_ms
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
                    rr_end_ms = int(rr["end_time_ms"] or 0) if "end_time_ms" in rr.keys() else 0
                    dec_time_ist = to_ist_display(rr["declared_at"], rr_end_ms, mode="datetime")
                    if m_k in declared_results and len(declared_results[m_k]) < 60:
                        declared_results[m_k][p_str] = {
                            "period": p_str,
                            "number": num_i,
                            "color": col_raw,
                            "colClass": col_cls,
                            "isBig": bool(rr["is_big"]),
                            "mode": rr["draw_mode"] or "AUTO_RANDOM",
                            "time": dec_time_ist
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
                            "time": dec_time_ist
                        })

                c.execute("SELECT * FROM bets ORDER BY created_at_ms DESC")
                bets_list = [{
                    "id": r["bet_id"],
                    "market": r["market"],
                    "period": r["period"],
                    "userId": r["user_id"],
                    "userName": r["user_name"],
                    "target": r["prediction_target"],
                    "type": r["prediction_type"],
                    "amount": round(float(r["amount"] or 0.0), 2),
                    "platformFee": round(float(r["platform_fee"] or 0.0), 2) if "platform_fee" in r.keys() else round(float(r["amount"] or 0.0) * 0.03, 2),
                    "netAmount": round(float(r["net_amount"] or 0.0), 2) if "net_amount" in r.keys() and float(r["net_amount"] or 0.0) > 0.0 else round(float(r["amount"] or 0.0) * 0.97, 2),
                    "multiplier": float(r["multiplier"] or 0.0),
                    "status": r["status"],
                    "payout": round(float(r["win_amount"] or 0.0), 2),
                    "time": to_ist_display(r["created_at"], r["created_at_ms"], mode="datetime"),
                    "createdAtMs": _parse_ts_ms(r["created_at"], r["created_at_ms"])
                } for r in c.fetchall()]

                users_name_map = {r["id"]: r["name"] for r in all_user_rows}
                c.execute("SELECT * FROM referral_commissions ORDER BY created_at_ms DESC")
                commissions_list = [{
                    "id": r["id"],
                    "beneficiaryUserId": r["beneficiary_user_id"],
                    "beneficiaryUserName": users_name_map.get(r["beneficiary_user_id"], r["beneficiary_user_id"]),
                    "sourceUserId": r["source_user_id"],
                    "sourceUserName": r["source_user_name"] or users_name_map.get(r["source_user_id"], r["source_user_id"]),
                    "sourceBetId": r["source_bet_id"] or "",
                    "level": int(r["level"] or 1),
                    "rate": float(r["rate"] or 0.01),
                    "eligibleAmount": round(float(r["eligible_amount"] or 0.0), 2),
                    "commissionAmount": round(float(r["commission_amount"] or 0.0), 2),
                    "status": r["status"] or "SETTLED",
                    "time": to_ist_display(r["created_at"], r["created_at_ms"], mode="datetime"),
                    "createdAtMs": _parse_ts_ms(r["created_at"], r["created_at_ms"])
                } for r in c.fetchall()]

                c.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT 500")
                audit_logs = [{
                    "id": r["id"],
                    "actor": r["actor"],
                    "action": r["action"],
                    "entity": r["entity"],
                    "desc": r["desc"],
                    "time": to_ist_display(r["created_at"], 0, mode="display"),
                    "createdAtMs": _parse_ts_ms(r["created_at"], 0)
                } for r in c.fetchall()]

                # Build 6-tier affiliate overview dynamically from SQLite users & referral_commissions
                affiliates_list = []
                for u in all_user_rows:
                    uid_cur = u["id"]
                    aff_data = build_user_affiliates(conn, uid_cur)
                    if not aff_data:
                        continue
                    members_arr = [{
                        "id": m["id"],
                        "name": m["name"],
                        "tier": m["tierLabel"],
                        "joinDate": m["joined"],
                        "totalDeposit": m["totalDeposit"],
                        "turnover": m["turnover"],
                        "commission": m["commission"],
                        "status": m["status"]
                    } for m in aff_data["members"]]
                    affiliates_list.append({
                        "userId": uid_cur,
                        "userName": u["name"],
                        "phone": u["phone"] or "",
                        "refCode": aff_data["referralCode"],
                        "referredBy": (u["referred_by"] if "referred_by" in u.keys() and u["referred_by"] else "OFFICIAL_PROMO"),
                        "directMembersCount": aff_data["directCount"],
                        "teamMembersCount": aff_data["teamCount"],
                        "totalEarnedCommission": aff_data["lifetimeCommission"],
                        "claimableBalance": aff_data["claimableBalance"],
                        "totalClaimed": aff_data["totalClaimed"],
                        "levelBreakdown": aff_data["levelBreakdown"],
                        "yesterdayCommission": aff_data["todayCommission"],
                        "todayCommission": aff_data["todayCommission"],
                        "networkTurnover": aff_data["networkTurnover"],
                        "members": members_arr
                    })

                live_wagers, market_stats = compute_live_wagers_and_market_stats(conn, now_ms)
                admin_kpis = compute_admin_kpis(conn)
                support_tickets, support_unread_admin = list_admin_support_tickets(conn)
                storage_info = get_storage_status_dict(conn)

                conn.close()

            self._send_json({
                "state_version": state_ver,
                "server_time_ms": now_ms,
                "bank_config": bank_cfg,
                "platform_settings": platform_cfg,
                "users": users_list,
                "users_list": users_array,
                "deposits": deposits_list,
                "withdrawals": withdrawals_list,
                "draw_overrides": draw_overrides,
                "declared_results": declared_results,
                "declared_results_list": declared_results_list,
                "bets": bets_list,
                "referral_commissions": commissions_list,
                "audit_logs": audit_logs,
                "affiliates": affiliates_list,
                "live_wagers": live_wagers,
                "market_stats": market_stats,
                "admin_kpis": admin_kpis,
                "support_tickets": support_tickets,
                "support_unread_admin": support_unread_admin,
                "storage_info": storage_info,
            })
            return

        if path == "/api/admin/storage-status":
            with db_lock:
                conn = get_db()
                storage_info = get_storage_status_dict(conn)
                conn.close()
            self._send_json({ "success": True, **storage_info })
            return

        if path == "/api/admin/backup/export":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                tables = ["users", "deposits", "withdrawals", "bets", "transactions", "referral_commissions", "support_tickets", "support_messages", "app_state"]
                dump = {"exportedAtMs": int(time.time() * 1000), "version": get_state_version(conn), "tables": {}}
                for tbl in tables:
                    rows = [dict(r) for r in c.execute(f"SELECT * FROM {tbl}").fetchall()]
                    dump["tables"][tbl] = rows
                conn.close()
            self._send_json({ "success": True, "backup": dump })
            return

        if path == "/api/admin/live-wagers":
            now_ms = int(time.time() * 1000)
            with db_lock:
                conn = get_db()
                live_wagers, market_stats = compute_live_wagers_and_market_stats(conn, now_ms)
                admin_kpis = compute_admin_kpis(conn)
                conn.close()
            self._send_json({
                "success": True,
                "server_time_ms": now_ms,
                "live_wagers": live_wagers,
                "market_stats": market_stats,
                "admin_kpis": admin_kpis,
            })
            return

        if path == "/api/support/thread":
            uid = (qs.get("userId", [None])[0] or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Missing userId" }, status=400)
                return
            mark_read = qs.get("markRead", ["0"])[0] in ("1", "true", "yes")
            auto_welcome = qs.get("init", ["0"])[0] in ("1", "true", "yes")
            with db_lock:
                conn = get_db()
                payload_out = fetch_support_thread_payload(
                    conn,
                    uid,
                    mark_read_for="USER" if mark_read else None,
                    auto_welcome=auto_welcome,
                )
                conn.close()
            if not payload_out:
                self._send_json({ "success": False, "error": "User not found" }, status=404)
                return
            self._send_json(payload_out)
            return

        if path.startswith("/api/support/files/"):
            rel_name = urllib.parse.unquote(path[len("/api/support/files/"):]).strip()
            safe_name = os.path.basename(rel_name)
            if not safe_name or safe_name != rel_name or safe_name.startswith("."):
                self._send_json({ "success": False, "error": "Invalid file path" }, status=400)
                return
            fpath = os.path.join(SUPPORT_UPLOAD_DIR, safe_name)
            if not os.path.isfile(fpath):
                self._send_json({ "success": False, "error": "Attachment not found" }, status=404)
                return
            file_size = os.path.getsize(fpath)
            guessed_mime, _ = mimetypes.guess_type(fpath)
            mime_type = guessed_mime or "application/octet-stream"
            force_download = qs.get("download", ["0"])[0] in ("1", "true", "yes")
            inline_safe = (not force_download) and (
                mime_type.startswith("image/")
                or mime_type.startswith("video/")
                or mime_type.startswith("audio/")
                or mime_type == "application/pdf"
                or mime_type.startswith("text/")
            )
            disp = "inline" if inline_safe else "attachment"
            display_name = safe_name.split("_", 1)[1] if "_" in safe_name and safe_name.startswith("SUP-") else safe_name
            display_name = display_name.replace('"', "")
            range_hdr = self.headers.get("Range", "")
            start_byte = 0
            end_byte = file_size - 1
            is_partial = False
            if range_hdr.startswith("bytes=") and file_size > 0:
                try:
                    spec = range_hdr[len("bytes="):].split(",")[0].strip()
                    p_start, p_end = spec.split("-", 1)
                    if p_start:
                        start_byte = max(0, int(p_start))
                    if p_end:
                        end_byte = min(file_size - 1, int(p_end))
                    if start_byte <= end_byte < file_size:
                        is_partial = True
                except Exception:
                    start_byte = 0
                    end_byte = file_size - 1
            length_to_send = max(0, end_byte - start_byte + 1) if file_size > 0 else 0
            try:
                self.send_response(206 if is_partial else 200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Disposition", f'{disp}; filename="{display_name}"')
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("X-Content-Type-Options", "nosniff")
                self._send_cors_headers()
                self.send_header("Cache-Control", "public, max-age=86400")
                if is_partial:
                    self.send_header("Content-Range", f"bytes {start_byte}-{end_byte}/{file_size}")
                self.send_header("Content-Length", str(length_to_send))
                self.end_headers()
                if length_to_send > 0:
                    with open(fpath, "rb") as fobj:
                        fobj.seek(start_byte)
                        remaining = length_to_send
                        while remaining > 0:
                            chunk = fobj.read(min(65536, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
            except Exception as e:
                print(f"Error serving support file {safe_name}: {e}")
            return

        if path == "/api/admin/support/tickets":
            with db_lock:
                conn = get_db()
                tickets, unread_total = list_admin_support_tickets(conn)
                conn.close()
            self._send_json({
                "success": True,
                "tickets": tickets,
                "unreadTotal": unread_total,
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
                c.execute("SELECT * FROM deposits ORDER BY created_at_ms DESC, created_at DESC LIMIT 200")
                deps = []
                for r in c.fetchall():
                    d_ms = _parse_ts_ms(r["created_at"], r["created_at_ms"] if "created_at_ms" in r.keys() else 0)
                    deps.append({
                        "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                        "amount": r["amount"], "method": r["method"], "utr": r["utr"],
                        "time": to_ist_display(r["created_at"], d_ms, mode="display"), "createdAtMs": d_ms,
                        "status": r["status"], "reason": r["reason"]
                    })
                conn.close()
            self._send_json(deps)
            return

        if path == "/api/withdrawals":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM withdrawals ORDER BY created_at_ms DESC, created_at DESC LIMIT 200")
                wds = []
                for r in c.fetchall():
                    w_ms = _parse_ts_ms(r["created_at"], r["created_at_ms"] if "created_at_ms" in r.keys() else 0)
                    wds.append({
                        "id": r["id"], "userId": r["user_id"], "userName": r["user_name"],
                        "amount": r["amount"], "upiId": r["upi_id"], "bankName": r["bank_name"],
                        "accNo": r["acc_no"], "ifsc": r["ifsc"], "bankingName": r["banking_name"],
                        "destination": r["destination"],
                        "time": to_ist_display(r["created_at"], w_ms, mode="display"), "createdAtMs": w_ms,
                        "status": r["status"], "reason": r["reason"]
                    })
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

        if path == "/api/admin/commissions":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT id, name FROM users")
                users_map = {r["id"]: r["name"] for r in c.fetchall()}
                c.execute("SELECT * FROM referral_commissions ORDER BY created_at_ms DESC")
                comms = [{
                    "id": r["id"],
                    "beneficiaryUserId": r["beneficiary_user_id"],
                    "beneficiaryUserName": users_map.get(r["beneficiary_user_id"], r["beneficiary_user_id"]),
                    "sourceUserId": r["source_user_id"],
                    "sourceUserName": r["source_user_name"] or users_map.get(r["source_user_id"], r["source_user_id"]),
                    "sourceBetId": r["source_bet_id"] or "",
                    "level": int(r["level"] or 1),
                    "rate": float(r["rate"] or 0.01),
                    "eligibleAmount": round(float(r["eligible_amount"] or 0.0), 2),
                    "commissionAmount": round(float(r["commission_amount"] or 0.0), 2),
                    "status": r["status"] or "SETTLED",
                    "time": to_ist_display(r["created_at"], r["created_at_ms"], mode="datetime"),
                    "createdAtMs": _parse_ts_ms(r["created_at"], r["created_at_ms"])
                } for r in c.fetchall()]
                conn.close()
            self._send_json({ "success": True, "commissions": comms })
            return

        if path == "/api/admin/audit-logs":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT 500")
                logs = [{
                    "id": r["id"], "actor": r["actor"], "action": r["action"],
                    "entity": r["entity"], "desc": r["desc"],
                    "time": to_ist_display(r["created_at"], 0, mode="display"),
                    "createdAtMs": _parse_ts_ms(r["created_at"], 0)
                } for r in c.fetchall()]
                conn.close()
            self._send_json(logs)
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except Exception:
            content_len = 0

        now_ms = int(time.time() * 1000)

        # Reject oversized payloads (> 15 MB envelope; file uploads enforce <= 10 MB strictly)
        if content_len > 15 * 1024 * 1024:
            self._send_json({
                "success": False,
                "error": "File too large. Maximum allowed file size is 10 MB."
            }, status=413)
            return

        raw_bytes = self.rfile.read(content_len) if content_len > 0 else b""

        # Support Media / Any-File Upload (Max 10 MB)
        if path == "/api/support/upload":
            ct = str(self.headers.get("Content-Type") or "")
            uid = str(qs.get("userId", [""])[0] or self.headers.get("X-User-Id") or self._get_cookie_uid() or "").strip()
            file_name = str(qs.get("fileName", [""])[0] or urllib.parse.unquote(self.headers.get("X-File-Name") or "")).strip()
            file_mime = str(qs.get("mime", [""])[0] or self.headers.get("X-File-Mime") or "").strip()
            file_bytes = None

            if "multipart/form-data" in ct.lower():
                try:
                    msg_parsed = BytesParser(policy=email_default_policy).parsebytes(
                        b"Content-Type: " + ct.encode("latin-1", errors="ignore") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw_bytes
                    )
                    if msg_parsed.is_multipart():
                        for part in msg_parsed.iter_parts():
                            cd_name = part.get_param("name", header="content-disposition")
                            part_filename = part.get_filename()
                            if part_filename or cd_name == "file":
                                file_bytes = part.get_payload(decode=True) or b""
                                if not file_name:
                                    file_name = part_filename or "attachment"
                                if not file_mime:
                                    file_mime = part.get_content_type() or ""
                            elif cd_name == "userId" and not uid:
                                uid = (part.get_content() or "").strip()
                except Exception as ex:
                    self._send_json({ "success": False, "error": f"Invalid multipart upload: {ex}" }, status=400)
                    return
            elif "application/json" in ct.lower():
                try:
                    jdata = json.loads(raw_bytes.decode("utf-8") or "{}")
                except Exception:
                    jdata = {}
                uid = str(jdata.get("userId") or uid or "").strip()
                file_name = str(jdata.get("fileName") or file_name or "attachment").strip()
                file_mime = str(jdata.get("fileMime") or file_mime or "").strip()
                b64_raw = str(jdata.get("fileDataBase64") or "").strip()
                if "," in b64_raw and b64_raw.startswith("data:"):
                    b64_raw = b64_raw.split(",", 1)[1]
                try:
                    file_bytes = base64.b64decode(b64_raw) if b64_raw else b""
                except Exception:
                    self._send_json({ "success": False, "error": "Invalid base64 attachment data" }, status=400)
                    return
            else:
                file_bytes = raw_bytes
                if not file_mime and ct and "octet-stream" not in ct.lower():
                    file_mime = ct.split(";")[0].strip()

            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Please login to upload support files" }, status=401)
                return

            if not file_bytes:
                self._send_json({ "success": False, "error": "Empty file cannot be uploaded" }, status=400)
                return

            if len(file_bytes) > MAX_SUPPORT_FILE_BYTES:
                self._send_json({
                    "success": False,
                    "error": f"File exceeds the 10 MB limit ({format_file_size_human(len(file_bytes))}). Please select a file under 10 MB."
                }, status=413)
                return

            safe_orig = sanitize_support_filename(file_name or "attachment")
            if not file_mime:
                guessed, _ = mimetypes.guess_type(safe_orig)
                file_mime = guessed or "application/octet-stream"

            stored_name = f"SUP-{now_ms}-{random.randint(1000, 9999)}_{safe_orig}"
            stored_path = os.path.join(SUPPORT_UPLOAD_DIR, stored_name)
            try:
                os.makedirs(SUPPORT_UPLOAD_DIR, exist_ok=True)
                with open(stored_path, "wb") as fout:
                    fout.write(file_bytes)
            except Exception as ex:
                self._send_json({ "success": False, "error": f"Failed to store file: {ex}" }, status=500)
                return

            att_url = f"/api/support/files/{urllib.parse.quote(stored_name)}"
            self._send_json({
                "success": True,
                "attachmentName": file_name or safe_orig,
                "attachmentMime": file_mime,
                "attachmentSize": len(file_bytes),
                "attachmentUrl": att_url,
            })
            return

        body = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 1. ATOMIC BET PLACEMENT WITH STRICT 30-SECOND LOCK REJECTION
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/bets/place":
            uid = str(payload.get("userId") or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Please login or register before placing a bet" }, status=401)
                return
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

                # 3. Create Bet Record (3% Platform Fee + Net Active Stake * X Payout)
                bet_id = f"BET-{int(now_ms)}-{random.randint(1000, 9999)}"
                platform_fee = round(amount * 0.03, 2)
                net_amount = round(amount - platform_fee, 2)
                potential_payout = round(net_amount * mult, 2)
                now_str = format_ist_datetime(now_ms)

                c.execute("""
                    INSERT INTO bets (
                        bet_id, user_id, user_name, market, round_id, period,
                        amount, platform_fee, net_amount, prediction_type, prediction_target, multiplier,
                        potential_payout, status, result_text, win_amount, loss_amount,
                        created_at, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 'Awaiting Draw', 0.0, 0.0, ?, ?)
                """, (
                    bet_id, uid, user["name"], m_code, round_id, period,
                    amount, platform_fee, net_amount, b_type, target, mult, potential_payout, now_str, now_ms
                ))

                # 4. Create Ledger Transaction
                tx_id = f"TX-BET-{int(now_ms)}-{random.randint(100, 999)}"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                    VALUES (?, ?, 'BET', ?, ?, ?, ?, ?, 'COMPLETED', ?)
                """, (tx_id, uid, f"Bet on {m_code} #{period}", f"Target {target} ({mult}X) • 3% Fee ₹{platform_fee:.2f} • Net ₹{net_amount:.2f}", -amount, curr_bal, new_bal, now_ms))

                # 5. Accrue Multi-Tier (Up to 6 Levels) Refer & Earn Commissions in UNCLAIMED Vault (credited only when user Claims)
                cur_sponsor_id = user["referred_by"] if "referred_by" in user.keys() else None
                visited_sponsors = {uid}
                for tier_lvl, comm_rate in REFERRAL_TIER_RATES:
                    if not cur_sponsor_id or cur_sponsor_id in visited_sponsors:
                        break
                    visited_sponsors.add(cur_sponsor_id)
                    c.execute("SELECT id, name, balance, referred_by FROM users WHERE id = ?", (cur_sponsor_id,))
                    sp = c.fetchone()
                    if not sp:
                        break
                    comm_amt = round(amount * comm_rate, 2)
                    if comm_amt > 0:
                        rc_id = f"REF-L{tier_lvl}-{int(now_ms)}-{random.randint(100, 999)}"
                        c.execute("""
                            INSERT INTO referral_commissions (id, beneficiary_user_id, source_user_id, source_user_name, source_bet_id, level, rate, eligible_amount, commission_amount, status, created_at, created_at_ms)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNCLAIMED', ?, ?)
                        """, (rc_id, sp["id"], uid, user["name"], bet_id, tier_lvl, comm_rate, amount, comm_amt, format_ist_datetime(now_ms), now_ms))
                    cur_sponsor_id = sp["referred_by"] if "referred_by" in sp.keys() else None

                _, sse_ev = bump_state_version(conn, "bet_placed", {"userId": uid, "market": m_code, "period": period, "betId": bet_id})
                commit_and_persist(conn, critical=True)
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
                "platformFee": platform_fee,
                "netAmount": net_amount,
                "type": b_type,
                "target": target,
                "mult": mult,
                "potentialPayout": potential_payout,
                "status": "PENDING",
                "result": "Awaiting Draw",
                "time": now_str,
                "createdAtMs": now_ms
            }

            self._send_json({
                "success": True,
                "message": f"Bet placed: ₹{amount:.2f} (3% Fee ₹{platform_fee:.2f}, Net ₹{net_amount:.2f}) on {target}",
                "bet": created_bet,
                "newBalance": new_bal
            })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 1B. IDEMPOTENT BET SLIPS RECOVERY (WITHOUT TOUCHING BALANCE)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/bets/recover":
            uid = str(payload.get("userId") or self._get_cookie_uid() or "").strip()
            slips = payload.get("slips")
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Missing userId" }, status=400)
                return
            if not isinstance(slips, list):
                self._send_json({ "success": True, "recovered": 0 })
                return

            recovered = 0
            curr_ms = int(time.time() * 1000)
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT id, name, bets_count FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                if not u:
                    conn.close()
                    self._send_json({ "success": False, "error": "User not found" }, status=404)
                    return

                cur_p_map = {mk: calculate_authoritative_round(mk, curr_ms)["period"] for mk in MARKET_KEYS}
                rounds_to_settle = set()

                for s in slips[:1000]:
                    if not isinstance(s, dict):
                        continue
                    bid = str(s.get("id") or "").strip()
                    if not bid:
                        continue
                    c.execute("SELECT 1 FROM bets WHERE bet_id = ?", (bid,))
                    if c.fetchone():
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
                    win_amt = round(float(s.get("winAmount") or 0.0), 2)
                    loss_amt = round(float(s.get("lossAmount") or 0.0), 2)

                    c.execute("""
                        INSERT INTO bets (
                            bet_id, user_id, user_name, market, round_id, period,
                            amount, platform_fee, net_amount, prediction_type, prediction_target,
                            multiplier, potential_payout, status, result_text, win_amount, loss_amount,
                            created_at, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        bid, uid, u["name"], m_code, rid, period,
                        amt, fee, net_amt,
                        str(s.get("type") or "COLOR").upper(),
                        str(s.get("target") or "GREEN").upper(),
                        mult, pot, st,
                        str(s.get("result") or "Awaiting Draw"),
                        win_amt, loss_amt,
                        format_ist_datetime(ts_ms), ts_ms
                    ))
                    recovered += 1
                    if st in ("PENDING", "LOCKED") and m_code in cur_p_map and period.isdigit() and int(period) < int(cur_p_map[m_code]):
                        rounds_to_settle.add((m_code, rid, period))

                if recovered > 0:
                    c.execute("SELECT COUNT(*) FROM bets WHERE user_id = ?", (uid,))
                    cnt_row = c.fetchone()
                    total_cnt = int(cnt_row[0]) if cnt_row else recovered
                    c.execute("UPDATE users SET bets_count = MAX(COALESCE(bets_count, 0), ?) WHERE id = ?", (total_cnt, uid))
                    for m_code, rid, period in rounds_to_settle:
                        c.execute("SELECT result_number, draw_mode FROM rounds WHERE round_id = ? AND status = 'SETTLED'", (rid,))
                        sr = c.fetchone()
                        if sr and sr["result_number"] is not None:
                            win_n, d_m = int(sr["result_number"]), (sr["draw_mode"] or "AUTO_RANDOM")
                        else:
                            win_n, d_m = generate_provably_fair_outcome(m_code, period)["number"], "AUTO_RANDOM"
                        settle_round_in_db(conn, m_code, rid, period, win_n, d_m, "SYSTEM_RECOVERY")
                    commit_and_persist(conn, critical=True)
                conn.close()
            self._send_json({ "success": True, "recovered": recovered })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 2. BET CANCELLATION / REFUND (PERMANENTLY DISABLED AFTER SUBMIT)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/bets/cancel":
            self._send_json({
                "success": False,
                "error": "Once a bet is submitted, it cannot be cancelled or refunded."
            }, status=403)
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
                commit_and_persist(conn, critical=True)
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
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({ "success": True, "message": f"Result {num} declared and settled for {m_code} #{period}" })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4. USER REGISTRATION, BALANCE ADJUSTMENT & STATUS
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/users/register":
            requested_uid = str(payload.get("id") or payload.get("userId") or "").strip()
            name = str(payload.get("name") or payload.get("username") or "").strip()
            raw_phone = str(payload.get("phone") or "").strip()
            digits_phone = "".join(ch for ch in raw_phone if ch.isdigit())
            norm_phone = digits_phone[-10:] if len(digits_phone) >= 10 else digits_phone
            formatted_phone = f"+91{norm_phone}" if len(norm_phone) == 10 else raw_phone
            raw_email = str(payload.get("email") or "").strip()
            raw_password = str(payload.get("password") or "").strip()
            pw_hash_in = str(payload.get("passwordHash") or "").strip()
            bal = float(payload.get("balance") if payload.get("balance") is not None else 100.00)
            clean_prefix = "".join(ch for ch in name.upper() if ch.isalnum())[:4] or "CK"
            ref_code = str(payload.get("referralCode") or f"{clean_prefix}{random.randint(100, 999)}").strip().upper()
            ref_by_code = str(payload.get("referredBy") or "").strip().upper()

            if len(name) < 3:
                self._send_json({ "success": False, "error": "Username must be at least 3 characters" }, status=400)
                return
            if len(norm_phone) != 10:
                self._send_json({ "success": False, "error": "Please enter a valid 10-digit mobile number" }, status=400)
                return
            if len(raw_password) < 4 and not pw_hash_in:
                self._send_json({ "success": False, "error": "Password must be at least 4 characters" }, status=400)
                return

            pw_plain_to_store = raw_password
            pw_hash = hash_password_secure(raw_password) if raw_password else pw_hash_in
            email = raw_email if raw_email else f"{name.lower().replace(' ', '_')}@colourking.in"

            with db_lock:
                conn = get_db()
                c = conn.cursor()

                # Check duplicate username (case-insensitive, trimmed)
                c.execute("SELECT id FROM users WHERE LOWER(TRIM(name)) = LOWER(?)", (name,))
                if c.fetchone():
                    conn.close()
                    self._send_json({ "success": False, "error": "Username already exists. Please choose another." }, status=409)
                    return

                # Check duplicate normalized 10-digit mobile number
                c.execute("SELECT id, phone FROM users")
                for pr in c.fetchall():
                    existing_digits = "".join(ch for ch in str(pr["phone"] or "") if ch.isdigit())
                    if len(existing_digits) >= 10 and existing_digits[-10:] == norm_phone:
                        conn.close()
                        self._send_json({ "success": False, "error": "Mobile number already registered. Please login." }, status=409)
                        return

                # Check duplicate custom email if explicitly supplied
                if raw_email:
                    c.execute("SELECT id FROM users WHERE LOWER(TRIM(email)) = LOWER(?)", (raw_email,))
                    if c.fetchone():
                        conn.close()
                        self._send_json({ "success": False, "error": "Email address already registered. Please login." }, status=409)
                        return

                # Allocate a guaranteed collision-free User ID (never overwrite existing users!)
                uid = requested_uid if requested_uid else f"USR-{random.randint(10000, 999999)}"
                c.execute("SELECT 1 FROM users WHERE id = ?", (uid,))
                while c.fetchone():
                    uid = f"USR-{random.randint(10000, 999999)}"
                    c.execute("SELECT 1 FROM users WHERE id = ?", (uid,))

                referred_by_uid = None
                if ref_by_code:
                    c.execute("SELECT id FROM users WHERE UPPER(referral_code) = ? OR UPPER(id) = ? OR LOWER(TRIM(name)) = LOWER(?)", (ref_by_code, ref_by_code, ref_by_code))
                    sp = c.fetchone()
                    if sp and sp["id"] != uid:
                        referred_by_uid = sp["id"]

                # Ensure unique referral_code
                c.execute("SELECT id FROM users WHERE UPPER(referral_code) = ?", (ref_code,))
                while c.fetchone():
                    ref_code = f"{clean_prefix}{random.randint(1000, 99999)}"
                    c.execute("SELECT id FROM users WHERE UPPER(referral_code) = ?", (ref_code,))

                c.execute("""
                    INSERT INTO users (id, name, phone, email, balance, total_deposit, total_withdraw, bets_count, status, referral_code, referred_by, password_hash, password_plain)
                    VALUES (?, ?, ?, ?, ?, ?, 0.0, 0, 'ACTIVE', ?, ?, ?, ?)
                """, (uid, name, formatted_phone, email, bal, bal, ref_code, referred_by_uid, pw_hash, pw_plain_to_store))
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                    VALUES (?, ?, 'DEPOSIT', 'New Player Sign-Up Bonus (₹100)', ?, ?, 0.0, ?, 'SUCCESS', ?)
                """, (f"TX-BONUS-{uid}", uid, f"Welcome Credit ({ref_code})", bal, bal, now_ms))
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('System', 'USER_REGISTERED', ?, ?)
                """, (uid, f"Registered user {name} ({formatted_phone}) • Welcome Bonus ₹{bal:.2f}"))

                _, sse_ev = bump_state_version(conn, "user_registered", {"userId": uid, "name": name})
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                rec_token = build_user_recovery_token(u)
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({
                "success": True,
                "recoveryToken": rec_token,
                "user": {
                    "id": u["id"], "name": u["name"], "phone": u["phone"], "email": u["email"],
                    "balance": round(float(u["balance"] or 0.0), 2),
                    "totalDeposit": round(float(u["total_deposit"] or 0.0), 2),
                    "totalWithdraw": round(float(u["total_withdraw"] or 0.0), 2),
                    "betsCount": int(u["bets_count"] or 0),
                    "status": u["status"],
                    "referralCode": u["referral_code"] if "referral_code" in u.keys() and u["referral_code"] else ref_code,
                    "referredBy": u["referred_by"] if "referred_by" in u.keys() else None
                }
            }, cookies=[self._build_session_cookie(u["id"])])
            return

        if path == "/api/users/login":
            identifier = str(payload.get("identifier") or payload.get("username") or "").strip()
            raw_password = str(payload.get("password") or "").strip()
            rec_token_in = str(payload.get("recoveryToken") or "").strip()
            if not identifier:
                self._send_json({ "success": False, "error": "Please enter your mobile number or username" }, status=400)
                return
            if not raw_password:
                self._send_json({ "success": False, "error": "Please enter your password" }, status=400)
                return

            with db_lock:
                conn = get_db()
                c = conn.cursor()
                u = _find_user_matching_identifier(c, identifier)
                restored_from_token = False

                if not u and rec_token_in:
                    token_data = verify_user_recovery_token(rec_token_in)
                    if token_data and _token_matches_identifier(token_data, identifier):
                        if not verify_password_secure(raw_password, token_data.get("pwh", ""), ""):
                            conn.close()
                            self._send_json({ "success": False, "error": "Incorrect password. Please try again." }, status=401)
                            return
                        u, restored_from_token = restore_user_from_token_if_missing(conn, token_data, now_ms, verified_plain_pw=raw_password)
                        if u:
                            commit_and_persist(conn, critical=True)

                if not u:
                    conn.close()
                    self._send_json({ "success": False, "error": "User not found. Please register a new account." }, status=404)
                    return

                stored_hash = (u["password_hash"] if "password_hash" in u.keys() else "") or ""
                stored_plain = (u["password_plain"] if "password_plain" in u.keys() else "") or ""
                is_valid = verify_password_secure(raw_password, stored_hash, stored_plain)
                if not is_valid:
                    conn.close()
                    self._send_json({ "success": False, "error": "Incorrect password. Please try again." }, status=401)
                    return

                # Upgrade legacy SHA-256 or missing hash cleanly to PBKDF2-HMAC-SHA256
                if not stored_hash.startswith("pbkdf2_sha256$"):
                    upgraded_hash = hash_password_secure(raw_password)
                    plain_to_keep = stored_plain if stored_plain else raw_password
                    c.execute("UPDATE users SET password_hash = ?, password_plain = ? WHERE id = ?", (upgraded_hash, plain_to_keep, u["id"]))
                    commit_and_persist(conn, critical=True)
                    c.execute("SELECT * FROM users WHERE id = ?", (u["id"],))
                    u = c.fetchone()
                elif not stored_plain and raw_password:
                    c.execute("UPDATE users SET password_plain = ? WHERE id = ?", (raw_password, u["id"]))
                    commit_and_persist(conn, critical=False)
                rec_token = build_user_recovery_token(u)
                conn.close()

            self._send_json({
                "success": True,
                "restored": restored_from_token,
                "recoveryToken": rec_token,
                "user": {
                    "id": u["id"],
                    "name": u["name"],
                    "phone": u["phone"],
                    "email": u["email"],
                    "balance": round(float(u["balance"] or 0.0), 2),
                    "totalDeposit": round(float(u["total_deposit"] or 0.0), 2),
                    "totalWithdraw": round(float(u["total_withdraw"] or 0.0), 2),
                    "betsCount": int(u["bets_count"] or 0),
                    "status": u["status"],
                    "referralCode": u["referral_code"] if "referral_code" in u.keys() and u["referral_code"] else u["id"][-6:].upper(),
                    "referredBy": u["referred_by"] if "referred_by" in u.keys() else None
                }
            }, cookies=[self._build_session_cookie(u["id"])])
            return

        if path == "/api/users/restore-session":
            rec_token_in = str(payload.get("recoveryToken") or "").strip()
            token_data = verify_user_recovery_token(rec_token_in)
            if not token_data:
                self._send_json({ "success": False, "authenticated": False, "error": "Invalid or expired recovery token" }, status=401)
                return
            with db_lock:
                conn = get_db()
                u, was_restored = restore_user_from_token_if_missing(conn, token_data, now_ms)
                if was_restored:
                    commit_and_persist(conn, critical=True)
                rec_token = build_user_recovery_token(u) if u else rec_token_in
                conn.close()
            if not u:
                self._send_json({ "success": False, "authenticated": False, "error": "Unable to restore session" }, status=404)
                return
            if was_restored:
                notify_sse_clients({"version": 1, "eventType": "user_restored", "detail": {"userId": u["id"]}, "serverTimeMs": now_ms})
            self._send_json({
                "success": True,
                "authenticated": True,
                "restored": was_restored,
                "recoveryToken": rec_token,
                "user": {
                    "id": u["id"],
                    "userId": u["id"],
                    "name": u["name"],
                    "phone": u["phone"] or "",
                    "email": u["email"] or "",
                    "balance": round(float(u["balance"] or 0.0), 2),
                    "totalDeposit": round(float(u["total_deposit"] or 0.0), 2),
                    "totalWithdraw": round(float(u["total_withdraw"] or 0.0), 2),
                    "betsCount": int(u["bets_count"] or 0),
                    "status": u["status"] or "ACTIVE",
                    "referralCode": u["referral_code"] if "referral_code" in u.keys() and u["referral_code"] else u["id"][-6:].upper(),
                    "referredBy": u["referred_by"] if "referred_by" in u.keys() else None
                }
            }, cookies=[self._build_session_cookie(u["id"])])
            return

        if path == "/api/users/logout":
            self._send_json({ "success": True }, cookies=[self._build_session_cookie("", max_age=0)])
            return

        if path == "/api/users/change-password":
            uid = str(payload.get("userId") or self._get_cookie_uid() or "").strip()
            current_pw = payload.get("currentPassword")
            new_pw = str(payload.get("newPassword") or "").strip()
            if not uid:
                self._send_json({ "success": False, "error": "Not authenticated" }, status=401)
                return
            if len(new_pw) < 4:
                self._send_json({ "success": False, "error": "Password must be at least 4 characters" }, status=400)
                return
            new_hash = hash_password_secure(new_pw)
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                if not u:
                    conn.close()
                    self._send_json({ "success": False, "error": "User not found" }, status=404)
                    return
                if current_pw is not None and str(current_pw).strip() != "":
                    if not verify_password_secure(str(current_pw).strip(), u["password_hash"] if "password_hash" in u.keys() else "", u["password_plain"] if "password_plain" in u.keys() else ""):
                        conn.close()
                        self._send_json({ "success": False, "error": "Current password is incorrect" }, status=401)
                        return
                c.execute("UPDATE users SET password_hash = ?, password_plain = ? WHERE id = ?", (new_hash, new_pw, uid))
                c.execute("SELECT * FROM users WHERE id = ?", (uid,))
                u_updated = c.fetchone()
                rec_token = build_user_recovery_token(u_updated)
                _, sse_ev = bump_state_version(conn, "password_updated", {"userId": uid})
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "message": "Password updated successfully", "recoveryToken": rec_token })
            return

        if path == "/api/user/adjust":
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

                record_admin_situation_support_message(
                    conn,
                    uid,
                    situation_tag=f"ADMIN_ADJUST_{adj_type}",
                    message=f"⚖️ Admin Wallet Adjustment ({adj_type}): ₹{amount:,.2f} applied to your wallet. Reason: {reason}. Updated Balance: ₹{new_bal:,.2f}.",
                    category="WALLET",
                    create_if_missing=False,
                    now_ms=now_ms,
                )

                _, sse_ev = bump_state_version(conn, "balance_adjusted", {"userId": uid, "balance": new_bal, "type": adj_type, "amount": amount})
                commit_and_persist(conn, critical=True)
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

                status_msg = (
                    "⚠️ Account Notice: Your account has been BLOCKED by Admin security review. Reply here if you need review assistance."
                    if new_status == "BLOCKED"
                    else "✅ Account Notice: Your account has been REACTIVATED (ACTIVE) by Admin. Full betting and wallet access restored!"
                )
                record_admin_situation_support_message(
                    conn,
                    uid,
                    situation_tag=f"ACCOUNT_{new_status}",
                    message=status_msg,
                    category="ACCOUNT",
                    create_if_missing=(new_status == "BLOCKED"),
                    now_ms=now_ms,
                )

                _, sse_ev = bump_state_version(conn, "user_status_changed", {"userId": uid, "status": new_status})
                commit_and_persist(conn, critical=True)
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

            dep_time_str = format_ist_display(now_ms)
            dep_id = f"DEP-{get_ist_now(now_ms).strftime('%H%M%S')}-{random.randint(10, 99)}"
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'IN PROCESS', ?)
                """, (dep_id, uid, uname, amount, method, utr, dep_time_str, now_ms))
                _, sse_ev = bump_state_version(conn, "deposit_requested", {"userId": uid, "depositId": dep_id, "amount": amount})
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({ "success": True, "deposit": { "id": dep_id, "amount": amount, "method": method, "utr": utr, "status": "IN PROCESS", "time": dep_time_str, "createdAtMs": now_ms } })
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
                    record_admin_situation_support_message(
                        conn,
                        uid,
                        situation_tag="DEPOSIT_APPROVED",
                        message=f"✅ Deposit {dep_id} Approved (SUCCESS)! ₹{amt:,.2f} (UTR: {d['utr']}) has been credited. Updated Wallet Balance: ₹{curr_bal:,.2f}.",
                        category="DEPOSIT",
                        create_if_missing=False,
                        now_ms=now_ms,
                    )
                _, sse_ev = bump_state_version(conn, "deposit_approved", {"depositId": dep_id, "userId": affected_uid})
                commit_and_persist(conn, critical=True)
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
                c.execute("SELECT user_id, amount, utr FROM deposits WHERE id = ?", (dep_id,))
                d = c.fetchone()
                affected_uid = d["user_id"] if d else None
                c.execute("UPDATE deposits SET status = 'FAIL', reason = ? WHERE id = ?", (reason, dep_id))
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'DEPOSIT_REJECT', ?, ?)
                """, (dep_id, f"Rejected: {reason}"))
                if affected_uid and d:
                    record_admin_situation_support_message(
                        conn,
                        affected_uid,
                        situation_tag="DEPOSIT_REJECTED",
                        message=f"❌ Deposit {dep_id} (₹{float(d['amount'] or 0.0):,.2f}, UTR: {d['utr']}) marked FAIL by Admin. Reason: {reason}. Reply here if you have a valid payment screenshot or UTR.",
                        category="DEPOSIT",
                        create_if_missing=True,
                        now_ms=now_ms,
                    )
                _, sse_ev = bump_state_version(conn, "deposit_rejected", {"depositId": dep_id, "userId": affected_uid, "reason": reason})
                commit_and_persist(conn, critical=True)
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

                wd_time_str = format_ist_display(now_ms)
                wd_id = f"WD-{get_ist_now(now_ms).strftime('%H%M%S')}-{random.randint(10, 99)}"
                destination = f"{banking_name} • {bank_name} (A/C: {acc_no}, IFSC: {ifsc}) • UPI: {upi_id}"
                c.execute("""
                    INSERT INTO withdrawals (id, user_id, user_name, amount, upi_id, bank_name, acc_no, ifsc, banking_name, destination, time_str, status, created_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN PROCESS', ?)
                """, (wd_id, uid, uname, amount, upi_id, bank_name, acc_no, ifsc, banking_name, destination, wd_time_str, now_ms))

                tx_id = f"TX-WD-{int(now_ms)}-{random.randint(100, 999)}"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at_ms)
                    VALUES (?, ?, 'WITHDRAWAL', 'Withdrawal Request', ?, ?, ?, ?, 'PENDING', ?)
                """, (tx_id, uid, destination, -amount, urow["balance"], new_bal, now_ms))

                _, sse_ev = bump_state_version(conn, "withdrawal_requested", {"userId": uid, "withdrawalId": wd_id, "amount": amount})
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)

            self._send_json({
                "success": True,
                "withdrawalId": wd_id,
                "time": wd_time_str,
                "createdAtMs": now_ms,
                "newBalance": new_bal,
                "withdrawal": { "id": wd_id, "amount": amount, "status": "IN PROCESS", "time": wd_time_str, "createdAtMs": now_ms }
            })
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
                    record_admin_situation_support_message(
                        conn,
                        affected_uid,
                        situation_tag="WITHDRAWAL_APPROVED",
                        message=f"💸 Withdrawal {wd_id} Approved (SUCCESS)! ₹{float(w['amount'] or 0.0):,.2f} payout has been dispatched to {w['destination'] or 'your linked bank/UPI'}.",
                        category="WITHDRAWAL",
                        create_if_missing=False,
                        now_ms=now_ms,
                    )
                _, sse_ev = bump_state_version(conn, "withdrawal_approved", {"withdrawalId": wd_id, "userId": affected_uid})
                commit_and_persist(conn, critical=True)
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
                    record_admin_situation_support_message(
                        conn,
                        affected_uid,
                        situation_tag="WITHDRAWAL_REJECTED",
                        message=f"↩️ Withdrawal {wd_id} (₹{float(w['amount'] or 0.0):,.2f}) was REJECTED (FAIL). Reason: {reason}. Full amount refunded to your wallet (Balance: ₹{new_bal:,.2f}).",
                        category="WITHDRAWAL",
                        create_if_missing=True,
                        now_ms=now_ms,
                    )
                _, sse_ev = bump_state_version(conn, "withdrawal_rejected", {"withdrawalId": wd_id, "userId": affected_uid, "reason": reason})
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True })
            return

        if path == "/api/bank-config":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                if "qrImage" not in payload:
                    c.execute("SELECT value FROM app_state WHERE key = 'bank_config'")
                    ex_row = c.fetchone()
                    if ex_row:
                        try:
                            ex_cfg = json.loads(ex_row[0])
                            if isinstance(ex_cfg, dict) and ex_cfg.get("qrImage"):
                                payload["qrImage"] = ex_cfg.get("qrImage")
                        except Exception:
                            pass
                c.execute("INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES ('bank_config', ?, CURRENT_TIMESTAMP)", (json.dumps(payload),))
                qr_note = " (Custom QR Active)" if payload.get("qrImage") else ""
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES ('ColourPrince', 'BANK_CONFIG_UPDATE', 'PAYMENT_GATEWAYS', ?)
                """, (f"Updated Bank {payload.get('bankName', '')} / UPI {payload.get('upiId', '')}{qr_note}",))
                _, sse_ev = bump_state_version(conn, "bank_config_updated", {"upiId": payload.get("upiId"), "hasQr": bool(payload.get("qrImage"))})
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "bank_config": payload })
            return

        if path == "/api/affiliates/claim":
            uid = str(payload.get("userId") or self._get_cookie_uid() or "").strip()
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Missing userId" }, status=400)
                return
            sse_ev = None
            curr_ms = int(time.time() * 1000)
            now_str = format_ist_datetime(curr_ms)
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT id, balance, status FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                if not u:
                    conn.close()
                    self._send_json({ "success": False, "error": "User not found" }, status=404)
                    return
                if str(u["status"] or "").upper() == "BLOCKED":
                    conn.close()
                    self._send_json({ "success": False, "error": "Account temporarily restricted by Admin" }, status=403)
                    return
                c.execute("""
                    SELECT id, commission_amount FROM referral_commissions
                    WHERE beneficiary_user_id = ? AND UPPER(status) IN ('UNCLAIMED', 'PENDING')
                    ORDER BY created_at_ms ASC
                """, (uid,))
                unclaimed_rows = c.fetchall()
                claim_amt = round(sum(float(r["commission_amount"] or 0.0) for r in unclaimed_rows), 2)
                if not unclaimed_rows or claim_amt <= 0.0:
                    conn.close()
                    self._send_json({ "success": False, "error": "No unclaimed affiliate commission available to claim." }, status=400)
                    return

                curr_bal = float(u["balance"] or 0.0)
                new_bal = round(curr_bal + claim_amt, 2)
                c.execute("UPDATE users SET balance = ? WHERE id = ?", (new_bal, uid))
                c.execute("""
                    UPDATE referral_commissions SET status = 'CLAIMED'
                    WHERE beneficiary_user_id = ? AND UPPER(status) IN ('UNCLAIMED', 'PENDING')
                """, (uid,))
                claim_tx_id = f"TX-AFFCLAIM-{curr_ms}-{random.randint(100, 999)}"
                claim_title = f"Affiliate Commission Claimed (+₹{claim_amt:.2f})"
                claim_ref = f"Claimed {len(unclaimed_rows)} L1–L6 Commission(s) to Main Wallet"
                c.execute("""
                    INSERT INTO transactions (tx_id, user_id, type, title, ref, amount, balance_before, balance_after, status, created_at, created_at_ms)
                    VALUES (?, ?, 'AFFILIATE_CLAIM', ?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
                """, (claim_tx_id, uid, claim_title, claim_ref, claim_amt, curr_bal, new_bal, now_str, curr_ms))
                _, sse_ev = bump_state_version(conn, "affiliate_claimed", {"userId": uid, "claimedAmount": claim_amt, "claimTxId": claim_tx_id})
                commit_and_persist(conn, critical=True)
                updated_aff = build_user_affiliates(conn, uid)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({
                "success": True,
                "message": f"Claimed ₹{claim_amt:.2f} affiliate earnings into main wallet!",
                "claimedAmount": claim_amt,
                "claimedCount": len(unclaimed_rows),
                "newBalance": new_bal,
                "claimTransaction": {
                    "id": claim_tx_id,
                    "title": claim_title,
                    "ref": claim_ref,
                    "amount": claim_amt,
                    "balanceBefore": round(curr_bal, 2),
                    "balanceAfter": new_bal,
                    "status": "CREDITED",
                    "createdAt": now_str,
                    "createdAtMs": curr_ms,
                },
                "affiliates": updated_aff,
            })
            return

        if path == "/api/admin/verify-login":
            u_in = str(payload.get("username") or "").strip()
            p_in = str(payload.get("password") or "").strip()
            mpin_in = str(payload.get("mpin") or "").strip()
            step = str(payload.get("step") or "FULL").upper().strip()
            if u_in != "ColourPrince" or p_in != "Prince@124735":
                self._send_json({ "success": False, "error": "Invalid administrator username or password." }, status=401)
                return
            if step in ("MPIN", "FULL") and mpin_in != "124735":
                self._send_json({ "success": False, "error": "Invalid 6-digit Security MPIN." }, status=401)
                return
            self._send_json({ "success": True, "adminName": "ColourPrince" })
            return

        if path == "/api/admin/sync-state":
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                if isinstance(payload.get("bank_config"), dict):
                    incoming_bc = dict(payload["bank_config"])
                    if "qrImage" not in incoming_bc:
                        c.execute("SELECT value FROM app_state WHERE key = 'bank_config'")
                        ex_row = c.fetchone()
                        if ex_row:
                            try:
                                ex_cfg = json.loads(ex_row[0])
                                if isinstance(ex_cfg, dict) and ex_cfg.get("qrImage"):
                                    incoming_bc["qrImage"] = ex_cfg.get("qrImage")
                            except Exception:
                                pass
                    c.execute("INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES ('bank_config', ?, CURRENT_TIMESTAMP)", (json.dumps(incoming_bc),))
                if isinstance(payload.get("platform_settings"), dict):
                    c.execute("INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES ('platform_settings', ?, CURRENT_TIMESTAMP)", (json.dumps(payload["platform_settings"]),))
                # Note: Never mutate, overwrite, or delete `users` rows via bulk sync-state; users are exclusively managed via /api/users/*, /api/user/adjust, and /api/user/status.
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
                                str(d.get("utr") or ""), format_ist_display(now_ms) if not d.get("time") or str(d.get("time")).lower() == "just now" else str(d.get("time")),
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
                                str(w.get("destination") or ""), format_ist_display(now_ms) if not w.get("time") or str(w.get("time")).lower() == "just now" else str(w.get("time")),
                                str(w.get("status") or "IN PROCESS"), w.get("reason"), now_ms
                            ))
                new_ver, sse_ev = bump_state_version(conn, "admin_sync")
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "state_version": new_ver })
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 6. 24/7 LIVE SUPPORT SYSTEM (AUTO-REACTIVE & ADMIN CUSTOM)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if path == "/api/support/message":
            uid = str(payload.get("userId") or self._get_cookie_uid() or "").strip()
            message = str(payload.get("message") or "").strip()
            category = str(payload.get("category") or "GENERAL").upper().strip()
            att_name = str(payload.get("attachmentName") or "").strip()
            att_mime = str(payload.get("attachmentMime") or "").strip()
            try:
                att_size = max(0, int(payload.get("attachmentSize") or 0))
            except Exception:
                att_size = 0
            att_url = str(payload.get("attachmentUrl") or "").strip()
            if att_url and not att_url.startswith("/api/support/files/"):
                att_url = ""
                att_name = ""
                att_mime = ""
                att_size = 0
            if att_size > MAX_SUPPORT_FILE_BYTES:
                self._send_json({ "success": False, "error": "Attachment exceeds 10 MB limit" }, status=413)
                return
            if not uid or uid == "Guest":
                self._send_json({ "success": False, "error": "Please login to send a support message" }, status=401)
                return
            if not message and not att_url:
                self._send_json({ "success": False, "error": "Please enter a message or attach a file (under 10 MB)" }, status=400)
                return

            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT id, name FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                if not u:
                    conn.close()
                    self._send_json({ "success": False, "error": "User not found" }, status=404)
                    return

                tid, _ = ensure_support_ticket_and_add_message(
                    conn,
                    uid=uid,
                    user_name=u["name"],
                    sender_type="USER",
                    sender_name=u["name"],
                    message=message,
                    category=category,
                    is_auto=0,
                    situation_tag="USER_MEDIA" if att_url else "USER_MESSAGE",
                    now_ms=now_ms,
                    attachment_name=att_name,
                    attachment_mime=att_mime,
                    attachment_size=att_size,
                    attachment_url=att_url,
                )
                auto_tag, auto_reply = generate_support_auto_reply(conn, uid, message, category)
                if att_url:
                    auto_reply = (
                        f"📎 Received your shared file: {att_name or 'Attachment'} ({format_file_size_human(att_size)}). "
                        "It is now visible on the Admin Support Desk.\n" + auto_reply
                    )
                ensure_support_ticket_and_add_message(
                    conn,
                    uid=uid,
                    user_name=u["name"],
                    sender_type="AUTO_BOT",
                    sender_name="Colour King 24/7 Support Bot",
                    message=auto_reply,
                    category=category,
                    is_auto=1,
                    situation_tag=auto_tag,
                    now_ms=now_ms + 1,
                )
                # User is actively viewing chat when sending; clear unread_user right away
                c.execute("UPDATE support_tickets SET unread_user = 0 WHERE ticket_id = ?", (tid,))
                _, sse_ev = bump_state_version(conn, "support_message", {"userId": uid, "ticketId": tid, "category": category, "hasAttachment": bool(att_url)})
                thread_data = fetch_support_thread_payload(conn, uid, mark_read_for="USER", auto_welcome=False)
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({
                **(thread_data or {"success": True}),
                "autoReply": auto_reply,
                "situationTag": auto_tag,
            })
            return

        if path == "/api/support/mark-read":
            uid = str(payload.get("userId") or self._get_cookie_uid() or "").strip()
            role = str(payload.get("role") or "USER").upper().strip()
            ticket_id = str(payload.get("ticketId") or "").strip()
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                if role == "ADMIN" and ticket_id:
                    c.execute("UPDATE support_tickets SET unread_admin = 0 WHERE ticket_id = ?", (ticket_id,))
                elif uid:
                    c.execute("UPDATE support_tickets SET unread_user = 0 WHERE user_id = ?", (uid,))
                _, sse_ev = bump_state_version(conn, "support_read", {"userId": uid, "ticketId": ticket_id, "role": role})
                commit_and_persist(conn, critical=False)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True })
            return

        if path == "/api/admin/support/reply":
            ticket_id = str(payload.get("ticketId") or "").strip()
            uid = str(payload.get("userId") or "").strip()
            message = str(payload.get("message") or "").strip()
            admin_name = str(payload.get("adminName") or "ColourPrince").strip() or "ColourPrince"
            att_name = str(payload.get("attachmentName") or "").strip()
            att_mime = str(payload.get("attachmentMime") or "").strip()
            try:
                att_size = max(0, int(payload.get("attachmentSize") or 0))
            except Exception:
                att_size = 0
            att_url = str(payload.get("attachmentUrl") or "").strip()
            if att_url and not att_url.startswith("/api/support/files/"):
                att_url = ""
                att_name = ""
                att_mime = ""
                att_size = 0
            if not message and not att_url:
                self._send_json({ "success": False, "error": "Reply message or attachment cannot be empty" }, status=400)
                return

            with db_lock:
                conn = get_db()
                c = conn.cursor()
                if not uid and ticket_id:
                    c.execute("SELECT user_id FROM support_tickets WHERE ticket_id = ?", (ticket_id,))
                    tr = c.fetchone()
                    if tr:
                        uid = tr["user_id"]
                c.execute("SELECT id, name FROM users WHERE id = ?", (uid,))
                u = c.fetchone()
                if not u:
                    conn.close()
                    self._send_json({ "success": False, "error": "Target user not found" }, status=404)
                    return

                tid, msg_id = ensure_support_ticket_and_add_message(
                    conn,
                    uid=uid,
                    user_name=u["name"],
                    sender_type="ADMIN",
                    sender_name=f"Admin ({admin_name})",
                    message=message,
                    category="ADMIN_CUSTOM",
                    is_auto=0,
                    situation_tag="ADMIN_CUSTOM_REPLY",
                    now_ms=now_ms,
                    attachment_name=att_name,
                    attachment_mime=att_mime,
                    attachment_size=att_size,
                    attachment_url=att_url,
                )
                c.execute("""
                    INSERT INTO admin_audit_logs (actor, action, entity, desc)
                    VALUES (?, 'ADMIN_SUPPORT_REPLY', ?, ?)
                """, (admin_name, f"{uid} ({tid})", (message or f"📎 {att_name}")[:180]))
                _, sse_ev = bump_state_version(conn, "support_reply", {"userId": uid, "ticketId": tid, "message": message or f"📎 {att_name}"})
                thread_data = fetch_support_thread_payload(conn, uid, mark_read_for=None, auto_welcome=False)
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "ticketId": tid, "messageId": msg_id, "thread": thread_data })
            return

        if path == "/api/admin/support/status":
            ticket_id = str(payload.get("ticketId") or "").strip()
            new_status = str(payload.get("status") or "RESOLVED").upper().strip()
            if new_status not in ("OPEN", "RESOLVED"):
                new_status = "RESOLVED"
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT user_id FROM support_tickets WHERE ticket_id = ?", (ticket_id,))
                trow = c.fetchone()
                uid = trow["user_id"] if trow else ""
                c.execute("UPDATE support_tickets SET status = ?, unread_admin = 0, updated_at = CURRENT_TIMESTAMP, updated_at_ms = ? WHERE ticket_id = ?", (new_status, now_ms, ticket_id))
                if uid:
                    record_admin_situation_support_message(
                        conn,
                        uid,
                        situation_tag=f"TICKET_{new_status}",
                        message=f"📌 Support Ticket {ticket_id} marked {new_status} by Admin." + (" Send a new message anytime to reopen 24/7 support." if new_status == "RESOLVED" else ""),
                        category="SYSTEM",
                        create_if_missing=False,
                        now_ms=now_ms + 1,
                    )
                _, sse_ev = bump_state_version(conn, "support_updated", {"ticketId": ticket_id, "userId": uid, "status": new_status})
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "ticketId": ticket_id, "status": new_status })
            return

        if path == "/api/admin/backup/import":
            backup_obj = payload.get("backup") if isinstance(payload.get("backup"), dict) else payload
            tables = backup_obj.get("tables") if isinstance(backup_obj, dict) else None
            if not isinstance(tables, dict):
                self._send_json({ "success": False, "error": "Invalid backup JSON format (expected tables map)" }, status=400)
                return
            imported_counts = {}
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                allowed_tables = {
                    "users": ["id", "name", "phone", "email", "balance", "total_deposit", "total_withdraw", "bets_count", "status", "referral_code", "referred_by", "password_hash", "password_plain", "created_at"],
                    "deposits": ["id", "user_id", "user_name", "amount", "method", "utr", "time_str", "status", "reason", "created_at", "created_at_ms"],
                    "withdrawals": ["id", "user_id", "user_name", "amount", "upi_id", "bank_name", "acc_no", "ifsc", "banking_name", "destination", "time_str", "status", "reason", "created_at", "created_at_ms"],
                    "bets": ["bet_id", "user_id", "user_name", "market", "round_id", "period", "amount", "platform_fee", "net_amount", "prediction_type", "prediction_target", "multiplier", "potential_payout", "status", "result_text", "win_amount", "loss_amount", "created_at", "created_at_ms", "settled_at"],
                    "transactions": ["tx_id", "user_id", "type", "title", "ref", "amount", "balance_before", "balance_after", "status", "created_at", "created_at_ms"],
                    "referral_commissions": ["id", "beneficiary_user_id", "source_user_id", "source_user_name", "source_bet_id", "level", "rate", "eligible_amount", "commission_amount", "status", "created_at", "created_at_ms"],
                    "support_tickets": ["ticket_id", "user_id", "user_name", "status", "category", "last_message", "last_sender", "unread_admin", "unread_user", "updated_at", "updated_at_ms", "created_at"],
                    "support_messages": ["id", "ticket_id", "user_id", "sender_type", "sender_name", "category", "message", "is_auto", "situation_tag", "attachment_name", "attachment_mime", "attachment_size", "attachment_url", "created_at", "created_at_ms"],
                    "app_state": ["key", "value", "updated_at"],
                }
                for tbl, cols in allowed_tables.items():
                    rows = tables.get(tbl)
                    if not isinstance(rows, list):
                        continue
                    count_tbl = 0
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        present_cols = [col for col in cols if col in row]
                        if not present_cols:
                            continue
                        col_sql = ", ".join(present_cols)
                        ph_sql = ", ".join("?" for _ in present_cols)
                        verb = "INSERT OR REPLACE" if tbl in ("users", "app_state") else "INSERT OR IGNORE"
                        c.execute(f"{verb} INTO {tbl} ({col_sql}) VALUES ({ph_sql})", tuple(row[col] for col in present_cols))
                        count_tbl += 1
                    imported_counts[tbl] = count_tbl
                _, sse_ev = bump_state_version(conn, "backup_imported", {"counts": imported_counts})
                commit_and_persist(conn, critical=True)
                conn.close()
            notify_sse_clients(sse_ev)
            self._send_json({ "success": True, "imported": imported_counts })
            return

        self._send_json({ "error": "Endpoint not found" }, status=404)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

def _flush_on_shutdown(signum, _frame):
    try:
        with db_lock:
            conn = get_db()
            commit_and_persist(conn, critical=True)
            conn.close()
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    if HAS_FLASK_ORM:
        _run_flask_server()
    else:
        signal.signal(signal.SIGTERM, _flush_on_shutdown)
        signal.signal(signal.SIGINT, _flush_on_shutdown)
        init_database()
        sync_round_lifecycle_once()
        daemon_thread = threading.Thread(target=background_round_lifecycle_daemon, daemon=True)
        daemon_thread.start()

        with ThreadedTCPServer(("", PORT), AppHandler) as httpd:
            print(f"Colour King Master Real-Time Threaded Server running on port {PORT} (DB: {DB_FILE}, PostgreSQL: {'ENABLED' if DATABASE_URL else 'LOCAL'}).")
            httpd.serve_forever()
