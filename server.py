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
    "UEsDBBQABgAIAAAAIQCnDOt5aAEAAA0FAAATAAgCW0NvbnRlbnRfVHlwZXNdLnhtbCCiBAIooAAC"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACs"
    "lMtuwjAQRfeV+g+Rt1Vi6KKqKgKLPpYtUukHuPaEWPglz0Dh7+sYqKoqBSHYxEo8c8/NxDejydqa"
    "YgURtXc1G1YDVoCTXmk3r9nH7KW8ZwWScEoY76BmG0A2GV9fjWabAFikboc1a4nCA+coW7ACKx/A"
    "pZ3GRyso3cY5D0IuxBz47WBwx6V3BI5K6jTYePQEjVgaKp7X6fHWSQSDrHjcFnasmokQjJaCklO+"
    "cuoPpdwRqtSZa7DVAW+SDcZ7Cd3O/4Bd31saTdQKiqmI9CpsssHXhn/5uPj0flEdFulx6ZtGS1Be"
    "Lm2aQIUhglDYApA1VV4rK7Tb+z7Az8XI8zK8sJHu/bLwER+UvjfwfD3fQpY5AkTaGMBLjz2LHiO3"
    "IoJ6p5iScXEDv7UP+UjnZhp9wJSgCKdPYR+RrrsMSQgiafgJSd9h+yGm9J09dujyrUCdypZLJG/P"
    "xm9leuA8/8zG3wAAAP//AwBQSwMEFAAGAAgAAAAhABNevmUCAQAA3wIAAAsACAJfcmVscy8ucmVs"
    "cyCiBAIooAACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAACskk1LAzEQhu+C/yHMvTvbKiLSbC9F6E1k/QExmf1gN5mQpLr990ZBdKG2Hnqcr3ee"
    "eZn1ZrKjeKMQe3YSlkUJgpxm07tWwkv9uLgHEZNyRo3sSMKBImyq66v1M40q5aHY9T6KrOKihC4l"
    "/4AYdUdWxYI9uVxpOFiVchha9EoPqiVcleUdht8aUM00xc5ICDtzA6I++Lz5vDY3Ta9py3pvyaUj"
    "K5CmRM6QWfiQ2ULq8zWiVqGlJMGwfsrpiMr7ImMDHida/Z/o72vRUlJGJYWaA53m+ew4BbS8pEVz"
    "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"
    "Or80ZPko/Pn1R/n9zcanJf58pJ7eyJ/M3wxZPgp/3i7Ts/5c4s9Ryp7zD7Qtk/urzjAKf94u85yl"
    "ZPkr8edonPP0j0n4hSYg/xD+3KnS+Er+Qfz5PAm/MBqyfBT+3KnS+Er+QX2+EZ/MPwx/Pgp/jooo"
    "s+Q0vpJ/EH+O+OT9MGT5KPw5KqLUvzS+0voV8eeIT94P0/J7FP4cFbE/fyX/IP581s4iqHXqv8Kf"
    "O1Wav5J/EH+O+GR8ZfjzUfhzVMT+/JX8g/jzGR9YifXPdPcehT9HRex//krzD+LPEZ++H2b9Svjz"
    "sZ8/R3Gq+C/z55M0tb4uF/Y/hD93quz5K/HnKGXkH8LvNwH5h/DnTpXGV/IP5s+neLLqhVpn3l/Z"
    "P+/nz1GcKveX+XMA8vH9MG2/pc3X+/qjXeevxhMF7x7fM38OgFXiM/MP4c+vP9o3/ivx5yhlz+cP"
    "C+QSn9n/EP68XaZn/63En6OUPcd/s44PDFk+Cn/eLvMc/2XzyxJ/PlK38HmW889NQO+v8OdOlcZX"
    "8g9qGY74pD4bsnwU/hydDuUtT+Mr+Qfz57OOXwxZPgp/jnaH4r9pfCX/oObhyJ+sTxqyfBT+fOzn"
    "z1GcKvWP+XNM0OP7a8hy2SV5X3+U61+WvxJ/PjJ/jgGqxGf8Q/jzdpme9/dEwbvrM/Pns3wfEzty"
    "8mSNwp87VZq/0vyD+fM5riy/UOvUf4U/d6o0vtL8g/nzWb7fORqyfBT+3KnS+ErzD2otPs/xy6HI"
    "n5l/CH/uVGl8pfnH3Rv8+n7YPEsfXtQ68/yFWQDe3+7zuyhOpfpC61dzXBlF/sz+eWx7j/j6/eNE"
    "wfvfX9o/xw2W+mLmH7ELDOLr948Sfz4yf44bLPGZ9Svhz9tleupfiT9HKaPxn3y/swlo/CL8uVNl"
    "70eJPx+ZP5/l+5hNQOcPhD93qjS+0vyDuo/j9sr4wJDlo/DnqIjd45dSB/KR+fNZ+J4moPwJf+5U"
    "af5K/kF9yOdZ+J7RkOWj8OdOlcZX8g/mz2fhe0ZDlsspj7dTpfGV/IP581n4mdGQ5XLKA/H1+0eJ"
    "Px9vcPw+Pz5Ll8sm4OdPzl/1dyYfS/z5pf6c352F72kCqn/CnztVen9L8w9qUI73I/J5oyHL5ZQH"
    "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"
    "a/1lXLlQ/zPfP5Dfd1Vt+0X+UfLnOoYM+/9MsnxDfn+7f/75dkbBb79flfy59I35xvflhvkH8vuu"
    "qtt/FeXP1dW/1q+kD+uTJn++Ib9/XebbZVp9kX+U/Ln0YX+dSZZjl8dfPTFwmVZf5B8lfy592B9m"
    "kuUb8vvaN4O3nFZf5B8lfy59Yz5PzwL9F/l9V9Xqi/yj5M+lD98/TLJ8Q35/M1Wtvsg/Sv5cxwhi"
    "fDH58w35fT0x9/tf5B8lfy59GF9M/nxDfl9PzP3+F80/Sv5c+ji+GP9Afl9PzP32i/yjnH8uffj+"
    "YU42xy4tjS/38x9R/lxd/ct/pY/jn5l/IL9/XeZ7/1X3fET5c3X14h98fzH5c+zS+ntd5o5/RPlz"
    "dfXafhj/zPnn2KUlfff9I8qfbyV/rvuL8c+cbI5dWtJ33z+i88/V1Wv7DStTf66Ckn9Dft9Vtf0v"
    "8o+SP9cxqhifTbIcu7TUfvxK0uqL/KPkz6UP47NJlmOXlvTd94/o/HN19fL8Mj9okuXYpSV99/0j"
    "Ov9cXb30P/Dlr4KysxT5fVfV3t/IP0r+XPf3d1bzPh9COxbhrNilpfa77x9nFPz2/KPkz6UP/mGS"
    "5dilJX2384PqvPoH39X3rr7W/6RvfH++Cr6dAbu0/rqq5v6q80b6qn+M5N8/78vV+Rt2aUnfbf/Q"
    "FsNI33d+UO03js/vy9X1e+zSkr7b/qHOG+mr/jF+OVD7cf6xI7/vqtr7m/iHunoZ/8YvB9JHZ9hH"
    "yp3a77Z/qPNG7fce+N/rL8ITju/P78sN/Q/5fVfVtl8y/1BXr+03vj9fBeX5RX7fVbX6kvmHunrx"
    "j/HLge4vZxY78vuuqtWX+Ie6em2/cXy+Cmr7jfufXVWrL/n+oa5e24/jM51hR37/usyN+cce5c/f"
    "1b/+gfzbVVDbbzw/3lV17Rflz/eSP9fzO77fXwXl/QX5fVfV6ov8o5x/Lrzo+P6sZ4HvL8jvu6pW"
    "X+QfJX8uvCj6n0mWYxft391UNfkydd5kfC75c+kb55fvyw3+i/PjXVWrL/KPkj+XPvY/ziywy1ft"
    "x6pWX+QfJX8uPCv7H2cW2OUrfaxq9UX+UfLn0jfO33aTP8cuX+mjy7T6Iv8o+XPpw/uBSZZjl6/0"
    "cf7R6ov8o5x/Ln14PzD58x35/d1Udfqi/Lm6+rf/TuATXgXFP5Dft1WeT6POm4wvJX8u/C7eD0z+"
    "fEd+//2jw1tipy/yj5I/F34X47M52Ry7pP/qiaHLdPoi/yj5c+F38fya/Dl2SUsfZymdv0Xnn6ur"
    "l/6H729XQe1/4/4wV9Xqi/yj5M/Vfnh+Tf4cu6TVfrfXr9R5o+ejzD8m7A97X27wX+T3XVXbfpF/"
    "lPy52o/Pr5l/IL+vJ+bsJnfen6Pzz9XVa//j82vWr5Dfvy5zY/1eW/yj+1vmHxO+X74vN4xsyO+7"
    "qu7+RvlzdfXafni/MvnzHfn96zJ32i86/1yBgO/524T9a1dBmX8gv++q2vaL/KPkz18Tvl8qMUBn"
    "QH7fVbX6Iv8o+XPpw/uVyZ9jF/df5QpuP7/R+ecKBJT+h++XV0Hxj3EXt/TdX786A+O313dL/lzt"
    "N66P61lAy2AXt/Td948zCn5fX/UPfF9VooH9D/l9V9X2v8g/Sv5c7Yf5pcmfY5e52u++f5yB8fvt"
    "V/0D3y/1LJj2w/rV/fPPFUFI/KPkz9V+WB83+XPsMlf73f/+EeXP1dXL84vvl1dBeX6R33dVXf+L"
    "zj/fS/78NeH75VVQ/AP5fVfV6ov8o+TPpQ/js0uWI7+vJwa9tNUX+UfJn0sfxj+TP9+R31cu47Z/"
    "ROefq6vX/of3P5M/xy74v9dlvntps79TEYnk+S35c7Ufxj+TP8cueOmjf7T6ovlHyZ9LH97/TP4c"
    "u+Cl7/b+XUUkovYr3z8mfh80yXLsgpc++kfbftH6Vcmf6/gZrP+ZZDl2wUsfXabVF/lHOf9c+ji+"
    "mO8fyO/ricHz2+mL8ufq6uX5xfmNV0HxD+T3XVWrL1q/KvlztR/GP5Msxy74v3pi7rdf5B8lfy59"
    "mJ+b/PmO/L6eGPhH236Rf5T8ufRhfDb58x3nx+uJud9+0fePkj+XPozPJn++Ix+v3Mj99ov8o+TP"
    "pQ/js8mf78jHKzdyv/0i/yj5c+nD+6nJn+/Ix+uJud9+kX+U/LmO38L6qcmf7zg/Xk/M/faL/KPk"
    "z6UP47NJlu/Ix+uJud9+kX+U/Ln0Yf3UnH++4/x4PTG32y/Kn6urF/8Ykyd/roLiH8jHu6pu/DsD"
    "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"
    "dC7lWVK+Duf17QMaxqwrPehJ5+6C7OWW4o+2TDjcy2OHQMWBcWjJX+lHgFl1U4frL05jHzZ97zvv"
    "An6oaE0O3NydJ1M8jT/Qih1EfLb6k90r00OkeBq/t43YX9jrhnbmfQuXN3zRQbMU/3O9Wcbb6zxw"
    "Vt5m5YSXNHLiaLN1ovBqs93msRd4V//Onlc/8bjqX4PQlPxw3XJ4gunxsOMRbyddimfCQL+/LIH2"
    "nHscLLx3ke85+aXnO+GCrJzV4jJy8sgPtotwcx3l0Yx79MJHmOf6/vCcs+SjtWGCciZPsTpFaK6F"
    "IIH4xCHcUyTc6amd/QcAAP//AwBQSwMEFAAGAAgAAAAhAFrL1YTnPgAA0mgBABQAAAB4bC9zaGFy"
    "ZWRTdHJpbmdzLnhtbIx9yXbbSJTluuuc/gcf15rlmCNQJzPrEAABJEjC4DzsbI0pS0pZUnrIVX9B"
    "f2R/ST9SHgi8S4NLXV7deO/FPOK3//lyd/vq08Xj019/3//+Wv6XeP3q4v7s7/O/7q9+f72YZ73w"
    "+tXT87v783e3f99f/P7668XT6//543//x29PT8+v6H/vn35/ff38/PDfb948nV1f3L17+q+/Hy7u"
    "6ZfLvx/v3j3Tn49Xb54eHi/enT9dX1w8392+UUK4N3fv/rp//ers73/un39/7SLpX7/65/6vj/9c"
    "JC+QNta9/uO3p7/++O35j/7T08Xzq+qfu/cXj7+9ef7jtzc7/OW32cXjX+9uj/z48o/zrw8X7X8b"
    "vXt4/vuhjaYXTx8APP77/V+3TGL+7v3txTOz5+zx4uK+jS7qGTCcAt9Ghy5SWuieDZGM2j+Wq+XI"
    "yLINz+fSGON9JNAvVgUjbPsXIUKhk6BYBAaj0ZtkpKcZT2dhIiN7XgWvelZPenLjR+3/Tyqxp+1Z"
    "RJLLaTdnk3VzVoNuzjw6wZ4V42SrEGmWEXWP8CBZSFdjy+JMXm+MiiIvnQzWlHFapyy/hyKzxjjj"
    "nQhWh/54HU7gMJ1WWiruZ3GnTuX8CWkNQW7+9MskMu5L18lJ5+tfcqyp+9Vw08GhGG7NCfZ05QWl"
    "NWI1hufXJOm2p86746xZDGftfK/svK1ThuVsxCucXs4RvDFG+p4zMoie6dc9lY1Z67L3kGh7FpH0"
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
