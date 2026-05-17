"""
Asset Manager — Server
- HTTP (internal domain network)
- SQLite database
- Admin password protected settings
- Asset lookup from Excel file (asset_lookup.xlsx)
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sqlite3, json, os, sys, socket, threading, time, hashlib, secrets, base64, io
from datetime import datetime

app = Flask(__name__)
CORS(app)

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH         = os.path.join(BASE_DIR, "assets.db")
ADMIN_CFG_PATH  = os.path.join(BASE_DIR, "admin_config.json")
SERVER_CFG_PATH = os.path.join(BASE_DIR, "server_config.json")
LOOKUP_PATH     = os.path.join(BASE_DIR, "asset_lookup.xlsx")

def _load_server_cfg():
    default = {"host": "0.0.0.0", "port": 8080}
    if os.path.exists(SERVER_CFG_PATH):
        try:
            with open(SERVER_CFG_PATH) as f:
                d = json.load(f)
            default.update(d)
        except Exception:
            pass
    return default

_SERVER_CFG = _load_server_cfg()
HOST = _SERVER_CFG["host"]
PORT = _SERVER_CFG["port"]

ASSET_TYPES = ["Laptop", "Desktop", "Mobile", "Tablet", "Screen", "UPS", "Server",
               "Cisco Phone", "Printer", "Scanner", "Switch"]

# ─── Embedded default lookup (asset_lookup.xlsx shipped with the app) ─────────
DEFAULT_LOOKUP_B64 = (
    "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"
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

# ─── Admin config ─────────────────────────────────────────────────────────────

def load_admin_cfg():
    if os.path.exists(ADMIN_CFG_PATH):
        with open(ADMIN_CFG_PATH) as f:
            return json.load(f)
    cfg = {"password_hash": sha256("admin"), "first_run": True}
    save_admin_cfg(cfg)
    return cfg

def save_admin_cfg(cfg):
    with open(ADMIN_CFG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

ADMIN_CFG = load_admin_cfg()

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_type       TEXT    NOT NULL,
        serial_number    TEXT    DEFAULT '',
        asset_number     TEXT    DEFAULT '',
        team_member      TEXT    NOT NULL,
        direction        TEXT    NOT NULL,
        timestamp        TEXT    NOT NULL,
        confirmed        INTEGER DEFAULT 0,
        rejected         INTEGER DEFAULT 0,
        confirmed_at     TEXT    DEFAULT '',
        rejection_reason TEXT    DEFAULT '',
        notes            TEXT    DEFAULT '',
        storekeeper      TEXT    DEFAULT 'Storekeeper User'
    )''')
    cols = [row[1] for row in c.execute("PRAGMA table_info(transactions)").fetchall()]
    if 'rejection_reason' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN rejection_reason TEXT DEFAULT ''")
    if 'asset_number' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN asset_number TEXT DEFAULT ''")
    if 'asset_model' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN asset_model TEXT DEFAULT ''")
    conn.commit()
    conn.close()

# ─── Lookup helpers ───────────────────────────────────────────────────────────

def _ensure_sample_lookup():
    """Write the embedded real asset_lookup.xlsx if no file exists yet."""
    if os.path.exists(LOOKUP_PATH):
        return
    try:
        raw = base64.b64decode(DEFAULT_LOOKUP_B64)
        with open(LOOKUP_PATH, 'wb') as f:
            f.write(raw)
    except Exception:
        pass  # fallback: leave missing, server will still run


def _load_lookup_table():
    """
    Load asset_lookup.xlsx into a dict keyed by both asset_number and serial_number
    (both lowercased for case-insensitive lookup).
    Returns dict: lower(value) -> {"asset_type": ..., "asset_number": ..., "serial_number": ...}
    """
    _ensure_sample_lookup()
    if not os.path.exists(LOOKUP_PATH):
        return {}
    try:
        import openpyxl
        wb  = openpyxl.load_workbook(LOOKUP_PATH, read_only=True, data_only=True)
        ws  = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        wb.close()
    except Exception:
        return {}

    table = {}
    for row in rows:
        if not row or len(row) < 3:
            continue
        asset_no  = str(row[0]).strip() if row[0] else ""
        serial_no = str(row[1]).strip() if row[1] else ""
        atype     = str(row[2]).strip() if row[2] else ""
        amodel    = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        if amodel.upper() in ("N/A", "N\\A", "NA", "N.A", "-"):
            amodel = ""
        if atype not in ASSET_TYPES:
            continue
        entry = {"asset_type": atype, "asset_number": asset_no, "serial_number": serial_no, "asset_model": amodel}
        if asset_no:
            table[asset_no.lower()] = entry
        if serial_no:
            table[serial_no.lower()] = entry
    return table


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    conn  = get_db()
    count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    conn.close()
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat(), "total": count})

@app.route('/transactions', methods=['GET'])
def get_transactions():
    member = request.args.get('member', '')
    conn   = get_db()
    if member:
        rows = conn.execute(
            'SELECT * FROM transactions WHERE team_member=? ORDER BY timestamp DESC', (member,)
        ).fetchall()
    else:
        rows = conn.execute('SELECT * FROM transactions ORDER BY timestamp DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/transactions', methods=['POST'])
def create_transaction():
    data = request.json
    if not data.get('team_member') or not data.get('direction'):
        return jsonify({"error": "Missing required fields"}), 400
    if not data.get('serial_number') and not data.get('asset_number'):
        return jsonify({"error": "Provide at least Serial Number or Asset Number"}), 400

    asset_no  = (data.get('asset_number',  '') or '').strip()
    serial_no = (data.get('serial_number', '') or '').strip()

    conn = get_db()

    # Block duplicate pending transactions for the same asset
    conditions, params = [], []
    if asset_no:
        conditions.append("(asset_number=? AND asset_number != '')")
        params.append(asset_no)
    if serial_no:
        conditions.append("(serial_number=? AND serial_number != '')")
        params.append(serial_no)
    if conditions:
        existing = conn.execute(
            f"SELECT id FROM transactions WHERE ({' OR '.join(conditions)}) AND confirmed=0 AND rejected=0",
            params
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({"error": "This asset already has a pending transaction. Confirm or reject it first."}), 409

    cur  = conn.execute(
        '''INSERT INTO transactions
           (asset_type, serial_number, asset_number, asset_model,
            team_member, direction, timestamp, notes, storekeeper)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (
            data.get('asset_type',   'Laptop'),
            serial_no,
            asset_no,
            (data.get('asset_model', '') or '').strip(),
            data['team_member'],
            data['direction'],
            datetime.now().isoformat(),
            data.get('notes', ''),
            data.get('storekeeper', 'Storekeeper User'),
        )
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return jsonify({"id": new_id, "status": "created"}), 201

@app.route('/pending/<path:member>')
def get_pending(member):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM transactions WHERE team_member=? AND confirmed=0 AND rejected=0 ORDER BY timestamp',
        (member,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/confirm/<int:trans_id>', methods=['POST'])
def confirm_transaction(trans_id):
    conn = get_db()
    conn.execute('UPDATE transactions SET confirmed=1, confirmed_at=? WHERE id=?',
                 (datetime.now().isoformat(), trans_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "confirmed"})

@app.route('/reject/<int:trans_id>', methods=['POST'])
def reject_transaction(trans_id):
    data   = request.json or {}
    reason = data.get('reason', '')
    conn   = get_db()
    conn.execute(
        'UPDATE transactions SET rejected=1, confirmed_at=?, rejection_reason=? WHERE id=?',
        (datetime.now().isoformat(), reason, trans_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "rejected"})

@app.route('/stats')
def get_stats():
    conn      = get_db()
    total     = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    pending   = conn.execute('SELECT COUNT(*) FROM transactions WHERE confirmed=0 AND rejected=0').fetchone()[0]
    confirmed = conn.execute('SELECT COUNT(*) FROM transactions WHERE confirmed=1').fetchone()[0]
    out_now   = conn.execute("SELECT COUNT(*) FROM transactions WHERE direction='Out Store' AND confirmed=1").fetchone()[0]
    conn.close()
    return jsonify({"total": total, "pending": pending, "confirmed": confirmed, "out_now": out_now})

@app.route('/export')
def export_all():
    conn = get_db()
    rows = conn.execute('SELECT * FROM transactions ORDER BY timestamp DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ─── Lookup routes ────────────────────────────────────────────────────────────

@app.route('/lookup')
def lookup_asset():
    """
    GET /lookup?q=<asset_number_or_serial>
    Returns {"found": true, "asset_type": "...", "asset_number": "...", "serial_number": "..."}
    or      {"found": false}
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"found": False, "error": "No query provided"}), 400
    table = _load_lookup_table()
    entry = table.get(q.lower())
    if entry:
        return jsonify({"found": True, **entry})
    return jsonify({"found": False})

@app.route('/lookup/file')
def lookup_file():
    """GET /lookup/file — Download the current lookup Excel file."""
    _ensure_sample_lookup()
    if not os.path.exists(LOOKUP_PATH):
        return jsonify({"error": "No lookup file on server"}), 404
    return send_file(
        LOOKUP_PATH,
        as_attachment=True,
        download_name="asset_lookup.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/lookup/upload', methods=['POST'])
def lookup_upload():
    """
    POST /lookup/upload
    Body: {"password": "...", "file_data": "<base64-encoded xlsx>"}
    Replaces asset_lookup.xlsx on the server.
    """
    data = request.json or {}
    if sha256(data.get('password', '')) != ADMIN_CFG['password_hash']:
        return jsonify({"error": "Wrong admin password"}), 401
    file_b64 = data.get('file_data', '')
    if not file_b64:
        return jsonify({"error": "No file data provided"}), 400
    try:
        raw = base64.b64decode(file_b64)
        # Quick validation — check it's a valid xlsx
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True)
        wb.close()
        with open(LOOKUP_PATH, 'wb') as f:
            f.write(raw)
        # Count rows loaded
        table = _load_lookup_table()
        unique = {(e['asset_number'], e['serial_number']) for e in table.values()}
        return jsonify({"status": "ok", "assets_loaded": len(unique)})
    except Exception as e:
        return jsonify({"error": f"Invalid Excel file: {e}"}), 400

# ─── Admin routes ─────────────────────────────────────────────────────────────

@app.route('/admin/verify', methods=['POST'])
def admin_verify():
    data = request.json or {}
    if sha256(data.get('password', '')) == ADMIN_CFG['password_hash']:
        return jsonify({"valid": True})
    return jsonify({"valid": False}), 401

@app.route('/admin/change_password', methods=['POST'])
def admin_change_password():
    data    = request.json or {}
    current = data.get('current_password', '')
    new_pw  = data.get('new_password', '')
    if sha256(current) != ADMIN_CFG['password_hash']:
        return jsonify({"error": "Wrong current password"}), 401
    if len(new_pw) < 4:
        return jsonify({"error": "Password too short (min 4 chars)"}), 400
    ADMIN_CFG['password_hash'] = sha256(new_pw)
    ADMIN_CFG['first_run']     = False
    save_admin_cfg(ADMIN_CFG)
    return jsonify({"status": "ok"})

@app.route('/admin/server_config', methods=['GET'])
def get_server_config():
    data = request.json or {}
    if sha256(data.get('password', '')) != ADMIN_CFG['password_hash']:
        return jsonify({"error": "Wrong admin password"}), 401
    return jsonify({"host": HOST, "port": PORT})

@app.route('/admin/server_config', methods=['POST'])
def set_server_config():
    data = request.json or {}
    if sha256(data.get('password', '')) != ADMIN_CFG['password_hash']:
        return jsonify({"error": "Wrong admin password"}), 401
    new_host = str(data.get('host', '0.0.0.0')).strip()
    try:
        new_port = int(data.get('port', 80))
        if not (1 <= new_port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid port (1–65535)"}), 400
    with open(SERVER_CFG_PATH, 'w') as f:
        json.dump({"host": new_host, "port": new_port}, f, indent=2)
    return jsonify({"status": "ok", "note": "Restart the server to apply changes."})

# ─── Server GUI ───────────────────────────────────────────────────────────────

def _load_lookup_raw():
    """Return list of (asset_number, serial_number, asset_type, asset_model) from xlsx."""
    _ensure_sample_lookup()
    if not os.path.exists(LOOKUP_PATH):
        return []
    try:
        import openpyxl
        wb   = openpyxl.load_workbook(LOOKUP_PATH, read_only=True, data_only=True)
        ws   = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        wb.close()
        result = []
        for row in rows:
            if not row or len(row) < 3:
                continue
            an = str(row[0]).strip() if row[0] else ""
            sn = str(row[1]).strip() if row[1] else ""
            at = str(row[2]).strip() if row[2] else ""
            am = str(row[3]).strip() if len(row) > 3 and row[3] else ""
            if am.upper() in ("N/A", "N\\A", "NA", "N.A", "-"):
                am = ""
            if not an and not sn:
                continue
            result.append((an, sn, at, am))
        return result
    except Exception:
        return []


def _save_lookup_raw(rows):
    """Write list of (asset_number, serial_number, asset_type) to xlsx."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Asset Lookup"
    blue_fill = PatternFill("solid", fgColor="0078D4")
    hdr_font  = Font(bold=True, color="FFFFFF", name="Segoe UI", size=10)
    headers   = ["Asset Number", "Serial Number", "Asset Type", "Asset Model"]
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font      = hdr_font
        cell.fill      = blue_fill
        cell.alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 26
    for ri, row_data in enumerate(rows, 2):
        an = row_data[0] if len(row_data) > 0 else ""
        sn = row_data[1] if len(row_data) > 1 else ""
        at = row_data[2] if len(row_data) > 2 else ""
        am = row_data[3] if len(row_data) > 3 else ""
        ws.cell(row=ri, column=1, value=an)
        ws.cell(row=ri, column=2, value=sn)
        ws.cell(row=ri, column=3, value=at)
        ws.cell(row=ri, column=4, value=am)
    wb.save(LOOKUP_PATH)


def run_gui():
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Asset Manager — Server")
    root.geometry("530x630")
    root.configure(bg="#1e2a3a")
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW",
        lambda: messagebox.askyesno("Quit", "Stop the server?") and os._exit(0))

    hdr = tk.Frame(root, bg="#0078d4", height=55)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="📦  Asset Manager  —  Server",
             bg="#0078d4", fg="white",
             font=("Segoe UI", 14, "bold")).pack(side="left", padx=18, pady=14)

    card = tk.Frame(root, bg="#243447", padx=24, pady=16)
    card.pack(fill="x", padx=18, pady=14)

    hostname = socket.gethostname()
    try:    local_ip = socket.gethostbyname(hostname)
    except: local_ip = "127.0.0.1"

    server_url = f"http://asset-server:{PORT}"

    def info_row(label, value, color="#ffffff"):
        f = tk.Frame(card, bg="#243447")
        f.pack(fill="x", pady=3)
        tk.Label(f, text=label, bg="#243447", fg="#8a9bb0",
                 font=("Segoe UI", 9), width=18, anchor="w").pack(side="left")
        tk.Label(f, text=value, bg="#243447", fg=color,
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left")

    info_row("Status:",      "● RUNNING",            "#4caf50")
    info_row("Encryption:",  "HTTP  (internal network)", "#4caf50")
    info_row("Host:",        hostname)
    info_row("IP Address:",  local_ip,   "#0078d4")
    info_row("Port:",        str(PORT))
    info_row("Server URL:",  server_url, "#f0a500")
    info_row("Database:",    DB_PATH)

    def copy_url():
        root.clipboard_clear()
        root.clipboard_append(server_url)
        btn.config(text="✓  Copied!")
        root.after(2500, lambda: btn.config(text="📋  Copy Server URL"))

    btn = tk.Button(root, text="📋  Copy Server URL",
                    bg="#0078d4", fg="white",
                    font=("Segoe UI", 10, "bold"),
                    relief="flat", cursor="hand2", pady=10,
                    command=copy_url, activebackground="#106ebe")
    btn.pack(fill="x", padx=18, pady=(0, 6))

    # ─── Change Admin Password ────────────────────────────────────────────
    def change_admin_password():
        import tkinter.messagebox as mb
        dlg = tk.Toplevel(root)
        dlg.title("Change Admin Password")
        dlg.geometry("400x400")
        dlg.configure(bg="#1e2a3a")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(root)

        hdr = tk.Frame(dlg, bg="#0078d4", height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🔑  Change Admin Password",
                 bg="#0078d4", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=14, pady=12)

        frm = tk.Frame(dlg, bg="#243447", padx=20, pady=14)
        frm.pack(fill="x", padx=18, pady=14)

        def pw_field(label):
            tk.Label(frm, text=label, bg="#243447", fg="#8a9bb0",
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 2))
            e = tk.Entry(frm, show="●", bg="#2a3f55", fg="#ffffff",
                         relief="flat", font=("Segoe UI", 10),
                         insertbackground="#ffffff")
            e.pack(fill="x", ipady=7)
            return e

        cur_e = pw_field("Current Password")
        new_e = pw_field("New Password  (min 4 characters)")
        cnf_e = pw_field("Confirm New Password")

        err_lbl = tk.Label(dlg, text="", bg="#1e2a3a", fg="#f44336",
                           font=("Segoe UI", 9))
        err_lbl.pack(pady=(2, 0))

        def do_change():
            cur = cur_e.get()
            new = new_e.get()
            cnf = cnf_e.get()
            if not cur or not new or not cnf:
                err_lbl.config(text="✗  All fields are required.")
                return
            if new != cnf:
                err_lbl.config(text="✗  New password and confirmation do not match.")
                return
            if len(new) < 4:
                err_lbl.config(text="✗  New password must be at least 4 characters.")
                return
            if sha256(cur) != ADMIN_CFG['password_hash']:
                err_lbl.config(text="✗  Current password is incorrect.")
                return
            ADMIN_CFG['password_hash'] = sha256(new)
            ADMIN_CFG['first_run']     = False
            save_admin_cfg(ADMIN_CFG)
            dlg.destroy()
            mb.showinfo("Done", "✓  Admin password changed successfully.")

        tk.Button(dlg, text="Change Password",
                  bg="#0078d4", fg="white", font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", pady=9,
                  command=do_change,
                  activebackground="#106ebe").pack(fill="x", padx=18, pady=(4, 12))
        cur_e.focus_set()

    tk.Button(root, text="🔑  Change Admin Password",
              bg="#f0a500", fg="white",
              font=("Segoe UI", 9, "bold"),
              relief="flat", cursor="hand2", pady=8,
              command=change_admin_password,
              activebackground="#c47d00").pack(fill="x", padx=18, pady=(0, 4))

    def change_host_port():
        import tkinter.messagebox as mb
        dlg = tk.Toplevel(root)
        dlg.title("Change Host / Port")
        dlg.geometry("400x340")
        dlg.configure(bg="#1e2a3a")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(root)

        hdr2 = tk.Frame(dlg, bg="#0078d4", height=44)
        hdr2.pack(fill="x")
        hdr2.pack_propagate(False)
        tk.Label(hdr2, text="🌐  Change Host / Port",
                 bg="#0078d4", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=14, pady=12)

        frm2 = tk.Frame(dlg, bg="#243447", padx=20, pady=14)
        frm2.pack(fill="x", padx=18, pady=14)

        def cfg_field(label, default_val):
            tk.Label(frm2, text=label, bg="#243447", fg="#8a9bb0",
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 2))
            e = tk.Entry(frm2, bg="#2a3f55", fg="#ffffff", relief="flat",
                         font=("Segoe UI", 10), insertbackground="#ffffff")
            e.insert(0, str(default_val))
            e.pack(fill="x", ipady=7)
            return e

        host_e = cfg_field("Bind Host  (0.0.0.0 = all interfaces)", HOST)
        port_e = cfg_field("Port", PORT)

        tk.Label(dlg, text="⚠  Restart the server after saving for changes to take effect.",
                 bg="#1e2a3a", fg="#f0a500", font=("Segoe UI", 8),
                 wraplength=360).pack(pady=(0, 2))
        err2 = tk.Label(dlg, text="", bg="#1e2a3a", fg="#f44336", font=("Segoe UI", 9))
        err2.pack()

        def do_save_cfg():
            h = host_e.get().strip()
            p = port_e.get().strip()
            if not h:
                err2.config(text="✗  Host cannot be empty.")
                return
            try:
                p_int = int(p)
                if not (1 <= p_int <= 65535):
                    raise ValueError
            except ValueError:
                err2.config(text="✗  Port must be a number between 1 and 65535.")
                return
            with open(SERVER_CFG_PATH, 'w') as f:
                json.dump({"host": h, "port": p_int}, f, indent=2)
            dlg.destroy()
            mb.showinfo("Saved", "✓  Server config saved.\nRestart the server to apply.")

        tk.Button(dlg, text="Save  (restart to apply)",
                  bg="#0078d4", fg="white", font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", pady=9,
                  command=do_save_cfg,
                  activebackground="#106ebe").pack(fill="x", padx=18, pady=(0, 12))
        host_e.focus_set()

    tk.Button(root, text="🌐  Change Host / Port",
              bg="#2a5e8a", fg="white",
              font=("Segoe UI", 9, "bold"),
              relief="flat", cursor="hand2", pady=8,
              command=change_host_port,
              activebackground="#1a4060").pack(fill="x", padx=18, pady=(0, 10))

    # Stats
    stats_card = tk.Frame(root, bg="#243447", padx=14, pady=12)
    stats_card.pack(fill="x", padx=18, pady=(0, 10))
    tk.Label(stats_card, text="Live Statistics",
             bg="#243447", fg="#0078d4",
             font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
    stat_row   = tk.Frame(stats_card, bg="#243447")
    stat_row.pack(fill="x")
    stat_labels = {}
    for key, label, color in [
        ("total",     "Total",     "#ffffff"),
        ("pending",   "Pending",   "#f0a500"),
        ("confirmed", "Confirmed", "#4caf50"),
        ("out_now",   "Out Now",   "#f44336"),
    ]:
        col = tk.Frame(stat_row, bg="#2d3f52", padx=12, pady=8)
        col.pack(side="left", expand=True, fill="x", padx=3)
        v = tk.Label(col, text="—", bg="#2d3f52", fg=color,
                     font=("Segoe UI", 18, "bold"))
        v.pack()
        tk.Label(col, text=label, bg="#2d3f52", fg="#e0eaf5",
                 font=("Segoe UI", 10, "bold")).pack(pady=(4, 4))
        stat_labels[key] = v

    def refresh_stats():
        try:
            import requests as req
            r = req.get(f"http://127.0.0.1:{PORT}/stats", timeout=2)
            if r.ok:
                for k, lbl in stat_labels.items():
                    lbl.config(text=str(r.json().get(k, "—")))
        except: pass
        root.after(5000, refresh_stats)

    refresh_stats()

    root.mainloop()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    _ensure_sample_lookup()

    def run_flask():
        app.run(
            host=HOST,
            port=PORT,
            debug=False,
            use_reloader=False
        )

    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(0.8)
    run_gui()
