r"""Creating a Transaction: the one door, the timestamp, the sheet.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import base64
import io
import os
import sqlite3
from datetime import datetime, timedelta

from server_checks.stage import (M, R, SRC_ALL, SRC_TXN_ALL, _admin,
                                 _blank_lookup, _owners_of, _stub_lookup, bad,
                                 eq, fresh_db, head, ok, stage_name, txn)



def check_one_door_creates_a_transaction():
    """Every creation goes through _create_transaction.

    This is the ticket's real risk. The Server GUI gaining its own INSERT is
    how rule 6 comes to hold at the endpoint and quietly not in the window an
    admin uses, and the window is exactly where somebody would reach for a way
    around a sheet that is missing an asset. The archive importer is the one
    other writer, and deliberately so: it restores rows that were already
    validated when they were first created.
    """
    head("one door creates a Transaction")
    eq("only two functions insert a Transaction",
       sorted(_owners_of("INSERT INTO transactions")),
       ["_create_transaction", "_import_records_xlsx"])

    tree = ast.parse(SRC_TXN_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("_create_transaction", "create_transaction",
                 "add_transaction"):
        if name not in fns:
            bad("%s is gone" % name)
            return

    seg = ast.get_source_segment(SRC_TXN_ALL, fns["create_transaction"])
    if "_create_transaction(" not in seg:
        bad("POST /transactions no longer calls the helper")
    else:
        ok("POST /transactions forwards to _create_transaction")

    seg = ast.get_source_segment(SRC_TXN_ALL, fns["add_transaction"])
    if "_create_transaction(" not in seg:
        bad("the Add Transaction dialog no longer calls the helper")
    else:
        ok("Add Transaction forwards to _create_transaction")


def check_the_endpoint_ignores_a_supplied_timestamp():
    """POST /transactions must not read a timestamp from the body.

    The endpoint is unauthenticated on purpose (ADR-0002): an engineer confirms
    from a laptop nobody has given a password to. A caller who could set the
    timestamp could therefore rewrite the history of the store from anywhere on
    the network, and backdating an entry out of the 24h Auto-Accept window
    would confirm it without asking anybody. Backdating belongs behind the
    admin password, which is why the helper takes it as a parameter rather than
    reading it out of `data`.
    """
    head("the endpoint ignores a supplied timestamp")
    db = fresh_db()
    _blank_lookup()
    c = M.app.test_client()

    r = c.post("/transactions", json={
        "team_member": "Brian Dawson", "direction": "Out Store",
        "asset_number": "TS-1", "timestamp": "2001-01-01T00:00:00"})
    eq("the submission is accepted", r.status_code, 201)
    row = txn(db, r.get_json()["id"])
    if row["timestamp"].startswith("2001-01-01"):
        bad("the body's timestamp was stored - anyone on the network can "
            "rewrite history")
    else:
        ok("the stored timestamp is the server's own: %s" % row["timestamp"])
    eq("and it is now, to the day", row["timestamp"][:10],
       datetime.now().isoformat()[:10])

    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    # Unparsed rather than read as text: the comment above the call says the
    # word "timestamp" several times, and it is the code that matters.
    if "timestamp" in ast.unparse(fns["create_transaction"]):
        bad("the endpoint's code mentions a timestamp - it must not pass one")
    else:
        ok("the endpoint passes no timestamp at all")


def check_a_backdated_transaction_is_stored_as_given():
    """A movement made while the server was down still gets recorded.

    The gap: only the Storekeeper's client can create a Transaction, and only
    at the moment of the movement, so a movement made while the server was down
    has no way in and the history is quietly incomplete.
    """
    head("a backdated Transaction")
    db = fresh_db()
    _blank_lookup()
    back = (datetime.now() - timedelta(days=3)).replace(
        microsecond=0).isoformat()

    payload, status = M._create_transaction({
        "team_member": "Brian Dawson", "direction": "Out Store",
        "asset_number": "BD-1", "asset_type": "Laptop",
        "notes": "recorded after the fact",
        "storekeeper": "Admin (Server GUI)"}, timestamp=back)
    eq("it is created", status, 201)
    row = txn(db, payload["id"])
    eq("the timestamp is the one given", row["timestamp"], back)
    eq("it is Pending", (row["confirmed"], row["rejected"], row["cancelled"]),
       (0, 0, 0))
    eq("the Admin is its originator, not the Storekeeper",
       row["storekeeper"], "Admin (Server GUI)")

    # The attribution comes from the caller, so the Storekeeper's own
    # submissions must be untouched by it.
    payload, status = M._create_transaction({
        "team_member": "Brian Dawson", "direction": "In Store",
        "asset_number": "BD-2"})
    eq("an ordinary submission is created", status, 201)
    eq("and is still the Storekeeper's", txn(db, payload["id"])["storekeeper"],
       "Storekeeper User")


def check_the_lookup_sheet_lives_in_the_database():
    """The assets moved out of the workbook (024, ADR-0011).

    What has to hold on both sides of that move: the table arrives by migration
    and by init_db alike, `down()` keeps it, a first run fills it from the
    sheet that ships in the exe, and every rule that used to read the workbook
    - rule 6, GET /asset_types, GET /lookup - reads the table and answers
    exactly as it did. The workbook is still the format both directions of the
    exchange are spoken in, so what GET /lookup/file exports has to be
    something POST /lookup/upload puts back unchanged.
    """
    head("the Lookup Sheet lives in the database")
    db = fresh_db()
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(assets)")]
    conn.close()
    eq("init_db creates the table",
       cols, ["id", "asset_number", "serial_number", "asset_type",
              "asset_model", "created_at", "created_by", "updated_at"])

    mig = os.path.join(R, "migrations", "009_assets.py")
    if not os.path.exists(mig):
        bad("migrations/009_assets.py is missing")
        return
    mod = {}
    exec(compile(io.open(mig, encoding="utf-8").read(), mig, "exec"), mod)
    plain = stage_name("no_assets_", ".db")
    conn = sqlite3.connect(plain)
    mod["up"](conn)
    conn.commit()
    got = [r[1] for r in conn.execute("PRAGMA table_info(assets)")]
    eq("  and so does migration 009, identically", got, cols)
    conn.execute("INSERT INTO assets(asset_number, asset_type, created_at)"
                 " VALUES ('KEEP-1', 'Laptop', '2026-01-01')")
    conn.commit()
    mod["down"](conn)
    conn.commit()
    eq("  down() keeps the table and every asset in it",
       conn.execute("SELECT asset_number FROM assets").fetchall(),
       [("KEEP-1",)])
    conn.close()

    # A first run reads the Lookup Sheet in from the sheet. The staged sheet is
    # unreadable for every other check here, so this one writes a real
    # workbook, which is also what an install upgrading from 023 has beside it.
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Asset Number", "Serial Number", "Asset Type", "Asset Model"])
    ws.append(["SEED-1", "SS-1", "Laptop", "Latitude 5540"])
    ws.append(["SEED-2", "SS-2", "Screen", "N/A"])
    ws.append(["", "", "Laptop", "no identifier - dropped"])
    wb.save(M.LOOKUP_PATH)
    try:
        seeded = fresh_db()
        eq("a first run fills the Lookup Sheet from asset_lookup.xlsx",
           sorted(a["asset_number"] for a in M._load_assets()),
           ["SEED-1", "SEED-2"])
        eq("  N/A is not a model",
           M._load_lookup_table()["seed-2"]["asset_model"], "")
        conn = sqlite3.connect(seeded)
        eq("  and it is recorded as having come from the sheet",
           conn.execute("SELECT DISTINCT created_by FROM assets").fetchall(),
           [("asset_lookup.xlsx",)])
        said = conn.execute("SELECT detail FROM system_log WHERE"
                            " event='assets.seeded'").fetchall()
        conn.close()
        eq("  the System Log says so once", len(said), 1)

        # Seeding is once, not on every boot: an Admin who removed an asset
        # must not find it back after a restart.
        M._delete_asset(M._load_assets()[0]["id"])
        M.init_db()
        eq("  a later start does not re-seed over the Lookup Sheet",
           sorted(a["asset_number"] for a in M._load_assets()), ["SEED-2"])
    finally:
        with io.open(M.LOOKUP_PATH, "wb") as f:
            f.write(b"")

    db = fresh_db()
    _stub_lookup([("2100", "SN-100", "Screen", "Dell U2419H"),
                  ("2200", "SN-200", "Laptop", "")])
    eq("GET /asset_types answers off the table",
       M._lookup_asset_types(), ["Laptop", "Screen"])
    c = M.app.test_client()
    eq("GET /lookup answers off it too, on either identifier",
       [c.get("/lookup?q=%s" % q).get_json().get("asset_number")
        for q in ("2100", "SN-100")], ["2100", "2100"])
    r = c.post("/transactions", json={"team_member": "Brian Dawson",
                                      "direction": "Out Store",
                                      "asset_number": "NOT-HERE"})
    eq("rule 6 refuses an asset the table does not hold",
       (r.status_code, r.get_json().get("code")), (400, "not_in_lookup"))

    # The workbook is still the interchange format, in both directions.
    r = c.get("/lookup/file")
    eq("GET /lookup/file exports the table", r.status_code, 200)
    _admin()
    up = c.post("/lookup/upload",
                json={"password": "admin",
                      "file_data": base64.b64encode(r.data).decode()})
    eq("  and the upload door takes its own export back",
       (up.status_code, up.get_json().get("assets_loaded")), (200, 2))
    eq("  with every asset unchanged",
       sorted((a["asset_number"], a["serial_number"], a["asset_type"],
               a["asset_model"]) for a in M._load_assets()),
       [("2100", "SN-100", "Screen", "Dell U2419H"),
        ("2200", "SN-200", "Laptop", "")])
    eq("  and the ids reissued, the Lookup Sheet having been replaced",
       len({a["id"] for a in M._load_assets()}), 2)

    # One write is one row. Rewriting the whole sheet to correct one asset
    # is the shape 024 exists to remove.
    ids = {a["asset_number"]: a["id"] for a in M._load_assets()}
    M._save_asset("2100", "SN-100", "Screen", "U2419H",
                  asset_id=ids["2100"])
    after = {a["asset_number"]: a for a in M._load_assets()}
    eq("correcting one asset touches that row",
       after["2100"]["asset_model"], "U2419H")
    eq("  and leaves the row beside it alone, id included",
       (after["2200"]["id"], after["2200"]["asset_model"]),
       (ids["2200"], ""))
    for label, args in (("an asset with neither identifier",
                         ("", "", "Laptop")),
                        ("an asset with no type", ("2300", "", ""))):
        try:
            M._save_asset(*args)
            bad("the one writer accepted %s" % label)
        except ValueError:
            ok("the one writer refuses %s" % label)
    _blank_lookup()


# -- Origin (#282) ------------------------------------------------------------

def _log_data(db, event):
    import json
    conn = sqlite3.connect(db)
    rows = [r[0] for r in conn.execute(
        "SELECT data FROM system_log WHERE event=? ORDER BY id", (event,))]
    conn.close()
    return [json.loads(d) if d else None for d in rows]


def check_confirm_and_reject_write_a_desktop_origin():
    """Origin is decided by the route and never read from the body."""
    head("confirm and reject write origin=desktop (#282)")
    db = fresh_db()
    _blank_lookup()
    c = M.app.test_client()
    a = c.post("/transactions", json={"team_member": "Brian Dawson",
        "direction": "Out Store", "asset_number": "OR-1"}).get_json()["id"]
    b = c.post("/transactions", json={"team_member": "Brian Dawson",
        "direction": "Out Store", "asset_number": "OR-2"}).get_json()["id"]
    eq("a Pending row has no Origin", txn(db, a)["origin"], None)
    # The body names an origin; the route must not believe it.
    eq("confirm answers", c.post("/confirm/%d" % a,
       json={"origin": "tampered"}).status_code, 200)
    eq("confirm writes desktop, not the body's claim", txn(db, a)["origin"],
       "desktop")
    eq("reject answers", c.post("/reject/%d" % b,
       json={"reason": "no", "origin": "tampered"}).status_code, 200)
    eq("reject writes desktop, not the body's claim", txn(db, b)["origin"],
       "desktop")
    eq("the confirmed entry carries origin and the Engineer",
       _log_data(db, "transaction.confirmed")[-1],
       {"origin": "desktop", "engineer": "Brian Dawson"})
    eq("the rejected entry carries origin and the Engineer",
       _log_data(db, "transaction.rejected")[-1],
       {"origin": "desktop", "engineer": "Brian Dawson"})
    eq("a refused confirm leaves the Origin alone",
       (c.post("/confirm/%d" % a, json={}).status_code, txn(db, a)["origin"]),
       (409, "desktop"))


def check_an_auto_approve_creation_writes_an_auto_origin():
    head("an Auto-Approve creation writes origin=auto (#282)")
    db = fresh_db()
    _blank_lookup()
    conn = sqlite3.connect(db)
    conn.execute("UPDATE team_members SET auto_approve=1 WHERE name=?",
                 ("Brian Dawson",))
    conn.commit()
    conn.close()
    c = M.app.test_client()
    auto = c.post("/transactions", json={"team_member": "Brian Dawson",
        "direction": "Out Store", "asset_number": "OR-3",
        "origin": "tampered"}).get_json()["id"]
    plain = c.post("/transactions", json={"team_member": "Carol Evans",
        "direction": "Out Store", "asset_number": "OR-4",
        "origin": "tampered"}).get_json()["id"]
    eq("an Auto-Approve row is auto, whatever the body said",
       txn(db, auto)["origin"], "auto")
    eq("an ordinary Pending row has none, whatever the body said",
       txn(db, plain)["origin"], None)


def check_origin_is_returned_by_pending_and_transactions():
    head("origin appears in /pending and /transactions (#282)")
    db = fresh_db()
    _blank_lookup()
    c = M.app.test_client()
    a = c.post("/transactions", json={"team_member": "Brian Dawson",
        "direction": "Out Store", "asset_number": "OR-5"}).get_json()["id"]
    b = c.post("/transactions", json={"team_member": "Brian Dawson",
        "direction": "Out Store", "asset_number": "OR-6"}).get_json()["id"]
    pend = c.get("/pending/Brian Dawson").get_json()
    eq("every pending row has the key",
       [("origin" in r) for r in pend], [True, True])
    c.post("/confirm/%d" % a)
    rows = {r["id"]: r for r in c.get("/transactions").get_json()}
    eq("/transactions returns it for a decided row", rows[a]["origin"], "desktop")
    eq("  and null for a Pending one", rows[b]["origin"], None)
    eq("/export returns it too",
       {r["id"]: r["origin"] for r in c.get("/export").get_json()}[a], "desktop")


def check_migration_017_backfills_auto_only_where_auto_approved():
    head("migration 017 (#282)")
    path = os.path.join(R, "migrations", "017_transaction_origin.py")
    if not os.path.exists(path):
        bad("migrations/017_transaction_origin.py is missing")
        return
    msrc = io.open(path, encoding="utf-8").read()
    mod = {}
    exec(compile(msrc, path, "exec"), mod)
    old = stage_name("pre_282_", ".db")
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asset_type TEXT NOT NULL,
        team_member TEXT NOT NULL, direction TEXT NOT NULL,
        timestamp TEXT NOT NULL, confirmed INTEGER DEFAULT 0,
        auto_approved INTEGER DEFAULT 0)""")
    for auto_approved, confirmed in ((1, 1), (0, 1), (0, 0)):
        conn.execute("INSERT INTO transactions (asset_type, team_member,"
                     " direction, timestamp, confirmed, auto_approved)"
                     " VALUES ('Laptop','Brian Dawson','Out Store','t',?,?)",
                     (confirmed, auto_approved))
    conn.commit()
    mod["up"](conn)
    mod["up"](conn)
    got = [r[0] for r in conn.execute(
        "SELECT origin FROM transactions ORDER BY id")]
    eq("auto where auto_approved, NULL otherwise (never desktop)", got,
       ["auto", None, None])
    mod["down"](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    eq("down() keeps the column", "origin" in cols, True)
    conn.close()
    # init_db() alone reaches the same answer on an old database.
    old2 = stage_name("pre_282b_", ".db")
    conn = sqlite3.connect(old2)
    conn.execute("""CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asset_type TEXT NOT NULL,
        team_member TEXT NOT NULL, direction TEXT NOT NULL,
        timestamp TEXT NOT NULL, confirmed INTEGER DEFAULT 0)""")
    conn.execute("INSERT INTO transactions (asset_type, team_member,"
                 " direction, timestamp, confirmed) VALUES"
                 " ('Laptop','Brian Dawson','Out Store','t',1)")
    conn.commit()
    conn.close()
    M.DB_PATH = old2
    M.init_db()
    conn = sqlite3.connect(old2)
    eq("init_db() adds the column and leaves an old row NULL",
       [r[0] for r in conn.execute("SELECT origin FROM transactions")], [None])
    conn.close()
