r"""Backup and restore (A13, ADR-0019).

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import os
import shutil
import sqlite3

from server_checks.stage import (M, SRC_BACKUP_ALL, STAGE, _call_name,
                                 _clear_log, _log_rows, _no_maintenance,
                                 add_txn, bad, eq, fresh_db, head, ok, skip,
                                 stage_name, stored_form, txn,
                                 write_admin_cfg, write_server_cfg)



# ── backup and restore (A13, ADR-0019) ───────────────────────────

def _stage_backup_dir(name):
    """An empty directory under STAGE for a backup to be written into."""
    out = os.path.join(STAGE, name)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    return out


def check_a_backup_carries_the_install_and_not_its_secrets():
    """What a backup holds, and the three files it deliberately does not.

    The exclusions are the half worth checking hardest. Both DPAPI secrets are
    at machine scope (ADR-0013, ADR-0014), so a copy of one on another machine
    reads as a stored password and is not one - Mail Settings would go on
    saying a password is set while every send failed. `ssl_key.pem` is the
    older rule: the one file that must never travel, and a backup travels by
    definition. `ssl_cert.pem` is deliberately **not** excluded, being public
    and pinned by every client.
    """
    head("a backup carries the install and not its secrets")

    db = fresh_db()
    _clear_log(db)
    write_server_cfg({"port": 8081})
    write_admin_cfg(json.dumps({"password_hash": stored_form("admin")}))
    for name in ("smtp_secret.dat", "sync_secret.dat", "ssl_key.pem",
                 "ssl_cert.pem"):
        with io.open(os.path.join(STAGE, name), "wb") as f:
            f.write(b"x" * 16)

    dest = _stage_backup_dir("backup-dest")
    out, manifest = M._take_backup(dest)

    eq("the backup is a directory of its own under the one that was picked",
       os.path.dirname(out) == dest and os.path.isdir(out), True)
    eq("  named for the build and the moment",
       out.rsplit(os.sep, 1)[-1].startswith("AssetManagerBackup-%s-"
                                            % M.APP_VERSION), True)
    eq("it is an Asset Manager backup and says which build took it",
       (manifest["kind"], manifest["version"]),
       (M.BACKUP_KIND, M.APP_VERSION))

    got = sorted(manifest["files"])
    eq("it carries the database, both configurations and the lookup sheet",
       got, sorted([os.path.basename(db), "admin_config.json",
                    "asset_lookup.xlsx", "server_config.json"]))
    for name in ("smtp_secret.dat", "sync_secret.dat", "ssl_key.pem"):
        eq("  and not %s" % name,
           name in got or os.path.exists(os.path.join(out, name)), False)
        eq("  with the manifest saying why rather than only omitting it",
           bool((manifest["excluded"] or {}).get(name)), True)
    eq("  while ssl_cert.pem is not excluded: it is public and every client "
       "pinned it",
       "ssl_cert.pem" in (manifest["excluded"] or {}), False)

    # The digest is over the copy, after the copy. Damaging the copy has to
    # show, which is what a digest of the *source* would not.
    name = os.path.basename(db)
    eq("every file is there and matches its digest",
       [n for n, _ in M._verify_backup(out, manifest)], got)
    eq("  and the digest is the copy's own",
       M._sha256_file(os.path.join(out, name)),
       manifest["files"][name]["sha256"])

    rows = _log_rows(db, "backup.started")
    eq("starting is written down", bool(rows), True)
    rows = _log_rows(db, "backup.finished")
    eq("  and so is finishing, naming where it went",
       bool(rows) and out in rows[-1]["detail"], True)

    # Nothing is left holding writes afterwards: the state is the copy's
    # window and not the feature's.
    eq("the maintenance state is over by the time it returns",
       M._maintenance_state(), None)

    # And it really was in force while the copy was being taken - source,
    # since the window is seconds long and a request inside it is a race.
    # SRC_BACKUP_ALL rather than SRC_ALL since #228: both helpers are in
    # server_archive.py now and the window that calls them is not.
    tree = ast.parse(SRC_BACKUP_ALL)
    for fn in ("_take_backup", "_restore_backup"):
        node = [n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == fn]
        eq("%s is there" % fn, len(node), 1)
        used = [w for w in ast.walk(node[0]) if isinstance(w, ast.With)]
        names = []
        for w in used:
            for item in w.items:
                call = item.context_expr
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)):
                    names.append(call.func.id)
        eq("  and copies inside the maintenance state",
           "_maintenance" in names, True)
    _no_maintenance()


def check_a_restore_refuses_before_it_writes_anything():
    """Every refusal, and the live files untouched after each one.

    The order is the decision this ticket makes: by the time a restore is
    copying, what it is replacing is the only copy of this install left, so a
    digest checked afterwards is a digest checked too late. Each leg below
    damages one thing and then asserts the database is still the one that was
    there.
    """
    head("a restore refuses before it writes anything")

    db = fresh_db()
    _clear_log(db)
    write_server_cfg({"port": 8081})
    tid = add_txn(db, asset_number="AM-BK-1")
    dest = _stage_backup_dir("refuse-dest")
    out, manifest = M._take_backup(dest)

    def rows_now():
        conn = sqlite3.connect(M.DB_PATH)
        got = [r[0] for r in conn.execute(
            "SELECT asset_number FROM transactions ORDER BY id")]
        conn.close()
        return got

    def refused(label, prepare):
        # The Transactions rather than the file's digest: the refusal itself
        # writes a System Log row, which is a write to this same database, so
        # a digest would move for the right reason and say the wrong thing.
        before = rows_now()
        prepare()
        try:
            M._restore_backup(out)
            bad("%s: it restored instead of refusing" % label)
        except ValueError as ex:
            ok("%s: %s" % (label, str(ex)[:72]))
        except Exception as ex:
            bad("%s: raised %s instead of a sentence"
                % (label, type(ex).__name__))
        eq("  and what the live database holds is untouched",
           rows_now(), before)

    mpath = os.path.join(out, M.BACKUP_MANIFEST_NAME)
    text = io.open(mpath, encoding="utf-8").read()

    def rewrite(**changes):
        got = json.loads(text)
        got.update(changes)
        with io.open(mpath, "w", encoding="utf-8") as f:
            f.write(json.dumps(got))

    refused("a directory with no manifest in it", lambda: os.remove(mpath))
    refused("a manifest that cannot be read",
            lambda: io.open(mpath, "w", encoding="utf-8").write("}{"))
    refused("a manifest that is not this product's",
            lambda: rewrite(kind="something-else"))
    refused("a backup from a build this one cannot open",
            lambda: rewrite(schema_version=M._latest_schema_version() + 1))

    # A name in a manifest is a name somebody could have typed.
    for label, name in (("an absolute path", os.path.join(STAGE, "evil.txt")),
                        ("a walk up out of the backup",
                         ".." + os.sep + "evil.txt"),
                        ("nothing but dots", "..")):
        refused("a manifest naming %s" % label,
                lambda name=name: rewrite(
                    files=dict(json.loads(text)["files"], **{name: {
                        "sha256": "0" * 64, "size": 0}})))

    rewrite()
    refused("a backup missing a file its manifest names",
            lambda: os.remove(os.path.join(out, "server_config.json")))
    shutil.copy2(M.SERVER_CFG_PATH, os.path.join(out, "server_config.json"))

    def damage():
        rewrite()
        with io.open(os.path.join(out, os.path.basename(db)), "ab") as f:
            f.write(b"damaged")

    refused("a file that does not match the digest beside it", damage)

    # A refusal is written down, in the sentence the Admin was shown: the
    # window's own message is dismissed and gone, and somebody pointing a
    # restore at a foreign or damaged backup is worth being able to find
    # afterwards. Refused rather than failed - nothing was attempted.
    rows = _log_rows(db, "restore.refused")
    eq("each refusal is written down as one", len(rows) >= 9, True)
    eq("  at warn", rows[-1]["level"], "warn")
    eq("  in the words the Admin was shown",
       "does not match the digest" in rows[-1]["detail"], True)
    eq("  and nothing says a restore started or finished",
       (len(_log_rows(db, "restore.started")),
        len(_log_rows(db, "restore.finished"))), (0, 0))
    eq("  while the Transaction that was there still is",
       txn(db, tid)["asset_number"], "AM-BK-1")
    _no_maintenance()


def check_a_restore_puts_the_files_aside_and_follows_this_install_db_path():
    """The round trip, and where the database lands.

    `db_path` is this install's answer and not the backup's: the machine being
    restored onto has already been told where the database belongs, and the
    `server_config.json` landing in the same run may well name a third place,
    which takes effect on the next start the way `db_path` always has.
    """
    head("a restore puts the files aside and follows this install's db_path")

    db = fresh_db()
    _clear_log(db)
    write_server_cfg({"port": 8081})
    add_txn(db, asset_number="AM-BK-BEFORE")
    dest = _stage_backup_dir("round-trip")
    out, manifest = M._take_backup(dest)

    # The state moves on after the backup, which is what a restore undoes.
    later = add_txn(db, asset_number="AM-BK-AFTER")
    eq("the database moved on after the backup was taken",
       txn(db, later)["asset_number"], "AM-BK-AFTER")

    shutil.rmtree(M.RESTORE_ASIDE_DIR, ignore_errors=True)
    aside, got = M._restore_backup(out)

    conn = sqlite3.connect(M.DB_PATH)
    rows = [r[0] for r in conn.execute(
        "SELECT asset_number FROM transactions ORDER BY id")]
    conn.close()
    eq("the restored database is the one the backup held",
       rows, ["AM-BK-BEFORE"])
    eq("  and it landed at this install's configured db_path",
       os.path.exists(M.DB_PATH), True)
    eq("  which is where _restore_target sends it whatever the backup called "
       "it",
       M._restore_target("somewhere-else.db", "somewhere-else.db"), M.DB_PATH)
    eq("  with -wal and -shm following it",
       (M._restore_target("x.db-wal", "x.db"),
        M._restore_target("x.db-shm", "x.db")),
       (M.DB_PATH + "-wal", M.DB_PATH + "-shm"))
    eq("  while everything else lands beside the server",
       M._restore_target("server_config.json", "x.db"), M.SERVER_CFG_PATH)

    eq("what was replaced was copied aside first",
       os.path.isdir(aside) and sorted(os.listdir(aside)),
       sorted([os.path.basename(M.DB_PATH), "admin_config.json",
               "asset_lookup.xlsx", "server_config.json"]))
    eq("  one directory per run, under restore_aside",
       os.path.dirname(aside), M.RESTORE_ASIDE_DIR)

    # The aside copy is the way back, so it has to be the state that was
    # replaced rather than the state that was restored.
    conn = sqlite3.connect(os.path.join(aside, os.path.basename(M.DB_PATH)))
    was = [r[0] for r in conn.execute(
        "SELECT asset_number FROM transactions ORDER BY id")]
    conn.close()
    eq("  and holds what the restore overwrote, not what it wrote",
       was, ["AM-BK-BEFORE", "AM-BK-AFTER"])

    aside2, _ = M._restore_backup(out)
    eq("a second restore sets its own aside rather than overwriting the first",
       aside2 != aside and os.path.isdir(aside), True)

    rows = _log_rows(M.DB_PATH, "restore.finished")
    eq("finishing is written down, naming where the way back is",
       bool(rows) and aside2 in rows[-1]["detail"], True)
    eq("  at warn, this being the largest thing this console can do",
       rows[-1]["level"], "warn")
    eq("the maintenance state is over by the time it returns",
       M._maintenance_state(), None)
    shutil.rmtree(M.RESTORE_ASIDE_DIR, ignore_errors=True)
    _no_maintenance()


def check_the_backup_window_asks_and_reports_and_decides_nothing():
    """Source: the decisions are in helpers a gate can reach.

    `_export_public_cert`'s precedent (C5). The window is a Tk callback behind
    a directory picker no harness can answer, so anything it decided for
    itself would be a decision nothing checks - and what this one can decide
    is whether to replace the database.
    """
    head("the backup window asks and reports and decides nothing")

    # SRC_BACKUP_ALL since #228: the window is server_gui.py's and the
    # seven helpers below are server_archive.py's, and this group reads
    # both sides of that seam.
    tree = ast.parse(SRC_BACKUP_ALL)
    win = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "backup_restore"]
    eq("the window is there", len(win), 1)

    names = set()
    for node in ast.walk(win[0]):
        if isinstance(node, ast.Call):
            nm = _call_name(node.func)
            if nm:
                names.add(nm)
    eq("it takes the backup through the one helper",
       "_take_backup" in names, True)
    eq("  and the restore through the one helper",
       "_restore_backup" in names, True)
    eq("  and it verifies before it asks the Admin to confirm anything",
       "_restore_preflight" in names, True)
    # `do_restore` sits inside `backup_restore`, so enclosing-function
    # matching answers twice for the one call site - the trap the Storekeeper
    # actor check writes down. What is asserted is the set: those two doors
    # and nothing else reaches it.
    eq("  through the same function the restore itself verifies with, so the "
       "two doors cannot disagree",
       sorted(set(n.name for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  for c in ast.walk(n)
                  if isinstance(c, ast.Call)
                  and _call_name(c.func) == "_restore_preflight")),
       ["_restore_backup", "backup_restore", "do_restore"])
    for bad_name in ("shutil", "copy2", "makedirs", "remove"):
        eq("  and copies nothing itself (%s)" % bad_name,
           bad_name in names, False)

    # The helpers take paths and open no window, which is what makes every
    # refusal above reachable at all.
    for fn in ("_take_backup", "_restore_backup", "_read_backup_manifest",
               "_verify_backup", "_restore_target", "_backup_members",
               "_restore_preflight"):
        node = [n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == fn][0]
        text = ast.dump(node)
        eq("%s touches no Tk" % fn,
           ("messagebox" in text or "filedialog" in text
            or "Toplevel" in text), False)

    # And the excluded names are the ones the documentation states: the two
    # machine-scope secrets, the private key, and since C1 the staged key
    # beside it (ADR-0020) - the same rule one certificate earlier, a key
    # nothing has bound yet being still a key.
    excluded = sorted(M.BACKUP_EXCLUDED)
    eq("the excluded set is the two machine-scope secrets and both keys",
       excluded, ["smtp_secret.dat", "ssl_key.pem", "ssl_key_next.pem",
                  "sync_secret.dat"])
    eq("  each with a reason to show the Admin, not a bare name",
       all(len(v) > 20 for v in M.BACKUP_EXCLUDED.values()), True)

    # Nothing on the wire: a restore replaces the database, and there is
    # nobody to offer that to.
    for rule in M.app.url_map.iter_rules():
        if "backup" in rule.rule or "restore" in rule.rule:
            bad("there is an endpoint for it: %s" % rule.rule)
            break
    else:
        ok("there is deliberately no endpoint for either")


def check_records_import_refuses_a_header_and_skips_a_bad_row():
    """#269: a missing header is a refusal, not a blank Transaction.

    Before this ticket a header missing `asset_number`/`serial_number`,
    `asset_type`, `team_member` (Engineer) or `direction` became `''` or `0`
    at insert time - so any workbook, not only one this server wrote, could
    insert one blank Transaction per row. It refuses that whole, before
    writing anything, and separately skips a row that carries neither
    identifier (rule 5) rather than either inserting it blank or failing the
    file over it.
    """
    head("the records archive's header and row checks")
    try:
        import openpyxl
    except ImportError:
        skip("openpyxl is not installed - the round-trip is not exercised")
        return

    def _write(path, header, rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(header)
        for r in rows:
            ws.append(r)
        wb.save(path)

    # A header with no identifier column at all.
    path = os.path.join(STAGE, "no_identifier.xlsx")
    _write(path, ["asset_type", "team_member", "direction"],
           [["Laptop", "Brian Dawson", "Out Store"]])
    fresh_db()
    n, refusal = M._import_records_xlsx(path)
    eq("a header with neither identifier column inserts nothing", n, 0)
    eq("  and says why", bool(refusal), True)

    # A header missing the Engineer column.
    path = os.path.join(STAGE, "no_engineer.xlsx")
    _write(path, ["asset_type", "asset_number", "direction"],
           [["Laptop", "AR-9", "Out Store"]])
    fresh_db()
    n, refusal = M._import_records_xlsx(path)
    eq("a header with no Engineer column inserts nothing", n, 0)
    eq("  and says why", bool(refusal), True)

    # A well-formed header, but one row with neither identifier.
    path = os.path.join(STAGE, "one_bad_row.xlsx")
    _write(path, ["asset_type", "serial_number", "asset_number",
                  "team_member", "direction"],
           [["Laptop", "", "AR-10", "Brian Dawson", "Out Store"],
            ["Laptop", "", "", "Brian Dawson", "Out Store"]])
    db = fresh_db()
    n, refusal = M._import_records_xlsx(path)
    eq("the good row is inserted", n, 1)
    eq("  the bad one does not fail the file", refusal, "")
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    eq("  and only the good row landed", count, 1)


def check_a_fresh_database_is_stamped_and_an_old_one_is_left_alone():
    """init_db() on an empty file reads the latest version; on tables it built
    without it, tables somebody else's code built, 0 stays 0 (#275).

    A backup's manifest carries `user_version` as `schema_version`, so a fresh
    install's first backup is the proof this ticket asks for: before #275 it
    read 0 no matter how many migrations this build ships, indistinguishable
    from a v2.0.0 install nothing has ever migrated - and `update.ps1` would
    re-apply all fifteen over a database that already has every column.
    """
    head("a fresh database is stamped and an old one is left alone")

    db = fresh_db()
    eq("a database init_db() built from nothing reads the latest version",
       M._schema_version(db), M._latest_schema_version())

    dest = _stage_backup_dir("fresh-stamp-dest")
    _out, manifest = M._take_backup(dest)
    eq("  and its first backup manifest carries that same version",
       manifest["schema_version"], M._latest_schema_version())

    # A database with a table already in it - unversioned, the way a
    # v2.0.0 install or anything migrations predate reads - must stay at 0
    # so `001_baseline` onward still has something to do.
    old_path = stage_name("check_", "-preexisting.db")
    conn = sqlite3.connect(old_path)
    conn.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    eq("  a pre-existing table means it is not this init_db()'s to stamp",
       M._schema_version(old_path), 0)
    M.DB_PATH = old_path
    M.init_db()
    eq("  so init_db() over it leaves user_version at 0",
       M._schema_version(old_path), 0)
