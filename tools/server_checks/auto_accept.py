r"""The 24h Auto-Accept rule.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
from datetime import datetime, timedelta

from server_checks.stage import (M, SRC_ALL, add_txn, bad, eq, fresh_db, head,
                                 ok, txn)



# ── the 24h Auto-Accept rule ─────────────────────────────────────────────────

def check_auto_accept_pass():
    """Auto-Accept confirms a Transaction pending for over 24h, and only that.

    The rule is a deadline that applies to every Engineer. It is distinct from
    Auto-Approve, which is a per-Engineer flag - one letter apart, and changing
    one must never change the other.
    """
    head("the 24h Auto-Accept pass")
    db = fresh_db()
    now = datetime.now()

    stale = add_txn(db, timestamp=(now - timedelta(hours=25)).isoformat())
    fresh = add_txn(db, timestamp=(now - timedelta(hours=1)).isoformat())
    rejd = add_txn(db, timestamp=(now - timedelta(hours=25)).isoformat(),
                   rejected=1, rejection_reason="never had it")
    conf = add_txn(db, timestamp=(now - timedelta(hours=25)).isoformat(),
                   confirmed=1, confirmed_at=(now - timedelta(hours=24)).isoformat())

    n = M._auto_accept_pass(now=now)
    eq("one row confirmed", n, 1)
    eq("the stale pending one is Confirmed", txn(db, stale)["confirmed"], 1)
    if txn(db, stale)["confirmed_at"]:
        ok("it carries a confirmed_at")
    else:
        bad("it was confirmed with no confirmed_at")
    eq("the one pending an hour is untouched", txn(db, fresh)["confirmed"], 0)
    eq("a Rejected one is not confirmed", txn(db, rejd)["confirmed"], 0)
    eq("a Rejected one stays Rejected", txn(db, rejd)["rejected"], 1)
    eq("an already-Confirmed one keeps its confirmed_at",
       txn(db, conf)["confirmed_at"],
       (now - timedelta(hours=24)).isoformat())

    eq("a second pass finds nothing left", M._auto_accept_pass(now=now), 0)


def check_auto_accept_is_still_hourly():
    """The loop must still apply the rule.

    Extracting the pass for testability is worthless if nothing calls it in
    production, and nothing would report that: the job is a daemon thread whose
    exceptions are swallowed.
    """
    head("Auto-Accept is still applied hourly")
    tree = ast.parse(SRC_ALL)
    loop = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "_auto_accept_stale_pending"), None)
    if loop is None:
        bad("_auto_accept_stale_pending is gone")
        return
    seg = ast.get_source_segment(SRC_ALL, loop) or ""
    if "_auto_accept_pass(" in seg:
        ok("the hourly loop calls the pass")
    else:
        bad("the hourly loop no longer calls _auto_accept_pass")
    if "3600" in seg:
        ok("it still re-checks hourly")
    else:
        bad("the hourly cadence is gone")
    starter = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                    and n.name == "_start_background_jobs"), None)
    seg = ast.get_source_segment(SRC_ALL, starter) if starter else ""
    if starter and "_auto_accept_stale_pending" in seg:
        ok("the job is still started")
    else:
        bad("nothing starts the Auto-Accept job")


def check_an_auto_accept_pass_writes_an_auto_origin():
    """The pass marks each row it confirms, and says so in the log (#282)."""
    head("Auto-Accept writes origin=auto (#282)")
    import json
    import sqlite3
    db = fresh_db()
    now = datetime.now()
    stale = add_txn(db, timestamp=(now - timedelta(hours=25)).isoformat())
    fresh = add_txn(db, timestamp=(now - timedelta(hours=1)).isoformat())
    M._auto_accept_pass(now=now)
    eq("the stale row is auto", txn(db, stale)["origin"], "auto")
    eq("the fresh row has none", txn(db, fresh)["origin"], None)
    conn = sqlite3.connect(db)
    d = conn.execute("SELECT data FROM system_log WHERE "
                     "event='transaction.auto_accepted'").fetchone()[0]
    conn.close()
    eq("the entry carries origin and the Engineers", json.loads(d),
       {"origin": "auto", "engineers": ["Brian Dawson"]})
