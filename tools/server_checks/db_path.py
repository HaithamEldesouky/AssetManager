r"""The database can live somewhere else (ADR-0004).

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import os
import sqlite3

from server_checks.stage import (M, SRC_ALL, SRC_BACKUP_ALL, STAGE, add_txn,
                                 bad, eq, head, moved_db, ok, stage_import)



# ── the database can live somewhere else ─────────────────────────────────────

def check_the_database_path_is_validated():
    """_validate_db_path refuses what SQLite cannot survive.

    A network path is the one that matters. SQLite's locking rests on advisory
    locks an SMB redirector emulates rather than honours, so two writers on one
    share interleave the file instead of queueing - and the migration backup
    lands on the same share. Refusing at the point of entry is the only place
    this can be caught: by bind time there is nothing to say it to.
    """
    head("the database path is validated")

    for value, want in (
            ("", "cannot be empty"),
            ("   ", "cannot be empty"),
            ("assets.db", "must be absolute"),
            (r"data\assets.db", "must be absolute"),
            (r"\\asset-server\share\assets.db", "network path"),
            ("//asset-server/share/assets.db", "network path"),
            ("C:\\AssetManager\\", "must name a file"),
            (STAGE, "must name a file")):
        p, err = M._validate_db_path(value)
        if p is not None:
            bad("%r was accepted as %r" % (value, p))
        elif want not in (err or ""):
            bad("%r was refused, but not for %r: %s" % (value, want, err))
        else:
            ok("refused %r" % (value,))

    for value, want in ((r"D:\AssetManager\assets.db",
                         r"D:\AssetManager\assets.db"),
                        (r'"D:\AssetManager\assets.db"',
                         r"D:\AssetManager\assets.db"),
                        ("D:/AssetManager/assets.db",
                         r"D:\AssetManager\assets.db"),
                        (r"D:\AssetManager\.\sub\..\assets.db",
                         r"D:\AssetManager\assets.db")):
        p, err = M._validate_db_path(value)
        if err:
            bad("%r was refused: %s" % (value, err))
        else:
            eq("%r resolves" % (value,), p, want)

    # Same contract as the other two validators: exactly one of the pair is
    # None, so neither can be mistaken for returning a bare value.
    for v in ("", "assets.db", r"D:\AssetManager\assets.db"):
        p, err = M._validate_db_path(v)
        if (p is None) == (err is None):
            bad("%r returned (%r, %r) - exactly one must be None" % (v, p, err))
    ok("exactly one of (path, error) is None")


def check_a_configured_database_is_the_one_that_is_used():
    """db_path moves the database and nothing else.

    Not a monkeypatch: a real import with a real server_config.json, driven
    through the API, because the resolution happens at import time.
    """
    head("a configured database is the one that is used")

    src = moved_db("elsewhere")
    add_txn(src, asset_number="MV-1")
    add_txn(src, asset_number="MV-2")

    mod, d = stage_import("cfg_ok", {"host": "127.0.0.1", "port": 8081,
                                     "db_path": src})
    eq("DB_PATH is the configured file", mod.DB_PATH, src)
    eq("nothing prevents startup", mod._require_db(), None)

    c = mod.app.test_client()
    eq("/health counts the moved database's records",
       c.get("/health").get_json().get("total"), 2)
    eq("/transactions reads it too", len(c.get("/transactions").get_json()), 2)

    # Only the database moves. The lookup sheet, the certificate and both
    # config files are part of the install, not of the data - a half-moved
    # install is worse than a moved one, because the server still starts.
    for label, path in (("admin_config.json", mod.ADMIN_CFG_PATH),
                        ("server_config.json", mod.SERVER_CFG_PATH),
                        ("asset_lookup.xlsx", mod.LOOKUP_PATH),
                        ("ssl_cert.pem", mod.SSL_CERT_PATH),
                        ("ssl_key.pem", mod.SSL_KEY_PATH)):
        if os.path.dirname(path) == d:
            ok("%s stayed beside the server" % label)
        else:
            bad("%s moved with the database: %s" % (label, path))

    eq("the default is still recorded", mod.DB_DEFAULT_PATH,
       os.path.join(d, "assets.db"))


def check_an_absent_configured_database_prevents_startup():
    """A configured path with nothing at it refuses to start, naming the path.

    Creating an empty database instead would give a server that starts
    cleanly, reports healthy, shows no records and takes a day's work into a
    file nobody opens again - while the real database, wherever it went, is the
    one everybody believes they are looking at.
    """
    head("an absent configured database prevents startup")

    missing = os.path.join(STAGE, "not_here", "assets.db")
    mod, _ = stage_import("cfg_missing", {"host": "127.0.0.1", "port": 8081,
                                          "db_path": missing})
    err = mod._require_db()
    if not err:
        bad("a configured database that does not exist was allowed to start")
    else:
        ok("startup is refused")
        if missing not in err:
            bad("the refusal does not name the path: %s" % err)
        else:
            ok("the refusal names the path")
        if "db_path" not in err:
            bad("the refusal does not name the setting to change: %s" % err)
        else:
            ok("the refusal names db_path")

    # The default path is exempt: a missing file there is a first run, and
    # init_db() has always created it.
    mod2, d2 = stage_import("cfg_default", {"host": "127.0.0.1", "port": 8081})
    eq("no db_path means the default", mod2.DB_PATH, mod2.DB_DEFAULT_PATH)
    if os.path.exists(mod2.DB_PATH):
        bad("the staged default database already exists - the check is void")
    eq("a first run at the default path is allowed", mod2._require_db(), None)


def check_a_bad_configured_path_never_falls_back():
    """An invalid db_path refuses to start rather than using the default.

    Falling back is the dangerous shape: the server would come up, look
    healthy, and write to a different file than the one the admin configured.
    The invalid value is kept and reported instead.
    """
    head("a bad configured path never falls back")

    for name, value, want in (
            ("relative", "assets.db", "must be absolute"),
            ("unc", r"\\asset-server\share\assets.db", "network path")):
        mod, d = stage_import("cfg_bad_" + name,
                              {"host": "127.0.0.1", "port": 8081,
                               "db_path": value})
        err = mod._require_db()
        if not err:
            bad("a %s db_path was allowed to start" % name)
            continue
        ok("a %s db_path is refused" % name)
        if value not in err:
            bad("the refusal does not quote the configured value: %s" % err)
        if want not in err:
            bad("the refusal does not say why: %s" % err)
        # It falls back for the purposes of not crashing at import, but the
        # gate above is what stops it ever being written to.
        eq("DB_PATH did not become the bad value", mod.DB_PATH,
           mod.DB_DEFAULT_PATH)


def check_every_entry_point_refuses_to_start():
    """All three hosts call _require_db before init_db.

    A source check, because two of the three cannot be reached from here at
    all: SvcDoRun runs in session 0 under the SCM, and the GUI branch opens a
    window. The gate deliberately does not live inside init_db() - that also
    runs against a fresh install and from this file, where creating the
    database is exactly right - so nothing but this would notice a host that
    was left out.
    """
    head("every entry point refuses to start")
    # SRC_BACKUP_ALL since #228: the three hosts are here, _migrate_cli
    # is in server_archive.py, and the migrate verb is one of the four
    # entry points this asks about.
    tree = ast.parse(SRC_BACKUP_ALL)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def positions(text, needle):
        out, i = [], text.find(needle)
        while i != -1:
            out.append(i)
            i = text.find(needle, i + 1)
        return out

    def gate_before_init(label, text, want):
        req = positions(text, "_require_db()")
        ini = positions(text, "init_db()")
        if len(ini) != want:
            bad("%s: expected %d init_db() call(s), found %d"
                % (label, want, len(ini)))
            return
        if len(req) != want:
            bad("%s: %d init_db() call(s) but %d _require_db() call(s)"
                % (label, len(ini), len(req)))
            return
        for r, n in zip(req, ini):
            if r > n:
                bad("%s: init_db() runs before the _require_db() gate" % label)
                return
        ok("%s gates init_db()" % label)

    main = None
    for node in tree.body:
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"):
            main = node
    if main is None:
        bad("could not find the __main__ block")
    else:
        # Two hosts live in there: the headless serve verb and the GUI.
        gate_before_init("the __main__ block",
                         ast.get_source_segment(SRC_BACKUP_ALL, main), 2)

    if "SvcDoRun" not in fns:
        bad("SvcDoRun is gone - the Windows Service host cannot be checked")
    else:
        gate_before_init("SvcDoRun",
                         ast.get_source_segment(SRC_BACKUP_ALL,
                                                fns["SvcDoRun"]), 1)

    body = ast.get_source_segment(SRC_BACKUP_ALL, fns["init_db"])
    if "_require_db" in body:
        bad("init_db() calls the gate - it also runs on a fresh install and "
            "from this file, where creating the database is correct")
    else:
        ok("init_db() does not call the gate")

    body = ast.get_source_segment(SRC_BACKUP_ALL, fns["_migrate_cli"])
    if "_require_db" in body:
        bad("the migrate verb calls the gate - migrating a copy at an "
            "explicit --db is legitimate and would be refused")
    else:
        ok("the migrate verb is exempt, as intended")

    # --db inherits the resolved path, which is what makes the migration
    # backup land next to the database rather than next to the server.
    # `_db_path()` rather than `DB_PATH` since #228 moved this function
    # into server_archive.py: the path is read through the callable
    # server.py binds, for the reason every lifted module takes one.
    if "default=_db_path()" not in body:
        bad("migrate's --db no longer defaults to the resolved path")
    else:
        ok("migrate's --db defaults to the resolved database path")


def check_the_backup_follows_the_database():
    """The migration backup is written next to whatever file was opened.

    A backup written where the database no longer is, is worse than no backup:
    it succeeds, it is roughly the right size, and it is the wrong file. This
    is also the only recovery path a migration has.
    """
    head("the backup follows the database")
    src = moved_db("backup_here")
    add_txn(src, asset_number="BK-1")
    dest = M._backup_db(src)
    eq("the backup is beside the database",
       os.path.dirname(dest), os.path.dirname(src))
    if not os.path.exists(dest):
        bad("the backup was not written: %s" % dest)
    else:
        ok("the backup exists: %s" % os.path.basename(dest))
    conn = sqlite3.connect(dest)
    eq("and it carries the rows",
       conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)
    conn.close()


def check_the_gui_shows_and_saves_a_moved_database():
    """The status card names a moved database, and the dialog never moves it.

    The chip text is behaviour; the dialog is a source check, because a
    Toplevel cannot be reached from here. Both halves of "it does not move the
    file" are worth pinning: copying a live SQLite database out from under a
    running server can capture a half-written page, and a move would leave the
    -wal and -shm files behind.
    """
    head("the GUI shows and saves a moved database")

    # `_db_chip_text` was asserted here until #204, in both of its states.
    # It is gone with the band segment it worded: the database's path is
    # read and changed in this dialog and nowhere else on the window now,
    # so what is left to hold is this dialog, which is the rest of this
    # group. The absence is asserted rather than assumed - a helper left
    # behind with no caller is the next thing somebody wires back onto a
    # band that cannot hold it.
    if hasattr(M, "_db_chip_text"):
        bad("_db_chip_text is back in server.py - the band's status line "
            "carries a bounded address and protocol now, and a database "
            "path is a folder name nobody here bounds (#204)")
    else:
        ok("the band no longer words a database path")

    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if "change_db_location" not in fns:
        bad("change_db_location is gone - the chip has nothing to open")
        return
    seg = ast.get_source_segment(SRC_ALL, fns["change_db_location"])
    for banned in ("shutil.move", "shutil.copy", "os.replace", "os.rename",
                   "os.remove"):
        if banned in seg:
            bad("the dialog calls %s - it must not touch the file" % banned)
    ok("the dialog does not move, copy or delete the database")
    for needed, why in (
            ("_validate_db_path", "the dialog must validate what it saves"),
            ("_save_server_cfg(db_path=",
             "the dialog must save through the one writer")):
        if needed not in seg:
            bad("%s: %s" % (needed, why))
        else:
            ok("the dialog calls %s" % needed)
