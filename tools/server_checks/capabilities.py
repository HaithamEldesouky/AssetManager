r"""Capability passwords, the doors they open, the certificate they pin.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import threading

from server_checks.console import open_section_entry
from server_checks.stage import console_door
from server_checks.stage import (C, CERT_SRC, GUI_SRC, IM, M, R, SRC, SRC_ALL,
                                 SRC_ENG_ALL, SRC_TXN_ALL, STAGE, _caps, _code,
                                 _member_hash, _resolves_to, add_txn, bad, eq,
                                 fresh_db, gui_root, head, log_rows, ok,
                                 stored_form, tk_or_skip, txn, widgets,
                                 write_admin_cfg)



def check_the_four_capabilities_are_the_delegable_actions():
    """The list, and that changing the admin password is not in it.

    A capability password that could change the admin password would be the
    admin password with an extra step, so that action is deliberately absent.

    Five since #170, `server_settings` being the fifth. It is **one** capability
    covering four areas rather than four capabilities, which is a decision
    rather than an economy, so what it opens is written down in
    `CAPABILITY_REACH` and shown on its row - a label names an action, and
    "Server Settings" sitting a click under "Change Host / Port" does not say
    what it is. The reach line is held to the capability list here for the
    reason the label is: a capability with no line is a row that says nothing
    about the password an Admin is handing over.
    """
    head("the capabilities")
    eq("five capabilities, and these five", sorted(M.CAPABILITIES),
       ["import_archive", "manage_records", "server_config", "server_settings",
        "ssl_cert"])
    eq("every one has a label", sorted(M.CAPABILITY_LABELS),
       sorted(M.CAPABILITIES))
    eq("labelled as the console's own entries label them",
       [M.CAPABILITY_LABELS[c] for c in M.CAPABILITIES],
       ["Change Host / Port", "SSL Certificate",
        "Manage Transaction History", "Import Transaction Archive",
        "Server Settings"])
    eq("every one says what it reaches", sorted(M.CAPABILITY_REACH),
       sorted(M.CAPABILITIES))
    blank = [c for c in M.CAPABILITIES
             if not (M.CAPABILITY_REACH[c] or "").strip()]
    eq("and none of those lines is empty", blank, [])
    eq("Server Settings is reachable over the network",
       "server_settings" in M.CAPABILITY_REMOTE, True)
    for absent in ("admin_password", "change_admin_password"):
        if absent in M.CAPABILITIES:
            bad("%s is delegable - it must not be" % absent)
        else:
            ok("%s is not a capability" % absent)
    # Not PERMISSIONS: those gate what an Engineer's own client shows them.
    # Nothing here reaches a client at all.
    for c in M.CAPABILITIES:
        if c in M.PERMISSIONS:
            bad("%s leaked into PERMISSIONS" % c)
    ok("none of them leaked into PERMISSIONS (rule 8)")


def check_the_admin_password_opens_every_capability():
    """The admin password always works, so a delegation cannot lock the Admin
    out of their own server - and each capability password opens only its own.
    """
    head("who opens what")
    _caps(ssl_cert="certpw", import_archive="archivepw")
    for c in M.CAPABILITIES:
        if M._authorise(c, "admin"):
            ok("the admin password opens %s" % M.CAPABILITY_LABELS[c])
        else:
            bad("the admin password does not open %s" % c)
    eq("the SSL password opens SSL",
       bool(M._authorise("ssl_cert", "certpw")), True)
    eq("the Import password opens Import",
       bool(M._authorise("import_archive", "archivepw")), True)
    for c in M.CAPABILITIES:
        if c != "ssl_cert" and M._authorise(c, "certpw"):
            bad("the SSL password also opens %s" % c)
    ok("the SSL password opens nothing else")
    for c in M.CAPABILITIES:
        if c != "import_archive" and M._authorise(c, "archivepw"):
            bad("the Import password also opens %s" % c)
    ok("the Import password opens nothing else")
    eq("a capability with no password of its own takes the admin password only",
       [bool(M._authorise("manage_records", p)) for p in
        ("admin", "certpw", "archivepw", "nope")],
       [True, False, False, False])
    eq("nothing empty ever authorises",
       [bool(M._authorise(c, p)) for c in M.CAPABILITIES for p in ("", None)],
       [False] * (2 * len(M.CAPABILITIES)))
    try:
        M._authorise("reset_the_database", "admin")
    except ValueError:
        ok("an unknown capability raises rather than reading as refused")
    else:
        bad("an unknown capability name was quietly refused - a typo at a "
            "callsite would look like a wrong password")


def check_the_console_writes_one_actor_and_the_vocabulary_survives():
    """One credential at the console, and the words the remote channel needs.

    `actor` - "who, as far as anything knows" - said which of two passwords
    opened an action for as long as two could. Since ADR-0015 only one can:
    the admin password, at the door, so every console entry reads
    `Admin (Server GUI)` again and a Delegate named there would be naming
    somebody who cannot get in.

    `_authorise` and `_console_actor` are kept all the same, with no caller at
    this console. They are the store and the vocabulary the remote channel is
    built on, and rebuilding them against the network would be rebuilding what
    is already correct - so they are asserted here as the **pure functions**
    they now are, including the two labels that moved with the actions they
    name.

    **R1 built that channel and `_authorise` has one caller again** -
    `_remote_admit`, the body `_remote_authorise` and the cancel door share
    since #169, and nothing else anywhere in the file. That is what
    keeps this check meaningful rather than retiring it: the claim was never
    "nobody asks" but "nobody at this console asks", and a call that reappeared
    in a Tk callback would be a console entry naming a Delegate for an act only
    the admin password could have opened. `_console_actor` still has none, its
    remote sibling `_remote_actor` wording the network's entries instead.
    """
    head("the console writes one actor, and the vocabulary is kept")
    _caps(manage_records="mrpw")
    eq("_authorise answers with the credential, not a bare bool",
       [M._authorise("manage_records", p) for p in ("mrpw", "admin", "nope")],
       ["capability", "admin", ""])
    eq("and the wording is one place",
       [M._console_actor("manage_records", "capability"),
        M._console_actor("manage_records", "admin")],
       ["Delegate: Manage Transaction History (Server GUI)",
        "Admin (Server GUI)"])

    db = fresh_db()
    tid = add_txn(db, asset_number="NS-1")
    payload, status = M._modify_transaction(tid, {"notes": "by the admin"})
    eq("a correction behind the door is a plain 200", status, 200)
    eq("  and the entry reads as the Admin, the console having one "
       "credential again", log_rows(db)[-1]["actor"], "Admin (Server GUI)")

    # And nothing at this console calls either of them. An absence, which is
    # why it is a source check: a call left in one of these would be an entry
    # naming a Delegate for an act only the admin password could have opened.
    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    def asks(f):
        # `_remote_authorise(` carries `_authorise(` inside it, so the remote
        # gate would match as a caller of the thing it *is*. Blank it out
        # before looking, and count who calls the gate itself separately.
        return _code(f).replace("_remote_authorise(", "")

    callers = sorted({n for n, f in fns.items()
                      if n not in ("_authorise", "_console_actor",
                                   "_pw_caption", "_remote_authorise",
                                   "_remote_admit")
                      and ("_authorise(" in asks(f)
                           or "_console_actor(" in asks(f))})
    eq("nothing at this console asks either of them", callers, [])
    eq("and the one thing that asks _authorise is the remote gate",
       "_authorise(" in asks(fns["_remote_admit"]), True)
    eq("  which _remote_authorise is now a wrapper over, so there is still "
       "one gate rather than two",
       "_remote_admit(" in asks(fns["_remote_authorise"]), True)
    for name in ("_authorise", "_console_actor", "_pw_caption"):
        if name in fns:
            ok("%s is kept for the remote channel (ADR-0015)" % name)
        else:
            bad("%s has been deleted - the remote channel needs the store "
                "and the vocabulary, not a rebuild of them" % name)


def check_a_server_with_no_capability_passwords_is_unchanged():
    """The default install, which is every install today.

    With no capability password set, each of the four is exactly the admin
    password check it was before this ticket.
    """
    head("no capability passwords set")
    _caps()
    eq("nothing is delegated", M._capability_state(),
       {c: False for c in M.CAPABILITIES})
    for c in M.CAPABILITIES:
        eq("%s: the admin password and nothing else"
           % M.CAPABILITY_LABELS[c],
           [bool(M._authorise(c, "admin")), bool(M._authorise(c, "wrong")),
            bool(M._authorise(c, ""))],
           [True, False, False])
    db = fresh_db()
    tid = add_txn(db, asset_number="NS-1")
    payload, status = M._modify_transaction(tid, {"notes": "fixed"})
    eq("Modify corrects the row, the door having answered already", status,
       200)
    eq("  and the entry reads as the Admin", log_rows(db)[-1]["actor"],
       "Admin (Server GUI)")


def check_an_older_admin_config_needs_no_migration():
    """A file written before this ticket, and one written by hand badly.

    admin_config.json is never rewritten unless a password changes, so the file
    on a real server predates this key. A key of the wrong shape is malformed
    and raises, the same as bad JSON: reading {} out of a corrupt map would drop
    every delegation the Admin had made without saying so.
    """
    head("an older admin config")
    write_admin_cfg(json.dumps({"password_hash": stored_form("hunter2"),
                                "first_run": False}))
    cfg = M.load_admin_cfg()
    eq("the map defaults to empty", cfg.get("capability_hashes"), {})
    keep = M.ADMIN_CFG
    M.ADMIN_CFG = cfg
    eq("so the admin password still opens everything",
       [bool(M._authorise(c, "hunter2")) for c in M.CAPABILITIES],
       [True] * len(M.CAPABILITIES))
    eq("and nothing else opens anything",
       [bool(M._authorise(c, "admin")) for c in M.CAPABILITIES],
       [False] * len(M.CAPABILITIES))
    M.ADMIN_CFG = keep

    for shape in ('"hunter2"', "[]", "5"):
        write_admin_cfg('{"password_hash": "x", "capability_hashes": %s}'
                        % shape)
        try:
            M.load_admin_cfg()
        except Exception as ex:
            ok("capability_hashes as %s raises (%s)"
               % (shape, type(ex).__name__))
        else:
            bad("capability_hashes as %s loaded anyway" % shape)
    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()


def check_setting_a_capability_password_takes_the_admin_password():
    """Delegating is the Admin's decision.

    A capability password cannot grant or revoke itself - otherwise whoever held
    Import Archive could keep it after the Admin meant to take it back, and the
    Admin's own password would no longer be the whole story about who can do
    what.
    """
    head("setting one")
    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()

    for label, pw in (("no admin password", ""), ("None", None),
                      ("a wrong one", "nope")):
        payload, status = M._set_capability_password("ssl_cert", "certpw", pw)
        eq("%s is refused" % label, status, 401)
        eq("  with a code", payload.get("code"), "bad_password")
    eq("nothing was delegated", M._capability_state()["ssl_cert"], False)

    payload, status = M._set_capability_password("ssl_cert", "certpw", "admin")
    eq("the admin password sets it", status, 200)
    eq("  and says so", payload.get("status"), "set")
    eq("it now has its own password", M._capability_state()["ssl_cert"], True)
    eq("which opens that capability",
       M._authorise("ssl_cert", "certpw"), "capability")

    payload, status = M._set_capability_password("ssl_cert", "other", "certpw")
    eq("the capability password cannot change itself", status, 401)
    eq("  with a code", payload.get("code"), "bad_password")
    eq("the old one still works",
       bool(M._authorise("ssl_cert", "certpw")), True)
    payload, status = M._set_capability_password("ssl_cert", "", "certpw")
    eq("and cannot clear itself either", status, 401)
    eq("still set", M._capability_state()["ssl_cert"], True)

    payload, status = M._set_capability_password("no_such_thing", "abcd",
                                                 "admin")
    eq("an unknown capability is refused", status, 400)
    eq("  with a code", payload.get("code"), "bad_capability")
    payload, status = M._set_capability_password("manage_records", "abc",
                                                 "admin")
    eq("a short password is refused", status, 400)
    eq("  with a code", payload.get("code"), "too_short")
    eq("  held to the same length the admin password is", M.CAPABILITY_MIN, 4)
    payload, status = M._set_capability_password("manage_records", "admin",
                                                 "admin")
    eq("the admin password itself is refused as a delegation", status, 400)
    eq("  with a code", payload.get("code"), "same_as_admin")
    eq("none of those delegated anything",
       M._capability_state()["manage_records"], False)

    payload, status = M._set_capability_password("ssl_cert", "", "admin")
    eq("the Admin can clear it", status, 200)
    eq("  saying it was set", payload.get("was_set"), True)
    eq("it is gone", M._capability_state()["ssl_cert"], False)
    eq("and the password that opened it no longer does",
       bool(M._authorise("ssl_cert", "certpw")), False)
    eq("while the admin password still does",
       M._authorise("ssl_cert", "admin"), "admin")
    payload, status = M._set_capability_password("ssl_cert", "", "admin")
    eq("clearing one that was never set is not an error", status, 200)
    eq("  and says nothing was there", payload.get("was_set"), False)


def check_a_capability_password_survives_a_restart():
    """It is written to admin_config.json, which is the only place it lives."""
    head("a capability password is persisted")
    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()
    M._set_capability_password("import_archive", "archivepw", "admin")
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("the file holds one entry, for that capability",
       sorted(on_disk.get("capability_hashes") or {}), ["import_archive"])
    on_file = (on_disk.get("capability_hashes") or {}).get("import_archive")
    # Not an equality against a hash of our own: the stored value is salted, so
    # the same password hashed twice does not compare equal. What the file has
    # to hold is a value that verifies and is not the password.
    eq("and a value the password verifies against",
       M.password_matches("archivepw", on_file), True)
    eq("  which nothing else opens", M.password_matches("admin", on_file),
       False)
    if "archivepw" not in io.open(M.ADMIN_CFG_PATH, encoding="utf-8").read():
        ok("and the password itself is nowhere in the file")
    else:
        bad("the capability password was written in the clear")
    reloaded = M.load_admin_cfg()
    keep, M.ADMIN_CFG = M.ADMIN_CFG, reloaded
    eq("a fresh load still opens that capability",
       M._authorise("import_archive", "archivepw"), "capability")
    M.ADMIN_CFG = keep
    M._set_capability_password("import_archive", "", "admin")


def check_a_capability_password_opens_its_own_endpoint_and_no_other():
    """The boundary this whole feature rests on, inverted by R1.

    It read "no endpoint accepts a capability password" until R1, which is the
    assertion ADR-0015 said would have to be repointed **deliberately** rather
    than quietly when the remote channel landed. What it asserts now is the
    same boundary drawn one door further out, and it is three claims rather
    than one:

    * each of the three remote capabilities opens **its own** endpoint,
    * and **no other** - a delegate who may change the port may not delete a
      Transaction, which is the whole of what makes a capability a capability
      rather than a second admin password,
    * and **none of them** opens an admin-only endpoint, `POST
      /admin/change_password` above all (rule 7): a capability that could
      change the admin password would be the admin password with an extra step.

    `ssl_cert` is the fourth and is **not** remote and must not become so -
    installing a certificate means uploading `ssl_key.pem`, the one file that
    must never travel - so it is here as a password that opens nothing over the
    network at all, which is a claim about the set rather than about a route.

    **`server_settings` is the fifth**, and #171 moved the first of its four
    areas across: the three `/members` doors were in the admin-only list below
    and are in `doors` above it now, opened by `setpw` and by nothing else. It
    was added by #170 opening nothing at all, precisely so that each widening
    has to be written here deliberately rather than found to have passed
    already - the three panels still to come are the same list again.

    Driven over `https://` because that is the only way in (the check below is
    the other half); the admin password still opens every one of them, since a
    delegation that could lock the Admin out is not a delegation.
    """
    head("a capability password opens its own endpoint and no other")
    db = fresh_db()
    _caps(manage_records="mrpw", ssl_cert="certpw",
          import_archive="archivepw", server_config="cfgpw",
          server_settings="setpw")
    tid = add_txn(db, asset_number="NS-9")
    # An Own Password on the row, so /auth/change_password gets as far as
    # checking the password rather than refusing for having none to change.
    conn = sqlite3.connect(db)
    conn.execute("UPDATE team_members SET password_hash=?,"
                 " must_change_password=1 WHERE name='Brian Dawson'",
                 (stored_form("amrpw"),))
    conn.commit()
    conn.close()
    every = ("mrpw", "certpw", "archivepw", "cfgpw", "setpw")
    c = M.app.test_client()
    HTTPS = "https://localhost"

    # Each remote endpoint, against the one password that opens it and the
    # three that must not. `opens` is what the capability is for; anything else
    # has to be 401 and not 403, since the connection was fine and the
    # credential was not.
    doors = [
        ("POST /transactions/delete", "mrpw",
         lambda pw: c.post("/transactions/delete", base_url=HTTPS,
                           json={"password": pw, "ids": []})),
        ("POST /transactions/modify", "mrpw",
         lambda pw: c.post("/transactions/modify", base_url=HTTPS,
                           json={"password": pw, "id": tid})),
        ("POST /records/import", "archivepw",
         lambda pw: c.post("/records/import", base_url=HTTPS,
                           json={"password": pw})),
        ("GET /admin/server_config", "cfgpw",
         lambda pw: c.get("/admin/server_config", base_url=HTTPS,
                          json={"password": pw})),
        ("POST /admin/server_config", "cfgpw",
         lambda pw: c.post("/admin/server_config", base_url=HTTPS,
                           json={"password": pw, "host": "0.0.0.0",
                                 "port": 9091})),
        # The three Engineer doors (#171). Each is asked with a body it will
        # refuse - a blank name, no id - so that what is measured is which
        # credential got past the door and nothing is written by a check about
        # who may write.
        ("POST /members", "setpw",
         lambda pw: c.post("/members", base_url=HTTPS,
                           json={"password": pw, "name": "",
                                 "auto_approve": 0})),
        ("POST /members/delete", "setpw",
         lambda pw: c.post("/members/delete", base_url=HTTPS,
                           json={"password": pw, "name": ""})),
        ("POST /members/rename", "setpw",
         lambda pw: c.post("/members/rename", base_url=HTTPS,
                           json={"password": pw})),
        # The five mail doors (#172), the second of `server_settings`' areas.
        # The same capability rather than a fifth one, which is the decision
        # that ticket made - so they are written out here beside the Engineer
        # doors rather than in a list of their own, and the assertion below is
        # the one that matters either way: no other capability opens them.
        ("GET /admin/mail", "setpw",
         lambda pw: c.get("/admin/mail", base_url=HTTPS,
                          json={"password": pw})),
        ("POST /admin/mail", "setpw",
         lambda pw: c.post("/admin/mail", base_url=HTTPS,
                           json={"password": pw, "host": "relay.local",
                                 "port": 587, "from": "assets@example.com"})),
        ("POST /admin/mail/test", "setpw",
         lambda pw: c.post("/admin/mail/test", base_url=HTTPS,
                           json={"password": pw, "to": ""})),
        ("GET /admin/notify_rules", "setpw",
         lambda pw: c.get("/admin/notify_rules", base_url=HTTPS,
                          json={"password": pw})),
        ("POST /admin/notify_rules", "setpw",
         lambda pw: c.post("/admin/notify_rules", base_url=HTTPS,
                           json={"password": pw, "rules": "not a list"})),
        # The three Client doors (#174), the fourth and last of
        # `server_settings`' areas. The two writes are asked with a body they
        # will refuse - no client_id, nothing staged - so what is measured is
        # which credential got past the door and no machine is commanded by a
        # check about who may command one.
        ("GET /clients", "setpw",
         lambda pw: c.get("/clients", base_url=HTTPS,
                          json={"password": pw})),
        ("POST /clients/command", "setpw",
         lambda pw: c.post("/clients/command", base_url=HTTPS,
                           json={"password": pw})),
        ("POST /clients/push_cert", "setpw",
         lambda pw: c.post("/clients/push_cert", base_url=HTTPS,
                           json={"password": pw})),
    ]
    for name, opens, call in doors:
        for pw in every:
            r = call(pw)
            if pw == opens:
                # Past the door. Several of these then refuse the *request* -
                # no ids, nothing to correct, no file - which is the point:
                # what is asserted here is which credential got through, and a
                # 401 is the only answer that means it did not.
                eq("%s opens on %s" % (name, pw), r.status_code == 401, False)
            else:
                eq("%s refuses %s" % (name, pw), r.status_code, 401)
        r = call("admin")
        eq("%s still opens on the admin password" % name,
           r.status_code == 401, False)

    # And the admin-only doors, against all four. Rule 7 is the last of them
    # and the reason the list is written out rather than sampled.
    for pw in every:
        r = c.post("/lookup/upload", base_url=HTTPS,
                   json={"password": pw, "file_data": ""})
        eq("POST /lookup/upload refuses it", r.status_code, 401)
        r = c.post("/admin/verify", base_url=HTTPS, json={"password": pw})
        eq("POST /admin/verify says it is not the admin",
           r.get_json().get("valid"), False)
        r = c.post("/admin/change_password", base_url=HTTPS,
                   json={"current_password": pw, "new_password": "letmein"})
        eq("POST /admin/change_password refuses it (rule 7)",
           r.status_code, 401)
        r = c.post("/auth/verify", base_url=HTTPS,
                   json={"name": "Brian Dawson", "password": pw})
        eq("POST /auth/verify does not call it admin",
           bool(r.get_json().get("admin")), False)
        r = c.post("/auth/change_password", base_url=HTTPS,
                   json={"name": "Brian Dawson", "current_password": pw,
                         "new_password": "takenover"})
        eq("POST /auth/change_password refuses it", r.status_code, 401)
        # `_queue_command` was on this list until #174 put it behind
        # **Server Settings**, the way #171 moved `/members` and #172 the mail
        # routes. What holds it now is the `doors` table above, which is a rule
        # about scope rather than a fixed list: exactly its own capability, and
        # `/lookup/upload` above it is the one that has never moved (rule 11).

    eq("the Own Password is untouched",
       M.password_matches("amrpw", _member_hash(db, "Brian Dawson")), True)
    eq("the Transaction is still there", txn(db, tid) is not None, True)
    # A holder named, so the entry below can be read for the name rather than
    # only for the capability: a credential the Admin wrote a name beside is
    # the whole of what R1's identity half buys.
    M.ADMIN_CFG["capability_holders"] = {"manage_records": "Ops on-call"}
    r = c.post("/transactions/delete", base_url=HTTPS,
               json={"password": "mrpw", "ids": [tid]})
    eq("and the capability password really does delete", r.status_code, 200)
    conn = sqlite3.connect(db)
    gone = conn.execute("SELECT COUNT(*) FROM transactions WHERE id=?",
                        (tid,)).fetchone()[0]
    conn.close()
    eq("the row is gone", gone, 0)

    # The act is on the record, attributed to the delegate rather than to the
    # Admin - which is the half a status code cannot show, and the half that
    # cannot be reconstructed afterwards, the rows being what stopped existing.
    rows = [r for r in log_rows(db) if r["event"] == "transaction.deleted"]
    eq("one transaction.deleted entry", len(rows), 1)
    eq("naming the delegate rather than the Admin",
       rows[-1]["actor"], 'Delegate: Manage Transaction History held by '
                          '"Ops on-call" (remote)')
    acts = [r for r in log_rows(db) if r["event"] == "remote.action"]
    eq("and every use of a capability wrote remote.action before it",
       len(acts) > 0 and acts[-1]["level"], "warn")


def check_the_engineer_doors_answer_to_the_server_settings_password():
    """#171, and the three things a status code above cannot show.

    The boundary group one door up asserts **which** credential gets through
    each of these; this one asserts what happens on the other side of it, which
    is where the cost of this delegation actually is:

    * every act is attributed to the **delegate**, not to the Admin - a
      capability password is a credential rather than a person, and an
      Engineer deleted by a delegate recorded as the Admin's doing is the same
      defect #74 fixed at the console;
    * an Own Password set remotely is **Temporary** exactly as one set at the
      console is (ADR-0009), because both go through `_set_member_password` -
      the arming cannot hold at one door and quietly not at the other;
    * a rename rewrites `transactions.team_member` and **not** `system_log`
      (ADR-0016), which is `_rename_member`'s rule and has to survive being
      reached from somewhere new.

    The ADR-0017 create-only path is asserted beside them, since it is the one
    thing on `POST /members` that had to be left exactly as it was: a body with
    no `password` key at all is still the Storekeeper's, and a wrong password is
    still a wrong password rather than a quiet downgrade into it.
    """
    head("the Engineer doors on the Server Settings password")
    db = fresh_db()
    _caps(server_settings="setpw")
    M.ADMIN_CFG["capability_holders"] = {"server_settings": "Ops on-call"}
    ACTOR = 'Delegate: Server Settings held by "Ops on-call" (remote)'
    c = M.app.test_client()
    HTTPS = "https://localhost"

    r = c.post("/members", base_url=HTTPS,
               json={"password": "setpw", "name": "Nadia Fouad",
                     "auto_approve": 0})
    eq("the delegate adds an Engineer", r.status_code, 200)
    rows = [x for x in log_rows(db) if x["event"] == "member.saved"]
    eq("attributed to the delegate rather than the Admin",
       rows[-1]["actor"], ACTOR)

    # An Own Password, through the same helper the console's card writes
    # through - so it arrives armed, which is the whole of the reset path.
    r = c.post("/members", base_url=HTTPS,
               json={"password": "setpw", "name": "Nadia Fouad",
                     "auto_approve": 0, "member_password": "firstpw"})
    eq("and sets an Own Password", r.status_code, 200)
    row = [m for m in c.get("/members").get_json()
           if m["name"] == "Nadia Fouad"][0]
    eq("which is Temporary, as one set at the console is",
       (row["has_password"], row["must_change_password"]), (True, True))
    rows = [x for x in log_rows(db) if x["event"] == "member.password_set"]
    eq("and that entry names the delegate too", rows[-1]["actor"], ACTOR)

    # A Transaction against her, so the rename has something to carry.
    tid = add_txn(db, asset_number="NS-11", team_member="Nadia Fouad")
    r = c.post("/members/rename", base_url=HTTPS,
               json={"password": "setpw", "id": row["id"],
                     "name": "Nadia Fouad-Hassan"})
    eq("the delegate renames her", r.status_code, 200)
    eq("her Transaction came with her",
       txn(db, tid)["team_member"], "Nadia Fouad-Hassan")
    rows = [x for x in log_rows(db) if x["event"] == "member.renamed"]
    eq("one member.renamed entry", len(rows), 1)
    eq("naming the delegate", rows[-1]["actor"], ACTOR)
    # The audit trail is not edited to agree with a later decision: the older
    # entries still say what they said at the time.
    saved = [x for x in log_rows(db) if x["event"] == "member.saved"]
    eq("and the earlier entries still carry the name of the day",
       "Nadia Fouad-Hassan" in (saved[-1]["detail"] or ""), False)

    r = c.post("/members/delete", base_url=HTTPS,
               json={"password": "setpw", "name": "Nadia Fouad-Hassan"})
    eq("and deletes her", r.status_code, 200)
    rows = [x for x in log_rows(db) if x["event"] == "member.deleted"]
    eq("attributed to the delegate", rows[-1]["actor"], ACTOR)
    eq("her Transaction is untouched", txn(db, tid) is not None, True)

    # Every one of those wrote a remote.action before it ran.
    acts = [x for x in log_rows(db) if x["event"] == "remote.action"]
    eq("four remote.action entries, one per call", len(acts), 4)
    eq("each at warn", sorted({x["level"] for x in acts}), ["warn"])

    # ADR-0017, untouched: no key at all is the Storekeeper's create-only
    # path, and `password: ""` is an attempt at a credential.
    r = c.post("/members", json={"name": "Rami Nabil", "auto_approve": 0})
    eq("no password key at all is still the create-only path",
       r.status_code, 200)
    r = c.post("/members", base_url=HTTPS,
               json={"password": "", "name": "Rami Two", "auto_approve": 0})
    eq('and password: "" is a wrong password, not an absent one',
       r.status_code, 401)
    r = c.post("/members", base_url=HTTPS,
               json={"password": "setpw", "name": "Rami Nabil",
                     "auto_approve": 0, "profile": "custom",
                     "permissions": ["view_all_history"]})
    eq("the delegate may edit where the Storekeeper may only create",
       r.status_code, 200)


def check_the_engineer_doors_tell_the_two_credentials_apart_over_http():
    """Which of the two is a remote-channel credential here, and which is not.

    The three `/members` doors are the second endpoint to use
    `_remote_admit`'s `admin_is_native` after `POST /transactions/cancel`
    (ADR-0015), and this is the group that says why it is not a convenience:

    * the **capability** password is replayed rather than compared, so over a
      connection this server cannot see encrypted it is refused `insecure`
      wherever it arrives - the whole of what keeps #171's delegation to
      HTTPS;
    * the **admin** password is this door's own, as it has been since these
      routes existed, and plain HTTP is the default deployment (rule 1). A
      transport gate in front of it would have made a route every install
      already has HTTPS-only for a channel this ticket added, which is a
      wire-compat break dressed as a security tightening - a pre-S3
      Storekeeper mid-rollout still sends it.

    So the two get different answers to the same request, and the whole point
    is that they are told apart. The create-only path is asserted beside them
    for completeness: it carries no credential at all, so there is nothing for
    a transport gate to protect (ADR-0017).
    """
    head("the Engineer doors over plain http")
    db = fresh_db()
    _caps(server_settings="setpw")
    c = M.app.test_client()
    aid = [m for m in c.get("/members").get_json()
           if m["name"] == "Brian Dawson"][0]["id"]
    doors = (("/members", {"name": "", "auto_approve": 0}),
             ("/members/delete", {"name": ""}),
             ("/members/rename", {}))
    for path, body in doors:
        r = c.post(path, json=dict(body, password="setpw"))
        eq("POST %s refuses the capability password over http" % path,
           r.status_code, 403)
        eq("and says why rather than calling it wrong",
           (r.get_json() or {}).get("code"), "insecure")
        r = c.post(path, json=dict(body, password="admin"))
        eq("while the admin password is this door's own and still opens it",
           r.status_code == 403, False)
    eq("nothing was written by any of that",
       [m["name"] for m in c.get("/members").get_json()],
       ["Alice Carter", "Brian Dawson", "Carol Evans", "David Foster"])
    r = c.post("/members", json={"name": "Rami Nabil", "auto_approve": 0})
    eq("and the create-only path is untouched over http", r.status_code, 200)

    # The admin password over plain http really does the work, which is the
    # wire-compat half: a pre-S3 Storekeeper sends exactly this.
    r = c.post("/members", json={"password": "admin", "name": "Rami Nabil",
                                 "auto_approve": 1, "profile": "custom",
                                 "permissions": ["view_all_history"]})
    eq("an Admin edits an Engineer over plain http as they always could",
       r.status_code, 200)
    rows = [x for x in log_rows(db) if x["event"] == "member.saved"]
    eq("recorded as the Admin, not as a remote delegate",
       rows[-1]["actor"], "Admin")
    r = c.post("/members/rename", json={"password": "admin", "id": aid,
                                        "name": "Brian Dawson-Fouad"})
    eq("and renames one", r.status_code, 200)
    r = c.post("/members/delete", json={"password": "admin",
                                        "name": "Rami Nabil"})
    eq("and deletes one", r.status_code, 200)

    acts = [x for x in log_rows(db) if x["event"] == "remote.action"]
    eq("the admin password wrote no remote.action, it being this door's own "
       "credential rather than a remote-channel one", acts, [])
    refused = [x for x in log_rows(db) if x["event"] == "remote.refused"]
    eq("one remote.refused per capability password turned away", len(refused),
       3)


def check_the_permission_captions_are_served_rather_than_copied():
    """`GET /permissions`, and why it needs no credential. #171.

    Rule 8 says the Permission names live in `server.py` and no client carries
    a copy, and Remote Admin's Engineers panel has to draw a tick per
    Permission with a caption on it. Without this route that panel would either
    ship a second copy of `PERMISSION_LABELS` - the drift `cascade-audit.py`
    fails an app for - or show an Admin a row of bare names.

    No credential, for `GET /members`' reason one step on: every `/members`
    answer already carries the names, so what this adds is the caption.
    """
    head("the Permission captions are served")
    fresh_db()
    c = M.app.test_client()
    r = c.get("/permissions")
    eq("served with no password at all", r.status_code, 200)
    got = r.get_json()
    eq("one entry per Permission, in PERMISSIONS' own order",
       [p["name"] for p in got], list(M.PERMISSIONS))
    eq("each captioned as PERMISSION_LABELS captions it",
       [p["label"] for p in got],
       [M.PERMISSION_LABELS.get(n, n) for n in M.PERMISSIONS])
    eq("and nothing but the two keys",
       sorted({k for p in got for k in p}), ["label", "name"])


def check_a_capability_password_is_never_accepted_over_http():
    """The other half, and the one no status code on a working system shows.

    A capability password is **replayable** - unlike everything else this
    server checks, which is a salted hash it compares against (ADR-0008) - so
    it crossing a plain `http://` connection is the credential itself on the
    wire. There is no smaller version of that to fall back to, so it is a
    refusal rather than a downgrade, and it is refused **before** the password
    is examined, so a correct one over HTTP is no different from a wrong one.

    `403 insecure` rather than `401`: the credential was not the problem and an
    answer saying it was would send whoever holds it looking for a typo.

    The admin password is held to the same rule, for the reason it is held to
    every other one here: it opens more, not less.
    """
    head("a capability password is never accepted over http")
    db = fresh_db()
    _caps(manage_records="mrpw", import_archive="archivepw",
          server_config="cfgpw")
    tid = add_txn(db, asset_number="HT-1")
    c = M.app.test_client()

    for pw in ("mrpw", "admin"):
        r = c.post("/transactions/delete", json={"password": pw, "ids": [tid]})
        eq("POST /transactions/delete over http refuses %s" % pw,
           r.status_code, 403)
        eq("with the code that says why", r.get_json().get("code"), "insecure")
    r = c.post("/records/import", json={"password": "archivepw"})
    eq("POST /records/import over http refuses it", r.status_code, 403)
    r = c.post("/admin/server_config", json={"password": "cfgpw",
                                             "host": "0.0.0.0", "port": 9091})
    eq("POST /admin/server_config over http refuses it", r.status_code, 403)

    eq("and the Transaction is still there", txn(db, tid) is not None, True)
    refused = [r for r in log_rows(db) if r["event"] == "remote.refused"]
    eq("each refusal is on the record", len(refused), 4)
    eq("at warn", refused[0]["level"], "warn")
    eq("and none of them names the password that was sent",
       any(pw in (r["detail"] or "")
           for r in refused for pw in ("mrpw", "cfgpw", "archivepw")), False)

    # Under IIS the hop into this process is loopback HTTP, TLS having ended at
    # the site, so `request.is_secure` is false for every legitimate request on
    # the whole supported deployment (ADR-0001). `iis.json` carrying a bound
    # thumbprint is the second signal, and the one that makes this feature
    # reachable at all there; a file naming no thumbprint is a site nothing was
    # bound to and is not it.
    # _iis_host is server_iis.py's since #243, and _remote_tls_ok reads it
    # as that module's own global through _iis_tls_bound rather than
    # through server.py's namespace, so the patch below has to land on IM.
    real = IM._iis_host
    try:
        IM._iis_host = lambda: {"site": "AssetManager",
                                "cert_thumbprint": "AABBCC"}
        r = c.post("/admin/server_config", json={"password": "cfgpw",
                                                 "host": "0.0.0.0",
                                                 "port": 9091})
        eq("behind an IIS site with a certificate bound, it is accepted",
           r.status_code, 200)
        IM._iis_host = lambda: {"site": "AssetManager"}
        r = c.post("/admin/server_config", json={"password": "cfgpw",
                                                 "host": "0.0.0.0",
                                                 "port": 9091})
        eq("an iis.json naming no thumbprint is still refused",
           r.status_code, 403)
    finally:
        IM._iis_host = real


def check_auth_verify_is_the_one_door_a_client_knocks_on():
    """The contract common.verify_password rests on.

    The clients ask this one endpoint and read three things out of the answer:
    whether the password was accepted, whether what was accepted was the admin
    password, and what the engineer's profile allows. The Notifier's Settings
    gate is built out of exactly those three, and the installer's is about to
    be, so each has to hold on its own rather than only in combination.
    """
    head("/auth/verify, the client-facing door")
    fresh_db()
    _caps()
    c = M.app.test_client()

    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "auto_approve": 0, "profile": "custom",
                                 "permissions": "view_all_history",
                                 "member_password": "amrpw"})
    eq("an engineer can be given an own password", r.status_code, 200)

    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "amrpw"})
    d = r.get_json()
    eq("their own password is accepted", (r.status_code, d.get("valid")),
       (200, True))
    eq("it is not reported as the admin password", bool(d.get("admin")), False)
    eq("their profile comes back with it",
       "view_all_history" in (d.get("permissions") or []), True)

    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "admin"})
    d = r.get_json()
    eq("the admin password is accepted for them too", d.get("valid"), True)
    eq("and reports itself as the admin password", d.get("admin"), True)
    eq("an admin is not limited by their profile",
       sorted(d.get("permissions") or []), sorted(M.PERMISSIONS))

    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "wrong"})
    eq("a wrong password is refused", r.status_code, 401)

    # The refusal has to be a 401 and not a 404: the clients fall back to
    # /admin/verify on a 404, taking it to mean the server predates this
    # endpoint, so a wrong password answered with 404 would be retried as an
    # admin password and refused a second time for the wrong reason.
    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "wrong"})
    eq("and is not a 404, which the clients read as an old server",
       r.status_code == 404, False)

    r = c.post("/auth/verify", json={"name": "Carol Evans",
                                     "password": "amrpw"})
    eq("one engineer's own password is not another's", r.status_code, 401)

    r = c.post("/auth/verify", json={"name": "Carol Evans", "password": ""})
    eq("an engineer with no own password is not opened by an empty one",
       r.status_code, 401)

    r = c.post("/auth/verify", json={"name": "Nobody At All",
                                     "password": "amrpw"})
    eq("a name that is not an engineer is refused", r.status_code, 401)

    # A capability password is a console credential and reaches no endpoint
    # (ADR-0006). This is the door a client knocks on, so it is the one that
    # would matter most if that ever stopped being true.
    _caps(manage_records="mrpw", ssl_cert="certpw",
          import_archive="archivepw", server_config="cfgpw",
          server_settings="setpw")
    for pw in ("mrpw", "certpw", "archivepw", "cfgpw", "setpw"):
        r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                         "password": pw})
        eq("a capability password (%s) is refused outright" % pw,
           r.status_code, 401)


def check_admin_verify_is_the_admin_door_alone():
    """What refuses an engineer's own password. Nothing in a client does.

    common.verify_admin_password exists so three callers cannot accept one -
    standing up a Storekeeper, pointing a Notifier at a server, opening the
    Storekeeper's Server Settings - and an engineer who could open any of those
    could configure a Notifier as somebody else and then answer that person's
    Transactions. But no client code enforces it: the client's whole
    contribution is to knock on this door instead of /auth/verify, and this is
    the door that says no. So this is where the property lives, and the stubbed
    client-side group below can only prove which door was knocked on.

    A capability password is refused here too, asserted where every other
    endpoint's refusal of one is (ADR-0006), not repeated here.
    """
    head("/admin/verify, the admin door alone")
    fresh_db()
    _caps()
    c = M.app.test_client()

    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "auto_approve": 0,
                                 "member_password": "amrpw"})
    eq("an engineer can be given an own password", r.status_code, 200)

    # (r.get_json() or {}) throughout this group: an endpoint that raised
    # answers 500 with no body, and a bare .get() there fails on an
    # AttributeError instead of on the assertion that names the behaviour.
    r = c.post("/admin/verify", json={"password": "admin"})
    eq("the admin password opens it",
       (r.status_code, (r.get_json() or {}).get("valid")), (200, True))

    # The one the two-doors split rests on. /auth/verify accepts this same
    # password for this same engineer - the group above asserts that - so the
    # two doors giving the same answer here is the failure to catch.
    r = c.post("/admin/verify", json={"password": "amrpw"})
    eq("an engineer's own password does not",
       (r.status_code, (r.get_json() or {}).get("valid")), (401, False))

    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "amrpw"})
    eq("while the other door does accept it, which is the contrast",
       (r.get_json() or {}).get("valid"), True)

    r = c.post("/admin/verify", json={"password": ""})
    eq("nor does an empty password",
       (r.status_code, (r.get_json() or {}).get("valid")), (401, False))

    r = c.post("/admin/verify", json={})
    eq("nor an absent one", (r.get_json() or {}).get("valid"), False)


def check_the_two_client_password_doors():
    """common.py's two password doors: which one gets knocked on, and when.

    The client half of the group above. Three of its four legs can be reached
    from a live server, but the one that matters most cannot: a server that
    predates /auth/verify answers 404, and no such server exists to point at
    any more. So the transport is stubbed and the URLs it was asked for are
    recorded - what is being checked is *which door was knocked on*, which is
    the whole of the behaviour and is invisible from the return value alone.

    A 401 deliberately does not fall back. A wrong password is not an old
    server, and retrying it against /admin/verify would produce two refusals
    and name the wrong reason for the second. An unreachable server raises
    rather than returning refused, so the caller can tell "could not check"
    from "wrong password" - the installer's two paths and the Notifier's
    Settings gate all report those differently.
    """
    head("common.py's two password doors, from the client side")

    class Answer(object):
        def __init__(self, status, payload):
            self.status_code = status
            self.ok = 200 <= status < 300
            self._payload = payload

        def json(self):
            return self._payload

    asked = []

    def stub(*answers):
        """Replace common's transport; answer in order, record every URL."""
        queue = list(answers)
        del asked[:]

        def fake_api(method, url, **kw):
            asked.append(url)
            if not queue:
                # A door this case did not allow for. Answering keeps the
                # failure on the assertion that names the behaviour - the
                # URL list - rather than on an IndexError in here, which
                # is what a planted 401-falls-back defect first reported.
                return Answer(599, {})
            nxt = queue.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        C.api = fake_api

    _real_api = C.api
    try:
        base = "http://server:8081"

        # 1. The endpoint is there and accepts: its own answer comes back, whole.
        stub(Answer(200, {"valid": True, "admin": False, "profile": "custom",
                          "permissions": ["view_all_history"]}))
        d = C.verify_password(base, "Brian Dawson", "amrpw")
        eq("an accepted own password returns the server's own answer",
           d, {"valid": True, "admin": False, "profile": "custom",
               "permissions": ["view_all_history"]})
        eq("and one door was knocked on", asked, [base + "/auth/verify"])

        # 2. A refusal is a refusal. It must NOT be retried as an admin
        #    password: two refusals, the second naming the wrong reason.
        stub(Answer(401, {"valid": False}))
        d = C.verify_password(base, "Brian Dawson", "wrong")
        eq("a 401 refuses", d.get("valid"), False)
        eq("a 401 does not fall back to /admin/verify",
           asked, [base + "/auth/verify"])

        # 3. A server that predates the endpoint: 404, then the admin password.
        stub(Answer(404, {}), Answer(200, {"valid": True}))
        d = C.verify_password(base, "Brian Dawson", "admin")
        eq("a 404 falls back and the admin password is accepted",
           d.get("valid"), True)
        eq("what it accepted is reported as the admin password",
           d.get("admin"), True)
        eq("the fallback claims no permissions", d.get("permissions"), [])
        eq("both doors, in that order",
           asked, [base + "/auth/verify", base + "/admin/verify"])

        # 4. The old server refuses too: refused, not an exception.
        stub(Answer(404, {}), Answer(200, {"valid": False}))
        eq("a 404 then a refusal is a refusal",
           C.verify_password(base, "Brian Dawson", "nope").get("valid"), False)
        stub(Answer(404, {}), Answer(401, {"valid": False}))
        eq("a 404 then a 401 is a refusal too",
           C.verify_password(base, "Brian Dawson", "nope").get("valid"), False)

        # 5. Every refusal is the same shape, so a caller reading .get("admin")
        #    or .get("permissions") off one never reads None.
        stub(Answer(401, {"valid": False}))
        d = C.verify_password(base, "Brian Dawson", "wrong")
        eq("a refusal is fully shaped",
           (d.get("admin"), d.get("profile"), d.get("permissions")),
           (False, "default", []))

        # 6. Unreachable raises. Returning refused here would report a network
        #    failure as a wrong password, and both installs would then tell
        #    somebody to go and find a password that was never the problem.
        stub(IOError("connection refused"))
        try:
            C.verify_password(base, "Brian Dawson", "amrpw")
            bad("an unreachable server did not raise")
        except IOError:
            ok("an unreachable server raises rather than refusing")

        # ---- the admin-only door (#23) --------------------------------------
        # Three callers must not accept an engineer's own password: standing up
        # a Storekeeper, pointing a Notifier at a server, and opening the
        # Storekeeper's Server Settings. What refuses an own password is
        # /admin/verify itself, so the client's whole contribution is to knock
        # on that door and never on /auth/verify - which is what these assert.
        # The refusal itself is proved over real HTTP, not here.
        stub(Answer(200, {"valid": True}))
        eq("the admin password opens the admin-only door",
           C.verify_admin_password(base, "admin"), True)
        eq("and only /admin/verify was asked",
           asked, [base + "/admin/verify"])

        stub(Answer(200, {"valid": False}))
        eq("a refusal is False, not a dict to misread",
           C.verify_admin_password(base, "amrpw"), False)
        eq("and it did not then try /auth/verify",
           asked, [base + "/admin/verify"])

        stub(Answer(401, {"valid": False}))
        eq("a 401 is False too", C.verify_admin_password(base, "nope"), False)

        # There is no fallback here and there must not be one: /admin/verify has
        # existed for as long as the endpoint set has, so a second request could
        # only ever be to a door that accepts more than this caller wants.
        stub(Answer(404, {}))
        eq("a 404 is refused rather than falling back anywhere",
           C.verify_admin_password(base, "admin"), False)
        eq("still one door", asked, [base + "/admin/verify"])

        stub(IOError("connection refused"))
        try:
            C.verify_admin_password(base, "admin")
            bad("an unreachable server did not raise from the admin door")
        except IOError:
            ok("the admin door raises when the server cannot be reached")
    finally:
        C.api = _real_api


def check_changing_the_admin_password_is_never_delegable():
    """Both doors: the endpoint and the dialog."""
    head("changing the admin password")
    _caps(manage_records="mrpw", ssl_cert="certpw",
          import_archive="archivepw", server_config="cfgpw",
          server_settings="setpw")
    c = M.app.test_client()
    for pw in ("mrpw", "certpw", "archivepw", "cfgpw", "setpw"):
        r = c.post("/admin/change_password",
                   json={"current_password": pw, "new_password": "letmein"})
        eq("the endpoint refuses %s" % pw, r.status_code, 401)
    eq("the admin password is untouched",
       bool(M._authorise("ssl_cert", "admin")), True)

    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if "change_admin_password" not in fns:
        bad("change_admin_password is gone")
        return
    seg = _code(fns["change_admin_password"])
    if "_authorise" in seg:
        bad("the dialog calls _authorise - a capability password would then "
            "change the admin password, which is the admin password with an "
            "extra step")
    else:
        ok("the dialog compares against the admin hash directly")
    if "_admin_password_ok(" in seg:
        ok("and it is the admin password it checks")
    else:
        bad("the dialog does not check the admin password")
    # The console itself rather than the menu that used to sit between:
    # 077 deleted both hubs, and Capability Passwords is an entry on the
    # People section beside Change Admin Password rather than a button
    # behind a door in front of both.
    console = _code(fns["run_gui"]) if "run_gui" in fns else ""
    if "capability_passwords(" in console:
        ok("and Capability Passwords is an entry of the console's own, "
           "beside Change Admin Password rather than inside it")
    elif "capability_passwords(" in seg:
        bad("Change Admin Password still carries the way to Capability "
            "Passwords - both are entries in the console now, not one inside "
            "the other")
    else:
        bad("nothing reaches capability_passwords() - the dialog that sets a "
            "remote credential is unreachable")


def check_a_password_length_bound_is_never_a_literal():
    """Every door that refuses a short password names the constant.

    PASSWORD_MIN and CAPABILITY_MIN exist so the bound is one fact, and the
    comment on the first says why: an Own Password must not end up held to a
    looser bound than the admin password by an edit nobody noticed. The
    Server GUI's Change Admin Password dialog carried the literal 4 instead -
    in the check and in the caption under the field - which is the same drift
    pointing the other way, and the worse direction of the two: that dialog is
    rule 7's only door for the admin password, and the admin password is what
    every capability password is measured against.

    Source rather than behaviour for the dialog's half: it is a Tk callback no
    harness reaches, and what is asserted is the absence of a second copy of
    the number. The behaviour half below is what proves the constant is live
    rather than decorative - raise it and the endpoints move.
    """
    head("a password length bound is never a literal")

    # SRC_ENG_ALL: `_save_member` is one of the six doors below and has been in
    # the Engineers register since #217. The positive half of this check names
    # all six, so a text without it reports a door that stopped naming the
    # constant rather than one that moved file.
    tree = ast.parse(SRC_ENG_ALL)

    # Innermost enclosing function, not any enclosing one: do_change sits
    # inside change_admin_password inside run_gui, so asking which function a
    # node is *in* answers three times for one comparison - the same shape
    # that made the Add Transaction actor check match by call node.
    inner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for n in ast.walk(fn):
                inner[n] = fn

    def _is_len(x):
        return (isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                and x.func.id == "len")

    named, literal = set(), []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Compare) and len(n.ops) == 1
                and isinstance(n.ops[0], (ast.Lt, ast.LtE))):
            continue
        if not _is_len(n.left):
            continue
        fn = inner.get(n)
        right = n.comparators[0]
        # PASSWORD_MIN stays in server.py, so a compare against it inside
        # server_gui.py reads S.PASSWORD_MIN (#207) - still a name, just
        # through the bind() seam rather than the module's own scope.
        if ((isinstance(right, ast.Name) and right.id.endswith("_MIN"))
                or (isinstance(right, ast.Attribute)
                    and right.attr.endswith("_MIN")
                    and isinstance(right.value, ast.Name)
                    and right.value.id == "S")):
            named.add(fn.name if fn else "(module)")
        elif isinstance(right, ast.Constant) and isinstance(right.value, int):
            # A length bound is only this check's business where the code
            # around it is about a password - len(q) < 2 on a search box and
            # len(row) < 3 on a spreadsheet column are not.
            seg = _code(fn) if fn else ""
            if "assword" in seg or "assword" in (fn.name if fn else ""):
                literal.append("%s (line %d): %s"
                               % (fn.name if fn else "(module)", n.lineno,
                                  ast.unparse(n)))

    if literal:
        bad("a password length is written as a number in " + ", ".join(literal))
    else:
        ok("no door compares a password against a number of its own")

    # The positive half, so this cannot pass by finding nothing: these are the
    # six doors, and every one of them has to still be here. A seventh is the
    # moment somebody should look at this list.
    # do_change is Change Admin Password's own Save callback, which is
    # what innermost means here: the dialog it belongs to is
    # change_admin_password and the window around that is run_gui, and
    # naming either of those would answer for every other bound they
    # enclose as well.
    want = {"_set_capability_password", "_set_member_password", "_save_member",
            "auth_change_password", "admin_change_password", "do_change"}
    eq("the six doors that refuse a short password all name the constant",
       sorted(named), sorted(want))

    # The caption under the field is the other copy, and it was wrong in the
    # same dialog: "min 4 characters" over a check that had stopped being 4
    # would be worse than either half alone.
    said = [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and re.search(r"(min|at least)\s+\d+\s*char", n.value, re.I)]
    if said:
        bad("a window states the bound as a number: "
            + "; ".join("line %d %r" % s for s in said))
    else:
        ok("every window states the bound with %d from the constant")

    # And the behaviour half: the constant is what the endpoints actually
    # read, so raising it moves them. Without this the group would assert
    # nothing but the spelling of a number nobody uses. Nothing here changes
    # the admin password - the one call that would succeed is left unmade,
    # since ADMIN_CFG is this module's and the groups after this one read it.
    _caps()
    fresh_db()
    c = M.app.test_client()
    c.post("/members", json={"password": "admin", "name": "Bound Tester",
                             "auto_approve": 0, "member_password": "hunter2"})
    was = M.PASSWORD_MIN
    try:
        M.PASSWORD_MIN = 8
        r = c.post("/admin/change_password",
                   json={"current_password": "admin", "new_password": "1234"})
        eq("/admin/change_password refuses four characters at eight",
           r.status_code, 400)
        eq("and says so with the raised number", "8" in r.get_json()["error"],
           True)
        r = c.post("/members", json={"password": "admin",
                                     "name": "Bound Tester",
                                     "auto_approve": 0,
                                     "member_password": "1234"})
        eq("POST /members refuses four characters at eight", r.status_code, 400)
        payload, status = M._set_member_password("Bound Tester", "1234",
                                                 "admin")
        eq("the Engineer's card refuses it too", status, 400)
        eq("in the same words", "8" in payload["error"], True)
    finally:
        M.PASSWORD_MIN = was
    payload, status = M._set_member_password("Bound Tester", "1234", "admin")
    eq("and four characters is taken again at four", status, 200)


def check_the_two_silent_actions_now_ask():
    """Server Settings - host/port and the certificate - asked for nothing at all.

    They asked for nothing, then for a password of their own (two doors,
    change_host_port and upload_ssl_cert), then merged into one window and
    still ask for nothing - which is a different nothing, and the
    difference is the whole of what this holds. The door is
    `_console_unlock` at the point the window opens (ADR-0015), so what each
    callback below may assume is that the admin password has already been
    proved; what it may not do is carry a field of its own, because a
    console that asked twice is the defect the door removed.

    A GUI callback no harness can drive, so this stays a source check, the
    same as the two certificate paths above it.
    """
    head("the two actions behind the console door")
    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for fn, writer in (("do_save_cfg", "_save_server_cfg"),
                       ("do_install", "_save_server_cfg"),
                       ("do_remove", "os.remove")):
        if fn not in fns:
            bad("%s is gone" % fn)
            continue
        seg = ast.unparse(fns[fn])
        if "_authorise(" in seg or "_admin_password_ok(" in seg:
            bad("%s checks a password of its own, inside a console the door "
                "has already opened" % fn)
        else:
            ok("%s takes the door's answer" % fn)
        if writer in seg:
            ok("  and it is still what %s" % ("writes the config"
                                              if "cfg" in writer
                                              else "touches the files"))
        else:
            bad("  but it no longer %s" % ("writes the config"
                                           if "cfg" in writer
                                           else "touches the files"))
    for name in ("server_settings",):
        seg = ast.unparse(fns[name])
        if "_pw_caption(" in seg or "_authorise(" in seg:
            bad("%s still carries a password field behind the door" % name)
        else:
            ok("%s carries no password field of its own" % name)
        if console_door("Server Settings") == "admin" \
                and "_console_unlock(" not in seg:
            ok("  and its entry asks at the door, every open (096)")
        else:
            bad("  and its entry is not the admin door it asks through")

    # The lock column is a claim about behaviour, so it is read out of the
    # list itself rather than out of its text.
    acts = None
    for node in ast.walk(fns["run_gui"]):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SECTIONS"
                for t in node.targets):
            acts = node.value
    if acts is None:
        bad("the SECTIONS list is gone")
        return
    # (section name, entries), and an entry is
    # (label, subtitle, asks-for-a-password, function). The lock flag was the
    # fourth of five on the action row's tuple and is the third of four here;
    # what it means did not move with it.
    marks = {e.elts[0].value: e.elts[2].value
             for sec in acts.elts for e in sec.elts[1].elts}
    # Server Settings asks on every open since 096 ("admin"), Import
    # Transaction Archive once a sitting (True); both ask.
    for label, want in (("Server Settings", "admin"),
                        ("Import Transaction Archive", True)):
        eq("the console marks %s as asking for a password" % label,
           marks.get(label), want)
    # Manage Transaction History is not an entry since 088 but the
    # Transactions section's pane, so it carries no flag here to read. Its
    # door moved inside it rather than going: the group holding the three
    # console actions to `_console_unlock` still finds it in `manage_records`.
    eq("Manage Transaction History is the Transactions pane, not an entry",
       "Manage Transaction History" in marks, False)
    eq("and Display Settings asks for nothing, since it changes what this "
       "window shows rather than what the server does",
       marks.get("Display Settings"), False)
    # Copy URL is a button in the health banner now, beside the URL it
    # copies, and not an action here as well. It was both, two controls
    # calling one function, so this asserts the row does not take it back.
    eq("Copy Server URL is not one of the entries",
       "Copy Server URL" in marks, False)

    # The hover line is the only thing an entry says about *which* password,
    # and four of these open on a capability password too, so it must not
    # name the admin one. It moved off the action row and onto the section
    # entry with 077; it is the same sentence on the same status line.
    seg = _code(fns["run_gui"])
    if "asks for the admin password" in seg:
        bad("the console's hover line still promises the admin password")
    elif "asks for a password" in seg:
        ok("and the hover line says a password, not the admin password")
    else:
        bad("the console no longer says a locked entry asks for anything")



def check_exporting_the_certificate_carries_the_public_half_only():
    """Export writes the certificate and never the key (C5).

    `ssl_cert.pem` and `ssl_key.pem` sit beside each other in the install
    directory with names one character apart, and the moment somebody reaches
    for one is the moment a client will not connect and they are in a hurry.
    So the export is a control rather than a sentence telling an admin to copy
    a file - and the refusal is the whole of the feature, because the failure
    it prevents is silent: anybody holding the key impersonates this server to
    every client that pinned the certificate, and rule 1's fail-closed client
    would be verifying them perfectly happily.

    Two answers to that rather than one, and both are asserted: a source
    holding a `PRIVATE KEY` block is **refused**, the same refusal
    `package.ps1` and `bundle-client.ps1` carry over anything they stage; and
    only the certificate blocks are **written**, so material this does not
    recognise stays behind rather than travelling in a file called
    ssl_cert.pem on somebody's laptop.

    Behaviour rather than source, unlike the two groups either side of it: the
    refusal is in `_export_public_cert`, which takes paths and touches no Tk,
    precisely so the thing that must not be got wrong is reachable by a gate.
    The window around it is the Tk callback, and what is asserted of that is
    that it calls this and writes the entry.
    """
    head("exporting the certificate carries the public half only (C5)")

    der = b"the certificate, as far as a digest is concerned"
    body = base64.b64encode(der).decode()
    cert = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n"
            % body)
    key = ("-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----\n"
           % base64.b64encode(b"the key that must never travel").decode())

    src_path = os.path.join(STAGE, "export-src.pem")
    dest = os.path.join(STAGE, "exported.pem")

    def write_source(text):
        with io.open(src_path, "w", encoding="utf-8") as f:
            f.write(text)

    def read_dest():
        if not os.path.exists(dest):
            return None
        with io.open(dest, encoding="utf-8") as f:
            return f.read()

    for stale in (dest,):
        if os.path.exists(stale):
            os.remove(stale)

    # -- the ordinary export ---------------------------------------------
    write_source(cert)
    got = M._export_public_cert(dest, src_path)
    eq("the export answers with the fingerprint of what it wrote",
       got, M._cert_fingerprint(src_path))
    eq("  colon-separated, the form both the window and the prompt show",
       (got or "").count(":"), 31)
    eq("  and uppercase, the form openssl prints",
       got == (got or "").upper(), True)
    eq("  and what landed is the same certificate",
       M._cert_fingerprint(dest), got)

    # -- a key in the source is the refusal this exists for ---------------
    os.remove(dest)
    write_source(cert + key)
    try:
        M._export_public_cert(dest, src_path)
        bad("a source holding a private key was exported")
    except ValueError as ex:
        ok("a source holding a private key is refused")
        eq("  saying so rather than saying failed",
           "private key" in str(ex).lower(), True)
    eq("  and nothing at all was written", read_dest(), None)

    # The key first, so a refusal that only looked at the tail would miss it.
    write_source(key + cert)
    try:
        M._export_public_cert(dest, src_path)
        bad("a key before the certificate was exported")
    except ValueError:
        ok("wherever in the file the key sits")
    eq("  still nothing written", read_dest(), None)

    # -- only the certificate blocks travel -------------------------------
    write_source("# notes an operator left here\nSECRET=hunter2\n" + cert
                 + "\ntrailing material\n")
    got = M._export_public_cert(dest, src_path)
    out = read_dest() or ""
    eq("a source carrying other material still exports",
       got, M._cert_fingerprint(src_path))
    eq("  and only the certificate blocks were written",
       out.strip(), cert.strip())
    eq("  so nothing beside them travelled",
       ("hunter2" in out) or ("trailing" in out), False)

    # -- a chain travels whole --------------------------------------------
    issuer = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n"
              % base64.b64encode(der + b"issuer").decode())
    write_source(cert + issuer)
    got = M._export_public_cert(dest, src_path)
    eq("a chain is exported whole", (read_dest() or "").count(
        "-----BEGIN CERTIFICATE-----"), 2)
    eq("  and is still named by its leaf", got, M._cert_fingerprint(src_path))

    # -- nothing to export -------------------------------------------------
    os.remove(dest)
    write_source("this is not a certificate")
    try:
        M._export_public_cert(dest, src_path)
        bad("a file with no certificate in it was exported")
    except ValueError as ex:
        ok("a file with no certificate in it is refused")
        eq("  and says that, not that a key was found",
           "private key" in str(ex).lower(), False)
    eq("  with nothing written", read_dest(), None)

    try:
        M._export_public_cert(dest, os.path.join(STAGE, "no-such-file.pem"))
        bad("an absent source was exported")
    except ValueError:
        ok("an absent source is refused rather than raising OSError")

    if os.path.exists(dest):
        os.remove(dest)

    # -- and the window around it -----------------------------------------
    # Source, the control being a Tk callback behind a save dialog no harness
    # can answer. What is asserted is that it goes through the helper above
    # rather than copying the file itself, and that it leaves the record of
    # which certificate left this machine.
    fns = {n.name: n for n in ast.walk(ast.parse(SRC_ALL))
           if isinstance(n, ast.FunctionDef)}
    if "export_cert" not in fns:
        bad("Server Settings has no export control any more")
        return
    body_src = ast.get_source_segment(SRC_ALL, fns["export_cert"]) or ""
    eq("the control goes through the one exporter",
       "_export_public_cert(" in body_src, True)
    eq("  rather than copying the file itself",
       ("shutil.copy" in body_src) or ("SSL_KEY_PATH" in body_src), False)
    eq("  and writes the entry naming what left",
       "cert.exported" in body_src, True)

    exporters = [n for n in ast.walk(ast.parse(SRC_ALL))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_export_public_cert"]
    eq("with one caller, so there is no second way out",
       len(exporters), 1)


def _windows_of(src):
    """Every `Toplevel` in a source, with the function it is created in.

    Shared by the two halves below rather than written twice: what is being
    asserted is a property of the whole set, so the set has to be derived from
    the file rather than listed here - a list is what would still say
    thirty-nine the first time somebody adds a fortieth window.
    """
    found = []

    def walk(node, func):
        for field in ("body", "orelse", "finalbody", "handlers"):
            got = getattr(node, field, None)
            if not isinstance(got, list):
                continue
            for stmt in got:
                if not isinstance(stmt, ast.AST):
                    continue
                inner = func
                if isinstance(stmt, ast.FunctionDef):
                    inner = stmt
                elif (isinstance(stmt, ast.Assign)
                      and isinstance(stmt.value, ast.Call)
                      and (getattr(stmt.value.func, "attr", None)
                           or getattr(stmt.value.func, "id", None))
                      == "Toplevel"):
                    found.append((stmt.lineno,
                                  ast.unparse(stmt.targets[0]),
                                  func.name if func else "<module>"))
                walk(stmt, inner)

    walk(ast.parse(src), None)
    found.sort()
    return found


def _escape_bound_in(src):
    """The variable each `ui_kit.escape_closes` call names, and its argument."""
    out = {}
    for n in ast.walk(ast.parse(src)):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "escape_closes"):
            var = ast.unparse(n.args[0]) if n.args else ""
            arg = ast.unparse(n.args[1]) if len(n.args) > 1 else ""
            out.setdefault(var, []).append((n.lineno, arg))
    return out


def check_esc_closes_every_window_the_console_opens():
    """Esc closes a sub-window, by the route its X already takes (G4).

    There was no Escape binding anywhere in this product, so every dialog had
    to be closed by finding its Close button - and the Server GUI is the app
    that stacks them, five deep off one console.

    **Source**, and deliberately: what is asserted is that the binding is on
    every window, which is a claim about a set of twenty-five Tk callbacks
    behind an admin password no harness can answer. Opening each one to press
    a key is what `client-checks.py` does for the three windows there that can
    be built without a server; here the set is the thing worth holding, since
    the way this defect comes back is a twenty-sixth window being added
    without it rather than an existing one losing it.

    Three claims. **Every** `Toplevel` in this file takes the binding, the
    root window aside - Esc is a dismissal and the Server GUI is not
    dismissable. **Every** one of those bindings goes to its own window's
    close and to nothing above it: there is no console-wide close left for
    an Esc to reach (089), so a binding naming one would be naming something
    this file no longer defines. And each window that registered a close
    with `_track_unsaved` passes **that** close, for the same reason: a
    second route out of a window that asks before discarding a change is the
    route that does not ask.
    """
    head("Esc closes every window the console opens (G4)")

    wins = _windows_of(SRC_ALL)
    bound = _escape_bound_in(SRC_ALL)
    eq("the Server GUI still opens the windows this is about",
       len(wins) >= 25, True)

    missing = [(ln, var, fn) for ln, var, fn in wins
               if not any(l > ln for l, _ in bound.get(var, []))]
    eq("every window in server.py binds Esc", missing, [])

    root_bound = [v for v in bound if v == "root"]
    eq("and the Server GUI itself does not - Esc is not how it closes",
       root_bound, [])

    calls = [c for v in bound for c in bound[v]]
    eq("  with one binding per window and no second one",
       len(calls), len(wins))

    # The five windows that ask before discarding. There was a sixth
    # binding here until 077: `server_administration` was a Toplevel of its
    # own and its Esc went through `_console_close`, which asked about every
    # window that console had left open before shutting the door on them.
    # 077 deleted that window - the bar is its column of entries six times
    # over - and the console is the main window now, which hides to the tray
    # rather than closing, so the event that behaviour hung on stopped
    # happening. 089 deleted the function itself, with `_console_unsaved`
    # beside it: a typed change is protected by the window holding it, not
    # by a console above it, which is the half the five entries below are.
    #
    # So the absence is permanent, and what is asserted is that neither
    # function is **defined** rather than that the name is absent from the
    # source: the comment recording why they went says both of them, and a
    # substring check would read its own explanation as the defect.
    gone = sorted(n.name for n in ast.walk(ast.parse(SRC_ALL))
                  if isinstance(n, ast.FunctionDef)
                  and n.name in ("_console_close", "_console_unsaved"))
    eq("the Server GUI defines no console-wide close any more", gone, [])

    # Counted off the calls rather than off the pairs they make: four of the
    # five name their window `win` and their close `close`, so a set of those
    # two spellings holds two entries and would have read five as two.
    tracked = [(ast.unparse(n.value.args[0]), ast.unparse(n.targets[0]))
               for n in ast.walk(ast.parse(SRC_ALL))
               if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Name)
               and n.value.func.id == "_track_unsaved"]
    eq("the windows that ask before discarding are still five",
       len(tracked), 5)
    for var, close in sorted(set(tracked)):
        eq("  a window whose close is %s passes it to Esc" % close,
           any(arg == close for _l, arg in bound.get(var, [])), True)
    eq("  and that is every one of them",
       sum(1 for v in bound for _l, arg in bound[v] if arg), 5)

    # And the binding itself is the kit's, never a global.
    eq("nothing here binds Esc on its own",
       'bind("<Escape>"' in SRC_ALL, False)
    eq("  and nothing binds it on every window at once",
       'bind_all("<Escape>"' in SRC_ALL, False)


def check_the_certificate_fingerprint_is_shown():
    """Server Settings shows the fingerprint of what GET /cert serves.

    Two halves. The **value**: the digest is over the DER bytes between the
    PEM markers, which is what openssl prints and what whoever is holding the
    other copy will have computed. Hashing the file's text instead gives a
    number that looks exactly as right and matches nothing, which is the one
    failure worth pinning here - so the DER is chosen by this check rather
    than asked of server.py, and the expected string is built from it.

    And the **window**: the group that measures every dialog opens this one
    with no certificate beside the server, which is the branch where this
    block does not exist at all. So it is opened here with one - through the
    action row's own pill, since server_settings is a top-level
    function reached that way (#125) rather than called directly - and
    forced short afterwards,
    because the window carries no written size and its Install/Remove
    buttons are what the certificate half is for.

    No password on the way in, and no endpoint: the certificate is public and
    GET /cert already serves it to anybody who asks, so a console display of
    it is not a second door. That is asserted as one caller, which is also
    what keeps this off the API.
    """
    head("the certificate's SHA-256 fingerprint")

    der = b"these bytes are the certificate, as far as a digest is concerned"
    want = hashlib.sha256(der).hexdigest().upper()
    want = ":".join(want[i:i + 2] for i in range(0, len(want), 2))
    pem = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n"
           % base64.b64encode(der).decode())

    with io.open(M.SSL_CERT_PATH, "w", encoding="utf-8") as f:
        f.write(pem)
    eq("the fingerprint is the DER's digest, colon-separated uppercase hex",
       M._cert_fingerprint(), want)
    if M._cert_fingerprint() == hashlib.sha256(
            pem.encode()).hexdigest().upper():
        bad("it is the digest of the file's text, which matches nothing "
            "anybody else will compute")
    else:
        ok("and not of the file's text, which would match nothing")

    # A chain: the leaf comes first and is the one a Client compares.
    issuer = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n"
              % base64.b64encode(der + b"issuer").decode())
    with io.open(M.SSL_CERT_PATH, "w", encoding="utf-8") as f:
        f.write(pem + issuer)
    eq("a chain is measured at its leaf", M._cert_fingerprint(), want)

    eq("an absent file has no fingerprint rather than a wrong one",
       M._cert_fingerprint(os.path.join(STAGE, "no-such-cert.pem")), None)
    with io.open(os.path.join(STAGE, "junk.pem"), "w", encoding="utf-8") as f:
        f.write("this is not a certificate")
    eq("nor has a file with no certificate in it",
       M._cert_fingerprint(os.path.join(STAGE, "junk.pem")), None)

    # Every caller is the console. Three of them are Server Settings:
    # server_settings draws the fingerprint block, and do_install and
    # do_remove nested inside it name the outgoing certificate in the System
    # Log entry each writes. The fourth is Connected Clients' repaint (C2),
    # which is the same file read for the opposite direction - not what this
    # server is serving, but whether each Client would still be able to verify
    # it - and it is the console too. A fingerprint *endpoint* would be a
    # second way to ask a question the file already answers, and that is what
    # this list is holding the door against - not the count.
    # Innermost enclosing function, not any enclosing one: server_settings
    # sits inside run_gui and do_install and do_remove inside it, so asking
    # which function a call is *in* answers three times for one call site -
    # the same shape the password-bound check above is written around.
    # Three modules since #207: the two routes are in server.py, the console
    # itself in server_gui.py, and the four callers inside the lifecycle in
    # server_cert.py. The question this asks - who may read this file at
    # all - is about all three, not about one file.
    callers = set()
    for text in (SRC, GUI_SRC, CERT_SRC):
        tree = ast.parse(text)
        inner = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    inner[n] = fn
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_cert_fingerprint"):
                fn = inner.get(n)
                callers.add(fn.name if fn else "(module)")
    # The staged certificate (C1, ADR-0020) adds three, and all three are
    # this same console: _stage_new_cert answers with the fingerprint of what
    # it wrote, and show_staged and generate_cert nested inside server_settings
    # draw it and report it. Still no endpoint, which is what this list is
    # about.
    # C3 adds two more, and both are this same console again: `push_cert`
    # shows the Admin the fingerprint it is about to queue a command for, and
    # `_push_next_cert` reads it to refuse where nothing is staged and to name
    # it in the `cert.pushed` entry. Still no endpoint - the list is about who
    # may ask this question, and a route that answered it would be a server
    # measuring its own file on a caller's behalf.
    # C4 adds two, and both are this same console a third time: `cut_over`
    # shows the Admin the fingerprint it is about to serve, and `_cut_over_cert`
    # reads both sides of the swap - the staged one to refuse where nothing is
    # staged, the live one to name in the `cert.cutover` entry and to refuse a
    # cutover that has already happened. Still no endpoint.
    # #174 adds the **first endpoint** to this list, and it is a read of the
    # server own two fingerprints rather than a new question: `GET /clients`
    # answers `served` and `staged` beside the registry, so the panel drawing
    # it can say what the Certificate column means and whether there is
    # anything to push at all - which is what the console reads the same two
    # for. The sentence above about a server measuring its own file on a
    # caller behalf is the one that moved, and it moved because the caller
    # here is an Admin holding a credential rather than anybody who can reach
    # the port: that route is never open. A certificate, never the key.
    eq("only Server Settings, the exporter, the push, the cutover and the "
       "registry read it",
       sorted(callers),
       ["_cut_over_cert", "_export_public_cert", "_push_next_cert",
        "_stage_new_cert", "cut_over", "do_install", "do_remove",
        "generate_cert", "list_clients", "load_rows",
        "push_cert",
        "server_settings", "show_staged"])

    with io.open(M.SSL_CERT_PATH, "w", encoding="utf-8") as f:
        f.write(pem)
    tk = tk_or_skip()
    if tk is None:
        os.remove(M.SSL_CERT_PATH)
        return

    fresh_db()
    root = gui_root(tk)
    # server_settings is a top-level function, like manage_records beside
    # it, so it is reached the way that one is too: by opening its entry on
    # the console, not by a direct module call. Off the action row's pill
    # until 077 deleted the row; `open_section_entry` puts the section on
    # the stage first, which a click on an unmapped row would not.
    before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
    if not open_section_entry(tk, root, "System", "Server Settings"):
        bad("no Server Settings entry on the console's System section")
        root.destroy()
        os.remove(M.SSL_CERT_PATH)
        return
    dlgs = [w for w in widgets(root)
            if isinstance(w, tk.Toplevel) and str(w) not in before]
    if not dlgs:
        bad("Server Settings did not open")
        root.destroy()
        os.remove(M.SSL_CERT_PATH)
        return
    dlg = dlgs[-1]
    dlg.update_idletasks()

    # Displayed in groups so it can be read aloud, so what is asserted is the
    # pairs rather than the one string - the clipboard is where the canonical
    # single line has to be exact, and that is checked below.
    shown = " ".join(str(w.cget("text")) for w in widgets(dlg)
                     if w.winfo_class() == "Label")
    pairs = want.split(":")
    if all(":".join(pairs[i:i + 8]) in shown for i in range(0, 32, 8)):
        ok("every one of the 32 pairs is on the screen, in reading groups")
    else:
        bad("the fingerprint is not shown in the dialog")

    pills = [w._pill for w in widgets(dlg) if getattr(w, "_pill", None)]
    copies = [p for p in pills if "Copy" in p.full]
    if len(copies) != 1:
        bad("%d copy controls beside the fingerprint, expected 1"
            % len(copies))
    else:
        dlg.clipboard_clear()
        copies[0].command()
        eq("the copy control puts the canonical single line on the clipboard",
           dlg.clipboard_get(), want)

    eq("the dialog is as tall as its own children ask for",
       dlg.winfo_height(), dlg.winfo_reqheight())

    btns = [w for w in widgets(dlg) if w.winfo_class() == "Button"
            and "Install" in str(w.cget("text"))]
    if len(btns) != 1:
        bad("%d Install buttons, expected 1" % len(btns))
    else:
        btn = btns[0]
        for h in (0, 500, 400, 300):
            if h:
                dlg.geometry("440x%d" % h)
            dlg.update_idletasks()
            dlg.update()
            where = "as it opens" if not h else "forced to %dpx" % h
            top = btn.winfo_rooty() - dlg.winfo_rooty()
            if not btn.winfo_ismapped() or btn.winfo_height() < 20:
                bad("%s: the Install button is not usable (mapped=%s h=%d)"
                    % (where, btn.winfo_ismapped(), btn.winfo_height()))
            elif top + btn.winfo_height() > dlg.winfo_height():
                bad("%s: the Install button ends %dpx below the bottom"
                    % (where, top + btn.winfo_height() - dlg.winfo_height()))
            else:
                ok("%s: the Install button is on the screen (y=%d h=%d of "
                   "%dpx)" % (where, top, btn.winfo_height(),
                              dlg.winfo_height()))

    try:
        root.destroy()
    except Exception:
        pass
    # Left behind, the certificate would change what every later group's
    # server thinks it is serving.
    os.remove(M.SSL_CERT_PATH)


def check_a_certificate_change_is_in_the_system_log():
    """Installing or removing one is logged, with the fingerprint, read in time.

    A source check because both are Tk callbacks behind a file dialog no
    harness can answer - and because half of what is asserted is an *order*,
    which no request demonstrates: _cert_fingerprint() has to be read before
    the file is written or deleted. Afterwards there is nothing left to read
    the outgoing certificate from, and the call answers with the incoming one
    under the name of the one it replaced, which is worse than saying nothing.

    Replacing this file strands every Client that pinned the outgoing
    certificate - each loads it as its own trust anchor and fails closed
    against anything else (rule 1), the hourly GET /cert refresh included, so
    somebody has to stand at each machine and confirm the new fingerprint
    (ADR-0010). That is the largest blast radius this console has, and it is
    delegable (ADR-0006). The ssl_enabled key _save_server_cfg writes is not
    this fact: it reads identically on a first switch-on and on a swap.
    """
    head("a certificate change reaches the System Log")
    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for fn, event in (("do_install", "cert.installed"),
                      ("do_remove", "cert.removed")):
        node = fns.get(fn)
        if node is None:
            bad("%s is gone" % fn)
            continue
        seg = _code(node).replace('"', "'")
        if "_log_event('%s'" % event in seg:
            ok("%s writes %s" % (fn, event))
        else:
            bad("%s writes no %s entry - the act that strands every pinned "
                "Client would leave nothing in the log" % (fn, event))
        reads = [n.lineno for n in ast.walk(node)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "_cert_fingerprint"]
        if not reads:
            bad("%s names no fingerprint, which is the whole of what the "
                "entry is for" % fn)
            continue
        if fn == "do_install":
            gone = [n.lineno for n in ast.walk(node)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "open"
                    and n.args
                    and _resolves_to(n.args[0], "SSL_CERT_PATH")]
            verb = "written"
            if len(reads) < 2:
                bad("do_install names one fingerprint - one digest on its own "
                    "does not say which certificate the Clients had pinned, "
                    "which is why update.ps1 names both sides")
            else:
                ok("do_install names the outgoing and the incoming one")
        else:
            gone = [n.lineno for n in ast.walk(node)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "remove"]
            verb = "deleted"
        if not gone:
            bad("%s no longer touches the certificate file - this check is "
                "measuring the wrong function" % fn)
        elif min(reads) < min(gone):
            ok("%s reads the outgoing fingerprint before the file is %s"
               % (fn, verb))
        else:
            bad("%s reads _cert_fingerprint() only after the file is %s, so "
                "what it logs as the outgoing certificate is the incoming "
                "one" % (fn, verb))


def check_the_certificate_is_pinned_only_when_somebody_accepts_it():
    """common.py's bootstrap: what it fetches, what it shows, what it writes.

    The client half of the fingerprint group above, and the reason that one
    builds its expected value from the DER rather than asking server.py: the
    two numbers are compared by a person reading one screen against another,
    so this asserts they are the same string for the same certificate. A
    client that measured the file's text would show a fingerprint that looked
    exactly as right and matched nothing.

    The rest is about what may happen without an answer, which is nothing. No
    callback, a refusal, no Tk loop to ask on and nobody answering are all
    refusals, because the confirmation *is* the security property here
    (ADR-0010): whoever answered for asset-server during a silent
    fetch-and-pin would be pinned for good, and the next Settings unlock would
    hand them the admin password.

    And it asks once per process. The clients tick every 15 seconds, so a
    refusal that could be re-asked is a dialog every 15 seconds until somebody
    clicks OK without reading, which is not a confirmation but training.
    """
    head("the certificate is pinned only when somebody accepts it")

    der = b"these bytes are the certificate, as far as a digest is concerned"
    pem = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n"
           % base64.b64encode(der).decode()).encode()
    want = hashlib.sha256(der).hexdigest().upper()
    want = ":".join(want[i:i + 2] for i in range(0, len(want), 2))

    asked = []
    fetched = []

    def arrange(offer, answer):
        """No certificate on disk, one offer waiting, one answer ready."""
        if os.path.exists(C.SSL_CERT_PATH):
            os.remove(C.SSL_CERT_PATH)
        del asked[:]
        del fetched[:]
        C._cert_asked = False

        def fake_fetch(origin, timeout=6):
            fetched.append(origin)
            return offer
        C._fetch_offered_cert = fake_fetch

        def confirm(fp, url):
            asked.append((fp, url))
            return answer
        C.set_cert_confirm(None if answer is None else confirm)

    _real_fetch = C._fetch_offered_cert
    try:
        # The two fingerprints are one number. server.py measures a file and
        # common.py measures bytes that must not be written yet, so they are
        # separate functions on purpose - the server does not import common.py
        # (rule 10) - which is exactly why they are checked against each other
        # rather than each against itself.
        eq("the client measures the DER, colon-separated uppercase hex",
           C.cert_fingerprint(pem), want)
        with io.open(M.SSL_CERT_PATH, "wb") as f:
            f.write(pem)
        eq("and the server shows the same string for the same certificate",
           C.cert_fingerprint(pem), M._cert_fingerprint())
        os.remove(M.SSL_CERT_PATH)
        if C.cert_fingerprint(pem) == hashlib.sha256(pem).hexdigest().upper():
            bad("the client hashes the file's text, which matches nothing "
                "the server will ever show")
        eq("a body with no certificate in it has no fingerprint",
           C.cert_fingerprint(b"this is not a certificate"), None)
        # Corrupt base64 answered with a digest would be a fingerprint of
        # nothing, and there is no second place to check it against.
        eq("nor has one whose base64 is corrupt",
           C.cert_fingerprint(b"-----BEGIN CERTIFICATE-----\n!!!!\n"
                              b"-----END CERTIFICATE-----\n"), None)

        # An app that registers no confirmation keeps the old behaviour and
        # fails closed. The installer relies on that - it already holds the
        # file - so nothing may be fetched here at all.
        arrange(pem, None)
        C.bootstrap_cert("https://server:8081/health")
        eq("with no way to ask, nothing is fetched", fetched, [])
        eq("and nothing is written", os.path.exists(C.SSL_CERT_PATH), False)

        # Refused: the fingerprint was shown, and the answer was no.
        arrange(pem, False)
        C.bootstrap_cert("https://server:8081/health")
        eq("a refusal writes nothing", os.path.exists(C.SSL_CERT_PATH), False)
        eq("and the fingerprint it showed is the one to compare",
           [fp for fp, _ in asked], [want])
        eq("shown against the server it came from",
           [u for _, u in asked], ["https://server:8081"])

        # One attempt per process, whatever the outcome.
        C.bootstrap_cert("https://server:8081/health")
        eq("a refusal is not re-asked in the same process", len(asked), 1)

        # Accepted: the bytes that were measured are the bytes written.
        arrange(pem, True)
        C.bootstrap_cert("https://server:8081/health")
        eq("an acceptance pins it", os.path.exists(C.SSL_CERT_PATH), True)
        eq("and what is pinned is what was measured",
           io.open(C.SSL_CERT_PATH, "rb").read(), pem)
        C.bootstrap_cert("https://server:8081/health")
        eq("an acceptance is not re-asked either", len(asked), 1)

        # A certificate already on disk is never re-offered: refreshing one is
        # sync_server_cert's, over a connection the current pin verified.
        del asked[:]
        C._cert_asked = False
        C.bootstrap_cert("https://server:8081/health")
        eq("a client that already has one is not asked", asked, [])
        os.remove(C.SSL_CERT_PATH)

        # A server answering /cert with a private key is not a server to pin,
        # and nobody should be asked to accept one: refused before the
        # question is put.
        arrange(pem.replace(b"CERTIFICATE", b"PRIVATE KEY"), True)
        C.bootstrap_cert("https://server:8081/health")
        eq("a private key in the answer is refused without asking", asked, [])
        eq("and writes nothing", os.path.exists(C.SSL_CERT_PATH), False)

        arrange(b"<html>404</html>", True)
        C.bootstrap_cert("https://server:8081/health")
        eq("a body that is not a certificate is refused too", asked, [])
        eq("and that writes nothing either",
           os.path.exists(C.SSL_CERT_PATH), False)

        arrange(None, True)
        C.bootstrap_cert("https://server:8081/health")
        eq("a server that answers nothing writes nothing",
           os.path.exists(C.SSL_CERT_PATH), False)

        # It never raises: the caller is on its way to a request that fails
        # closed on its own, and that failure is the honest one to report.
        arrange(pem, True)

        def explode(fp, url):
            raise RuntimeError("the dialog blew up")
        C.set_cert_confirm(explode)
        C.bootstrap_cert("https://server:8081/health")
        eq("a confirmation that raises pins nothing",
           os.path.exists(C.SSL_CERT_PATH), False)

        # Marshalling onto the Tk thread from a worker, which is where both
        # clients call api() from. No loop to ask on, and nobody answering,
        # are refusals: a certificate must not be pinned by a client nobody
        # was looking at.
        class NoLoop(object):
            def after(self, ms, fn):
                raise RuntimeError("main thread is not in mainloop")

        class Ignores(object):
            def after(self, ms, fn):
                pass

        answers = []

        def in_worker(root, ask, timeout):
            def run():
                answers.append(C.confirm_on_tk_thread(root, ask, timeout))
            t = threading.Thread(target=run)
            t.start()
            t.join(10)
        in_worker(NoLoop(), lambda: True, 5)
        eq("no Tk loop to ask on is a refusal", answers, [False])
        del answers[:]
        in_worker(Ignores(), lambda: True, 0.2)
        eq("nobody answering is a refusal", answers, [False])
    finally:
        C._fetch_offered_cert = _real_fetch
        C.set_cert_confirm(None)
        C._cert_asked = False
        for p in (C.SSL_CERT_PATH, M.SSL_CERT_PATH):
            if os.path.exists(p):
                os.remove(p)


def check_one_connection_in_common_verifies_nothing():
    """Exactly one connection in common.py is unverified, and it fetches /cert.

    A source check, because it is about what *cannot* happen and no request
    demonstrates the absence of a second unverified path. The first contact
    has to be unverified - a self-signed server cannot be verified before its
    certificate is in hand - so the protection is that it is one function,
    reached from one place, carrying one GET of a public file. A verify=False
    handed to requests, or the pinned adapter relaxed, would put that same
    hole within reach of every call in this file: the check-in, the password
    doors, a Transaction.
    """
    head("one connection in common.py verifies nothing, and it fetches /cert")

    src = io.open(os.path.join(R, "common.py"),
                  encoding="utf-8", newline="").read()
    fns = {fn.name: fn for fn in ast.walk(ast.parse(src))
           if isinstance(fn, ast.FunctionDef)}

    eq("only _fetch_offered_cert turns verification off",
       sorted(n for n, fn in fns.items() if "CERT_NONE" in _code(fn)),
       ["_fetch_offered_cert"])
    # Not the literal "verify=False": a session attribute, a keyword in a
    # dict and a setdefault all turn verification off in text that does not
    # contain it, and a check that only saw the literal would wave those
    # through. This planted kw.setdefault("verify", False) and was not caught
    # until the pattern was widened.
    off = re.compile(r"verify\W{0,6}False")
    eq("nothing anywhere hands requests a falsy verify",
       sorted(n for n, fn in fns.items() if off.search(_code(fn))), [])
    eq("only bootstrap_cert reaches it",
       sorted(n for n, fn in fns.items()
              if n != "_fetch_offered_cert"
              and "_fetch_offered_cert(" in _code(fn)),
       ["bootstrap_cert"])
    eq("and only api() reaches that",
       sorted(n for n, fn in fns.items()
              if n != "bootstrap_cert" and "bootstrap_cert(" in _code(fn)),
       ["api"])

    body = _code(fns["_fetch_offered_cert"])
    # Quotes are normalised away because _code unparses the AST, which picks
    # its own; what is being asserted is the verb and the path.
    reqs = [re.sub(r"[\s\"']", "", r)
            for r in re.findall(r"conn\.request\(([^)]*)\)", body)]
    eq("one request crosses it, a GET of /cert", reqs, ["GET,/cert"])
    # Nothing has vouched for what is at the other end, so an unbounded read
    # lets a machine on the network choose how much memory this client uses.
    if re.search(r"\.read\(\s*\)", body):
        bad("the body is read unbounded from an unverified connection")
    else:
        ok("and the body it reads back is capped")


def check_the_console_actions_are_behind_one_door():
    """The three that asked for a password of their own now ask at the door.

    They took one each, and each accepted a capability password for it, until
    ADR-0015: a capability password is the credential for administering this
    server remotely and was never a delegation at this console. So the console
    became one door - `_console_unlock`, the admin password once and every
    control behind it - and what is asserted here is both halves of that.

    The **presence** half is the window: whichever function opens it calls
    `_console_unlock` before it draws anything, so the row's direct entry
    points are covered as well as the menu's. The **absence** half is the
    write: nothing inside them reaches `_authorise` or `_console_actor` any
    more, because there is one credential at this console again and an entry
    that named a Delegate would be naming somebody who cannot get in.
    """
    head("the three console actions are behind one door")
    # Three since 077: Server Administration was the fourth and is gone, its
    # entries having moved onto the sections that name them.
    # _modify_transaction is one of the six written about below and moved into
    # the Transactions register at #216, so the names are gathered over the
    # three texts. `_code` unparses the node, so nothing here reads a segment
    # back out of the string this was parsed from.
    tree = ast.parse(SRC_TXN_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    # Server Settings left this list at 096: its entry asks `_admin_again`
    # on every open, Backup / Restore's door, and the window asks nothing.
    eq("Server Settings is behind the every-open door at its entry",
       console_door("Server Settings"), "admin")
    for fn, what in (("manage_records", "Manage Transaction History"),
                     ("import_archive", "Import Transaction Archive")):
        if fn not in fns:
            bad("%s is gone" % fn)
            continue
        seg = _code(fns[fn])
        if "_console_unlock(" not in seg:
            bad("%s opens with no door on it at all" % fn)
        elif what not in seg:
            bad("%s asks at the door without naming %r, so the prompt cannot "
                "say what is being opened" % (fn, what))
        else:
            ok("%s is behind _console_unlock, named %r" % (fn, what))

    # The write side. These are the callbacks the four windows carry, and
    # _modify_transaction which is the enforcement point behind one of them.
    for fn in ("do_delete", "_modify_transaction", "do_save_cfg",
               "do_install", "do_remove", "import_archive"):
        if fn not in fns:
            bad("%s is gone" % fn)
            continue
        seg = _code(fns[fn]).replace('"', "'")
        if "_authorise(" in seg:
            bad("%s still gates on _authorise - the door has already been "
                "answered by the time it runs" % fn)
        elif "_console_actor(" in seg:
            bad("%s still attributes through _console_actor, which can only "
                "name a Delegate who cannot open this console" % fn)
        else:
            ok("%s takes the door's answer rather than asking again" % fn)

    # The other side of the same line. Changing the admin password is the one
    # control behind the door that still asks: a door that could change the
    # credential it was opened with would be that credential with an extra
    # step (rule 7). The Cancel switch asked too until 096, which took every
    # password but this one out of the windows behind a door; it is held
    # below to asking nothing.
    for fn, why in (("do_change", "changing the admin password"),):
        if fn not in fns:
            bad("%s is gone" % fn)
            continue
        seg = _code(fns[fn]).replace('"', "'")
        if "_authorise" in seg:
            bad("%s goes through _authorise - %s is not delegable" % (fn, why))
        elif "_admin_password_ok(" in seg:
            ok("%s asks for the admin password itself: %s is not something "
               "an already-open door may do unasked" % (fn, why))
        else:
            bad("%s checks neither - %s now asks for nothing" % (fn, why))
    seg = _code(fns["toggle_sk"]) if "toggle_sk" in fns else ""
    eq("toggle_sk asks nothing - the history pane's door already did (096)",
       ("_admin_password_ok(" in seg, "simple_password_prompt(" in seg,
        bool(seg)), (False, False, True))


def check_the_admin_password_is_asked_at_the_door_only():
    """Every window asks at its entry, every open, and not again inside (096).

    Backup / Restore's shape, made the console's: the entry is gated
    `"admin"` - `_admin_again` on every open - and the window behind it has
    no admin password field. Change Admin Password is the one entry that
    still asks inside, for rule 7. The register calls those windows make
    reach the enforcement points as `authorised_as`, which is what lets the
    field go without a second door: set, the password is not checked.
    """
    head("the admin password is asked at the door only")
    for label in ("Lookup Sheet", "Asset Sync", "Asset Proposals",
                  "Add Transaction", "Capability Passwords", "Manage Users",
                  "Server Settings", "Database Location", "Mail Settings",
                  "Notification Rules", "Backup / Restore"):
        eq("%s asks at its entry, every open" % label,
           console_door(label), "admin")
    eq("Change Admin Password keeps its own question inside (rule 7)",
       console_door("Change Admin Password"), True)
    for caption in ('text="Admin password', 'text="Admin Password'):
        eq("no console window carries a field captioned %r" % caption[6:],
           caption in GUI_SRC, False)

    fresh_db()
    payload, status = M._set_capability_password(
        "ssl_cert", "certpw", "wrong")
    eq("a wrong admin password still refuses a capability", status, 401)
    payload, status = M._set_capability_password(
        "ssl_cert", "certpw", None, authorised_as="Admin (Server GUI)")
    eq("  and the console's door answer sets one with no password", status,
       200)
    eq("  and it is set", M._capability_state()["ssl_cert"], True)
    M._set_capability_password("ssl_cert", "", None,
                               authorised_as="Admin (Server GUI)")
    eq("  and clears it the same way", M._capability_state()["ssl_cert"],
       False)


def check_the_capability_dialog_is_shaped_right():
    """The window that sets them, and what it deliberately is not.

    **R1 built the remote channel, and this is the repoint that landed with
    it.** The claim used to be that a capability password opened nothing at
    all; three of the four reach an endpoint now (ADR-0015), so what is held
    here is the sentence that is still true and is the one an Admin has to be
    told: these open nothing *at this console*, they are for administering the
    server remotely over HTTPS, and **SSL Certificate is deliberately not one
    of them** - installing a certificate means uploading `ssl_key.pem`, the one
    file that must never travel (rule 1), so that capability stays
    console-only and never becomes remote.

    The absence is the half worth asserting, and it is the half nothing else
    can: an Admin who sets a password on SSL Certificate is entitled to know
    it opens nothing over the network, rather than finding out when the
    delegate cannot use it. Matched on the meaning rather than on the
    sentence, so a rewording does not fail this and a deletion does.

    What no route may still do is name a capability: the three remote doors
    are the ordinary admin endpoints answering a second credential, not new
    `/capability/...` routes, and a route that appeared under that name would
    be a way to read or set the map over the wire.
    """
    head("the Capability Passwords dialog")
    extra = [str(r.rule) for r in M.app.url_map.iter_rules()
             if "capabilit" in str(r.rule).lower()]
    eq("no route names a capability", extra, [])

    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if "capability_passwords" not in fns:
        bad("capability_passwords() is missing")
        return
    seg = _code(fns["capability_passwords"])
    for needle in ("_set_capability_password", "_capability_state",
                   "CAPABILITY_LABELS", "CAPABILITIES", "Clear"):
        if needle in seg:
            ok("the dialog uses %s" % needle)
        else:
            bad("the dialog does not use %s" % needle)
    if "show='" + chr(0x25cf) + "'" in seg:
        ok("every field in it is masked")
    else:
        bad("a password field in it is not masked")
    if "_authorise" in seg:
        bad("the dialog calls _authorise - delegation would then be able to "
            "delegate itself")
    else:
        ok("it does not call _authorise: the admin password only")
    # The warning, matched on the meaning rather than on the sentence, so a
    # rewording does not fail this and a deletion does.
    if "nothing at this console" in seg and "REMOTELY" in seg:
        ok("and it says on its face that these open nothing at this console "
           "and are for administering the server remotely")
    else:
        bad("the dialog does not say what a password set here opens - an "
            "Admin would be handed a credential and left to guess where it "
            "works (ADR-0015)")
    if "HTTPS" in seg:
        ok("and that the channel is HTTPS only")
    else:
        bad("the dialog does not say the remote channel is HTTPS only")
    if "SSL Certificate" in seg and "private key" in seg:
        ok("and that SSL Certificate is deliberately not one of them, "
           "because installing a certificate would mean uploading the key")
    else:
        bad("the dialog does not say SSL Certificate is console-only - an "
            "Admin would set a password on the one capability that can never "
            "be used remotely (rule 1, ADR-0015)")
    if "ssl_cert" in M.CAPABILITY_REMOTE:
        bad("ssl_cert is in CAPABILITY_REMOTE, so the window's promise is "
            "false - installing a certificate remotely means uploading "
            "ssl_key.pem (rule 1)")
    else:
        ok("and the code agrees with it: ssl_cert is not in "
           "CAPABILITY_REMOTE")
    # _rehash_capability_password is the other writer and is not a delegation:
    # it takes a hash, not a password, so it cannot set one - it only rewrites
    # a legacy value in the salted format on the use that proved it (ADR-0008).
    setters = [n for n, f in fns.items()
               if n not in ("_set_capability_password",
                            "_rehash_capability_password")
               and "capability_hashes'] =" in ast.unparse(f)]
    eq("nothing else writes the map", setters, [])
    seg = _code(fns["_rehash_capability_password"])
    if "hash_password(" in seg or "password_matches(" in seg:
        bad("_rehash_capability_password hashes or checks a password - it "
            "takes a hash so that it cannot be a second way to delegate")
    else:
        ok("the rehash writer takes a hash, so it cannot delegate")
