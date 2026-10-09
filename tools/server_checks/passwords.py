r"""Stored passwords: the two formats of ADR-0008 and the upgrade on use.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import sqlite3
import time

from server_checks.stage import (M, SRC_ALL, _member_hash, bad, eq, fresh_db,
                                 head, legacy, ok, stored_form,
                                 write_admin_cfg)



# ── stored passwords ─────────────────────────────────────────────────────────

def check_a_stored_password_is_salted_and_self_describing():
    """The format, and that two installs of the same password differ.

    The whole point of the salt is that one recovered password does not answer
    for the next machine, so the two hashes of one password must not be equal -
    and the stored value has to say how to check it, or a later format change
    needs a migration of the column it lives in.
    """
    head("the stored form of a password")
    first = M.hash_password("hunter2")
    parts = first.split("$")
    eq("four fields", len(parts), 4)
    eq("named by the algorithm", parts[0], "pbkdf2_sha256")
    eq("carrying the iteration count", parts[1], str(M.PBKDF2_ITERATIONS))
    eq("a salt of the stated length", len(parts[2]),
       M.PBKDF2_SALT_BYTES * 2)
    eq("and a sha256-sized digest", len(parts[3]), 64)
    if "hunter2" in first:
        bad("the password itself is in the stored value")
    else:
        ok("the password itself is not in it")
    if M.PBKDF2_ITERATIONS >= 100000:
        ok("the work factor is %d rounds" % M.PBKDF2_ITERATIONS)
    else:
        bad("%d rounds is not a work factor" % M.PBKDF2_ITERATIONS)

    second = M.hash_password("hunter2")
    if first == second:
        bad("two installs given the same password store the same value - one "
            "recovered password would answer for every machine")
    else:
        ok("two installs given the same password store different values")
    eq("with different salts", parts[2] != second.split("$")[2], True)
    eq("and both verify",
       [M.password_matches("hunter2", first),
        M.password_matches("hunter2", second)], [True, True])


def check_a_legacy_hash_still_verifies():
    """A bare 64-hex SHA-256, which is what every existing install holds.

    There is no migration step here to skip: the server sees one password at a
    time, so the old value has to be readable until the password it stands for
    is next used.
    """
    head("a hash written before ADR-0008")
    old = legacy("hunter2")
    eq("64 hex characters, as it was", len(old), 64)
    eq("recognised as legacy", M._is_legacy_hash(old), True)
    eq("the right password verifies", M.password_matches("hunter2", old), True)
    # _is_legacy_hash accepts either case and hexdigest() produces only one, so
    # without a fold an upper-case value is recognised as legacy and then never
    # matches - a lockout dressed up as a wrong password.
    eq("an upper-case legacy hash is recognised",
       M._is_legacy_hash(old.upper()), True)
    eq("  and verifies too", M.password_matches("hunter2", old.upper()), True)
    eq("  while a wrong password still does not",
       M.password_matches("nope", old.upper()), False)
    eq("a wrong one does not", M.password_matches("nope", old), False)
    eq("a wrong one does not against the salted form either",
       M.password_matches("nope", M.hash_password("hunter2")), False)
    eq("an empty stored value matches nothing, not even an empty password",
       [M.password_matches("", ""), M.password_matches("hunter2", "")],
       [False, False])
    # A corrupt stored value has to be a refusal, not a 500: every one of
    # these comes off disk, and compare_digest raises on a non-ASCII str.
    eq("a stored value in neither format matches nothing",
       [M.password_matches("x", "not-a-hash"),
        M.password_matches("x", "pbkdf2_sha256$200000$zz$zz"),
        M.password_matches("x", "pbkdf2_sha256$0$00$00"),
        M.password_matches("x", "pbkdf2_sha256$200000$00$" + chr(0xe9)),
        M.password_matches("x", chr(0xff21) * 64),
        M.password_matches("x", chr(0xff11) * 64)],
       [False] * 6)
    eq("the salted form is not mistaken for a legacy one",
       not M._is_legacy_hash(M.hash_password("hunter2")), True)


def check_a_legacy_admin_password_is_upgraded_on_use():
    """Verifying rewrites it, so an install drains itself.

    Nobody is asked to do anything and there is no step an admin could skip:
    the first use of the password is the only moment the server holds the
    plaintext, so it is the moment the hash is replaced.
    """
    head("a legacy admin password drains itself")
    write_admin_cfg(json.dumps({"password_hash": legacy("hunter2"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()
    c = M.app.test_client()

    r = c.post("/admin/verify", json={"password": "nope"})
    eq("a wrong password is refused against the legacy hash", r.status_code,
       401)
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("  and nothing was rewritten", on_disk["password_hash"],
       legacy("hunter2"))

    r = c.post("/admin/verify", json={"password": "hunter2"})
    eq("the legacy password opens the server", r.status_code, 200)
    eq("  with the reply shape it always had", r.get_json(), {"valid": True})
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("the file was rewritten in the salted format",
       not M._is_legacy_hash(on_disk["password_hash"]), True)
    eq("  and the same password verifies against what replaced it",
       M.password_matches("hunter2", on_disk["password_hash"]), True)
    eq("  while a wrong one still does not",
       M.password_matches("nope", on_disk["password_hash"]), False)
    eq("  and first_run was not disturbed", on_disk.get("first_run"), False)

    upgraded = on_disk["password_hash"]
    eq("a second use still verifies",
       c.post("/admin/verify", json={"password": "hunter2"}).status_code, 200)
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("  and rewrites nothing this time", on_disk["password_hash"], upgraded)

    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()


def check_the_upgrade_cannot_refuse_a_correct_password():
    """A verify path that writes must not fail closed on the write.

    A read-only config file or a locked database is not a wrong password, and
    the legacy hash it leaves in place is upgraded on the next use instead.
    """
    head("a failed rewrite is not a refusal")
    write_admin_cfg(json.dumps({"password_hash": legacy("hunter2"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()
    keep = M.save_admin_cfg

    def explode(_cfg):
        raise OSError("admin_config.json is read-only")

    M.save_admin_cfg = explode
    try:
        eq("the correct password is still accepted",
           M._admin_password_ok("hunter2"), True)
        eq("  and a wrong one still refused",
           M._admin_password_ok("nope"), False)
    finally:
        M.save_admin_cfg = keep
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("the legacy hash is left to be upgraded next time",
       on_disk["password_hash"], legacy("hunter2"))

    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()


def check_a_failed_admin_cfg_write_changes_nothing():
    """The credential in memory and the one on disk move together, or not at all.

    Every writer set the key on ADMIN_CFG and then saved, so a write that
    failed - an install directory the console account cannot write in is how
    that happens - left the new hash in memory and the old one on disk, with
    nothing said at the time. The Admin's own correct current password was
    then refused by Change Admin Password, being checked against a hash nobody
    had been told about yet, and a restart put the old password back. What is
    asserted is the order: the write raises and nothing anywhere has moved.
    """
    head("a failed admin_config.json write changes nothing")
    write_admin_cfg(json.dumps({"password_hash": stored_form("hunter2"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()
    keep = M.save_admin_cfg

    def explode(_cfg):
        raise PermissionError(13, "Permission denied")

    raised = False
    M.save_admin_cfg = explode
    try:
        M._update_admin_cfg(password_hash=stored_form("newone"),
                            first_run=False)
    except PermissionError:
        raised = True
    finally:
        M.save_admin_cfg = keep
    eq("the write failure reaches the caller", raised, True)
    eq("the password that was there still opens the console",
       M._admin_password_ok("hunter2"), True)
    eq("  and the one that was never written does not",
       M._admin_password_ok("newone"), False)
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("  the file holds what it held",
       M.password_matches("hunter2", on_disk["password_hash"]), True)

    # The half that keeps the other honest: a write that lands has to move
    # both copies, or this group would pass against a helper that never
    # changes the password at all.
    M._update_admin_cfg(password_hash=stored_form("newone"), first_run=False)
    eq("a write that lands moves the credential",
       M._admin_password_ok("newone"), True)
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("  on disk as well",
       M.password_matches("newone", on_disk["password_hash"]), True)

    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()


def check_the_credential_follows_the_file():
    """A password changed in one process is the password the next one checks.

    ADMIN_CFG was read once at import, which is right only for the one
    deployment where the console *is* the server. Under IIS and under the
    Windows Service the Server GUI is a second, monitor-only process, so
    Change Admin Password moved the hash on disk and in the console while the
    process serving the port went on checking the one it read at start: the
    console took the new password and every door on the wire went on taking
    the old one, until the app pool was recycled. `POST /admin/verify` is
    what that costs most - it is what the installer asks before it will stand
    up a Storekeeper, so an install done after the change was let in by the
    install-time "admin" and refused what the Admin had set.

    Driven through the endpoint rather than through `_admin_password_ok`,
    because the endpoint is where it was seen and a helper asserted on its
    own would not show that the wire had been left behind. The write is made
    the way another process makes one - straight to the file, never through
    `_update_admin_cfg` - since a write this process made was never the
    problem, and the sleep is there because the change is noticed by the
    file's own timestamp.
    """
    head("the credential follows the file")
    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()
    c = M.app.test_client()
    eq("the password this process started with opens the door",
       c.post("/admin/verify", json={"password": "admin"}).get_json()
       .get("valid"), True)

    # Somebody else - the console, on the machine this is serving on -
    # changes it.
    time.sleep(0.05)
    write_admin_cfg(json.dumps({"password_hash": stored_form("newone"),
                                "first_run": False,
                                "capability_hashes":
                                    {"manage_records":
                                     stored_form("delegated")}}))
    eq("the password that was replaced stops opening it",
       c.post("/admin/verify", json={"password": "admin"}).get_json()
       .get("valid"), False)
    eq("  and the one that replaced it opens it",
       c.post("/admin/verify", json={"password": "newone"}).get_json()
       .get("valid"), True)
    eq("a capability password set the same way opens its own action",
       M._authorise("manage_records", "delegated"), "capability")

    # A file that has gone unreadable leaves the credential exactly as it
    # was: load_admin_cfg refuses to fall back to the install-time default,
    # and this refuses to fall back to anything at all.
    time.sleep(0.05)
    write_admin_cfg("{ not json")
    eq("an unreadable file leaves the working password working",
       c.post("/admin/verify", json={"password": "newone"}).get_json()
       .get("valid"), True)

    # And a write this process makes is still what it was: the sync must not
    # read a half-written file back over a credential it has just set.
    time.sleep(0.05)
    write_admin_cfg(json.dumps({"password_hash": stored_form("newone"),
                                "first_run": False}))
    M._sync_admin_cfg()
    M._update_admin_cfg(password_hash=stored_form("third"), first_run=False)
    eq("a change made here takes effect here",
       c.post("/admin/verify", json={"password": "third"}).get_json()
       .get("valid"), True)
    eq("  and the one it replaced does not",
       c.post("/admin/verify", json={"password": "newone"}).get_json()
       .get("valid"), False)

    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()


def check_the_credential_is_read_through_one_sync():
    """The three doors ask it, and nothing else re-reads the file by hand.

    A source check beside the behaviour one, for the reason every absence
    here is: what must not come back is a second place deciding when the
    credential is stale. `_admin_password_ok` is the admin door,
    `_authorise` reads the capability hashes before it and would answer out
    of a stale map first, and `_update_admin_cfg` syncs so its
    read-modify-write is over what is on disk now.
    """
    head("the credential is read through one sync")
    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}
    for name in ("_admin_password_ok", "_authorise", "_update_admin_cfg"):
        seg = ast.get_source_segment(SRC_ALL, fns[name]) or ""
        eq("%s asks _sync_admin_cfg" % name,
           "_sync_admin_cfg()" in seg, True)
    callers = sorted(n.name for n in fns.values()
                     if n.name not in ("_sync_admin_cfg",
                                       "load_admin_cfg")
                     and "load_admin_cfg()" in
                     (ast.get_source_segment(SRC_ALL, n) or ""))
    if callers:
        bad("these re-read admin_config.json themselves: %s"
            % ", ".join(callers))
    else:
        ok("only _sync_admin_cfg re-reads admin_config.json")

def check_one_writer_for_the_admin_config():
    """Every write to admin_config.json goes through the helper that saves first.

    A source check for check_one_writer_for_the_server_config's reason, and for
    a sharper one: the behaviour check above cannot see a call site it never
    reaches, and four of the six are a GUI callback or a legacy-hash upgrade
    that fires only on an install nobody here has. What is asserted is the
    absence of the shape that was wrong - a function that assigns into
    ADMIN_CFG and then saves it.
    """
    head("one writer for admin_config.json")
    tree = ast.parse(SRC_ALL)
    offenders = []
    for parent in ast.walk(tree):
        if not isinstance(parent, ast.FunctionDef):
            continue
        if parent.name in ("_update_admin_cfg", "load_admin_cfg",
                           "save_admin_cfg"):
            continue
        body = ast.walk(parent)
        writes = [n for n in body
                  if isinstance(n, ast.Subscript)
                  and isinstance(n.value, ast.Name)
                  and n.value.id == "ADMIN_CFG"
                  and isinstance(n.ctx, ast.Store)]
        seg = ast.get_source_segment(SRC_ALL, parent) or ""
        if writes or "save_admin_cfg(" in seg:
            offenders.append("%s (line %d)" % (parent.name, parent.lineno))
    offenders = sorted(set(offenders))
    if offenders:
        bad("these write admin_config.json without _update_admin_cfg: %s"
            % ", ".join(offenders))
    else:
        ok("only _update_admin_cfg writes admin_config.json")


def check_a_legacy_capability_password_is_upgraded_on_use():
    """The same for a delegated action's own password."""
    head("a legacy capability password drains itself")
    write_admin_cfg(json.dumps(
        {"password_hash": legacy("admin"), "first_run": False,
         "capability_hashes": {"ssl_cert": legacy("certpw")}}))
    M.ADMIN_CFG = M.load_admin_cfg()

    eq("it opens its own capability",
       M._authorise("ssl_cert", "certpw"), "capability")
    eq("  and nothing else",
       bool(M._authorise("manage_records", "certpw")), False)
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("it was rewritten in the salted format",
       not M._is_legacy_hash(on_disk["capability_hashes"]["ssl_cert"]),
       True)
    eq("  and still opens that capability",
       M._authorise("ssl_cert", "certpw"), "capability")
    eq("the admin password opens everything, legacy or not",
       [M._authorise(c, "admin") for c in M.CAPABILITIES],
       ["admin"] * len(M.CAPABILITIES))
    on_disk = json.load(io.open(M.ADMIN_CFG_PATH, encoding="utf-8"))
    eq("  and was itself rewritten on the way",
       not M._is_legacy_hash(on_disk["password_hash"]), True)
    payload, status = M._set_capability_password("manage_records", "admin",
                                                 "admin")
    eq("the admin password is still refused as a delegation", status, 400)
    eq("  with the same code as before", payload.get("code"), "same_as_admin")

    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()


def check_a_legacy_own_password_is_upgraded_on_use():
    """An Engineer's Own Password, the one that lives in the database.

    /auth/verify is the only place it is checked and then kept, so it is the
    only place upgrading it is worth anything - /auth/change_password checks
    one too, but replaces it in the same request. The column is not renamed and
    the reply only gains a key, which is what keeps an older client working
    mid-rollout.
    """
    head("a legacy Own Password drains itself")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    conn = sqlite3.connect(db)
    conn.execute("UPDATE team_members SET password_hash=? WHERE name=?",
                 (legacy("amrpw"), "Brian Dawson"))
    conn.commit()
    conn.close()
    c = M.app.test_client()

    eq("/members says the Engineer has a password",
       [m["has_password"] for m in c.get("/members").get_json()
        if m["name"] == "Brian Dawson"], [True])
    eq("  and publishes no hash",
       sorted(c.get("/members").get_json()[0]),
       ["auto_approve", "has_password", "id", "must_change_password", "name",
        "permissions", "profile"])

    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "nope"})
    eq("a wrong Own Password is refused", r.status_code, 401)
    eq("  and the row is untouched", _member_hash(db, "Brian Dawson"),
       legacy("amrpw"))

    r = c.post("/auth/verify", json={"name": "Brian Dawson",
                                     "password": "amrpw"})
    eq("the legacy Own Password verifies", r.status_code, 200)
    eq("  with the reply shape it always had, plus the new key",
       sorted(r.get_json()),
       ["admin", "must_change_password", "permissions", "profile", "valid"])
    eq("  and admin false, as it was", r.get_json().get("admin"), False)
    now = _member_hash(db, "Brian Dawson")
    eq("the row was rewritten in the salted format",
       not M._is_legacy_hash(now), True)
    eq("  and the same password verifies against what replaced it",
       M.password_matches("amrpw", now), True)
    eq("  while a wrong one is still refused",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "nope"}).status_code, 401)
    eq("  and the second use rewrites nothing",
       _member_hash(db, "Brian Dawson"), now)
    eq("an Engineer with no password of their own is still refused",
       c.post("/auth/verify", json={"name": "Carol Evans",
                                    "password": ""}).status_code, 401)
    eq("the admin password still opens their client",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": "admin"}
              ).get_json().get("admin"), True)


def check_a_password_set_through_the_api_is_salted():
    """POST /members must not put a bare digest back in the column."""
    head("a newly set Own Password")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()
    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "member_password": "amrpw"})
    eq("it is set", r.status_code, 200)
    eq("  and reported as a boolean", r.get_json().get("has_password"), True)
    now = _member_hash(db, "Brian Dawson")
    eq("the column holds a salted hash", not M._is_legacy_hash(now), True)
    eq("  which the password verifies against",
       M.password_matches("amrpw", now), True)
    if "amrpw" in now:
        bad("the password itself is in the column")
    else:
        ok("  and the password itself is not in it")
    r = c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                                 "member_password": ""})
    eq("clearing it empties the column", _member_hash(db, "Brian Dawson"), "")
    eq("  and nothing then opens Settings",
       c.post("/auth/verify", json={"name": "Brian Dawson",
                                    "password": ""}).status_code, 401)
