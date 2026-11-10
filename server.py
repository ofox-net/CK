import http.server
import socketserver
import json
import os
import urllib.parse
from datetime import datetime

PORT = 3000
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATE_FILE = os.path.join(DIRECTORY, "server_state.json")

DEFAULT_STATE = {
    "bank_config": {
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
    },
    "users": {
        "USR-1001": { "id": "USR-1001", "name": "Rahul_Player", "balance": 50200.00, "totalDeposit": 75000.00, "totalWithdraw": 28000.00, "betsCount": 142, "status": "ACTIVE" },
        "USR-1002": { "id": "USR-1002", "name": "Aman_Trader", "balance": 14500.00, "totalDeposit": 25000.00, "totalWithdraw": 11000.00, "betsCount": 68, "status": "ACTIVE" },
        "USR-1003": { "id": "USR-1003", "name": "Priya_VIP", "balance": 125000.00, "totalDeposit": 200000.00, "totalWithdraw": 95000.00, "betsCount": 310, "status": "ACTIVE" },
        "USR-1004": { "id": "USR-1004", "name": "Vikram_99", "balance": 3200.00, "totalDeposit": 10000.00, "totalWithdraw": 6000.00, "betsCount": 45, "status": "ACTIVE" },
        "USR-1005": { "id": "USR-1005", "name": "Suspicious_Bot1", "balance": 0.00, "totalDeposit": 5000.00, "totalWithdraw": 0.00, "betsCount": 8, "status": "BLOCKED" },
        "USR-1006": { "id": "USR-1006", "name": "Karan_Pro", "balance": 38400.00, "totalDeposit": 60000.00, "totalWithdraw": 24000.00, "betsCount": 94, "status": "ACTIVE" }
    },
    "deposits": [
        { "id": "DEP-88401", "userId": "USR-1001", "userName": "Rahul_Player", "amount": 5000.00, "method": "UPI (GooglePay)", "utr": "429188402911", "time": "Today, 11:24 AM", "status": "PENDING" },
        { "id": "DEP-88402", "userId": "USR-1002", "userName": "Aman_Trader", "amount": 10000.00, "method": "IMPS SBI NetBanking", "utr": "902184716294", "time": "Today, 11:18 AM", "status": "PENDING" },
        { "id": "DEP-88403", "userId": "USR-1006", "userName": "Karan_Pro", "amount": 2500.00, "method": "Paytm UPI QR", "utr": "419082736184", "time": "Today, 10:45 AM", "status": "PENDING" },
        { "id": "DEP-88399", "userId": "USR-1003", "userName": "Priya_VIP", "amount": 50000.00, "method": "HDFC IMPS", "utr": "389271628190", "time": "Today, 09:12 AM", "status": "APPROVED" }
    ],
    "withdrawals": [
        {
            "id": "WD-99412",
            "userId": "USR-1001",
            "userName": "Rahul_Player",
            "amount": 8000.00,
            "upiId": "rahul@oksbi",
            "bankName": "State Bank of India",
            "accNo": "40928172901",
            "ifsc": "SBIN0001824",
            "bankingName": "Rahul Kumar Sharma",
            "destination": "Rahul Kumar Sharma • SBI (A/C: 40928172901, IFSC: SBIN0001824) • UPI: rahul@oksbi",
            "time": "Today, 11:32 AM",
            "status": "PENDING"
        },
        {
            "id": "WD-99413",
            "userId": "USR-1004",
            "userName": "Vikram_99",
            "amount": 2500.00,
            "upiId": "vikram99@icici",
            "bankName": "HDFC Bank",
            "accNo": "5010049281729",
            "ifsc": "HDFC000124",
            "bankingName": "Vikram Sethi",
            "destination": "Vikram Sethi • HDFC (A/C: 5010049281729, IFSC: HDFC000124) • UPI: vikram99@icici",
            "time": "Today, 10:55 AM",
            "status": "PENDING"
        },
        {
            "id": "WD-99410",
            "userId": "USR-1003",
            "userName": "Priya_VIP",
            "amount": 45000.00,
            "upiId": "priya@axl",
            "bankName": "ICICI Bank",
            "accNo": "002101928374",
            "ifsc": "ICIC0000021",
            "bankingName": "Priya Singhania",
            "destination": "Priya Singhania • ICICI (A/C: 002101928374, IFSC: ICIC0000021) • UPI: priya@axl",
            "time": "Today, 08:40 AM",
            "status": "APPROVED"
        }
    ]
}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    save_state(DEFAULT_STATE)
    return DEFAULT_STATE

def save_state(state):
    try:
        os.makedirs(DIRECTORY, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Error saving state: {e}")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == '/admin' or path == '/admin/':
            self.send_response(301)
            self.send_header('Location', '/admin.html')
            self.end_headers()
            return

        if path == '/api/state':
            state = load_state()
            self._send_json(state)
            return

        if path == '/api/bank-config':
            state = load_state()
            self._send_json(state.get("bank_config", {}))
            return

        if path == '/api/user':
            user_id = qs.get("id", ["USR-1001"])[0]
            state = load_state()
            user = state.get("users", {}).get(user_id)
            if user:
                self._send_json(user)
            else:
                new_user = {
                    "id": user_id,
                    "name": qs.get("name", [user_id])[0],
                    "balance": 50200.00,
                    "totalDeposit": 0.0,
                    "totalWithdraw": 0.0,
                    "betsCount": 0,
                    "status": "ACTIVE"
                }
                state["users"][user_id] = new_user
                save_state(state)
                self._send_json(new_user)
            return

        if path == '/api/wallet':
            user_id = qs.get("userId", ["USR-1001"])[0]
            state = load_state()
            user = state.get("users", {}).get(user_id, {})
            self._send_json({
                "userId": user_id,
                "name": user.get("name", "Rahul_Player"),
                "balance": user.get("balance", 50200.00)
            })
            return

        if path == '/api/deposits':
            state = load_state()
            self._send_json(state.get("deposits", []))
            return

        if path == '/api/withdrawals':
            state = load_state()
            self._send_json(state.get("withdrawals", []))
            return

        if path == '/api/results':
            state = load_state()
            self._send_json(state.get("declared_results", {}))
            return

        if path == '/api/admin/draw-override':
            state = load_state()
            self._send_json(state.get("draw_overrides", {}))
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        state = load_state()

        if path == '/api/admin/draw-override':
            m_key = str(payload.get("market", "MIAMI")).upper()
            period = str(payload.get("period", "")).strip()
            mode = str(payload.get("mode", "MANUAL")).upper()
            if "draw_overrides" not in state:
                state["draw_overrides"] = {}

            if mode == "AUTO" or payload.get("number") is None:
                # Clear manual override for this market
                state["draw_overrides"].pop(m_key, None)
            else:
                num = int(payload.get("number", 0))
                num = max(0, min(9, num))
                color = "violet" if num in [0, 5] else ("green" if num in [1, 3, 7, 9] else "red")
                col_class = "red-violet" if num == 0 else ("green-violet" if num == 5 else color)
                state["draw_overrides"][m_key] = {
                    "market": m_key,
                    "period": period,
                    "number": num,
                    "color": color,
                    "colClass": col_class,
                    "isBig": num >= 5,
                    "mode": "MANUAL",
                    "setAt": datetime.now().strftime('%H:%M:%S')
                }
            save_state(state)
            self._send_json({ "success": True, "overrides": state["draw_overrides"] })
            return

        if path == '/api/bank-config':
            state["bank_config"].update(payload)
            save_state(state)
            self._send_json({ "success": True, "bank_config": state["bank_config"] })
            return

        if path == '/api/results':
            m_key = str(payload.get("market", "MIAMI")).upper()
            period = str(payload.get("period", "")).strip()
            if period:
                if "declared_results" not in state:
                    state["declared_results"] = {}
                if m_key not in state["declared_results"]:
                    state["declared_results"][m_key] = {}
                state["declared_results"][m_key][period] = payload

                # Check if manual override existed and consume it
                if "draw_overrides" in state and m_key in state["draw_overrides"]:
                    override = state["draw_overrides"][m_key]
                    if not override.get("period") or override.get("period") == period:
                        state["draw_overrides"].pop(m_key, None)

                save_state(state)
            self._send_json({ "success": True })
            return

        if path == '/api/user/balance' or path == '/api/wallet/sync':
            user_id = payload.get("userId", "USR-1001")
            new_balance = float(payload.get("balance", 0.0))
            if user_id not in state["users"]:
                state["users"][user_id] = {
                    "id": user_id,
                    "name": payload.get("name", user_id),
                    "balance": new_balance,
                    "totalDeposit": 0.0,
                    "totalWithdraw": 0.0,
                    "betsCount": 0,
                    "status": "ACTIVE"
                }
            else:
                state["users"][user_id]["balance"] = new_balance

            save_state(state)
            self._send_json({ "success": True, "userId": user_id, "balance": new_balance })
            return

        if path == '/api/deposits':
            # Create new deposit request
            amount = float(payload.get("amount", 0.0))
            utr = str(payload.get("utr", "")).strip()
            method = str(payload.get("method", "UPI"))
            user_id = payload.get("userId", "USR-1001")
            user_name = payload.get("userName", state.get("users", {}).get(user_id, {}).get("name", "Rahul_Player"))

            dep_id = f"DEP-{datetime.now().strftime('%H%M%S')}"
            new_dep = {
                "id": dep_id,
                "userId": user_id,
                "userName": user_name,
                "amount": amount,
                "method": method,
                "utr": utr,
                "time": "Just now",
                "status": "IN PROCESS"
            }
            state.setdefault("deposits", []).insert(0, new_dep)
            save_state(state)
            self._send_json({ "success": True, "deposit": new_dep })
            return

        if path == '/api/deposits/approve':
            dep_id = payload.get("depositId")
            for d in state.get("deposits", []):
                if d["id"] == dep_id:
                    d["status"] = "SUCCESS"
                    uid = d["userId"]
                    if uid in state["users"]:
                        state["users"][uid]["balance"] += d["amount"]
                        state["users"][uid]["totalDeposit"] += d["amount"]
                    break
            save_state(state)
            self._send_json({ "success": True })
            return

        if path == '/api/deposits/reject':
            dep_id = payload.get("depositId")
            reason = payload.get("reason", "Verification failed")
            for d in state.get("deposits", []):
                if d["id"] == dep_id:
                    d["status"] = "FAIL"
                    d["reason"] = reason
                    break
            save_state(state)
            self._send_json({ "success": True })
            return

        if path == '/api/withdrawals':
            # Create new withdrawal request with all requested details:
            amount = float(payload.get("amount", 0.0))
            upi_id = str(payload.get("upiId", "")).strip()
            bank_name = str(payload.get("bankName", "")).strip()
            acc_no = str(payload.get("accNo", "")).strip()
            ifsc = str(payload.get("ifsc", "")).strip().upper()
            banking_name = str(payload.get("bankingName", "")).strip()
            user_id = payload.get("userId", "USR-1001")
            user_name = payload.get("userName", state.get("users", {}).get(user_id, {}).get("name", "Rahul_Player"))

            # Deduct balance into escrow
            if user_id in state["users"]:
                if state["users"][user_id]["balance"] >= amount:
                    state["users"][user_id]["balance"] -= amount
                else:
                    self._send_json({ "success": False, "error": "Insufficient balance" }, status=400)
                    return

            wd_id = f"WD-{datetime.now().strftime('%H%M%S')}"
            destination = f"{banking_name} • {bank_name} (A/C: {acc_no}, IFSC: {ifsc}) • UPI: {upi_id}"
            new_wd = {
                "id": wd_id,
                "userId": user_id,
                "userName": user_name,
                "amount": amount,
                "upiId": upi_id,
                "bankName": bank_name,
                "accNo": acc_no,
                "ifsc": ifsc,
                "bankingName": banking_name,
                "destination": destination,
                "time": "Just now",
                "status": "IN PROCESS"
            }
            state.setdefault("withdrawals", []).insert(0, new_wd)
            save_state(state)
            self._send_json({ "success": True, "withdrawal": new_wd, "newBalance": state["users"][user_id]["balance"] })
            return

        if path == '/api/withdrawals/approve':
            wd_id = payload.get("withdrawalId")
            for w in state.get("withdrawals", []):
                if w["id"] == wd_id:
                    w["status"] = "SUCCESS"
                    uid = w["userId"]
                    if uid in state["users"]:
                        state["users"][uid]["totalWithdraw"] += w["amount"]
                    break
            save_state(state)
            self._send_json({ "success": True })
            return

        if path == '/api/withdrawals/reject':
            wd_id = payload.get("withdrawalId")
            reason = payload.get("reason", "Details mismatch")
            for w in state.get("withdrawals", []):
                if w["id"] == wd_id:
                    w["status"] = "FAIL"
                    w["reason"] = reason
                    uid = w["userId"]
                    if uid in state["users"]:
                        # Refund balance
                        state["users"][uid]["balance"] += w["amount"]
                    break
            save_state(state)
            self._send_json({ "success": True })
            return

        self._send_json({ "error": "Endpoint not found" }, status=404)

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving Colour King Master Full-Stack API & Web on port {PORT} from {DIRECTORY}")
        httpd.serve_forever()
