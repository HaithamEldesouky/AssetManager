r"""Cancellation, the admin path, and the storekeeper switch.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import os
import sqlite3
from datetime import datetime, timedelta

from server_checks.stage import (M, R, REG_SRC, SRC_ALL, SRC_TXN_ALL, STAGE,
                                 _admin, _blank_lookup, _caps, add_txn, bad,
                                 eq, fresh_db, head, log_rows, ok,
                                 read_server_cfg, skip, stored_form, txn,
                                 write_server_cfg)



def check_cancel_columns_are_added_both_ways():
    """A fresh database and an upgraded one must end up identical.

    init_db()'s idempotent ALTER TABLE is what makes migration 001 a no-op, and
    the same has to hold for 003: a server started without ever running migrate
    still needs the columns, or every predicate below is a SQL error rather than
    a wrong answer.
    """
    head("the cancel columns")
    db = fresh_db()
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    conn.close()
    for name in ("cancelled", "cancelled_at", "cancelled_by", "cancel_reason"):
        if name in cols:
            ok("init_db() creates %s" % name)
        else:
            bad("init_db() does not create %s" % name)

    # An old database - the table as it was before this ticket - upgraded by
    # init_db() alone.
    old = os.path.join(STAGE, "old_schema.db")
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asset_type TEXT NOT NULL,
        serial_number TEXT DEFAULT '', asset_number TEXT DEFAULT '',
        team_member TEXT NOT NULL, direction TEXT NOT NULL,
        timestamp TEXT NOT NULL, confirmed INTEGER DEFAULT 0,
        rejected INTEGER DEFAULT 0, confirmed_at TEXT DEFAULT '',
        rejection_reason TEXT DEFAULT '', notes TEXT DEFAULT '',
        storekeeper TEXT DEFAULT 'Storekeeper User')""")
    conn.execute("INSERT INTO transactions (asset_type, team_member, direction,"
                 " timestamp) VALUES ('Laptop','Brian Dawson','Out Store',?)",
                 (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    M.DB_PATH = old
    M.init_db()
    conn = sqlite3.connect(old)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    n = conn.execute("SELECT COUNT(*) FROM transactions WHERE cancelled=0").fetchone()[0]
    conn.close()
    eq("an upgraded database has all four columns",
       sorted(c for c in cols if c.startswith("cancel")),
       ["cancel_reason", "cancelled", "cancelled_at", "cancelled_by"])
    eq("an existing row reads as not cancelled", n, 1)


def check_migration_003_keeps_its_columns_on_the_way_down():
    """A downgrade never drops a column.

    Dropping these four would un-cancel every retracted Transaction at once:
    each would read as Pending again, and Auto-Accept would confirm the lot
    within a day. The rule is in CLAUDE.md; this is the check that it holds for
    the migration that just added them.
    """
    head("migration 003")
    path = os.path.join(R, "migrations", "003_transaction_cancel.py")
    if not os.path.exists(path):
        bad("migrations/003_transaction_cancel.py is missing")
        return
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    for want in ("up", "down"):
        if want in names:
            ok("003 defines %s()" % want)
        else:
            bad("003 does not define %s()" % want)
    down = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "down"][0]
    body = [st for st in down.body if not isinstance(st, ast.Expr)]
    if body and all(isinstance(st, ast.Return) and st.value is None
                    for st in body):
        ok("003's down() is a no-op")
    else:
        bad("003's down() does something - a downgrade never drops a column")
    up = src.upper()
    if "DROP COLUMN" in up or "DROP TABLE" in up:
        bad("003 drops something")
    else:
        ok("003 drops nothing")

    # and it applies for real, twice, without complaining
    db = fresh_db()
    mod = {}
    exec(compile(src, path, "exec"), mod)
    conn = sqlite3.connect(db)
    mod["up"](conn)
    mod["up"](conn)
    mod["down"](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    conn.close()
    eq("up() twice then down() still leaves four cancel columns",
       len([c for c in cols if c.startswith("cancel")]), 4)


def check_cancel_a_pending_transaction():
    """The happy path, and what the row carries afterwards.

    No password: correcting a mis-scan has to be as quick as making one, and
    ADR-0002 already leaves the transaction endpoints unauthenticated.
    """
    head("cancelling a pending Transaction")
    db = fresh_db()
    tid = add_txn(db, asset_number="A-1")
    c = M.app.test_client()

    r = c.post("/transactions/cancel",
               json={"id": tid, "reason": "scanned the wrong barcode"})
    eq("a pending Transaction is cancelled", r.status_code, 200)
    eq("no password was asked for", r.get_json().get("status"), "cancelled")

    row = txn(db, tid)
    eq("the row survives", row["id"], tid)
    eq("it is marked cancelled", row["cancelled"], 1)
    eq("it carries why", row["cancel_reason"], "scanned the wrong barcode")
    eq("it carries who, falling back to the row's storekeeper",
       row["cancelled_by"], "Storekeeper User")
    if row["cancelled_at"]:
        ok("it carries when: %s" % row["cancelled_at"])
    else:
        bad("cancelled_at was not set")
    eq("confirmed was not touched", row["confirmed"], 0)
    eq("rejected was not touched", row["rejected"], 0)

    r = c.post("/transactions/cancel",
               json={"id": add_txn(db, asset_number="A-2"),
                     "reason": "wrong engineer",
                     "cancelled_by": "Admin (Server GUI)"})
    eq("a caller may name itself", r.status_code, 200)
    eq("and that name is stored", r.get_json().get("cancelled_by"),
       "Admin (Server GUI)")


def check_cancel_refusals():
    """Every refusal, each with the code the API table documents."""
    head("cancellation refusals")
    db = fresh_db()
    c = M.app.test_client()

    def code(payload):
        r = c.post("/transactions/cancel", json=payload)
        return r.status_code, (r.get_json() or {}).get("code")

    tid = add_txn(db, asset_number="A-10")
    eq("no reason is refused", code({"id": tid}), (400, "reason_required"))
    eq("a blank reason is refused", code({"id": tid, "reason": "   "}),
       (400, "reason_required"))
    eq("a missing id is refused", code({"reason": "x"}), (400, "bad_id"))
    eq("a non-numeric id is refused", code({"id": "abc", "reason": "x"}),
       (400, "bad_id"))
    eq("an unknown id is refused", code({"id": 999999, "reason": "x"}),
       (404, "not_found"))

    eq("a first cancel is accepted", code({"id": tid, "reason": "mis-scan"}),
       (200, None))
    eq("cancelling it twice is refused", code({"id": tid, "reason": "again"}),
       (409, "already_cancelled"))

    rej = add_txn(db, asset_number="A-11", rejected=1,
                  rejection_reason="not mine")
    eq("a rejected Transaction is refused", code({"id": rej, "reason": "x"}),
       (409, "rejected"))

    con = add_txn(db, asset_number="A-12", confirmed=1,
                  confirmed_at=datetime.now().isoformat())
    eq("a confirmed Transaction is refused without the admin path",
       code({"id": con, "reason": "x"}), (409, "confirmed"))

    # the newest-per-asset rule, on one asset with two Transactions
    # Both Pending, inserted directly: the API's own duplicate guard would
    # refuse the second, which is the point of that guard and not of this one.
    old = add_txn(db, asset_number="A-20",
                  timestamp=(datetime.now() - timedelta(hours=5)).isoformat())
    new = add_txn(db, asset_number="A-20", direction="In Store",
                  timestamp=datetime.now().isoformat())
    st, cd = code({"id": old, "reason": "wrong"})
    eq("an older Transaction for the asset is refused", (st, cd),
       (409, "not_newest"))
    r = c.post("/transactions/cancel", json={"id": old, "reason": "wrong"})
    eq("the refusal names which one to cancel first",
       r.get_json().get("newest_id"), new)
    eq("the newest one is accepted", code({"id": new, "reason": "mis-scan"}),
       (200, None))
    # now that the newest is cancelled it no longer counts as newest, so the
    # older one becomes cancellable - the history unwinds one row at a time,
    # each with its own reason.
    eq("cancelling the newest makes the previous one the newest",
       code({"id": old, "reason": "the whole pair was a mis-scan"}),
       (200, None))

    # serial-only assets are keyed on serial_number, same as Out Now
    s_old = add_txn(db, serial_number="SN-1",
                    timestamp=(datetime.now() - timedelta(hours=2)).isoformat())
    s_new = add_txn(db, serial_number="SN-1", direction="In Store")
    eq("the rule keys on serial number when there is no asset number",
       code({"id": s_old, "reason": "x"}), (409, "not_newest"))
    eq("and accepts the newest of those", code({"id": s_new, "reason": "x"}),
       (200, None))


def check_cancelled_is_excluded_everywhere():
    """Every predicate that means Pending or Confirmed.

    Eight of them when this landed. Auto-Accept is the one that matters: a
    Cancelled Transaction left in that query confirms itself twenty-four hours
    later, and nothing is watching by then.
    """
    head("Cancelled is excluded from Pending, Confirmed and Out Now")
    db = fresh_db()
    c = M.app.test_client()

    pend = add_txn(db, asset_number="P-1", team_member="Brian Dawson")
    conf = add_txn(db, asset_number="C-1", team_member="Brian Dawson",
                   confirmed=1, confirmed_at=datetime.now().isoformat())
    stale = add_txn(db, asset_number="S-1", team_member="Brian Dawson",
                    timestamp=(datetime.now() - timedelta(hours=30)).isoformat())

    before = c.get("/stats").get_json()
    eq("pending before", before["pending"], 2)
    eq("confirmed before", before["confirmed"], 1)
    eq("out_now before", before["out_now"], 1)
    eq("the engineer's pending list before",
       len(c.get("/pending/Brian Dawson").get_json()), 2)

    for tid in (pend, conf, stale):
        conn = sqlite3.connect(db)
        conn.execute("UPDATE transactions SET cancelled=1, cancel_reason='x' "
                     "WHERE id=?", (tid,))
        conn.commit()
        conn.close()

    after = c.get("/stats").get_json()
    eq("total still counts every row", after["total"], 3)
    eq("Cancelled is not Pending", after["pending"], 0)
    eq("Cancelled is not Confirmed", after["confirmed"], 0)
    eq("Cancelled is not Out Now", after["out_now"], 0)
    eq("Cancelled never reaches a Notifier",
       c.get("/pending/Brian Dawson").get_json(), [])

    recent, held, oldest, _sig = M._gui_snapshot(20)
    eq("the Server GUI feed still shows all three", len(recent), 3)
    eq("the GUI's holdings ignore Cancelled", held, [])
    eq("the GUI's oldest-pending ignores Cancelled", len(oldest), 0)

    eq("Auto-Accept skips a Cancelled Transaction 30h old",
       M._auto_accept_pass(), 0)
    eq("and it is still not confirmed", txn(db, stale)["confirmed"], 0)

    # the control: the same row, not cancelled, is auto-accepted
    conn = sqlite3.connect(db)
    conn.execute("UPDATE transactions SET cancelled=0 WHERE id=?", (stale,))
    conn.commit()
    conn.close()
    eq("a Pending Transaction 30h old still is", M._auto_accept_pass(), 1)


def check_confirm_and_reject_only_move_a_pending_transaction():
    """Neither endpoint may write over a Transaction that is already resolved.

    The popup queue produces this on its own, with nobody doing anything
    strange: a Transaction is sitting in an engineer's queue, the Storekeeper
    cancels it, and the engineer clicks Confirm on the popup still on screen.
    Before the guard that left confirmed=1 beside cancelled=1, with confirmed_at
    overwritten so the row no longer said when it was retracted.

    The Rejected case is the one that is counted rather than merely untidy:
    /stats computes Confirmed as confirmed=1 AND cancelled=0, which excludes
    cancelled and not rejected, so a rejected-then-confirmed row inflates the
    Live Statistics tile.

    GET /pending/<member> has always filtered on this same shape. These were the
    two writes that did not.
    """
    head("confirm and reject only move a Pending Transaction")
    db = fresh_db()
    c = M.app.test_client()

    tid = add_txn(db, asset_number="A-1")
    eq("a pending Transaction is confirmed",
       c.post("/confirm/%d" % tid).status_code, 200)
    r = c.post("/confirm/%d" % tid)
    eq("confirming it a second time is refused", r.status_code, 409)
    eq("and says why", r.get_json().get("code"), "not_pending")

    tid = add_txn(db, asset_number="A-2")
    c.post("/transactions/cancel", json={"id": tid, "reason": "never happened"})
    r = c.post("/confirm/%d" % tid)
    eq("a Cancelled Transaction cannot be confirmed", r.status_code, 409)
    row = txn(db, tid)
    eq("and the row is untouched", row["confirmed"], 0)
    eq("still cancelled", row["cancelled"], 1)
    if not row["confirmed_at"]:
        ok("confirmed_at was not overwritten")
    else:
        bad("confirmed_at was overwritten: %s" % row["confirmed_at"])

    tid = add_txn(db, asset_number="A-3")
    c.post("/transactions/cancel", json={"id": tid, "reason": "never happened"})
    r = c.post("/reject/%d" % tid, json={"reason": "not mine"})
    eq("a Cancelled Transaction cannot be rejected either", r.status_code, 409)
    eq("and the row is untouched", txn(db, tid)["rejected"], 0)

    tid = add_txn(db, asset_number="A-4")
    c.post("/reject/%d" % tid, json={"reason": "not mine"})
    r = c.post("/confirm/%d" % tid)
    eq("a Rejected Transaction cannot be confirmed", r.status_code, 409)
    eq("and the row is untouched", txn(db, tid)["confirmed"], 0)
    eq("a rejected row is not counted as Confirmed",
       c.get("/stats").get_json()["confirmed"], 1)


def check_a_cancelled_transaction_does_not_block_a_new_one():
    """The duplicate-pending guard.

    The point of cancelling a mis-scan is to record the right Transaction
    immediately afterwards. A Cancelled row still counting as pending would make
    that impossible, and 409 is the least informative way to find out.
    """
    head("the duplicate-pending guard")
    db = fresh_db()
    _blank_lookup()
    c = M.app.test_client()

    body = {"asset_number": "DUP-1", "asset_type": "Laptop",
            "team_member": "Brian Dawson", "direction": "Out Store"}
    r = c.post("/transactions", json=body)
    eq("a first submission is accepted", r.status_code, 201)
    r = c.post("/transactions", json=body)
    eq("a second while the first is pending is refused", r.status_code, 409)

    conn = sqlite3.connect(db)
    tid = conn.execute("SELECT MAX(id) FROM transactions").fetchone()[0]
    conn.close()
    r = c.post("/transactions/cancel", json={"id": tid, "reason": "mis-scan"})
    eq("the pending one is cancelled", r.status_code, 200)

    r = c.post("/transactions", json=body)
    eq("a fresh submission for the same asset is now accepted",
       r.status_code, 201)


def check_the_list_endpoints_default_to_hiding_cancelled():
    """/export and /transactions keep today's shape unless asked.

    Every client works out Pending as neither-confirmed-nor-rejected from these
    two, so an un-updated Storekeeper would show a Cancelled Transaction as
    Pending for ever. The opt-in is the whole reason the default is off.
    """
    head("/export and /transactions")
    db = fresh_db()
    c = M.app.test_client()
    live = add_txn(db, asset_number="L-1", team_member="Brian Dawson")
    gone = add_txn(db, asset_number="G-1", team_member="Brian Dawson",
                   cancelled=1, cancel_reason="mis-scan",
                   cancelled_at=datetime.now().isoformat())

    ids = [r["id"] for r in c.get("/export").get_json()]
    eq("/export omits Cancelled by default", ids, [live])
    for flag in ("1", "true", "yes"):
        ids = [r["id"] for r in
               c.get("/export?include_cancelled=%s" % flag).get_json()]
        eq("/export?include_cancelled=%s includes it" % flag,
           sorted(ids), sorted([live, gone]))
    ids = [r["id"] for r in c.get("/export?include_cancelled=0").get_json()]
    eq("/export?include_cancelled=0 still omits it", ids, [live])

    rows = c.get("/export?include_cancelled=1").get_json()
    keys = set(rows[0].keys())
    for k in ("cancelled", "cancelled_at", "cancelled_by", "cancel_reason"):
        if k in keys:
            ok("/export exposes %s" % k)
        else:
            bad("/export does not expose %s" % k)

    ids = [r["id"] for r in c.get("/transactions").get_json()]
    eq("/transactions omits Cancelled by default", ids, [live])
    ids = [r["id"] for r in
           c.get("/transactions?member=Brian Dawson").get_json()]
    eq("and so does the per-member filter", ids, [live])
    ids = [r["id"] for r in
           c.get("/transactions?member=Brian Dawson&include_cancelled=1")
           .get_json()]
    eq("both filters compose", sorted(ids), sorted([live, gone]))


def check_the_feed_repaints_on_a_cancellation():
    """_gui_snapshot's change signature.

    Cancelling moves nothing else in that tuple - the row count, the max id and
    both other sums stay exactly where they were - so without SUM(cancelled) the
    GUI would go on showing the Transaction as pending until something unrelated
    happened.
    """
    head("the feed's change signature")
    db = fresh_db()
    tid = add_txn(db, asset_number="F-1")
    before = M._gui_snapshot(20)[3]
    conn = sqlite3.connect(db)
    conn.execute("UPDATE transactions SET cancelled=1, cancel_reason='x' "
                 "WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    after = M._gui_snapshot(20)[3]
    if after != before:
        ok("the signature moves: %r -> %r" % (before, after))
    else:
        bad("the signature did not move - the feed would not repaint: %r"
            % (before,))
    eq("the row is shown as cancelled",
       M._status_of(txn(db, tid)), "cancelled")


def check_manage_records_opens_a_cancel():
    """#169: the Manage Transaction History capability password may Cancel.

    It covered Delete and Correct and not Cancel, because Cancel is enforced
    inside `_cancel_transaction`, which the unauthenticated endpoint shares -
    so the delegate who had just deleted a row outright had to walk to the
    console to retract one, which is the argument that put Correct on the
    network at R1. It opens what the admin password opens here: a **Confirmed**
    row, with the Storekeeper switch overridden.

    What this drives that nothing else can is the **ordering exception**
    (ADR-0015). Every other remote door refuses on the transport before the
    password is examined; this one cannot, because the admin password has been
    its own credential since ADR-0003, arrives over plain HTTP on the default
    deployment (rule 1), and nothing but examining it says which of the two
    came. So both halves are asserted from the one door: the capability
    password refused `insecure` over http with the row untouched, and the admin
    password going through over the same http exactly as it always did.
    """
    head("manage_records opens Cancel (#169)")
    HTTPS = "https://localhost"
    db = fresh_db()
    _blank_lookup()
    write_server_cfg({"host": "0.0.0.0", "port": 8081})
    _caps(manage_records="mrpw", server_cfg="cfgpw")
    c = M.app.test_client()

    def confirmed(asset):
        return add_txn(db, asset_number=asset, confirmed=1,
                       confirmed_at=datetime.now().isoformat())

    # --- the delegate, unnamed --------------------------------------------
    tid = confirmed("MR-1")
    r = c.post("/transactions/cancel", base_url=HTTPS,
               json={"id": tid, "reason": "mis-scan", "password": "mrpw"})
    eq("a Confirmed row opens on the capability password", r.status_code, 200)
    row = txn(db, tid)
    eq("  and is cancelled", row["cancelled"], 1)
    eq("  recorded against the credential rather than as the Admin",
       row["cancelled_by"],
       "Delegate: Manage Transaction History, unnamed holder (remote)")
    entries = log_rows(db)
    eq("  the System Log says the same",
       entries[-1]["event"], "transaction.cancelled")
    eq("  and names the same delegate", entries[-1]["actor"],
       "Delegate: Manage Transaction History, unnamed holder (remote)")
    eq("  with the remote use written down before it",
       entries[-2]["event"], "remote.action")

    # --- the delegate, named, and a cancelled_by that must not stick -------
    M.ADMIN_CFG["capability_holders"] = {"manage_records": "Brian Dawson"}
    tid = confirmed("MR-2")
    r = c.post("/transactions/cancel", base_url=HTTPS,
               json={"id": tid, "reason": "mis-scan", "password": "mrpw",
                     "cancelled_by": "Storekeeper User"})
    eq("the holder the Admin named is carried", r.status_code, 200)
    eq("  into the column", txn(db, tid)["cancelled_by"],
       'Delegate: Manage Transaction History held by "Brian Dawson" (remote)')
    eq("  and a cancelled_by in the body does not dress the act",
       log_rows(db)[-1]["actor"],
       'Delegate: Manage Transaction History held by "Brian Dawson" (remote)')
    M.ADMIN_CFG["capability_holders"] = {}

    # --- the switch is overridden, as it is for the admin password --------
    write_server_cfg({"host": "0.0.0.0", "port": 8081,
                      "storekeeper_can_cancel": False})
    tid = add_txn(db, asset_number="MR-3")
    r = c.post("/transactions/cancel", base_url=HTTPS,
               json={"id": tid, "reason": "mis-scan", "password": "mrpw"})
    eq("the Storekeeper switch does not apply to a delegate", r.status_code,
       200)
    write_server_cfg({"host": "0.0.0.0", "port": 8081})

    # --- the same password over plain http --------------------------------
    tid = confirmed("MR-4")
    before = len(log_rows(db))
    r = c.post("/transactions/cancel",
               json={"id": tid, "reason": "mis-scan", "password": "mrpw"})
    eq("the same password over plain http is refused", r.status_code, 403)
    eq("  and says the transport was the problem, not the credential",
       (r.get_json() or {}).get("code"), "insecure")
    eq("  the row is untouched", txn(db, tid)["cancelled"], 0)
    eq("  and the refusal is written down",
       log_rows(db)[before]["event"], "remote.refused")

    # --- the admin password over that same plain http ---------------------
    # The whole reason the gate is examined late. This is the Storekeeper's
    # Cancel pill on the default install.
    before = len(log_rows(db))
    r = c.post("/transactions/cancel",
               json={"id": tid, "reason": "mis-scan", "password": "admin"})
    eq("the admin password over plain http still cancels a Confirmed row",
       r.status_code, 200)
    eq("  as the Admin, not as a delegate", txn(db, tid)["cancelled_by"],
       "Admin")
    eq("  and is not a remote.action - it is this door's own credential",
       [e["event"] for e in log_rows(db)[before:]], ["transaction.cancelled"])

    # --- another capability's password opens nothing here -----------------
    tid = confirmed("MR-5")
    r = c.post("/transactions/cancel", base_url=HTTPS,
               json={"id": tid, "reason": "mis-scan", "password": "cfgpw"})
    eq("the Change Host / Port password does not open this door",
       r.status_code, 401)
    eq("  and nothing was cancelled", txn(db, tid)["cancelled"], 0)

    # --- the unauthenticated path is exactly as it was --------------------
    tid = add_txn(db, asset_number="MR-6")
    r = c.post("/transactions/cancel", json={"id": tid, "reason": "mis-scan"})
    eq("a Pending row still needs no password at all", r.status_code, 200)
    eq("  and is still the Storekeeper's", log_rows(db)[-1]["actor"],
       M._storekeeper_actor("Storekeeper User"))
    tid = confirmed("MR-7")
    r = c.post("/transactions/cancel", json={"id": tid, "reason": "mis-scan"})
    eq("and a Confirmed row is still refused on it", r.status_code, 409)
    eq("  naming the state rather than the credential",
       (r.get_json() or {}).get("code"), "confirmed")

    # --- a cancel is authorised once --------------------------------------
    try:
        M._cancel_transaction(confirmed("MR-8"), "twice", password="admin",
                              authorised_as="Admin (remote)")
        bad("both credentials at once was accepted")
    except ValueError:
        ok("a cancel is authorised once, not twice")


def check_one_place_writes_the_cancellation():
    """The GUI and the endpoint must not each enforce the rule.

    Only _cancel_transaction may set cancelled=1. A second writer - a GUI
    callback with its own UPDATE - is how the newest-per-asset rule comes to
    hold at the endpoint and quietly not in the window the admin actually uses.
    """
    head("one enforcement point")
    # The register as well as the API and the console: the UPDATE moved with
    # the function at #216, and the question here is still whether anything
    # *else* writes it. The `manage_records` half below stays on SRC_ALL for
    # the opposite reason - the register's own `def _cancel_transaction` sorts
    # after `def manage_records` in the joined text, so a split of that would
    # find the definition and report a caller.
    tree = ast.parse(SRC_TXN_ALL)
    owners = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and "cancelled=1" in node.value.replace(" ", ""):
            owners.append(node.lineno)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns[node.name] = (node.lineno, node.end_lineno)

    def owner_of(line):
        best = None
        for name, (a, b) in fns.items():
            if a <= line <= b and (best is None
                                   or (fns[best][1] - fns[best][0])
                                   > (b - a)):
                best = name
        return best

    writers = sorted({owner_of(ln) for ln in owners})
    eq("only _cancel_transaction writes cancelled=1", writers,
       ["_cancel_transaction"])

    if "_cancel_transaction(" in SRC_ALL.split("def manage_records", 1)[-1]:
        ok("manage_records goes through _cancel_transaction")
    else:
        bad("manage_records does not call _cancel_transaction")


def check_the_archive_carries_the_cancellation():
    """Archive-then-delete is still the only way to remove a row.

    That archive is what a purge leaves behind, so it has to carry the
    cancellation with it. And an archive written before these columns existed
    must still import: '' in an INTEGER column does not equal 0 in SQLite, so an
    un-defaulted import would produce rows that no `cancelled=0` predicate
    matches - invisible in Pending, in Out Now, and in the export.
    """
    head("the xlsx archive")
    for k in ("cancelled", "cancelled_at", "cancelled_by", "cancel_reason"):
        if k in M._ARCHIVE_COLS:
            ok("_ARCHIVE_COLS carries %s" % k)
        else:
            bad("_ARCHIVE_COLS does not carry %s" % k)

    db = fresh_db()
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        skip("openpyxl is not installed - the round-trip is not exercised")
        return

    tid = add_txn(db, asset_number="AR-1", cancelled=1,
                  cancel_reason="mis-scan", cancelled_by="Storekeeper User",
                  cancelled_at=datetime.now().isoformat())
    path = os.path.join(STAGE, "archive.xlsx")
    eq("one row is archived", M._export_records_xlsx(path, ids=[tid]), 1)

    db2 = fresh_db()
    n, refusal = M._import_records_xlsx(path)
    eq("and imported", n, 1)
    eq("with no refusal", refusal, "")
    conn = sqlite3.connect(db2)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM transactions").fetchone())
    conn.close()
    eq("the cancellation survived the round trip", row["cancelled"], 1)
    eq("so did the reason", row["cancel_reason"], "mis-scan")

    # an archive from before this ticket: no cancel columns at all
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    cols = [c for c in M._ARCHIVE_COLS if not c.startswith("cancel")]
    ws.append(cols)
    ws.append(["1", "Laptop", "", "OLD-1", "", "Brian Dawson", "Out Store",
               datetime.now().isoformat(), 0, 0, "", "", "", "Storekeeper User"])
    wb.save(path)
    db3 = fresh_db()
    n, refusal = M._import_records_xlsx(path)
    eq("an archive with no cancel columns imports", n, 1)
    eq("with no refusal", refusal, "")
    conn = sqlite3.connect(db3)
    n = conn.execute("SELECT COUNT(*) FROM transactions "
                     "WHERE cancelled=0").fetchone()[0]
    conn.close()
    eq("and the imported row matches cancelled=0", n, 1)


# ── the admin path, and the storekeeper switch ───────────────────────────────

def check_the_admin_can_cancel_a_confirmed_transaction():
    """An Auto-Approve Engineer's Transactions are Confirmed the instant they
    are recorded and are never Pending, so a mis-scan against one of them is
    unreachable without this path.

    The password is what opens it: once the Engineer has Confirmed, they and the
    Storekeeper are asserting different things about the physical world, and
    clearing that disagreement should not be one person's button.
    """
    head("cancelling a Confirmed Transaction")
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    write_server_cfg({"host": "0.0.0.0", "port": 8081})
    db = fresh_db()
    c = M.app.test_client()

    tid = add_txn(db, asset_number="CF-1", confirmed=1,
                  confirmed_at=datetime.now().isoformat())

    r = c.post("/transactions/cancel", json={"id": tid, "reason": "mis-scan"})
    eq("no password is refused", (r.status_code,
                                 (r.get_json() or {}).get("code")),
       (409, "confirmed"))
    eq("and the row is untouched", txn(db, tid)["cancelled"], 0)

    r = c.post("/transactions/cancel",
               json={"id": tid, "reason": "mis-scan", "password": "wrong"})
    eq("a wrong password is refused, not downgraded",
       (r.status_code, (r.get_json() or {}).get("code")),
       (401, "bad_password"))
    eq("still untouched", txn(db, tid)["cancelled"], 0)

    r = c.post("/transactions/cancel",
               json={"id": tid, "reason": "mis-scan", "password": ""})
    eq("an empty password is an attempt, not an absence",
       (r.status_code, (r.get_json() or {}).get("code")),
       (401, "bad_password"))

    r = c.post("/transactions/cancel",
               json={"id": tid, "reason": "mis-scan", "password": "admin"})
    eq("the admin password is accepted", r.status_code, 200)
    eq("a nameless admin is recorded as one, not as the storekeeper",
       txn(db, tid)["cancelled_by"], "Admin")
    eq("and the reason is kept", txn(db, tid)["cancel_reason"], "mis-scan")

    # the newest-per-asset rule still applies to Confirmed Transactions
    old = add_txn(db, asset_number="CF-2", confirmed=1,
                  timestamp=(datetime.now() - timedelta(hours=6)).isoformat(),
                  confirmed_at=datetime.now().isoformat())
    new = add_txn(db, asset_number="CF-2", direction="In Store", confirmed=1,
                  confirmed_at=datetime.now().isoformat())
    r = c.post("/transactions/cancel",
               json={"id": old, "reason": "x", "password": "admin"})
    eq("an older Confirmed Transaction is still refused",
       (r.status_code, r.get_json().get("code"), r.get_json().get("newest_id")),
       (409, "not_newest", new))


def check_an_auto_approved_transaction_has_a_cancel_window():
    """The one Confirmed row a caller with no password may retract (#198).

    An Auto-Approve Engineer has no Notifier and is never asked, so a
    Transaction against one is Confirmed a millisecond after the scan - which
    made the ordinary mis-scan against them slower to undo than the scan that
    made it, the exact thing the Storekeeper switch exists to prevent for every
    other Engineer.

    What has to hold is that the window opens **that** row and no other. The
    leg that matters most is the third: a Transaction an Engineer really
    answered is refused whatever the clock says, because `auto_approved` is
    written on the row when the row is written rather than read back off the
    Engineer's flag - which an Admin may tick an hour from now - or off the
    System Log, which `POST /clients/log` lets anybody on the network write.

    The setting is read from disk on every request, like the two switches
    beside it, so the last legs write the file and expect the next request to
    answer differently with no restart.
    """
    head("the auto-approve cancel window (#198)")
    db = fresh_db()
    _blank_lookup()
    _admin()
    c = M.app.test_client()

    # -- the flag is written by the one writer, from the Engineer's own --------
    conn = sqlite3.connect(db)
    conn.execute("UPDATE team_members SET auto_approve=1 WHERE name=?",
                 ("Brian Dawson",))
    conn.commit()
    conn.close()
    write_server_cfg({"storekeeper_cancel_window_mins": 10})

    r = c.post("/transactions", json={"team_member": "Brian Dawson",
                                      "direction": "Out Store",
                                      "asset_type": "Laptop",
                                      "asset_number": "AW-1"})
    eq("an auto-approved Transaction is recorded", r.status_code, 201)
    tid = (r.get_json() or {}).get("id")
    row = txn(db, tid)
    eq("  Confirmed at once, as it always was", row["confirmed"], 1)
    eq("  and the row says that is how it came to be Confirmed",
       row["auto_approved"], 1)

    r = c.post("/transactions", json={"team_member": "Carol Evans",
                                      "direction": "Out Store",
                                      "asset_type": "Laptop",
                                      "asset_number": "AW-2"})
    eq("a Transaction an Engineer will answer is not marked",
       txn(db, (r.get_json() or {}).get("id"))["auto_approved"], 0)

    # -- inside the window, no password at all --------------------------------
    r = c.post("/transactions/cancel", json={"id": tid, "reason": "mis-scan"})
    eq("inside the window it is cancelled with no password", r.status_code, 200)
    eq("  and the row is marked", txn(db, tid)["cancelled"], 1)
    ev = [e for e in log_rows(db) if e["event"] == "transaction.cancelled"]
    eq("  with one entry saying which door opened it",
       len(ev) == 1 and "auto-approve cancel window" in ev[-1]["detail"], True)

    # -- outside it, refused --------------------------------------------------
    old = add_txn(db, asset_number="AW-3", confirmed=1, auto_approved=1,
                  team_member="Brian Dawson",
                  confirmed_at=(datetime.now()
                                - timedelta(minutes=40)).isoformat())
    r = c.post("/transactions/cancel", json={"id": old, "reason": "late"})
    eq("outside the window it is refused",
       (r.status_code, (r.get_json() or {}).get("code")), (409, "confirmed"))
    eq("  and the row is untouched", txn(db, old)["cancelled"], 0)

    # -- a row an Engineer really confirmed, whatever the clock says ----------
    real = add_txn(db, asset_number="AW-4", confirmed=1, auto_approved=0,
                   team_member="Carol Evans",
                   confirmed_at=datetime.now().isoformat())
    r = c.post("/transactions/cancel", json={"id": real, "reason": "no"})
    eq("a Transaction an Engineer answered is refused inside the window too",
       (r.status_code, (r.get_json() or {}).get("code")), (409, "confirmed"))
    eq("  and the admin password still opens it",
       c.post("/transactions/cancel",
              json={"id": real, "reason": "no", "password": "admin"}
              ).status_code, 200)
    ev = [e for e in log_rows(db) if e["event"] == "transaction.cancelled"]
    eq("  and that entry does not claim the window opened it",
       "auto-approve cancel window" in ev[-1]["detail"], False)

    # -- the switch still answers first ---------------------------------------
    write_server_cfg({"storekeeper_cancel_window_mins": 10,
                      "storekeeper_can_cancel": False})
    off = add_txn(db, asset_number="AW-5", confirmed=1, auto_approved=1,
                  team_member="Brian Dawson",
                  confirmed_at=datetime.now().isoformat())
    r = c.post("/transactions/cancel", json={"id": off, "reason": "x"})
    eq("the window is not a second door around the Storekeeper switch",
       (r.status_code, (r.get_json() or {}).get("code")),
       (403, "cancel_disabled"))

    # -- and the setting is read from disk, with no restart -------------------
    write_server_cfg({"storekeeper_cancel_window_mins": 0})
    r = c.post("/transactions/cancel", json={"id": off, "reason": "x"})
    eq("0 is no window at all",
       (r.status_code, (r.get_json() or {}).get("code")), (409, "confirmed"))
    write_server_cfg({})
    r = c.post("/transactions/cancel", json={"id": off, "reason": "x"})
    eq("and an absent key means the same, unlike the two switches beside it",
       (r.status_code, (r.get_json() or {}).get("code")), (409, "confirmed"))
    write_server_cfg({"storekeeper_cancel_window_mins": 10})
    eq("a window written to the file applies to the next request",
       c.post("/transactions/cancel",
              json={"id": off, "reason": "x"}).status_code, 200)

    # -- and the heartbeat carries it -----------------------------------------
    eq("GET /health publishes the window, so the Storekeeper can offer it",
       (c.get("/health").get_json() or {}).get(
           "storekeeper_cancel_window_mins"), 10)
    write_server_cfg({})
    eq("  and answers 0 where nothing is written down",
       (c.get("/health").get_json() or {}).get(
           "storekeeper_cancel_window_mins"), 0)


def check_the_auto_approved_column_arrives_both_ways():
    """Migration 014 and `init_db()` leave the same table, and `down()` keeps.

    The both-ways pattern every column here follows: a fresh database and an
    upgraded one have to be identical without anybody running `migrate`, and a
    downgrade never drops a column - an older build ignores one it does not
    know, where dropping it would throw away which Transactions nobody was ever
    asked about, the one fact that tells a confirmation from a row that was
    never verified.
    """
    head("transactions.auto_approved arrives both ways (#198)")
    db = fresh_db()
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    conn.close()
    eq("init_db() creates it", "auto_approved" in cols, True)

    path = os.path.join(R, "migrations", "014_transaction_auto_approved.py")
    if not os.path.exists(path):
        bad("migrations/014_transaction_auto_approved.py is missing")
        return
    msrc = io.open(path, encoding="utf-8").read()
    tree = ast.parse(msrc)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    for want in ("up", "down"):
        if want in names:
            ok("014 defines %s()" % want)
        else:
            bad("014 does not define %s()" % want)
    down = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "down"][0]
    body = [st for st in down.body if not isinstance(st, ast.Expr)]
    if body and all(isinstance(st, ast.Return) and st.value is None
                    for st in body):
        ok("014's down() is a no-op")
    else:
        bad("014's down() does something - a downgrade keeps the column")
    if "DROP COLUMN" in msrc.upper() or "DROP TABLE" in msrc.upper():
        bad("014 drops something")
    else:
        ok("014 drops nothing")

    # An old database - the table as it was before this ticket - upgraded by
    # init_db() alone, which is what makes a fresh install and an upgraded one
    # identical without anybody running migrate.
    old = os.path.join(STAGE, "pre_198.db")
    if os.path.exists(old):
        os.remove(old)
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asset_type TEXT NOT NULL,
        serial_number TEXT DEFAULT '', asset_number TEXT DEFAULT '',
        team_member TEXT NOT NULL, direction TEXT NOT NULL,
        timestamp TEXT NOT NULL, confirmed INTEGER DEFAULT 0,
        rejected INTEGER DEFAULT 0, confirmed_at TEXT DEFAULT '',
        rejection_reason TEXT DEFAULT '', notes TEXT DEFAULT '',
        storekeeper TEXT DEFAULT 'Storekeeper User')""")
    conn.execute("INSERT INTO transactions (asset_type, team_member, direction,"
                 " timestamp, confirmed) VALUES ('Laptop','Brian Dawson',"
                 "'Out Store',?,1)", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    M.DB_PATH = old
    M.init_db()
    conn = sqlite3.connect(old)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    n = conn.execute("SELECT COUNT(*) FROM transactions "
                     "WHERE auto_approved=0").fetchone()[0]
    conn.close()
    eq("an upgraded database has the column", "auto_approved" in cols, True)
    eq("  and a Confirmed row that predates it reads the closed answer", n, 1)

    # and the migration applies for real, twice, then down
    db = fresh_db()
    mod = {}
    exec(compile(msrc, path, "exec"), mod)
    conn = sqlite3.connect(db)
    mod["up"](conn)
    mod["up"](conn)
    mod["down"](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
    conn.close()
    eq("up() twice then down() still leaves the column",
       "auto_approved" in cols, True)


def check_cancelling_a_confirmed_transaction_moves_out_now():
    """Out Now must fall back to the movement before the one withdrawn.

    Out Now is the newest Confirmed Transaction per asset, and the out_now CTE
    excludes Cancelled rows, so cancelling the newest promotes the one before
    it. Anything less would leave an asset counted as held by an Engineer who
    handed it back, or the reverse.
    """
    head("Out Now after cancelling a Confirmed Transaction")
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    write_server_cfg({"host": "0.0.0.0", "port": 8081})
    db = fresh_db()
    c = M.app.test_client()

    out = add_txn(db, asset_number="ON-1", confirmed=1, direction="Out Store",
                  timestamp=(datetime.now() - timedelta(hours=8)).isoformat(),
                  confirmed_at=datetime.now().isoformat())
    back = add_txn(db, asset_number="ON-1", confirmed=1, direction="In Store",
                   timestamp=datetime.now().isoformat(),
                   confirmed_at=datetime.now().isoformat())
    eq("the asset reads as returned", c.get("/stats").get_json()["out_now"], 0)

    r = c.post("/transactions/cancel",
               json={"id": back, "reason": "it never came back",
                     "password": "admin"})
    eq("the return is cancelled", r.status_code, 200)
    eq("the asset is held again", c.get("/stats").get_json()["out_now"], 1)
    _recent, held, _oldest, _sig = M._gui_snapshot(20)
    eq("and the Server GUI agrees", [(h["team_member"], h["n"]) for h in held],
       [("Brian Dawson", 1)])

    r = c.post("/transactions/cancel",
               json={"id": out, "reason": "the whole pair was a mis-scan",
                     "password": "admin"})
    eq("the departure can then be cancelled too", r.status_code, 200)
    eq("and nothing is held", c.get("/stats").get_json()["out_now"], 0)


def check_which_asset_a_transaction_is_about_is_worded_once():
    """Out Now, the per-Engineer counts and Cancel ask the same question.

    A Transaction carries no `assets.id` - it records the identifiers as they
    were typed - so what identifies the asset is a SQL expression, and it was
    written out three times: in /stats' out_now, in _gui_snapshot's held and on
    both sides of _cancel_transaction's newest-per-asset equality. Nothing held
    the three together but a comment saying they were the same rule.

    A drift is invisible at the moment it is made and shows up as two numbers
    on one Server GUI window that disagree - the Out Now tile counting one way
    and the side panel's per-Engineer rows the other, with nothing saying which
    is right - and a Cancel refusing `not_newest` against a Transaction the
    count beside it thinks belongs to a different asset.

    The source half is asserted because what is claimed is an absence: no
    second copy of the wording anywhere in the file. The behaviour half needs
    rows the two spellings actually part company on, and the shape that does
    it is **two assets sharing a Serial Number** - which migration 010 found
    6 times in the 3462 rows of the shipped sheet, a manufacturer's number
    that identified nothing. Reading the Asset Number first they are two
    assets; reading the Serial Number first they are one, so the Out Now tile
    and the per-Engineer rows beside it come out one apart. An asset carrying
    only a Serial Number (rule 5's shape) and two Asset Numbers differing only
    by case are in the same table for what they pin down rather than what they
    discriminate: the first that the fallback leg is exercised at all, the
    second that a Transaction still records the spelling that was typed, where
    the `assets` table folds the two into one asset.
    """
    head("the asset a Transaction is about is worded once")
    # Which function each occurrence sits in: a constant like this is a string
    # inside a call, so there is no call node to match on and the enclosing
    # function is what says whether there is a second copy. Read over the API,
    # the console **and** the register - `_asset_key_sql` moved into
    # register_assets.py at #215, and reading only the first two would leave
    # this asserting an absence from the one file the wording is not in.
    owners = set()
    for _text in (SRC_ALL, REG_SRC):
        for fn in ast.walk(ast.parse(_text)):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for s in ast.walk(fn):
                if isinstance(s, ast.Constant) and isinstance(s.value, str) \
                        and "'A:' ||" in s.value:
                    owners.add(fn.name)
    if owners == {"_asset_key_sql"}:
        ok("only _asset_key_sql words it")
    else:
        bad("the asset-identity expression is written in %s - a copy left "
            "behind is Out Now and the per-Engineer counts disagreeing with "
            "nothing saying which is right" % (sorted(owners) or "nothing",))

    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    db = fresh_db()
    c = M.app.test_client()
    now = datetime.now()

    def out(**kw):
        kw.setdefault("confirmed", 1)
        kw.setdefault("direction", "Out Store")
        kw.setdefault("timestamp", now.isoformat())
        kw.setdefault("confirmed_at", now.isoformat())
        return add_txn(db, **kw)

    # An asset with both identifiers, one with a Serial Number alone (rule 5's
    # shape), two whose Asset Numbers differ only by case, and the pair that
    # discriminates: two Asset Numbers sharing one Serial Number.
    out(asset_number="AK-1", serial_number="SN-1")
    out(serial_number="SN-ONLY")
    out(asset_number="AM-1", team_member="Brian Dawson")
    out(asset_number="am-1", team_member="Carol Evans")
    out(asset_number="AK-9", serial_number="SH-1", team_member="Brian Dawson")
    out(asset_number="AK-10", serial_number="SH-1",
        team_member="Carol Evans")

    total = c.get("/stats").get_json()["out_now"]
    _recent, held, _oldest, _sig = M._gui_snapshot(20)
    eq("the tile and the per-Engineer rows count the same assets",
       total, sum(h["n"] for h in held))
    eq("and it is six - the shared Serial Number is two assets, the two "
       "spellings of one Asset Number two Transactions", total, 6)

    # Cancel's newest-per-asset rule asks the same question a third time.
    dep = out(asset_number="AK-2", serial_number="SN-2",
              timestamp=(now - timedelta(hours=3)).isoformat())
    ret = out(asset_number="AK-2", serial_number="SN-2", direction="In Store")
    r = c.post("/transactions/cancel",
               json={"id": dep, "reason": "mis-scan", "password": "admin"})
    eq("the older departure is refused", r.status_code, 409)
    eq("naming the newest Transaction for that asset",
       r.get_json().get("newest_id"), ret)

    # And the shape that tells the two spellings apart: two Asset Numbers
    # sharing a Serial Number are two assets, so the older of them is still
    # the newest Transaction for its own and can be cancelled. A copy reading
    # the Serial Number first calls them one asset and refuses this, sending
    # the Admin to cancel a Transaction against a laptop they are not holding.
    older = out(asset_number="AK-20", serial_number="SH-9",
                timestamp=(now - timedelta(hours=3)).isoformat())
    out(asset_number="AK-21", serial_number="SH-9")
    r = c.post("/transactions/cancel",
               json={"id": older, "reason": "mis-scan", "password": "admin"})
    eq("two Asset Numbers sharing a Serial Number are two assets to Cancel",
       r.status_code, 200)


def check_the_storekeeper_switch_is_enforced_at_the_endpoint():
    """The switch has to hold on the server, whatever a client shows.

    Publishing it on the heartbeat lets a Client hide a control rather than
    offer one that only ever fails, but a client is a file on someone's laptop.
    An older one does not know the field at all and will keep sending the
    request, so the endpoint is the only place the rule actually holds.
    """
    head("the storekeeper Cancel switch")
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    db = fresh_db()
    c = M.app.test_client()

    write_server_cfg({"host": "0.0.0.0", "port": 8081, "ssl_enabled": True})
    eq("an absent key means allowed", M._storekeeper_can_cancel(), True)
    eq("and the heartbeat says so",
       c.get("/health").get_json().get("storekeeper_can_cancel"), True)

    t1 = add_txn(db, asset_number="SW-1")
    r = c.post("/transactions/cancel", json={"id": t1, "reason": "mis-scan"})
    eq("the storekeeper can cancel while it is on", r.status_code, 200)

    M._save_server_cfg(storekeeper_can_cancel=False)
    eq("the switch is off", M._storekeeper_can_cancel(), False)
    eq("the heartbeat publishes it",
       c.get("/health").get_json().get("storekeeper_can_cancel"), False)
    eq("host survived the save", read_server_cfg().get("host"), "0.0.0.0")
    eq("ssl_enabled survived the save",
       read_server_cfg().get("ssl_enabled"), True)

    t2 = add_txn(db, asset_number="SW-2")
    r = c.post("/transactions/cancel", json={"id": t2, "reason": "mis-scan"})
    eq("a Pending cancel with no password is now refused",
       (r.status_code, (r.get_json() or {}).get("code")),
       (403, "cancel_disabled"))
    eq("and the row is untouched", txn(db, t2)["cancelled"], 0)

    r = c.post("/transactions/cancel",
               json={"id": t2, "reason": "mis-scan", "password": "wrong"})
    eq("a wrong password is still a wrong password",
       (r.status_code, (r.get_json() or {}).get("code")),
       (401, "bad_password"))

    r = c.post("/transactions/cancel",
               json={"id": t2, "reason": "mis-scan", "password": "admin"})
    eq("the admin can still cancel", r.status_code, 200)
    eq("and is recorded as the admin", txn(db, t2)["cancelled_by"], "Admin")

    M._save_server_cfg(storekeeper_can_cancel=True)
    t3 = add_txn(db, asset_number="SW-3")
    r = c.post("/transactions/cancel", json={"id": t3, "reason": "mis-scan"})
    eq("switching it back on restores the storekeeper's cancel",
       r.status_code, 200)
    eq("the heartbeat agrees again",
       c.get("/health").get_json().get("storekeeper_can_cancel"), True)


def check_the_heartbeat_did_not_change_shape():
    """A Client of any version has to keep finding the server here.

    /health is how every client resolves the server and how the port-change
    cascade works. A field added to it is safe; a field renamed or dropped
    strands a client that cannot be updated until it can reach the server.
    """
    head("the heartbeat's existing fields")
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    write_server_cfg({"host": "0.0.0.0", "port": 8081})
    fresh_db()
    body = M.app.test_client().get("/health").get_json()
    for k in ("status", "timestamp", "total", "port", "next_port", "ssl"):
        if k in body:
            ok("/health still carries %s" % k)
        else:
            bad("/health no longer carries %s" % k)
    eq("status is still ok", body.get("status"), "ok")
    eq("the switch is published alongside them",
       body.get("storekeeper_can_cancel"), True)


def check_the_switch_reads_from_disk_every_time():
    """Turning the switch off must not need a restart.

    _SERVER_CFG is a snapshot taken at import. Reading the switch from it would
    mean an admin who withdraws the permission has to restart the server to make
    it true, which is not something anyone will do in the situation that made
    them want the switch.
    """
    head("the switch takes effect at once")
    fn = [n for n in ast.walk(ast.parse(SRC_ALL))
          if isinstance(n, ast.FunctionDef)
          and n.name == "_storekeeper_can_cancel"]
    if not fn:
        bad("_storekeeper_can_cancel is gone")
        return
    # The names the body actually reads, not the text: the docstring names
    # _SERVER_CFG in order to say it is deliberately not read, and a substring
    # search cannot tell that apart from reading it.
    names = {n.id for n in ast.walk(fn[0]) if isinstance(n, ast.Name)}
    if "_load_server_cfg" in names:
        ok("it reads the file, not the import-time snapshot")
    else:
        bad("it does not call _load_server_cfg()")
    if "_SERVER_CFG" in names:
        bad("it reads _SERVER_CFG, which is a snapshot taken at import")
    else:
        ok("it never reads _SERVER_CFG")

    # and for real: write the file behind the module's back
    write_server_cfg({"host": "0.0.0.0", "port": 8081,
                      "storekeeper_can_cancel": False})
    eq("a file written underneath is seen immediately",
       M._storekeeper_can_cancel(), False)
    write_server_cfg({"host": "0.0.0.0", "port": 8081})
    eq("and so is its removal", M._storekeeper_can_cancel(), True)


def check_authorisation_is_in_the_one_enforcement_point():
    """The password check belongs in _cancel_transaction, not at the endpoint.

    The Server GUI calls the function directly. A check written at the endpoint
    would hold for a curl and not for the window an admin actually uses - which
    is the same failure mode the newest-per-asset rule is guarded against.

    This is one half of the rule and it is the half about *where* a credential
    is judged. The other half is
    `check_every_route_declares_the_credential_it_wants` below, which is about
    *which* credential each route asks for and is what refuses a route that
    names none (#209). They are kept apart because this one turns on one
    function pair and that one enumerates every route in the file.
    """
    head("authorisation lives with the rule")
    tree = ast.parse(SRC_TXN_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            fns[node.name] = node
    for want in ("_cancel_transaction", "cancel_transaction",
                 "_storekeeper_can_cancel"):
        if want not in fns:
            bad("%s is missing" % want)
            return

    inner = ast.get_source_segment(SRC_TXN_ALL,
                                   fns["_cancel_transaction"]) or ""
    outer = ast.get_source_segment(SRC_TXN_ALL,
                                   fns["cancel_transaction"]) or ""
    if "_admin_password_ok(" in inner:
        ok("_cancel_transaction checks the password")
    else:
        bad("_cancel_transaction does not check the password")
    if "_storekeeper_can_cancel()" in inner:
        ok("_cancel_transaction checks the switch")
    else:
        bad("_cancel_transaction does not check the switch")
    if "_admin_password_ok(" in outer:
        bad("the endpoint checks the password too - the GUI would bypass it")
    else:
        ok("the endpoint still forwards the admin password rather than "
           "checking it")

    args = [a.arg for a in fns["_cancel_transaction"].args.args]
    if "allow_confirmed" in args:
        bad("allow_confirmed survives - a caller can open a Confirmed "
            "Transaction without a password")
    else:
        ok("there is no allow_confirmed back door")

    # #169 put one credential at the endpoint and one only: the capability
    # password, whose acceptance is a question about the **transport** that no
    # helper can see. What crosses back into the rule is the answer rather than
    # the credential - `authorised_as`, the actor - so the rule itself is
    # unmoved. The pair is asserted together because either half alone is the
    # defect: a helper with no `authorised_as` is a second Cancel written at
    # the endpoint, and an endpoint with no `_remote_admit` is a capability
    # password gated on nothing.
    if "authorised_as" in args:
        ok("_cancel_transaction takes the answer, not a second password")
    else:
        bad("_cancel_transaction has no authorised_as - the capability path "
            "would have to mark the row itself")
    if "_remote_admit(" in outer:
        ok("the endpoint is what tells the two credentials apart")
    else:
        bad("the endpoint does not ask _remote_admit - a capability password "
            "would be accepted over plain http")
