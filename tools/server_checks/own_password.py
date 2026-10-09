r"""The Own Password lifecycle - an Engineer's own credential.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import os
import sqlite3

from server_checks.stage import (M, R, STAGE, _member_hash, add_txn, bad, eq,
                                 fresh_db, head, ok, stored_form, txn)



# ── the Own Password lifecycle ───────────────────────────────────────────────

def _members(c, name):
    """One Engineer's row as GET /members publishes it."""
    return [m for m in c.get("/members").get_json() if m["name"] == name][0]


def _flag(db, name):
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT must_change_password FROM team_members"
                       " WHERE name=?", (name,)).fetchone()
    conn.close()
    return row[0]


def check_the_temporary_flag_arrives_both_ways():
    """must_change_password by migration 006 and by init_db() alike.

    The both-ways pattern every other column here follows: a fresh database and
    an upgraded one must be identical without anybody running migrate, or a new
    install and an old one disagree about whether a password is temporary.
    """
    head("must_change_password, both ways")
    fresh = fresh_db()
    conn = sqlite3.connect(fresh)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(team_members)")]
    conn.close()
    eq("a fresh database has it", "must_change_password" in cols, True)

    # team_members as it stood before this ticket, upgraded by init_db alone.
    old = os.path.join(STAGE, "old_members.db")
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE team_members (
        name TEXT PRIMARY KEY, auto_approve INTEGER DEFAULT 0,
        profile TEXT DEFAULT 'default', permissions TEXT DEFAULT '',
        password_hash TEXT DEFAULT '')""")
    conn.execute("INSERT INTO team_members(name, password_hash)"
                 " VALUES ('Brian Dawson', ?)", (stored_form("amrpw"),))
    conn.commit()
    conn.close()
    M.DB_PATH = old
    M.init_db()
    conn = sqlite3.connect(old)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(team_members)")]
    got = conn.execute("SELECT must_change_password FROM team_members"
                       " WHERE name='Brian Dawson'").fetchone()[0]
    conn.close()
    eq("an upgraded database has it too", "must_change_password" in cols, True)
    # An install written before this had Own Passwords an Admin set, but nobody
    # was ever told they were temporary. Arming them on an upgrade would make
    # every Engineer with a password replace it because of a release.
    eq("and an Own Password that predates it is not made temporary", got, 0)


def check_migration_006_keeps_its_column_on_the_way_down():
    """A downgrade never drops a column.

    Dropping this one would read 0 for every row on the way back up, turning
    every temporary Own Password into a permanent one without saying so.
    """
    head("migration 006")
    path = os.path.join(R, "migrations", "006_own_password_lifecycle.py")
    if not os.path.exists(path):
        bad("migrations/006_own_password_lifecycle.py is missing")
        return
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    for want in ("up", "down"):
        if want in names:
            ok("006 defines %s()" % want)
        else:
            bad("006 does not define %s()" % want)
    down = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "down"][0]
    body = [st for st in down.body if not isinstance(st, ast.Expr)]
    if body and all(isinstance(st, ast.Return) and st.value is None
                    for st in body):
        ok("006's down() is a no-op")
    else:
        bad("006's down() does something - a downgrade never drops a column")
    if "DROP COLUMN" in src.upper() or "DROP TABLE" in src.upper():
        bad("006 drops something")
    else:
        ok("006 drops nothing")

    db = fresh_db()
    mod = {}
    exec(compile(src, path, "exec"), mod)
    conn = sqlite3.connect(db)
    mod["up"](conn)
    mod["up"](conn)
    mod["down"](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(team_members)")]
    conn.close()
    eq("up() twice then down() still leaves the column",
       "must_change_password" in cols, True)


def check_an_admin_set_own_password_is_temporary():
    """POST /members arms the flag, and clearing the password clears it.

    The whole premise of ADR-0009: a password somebody else chose is not the
    Engineer's password yet. And the flag has to come down with the hash, or an
    Engineer with no Own Password is left carrying a demand to replace one that
    does not exist.
    """
    head("an Admin-set Own Password is temporary")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()

    eq("an Engineer with no Own Password is not flagged",
       _members(c, "Brian Dawson")["must_change_password"], False)

    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "member_password": "amrpw"})
    eq("setting one is accepted", r.status_code, 200)
    eq("  and the reply says it is temporary",
       r.get_json().get("must_change_password"), True)
    eq("  as does /members", _members(c, "Brian Dawson")["must_change_password"],
       True)
    eq("  and the column, not something derived", _flag(db, "Brian Dawson"), 1)
    eq("  while has_password is still a boolean",
       _members(c, "Brian Dawson")["has_password"], True)

    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "amrpw"})
    eq("/auth/verify accepts it and says a replacement is due",
       (r.status_code, r.get_json().get("must_change_password")), (200, True))
    eq("  and it is still due after being used", _flag(db, "Brian Dawson"), 1)

    # The convention every field here follows: not sent means not touched.
    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "auto_approve": 1})
    eq("a client that only toggles auto-approve keeps the password",
       (r.get_json().get("has_password"),
        r.get_json().get("must_change_password")), (True, True))

    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "member_password": ""})
    eq("clearing the password clears the flag too",
       (_members(c, "Brian Dawson")["has_password"],
        _members(c, "Brian Dawson")["must_change_password"]), (False, False))
    eq("  in the column as well", _flag(db, "Brian Dawson"), 0)

    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "member_password": "abc"})
    eq("a password shorter than the bound is refused", r.status_code, 400)
    eq("  and nothing was written",
       _members(c, "Brian Dawson")["has_password"], False)
    eq("  the bound being the admin password's own", M.PASSWORD_MIN, 4)

    r = c.post("/members", json={"password": "nope", "name": "Brian Dawson",
                                 "member_password": "amrpw"})
    eq("a wrong admin password sets nothing", r.status_code, 401)
    eq("  and the column is untouched",
       _members(c, "Brian Dawson")["has_password"], False)


def check_an_engineer_replaces_a_temporary_password():
    """The replacement, and that it is what takes the flag down.

    Nothing else does. An Engineer who has replaced their password must not be
    asked again on their next login, and one who has not must be.
    """
    head("an Engineer replaces a temporary Own Password")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()
    c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                             "member_password": "handedover"})

    r = c.post("/auth/change_password",
               json={"name": "Brian Dawson", "current_password": "wrong",
                     "new_password": "chosenbyme"})
    eq("a wrong current password is refused", r.status_code, 401)
    eq("  naming why", r.get_json().get("code"), "bad_password")
    eq("  and the old password still works",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "handedover"}).status_code, 200)

    r = c.post("/auth/change_password",
               json={"name": "Brian Dawson", "current_password": "handedover",
                     "new_password": "abc"})
    eq("a new password shorter than the bound is refused", r.status_code, 400)
    eq("  naming why", r.get_json().get("code"), "too_short")
    eq("  and it is still temporary", _flag(db, "Brian Dawson"), 1)

    r = c.post("/auth/change_password",
               json={"name": "Brian Dawson", "current_password": "handedover",
                     "new_password": "chosenbyme"})
    eq("the replacement is accepted", r.status_code, 200)
    eq("  and reported as no longer due",
       r.get_json().get("must_change_password"), False)
    eq("  the column agreeing", _flag(db, "Brian Dawson"), 0)
    eq("  /members agreeing too",
       _members(c, "Brian Dawson")["must_change_password"], False)

    eq("the new password authenticates",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "chosenbyme"}
              ).get_json().get("must_change_password"), False)
    eq("  and the one it replaced does not",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "handedover"}).status_code, 401)
    now = _member_hash(db, "Brian Dawson")
    eq("what is stored is salted", not M._is_legacy_hash(now), True)
    if "chosenbyme" in now:
        bad("the password itself is in the column")
    else:
        ok("  and the password itself is not in it")

    # Re-arming is the reset path: a new temporary password, asked for again.
    c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                             "member_password": "resetagain"})
    eq("an Admin can re-arm it", _flag(db, "Brian Dawson"), 1)
    eq("  and the Engineer is asked again",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "resetagain"}
              ).get_json().get("must_change_password"), True)


def check_an_engineer_cannot_change_another_engineers_password():
    """One Engineer's password does not open another Engineer's row.

    `name` in the body is not proof of anything and is not meant to be. What
    protects Alice Carter is that the current password is checked against Alice Carter's
    row, so Brian Dawson's password is simply the wrong password there.
    """
    head("an Engineer changes only their own")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()
    c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                             "member_password": "amrpw"})
    c.post("/members", json={"password": "admin", "name": "Alice Carter",
                             "member_password": "acarterpw"})

    r = c.post("/auth/change_password",
               json={"name": "Alice Carter",
                     "current_password": "amrpw",
                     "new_password": "amrtookover"})
    eq("Brian Dawson's password does not open Alice Carter's row", r.status_code, 401)
    eq("  and Alice Carter's password still works",
       c.post("/auth/verify", json={"name": "Alice Carter",
                                    "password": "acarterpw"}).status_code, 200)
    eq("  while the one Brian Dawson tried to set does not",
       c.post("/auth/verify", json={"name": "Alice Carter",
                                    "password": "amrtookover"}).status_code,
       401)
    eq("  and Alice Carter's is still temporary", _flag(db, "Alice Carter"), 1)

    r = c.post("/auth/change_password",
               json={"name": "", "current_password": "amrpw",
                     "new_password": "nowhere"})
    eq("no name at all is refused", (r.status_code,
                                     r.get_json().get("code")),
       (400, "no_name"))
    r = c.post("/auth/change_password",
               json={"name": "Nobody At All", "current_password": "admin",
                     "new_password": "nowhere"})
    eq("an Engineer who does not exist is refused",
       (r.status_code, r.get_json().get("code")), (404, "no_member"))


def check_the_admin_password_is_the_reset_path():
    """The admin password changes an Engineer's Own Password, and marks it.

    That is what an Engineer who has forgotten theirs needs: an Admin proves
    the admin password and a new password is set. What it leaves behind is a
    **Temporary** Own Password, exactly like one set through POST /members,
    because this endpoint is on the network and the admin password proves an
    Admin and nothing about who typed the new password. Clearing it here was
    the one route around ADR-0009 - an Admin could replace an existing Own
    Password from anywhere and the result was never flagged.

    So the mark follows the proof, and both directions are asserted: the
    Engineer's own password takes it down, the admin password puts it up.
    """
    head("the admin password as a reset path")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()
    c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                             "member_password": "forgotten"})

    r = c.post("/auth/change_password",
               json={"name": "Brian Dawson", "current_password": "admin",
                     "new_password": "setoverthephone"})
    eq("the admin password opens the change", r.status_code, 200)
    eq("  and what it leaves is temporary", _flag(db, "Brian Dawson"), 1)
    eq("  which the answer says as well",
       r.get_json().get("must_change_password"), True)
    eq("  the new password authenticating",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "setoverthephone"}
              ).status_code, 200)
    eq("  and the forgotten one no longer doing so",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "forgotten"}).status_code, 401)

    # The Engineer replacing it is what takes the mark down, wherever the
    # password they are replacing came from.
    r = c.post("/auth/change_password",
               json={"name": "Brian Dawson",
                     "current_password": "setoverthephone",
                     "new_password": "chosenatmydesk"})
    eq("the Engineer replacing it clears the mark", r.status_code, 200)
    eq("  the column agreeing", _flag(db, "Brian Dawson"), 0)
    eq("  and they are not asked a second time",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "chosenatmydesk"}
              ).get_json().get("must_change_password"), False)


def check_a_passwordless_engineer_is_unaffected():
    """An Engineer with no Own Password is a normal Engineer, not a broken one.

    Nothing about this lifecycle may reach the endpoints an Engineer actually
    uses: /transactions, /confirm and /reject are unauthenticated on purpose
    (ADR-0002), and an Engineer nobody has given a password is the common case.
    The change endpoint refuses them rather than creating a first password,
    which is what keeps "a password an Admin set is temporary" true with no
    exception - an Admin at a Notifier cannot stand a permanent one up here.
    """
    head("a passwordless Engineer is unaffected")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()

    eq("no password, and no replacement due",
       (_members(c, "Carol Evans")["has_password"],
        _members(c, "Carol Evans")["must_change_password"]), (False, False))

    r = c.post("/auth/change_password",
               json={"name": "Carol Evans", "current_password": "",
                     "new_password": "iwilljustsetone"})
    eq("they cannot set a first one themselves",
       (r.status_code, r.get_json().get("code")), (409, "no_password"))
    r = c.post("/auth/change_password",
               json={"name": "Carol Evans", "current_password": "admin",
                     "new_password": "adminsetsone"})
    eq("nor can an Admin, from here", (r.status_code,
                                       r.get_json().get("code")),
       (409, "no_password"))
    eq("  so nothing was written",
       _members(c, "Carol Evans")["has_password"], False)
    eq("  and the empty column still opens nothing",
       c.post("/auth/verify", json={"name": "Carol Evans",
                                    "password": ""}).status_code, 401)

    # The part that matters: their Transactions are untouched.
    tid = add_txn(db, team_member="Carol Evans", asset_number="NS-1")
    eq("their Transactions still list",
       [t["id"] for t in c.get("/pending/Carol Evans").get_json()], [tid])
    eq("  Confirm still takes no password",
       c.post("/confirm/%d" % tid).status_code, 200)
    eq("  and the row is confirmed", txn(db, tid)["confirmed"], 1)
    tid2 = add_txn(db, team_member="Carol Evans", asset_number="NS-2")
    eq("  Reject still takes no password either",
       c.post("/reject/%d" % tid2, json={"reason": "not mine"}).status_code,
       200)


def check_the_no_password_refusal_names_the_remedy():
    """The 409 must not read as a refusal of the password that was typed.

    The group above asserts that an Admin cannot stand a first Own Password up
    through here, which is the behaviour. This asserts the other half, which is
    what an Admin actually experiences: the refusal fires before either
    password is examined, so the admin password is never wrong here - it is
    never looked at. The Notifier shows the server's `error` verbatim
    (OwnPasswordWindow._submit), so this string is the whole of what reaches
    whoever is standing at that laptop, and a message that only said there was
    nothing to change sent them back to retype a password that had not failed.

    Three things are asserted about the words rather than one, because each is
    a different half of the bug: that the refusal says the typed password was
    not the problem, that it names Manage Users as where the first one is set -
    the Engineer's own card there since A5, the window that used to be named
    having been deleted with its one job moved onto that card - and - the
    regression guard - that it is still the same `no_password` 409 and still
    writes nothing. The wording is matched loosely, on the two
    phrases that carry the meaning, so rephrasing it does not fail this while
    dropping either half does.
    """
    head("the no_password refusal names the remedy")
    fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()

    r = c.post("/auth/change_password",
               json={"name": "David Foster", "current_password": "admin",
                     "new_password": "adminsetsone"})
    body = r.get_json() or {}
    say = (body.get("error") or "")
    eq("the admin password still cannot create a first one",
       (r.status_code, body.get("code")), (409, "no_password"))
    eq("  the Engineer is named", "David Foster" in say, True)
    eq("  it says the typed password was not the problem",
       "whichever password you typed" in say, True)
    eq("  and it names where the first one is set",
       "Manage Users" in say, True)
    eq("  nothing was written", _members(c, "David Foster")["has_password"],
       False)

    # The same words whichever password was typed, since neither is examined:
    # an Engineer's own guess must not get a different story from the Admin's.
    r2 = c.post("/auth/change_password",
                json={"name": "David Foster",
                      "current_password": "not the admin password",
                      "new_password": "adminsetsone"})
    eq("  and the same answer for any other password",
       ((r2.get_json() or {}).get("code"), (r2.get_json() or {}).get("error")),
       ("no_password", say))
