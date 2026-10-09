r"""The Storekeeper is a name, not a row.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import sqlite3

from server_checks.stage import (M, SRC_ALL, _blank_lookup, _call_name, _code,
                                 add_txn, bad, eq, fresh_db, head, log_rows,
                                 ok, stored_form, txn, write_admin_cfg,
                                 write_server_cfg)



# ── the Storekeeper is a name, not a row ──────────────────────────

def check_the_storekeeper_is_a_named_setting():
    """The Storekeeper has a name an Admin can change, and still has no row.

    A row in team_members is what was rejected: the Storekeeper is never the
    recipient of a Transaction, so every reader of that table would have had to
    learn to skip one of its rows. What is asserted here is the setting that
    replaced it - that the name is read from disk on every call, that an empty
    or missing value means the column default rather than an empty name, and
    that naming somebody created no Engineer.
    """
    head("the Storekeeper is a named setting")
    db = fresh_db()

    write_server_cfg({"host": "0.0.0.0", "port": 8081})
    eq("a config with no name means the column default",
       M._storekeeper_name(), M.STOREKEEPER_DEFAULT)
    write_server_cfg({"host": "0.0.0.0", "port": 8081,
                      "storekeeper_name": "   "})
    eq("a blank name means it too", M._storekeeper_name(),
       M.STOREKEEPER_DEFAULT)

    M._save_server_cfg(storekeeper_name="Ahmed Fathy")
    eq("a saved name is read back", M._storekeeper_name(), "Ahmed Fathy")
    eq("the rename is logged as a config change",
       [r["event"] for r in log_rows(db)
        if "storekeeper_name" in (r["detail"] or "")],
       ["server.config_changed"])

    conn = sqlite3.connect(db)
    names = [r[0] for r in conn.execute("SELECT name FROM team_members")]
    conn.close()
    if "Ahmed Fathy" in names:
        bad("naming the Storekeeper put them on the Engineer list")
    else:
        ok("no Engineer row was created")

    c = M.app.test_client()
    health = c.get("/health").get_json()
    eq("/health carries the name", health.get("storekeeper_name"),
       "Ahmed Fathy")
    eq("as the bare name, with no role suffix",
       "(" in (health.get("storekeeper_name") or ""), False)


def check_who_recorded_a_transaction_is_said_once():
    """The column and the System Log agree about who recorded a Transaction.

    Three callers, three answers, and the one that would go wrong silently is
    the Server GUI: it records "Admin (Server GUI)" on the row and means it, so
    a label derived from that column would read "Admin (Server GUI)
    (Storekeeper)". That is why `actor` is a parameter rather than inferred
    from the body, and it is asserted from both ends here.
    """
    head("who recorded a Transaction is said once")
    db = fresh_db()
    _blank_lookup()
    write_server_cfg({"host": "0.0.0.0", "port": 8081,
                      "storekeeper_name": "Ahmed Fathy"})

    def created(**kw):
        actor = kw.pop("actor", None)
        body = {"team_member": "Brian Dawson", "direction": "Out Store",
                "asset_number": "AM-1"}
        body.update(kw)
        payload, status = M._create_transaction(body, actor=actor)
        eq("created (%s)" % (kw.get("storekeeper") or actor or "no name given"),
           status, 201)
        return txn(db, payload["id"]), log_rows(db)[-1]

    row, entry = created()
    eq("a caller that sent no name takes the server's",
       row["storekeeper"], "Ahmed Fathy")
    eq("and the log says so with the role", entry["actor"],
       "Ahmed Fathy (Storekeeper)")

    row, entry = created(asset_number="AM-2", storekeeper="Storekeeper User")
    eq("a name the caller sent is what the row carries",
       row["storekeeper"], "Storekeeper User")
    eq("and the log follows the row, not the setting",
       entry["actor"], "Storekeeper User (Storekeeper)")

    row, entry = created(asset_number="AM-3", storekeeper="Admin (Server GUI)",
                         actor="Admin (Server GUI)")
    eq("the Server GUI records itself on the row",
       row["storekeeper"], "Admin (Server GUI)")
    eq("and is not dressed as the Storekeeper",
       entry["actor"], "Admin (Server GUI)")


def check_a_cancel_is_attributed_the_same_way_a_creation_is():
    """Cancelling carries the role too, and the column still does not.

    The gap this closes: creation logged "<name> (Storekeeper)" while a cancel
    by that same person logged a bare name, which in the actor column is
    indistinguishable from an Engineer's. Both are acts a Storekeeper takes on
    a row, so both read the same way.

    The trap is that `who` is written to `cancelled_by` as well as being
    logged, so dressing it would put a role in a stored column - the same
    mistake `_create_transaction` avoids by taking `actor` as a parameter.
    Asserted from both ends here: the column bare, the entry with the role.
    """
    head("a cancel is attributed the way a creation is")
    db = fresh_db()
    c = M.app.test_client()
    write_server_cfg({"host": "0.0.0.0", "port": 8081,
                      "storekeeper_name": "Ahmed Fathy"})

    tid = add_txn(db, asset_number="C-1", storekeeper="Ahmed Fathy")
    eq("the Storekeeper's own cancel is accepted",
       c.post("/transactions/cancel",
              json={"id": tid, "reason": "mis-scan"}).status_code, 200)
    eq("the column carries the name alone",
       txn(db, tid)["cancelled_by"], "Ahmed Fathy")
    eq("and the System Log carries the role with it",
       log_rows(db)[-1]["actor"], "Ahmed Fathy (Storekeeper)")

    tid = add_txn(db, asset_number="C-2", storekeeper="Ahmed Fathy")
    eq("a caller that names itself is accepted",
       c.post("/transactions/cancel",
              json={"id": tid, "reason": "wrong engineer",
                    "cancelled_by": "Admin (Server GUI)"}).status_code, 200)
    eq("its own name is what the column carries",
       txn(db, tid)["cancelled_by"], "Admin (Server GUI)")
    eq("and it is not dressed as the Storekeeper",
       log_rows(db)[-1]["actor"], "Admin (Server GUI)")

    # A nameless Admin: the admin password proves an Admin and names nobody, so
    # the row and the entry both say Admin and neither says Storekeeper.
    write_admin_cfg('{"password_hash": "%s", "first_run": false}'
                    % stored_form("adminpw"))
    M.ADMIN_CFG = M.load_admin_cfg()
    tid = add_txn(db, asset_number="C-3", storekeeper="Ahmed Fathy",
                  confirmed=1)
    eq("a Confirmed row takes the admin password",
       c.post("/transactions/cancel",
              json={"id": tid, "reason": "never happened",
                    "password": "adminpw"}).status_code, 200)
    eq("a nameless Admin is recorded as one",
       txn(db, tid)["cancelled_by"], "Admin")
    eq("and is not dressed as the Storekeeper either",
       log_rows(db)[-1]["actor"], "Admin")

    # The row that has nothing to attribute a cancel to. This is the caller the
    # `name=None` fallback on _storekeeper_actor exists for.
    tid = add_txn(db, asset_number="C-4", storekeeper="")
    eq("a row with no storekeeper can still be cancelled",
       c.post("/transactions/cancel",
              json={"id": tid, "reason": "no idea who"}).status_code, 200)
    eq("and the entry falls back to this server's own name",
       log_rows(db)[-1]["actor"], "Ahmed Fathy (Storekeeper)")


def check_one_place_words_the_storekeeper_label():
    """Only `_storekeeper_actor` builds the role suffix, and every caller of
    `_create_transaction` that is not the Storekeeper says so.

    Both halves are source checks. The first guards a second site wording the
    label differently - "(storekeeper)", " - Storekeeper" - which no behaviour
    check sees until somebody filters the System Log by a string that now
    matches half the rows. The second guards the Server GUI's Add Transaction,
    a Tk callback no harness reaches: it records "Admin (Server GUI)" on the
    row, so a call there that left `actor` to be derived would log
    "Admin (Server GUI) (Storekeeper)".
    """
    head("one place words the Storekeeper label")
    tree = ast.parse(SRC_ALL)
    fns = {f.name: f for f in ast.walk(tree)
           if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}

    # The construction, not a mention of it: the docstrings around this explain
    # the label and would otherwise fail their own rule.
    fmt = '"%s (Storekeeper)"'
    eq("the suffix is constructed exactly once", SRC_ALL.count(fmt), 1)
    # `_code` unparses, which normalises the quotes around the literal, so
    # the comparison inside is on the format itself.
    if "%s (Storekeeper)" in _code(fns["_storekeeper_actor"]):
        ok("and that once is inside _storekeeper_actor")
    else:
        bad("the suffix is built outside _storekeeper_actor")

    # Every call, found as a call rather than by which function encloses it -
    # add_transaction sits inside run_gui and do_add inside add_transaction, so
    # enclosing-function matching answers three times for one call site.
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and _call_name(n.func) == "_create_transaction"]
    eq("_create_transaction has the two callers it is documented to have",
       len(calls), 2)
    for call in calls:
        src = ast.unparse(call)
        states = any(k.arg == "actor" for k in call.keywords)
        if "Admin (Server GUI)" in src:
            if states:
                ok("the Server GUI call states its own actor")
            else:
                bad("the Server GUI call leaves actor to be derived, which "
                    "would log \"Admin (Server GUI) (Storekeeper)\"")
        elif states:
            bad("a caller states an actor that is not the Server GUI: %s"
                % src[:60])
        else:
            ok("the endpoint call derives the Storekeeper's label")
