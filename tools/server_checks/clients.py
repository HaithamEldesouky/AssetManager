r"""The client registry and the command queue behind it.

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

from server_checks.stage import (C, M, R, SRC_ALL, SRC_CLIENTS_ALL, STAGE,
                                 _admin, _caps, bad, checkin, clients,
                                 commands, eq, fresh_db, head, log_rows,
                                 moved_db, ok, seen, stage_import)



# ── the client registry ──────────────────────────────────────────────────────

CLIENT_COLS = ("client_id", "hostname", "os_user", "app", "version", "member",
               "cert_fingerprint", "reported_address", "address", "first_seen",
               "last_seen")


def check_the_client_table_is_created_both_ways():
    """A fresh database and an upgraded one must end up identical.

    Same reason as the cancel columns: a server started without anybody running
    migrate still needs the table, or the Clients panel is a SQL error rather
    than an empty list.
    """
    head("the clients table")
    db = fresh_db()
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    conn.close()
    eq("init_db() creates clients with every column",
       sorted(cols), sorted(CLIENT_COLS))

    # A database from before this ticket - no clients table at all - upgraded
    # by init_db() alone, with a Transaction in it that must survive.
    old = os.path.join(STAGE, "pre_clients.db")
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asset_type TEXT NOT NULL,
        team_member TEXT NOT NULL, direction TEXT NOT NULL,
        timestamp TEXT NOT NULL)""")
    conn.execute("INSERT INTO transactions (asset_type, team_member, direction,"
                 " timestamp) VALUES ('Laptop','Brian Dawson','Out Store',?)",
                 (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    M.DB_PATH = old
    M.init_db()
    M.init_db()          # twice: the CREATE has to be idempotent
    conn = sqlite3.connect(old)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    eq("an upgraded database has the table", sorted(cols), sorted(CLIENT_COLS))
    eq("the Transaction that was already there is untouched", n, 1)


def check_migration_004_keeps_its_table_on_the_way_down():
    """A downgrade keeps the table.

    A downgrade never drops a column, and dropping a whole table is that rule
    written larger. An older build never reads `clients`, so keeping it costs
    that build nothing; dropping it would throw away the hostname and address
    of every machine that is not in front of the Admin, and re-upgrading would
    present the whole fleet as brand new installations.
    """
    head("migration 004")
    path = os.path.join(R, "migrations", "004_client_registry.py")
    if not os.path.exists(path):
        bad("migrations/004_client_registry.py is missing")
        return
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    for want in ("up", "down"):
        if want in names:
            ok("004 defines %s()" % want)
        else:
            bad("004 does not define %s()" % want)
    down = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "down"][0]
    body = [st for st in down.body if not isinstance(st, ast.Expr)]
    if body and all(isinstance(st, ast.Return) and st.value is None
                    for st in body):
        ok("004's down() is a no-op")
    else:
        bad("004's down() does something - a downgrade keeps the table")
    up = src.upper()
    if "DROP COLUMN" in up or "DROP TABLE" in up:
        bad("004 drops something")
    else:
        ok("004 drops nothing")

    # and it applies for real, twice, then down, with a row in the table
    db = fresh_db()
    mod = {}
    exec(compile(src, path, "exec"), mod)
    conn = sqlite3.connect(db)
    mod["up"](conn)
    mod["up"](conn)
    conn.execute("INSERT INTO clients (client_id, hostname, last_seen)"
                 " VALUES ('c-1','HOST-LT-01',?)",
                 (datetime.now().isoformat(),))
    conn.commit()
    mod["down"](conn)
    rows = conn.execute("SELECT hostname FROM clients").fetchall()
    conn.close()
    eq("up() twice then down() keeps the table and its row",
       [r[0] for r in rows], ["HOST-LT-01"])


def check_a_client_can_check_in():
    """One check-in, and what the registry holds afterwards.

    Every fact the Admin needs to identify a machine and go and find it, plus
    when it was last heard from. No password: a Client holds no credential, the
    same reason ADR-0002 gives for the Transaction endpoints, and ADR-0005
    records what that does and does not expose.
    """
    head("a Client checking in")
    db = fresh_db()
    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-11220",
                 "os_user": "DOMAIN\\bdawson", "app": "Notifier",
                 "version": "2.3.0", "member": "Brian Dawson"},
                address="192.0.2.42")
    eq("the check-in is accepted", r.status_code, 200)
    body = r.get_json()
    eq("it answers with the identifier it recorded",
       body.get("client_id"), "c-abc")
    for k in ("status", "known_since", "last_seen", "commands"):
        if k in body:
            ok("the response carries %s" % k)
        else:
            bad("the response does not carry %s" % k)
    eq("commands is an empty list, so the queue is additive later",
       body.get("commands"), [])

    rows = clients(db)
    eq("one installation is registered", len(rows), 1)
    row = rows[0]
    for field, want in (("hostname", "HOST-LT-11220"),
                        ("os_user", "DOMAIN\\bdawson"),
                        ("app", "Notifier"), ("version", "2.3.0"),
                        ("member", "Brian Dawson")):
        eq("the registry records %s" % field, row[field], want)
    eq("the source address is taken from the request, not the body",
       row["address"], "192.0.2.42")
    # `or 1e9` here read a genuine 0.0 - a check-in and a read inside one clock
    # tick, which Windows' ~16ms resolution makes ordinary - as unreadable, and
    # failed a release gate at random.
    since = M._since_ts(row["last_seen"])
    if since is not None and since < 60:
        ok("last_seen is now")
    else:
        bad("last_seen is not now: %r" % (row["last_seen"],))
    eq("first_seen and last_seen agree on a first check-in",
       row["first_seen"], row["last_seen"])
    # A minute ago and a week ago have to read differently, which is the whole
    # point of the column.
    eq("a fresh check-in reads as recent", M._ago_ts(row["last_seen"]),
       "just now")
    week = (datetime.now() - timedelta(days=7)).isoformat()
    eq("a week-old one does not", M._ago_ts(week), "7d ago")
    if M._client_colour(row["last_seen"]) != M._client_colour(week):
        ok("and the two are coloured differently")
    else:
        bad("a Client seen now and one seen a week ago look the same")


def check_a_client_reports_its_own_address():
    """The address a Client says it has, beside the one this server saw (#281).

    Behind a NAT or VPN gateway the peer is the gateway for every Client, so
    the claim is kept in a column of its own and `address` stays the peer:
    the two have to come back different, or one has overwritten the other. A
    Client too old to send it reads "", and a long value is capped like every
    other field on this unauthenticated route.
    """
    head("a Client reporting its own address")
    db = fresh_db()
    _admin()
    checkin({"client_id": "c-nat", "hostname": "client-lt-11220",
             "app": "Notifier", "reported_address": "198.51.100.11"},
            address="198.51.100.29")
    checkin({"client_id": "c-old", "hostname": "store-11-9365",
             "app": "Storekeeper"}, address="198.51.100.29")
    checkin({"client_id": "c-long", "reported_address": "9" * 500})
    rows = {r["client_id"]: r for r in clients(db)}
    eq("the claim is stored in its own column",
       rows["c-nat"]["reported_address"], "198.51.100.11")
    eq("  and address is still the peer this server saw",
       rows["c-nat"]["address"], "198.51.100.29")
    eq("a check-in without it stores ''", rows["c-old"]["reported_address"], "")
    eq("an over-long value is capped",
       len(rows["c-long"]["reported_address"]), M._CHECKIN_MAX)

    r = M.app.test_client().get("/clients", base_url="https://localhost",
                                json={"password": "admin"})
    eq("GET /clients answers the admin password", r.status_code, 200)
    got = {c["client_id"]: c for c in (r.get_json() or {}).get("clients", [])}
    eq("  and carries both addresses, each its own",
       (got.get("c-nat", {}).get("reported_address"),
        got.get("c-nat", {}).get("address")),
       ("198.51.100.11", "198.51.100.29"))
    eq("  with '' for the Client that sent none",
       got.get("c-old", {}).get("reported_address"), "")


def check_migration_016_adds_the_column_both_ways():
    """016 up, up, down against the table as 013 left it, then init_db().

    Same shape as 013's check, for the same reason: a downgrade keeps the
    column and every row on it, and a server nobody ran migrate on gets it
    from init_db() alone.
    """
    head("migration 016")
    path = os.path.join(R, "migrations", "016_client_reported_address.py")
    if not os.path.exists(path):
        bad("migrations/016_client_reported_address.py is missing")
        return
    src = io.open(path, encoding="utf-8").read()
    if "DROP COLUMN" in src.upper() or "DROP TABLE" in src.upper():
        bad("016 drops something")
    else:
        ok("016 drops nothing")

    def pre_016(db):
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE IF EXISTS clients")
        conn.execute("""CREATE TABLE clients (
            client_id  TEXT PRIMARY KEY, hostname TEXT DEFAULT '',
            os_user TEXT DEFAULT '', app TEXT DEFAULT '',
            version TEXT DEFAULT '', member TEXT DEFAULT '',
            cert_fingerprint TEXT DEFAULT '', address TEXT DEFAULT '',
            first_seen TEXT DEFAULT '', last_seen TEXT DEFAULT '')""")
        conn.execute("INSERT INTO clients (client_id, hostname, last_seen)"
                     " VALUES ('c-1','HOST-LT-01',?)",
                     (datetime.now().isoformat(),))
        conn.commit()
        return conn

    conn = pre_016(fresh_db())
    mod = {}
    exec(compile(src, path, "exec"), mod)
    mod["up"](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    eq("up() adds the column", "reported_address" in cols, True)
    eq("  reading '' for a row that was already there",
       conn.execute("SELECT reported_address FROM clients").fetchone()[0], "")
    conn.execute("UPDATE clients SET reported_address='198.51.100.11'")
    conn.commit()
    mod["down"](conn)
    mod["up"](conn)          # up again over a kept column must not raise
    rows = conn.execute("SELECT hostname, reported_address FROM clients"
                        ).fetchall()
    conn.close()
    eq("down() then up() keeps the column and the row on it",
       [tuple(r) for r in rows], [("HOST-LT-01", "198.51.100.11")])

    old = os.path.join(STAGE, "pre_reported_address.db")
    if os.path.exists(old):
        os.remove(old)
    pre_016(old).close()
    M.DB_PATH = old
    M.init_db()
    M.init_db()          # twice: the ALTER has to be idempotent
    conn = sqlite3.connect(old)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    n = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    conn.close()
    eq("init_db() adds it to a table that predates it",
       "reported_address" in cols, True)
    eq("  keeping the installation already recorded", n, 1)


def check_a_client_that_moves_updates_its_row():
    """A renamed machine or a new DHCP lease is the same installation.

    The key is the identifier the Client keeps in its own configuration, so
    neither a hostname nor an address change can produce a second entry - the
    failure this table exists to avoid is an Admin counting duplicates of one
    laptop. A genuinely new identity is a new row, because a reinstall that
    cleared the configuration is a new installation.
    """
    head("a Client that moves")
    db = fresh_db()
    checkin({"client_id": "c-abc", "hostname": "HOST-LT-01", "app": "Notifier",
             "version": "2.3.0", "member": "Brian Dawson"},
            address="192.0.2.42")
    first = clients(db)[0]["first_seen"]

    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01",
                 "app": "Notifier", "version": "2.3.0",
                 "member": "Brian Dawson"}, address="192.0.2.99")
    eq("a check-in from a new address is accepted", r.status_code, 200)
    rows = clients(db)
    eq("it did not create a second entry", len(rows), 1)
    eq("the address moved", rows[0]["address"], "192.0.2.99")
    eq("first_seen did not", rows[0]["first_seen"], first)

    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-RENAMED",
                 "app": "Notifier", "version": "2.4.0",
                 "member": "Carol Evans"}, address="192.0.2.99")
    rows = clients(db)
    eq("a renamed machine is still one entry", len(rows), 1)
    eq("the hostname moved", rows[0]["hostname"], "HOST-LT-RENAMED")
    eq("so did the version", rows[0]["version"], "2.4.0")
    eq("and the configured Engineer", rows[0]["member"], "Carol Evans")
    eq("first_seen still did not", rows[0]["first_seen"], first)

    checkin({"client_id": "c-xyz", "hostname": "HOST-LT-01",
             "app": "Notifier", "version": "2.3.0", "member": "Brian Dawson"},
            address="192.0.2.42")
    rows = clients(db)
    eq("a new identity on the same hostname is a second entry", len(rows), 2)
    eq("both are listed", sorted(r["client_id"] for r in rows),
       ["c-abc", "c-xyz"])

    # A check-in is the Client's whole statement about itself, not a patch of
    # one field: a Notifier reset to nobody must stop claiming the last
    # Engineer, and the Storekeeper has none to claim.
    checkin({"client_id": "c-abc", "hostname": "HOST-LT-RENAMED",
             "app": "Notifier", "version": "2.4.0"}, address="192.0.2.99")
    row = [r for r in clients(db) if r["client_id"] == "c-abc"][0]
    eq("an omitted Engineer is cleared, not kept", row["member"], "")


def check_a_checkin_refuses_nonsense():
    """The identifier is the only required field, and it is bounded.

    This endpoint is unauthenticated, so a caller on the network decides both
    the key and every value. The cap is what stops one of them being a
    megabyte; the refusals are what stop a row with no identity at all, which
    would be an entry the Admin can neither recognise nor match to a machine.
    """
    head("a check-in that makes no sense")
    db = fresh_db()
    for label, body in (("no client_id at all", {"hostname": "HOST-LT-01"}),
                        ("an empty client_id", {"client_id": ""}),
                        ("whitespace only", {"client_id": "   "}),
                        ("client_id null", {"client_id": None})):
        r = checkin(body)
        eq("%s is refused" % label, r.status_code, 400)
        eq("  with a code", r.get_json().get("code"), "no_client_id")
    r = checkin({"client_id": "c" * 200})
    eq("an over-long client_id is refused", r.status_code, 400)
    eq("  with its own code", r.get_json().get("code"), "bad_client_id")
    eq("nothing was written by any of them", len(clients(db)), 0)

    r = checkin({"client_id": "c-abc", "hostname": "H" * 400,
                 "os_user": "U" * 400})
    eq("an over-long field is accepted", r.status_code, 200)
    row = clients(db)[0]
    eq("but stored capped", len(row["hostname"]), M._CHECKIN_MAX)
    eq("every field of it", len(row["os_user"]), M._CHECKIN_MAX)


def check_the_client_registry_is_not_published():
    """The registry is never published to a caller holding nothing.

    It is a map of hostnames, Windows account names and addresses of machines
    on the internal network, so a GET answering it to anybody who can reach the
    port is what ADR-0005 said must not exist - and until #174 the answer was
    that there was no such route at all, the Server GUI reading the table.
    #174 gives it one and keeps the **property** rather than the absence: the
    asymmetry is what this group is about and it is unchanged. A caller holding
    no credential may write a row here (`POST /clients/checkin`, ADR-0002) and
    may still not read one back.

    So what is asserted is that the only GET under this prefix is `/clients`
    itself and that it is **closed**, which is a stronger statement than the
    absence was: an absent route could say nothing about the map still being
    unreadable once somebody added one. The heartbeat is untouched either way
    - ADR-0005 is the record of why the check-in is not an extension of it.
    """
    head("what the registry does not expose")
    rules = [(str(r.rule), sorted(r.methods - {"HEAD", "OPTIONS"}))
             for r in M.app.url_map.iter_rules()]
    checkins = [m for rule, m in rules if rule == "/clients/checkin"]
    eq("/clients/checkin exists and is a POST", checkins, [["POST"]])
    readable = sorted(rule for rule, m in rules
                      if rule.startswith("/clients") and "GET" in m)
    eq("the one GET under /clients is the registry read itself (#174)",
       readable, ["/clients"])
    _c = M.app.test_client()
    for label, kw in (("no credential at all", {}),
                      ("an empty one", {"json": {"password": ""}}),
                      ("something made up",
                       {"json": {"password": "letmein"}})):
        r = _c.get("/clients", base_url="https://localhost", **kw)
        eq("  and %s reads nothing of it" % label,
           r.status_code in (401, 403), True)

    db = fresh_db()
    checkin({"client_id": "c-abc", "hostname": "HOST-LT-01", "app": "Notifier"})
    body = M.app.test_client().get("/health").get_json()
    leaked = [k for k in body
              if k in ("clients", "client_id", "hostname", "os_user")]
    eq("the heartbeat still says nothing about Clients", leaked, [])
    eq("and it still answers with nothing attached", body.get("status"), "ok")

    # The GUI reads the table through the one reader, and renders last_seen
    # through the shared 'ago', which is what makes a minute distinguishable
    # from a week.
    tree = ast.parse(SRC_CLIENTS_ALL)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}
    for want in ("client_list", "_client_rows", "_record_checkin", "_ago_ts",
                 "_client_colour"):
        if want in fns:
            ok("%s() exists" % want)
        else:
            bad("%s() is missing" % want)
            return
    body_src = ast.unparse(fns["client_list"])
    for needle in ("_client_rows", "_ago_ts", "_when_ts", "_client_colour"):
        if needle in body_src:
            ok("the window uses %s" % needle)
        else:
            bad("the window does not use %s" % needle)
    for col in ("hostname", "os_user", "member", "address", "version", "app",
                "last_seen"):
        if col in body_src:
            ok("the window shows %s" % col)
        else:
            bad("the window does not show %s" % col)
    if "test_client" not in body_src and "requests" not in body_src:
        ok("and reaches no endpoint to do it")
    else:
        bad("the window calls an endpoint")


# ── the command queue ────────────────────────────────────────────────────────

COMMAND_COLS = ("id", "client_id", "command", "issued_at", "issued_by",
                "expires_at", "collected_at")


def check_the_command_table_is_created_both_ways():
    """A fresh database and an upgraded one must end up identical.

    Third time for this pattern, and for the same reason: a server started
    without anybody running migrate still needs the table, or every check-in
    raises instead of answering.
    """
    head("the client_commands table")
    db = fresh_db()
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(client_commands)")]
    idx = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
        " AND tbl_name='client_commands'")]
    conn.close()
    eq("init_db() creates client_commands with every column",
       sorted(cols), sorted(COMMAND_COLS))
    if "idx_client_commands_pending" in idx:
        ok("and the index every check-in reads through")
    else:
        bad("the pending index is missing: %s" % idx)

    # A database from before this ticket - the clients table but no commands.
    old = os.path.join(STAGE, "pre_commands.db")
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE clients (client_id TEXT PRIMARY KEY,"
                 " hostname TEXT DEFAULT '', last_seen TEXT DEFAULT '')")
    conn.commit()
    conn.close()
    M.DB_PATH = old
    M.init_db()
    M.init_db()          # twice: the CREATE has to be idempotent
    conn = sqlite3.connect(old)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(client_commands)")]
    conn.close()
    eq("an upgraded database has the table", sorted(cols),
       sorted(COMMAND_COLS))


def check_migration_005_keeps_its_table_on_the_way_down():
    """A downgrade keeps the table, and reverses the index.

    Dropping the table would throw away the record of every command the Admin
    issued, including the collected ones - the only evidence that a machine was
    ever told to do something. The index carries no data, so reversing that is
    exactly what a down() is for.
    """
    head("migration 005")
    path = os.path.join(R, "migrations", "005_client_commands.py")
    if not os.path.exists(path):
        bad("migrations/005_client_commands.py is missing")
        return
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    for want in ("up", "down"):
        if want in names:
            ok("005 defines %s()" % want)
        else:
            bad("005 does not define %s()" % want)
    up_src = src.upper()
    if "DROP TABLE" in up_src or "DROP COLUMN" in up_src:
        bad("005 drops a table or a column")
    else:
        ok("005 drops no table and no column")
    if "DROP INDEX" in up_src:
        ok("it does drop its index, which is what down() is for")
    else:
        bad("005's down() does not reverse its index")

    db = fresh_db()
    mod = {}
    exec(compile(src, path, "exec"), mod)
    conn = sqlite3.connect(db)
    mod["up"](conn)
    mod["up"](conn)
    conn.execute("INSERT INTO client_commands (client_id, command, issued_at,"
                 " expires_at) VALUES ('c-1','logoff',?,?)",
                 (datetime.now().isoformat(),
                  (datetime.now() + timedelta(days=7)).isoformat()))
    conn.commit()
    mod["down"](conn)
    rows = conn.execute("SELECT command FROM client_commands").fetchall()
    idx = conn.execute("SELECT name FROM sqlite_master WHERE type='index'"
                       " AND tbl_name='client_commands'").fetchall()
    conn.close()
    eq("up() twice then down() keeps the table and its row",
       [r[0] for r in rows], ["logoff"])
    eq("and the index is gone", [r[0] for r in idx], [])


def check_a_command_can_be_queued():
    """Both commands, and what the row carries.

    Seven days by default, written into the row at issue time so changing the
    default later cannot move the deadline of a command already waiting.
    """
    head("queueing a command")
    db = fresh_db()
    _admin()
    seen("c-abc")
    # C3 adds the third and #177 the fourth, and this list is the whole of
    # what a Client may be told to do: a command that is in it and obeyed by
    # nobody is rule 8's permission that gates nothing, one command further
    # out.
    eq("the four commands are the ones that exist", sorted(M.COMMANDS),
       ["logoff", "reset_identity", "trust_cert", "update_now"])
    eq("and every one of them has a label",
       sorted(M.COMMAND_LABELS), sorted(M.COMMANDS))
    eq("the default expiry is seven days", M.COMMAND_TTL_DAYS, 7)

    for cmd in ("logoff", "reset_identity"):
        payload, status = M._queue_command(
            "c-abc", cmd, issued_by="Admin (Server GUI)")
        eq("%s is queued" % cmd, status, 201)
        eq("  with a status", payload.get("status"), "queued")
    rows = commands(db, "c-abc")
    eq("both are waiting", [r["command"] for r in rows],
       ["logoff", "reset_identity"])
    row = rows[0]
    eq("nothing has collected it yet", row["collected_at"], "")
    eq("who issued it is recorded", row["issued_by"], "Admin (Server GUI)")
    days = ((datetime.fromisoformat(row["expires_at"])
             - datetime.fromisoformat(row["issued_at"])).total_seconds()
            / 86400.0)
    if 6.99 < days < 7.01:
        ok("it expires seven days after it was issued")
    else:
        bad("the expiry is %.3f days after issue" % days)
    eq("a waiting command reads as queued", M._command_status(row), "queued")

    # the same command twice while the first is still waiting
    payload, status = M._queue_command("c-abc", "logoff")
    eq("the same command again is refused", status, 409)
    eq("  with a code", payload.get("code"), "already_queued")
    eq("  naming the one in the way", payload.get("id"), row["id"])
    eq("and nothing was added", len(commands(db, "c-abc")), 2)


def check_what_the_queue_refuses_whoever_asked():
    """The rules that are the **helper's** and not the door's.

    `_queue_command` checked the admin password inside itself until #174, and
    this group asserted that. It cannot any more and must not: the endpoint
    `POST /clients/command` is a second caller now, opened by the admin
    password **or** the Server Settings capability over HTTPS, and a helper
    holding a password could only ever know about the first of the two - so it
    takes an **actor**, which is `_modify_transaction`'s shape at R1 and
    `_save_asset`'s and `_decide_proposal`'s before it.

    There is still **no unauthenticated path**, which is now two facts in two
    places rather than one: the console asks `_admin_password_ok` itself before
    it calls this, and the endpoint asks `_remote_authorise`. Both are asserted
    - the console's as source, it being a Tk callback no harness reaches, and
    the endpoint's in the delegated-channel group below.

    What is left here is what the helper refuses however it was reached, and
    that is the half that must not have moved with the password.
    """
    head("what the queue refuses whoever asked")
    db = fresh_db()
    _admin()
    seen("c-abc")

    payload, status = M._queue_command("c-abc", "reboot")
    eq("an unknown command is refused", status, 400)
    eq("  with a code", payload.get("code"), "bad_command")

    payload, status = M._queue_command("c-never", "logoff")
    eq("a Client that has never checked in is refused", status, 404)
    eq("  with a code", payload.get("code"), "unknown_client")
    eq("still nothing queued", len(commands(db)), 0)

    payload, status = M._queue_command("c-abc", "", issued_by="A")
    eq("and an empty command is not a command either", status, 400)
    eq("  with a code", payload.get("code"), "bad_command")
    eq("nothing at all was queued by any of them", len(commands(db)), 0)


def _stage_client_zip(key="notifier"):
    """Put a client package where `_client_package` looks for one.

    `update_now` is the first command whose queueing depends on something on
    disk beside the server, so the check has to produce that state rather than
    inherit it: the staged copy this file imports has no dist directory at
    all, which is the same state a server nobody copied the bundles onto is
    in.
    """
    d = os.path.join(M.BASE_DIR, "dist", M.APP_VERSION)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s-%s.zip"
                        % (M.CLIENT_PACKAGES[key], M.APP_VERSION))
    with open(path, "wb") as fh:
        fh.write(b"not a real zip, and nothing here opens it")
    return path


def check_an_update_is_refused_where_there_is_nothing_to_apply():
    """`update_now` against a server holding no package for that app (#177).

    The command's whole promise is that the machine applies the published
    release with nobody at it. A server with no zip for that app cannot keep
    it: the client's own answer would be to open a browser at the installer,
    which is not what an Admin pressing Update Selected asked for and is not
    something a queue can be told about afterwards - a `collected` row would
    read as an update that happened. So it is refused at issue time, naming
    what is missing, while the three commands that depend on nothing on disk
    are queued exactly as they were.
    """
    head("an update with no package behind it")
    db = fresh_db()
    _admin()
    seen("c-abc", app="Notifier")

    payload, status = M._queue_command("c-abc", "update_now")
    eq("with no package on this server it is refused", status, 409)
    eq("  with a code", payload.get("code"), "no_package")
    if M.APP_VERSION in str(payload.get("error", "")):
        ok("  naming the version there is nothing to apply at")
    else:
        bad("the refusal does not name the version: %r" % payload.get("error"))
    eq("nothing was queued", len(commands(db, "c-abc")), 0)
    payload, status = M._queue_command("c-abc", "reset_identity")
    eq("and a command that needs no package still queues", status, 201)

    _stage_client_zip("notifier")
    payload, status = M._queue_command("c-abc", "update_now")
    eq("with the package there it is queued", status, 201)
    eq("  and is waiting", payload.get("status"), "queued")

    # The other app's package is a different file, and a Client is answered
    # about its own: _APP_PACKAGE_KEY is what maps the name the check-in
    # reports onto the key the zip is filed under, and a Storekeeper is not
    # updated by a Notifier bundle sitting beside it.
    seen("c-sk", host="HOST-STORE", app="Storekeeper")
    payload, status = M._queue_command("c-sk", "update_now")
    eq("a Storekeeper is not answered with the Notifier's package",
       status, 409)
    eq("  with a code", payload.get("code"), "no_package")
    _stage_client_zip("storekeeper")
    payload, status = M._queue_command("c-sk", "update_now")
    eq("and with its own package it is queued", status, 201)

    # An app this build has no mapping for at all - a Client from a future
    # release, or one that reported nothing - is the same answer rather than a
    # traceback, since the mapping is what says which zip to look for.
    seen("c-odd", host="IT-ODD", app="Something Else")
    payload, status = M._queue_command("c-odd", "update_now")
    eq("an app with no package key is refused the same way", status, 409)
    eq("  with a code", payload.get("code"), "no_package")


def check_an_update_and_a_logoff_are_never_queued_together():
    """The one pair `_COMMAND_ORDER` cannot settle (#177).

    Both end the process and only one of them brings the app back, and
    neither handler is synchronous - the update handler returns the moment its
    download worker starts - so obeyed in one batch the logoff either takes
    the process down mid-download or is undone by the applier relaunching the
    app it just closed. No ordering answers that, so the pair is refused at
    the moment of the click instead, which is also the answer an Admin can act
    on. Both directions, because which of the two was queued first must not
    change what the second is told.
    """
    head("an update and a logoff are never queued together")
    db = fresh_db()
    _admin()
    seen("c-abc")
    _stage_client_zip("notifier")

    payload, status = M._queue_command("c-abc", "logoff")
    eq("a logoff is queued", status, 201)
    first = payload.get("id")
    payload, status = M._queue_command("c-abc", "update_now")
    eq("an update behind it is refused", status, 409)
    eq("  with a code", payload.get("code"), "conflicts")
    eq("  naming the one in the way", payload.get("id"), first)
    eq("  and which command that is", payload.get("command"), "logoff")
    eq("nothing was added", [r["command"] for r in commands(db, "c-abc")],
       ["logoff"])

    db = fresh_db()
    _admin()
    seen("c-abc")
    _stage_client_zip("notifier")
    payload, status = M._queue_command("c-abc", "update_now")
    eq("the other way round, an update is queued", status, 201)
    second = payload.get("id")
    payload, status = M._queue_command("c-abc", "logoff")
    eq("a logoff behind it is refused", status, 409)
    eq("  with a code", payload.get("code"), "conflicts")
    eq("  naming the one in the way", payload.get("id"), second)
    eq("and still one command", len(commands(db, "c-abc")), 1)

    # The refusal is about the pair and not about queueing at all: everything
    # that is not that pair still goes in beside an update.
    payload, status = M._queue_command("c-abc", "trust_cert")
    eq("a certificate push beside an update is fine", status, 201)
    payload, status = M._queue_command("c-abc", "reset_identity")
    eq("and so is a reset", status, 201)

    # Once the logoff has been collected there is nothing left to race, so the
    # pair is allowed again - the same door the duplicate guard leaves open
    # for a second certificate push.
    db = fresh_db()
    _admin()
    seen("c-abc")
    _stage_client_zip("notifier")
    M._queue_command("c-abc", "logoff")
    # The check-in is this Client's whole statement about itself and every
    # field is overwritten, so it is made through the same helper that
    # registered it - a bare {client_id} would clear the app column and the
    # refusal under test would be the missing package instead.
    seen("c-abc")
    payload, status = M._queue_command("c-abc", "update_now")
    eq("a collected logoff is no longer in the way", status, 201)


def check_the_commands_agree_across_the_three_places_they_are_written():
    """`COMMANDS`, `COMMAND_LABELS` and `common._COMMAND_ORDER` (#177).

    Three copies of one set, in two files that cannot import each other - the
    server does not import `common.py` (rule 10) - so a command added to one
    is drift the moment it is not added to the others, and drift here is
    quiet: a command with no label is offered to an Admin as its own name, and
    one with no order is sorted with the unlisted middle rather than where it
    was reasoned about.
    """
    head("the commands agree wherever they are written down")
    eq("every command has a label",
       sorted(M.COMMAND_LABELS), sorted(M.COMMANDS))

    order = C._COMMAND_ORDER
    eq("and every command has an order", sorted(order), sorted(M.COMMANDS))
    if order["logoff"] == max(order.values()):
        ok("the logoff is obeyed last")
    else:
        bad("the logoff is not last in the order: %r" % (order,))
    if order["update_now"] < order["logoff"]:
        ok("and the update is obeyed before it")
    else:
        bad("update_now does not sit in front of the logoff: %r" % (order,))
    for earlier in ("reset_identity", "trust_cert"):
        if order[earlier] < order["update_now"]:
            ok("%s is obeyed before the update" % earlier)
        else:
            bad("%s is not in front of update_now: %r" % (earlier, order))

    # The pair that no ordering settles is refused instead, and that is the
    # only entry in the conflict table - a second one would be a rule about
    # ordering written in the wrong place.
    eq("the conflict table is that one pair, written both ways",
       {k: tuple(v) for k, v in M._COMMAND_CONFLICTS.items()},
       {"update_now": ("logoff",), "logoff": ("update_now",)})
    for name in M._COMMAND_CONFLICTS:
        eq("  %s is a command" % name, name in M.COMMANDS, True)
    for others in M._COMMAND_CONFLICTS.values():
        for name in others:
            eq("  %s is a command" % name, name in M.COMMANDS, True)


def check_a_client_collects_only_its_own_commands():
    """The check-in hands back what is queued for that Client and nothing else.

    Two installations on one machine is the ordinary case - a reinstall leaves
    the old row behind - so a command must never leak between identifiers.
    """
    head("a Client collects its own commands")
    db = fresh_db()
    _admin()
    seen("c-abc", host="HOST-LT-01")
    seen("c-xyz", host="HOST-LT-02")
    M._queue_command("c-abc", "logoff")
    M._queue_command("c-xyz", "reset_identity")

    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    got = r.get_json().get("commands")
    eq("the first Client is handed one command", len(got or []), 1)
    eq("  and it is its own", got[0]["command"], "logoff")
    for k in ("id", "command", "issued_at"):
        if k in got[0]:
            ok("the command carries %s" % k)
        else:
            bad("the command does not carry %s" % k)

    r = checkin({"client_id": "c-xyz", "hostname": "HOST-LT-02"})
    got = r.get_json().get("commands")
    eq("the second Client gets only its own", [c["command"] for c in got],
       ["reset_identity"])
    eq("neither collected the other's",
       sorted((c["client_id"], c["command"]) for c in commands(db)),
       [("c-abc", "logoff"), ("c-xyz", "reset_identity")])


def check_a_collected_command_is_not_handed_over_twice():
    """At most once, and visibly collected afterwards.

    There is no channel for a Client to say it obeyed, so a command left
    queued until an acknowledgement arrived would be handed out on every
    check-in - a laptop that crashed mid-logoff would be logged off for ever.
    A collected command that was not obeyed shows as collected, which the Admin
    can see and act on.
    """
    head("a command is handed over once")
    db = fresh_db()
    _admin()
    seen("c-abc")
    M._queue_command("c-abc", "logoff")

    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    eq("the first check-in collects it",
       [c["command"] for c in r.get_json()["commands"]], ["logoff"])
    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    eq("the second gets nothing", r.get_json()["commands"], [])
    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    eq("and so does the third", r.get_json()["commands"], [])

    row = commands(db, "c-abc")[0]
    if row["collected_at"]:
        ok("the row records when it was collected")
    else:
        bad("collected_at is empty after a collection")
    eq("and it reads as collected", M._command_status(row), "collected")
    eq("the row is kept, not deleted", len(commands(db)), 1)

    # queueing the same command again is allowed once the first was collected
    payload, status = M._queue_command("c-abc", "logoff")
    eq("the same command can be queued again afterwards", status, 201)
    eq("which is a second row", len(commands(db)), 2)


def check_an_expired_command_is_kept_and_never_handed_over():
    """Expired is a state, not a deletion.

    A command issued a month ago must not fire on a laptop coming back from
    long leave. It stays in the list so the Admin can see it was issued and
    never collected, which is the signal that the machine has not been running
    - deleting it would leave the Admin with no answer at all.
    """
    head("an expired command")
    db = fresh_db()
    _admin()
    seen("c-abc")
    M._queue_command("c-abc", "logoff")
    cid_row = commands(db, "c-abc")[0]
    stale = (datetime.now() - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(db)
    conn.execute("UPDATE client_commands SET expires_at=? WHERE id=?",
                 (stale, cid_row["id"]))
    conn.commit()
    conn.close()

    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    eq("an expired command is not handed over", r.get_json()["commands"], [])
    row = commands(db, "c-abc")[0]
    eq("it was not marked collected either", row["collected_at"], "")
    eq("and it reads as expired", M._command_status(row), "expired")
    eq("the row is kept", len(commands(db)), 1)

    # and an expired one does not block a fresh one
    payload, status = M._queue_command("c-abc", "logoff")
    eq("an expired command does not block re-queueing", status, 201)
    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    eq("the new one is collected", len(r.get_json()["commands"]), 1)


def check_a_queued_command_survives_a_restart():
    """The queue is in the database, so a restart is not a loss.

    A command for a laptop closed for a week has to still be there when it
    opens, and under IIS an application-pool recycle would take an in-memory
    queue with it and leave no record it had ever existed. Imported fresh, the
    way a restart does it - not by resetting DB_PATH on the module already
    loaded, which would prove nothing about a new process.
    """
    head("a queued command survives a restart")
    db = moved_db("restart_queue")
    keep = M.DB_PATH
    M.DB_PATH = db
    _admin()
    seen("c-abc")
    M._queue_command("c-abc", "logoff")
    M.DB_PATH = keep
    eq("one command is waiting on disk", len(commands(db)), 1)

    mod, _d = stage_import("restart_srv", {"host": "127.0.0.1", "port": 8099,
                                           "db_path": db})
    eq("the fresh process opens the same database", mod.DB_PATH, db)
    r = mod.app.test_client().post(
        "/clients/checkin", json={"client_id": "c-abc",
                                  "hostname": "HOST-LT-01"},
        environ_base={"REMOTE_ADDR": "192.0.2.42"})
    eq("and hands the command over", r.status_code, 200)
    eq("  the one that was queued before the restart",
       [c["command"] for c in r.get_json()["commands"]], ["logoff"])
    eq("marked collected in the same database",
       M._command_status(commands(db)[0]), "collected")


def check_the_client_registry_over_the_delegated_channel():
    """Connected Clients from somewhere else (#174).

    The console's Connected Clients window put on the network behind the
    **Server Settings** capability password - the last of that capability's
    four areas. What has to hold across the move is that nothing about the acts
    themselves moved: `_queue_command` and `_push_next_cert` are the one path
    either way, so the duplicate guard, the refusal for a Client that has never
    checked in and the seven-day expiry are the same rules in the same words.

    What the wire adds, and what is asserted here:

      - **`GET /clients` is never open.** It is the one credential-less-looking
        read this server must not have: `GET /permissions` and
        `GET /asset_models` answer facts about this build, where this answers a
        map of hostnames, Windows account names and source addresses of
        machines on the internal network - ADR-0005's own sentence, kept by
        putting a credential on the route rather than by weakening it.
      - **The transport rule is strict on both credentials**, these routes
        being new, for the mail routes' reason (#172).
      - **The act is attributed to the delegate**, in the row's `issued_by` and
        in the `client.command_issued` entry beside it, and nothing the caller
        sends names the issuer.
      - **The push is a route of its own**, so commanding the whole fleet is
        never reachable by leaving `client_id` out of the one-machine route.
    """
    head("the Client registry over the delegated channel (#174)")
    db = fresh_db()
    _caps(server_settings="setpw", manage_records="mrpw")
    M.ADMIN_CFG["capability_holders"] = {"server_settings": "Ops on-call"}
    seen("c-abc", host="HOST-LT-01")
    seen("c-xyz", host="HOST-LT-02", app="Storekeeper")
    c = M.app.test_client()
    HTTPS = "https://localhost"

    def read(pw, base=HTTPS):
        r = c.get("/clients", base_url=base, json={"password": pw})
        return r.status_code, (r.get_json() or {})

    def command(pw, base=HTTPS, **body):
        r = c.post("/clients/command", base_url=base,
                   json=dict(body, password=pw))
        return r.status_code, (r.get_json() or {})

    def push(pw, base=HTTPS):
        r = c.post("/clients/push_cert", base_url=base,
                   json={"password": pw})
        return r.status_code, (r.get_json() or {})

    # -- the door ---------------------------------------------------------
    code, body = read("setpw", base="http://localhost")
    eq("the read over plain HTTP is refused before the password is examined",
       (code, body.get("code")), (403, "insecure"))
    code, body = read("admin", base="http://localhost")
    eq("  and so is the admin password - these routes are new, so there is no "
       "install to break by holding both to the transport rule",
       (code, body.get("code")), (403, "insecure"))
    code, body = read("")
    eq("no credential at all reads nothing - this route is never open",
       (code, body.get("code")), (401, "bad_password"))
    code, body = read("mrpw")
    eq("  and another capability's password opens nothing here",
       (code, body.get("code")), (401, "bad_password"))
    code, body = command("setpw", base="http://localhost", client_id="c-abc",
                         command="logoff")
    eq("a command over plain HTTP is refused",
       (code, body.get("code")), (403, "insecure"))
    code, body = push("setpw", base="http://localhost")
    eq("  and so is a push", (code, body.get("code")), (403, "insecure"))
    eq("nothing was queued by any of them", len(commands(db)), 0)

    # -- the read ---------------------------------------------------------
    code, body = read("setpw")
    eq("the Server Settings password reads the registry", code, 200)
    rows = {r["client_id"]: r for r in body.get("clients", [])}
    eq("  one entry per installation", sorted(rows), ["c-abc", "c-xyz"])
    eq("  carrying what the console column shows",
       (rows["c-abc"]["hostname"], rows["c-xyz"]["app"]),
       ("HOST-LT-01", "Storekeeper"))
    eq("  and how long ago it was heard from, so a panel can colour it",
       isinstance(rows["c-abc"].get("age_secs"), (int, float)), True)
    eq("  with no commands against it yet", rows["c-abc"]["commands"], [])
    eq("the server's own two fingerprints come with the list",
       sorted(k for k in body if k in ("served", "staged")),
       ["served", "staged"])

    # -- the command ------------------------------------------------------
    code, body = command("setpw", command="logoff")
    eq("a command naming no Client is refused after the credential",
       (code, body.get("code")), (400, "no_client"))
    code, body = command("setpw", client_id="c-abc", command="reboot")
    eq("  and a command that is not one is _queue_command's own refusal",
       (code, body.get("code")), (400, "bad_command"))
    code, body = command("setpw", client_id="c-never", command="logoff")
    eq("  as is a Client that has never checked in",
       (code, body.get("code")), (404, "unknown_client"))
    eq("still nothing queued", len(commands(db)), 0)

    code, body = command("setpw", client_id="c-abc", command="logoff",
                         issued_by="Somebody Else")
    eq("the capability queues one command", (code, body.get("status")),
       (201, "queued"))
    row = commands(db, "c-abc")[0]
    eq("  attributed to the delegate, the caller's issued_by ignored",
       row["issued_by"],
       'Delegate: Server Settings held by "Ops on-call" (remote)')
    code, body = command("setpw", client_id="c-abc", command="logoff")
    eq("the duplicate guard holds over the wire too",
       (code, body.get("code")), (409, "already_queued"))
    eq("  naming the one in the way", body.get("id"), row["id"])
    eq("and no row was stacked", len(commands(db)), 1)

    code, body = read("setpw")
    rows = {r["client_id"]: r for r in body.get("clients", [])}
    eq("the read carries the queued command with the row it is about",
       [(x["command"], x["state"]) for x in rows["c-abc"]["commands"]],
       [("logoff", "queued")])

    # -- the push ---------------------------------------------------------
    _had = {}
    for p in (M.SSL_CERT_NEXT_PATH, M.SSL_KEY_NEXT_PATH):
        _had[p] = io.open(p, "rb").read() if os.path.exists(p) else None
        if os.path.exists(p):
            os.remove(p)
    code, body = push("setpw")
    eq("with nothing staged the push is refused whoever asked",
       (code, body.get("code")), (409, "no_staged_cert"))
    try:
        from cryptography import x509           # noqa: F401
        fp = M._stage_new_cert()
    except ImportError:
        fp = None
    if fp:
        code, body = push("setpw")
        eq("the capability pushes the staged certificate", code, 200)
        eq("  one command per installation", body.get("queued"), 2)
        eq("  naming the certificate it was about",
           body.get("fingerprint"), fp)
        pushed = [r for r in log_rows(db) if r["event"] == "cert.pushed"]
        eq("  one cert.pushed per Client, under the delegate's name",
           (len(pushed),
            all(r["actor"].startswith("Delegate: Server Settings")
                for r in pushed)), (2, True))
    for p, was in _had.items():
        if was is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            with io.open(p, "wb") as f:
                f.write(was)

    # -- what did not move ------------------------------------------------
    r = c.post("/lookup/upload", base_url=HTTPS,
               json={"password": "setpw", "file_data": ""})
    eq("replacing the sheet is still the admin password and nothing else",
       r.status_code in (401, 403), True)
    r = c.post("/admin/change_password", base_url=HTTPS,
               json={"current_password": "setpw", "new_password": "letmein"})
    eq("and the admin password's own door is closed to it (rule 7)",
       r.status_code, 401)

    acts = [x for x in log_rows(db) if x["event"] == "remote.action"]
    eq("every use of the capability wrote remote.action before it, at warn",
       len(acts) > 0 and acts[-1]["level"], "warn")


def backdate(db, cid, last_seen):
    """Rewrite one Client's `last_seen` by hand.

    The only column #203 measures, and the check-in that wrote it cannot be
    asked for a date in the past - so the row is aged here rather than by
    waiting a fortnight.
    """
    conn = sqlite3.connect(db)
    conn.execute("UPDATE clients SET last_seen=? WHERE client_id=?",
                 (last_seen, cid))
    conn.commit()
    conn.close()


def check_clearing_the_clients_nobody_has_heard_from():
    """Removing the installations that are no longer there (#203).

    A row in `clients` is not a connection - it is there because that
    installation checked in once, so **how long ago** is the only question the
    list answers and the only question this delete may be asked. What is
    asserted here is that the answer is decided once:

      - **the count in the confirmation is the rows that go**, because the
        console's preview and the writer read one `_stale_clients`, which is
        the whole of why that sentence may name a number at all;
      - **a row inside the threshold survives**, and one whose `last_seen`
        cannot be read survives too - a delete is not reversible, and a
        timestamp nothing can measure is a reason to leave a row alone rather
        than to treat it as infinitely old;
      - **there is a floor**, since a threshold of nothing at all would take
        out the machine that checked in a second ago, which is a fleet reset
        rather than housekeeping;
      - **the `clients.cleared` entry names the count and the threshold**,
        that entry being the whole record those rows ever existed;
      - **the actor is whoever asked** - `Admin (Server GUI)` at the console
        and the delegate over the wire, the #174 shape, with a wrong password
        removing nothing at all;
      - and **`client_commands` is left alone on purpose**: the rows stay, and
        an installation that comes back under the identifier it has always had
        is still handed whatever is still waiting for it. That last one is the
        claim the docstring makes about `_record_checkin`, so it is driven
        rather than restated - this is **not** a way to withdraw a command.
    """
    head("clearing the Clients nobody has heard from (#203)")
    db = fresh_db()
    _caps(server_settings="setpw", manage_records="mrpw")
    M.ADMIN_CFG["capability_holders"] = {"server_settings": "Ops on-call"}
    now = datetime.now()
    seen("c-fresh", host="HOST-LT-01")
    seen("c-old", host="HOST-LT-02")
    seen("c-ancient", host="HOST-LT-03")
    seen("c-broken", host="HOST-LT-04")
    backdate(db, "c-old", (now - timedelta(days=40)).isoformat())
    backdate(db, "c-ancient", (now - timedelta(days=400)).isoformat())
    backdate(db, "c-broken", "whenever")

    payload, status = M._queue_command("c-old", "logoff",
                                       issued_by="Admin (Server GUI)")
    eq("a command is queued against one of the stale installations",
       (status, len(commands(db, "c-old"))), (201, 1))

    # -- the floor ---------------------------------------------------------
    payload, status = M._clear_stale_clients(0.5)
    eq("a threshold under the floor is refused, naming it",
       (status, payload.get("code")), (400, "bad_age"))
    payload, status = M._clear_stale_clients("not a number")
    eq("  and so is a threshold that is not a number at all",
       (status, payload.get("code")), (400, "bad_age"))
    eq("  with every installation still listed", len(M._client_rows()), 4)

    # -- the count the Admin is shown is the rows that go -------------------
    preview = M._stale_clients(30)
    eq("the reader the console previews with names the two stale rows",
       sorted(r["client_id"] for r in preview), ["c-ancient", "c-old"])
    payload, status = M._clear_stale_clients(
        30, actor="Admin (Server GUI)")
    eq("the console's clear answers 200", status, 200)
    eq("  removing exactly the rows it offered to remove",
       payload["removed"], len(preview))
    left = {r["client_id"] for r in M._client_rows()}
    eq("  the installation inside the threshold survives",
       "c-fresh" in left, True)
    eq("  and so does the one whose last_seen cannot be read, a delete being "
       "the thing that cannot be taken back",
       "c-broken" in left, True)
    eq("  and the two stale ones are gone", sorted(left),
       ["c-broken", "c-fresh"])
    eq("  with how many are left answered beside how many went",
       payload["remaining"], 2)

    entries = [x for x in log_rows(db) if x["event"] == "clients.cleared"]
    eq("one clients.cleared entry, at warn - the whole record those rows "
       "existed", (len(entries), entries[-1]["level"]), (1, "warn"))
    eq("  naming the count and the threshold",
       ("2 installation" in entries[-1]["detail"]
        and "30" in entries[-1]["detail"]), True)
    eq("  attributed to whoever was at the console",
       entries[-1]["actor"], "Admin (Server GUI)")

    # -- the commands are kept, and are still owed --------------------------
    kept = commands(db, "c-old")
    eq("the commands issued to a removed Client are kept", len(kept), 1)
    eq("  uncollected, which is the evidence that machine was not running",
       kept[0]["collected_at"], "")
    r = checkin({"client_id": "c-old", "hostname": "HOST-LT-02",
                 "app": "Notifier", "version": "2.3.0"})
    body = r.get_json() or {}
    eq("an installation that comes back is registered again", r.status_code,
       200)
    eq("  and is still handed the command still waiting for it - clearing "
       "the registry is not a way to withdraw one",
       [x["command"] for x in body.get("commands", [])], ["logoff"])

    # -- the same act over the wire -----------------------------------------
    db = fresh_db()
    _caps(server_settings="setpw", manage_records="mrpw")
    M.ADMIN_CFG["capability_holders"] = {"server_settings": "Ops on-call"}
    seen("c-fresh", host="HOST-LT-01")
    seen("c-old", host="HOST-LT-02")
    backdate(db, "c-old", (datetime.now() - timedelta(days=40)).isoformat())
    c = M.app.test_client()

    def clear(pw, base="https://localhost", **body):
        r = c.post("/clients/clear", base_url=base,
                   json=dict(body, password=pw))
        return r.status_code, (r.get_json() or {})

    code, body = clear("setpw", base="http://localhost", days=30)
    eq("the capability password over plain HTTP is refused before the "
       "password is examined", (code, body.get("code")), (403, "insecure"))
    code, body = clear("wrong", days=30)
    eq("  a wrong password is refused", (code, body.get("code")),
       (401, "bad_password"))
    code, body = clear("mrpw", days=30)
    eq("  and another capability's password opens nothing here",
       (code, body.get("code")), (401, "bad_password"))
    code, body = clear("", days=30)
    eq("  no credential at all removes nothing - this route is never open",
       (code, body.get("code")), (401, "bad_password"))
    eq("nothing was removed by any of them", len(M._client_rows()), 2)
    eq("  and nothing was written down about a refusal as a clear",
       len([x for x in log_rows(db) if x["event"] == "clients.cleared"]), 0)

    code, body = clear("setpw", days=0.5)
    eq("the floor holds on the wire too, after the credential",
       (code, body.get("code")), (400, "bad_age"))

    code, body = clear("setpw", threshold="not:a:threshold")
    eq("  and so does a threshold string that cannot be read",
       (code, body.get("code")), (400, "bad_age"))

    code, body = clear("setpw", threshold="30:0:0")
    eq("the Server Settings password clears the registry, given the d:h:m "
       "form #268 added beside days",
       (code, body.get("removed")), (200, 1))
    eq("  leaving the installation inside the threshold",
       [r["client_id"] for r in M._client_rows()], ["c-fresh"])
    entries = [x for x in log_rows(db) if x["event"] == "clients.cleared"]
    eq("  and the act is the delegate's rather than the Admin's",
       entries[-1]["actor"].startswith("Delegate: "), True)
    eq("  naming the holder the Admin wrote beside that password",
       "Ops on-call" in entries[-1]["actor"], True)


def check_the_age_threshold_is_typed_not_picked():
    """`_parse_age_threshold` / `_format_age_threshold`, and the auto-clear
    that only logs when it removed something (#268).

    The radio buttons #203 shipped are gone; what an Admin types now is
    "d:h:m", and what is asserted here is that the parser reads what the
    formatter writes, that a floor of a day still holds, and that the sweep
    which now runs on its own is quiet about finding nothing.
    """
    head("the age threshold is typed, not picked (#268)")
    eq("a day and a half reads as 1.5 days",
       M._parse_age_threshold("1:12:0"), 1.5)
    eq("a bare number is still read as whole days",
       M._parse_age_threshold("30"), 30.0)
    eq("a leading ':' means no days at all",
       M._parse_age_threshold(":6:0"), 0.25)
    eq("the formatter is the parser's inverse",
       M._parse_age_threshold(M._format_age_threshold(1.5)), 1.5)
    try:
        M._parse_age_threshold("not:a:threshold")
        bad("a threshold that is not numbers at all should have raised")
    except ValueError:
        ok("a threshold that is not numbers at all raises ValueError")
    try:
        M._parse_age_threshold("1:2:3:4")
        bad("a fourth part should have raised")
    except ValueError:
        ok("a fourth part raises ValueError")

    db = fresh_db()
    seen("c-fresh", host="HOST-LT-01")
    M._save_server_cfg(clear_age_threshold_days=30)
    payload, status = M._clear_stale_clients(
        30, actor="Auto-clear", log_when_empty=False)
    eq("a sweep that removes nothing answers 200 same as any other clear",
       (status, payload["removed"]), (200, 0))
    eq("  but writes nothing to the System Log",
       len([x for x in log_rows(db) if x["event"] == "clients.cleared"]), 0)
    backdate(db, "c-fresh", (datetime.now() - timedelta(days=40)).isoformat())
    payload, status = M._clear_stale_clients(
        30, actor="Auto-clear", log_when_empty=False)
    eq("  and does log the one time it actually removed a row",
       (status, payload["removed"]), (200, 1))
    entries = [x for x in log_rows(db) if x["event"] == "clients.cleared"]
    eq("  attributed to Auto-clear rather than an Admin",
       (len(entries), entries[-1]["actor"]), (1, "Auto-clear"))

    eq("a manual clear still logs even where nothing matched, unlike the "
       "sweep beside it",
       M._clear_stale_clients(30, actor="Admin (Server GUI)")[0]["removed"],
       0)
    eq("  the console default keeps its own name",
       len([x for x in log_rows(db) if x["event"] == "clients.cleared"]), 2)


def check_the_client_doors_are_four_routes_and_three_helpers():
    """#174 and #203, asserted as source: an absence, and a shape.

    **There is no `_client_door`.** A named door exists in this file where
    several routes share one question *and* that question has a decision of its
    own to keep in one place - `_member_door`'s `admin_is_native`, which is a
    wire-compatibility allowance. These four share nothing but the capability
    name, so a helper here would be a byte-identical copy of `_mail_door`
    (rule 10), which is `POST /records/import`'s and
    `POST /assets/proposals/decide`'s answer already.

    **It is `_remote_authorise` and not `_remote_admit(..., admin_is_native)`.**
    These routes are new and have no shipped caller sending the admin password
    to them over plain HTTP.

    **Each forwards rather than writing.** `GET /clients` reads `_client_rows`,
    the command route forwards to `_queue_command`, the push to
    `_push_next_cert` and the clear to `_clear_stale_clients` (#203), so no
    endpoint carries a second idea of the duplicate guard, the expiry, the
    fingerprint or the floor under the threshold. The clear is the one of the
    four whose own `DELETE` would look most reasonable written out here, which
    is why it is in the banned list below with the rest.

    **And none of them takes a name from the caller.** These are credentials
    rather than people, the way `POST /transactions/cancel` reads a
    `cancelled_by`.
    """
    head("the Client doors are four routes and three helpers (#174, #203)")
    tree = ast.parse(SRC_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns.setdefault(node.name, node)
    want = {"list_clients": ("_client_rows", "_command_rows"),
            "queue_client_command": ("_queue_command",),
            "push_staged_cert": ("_push_next_cert",),
            "clear_client_registry": ("_clear_stale_clients",)}
    eq("there is deliberately no _client_door, four routes with no decision "
       "of their own being what `_member_door` is not for",
       "_client_door" in SRC_ALL, False)
    for name, forwards in want.items():
        if name not in fns:
            bad("%s() is missing" % name)
            continue
        body = ast.unparse(fns[name])
        ok("%s() exists" % name)
        if "_remote_authorise(" in body and "'server_settings'" in body:
            ok("  asking _remote_authorise for the server_settings capability")
        else:
            bad("  does not ask _remote_authorise for server_settings")
        if "admin_is_native" in body:
            bad("  reaches for admin_is_native, an allowance for older doors")
        else:
            ok("  and never admin_is_native")
        for f in forwards:
            if f in body:
                ok("  forwarding to %s" % f)
            else:
                bad("  does not forward to %s" % f)
        for banned in ("INSERT", "UPDATE", "DELETE"):
            if banned in body:
                bad("  writes %s of its own" % banned)
            else:
                ok("  and no %s of its own" % banned)
        # The two write routes take no name from the caller - they pass
        # `issued_by=who`, which is _remote_authorise's answer - while the read
        # hands each queued row's own `issued_by` back, so the key is quoted
        # there and must be.
        if name == "list_clients":
            continue
        if "issued_by'" in body or 'issued_by"' in body:
            bad("  takes an issued_by from the caller")
        else:
            ok("  and takes no name from the caller")


def check_the_command_controls_are_shaped_right():
    """The Server GUI's side of it, and what it deliberately is not.

    The controls live in the Connected Clients window and nowhere else,
    because that list is built from check-ins: a Client that has never checked
    in has no row to select, so a button it would never obey cannot be offered.
    There is no endpoint - the Admin at this console is the only actor, the
    same call #8, #9 and #10 made.

    So what is asserted about the URL map is two things, and they are not the
    same thing. This used to be one line - "check-in is the only thing under
    /clients" - which read the invariant off the shape the tree happened to
    have when it was written, and 011's documented POST /clients/log then
    failed it while cascade-audit.py's routes-vs-table check passed the very
    same route. One gate said the route was properly recorded and the other
    said it may not exist. What ADR-0005 and the API table actually defend is
    that the registry is never *published*: it is a map of hostnames, Windows
    account names and addresses of machines on the internal network, and the
    Server GUI reads the table rather than serving it. A write-only POST
    publishes nothing, so the wording was wide and not the rule.

    Narrowed, then, to the two halves it was standing in for:

    1. **No route under /clients may be reachable without a credential**,
       beyond the two ADR-0002 and ADR-0005 argued for one at a time. That is
       the line, and #174 is what made it necessary to say it that way rather
       than as "no GET": `GET /clients` exists now, and what keeps ADR-0005's
       property is that it is **never open** - the admin password or the
       Server Settings capability and nothing else. The natural shape for a
       command queue is still a Client polling a GET for its own commands, and
       that is still the endpoint that was not built: the check-in carries them
       back in the answer to the POST, and `GET /clients` is the **Admin's**
       read of the whole registry rather than a Client's read of its own row.
    2. **The routes under /clients are an allow-list of the documented six**,
       and each is pinned to the method and the door it was argued for. A
       seventh fails here and has to be argued for - in the API table, in this
       list, and out loud - rather than being waved through by an ignore list,
       which is how the next addition would go in silently.

       The sixth is `POST /clients/clear` (#203), and this is where it was
       argued for: it is the Admin's **delete** of rows from that same
       registry, behind the same credential as the read and the two commands,
       and it is on the wire for the reason those three are - the registry is
       already acted on from the Notifier's Remote Admin panel, so an Admin who
       may log a machine off from there and must walk to the server to tidy up
       after a machine that no longer exists is being sent by the shape of the
       API rather than by the size of the act. What makes it safe to add is
       that it takes an **age** and never a `client_id`: there is no shape of
       this route that removes one row somebody pointed at, which is
       `POST /clients/push_cert`'s argument in reverse.

    Spelled as an allow-list because the risk a new route under this prefix
    carries is not only that it reads: an unauthenticated write is what those
    two ADRs weighed one endpoint at a time, and the read added at #174 is
    exactly the kind of thing that must not arrive without the argument being
    made again. The methods are pinned as the allow-list one level down - a
    PUT bolted onto an existing rule adds no path for (2) to notice.
    """
    head("the command controls")
    rules = [(str(r.rule), sorted(r.methods - {"HEAD", "OPTIONS"}))
             for r in M.app.url_map.iter_rules()]
    under = [(rule, m) for rule, m in rules
             if rule == "/clients" or rule.startswith("/clients/")]
    eq("the routes under /clients are the documented six, nothing else",
       sorted((rule, m) for rule, m in under),
       [("/clients", ["GET"]),
        ("/clients/checkin", ["POST"]),
        ("/clients/clear", ["POST"]),
        ("/clients/command", ["POST"]),
        ("/clients/log", ["POST"]),
        ("/clients/push_cert", ["POST"])])
    c = M.app.test_client()
    for rule in ("/clients", "/clients/command", "/clients/push_cert",
                 "/clients/clear"):
        meth = c.get if rule == "/clients" else c.post
        r = meth(rule, base_url="https://localhost", json={})
        eq("%s is never open" % rule, r.status_code in (401, 403), True)
    eq("while the check-in still needs no credential at all",
       c.post("/clients/checkin",
              json={"client_id": "c-open"}).status_code, 200)

    tree = ast.parse(SRC_CLIENTS_ALL)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}
    for want in ("_queue_command", "_command_rows", "_command_status",
                 "client_list"):
        if want in fns:
            ok("%s() exists" % want)
        else:
            bad("%s() is missing" % want)
            return

    win = ast.unparse(fns["client_list"])
    for needle in ("_queue_command", "_command_rows", "_command_status",
                   "COMMAND_LABELS", "logoff", "reset_identity",
                   "_push_next_cert"):
        if needle in win:
            ok("the window uses %s" % needle)
        else:
            bad("the window does not use %s" % needle)
    # No field of its own since 096: the Clients section is a pane with no
    # entry to carry a door, so each action asks `_admin_again` itself.
    if ("show='" + chr(0x25cf) + "'") in win:
        bad("the window still carries a password field of its own")
    else:
        ok("and carries no password field - the action asks at the door")
    for state in ("queued", "collected", "expired"):
        if state in win:
            ok("it shows the %s state" % state)
        else:
            bad("it does not show the %s state" % state)

    # The helper is the enforcement point for the *rules*, and since #174 the
    # door is the caller's: the console asks `_admin_password_ok` itself and
    # `POST /clients/command` asks `_remote_authorise`, because a password
    # checked in here could only know about one of the two.
    q = ast.unparse(fns["_queue_command"])
    for banned in ("_admin_password_ok", "_remote_authorise", "_authorise"):
        if banned in q:
            bad("_queue_command reaches for %s - the door is the caller's"
                % banned)
        else:
            ok("_queue_command does not check a credential itself (#174)")
    if "server_gui._admin_again(" in win:
        ok("and the console window asks for the password itself, through "
           "the door every open of it asks (096)")
    else:
        bad("the console window does not ask for the admin password")
    if "INSERT INTO client_commands" in q:
        ok("and it is the one thing that inserts a command")
    else:
        bad("_queue_command does not insert the command")
    inserters = [n for n, f in fns.items()
                 if n != "_queue_command"
                 and "INSERT INTO client_commands" in ast.unparse(f)]
    eq("nothing else writes to the queue", inserters, [])
