r"""The server holds writes (G3, ADR-0018).

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import os
import re

from server_checks.stage import (M, SRC_ALL, _clear_log, _log_rows,
                                 _no_maintenance, add_txn, eq, fresh_db, head,
                                 txn)



def check_every_write_endpoint_is_held_or_is_deliberately_open():
    """A route added later defaults to being held.

    The set is written as the endpoints that stay **open**, and this is the
    half that makes that choice mean anything: a new non-GET route lands in
    neither list, and without this it would go on taking writes through a
    restore with nobody having decided that it should.

    Read off the app's own url map rather than off a list in this file, which
    would be a third copy of the same fact and the one that goes stale - and
    **driven** rather than compared, since what is claimed about a route that
    is not on the open set is that it really answers 503, not that its name is
    absent from a set.
    """
    head("every write endpoint is held or is deliberately open")

    writes = set()
    for rule in M.app.url_map.iter_rules():
        if set(rule.methods) - {"GET", "HEAD", "OPTIONS"}:
            writes.add(rule.endpoint)
    eq("there are non-GET routes to be held at all", len(writes) > 0, True)
    eq("nothing in MAINTENANCE_OPEN names a route that is not there",
       sorted(M.MAINTENANCE_OPEN - writes), [])
    eq("the open set is the three that write nothing a backup is about",
       sorted(M.MAINTENANCE_OPEN),
       ["admin_verify", "auth_verify", "preview_import"])

    fresh_db()
    c = M.app.test_client()
    _no_maintenance()
    try:
        M._maintenance_enter("a backup")
        loose = []
        for rule in sorted(M.app.url_map.iter_rules(), key=lambda r: r.rule):
            if rule.endpoint in M.MAINTENANCE_OPEN:
                continue
            verbs = set(rule.methods) - {"GET", "HEAD", "OPTIONS"}
            if not verbs:
                continue
            path = re.sub(r"<[^>]+>", "1", rule.rule)
            r = c.open(path, method=sorted(verbs)[0], json={})
            if r.status_code != 503:
                loose.append((rule.endpoint, r.status_code))
        eq("every route not on the open set answers 503", loose, [])
    finally:
        M._maintenance_leave()
        _no_maintenance()


def check_a_write_is_refused_while_a_backup_runs():
    """503 and the code, with the read beside it untouched."""
    head("a write is refused while a backup runs")

    db = fresh_db()
    tid = add_txn(db, asset_number="AM-HOLD-1")
    c = M.app.test_client()
    _no_maintenance()

    try:
        M._maintenance_enter("a backup")
        r = c.post("/confirm/%d" % tid)
        eq("a write is refused", r.status_code, 503)
        body = r.get_json() or {}
        eq("  and says why in a code the client can read",
           body.get("code"), "maintenance")
        eq("  and in words a person can read",
           "backup" in (body.get("error") or ""), True)
        eq("  and names when the hold started", bool(body.get("since")), True)
        eq("the Transaction was not confirmed", txn(db, tid)["confirmed"], 0)

        eq("a read carries on", c.get("/transactions").status_code, 200)
        eq("  including the one every client resolves the server with",
           c.get("/health").status_code, 200)
        # Answered rather than held: it refuses the wrong password, which is
        # the point - a door that checks a credential and writes nothing is
        # not a door a backup has any reason to shut.
        eq("an endpoint on the open set still answers",
           c.post("/admin/verify", json={"password": "nope"}).status_code, 401)
    finally:
        M._maintenance_leave()
        _no_maintenance()

    r = c.post("/confirm/%d" % tid)
    eq("the write goes through once the hold is off", r.status_code, 200)
    eq("  and the Transaction is confirmed", txn(db, tid)["confirmed"], 1)


def check_a_held_write_is_logged_once_per_caller():
    """The first refusal is what an Admin needs; the hundredth is not.

    `POST /clients/log` is itself held, and every client retries on its own
    tick, so a ten-minute restore left to write a row per refusal would fill
    the table it is restoring - and a held log write answered with a log row
    is a refusal that writes what it refused.
    """
    head("a held write is logged once per caller")

    db = fresh_db()
    # Emptied rather than trusted to be empty: fresh_db() names the file after
    # how many are in the staging directory, so a run in which a name comes
    # back round hands out a database an earlier group already wrote to - and
    # what is counted here is rows.
    _clear_log(db)
    c = M.app.test_client()
    _no_maintenance()
    body = {"team_member": "Brian Dawson", "direction": "Out Store",
            "asset_number": "AM-HOLD-2"}
    try:
        M._maintenance_enter("a restore")
        for _ in range(5):
            c.post("/transactions", json=body)
        rows = _log_rows(db, "write.held")
        eq("five refusals of one endpoint are one entry", len(rows), 1)
        eq("  written at warn", rows[0]["level"], "warn")
        eq("  naming what is holding", "restore" in rows[0]["detail"], True)

        c.post("/clients/log", json={"entries": [{"event": "x"}]})
        eq("a different endpoint is its own entry",
           len(_log_rows(db, "write.held")), 2)

        # A second window is a second thing to be told about.
        M._maintenance_leave()
        M._maintenance_enter("a second backup")
        c.post("/transactions", json=body)
        eq("a later hold is reported again",
           len(_log_rows(db, "write.held")), 3)
    finally:
        M._maintenance_leave()
        _no_maintenance()

    eq("entering and leaving are each written down",
       (len(_log_rows(db, "maintenance.entered")),
        len(_log_rows(db, "maintenance.left"))), (2, 2))


def check_the_hold_comes_off_when_the_operation_raises():
    """An operation that fails must not leave the server shut.

    This is the whole reason the state is entered through a context manager
    rather than through two calls at each site.
    """
    head("the hold comes off when the operation raises")

    fresh_db()
    _no_maintenance()
    try:
        with M._maintenance("a backup that fails"):
            eq("the hold is on inside the block",
               bool(M._maintenance_state()), True)
            raise RuntimeError("the disk filled up")
    except RuntimeError:
        pass
    eq("and off again afterwards", M._maintenance_state(), None)
    eq("  with no file left behind", os.path.exists(M.MAINTENANCE_PATH), False)
    _no_maintenance()


def check_a_state_file_that_cannot_be_read_means_no_maintenance():
    """A stray byte must not be a server nobody can write to.

    The opposite answer from admin_config.json's raise, on purpose: that file
    holds a credential and is permanent, this one describes a few minutes, and
    a server refusing every write with nothing able to say why is the worse
    failure of the two.
    """
    head("a state file that cannot be read means no maintenance")

    db = fresh_db()
    c = M.app.test_client()
    tid = add_txn(db, asset_number="AM-HOLD-3")
    for label, text in (("not JSON at all", "}{"),
                        ("JSON that is not an object", "[1, 2, 3]"),
                        ("an object saying nothing", "{}"),
                        ("an object with an empty what", '{"what": ""}')):
        with io.open(M.MAINTENANCE_PATH, "w", encoding="utf-8") as f:
            f.write(text)
        eq("%s means no maintenance" % label, M._maintenance_state(), None)
    eq("  so a write still goes through",
       c.post("/confirm/%d" % tid).status_code, 200)
    _no_maintenance()


def check_a_stale_hold_is_cleared_at_start():
    """A process that is only now starting is not mid-backup.

    The state is on disk so a crash is visible rather than silent, and the
    price of that is a file outliving its process - which, left alone, is a
    server refusing every write for ever with nothing saying why.
    """
    head("a stale hold is cleared at start")

    db = fresh_db()
    _clear_log(db)
    M._maintenance_enter("a backup nobody finished")
    was = M._maintenance_clear_stale()
    eq("the leftover state is found", (was or {}).get("what"),
       "a backup nobody finished")
    eq("  and cleared", M._maintenance_state(), None)
    rows = _log_rows(db, "maintenance.left")
    eq("  and the clearing is written down rather than done quietly",
       bool(rows) and "no longer running" in rows[-1]["detail"], True)
    eq("  at warn, being a crash rather than a normal end",
       rows[-1]["level"], "warn")

    n = len(_log_rows(db, "maintenance.left"))
    eq("clearing nothing writes nothing", M._maintenance_clear_stale(), None)
    eq("  and says nothing either", len(_log_rows(db, "maintenance.left")), n)
    _no_maintenance()


def check_the_start_path_clears_it_and_the_monitor_does_not():
    """Source, both halves being about where a call is rather than what it does.

    `_start_background_jobs` is the one thing all three serving modes go
    through. The monitor-only GUI deliberately does not: a window watching
    somebody else's listener has no business clearing that process's state
    while the operation is still running - and there is no request that
    demonstrates a call that is not made.
    """
    head("the start path clears a stale hold and the monitor does not")

    tree = ast.parse(SRC_ALL)
    where = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "_maintenance_clear_stale"):
                where.append(node.name)
    eq("exactly one function clears it", sorted(where),
       ["_start_background_jobs"])

    # And the guard is a before_request rather than a decorator each view opts
    # into, which is what makes MAINTENANCE_OPEN the whole of the decision.
    guard = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == "_hold_writes_during_maintenance"]
    eq("the guard is there", len(guard), 1)
    eq("  and runs before every request",
       any(isinstance(d, ast.Attribute) and d.attr == "before_request"
           for d in guard[0].decorator_list), True)
