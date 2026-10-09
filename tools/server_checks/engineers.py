r"""The Engineers register: the collation, the id, the rename, the list.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import os
import sqlite3

from server_checks.stage import (M, R, SRC_ENG_ALL, _add_client, _blank_lookup,
                                 _log_rows, add_txn, bad, eq, fresh_db, head,
                                 ok, stage_name, stored_form, txn,
                                 write_server_cfg)


def _members_sql(db):
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'"
                       " AND name='team_members'").fetchone()
    conn.close()
    return (row[0] if row else "") or ""


def _legacy_members_db():
    """A database whose team_members predates the collation, pointed at.

    Built by hand rather than by asking server.py for one: the point of the
    rebuild is to read a table this build would never create, so a helper that
    made one would be a way back to the shape the ticket removed.
    """
    path = stage_name("legacy_", ".db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE team_members (
        name                 TEXT PRIMARY KEY,
        auto_approve         INTEGER DEFAULT 0,
        profile              TEXT    DEFAULT 'default',
        permissions          TEXT    DEFAULT '',
        password_hash        TEXT    DEFAULT '',
        must_change_password INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()
    M.DB_PATH = path
    return path


def check_an_engineer_name_is_matched_without_case():
    """A person typed in a different case is the same person.

    Every failure below was live before this: `_save_member` inserted a second
    Engineer beside the first, `/auth/verify` answered `no_member` to somebody
    who exists, `/pending` returned nothing to a Notifier whose configured name
    was cased differently - an Engineer who stops being asked to confirm
    anything - and the auto-approve read missed the row, so a Transaction for
    an Engineer with no Notifier sat Pending until the 24h pass resolved it.
    """
    head("an Engineer's name is matched without regard to case")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()

    before = len(c.get("/members").get_json())
    r = c.post("/members", json={"password": "admin",
                                 "name": "alice carter",
                                 "auto_approve": 0})
    eq("a re-cased name is accepted", r.status_code, 200)
    names = [m["name"] for m in c.get("/members").get_json()]
    eq("  and adds no second Engineer", len(names), before)
    eq("  it corrects the spelling instead",
       "alice carter" in names, True)

    # Put it back, and give them an Own Password to authenticate with.
    c.post("/members", json={"password": "admin", "name": "Alice Carter",
                             "auto_approve": 0, "member_password": "engineer1"})
    eq("the spelling is back",
       "Alice Carter" in [m["name"] for m in c.get("/members").get_json()],
       True)

    r = c.post("/auth/verify", json={"name": "ALICE CARTER",
                                     "password": "engineer1"})
    eq("/auth/verify answers for a re-cased name",
       (r.status_code, r.get_json().get("valid")), (200, True))
    # The half that must not move with it.
    eq("  the password itself is still case-sensitive",
       c.post("/auth/verify", json={"name": "Alice Carter",
                                    "password": "ENGINEER1"}).status_code, 401)

    # A row written before any of this, carrying whatever case was typed then.
    tid = add_txn(db, team_member="ALICE CARTER", asset_number="CS-1")
    eq("/pending finds an older row under another spelling",
       [t["id"] for t in c.get("/pending/Alice Carter").get_json()], [tid])
    eq("  and so does the history filter",
       [t["id"] for t in
        c.get("/transactions?member=alice%20carter").get_json()], [tid])

    # Auto-approve is read off the row, so it has to be found the same way.
    # The sheet is emptied first, so rule 6 does not refuse a made-up
    # asset before the name is ever looked at.
    _blank_lookup()
    c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                             "auto_approve": 1})
    r = c.post("/transactions", json={"team_member": "brian dawson",
                                      "direction": "Out Store",
                                      "asset_number": "CS-2"})
    new_id = r.get_json()["id"]
    eq("an auto-approve Engineer is found whatever the case",
       (r.status_code, txn(db, new_id)["confirmed"]), (201, 1))
    eq("  and the row records their own spelling, not the caller's",
       txn(db, new_id)["team_member"], "Brian Dawson")

    r = c.post("/transactions", json={"team_member": "Nobody At All",
                                      "direction": "Out Store",
                                      "asset_number": "CS-3"})
    eq("a name no Engineer holds is written as it was sent",
       txn(db, r.get_json()["id"])["team_member"], "Nobody At All")


def check_init_db_gives_the_name_its_collation():
    """Both ways, the pattern every table here uses.

    A fresh database and one upgraded without anybody running migrate must be
    the same database. And the path that runs on every boot must not refuse to
    start over data that was already there - that is the migration's job, being
    the deliberate act somebody is watching.
    """
    head("init_db gives the name its collation")
    db = fresh_db()
    eq("a fresh database has it", "COLLATE NOCASE" in _members_sql(db), True)

    legacy_db = _legacy_members_db()
    conn = sqlite3.connect(legacy_db)
    conn.execute("INSERT INTO team_members(name, auto_approve, profile,"
                 " permissions, password_hash, must_change_password)"
                 " VALUES ('Carol Evans', 1, 'custom', 'view_all_history',"
                 " 'x', 1)")
    conn.commit()
    conn.close()
    M.init_db()
    eq("an older one is rebuilt", "COLLATE NOCASE" in _members_sql(legacy_db),
       True)
    conn = sqlite3.connect(legacy_db)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM team_members WHERE"
                            " name='carol evans'").fetchone())
    conn.close()
    eq("  carrying every value across",
       (row["auto_approve"], row["profile"], row["permissions"],
        row["password_hash"], row["must_change_password"]),
       (1, "custom", "view_all_history", "x", 1))

    # A collision that was already there: warned about, never fatal.
    clash_db = _legacy_members_db()
    conn = sqlite3.connect(clash_db)
    conn.execute("INSERT INTO team_members(name) VALUES ('Brian Dawson')")
    conn.execute("INSERT INTO team_members(name) VALUES ('brian dawson')")
    conn.commit()
    conn.close()
    M.init_db()
    eq("a collision leaves the table alone",
       "COLLATE NOCASE" in _members_sql(clash_db), False)
    conn = sqlite3.connect(clash_db)
    said = conn.execute("SELECT detail FROM system_log WHERE"
                        " event='members.name_collision'").fetchall()
    conn.close()
    eq("  and is written to the System Log", len(said), 1)
    eq("  naming both spellings",
       "Brian Dawson" in said[0][0] and "brian dawson" in said[0][0], True)
    fresh_db()   # leave the module pointed at a sane database


def _step_dir(name, source):
    """A migrations directory holding one migration, written from source."""
    d = stage_name("mig_%s_" % name)
    os.makedirs(d)
    for i, text in enumerate(source, start=1):
        with io.open(os.path.join(d, "%03d_step%d.py" % (i, i)),
                     "w", encoding="utf-8") as fh:
            fh.write(text)
    return d


def _versioned_db(version=0):
    """A one-table database at a chosen schema version, with a row in it."""
    path = stage_name("step_", ".db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE kept (v TEXT)")
    conn.execute("INSERT INTO kept(v) VALUES ('the row that was here')")
    conn.execute("PRAGMA user_version = %d" % version)
    conn.commit()
    conn.close()
    return path


def _db_state(path):
    conn = sqlite3.connect(path)
    try:
        return (sorted(r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")),
                [r[0] for r in conn.execute("SELECT v FROM kept")],
                conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


# A rebuild's exact shape - create the scratch table, copy into it, and fail
# before the rename - because that is where the leak was. The CREATE is the
# statement sqlite3 does not open a transaction for.
_REBUILD_THAT_FAILS = """
def up(conn):
    conn.execute("CREATE TABLE kept_new (v TEXT)")
    conn.execute("INSERT INTO kept_new(v) SELECT v FROM kept")
    raise RuntimeError("the disk filled up, say")

def down(conn):
    pass
"""

_STEP_OK = """
def up(conn):
    conn.execute("CREATE TABLE landed (v TEXT)")
    conn.execute("INSERT INTO landed(v) VALUES ('step 1')")

def down(conn):
    conn.execute("DROP TABLE landed")
"""


def check_a_failed_migration_step_leaves_the_database_alone():
    """A step that raises has to leave nothing of itself behind.

    `sqlite3` opens a transaction only before INSERT, UPDATE and DELETE -
    never before DDL - so a rebuild's opening `CREATE TABLE` ran in autocommit
    and was on disk before anything began a transaction at all. The rollback of
    the step then left the scratch table sitting there: `user_version` unmoved,
    the migration still pending, and the re-run dying on "table assets_new
    already exists", which is a name in no runbook and no doc. It is the one
    path whose whole job is not to damage this file, and the moment it happens
    is the one at which `update.ps1` has deliberately restored everything
    except the database.

    Driven through `run_migrations` rather than against `008` and `010`,
    because the contract belongs to the runner: what is asserted is that a step
    is atomic, which is what makes every rebuild written after this one safe
    without a guard of its own.

    The three legs are one rule seen from each side - nothing of a failed step
    survives, everything of a finished one does, and a finished step is not
    undone by a later one failing.
    """
    head("a failed migration step leaves the database alone")

    # -- nothing of a failed step survives ------------------------------------
    db = _versioned_db(0)
    before = _db_state(db)
    d = _step_dir("fail", [_REBUILD_THAT_FAILS])
    try:
        M.run_migrations(db, 1, migrations_dir=d, do_backup=False,
                         log=lambda *_a: None)
        bad("run_migrations returned over a step that raised")
    except RuntimeError as ex:
        eq("the step's own failure is what comes back",
           "disk filled up" in str(ex), True)
    tables, rows, ver = _db_state(db)
    eq("the scratch table it created is gone", "kept_new" in tables, False)
    eq("  the table it was rebuilding is untouched", tables, before[0])
    eq("  every row is still there", rows, before[1])
    eq("  and the schema version has not moved", ver, before[2])

    # Which is the whole point: the same run again has something to do, and
    # can do it. This is what died on "already exists".
    d2 = _step_dir("retry", [_STEP_OK])
    M.run_migrations(db, 1, migrations_dir=d2, do_backup=False,
                     log=lambda *_a: None)
    tables, rows, ver = _db_state(db)
    eq("so the re-run applies rather than colliding with the leftovers",
       ("landed" in tables, ver), (True, 1))
    eq("  with the row still there", rows, before[1])

    # -- everything of a finished step survives -------------------------------
    # A BEGIN with no commit behind it would pass every assertion above and
    # apply nothing at all, so the other direction is asserted beside it.
    conn = sqlite3.connect(db)
    eq("  and what it wrote was committed, not left in a transaction",
       [r[0] for r in conn.execute("SELECT v FROM landed")], ["step 1"])
    conn.close()

    # -- a finished step is not undone by a later one failing -----------------
    # Per step and not around the whole run: a migration that has been applied
    # and stamped stays applied, so a run that fails at 010 leaves the database
    # at v9 rather than back where it began, and the operator's next run has
    # one step to take instead of ten.
    db = _versioned_db(0)
    d3 = _step_dir("pair", [_STEP_OK, _REBUILD_THAT_FAILS])
    try:
        M.run_migrations(db, 2, migrations_dir=d3, do_backup=False,
                         log=lambda *_a: None)
        bad("run_migrations returned over a second step that raised")
    except RuntimeError:
        pass
    tables, rows, ver = _db_state(db)
    eq("the step that finished is kept", "landed" in tables, True)
    eq("  and stamped, so the re-run starts from it", ver, 1)
    eq("  while the step that failed left nothing",
       "kept_new" in tables, False)
    eq("  and no row moved either way", rows, ["the row that was here"])
    fresh_db()


def check_migration_008_folds_case_both_ways():
    """up() rebuilds, down() rebuilds back, and neither drops a row.

    A downgrade never drops data, so this `down()` is the same rebuild in
    reverse rather than the no-op the column migrations use: what it restores
    is the byte-matching an older build's queries assume.
    """
    head("migration 008")
    path = os.path.join(R, "migrations", "008_member_name_nocase.py")
    if not os.path.exists(path):
        bad("migrations/008_member_name_nocase.py is missing")
        return
    src = io.open(path, encoding="utf-8").read()
    mod = {}
    exec(compile(src, path, "exec"), mod)

    db = _legacy_members_db()
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO team_members(name, auto_approve, profile,"
                 " permissions, password_hash, must_change_password)"
                 " VALUES ('David Foster', 0, 'custom', '', 'h', 1)")
    conn.commit()
    mod["up"](conn)
    conn.commit()
    eq("up() gives the name NOCASE",
       "COLLATE NOCASE" in _members_sql(db), True)
    row = conn.execute("SELECT profile, password_hash, must_change_password"
                       " FROM team_members WHERE name='DAVID FOSTER'"
                       ).fetchone()
    eq("  the row survives and is found under another case",
       tuple(row), ("custom", "h", 1))

    mod["down"](conn)
    conn.commit()
    eq("down() puts the collation back",
       "COLLATE NOCASE" in _members_sql(db), False)
    eq("  and keeps the row",
       conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0], 1)
    conn.close()

    clash = _legacy_members_db()
    conn = sqlite3.connect(clash)
    conn.execute("INSERT INTO team_members(name) VALUES ('Brian Dawson')")
    conn.execute("INSERT INTO team_members(name) VALUES ('BRIAN DAWSON')")
    conn.commit()
    try:
        mod["up"](conn)
        bad("up() applied over two names differing only in case")
    except RuntimeError as ex:
        eq("up() refuses a collision rather than choosing",
           "Brian Dawson" in str(ex) and "BRIAN DAWSON" in str(ex), True)
        eq("  and writes nothing",
           conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0], 2)
    conn.close()
    fresh_db()


def _nocase_members_db():
    """A team_members as migration `008` left it: name-keyed, NOCASE, no id.

    Built by hand for `_legacy_members_db`'s reason one version on - the point
    of this rebuild is to read a table this build would never create.
    """
    path = stage_name("nocase_", ".db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE team_members (
        name                 TEXT PRIMARY KEY COLLATE NOCASE,
        auto_approve         INTEGER DEFAULT 0,
        profile              TEXT    DEFAULT 'default',
        permissions          TEXT    DEFAULT '',
        password_hash        TEXT    DEFAULT '',
        must_change_password INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()
    M.DB_PATH = path
    return path


def _members_cols(db):
    conn = sqlite3.connect(db)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(team_members)")]
    finally:
        conn.close()


def _members_pk(db):
    conn = sqlite3.connect(db)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(team_members)")
                if r[5]]
    finally:
        conn.close()


def _members_row(db, name):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM team_members WHERE name=?",
                         (name,)).fetchone()
        return dict(r) if r is not None else None
    finally:
        conn.close()


def check_migration_012_gives_the_engineer_an_id_both_ways():
    """up() adds the key, down() takes it back, and neither drops a row.

    The id is the one column a `down()` here may drop, and only because it is
    the key being reversed rather than anything anybody wrote down (ADR-0016):
    nothing outside the table references it, and `/members` answered by name on
    both sides of the change. Every other column and every row is kept.
    """
    head("migration 012")
    path = os.path.join(R, "migrations", "012_member_identity.py")
    if not os.path.exists(path):
        bad("migrations/012_member_identity.py is missing")
        return
    mod = {}
    exec(compile(io.open(path, encoding="utf-8").read(), path, "exec"), mod)

    db = _nocase_members_db()
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO team_members(name, auto_approve, profile,"
                 " permissions, password_hash, must_change_password)"
                 " VALUES ('David Foster', 1, 'custom', 'view_all_history',"
                 " 'h', 1)")
    conn.execute("INSERT INTO team_members(name) VALUES ('Brian Dawson')")
    conn.commit()
    mod["up"](conn)
    conn.commit()
    conn.close()

    eq("up() gives the table an id", "id" in _members_cols(db), True)
    sql = _members_sql(db)
    eq("  and the name keeps its collation on the constraint",
       "UNIQUE" in sql and "COLLATE NOCASE" in sql, True)
    eq("  and is the key itself", _members_pk(db), ["id"])
    row = _members_row(db, "David Foster")
    eq("  every value survives",
       (row["auto_approve"], row["profile"], row["permissions"],
        row["password_hash"], row["must_change_password"]),
       (1, "custom", "view_all_history", "h", 1))
    eq("  and every row", _count_members(db), 2)
    eq("  ids are handed out in the order the rows were written",
       row["id"] < _members_row(db, "Brian Dawson")["id"], True)
    # The constraint is what 008 bought, carried across rather than re-argued.
    conn = sqlite3.connect(db)
    try:
        conn.execute("INSERT INTO team_members(name) VALUES ('BRIAN DAWSON')")
        bad("a second spelling of one name was accepted after up()")
    except sqlite3.IntegrityError:
        ok("a name differing only in case is still one Engineer")
    conn.rollback()

    mod["down"](conn)
    conn.commit()
    conn.close()
    eq("down() takes the id back", "id" in _members_cols(db), False)
    eq("  and the name is the key again", _members_pk(db), ["name"])
    eq("  and keeps every row", _count_members(db), 2)
    row = _members_row(db, "David Foster")
    eq("  carrying every other column with them",
       (row["auto_approve"], row["profile"], row["permissions"],
        row["password_hash"], row["must_change_password"]),
       (1, "custom", "view_all_history", "h", 1))

    # A database `init_db()` warned about and started anyway can reach this
    # step - that is the whole reason the check is in the migration as well.
    clash = _legacy_members_db()
    conn = sqlite3.connect(clash)
    conn.execute("INSERT INTO team_members(name) VALUES ('Brian Dawson')")
    conn.execute("INSERT INTO team_members(name) VALUES ('BRIAN DAWSON')")
    conn.commit()
    try:
        mod["up"](conn)
        bad("up() applied over two names differing only in case")
    except RuntimeError as ex:
        eq("up() refuses a collision rather than choosing",
           "Brian Dawson" in str(ex) and "BRIAN DAWSON" in str(ex), True)
        eq("  and writes nothing",
           conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0], 2)
    conn.close()
    fresh_db()


def _count_members(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0]
    finally:
        conn.close()


def check_init_db_gives_the_engineer_an_id():
    """Both ways, the pattern every table here uses.

    A fresh database and one upgraded without anybody running migrate must be
    the same database - and the path that runs on every boot must not refuse to
    start over data that was already there, which is the one place these two
    deliberately differ.
    """
    head("init_db gives the Engineer an id")
    db = fresh_db()
    eq("a fresh database has the id", "id" in _members_cols(db), True)
    sql = _members_sql(db)
    eq("  with the collation on the name's constraint",
       "UNIQUE" in sql and "COLLATE NOCASE" in sql, True)

    older = _nocase_members_db()
    conn = sqlite3.connect(older)
    conn.execute("INSERT INTO team_members(name, auto_approve, profile,"
                 " permissions, password_hash, must_change_password)"
                 " VALUES ('Carol Evans', 1, 'custom', 'view_all_history',"
                 " 'x', 1)")
    conn.commit()
    conn.close()
    M.init_db()
    eq("an older one is rebuilt", "id" in _members_cols(older), True)
    row = _members_row(older, "Carol Evans")
    eq("  carrying every value across",
       (row["auto_approve"], row["profile"], row["permissions"],
        row["password_hash"], row["must_change_password"]),
       (1, "custom", "view_all_history", "x", 1))
    was = row["id"]
    M.init_db()
    eq("  and a second boot changes nothing",
       (_count_members(older), _members_row(older, "Carol Evans")["id"]),
       (1, was))

    # A collision that was already there: warned about, never fatal - this is
    # the path that runs on every boot, and a store that cannot record a
    # movement today because of a duplicate made months ago is the worse
    # failure. The rebuild is left undone rather than done wrongly.
    clash = _legacy_members_db()
    conn = sqlite3.connect(clash)
    conn.execute("INSERT INTO team_members(name) VALUES ('Brian Dawson')")
    conn.execute("INSERT INTO team_members(name) VALUES ('brian dawson')")
    conn.commit()
    conn.close()
    M.init_db()
    eq("a collision leaves the table alone", "id" in _members_cols(clash),
       False)
    conn = sqlite3.connect(clash)
    said = conn.execute("SELECT detail FROM system_log WHERE"
                        " event='members.name_collision'").fetchall()
    conn.close()
    eq("  and is written to the System Log", len(said), 1)
    fresh_db()


def _rename_fixture():
    """A database holding one Engineer with a history, and the test client."""
    db = fresh_db()
    _blank_lookup()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    c = M.app.test_client()
    c.post("/members", json={"password": "admin", "name": "Carol Evans",
                             "auto_approve": 0, "member_password": "own1"})
    mid = [m["id"] for m in c.get("/members").get_json()
           if m["name"] == "Carol Evans"][0]
    return db, c, mid


def check_renaming_an_engineer_rewrites_the_register():
    """A rename is an UPDATE, and it takes the register with it.

    The name was the primary key until `012_member_identity`, so this was a
    delete and an insert - and a delete takes the Engineer's Own Password,
    their Access Profile and their permissions with it. What has to move with
    the row is `transactions.team_member` and `clients.member`, both of which
    hold a spelling rather than a key and both of which are about this same
    person; what must **not** move is `system_log`, which records what was done
    at the time (ADR-0016).
    """
    head("renaming an Engineer rewrites the register")
    db, c, mid = _rename_fixture()
    tid = add_txn(db, team_member="Carol Evans", asset_number="RN-1")
    _add_client(db, "cid-rename", "Carol Evans")
    M._log_event("transaction.created", "RN-1 out to Carol Evans",
                 actor="Carol Evans")
    before = [(r["event"], r["actor"], r["detail"]) for r in _log_rows(db)]

    payload, status = M._rename_member(mid, "Carol Everett", "admin")
    eq("the rename is accepted", (status, payload.get("renamed")), (200, True))
    eq("  answering with both spellings",
       (payload.get("was"), payload.get("name")),
       ("Carol Evans", "Carol Everett"))
    eq("  and how many Transactions moved", payload.get("transactions"), 1)
    eq("the Engineer is the same row", _members_row(db, "Carol Everett")["id"],
       mid)
    eq("  keeping their Own Password",
       c.post("/auth/verify", json={"name": "Carol Everett",
                                    "password": "own1"}
              ).get_json().get("valid"), True)
    eq("the Transaction moves with them", txn(db, tid)["team_member"],
       "Carol Everett")
    conn = sqlite3.connect(db)
    seen = conn.execute("SELECT member FROM clients WHERE client_id=?",
                        ("cid-rename",)).fetchone()[0]
    conn.close()
    eq("  and so does the Client row", seen, "Carol Everett")

    after = [(r["event"], r["actor"], r["detail"]) for r in _log_rows(db)]
    eq("the System Log is never rewritten", after[:len(before)], before)
    said = _log_rows(db, "member.renamed")
    eq("  the act is recorded instead", len(said), 1)
    eq("  at warn, by the Admin", (said[0]["level"], said[0]["actor"]),
       ("warn", "Admin"))
    eq("  and reads back as the id and both spellings",
       M._parse_renamed(said[0]["detail"]),
       (mid, "Carol Evans", "Carol Everett"))

    # The refusals. Each one writes nothing.
    payload, status = M._rename_member(mid, "Somebody Else", "wrong")
    eq("a wrong admin password is refused", status, 401)
    payload, status = M._rename_member(mid, "   ", "admin")
    eq("an empty name is refused", (status, payload.get("code")),
       (400, "no_name"))
    payload, status = M._rename_member(999999, "Nobody", "admin")
    eq("an id naming no Engineer is refused", (status, payload.get("code")),
       (404, "no_member"))
    c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                             "auto_approve": 0})
    payload, status = M._rename_member(mid, "brian dawson", "admin")
    eq("a name another Engineer holds is refused",
       (status, payload.get("code")), (409, "name_taken"))
    eq("  naming the Engineer in the way",
       "Brian Dawson" in payload.get("error", ""), True)
    payload, status = M._rename_member(mid, "Carol Everett", "admin")
    eq("renaming to the name they have is not a rename",
       (status, payload.get("renamed")), (200, False))
    eq("  so nothing more is written to the System Log",
       len(_log_rows(db, "member.renamed")), 1)
    eq("  and the Engineer is still there under the name they were given",
       _members_row(db, "Carol Everett")["id"], mid)


def check_a_renamed_engineers_notifier_is_not_deaf():
    """The failure this ticket is really about, from both sides.

    A Notifier holds its Engineer's *name*. After a rename that name resolves
    to nobody, `/pending` answers an empty list, and an empty list is
    indistinguishable from having nothing to confirm - so the engineer is never
    told and simply stops being asked, with the 24h Auto-Accept resolving
    everything behind them. Two answers, because the first one expires: the
    check-in carries the id, and `/pending` resolves a former name.
    """
    head("a renamed Engineer's Notifier is not deaf")
    db, c, mid = _rename_fixture()
    tid = add_txn(db, team_member="Carol Evans", asset_number="RN-2")
    M._rename_member(mid, "Carol Everett", "admin")

    eq("/pending answers under the new name",
       [t["id"] for t in c.get("/pending/Carol Everett").get_json()], [tid])
    eq("  and under the name the Notifier still holds",
       [t["id"] for t in c.get("/pending/Carol Evans").get_json()], [tid])
    eq("a name nobody has renamed resolves to nothing",
       M._former_member_name("Brian Dawson"), "")
    eq("  and neither does a name that is still somebody's",
       M._former_member_name("Carol Everett"), "")

    # The answer that does not expire: the id, learnt from a check-in.
    r = c.post("/clients/checkin", json={"client_id": "cid-deaf",
                                         "app": "Notifier",
                                         "version": "2.3.0",
                                         "member": "Carol Evans",
                                         "member_id": str(mid)})
    body = r.get_json()
    eq("the check-in answers with the Engineer's current name",
       (r.status_code, body.get("member")), (200, "Carol Everett"))
    eq("  and with the id to keep asking by", str(body.get("member_id")),
       str(mid))
    conn = sqlite3.connect(db)
    seen = conn.execute("SELECT member FROM clients WHERE client_id=?",
                        ("cid-deaf",)).fetchone()[0]
    conn.close()
    eq("  recording the row's own spelling", seen, "Carol Everett")

    # A Client that has never been told an id is answered exactly as it was.
    r = c.post("/clients/checkin", json={"client_id": "cid-old",
                                         "app": "Notifier",
                                         "member": "Carol Everett"})
    eq("a Client with no id is answered by name",
       r.get_json().get("member"), "Carol Everett")

    # An id naming a **different** living Engineer is an id from somewhere
    # else - a restored backup - and following it would re-point this Notifier
    # at somebody else, which is worse than going deaf. The name wins.
    c.post("/members", json={"password": "admin", "name": "Brian Dawson",
                             "auto_approve": 0})
    brian = [m["id"] for m in c.get("/members").get_json()
             if m["name"] == "Brian Dawson"][0]
    r = c.post("/clients/checkin", json={"client_id": "cid-foreign",
                                         "app": "Notifier",
                                         "member": "Brian Dawson",
                                         "member_id": str(mid)})
    body = r.get_json()
    eq("a living name beats an id naming somebody else",
       (body.get("member"), str(body.get("member_id"))),
       ("Brian Dawson", str(brian)))
    # And an id naming nobody falls back to the name rather than clearing it.
    r = c.post("/clients/checkin", json={"client_id": "cid-stale",
                                         "app": "Notifier",
                                         "member": "Brian Dawson",
                                         "member_id": "999999"})
    eq("an id naming no row falls back to the name",
       r.get_json().get("member"), "Brian Dawson")


def check_one_place_renames_an_engineer():
    """`_rename_member` is the one writer of a rename, and has one door.

    A source check for `check_one_place_writes_the_engineer_list`'s reason: the
    window this is for - Manage Users - is a Tk callback no harness can reach,
    and what is asserted is the **absence** of a second writer.

    It asserted the absence of a door as well until #171, on the grounds that a
    rename addressed over the wire is a way to move an Engineer's whole history
    from off this machine. What changed there is **where the Admin is
    standing** rather than the rule - the same thing that changed for
    `POST /transactions/modify` at R1 - so `POST /members/rename` exists now and
    reaches this same one writer, which is what keeps the id-not-name rule
    (ADR-0016) from holding at the console and quietly not on the wire. The
    assertion is therefore that **exactly one** endpoint reaches it and it is
    that one: a second would be the drift this group was written for.
    """
    head("one place renames an Engineer")
    # SRC_ENG_ALL: `_rename_member` is in the Engineers register since #217,
    # and what this group asserts is that nothing *else* writes those three
    # tables - an answer that needs the register in the text it reads, not a
    # report that the one writer is gone.
    tree = ast.parse(SRC_ENG_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns[node.name] = node

    def owner_of(line):
        best = None
        for name, n in fns.items():
            if n.lineno <= line <= n.end_lineno and (
                    best is None
                    or (fns[best].end_lineno - fns[best].lineno)
                    > (n.end_lineno - n.lineno)):
                best = name
        return best

    def writers(fragment):
        lines = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and fragment in n.value]
        return sorted({owner_of(ln) for ln in lines})

    eq("only _rename_member renames the row",
       writers("UPDATE team_members SET name"), ["_rename_member"])
    eq("only it moves the Transactions",
       writers("UPDATE transactions SET team_member"), ["_rename_member"])
    eq("only it moves the Client rows",
       writers("UPDATE clients SET member"), ["_rename_member"])
    # The audit trail is the one table a rename does not touch.
    eq("and nothing rewrites the System Log at all",
       writers("UPDATE system_log"), [])

    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            f = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(f, ast.Attribute) and f.attr == "route":
                routes.add(node.name)
    reached = sorted(r for r in routes
                     if "_rename_member(" in (ast.get_source_segment(
                         SRC_ENG_ALL, fns[r]) or ""))
    eq("exactly one endpoint reaches it, and it is #171's",
       reached, ["rename_member"])
    eq("  and the helper takes the admin password itself",
       "admin_password" in [a.arg for a in fns["_rename_member"].args.args],
       True)


def check_the_storekeeper_creates_an_engineer_but_never_edits_one():
    """The create-only path, and the three things that bound it (S3, ADR-0017).

    What is delegated is naming somebody Transactions are then recorded
    against - which is small beside `POST /transactions` taking no credential
    at all (ADR-0002), and is why the Add Engineer dialog no longer asks the
    store to hold the password that also opens Clear All Records (ADR-0007).

    What is **not** delegated is everything about an Engineer rather than the
    fact of one, so each of the three bounds is asserted on its own: the switch,
    the refusal of a name the list already holds (an update is an edit), and the
    refusal of a profile, a permission list or an Own Password sent with no
    password rather than those fields being ignored. Ignoring one is how an
    Admin comes to believe a permission was granted.
    """
    head("the Storekeeper creates an Engineer but never edits one (S3)")
    db = fresh_db()
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {}}
    write_server_cfg({})
    c = M.app.test_client()

    def names():
        return [m["name"] for m in c.get("/members").get_json()]

    # A file that predates the key is normal rather than corrupt, and reads
    # allowed - the answer `storekeeper_can_cancel` beside it gives.
    eq("a config that predates the switch reads allowed",
       M._storekeeper_can_add_engineer(), True)

    r = c.post("/members", json={"name": "Nadia Fouad", "auto_approve": False})
    eq("an engineer is created with no password at all", r.status_code, 200)
    eq("  and is on the list", "Nadia Fouad" in names(), True)
    row = [m for m in c.get("/members").get_json()
           if m["name"] == "Nadia Fouad"][0]
    eq("  on the Default profile", row["profile"], "default")
    eq("  with no own password of any kind", row["has_password"], False)
    eq("  and no temporary flag to go with one",
       row["must_change_password"], False)

    # Auto-Approve is the one flag settable here: not a permission and not a
    # credential, and the one fact the person adding them knows at that moment.
    r = c.post("/members", json={"name": "Omar Zaki", "auto_approve": True})
    eq("auto-approve comes with the creation", r.status_code, 200)
    eq("  and is what was asked for",
       [m["auto_approve"] for m in c.get("/members").get_json()
        if m["name"] == "Omar Zaki"], [True])

    # An update is an edit. Without this, "create" would reach every field on
    # an Engineer who is already on the list, which is the whole of what is
    # being withheld.
    r = c.post("/members", json={"name": "Nadia Fouad", "auto_approve": True})
    eq("a name the list already holds is refused", r.status_code, 409)
    eq("  naming why", r.get_json().get("code"), "already_exists")
    eq("  and nothing about the row moved",
       [m["auto_approve"] for m in c.get("/members").get_json()
        if m["name"] == "Nadia Fouad"], [False])
    r = c.post("/members", json={"name": "NADIA FOUAD"})
    eq("  a second spelling of them is the same refusal, 008's fold",
       (r.status_code, r.get_json().get("code")), (409, "already_exists"))

    # Refused outright rather than ignored: a field silently dropped is one
    # the caller believes was applied.
    for field, value in (("profile", "custom"),
                         ("permissions", ["view_all_history"]),
                         ("member_password", "handedover")):
        body = {"name": "Hala Nabil", field: value}
        r = c.post("/members", json=body)
        eq("%s sent with no password is refused, not ignored" % field,
           (r.status_code, r.get_json().get("code")), (403, "create_only"))
    eq("  and none of those attempts created the engineer",
       "Hala Nabil" in names(), False)

    # A wrong password never falls back to the delegated path: that would let
    # a typo silently downgrade an Admin and name the wrong reason.
    r = c.post("/members", json={"password": "", "name": "Hala Nabil"})
    eq("an empty password is an attempt at the admin path, not an absent key",
       r.status_code, 401)
    r = c.post("/members", json={"password": "wrong", "name": "Hala Nabil"})
    eq("  and a wrong one is refused as wrong", r.status_code, 401)
    eq("  neither having created anybody", "Hala Nabil" in names(), False)

    # The switch, read from disk on every request rather than from the
    # import-time snapshot: an Admin withdrawing it must not have to restart.
    write_server_cfg({"storekeeper_can_add_engineer": False})
    r = c.post("/members", json={"name": "Hala Nabil"})
    eq("the switch is off: the delegated path is refused", r.status_code, 403)
    eq("  naming why", r.get_json().get("code"), "add_engineer_disabled")
    eq("  with no restart between the write and the refusal",
       "Hala Nabil" in names(), False)
    r = c.post("/members", json={"password": "admin", "name": "Hala Nabil"})
    eq("  and the admin password is untouched by it", r.status_code, 200)
    eq("  the admin path still reaching every field",
       c.post("/members", json={"password": "admin", "name": "Hala Nabil",
                                "profile": "custom",
                                "permissions": ["view_all_history"]}
              ).status_code, 200)

    write_server_cfg({"storekeeper_can_add_engineer": True})
    eq("switched back on, the delegated path is open again",
       c.post("/members", json={"name": "Sara Adel"}).status_code, 200)

    # The heartbeat carries it, so the client hides the control rather than
    # offering one the server will refuse. Additive, like every key there.
    h = c.get("/health").get_json()
    eq("the heartbeat carries the switch", h.get("storekeeper_can_add_engineer"),
       True)
    write_server_cfg({"storekeeper_can_add_engineer": False})
    eq("  and follows it", c.get("/health").get_json()
       .get("storekeeper_can_add_engineer"), False)

    # An Admin reading the System Log has to be told who added the row, and
    # the label is `_storekeeper_actor`'s - the one this client's Transactions
    # and cancels already carry.
    write_server_cfg({})
    c.post("/members", json={"name": "Yara Samir"})
    conn = sqlite3.connect(db)
    actors = [r[0] for r in conn.execute(
        "SELECT actor FROM system_log WHERE event='member.saved' "
        "AND detail LIKE 'Yara Samir%'").fetchall()]
    conn.close()
    eq("the act is attributed to the Storekeeper, not to the Admin",
       actors, [M._storekeeper_actor()])

    write_server_cfg({})


def check_one_place_writes_the_engineer_list():
    """The console and the wire share the writers, and the wire has four.

    A source check, because the window this is about - Manage Users - is a Tk
    callback no harness can reach, and the thing being asserted is the absence
    of a second writer rather than the behaviour of the one that is there. The
    same shape as `check_one_place_writes_the_cancellation`, and for the same
    reason: a rule that holds at the endpoint and quietly not in the window an
    Admin uses is exactly where somebody reaches for a way past it.

    It said the list had **three** endpoints and that a rename deliberately had
    none, until #171 gave Remote Admin an Engineers panel: a delegate who can
    add an Engineer, delete one and set an Own Password, and who has to walk to
    the console to correct a misspelt name, leaves it misspelt - the argument
    that put `POST /transactions/modify` on the network at R1. The count is
    written out rather than sampled for that reason: a fifth has to be added
    here deliberately.
    """
    head("one writer for the Engineer list")
    # SRC_ENG_ALL, for the reason the rename group gives: `_save_member` and
    # `_delete_member` moved into the register at #217 and the absence of a
    # second writer is still asserted over the API and the console.
    tree = ast.parse(SRC_ENG_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns[node.name] = node

    def owner_of(line):
        best = None
        for name, n in fns.items():
            if n.lineno <= line <= n.end_lineno and (
                    best is None
                    or (fns[best].end_lineno - fns[best].lineno)
                    > (n.end_lineno - n.lineno)):
                best = name
        return best

    def writers(fragment):
        lines = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and fragment in n.value]
        return sorted({owner_of(ln) for ln in lines})

    # init_db seeds with INSERT OR IGNORE, which is deliberately a different
    # statement: it creates the default Engineers and never updates one.
    eq("only _save_member inserts an Engineer",
       writers("INSERT INTO team_members("), ["_save_member"])
    eq("only _delete_member removes one",
       writers("DELETE FROM team_members"), ["_delete_member"])

    src_of = {}
    for name in ("manage_users", "add_member", "delete_member"):
        if name not in fns:
            bad("%s is missing from server.py" % name)
            return
        src_of[name] = ast.get_source_segment(SRC_ENG_ALL, fns[name]) or ""

    for helper in ("_save_member(", "_delete_member("):
        if helper in src_of["manage_users"]:
            ok("manage_users goes through %s" % helper[:-1])
        else:
            bad("manage_users does not call %s" % helper[:-1])
    # Not a fifth capability: whoever can add an Engineer or clear one can then
    # be that Engineer at that Engineer's client (ADR-0009).
    if "_authorise(" in src_of["manage_users"]:
        bad("manage_users authorises through _authorise")
    else:
        ok("manage_users does not go through _authorise")
    # Own Passwords are shown *and set* there since A5, on the Engineer's own
    # card. It was the other way round - shown there, set in a window of its
    # own - which is two windows wording "temporary until the Engineer
    # replaces it" and one of them free to drift. Both halves are asserted:
    # that this window reaches the one writer, and that the window it replaced
    # is gone rather than left behind with no door onto it.
    if "_set_member_password(" in src_of["manage_users"]:
        ok("manage_users sets an Own Password through _set_member_password")
    else:
        bad("manage_users does not call _set_member_password")
    if hasattr(M, "engineer_passwords"):
        bad("the Engineer Passwords window is still there beside the card")
    else:
        ok("the Engineer Passwords window is gone, its one job on the card")

    for name in ("add_member", "delete_member"):
        if "_admin_password_ok(" in src_of[name]:
            bad("%s checks the admin password itself as well as the helper"
                % name)
        else:
            ok("%s leaves the admin password to the helper it forwards to"
               % name)

    # There is deliberately no endpoint of its own - the Admin at this console
    # is the only actor, the same call Add Transaction and Modify made. Read
    # off each function's decorators rather than by line number: a decorator
    # sits above its `def`, so it is outside the node's own line range.
    served = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not dec.args:
                continue
            first = dec.args[0]
            if isinstance(first, ast.Constant) \
                    and isinstance(first.value, str) \
                    and first.value.startswith("/members"):
                served.append(node.name)
    eq("the Engineer list has exactly its four endpoints",
       sorted(set(served)),
       ["add_member", "delete_member", "list_members", "rename_member"])
    if "_rename_member(" in (ast.get_source_segment(SRC_ENG_ALL,
                                                    fns["rename_member"])
                             or ""):
        ok("rename_member forwards to the one writer of a rename")
    else:
        bad("rename_member does not call _rename_member")
