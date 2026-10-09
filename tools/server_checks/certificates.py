r"""The certificate lifecycle: staged, collected, cut over (ADR-0020).

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
from datetime import datetime

from server_checks.stage import (CERT_SRC, GUI_SRC, IIS_SRC, M, R, SRC, SRC_ALL,
                                 STAGE, _admin, bad, checkin, clients, commands,
                                 eq, fresh_db, head, log_rows, ok, seen, skip)




def check_a_client_reports_the_certificate_it_holds():
    """The fingerprint on a check-in, and what the registry does with it.

    The question this column exists to answer is who would break if the
    certificate were replaced today: every client pins `ssl_cert.pem` and
    fails closed against anything else (rule 1), so a replacement strands each
    installation holding the outgoing one until somebody at that machine
    confirms the new fingerprint (ADR-0010). Nothing else on a check-in says
    which of them that is - `version` answers what build a Client is on, which
    is a different question.

    It is stored as the **claim** it is, with the source address the server saw
    beside it (ADR-0005): only that installation can say what it holds, and the
    server measuring its own file instead would answer the question with
    itself.
    """
    head("a Client reporting its certificate")
    db = fresh_db()
    fp = ":".join("%02X" % ((i * 7) % 256) for i in range(32))

    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01",
                 "app": "Notifier", "version": "2.3.0",
                 "member": "Brian Dawson", "cert_fingerprint": fp},
                address="192.0.2.42")
    eq("the check-in is accepted", r.status_code, 200)
    row = clients(db)[0]
    eq("the registry records the fingerprint exactly as it was sent",
       row["cert_fingerprint"], fp)
    eq("  which is 95 characters, inside the cap", len(fp), 95)
    eq("and the address the server saw is still recorded beside it",
       row["address"], "192.0.2.42")

    # The claim is not checked against anything: the server's own certificate
    # is a different file and may not exist at all. What is asserted here is
    # that nothing rewrote or dropped the value on the way in.
    other = ":".join("%02X" % ((i * 11) % 256) for i in range(32))
    checkin({"client_id": "c-abc", "hostname": "HOST-LT-01", "app": "Notifier",
             "version": "2.3.0", "member": "Brian Dawson",
             "cert_fingerprint": other}, address="192.0.2.42")
    rows = clients(db)
    eq("a Client that re-pins is still one installation", len(rows), 1)
    eq("  now holding the other certificate", rows[0]["cert_fingerprint"],
       other)

    # The contract every field on this endpoint keeps, and the one that matters
    # most here: a Client that stops sending it clears the column. A stale
    # fingerprint left behind would read as current, and this is the column an
    # Admin is about to decide a certificate replacement on.
    checkin({"client_id": "c-abc", "hostname": "HOST-LT-01", "app": "Notifier",
             "version": "2.3.0", "member": "Brian Dawson"},
            address="192.0.2.42")
    eq("a check-in that omits it clears the column rather than keeping it",
       clients(db)[0]["cert_fingerprint"], "")

    # Unauthenticated, so a caller on the network chooses the length.
    r = checkin({"client_id": "c-abc", "cert_fingerprint": "F" * 400})
    eq("an over-long fingerprint is accepted", r.status_code, 200)
    eq("  and stored capped like every other field here",
       len(clients(db)[0]["cert_fingerprint"]), M._CHECKIN_MAX)

    # A Client built before this sends nothing and is answered exactly as it
    # was, which is what "additive" means on this endpoint.
    db = fresh_db()
    r = checkin({"client_id": "c-old", "hostname": "HOST-LT-09",
                 "app": "Storekeeper", "version": "2.2.0"})
    eq("a Client that has never heard of this checks in as it did",
       r.status_code, 200)
    body = r.get_json()
    eq("  and is answered with the same keys",
       all(k in body for k in ("status", "client_id", "known_since",
                               "last_seen", "member", "member_id",
                               "commands")), True)
    eq("  with an empty fingerprint, which is the honest answer",
       clients(db)[0]["cert_fingerprint"], "")

    # The Engineer is resolved by position in _CHECKIN_FIELDS rather than from
    # the end of it, which is what adding a field after `member` would have
    # broken silently - the row would have been filed under the fingerprint.
    db = fresh_db()
    checkin({"client_id": "c-nm", "app": "Notifier", "version": "2.3.0",
             "member": "brian dawson", "cert_fingerprint": fp})
    row = clients(db)[0]
    eq("the Engineer is still resolved to the row's own spelling",
       row["member"], "Brian Dawson")
    eq("  with the fingerprint in its own column", row["cert_fingerprint"], fp)


def check_migration_013_adds_the_column_both_ways():
    """A fresh database and an upgraded one end up identical, and down() keeps.

    The answer 006 gives about a column: a downgrade never drops one. The
    insert in `_record_checkin` names its columns, so an older build ignores
    it; dropping it would throw away which certificate every machine that is
    not in front of the Admin is holding - and a downgrade is routinely what
    happens when a certificate change has gone wrong, which is the one moment
    that column is the thing being read.
    """
    head("migration 013")
    path = os.path.join(R, "migrations", "013_client_cert.py")
    if not os.path.exists(path):
        bad("migrations/013_client_cert.py is missing")
        return
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    for want in ("up", "down"):
        if want in names:
            ok("013 defines %s()" % want)
        else:
            bad("013 does not define %s()" % want)
    down = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "down"][0]
    body = [st for st in down.body if not isinstance(st, ast.Expr)]
    if body and all(isinstance(st, ast.Return) and st.value is None
                    for st in body):
        ok("013's down() is a no-op")
    else:
        bad("013's down() does something - a downgrade keeps the column")
    up = src.upper()
    if "DROP COLUMN" in up or "DROP TABLE" in up:
        bad("013 drops something")
    else:
        ok("013 drops nothing")

    # It applies for real against the table as 004 left it, twice, then down,
    # with a row in it that has to survive all three.
    db = fresh_db()
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE clients")
    conn.execute("""CREATE TABLE clients (
        client_id  TEXT PRIMARY KEY, hostname TEXT DEFAULT '',
        os_user TEXT DEFAULT '', app TEXT DEFAULT '',
        version TEXT DEFAULT '', member TEXT DEFAULT '',
        address TEXT DEFAULT '', first_seen TEXT DEFAULT '',
        last_seen TEXT DEFAULT '')""")
    conn.execute("INSERT INTO clients (client_id, hostname, last_seen)"
                 " VALUES ('c-1','HOST-LT-01',?)",
                 (datetime.now().isoformat(),))
    conn.commit()
    mod = {}
    exec(compile(src, path, "exec"), mod)
    mod["up"](conn)
    mod["up"](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    eq("up() adds the column", "cert_fingerprint" in cols, True)
    eq("  reading '' for a row that was already there",
       conn.execute("SELECT cert_fingerprint FROM clients").fetchone()[0], "")
    conn.execute("UPDATE clients SET cert_fingerprint='AA:BB'")
    conn.commit()
    mod["down"](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    rows = conn.execute("SELECT hostname, cert_fingerprint FROM clients"
                        ).fetchall()
    conn.close()
    eq("down() keeps the column", "cert_fingerprint" in cols, True)
    eq("  and every row on it, with what it was holding",
       [tuple(r) for r in rows], [("HOST-LT-01", "AA:BB")])

    # And init_db() does it the other way, which is the half that runs on a
    # machine nobody ran migrate on.
    old = os.path.join(STAGE, "pre_client_cert.db")
    if os.path.exists(old):
        os.remove(old)
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE clients (
        client_id  TEXT PRIMARY KEY, hostname TEXT DEFAULT '',
        os_user TEXT DEFAULT '', app TEXT DEFAULT '',
        version TEXT DEFAULT '', member TEXT DEFAULT '',
        address TEXT DEFAULT '', first_seen TEXT DEFAULT '',
        last_seen TEXT DEFAULT '')""")
    conn.execute("INSERT INTO clients (client_id, hostname, last_seen)"
                 " VALUES ('c-2','HOST-LT-02',?)",
                 (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    M.DB_PATH = old
    M.init_db()
    M.init_db()          # twice: the ALTER has to be idempotent
    conn = sqlite3.connect(old)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    n = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    conn.close()
    eq("init_db() adds it to a table that predates it",
       "cert_fingerprint" in cols, True)
    eq("  keeping the installation already recorded", n, 1)


def check_connected_clients_says_who_holds_the_served_certificate():
    """The window shows the fingerprint per row and judges it against ours.

    A source check: `client_list` is a Tk callback reached from the console and
    every row in it comes out of a database this harness would have to stand a
    whole fleet up in. What is asserted is the shape - that the column exists,
    that the verdict is decided against `_cert_fingerprint()` rather than
    against a literal or a second read of `ssl_enabled`, and that the full
    value is somewhere other than the 100px cell.

    It asserted a fourth thing until 085 - that the window still wrote down
    the 900x640 the ticket decided to keep - and that went with the window.
    `client_list` is the Clients section's pane and states no size at all; the
    column widths it was the reason for are unchanged and are what the first
    two assertions are still about.
    """
    head("Connected Clients and the certificate column")
    # client_list is the Server GUI's own, in server_gui.py since #207 and
    # the Clients section's pane rather than a window since 085.
    tree = ast.parse(GUI_SRC)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "client_list"]
    if not fn:
        bad("client_list is gone")
        return
    fn = fn[0]
    body = ast.get_source_segment(GUI_SRC, fn)

    eq("the list carries a Certificate column",
       '"cert": "Certificate"' in body, True)

    calls = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            calls.add(n.func.id)
    eq("the verdict is read off the certificate this server serves",
       "_cert_fingerprint" in calls, True)
    if "ssl_enabled" in body:
        bad("it reads ssl_enabled - the file is what a Client pinned, and "
            "that flag reads identically on a first switch-on and on a swap")
    else:
        ok("and never off ssl_enabled, which answers a different question")

    inner = set(n.name for n in ast.walk(fn)
                if isinstance(n, ast.FunctionDef))
    eq("the cell is decided in one place", "cert_cell" in inner, True)
    eq("  and the whole value is shown somewhere the cell is too narrow for",
       "show_cert" in inner, True)

    # The Storekeeper and the Notifier both send it, which is what makes the
    # column answer for the fleet rather than for the Notifiers alone. Source,
    # because the call is on a tick that needs a server.
    common = io.open(os.path.join(R, "common.py"), encoding="utf-8").read()
    ctree = ast.parse(common)
    ck = [n for n in ast.walk(ctree)
          if isinstance(n, ast.FunctionDef) and n.name == "checkin"]
    seg = ast.get_source_segment(common, ck[0]) if ck else ""
    eq("common.checkin sends the fingerprint on every check-in",
       "cert_fingerprint" in seg and "own_cert_fingerprint" in seg, True)
    eq("  read off the file it pins, through the one function that "
       "fingerprints a certificate here",
       "cert_fingerprint(f.read())" in common, True)



def check_a_new_certificate_is_staged_and_nothing_is_bound():
    """Phase one of a rotation changes nothing that is being served (C1).

    The whole safety property of ADR-0020 is an absence: the live pair is
    untouched, so every client that pinned `ssl_cert.pem` goes on working
    while a new certificate sits beside it. An absence is what a source read
    cannot show - `_stage_new_cert` could name the right constants and still
    write over them through a default argument - so the live files are written
    here, their bytes taken, and compared afterwards.

    The three details on the certificate itself are asserted because each one
    fails **silently**: a missing IPAddress SAN is a client configured by
    address that cannot verify, a missing DNSName SAN is the same for a client
    configured by name, and a missing `CA:TRUE` is OpenSSL 3 refusing the file
    as a trust anchor. None of them is visible until a cutover has already
    stranded somebody.
    """
    head("a staged certificate, bound to nothing")
    import socket
    try:
        from cryptography import x509
    except ImportError:
        skip("cryptography is not installed - a certificate cannot be "
             "generated or read back here")
        return

    # Put back afterwards: the group that measures every window opens Server
    # Settings with no certificate beside the server, which is a different
    # branch of that form.
    _had = {}
    for p in (M.SSL_CERT_PATH, M.SSL_KEY_PATH):
        _had[p] = io.open(p, "rb").read() if os.path.exists(p) else None

    # A live pair that is nothing of the sort: what is asserted about it is
    # that it comes back byte for byte, and any bytes do that.
    live_cert = b"-----BEGIN CERTIFICATE-----\nnot a real one\n"
    live_key = b"-----BEGIN RSA PRIVATE KEY-----\nnor this\n"
    with io.open(M.SSL_CERT_PATH, "wb") as f:
        f.write(live_cert)
    with io.open(M.SSL_KEY_PATH, "wb") as f:
        f.write(live_key)
    for p in (M.SSL_CERT_NEXT_PATH, M.SSL_KEY_NEXT_PATH):
        if os.path.exists(p):
            os.remove(p)

    fp = M._stage_new_cert()
    eq("the staged pair is written",
       (os.path.exists(M.SSL_CERT_NEXT_PATH),
        os.path.exists(M.SSL_KEY_NEXT_PATH)), (True, True))
    eq("the live certificate is untouched",
       io.open(M.SSL_CERT_PATH, "rb").read(), live_cert)
    eq("the live key is untouched",
       io.open(M.SSL_KEY_PATH, "rb").read(), live_key)
    eq("what it answers is the staged certificate's own fingerprint",
       fp, M._cert_fingerprint(M.SSL_CERT_NEXT_PATH))
    if fp and fp != M._cert_fingerprint(M.SSL_CERT_PATH):
        ok("and it is not the live one: %s" % fp)
    else:
        bad("the staged fingerprint is the live one, or unreadable: %r" % fp)

    # GET /cert is the other half of "nothing is served": a client refreshing
    # its copy during phase one must be handed the certificate it already has.
    served = M.app.test_client().get("/cert")
    eq("GET /cert still serves the live certificate",
       served.data, live_cert)
    # send_file hands back an open handle, and this group puts the live pair
    # back afterwards: on Windows an unclosed response is a file that cannot
    # be replaced.
    served.close()

    cert = x509.load_pem_x509_certificate(
        io.open(M.SSL_CERT_NEXT_PATH, "rb").read())
    basic = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    eq("it is a CA, which OpenSSL 3 requires of a trust anchor",
       basic.value.ca, True)
    sans = cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value
    eq("it carries a DNSName SAN for this machine",
       socket.gethostname() in sans.get_values_for_type(x509.DNSName), True)
    eq("  and localhost beside it",
       "localhost" in sans.get_values_for_type(x509.DNSName), True)
    # An address SAN only where this machine has one to write down: an absent
    # IPAddress SAN costs a client configured by address, a wrong one costs
    # every client there is, so _cert_names writes none rather than a guess.
    addrs = [n for n in M._cert_names() if n not in
             (socket.gethostname(), socket.getfqdn(), "localhost")]
    eq("it carries an IPAddress SAN for each address _cert_names found",
       len(sans.get_values_for_type(x509.IPAddress)), len(addrs))
    if not addrs:
        ok("  (this machine reported no address, so none was written)")

    # The key is a key, and it is the key that goes with that certificate -
    # a staged pair that does not match is a cutover that fails at the bind.
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(
        io.open(M.SSL_KEY_NEXT_PATH, "rb").read(), password=None)
    eq("the staged key is the one that certificate was signed for",
       key.public_key().public_bytes(
           serialization.Encoding.PEM,
           serialization.PublicFormat.SubjectPublicKeyInfo)
       == cert.public_key().public_bytes(
           serialization.Encoding.PEM,
           serialization.PublicFormat.SubjectPublicKeyInfo), True)

    # Generating twice replaces the staged pair rather than adding beside it,
    # and answers the fingerprint that is staged afterwards: a staged
    # certificate nobody can name is one nobody can compare a client's
    # reported fingerprint against.
    again = M._stage_new_cert()
    if again and again != fp:
        ok("generating again replaces the staged pair: %s" % again)
    else:
        bad("generating again did not replace the staged pair: %r" % again)
    eq("  and the live certificate is still untouched",
       io.open(M.SSL_CERT_PATH, "rb").read(), live_cert)

    # The two names are a few characters apart from the two that strand a
    # fleet, so the refusal is the assertion and not the naming of a default.
    for kw in ({"cert_path": M.SSL_CERT_PATH}, {"key_path": M.SSL_KEY_PATH}):
        try:
            M._stage_new_cert(**kw)
            bad("it wrote over the live pair when asked to: %r" % kw)
        except ValueError as ex:
            ok("it refuses to write the live pair (%s): %s"
               % (list(kw)[0], ex))

    for p, had in _had.items():
        if had is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            with io.open(p, "wb") as f:
                f.write(had)


def check_the_staged_certificate_is_written_by_one_function():
    """Nothing else writes those two names, and no backup carries the key.

    Both are absences. The first is the property the window rests on - a
    second writer is a staged certificate that changed under an Admin who was
    comparing it against what a client reported - and the second is
    ADR-0019's rule one certificate earlier: a key nothing has bound yet is
    still a key, and a backup is carried to another machine by definition.
    """
    head("who writes the staged pair")
    # Three modules: the routes are in server.py, the window in
    # server_gui.py since #207, the four names that write and consume the
    # pair in server_cert.py since #206. What the list is about is how many
    # functions anywhere name them.
    trees = [ast.parse(SRC), ast.parse(GUI_SRC), ast.parse(CERT_SRC)]
    writers = set()
    # Top-level functions only, and every node inside one: `ast.walk` over the
    # whole tree answers with each *enclosing* function as well, so a name
    # written inside a Tk callback would be reported three times under three
    # names - the trap this file has hit before.
    for tree in trees:
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub_node in ast.walk(node):
                # A plain Name in server.py or server_cert.py, or S.<name> in
                # server_gui.py (#207) - both name the same two paths, just
                # through the bind() seam rather than the module's own scope.
                if (isinstance(sub_node, ast.Name)
                        and sub_node.id in ("SSL_CERT_NEXT_PATH",
                                            "SSL_KEY_NEXT_PATH")):
                    writers.add(node.name)
                elif (isinstance(sub_node, ast.Attribute)
                        and sub_node.attr in ("SSL_CERT_NEXT_PATH",
                                              "SSL_KEY_NEXT_PATH")
                        and isinstance(sub_node.value, ast.Name)
                        and sub_node.value.id == "S"):
                    writers.add(node.name)
    # `server_settings` reads them, to show the staged fingerprint beside the
    # live one and to ask before replacing a staged pair; `_stage_new_cert` is
    # the one that writes. A third name here is what this is for.
    # C3 adds three readers and no writer, which is the half worth saying:
    # `serve_cert_next` sends the certificate, `client_list` decides whether
    # there is anything to push, and `_push_next_cert` reads its fingerprint.
    # None of them touches SSL_KEY_NEXT_PATH, which is asserted on its own
    # below - a key served from anywhere is rule 1 gone, and it is the one
    # name here that must stay in a single function.
    # C4 adds one, and it is the second writer - deliberately, this being the
    # function that consumes the staged pair: `_cut_over_cert` replaces the
    # live files with them and leaves neither behind. It is the one name that
    # may join `_stage_new_cert` below for that reason, and the group that
    # covers it asserts the order and the aside those two writes go through.
    # #174 adds one reader and no writer, and it is `client_list` own
    # question asked from somewhere else: `list_clients` answers the staged
    # fingerprint beside the served one, so a remote panel knows whether there
    # is anything to push. It names SSL_CERT_NEXT_PATH and never
    # SSL_KEY_NEXT_PATH, which the assertion below holds it to along with
    # everything else here - a key reachable from a route is rule 1 gone, and
    # this is the first name on this list that is reached from one.
    # #206 adds `bind`, which is the one name here that is neither reader
    # nor writer of the files: it is server_cert.py taking the two paths
    # from server.py, where they are still resolved. A name assigned the
    # path is what this counts, so it is listed rather than filtered out -
    # a second binder would be a second answer to where the staged pair is.
    eq("only these functions name the staged paths at all",
       sorted(writers), ["_cut_over_cert", "_push_next_cert",
                         "_stage_new_cert", "bind", "client_list",
                         "list_clients",
                         "serve_cert_next", "server_settings"])
    keyed = set()
    for tree in trees:
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub_node in ast.walk(node):
                if (isinstance(sub_node, ast.Name)
                        and sub_node.id == "SSL_KEY_NEXT_PATH"):
                    keyed.add(node.name)
    # The staged key is named by the two functions either side of its life -
    # the one that writes it and the one that consumes it - and by nothing
    # else. No route, no push, no backup: a key served from anywhere is rule 1
    # gone, and `serve_cert_next` and `_push_next_cert` are both absent here on
    # purpose.
    eq("and the staged key is named by the two ends of its life, and by "
       "the bind that hands its path over, and by nothing else",
       sorted(keyed), ["_cut_over_cert", "_stage_new_cert", "bind"])

    eq("the staged key is named in a backup's excluded list",
       "ssl_key_next.pem" in M.BACKUP_EXCLUDED, True)
    eq("  and no backup carries either staged file",
       [n for n, _p in M._backup_members()
        if "next" in n], [])


def check_the_staged_certificate_is_served_on_its_own_route():
    """GET /cert/next, and what it deliberately is not (C3, ADR-0020).

    404 is the ordinary state - most of the time nothing is staged - so it is
    asserted first and with its code, a client that reads it as a failure
    being a client that logs an error every time a rotation is not happening.

    The two routes are then asserted against each other on one staged pair,
    which is the whole point of the split: `/cert` goes on answering with what
    is being served while `/cert/next` answers with what is not. A single
    endpoint taking a flag would put that distinction inside a caller's
    argument, and the caller that must not get it wrong is ADR-0010's
    first-contact bootstrap, which pins what it is handed.
    """
    head("the staged certificate is served on its own route")
    fresh_db()
    c = M.app.test_client()

    _had = {}
    for p in (M.SSL_CERT_PATH, M.SSL_CERT_NEXT_PATH):
        _had[p] = io.open(p, "rb").read() if os.path.exists(p) else None
        if os.path.exists(p):
            os.remove(p)

    r = c.get("/cert/next")
    eq("with nothing staged it is a 404", r.status_code, 404)
    eq("  with a code", (r.get_json() or {}).get("code"), "no_staged_cert")

    live = b"-----BEGIN CERTIFICATE-----\nthe one being served\n" \
           b"-----END CERTIFICATE-----\n"
    nxt = b"-----BEGIN CERTIFICATE-----\nthe one bound to nothing\n" \
          b"-----END CERTIFICATE-----\n"
    with io.open(M.SSL_CERT_PATH, "wb") as f:
        f.write(live)
    with io.open(M.SSL_CERT_NEXT_PATH, "wb") as f:
        f.write(nxt)

    r = c.get("/cert/next")
    eq("with one staged it is served", r.status_code, 200)
    eq("  and it is the staged file", r.data, nxt)
    r.close()          # send_file keeps the handle, and Windows keeps the lock
    r = c.get("/cert")
    eq("/cert still answers with what is being served", r.data, live)
    r.close()

    # The key is the file that must never travel (rule 1), and a route that
    # serves the certificate beside it is the obvious place for that to go
    # wrong. Source, because what is claimed is an absence: no view anywhere
    # in this file hands either key path to `send_file`.
    keyless = True
    for node in ast.walk(ast.parse(SRC_ALL)):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "send_file"):
            continue
        named = ast.unparse(node)
        if "KEY" in named.upper():
            bad("a route serves a key: %s" % named)
            keyless = False
    if keyless:
        ok("no route serves a private key")

    for p, was in _had.items():
        if was is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            with io.open(p, "wb") as f:
                f.write(was)


def check_the_staged_certificate_is_pushed_to_every_client():
    """The console's side of phase two (C3, ADR-0020).

    Four things, and the third is the one worth the group.

    A push with **nothing staged** is refused rather than queued: a queue of
    commands that each answer "nothing staged" is a fleet of `collected` rows
    meaning nothing happened, which is the untruth the whole two-phase shape
    exists to avoid.

    **The credential is the caller's since #174**, as it is in
    `_queue_command` below it and for its reason: this is reached from the
    console and from `POST /clients/push_cert`, so what it takes is the actor
    every row it queues and every `cert.pushed` it writes is attributed to.
    What it still refuses on its own is a push with nothing staged, and it
    refuses that **first** - a queue of commands that each answer "nothing
    staged" is a fleet of collected rows meaning nothing happened.

    It queues for **every** Client rather than for the ones that are behind,
    and that is deliberate and would read as a bug: a Client reports the
    fingerprint of the *first* certificate in its pinned file, appending
    leaves the served one first, so the Certificate column cannot see the
    append and a count off it would be a fleet status that is the opposite of
    one. So what is asserted is one row per installation, and that the
    **queue** is what says who has answered.

    And a re-push is refused per Client while the first is still waiting and
    allowed once it has been collected, which is `_queue_command`'s own
    duplicate guard rather than a second rule here - a second rotation needs
    the second push, and it is safe because the append is idempotent.
    """
    head("the staged certificate is pushed to every Client")
    db = fresh_db()
    _admin()
    seen("c-abc", host="HOST-LT-01")
    seen("c-xyz", host="HOST-LT-02", app="Storekeeper")

    _had = {}
    for p in (M.SSL_CERT_NEXT_PATH, M.SSL_KEY_NEXT_PATH):
        _had[p] = io.open(p, "rb").read() if os.path.exists(p) else None
        if os.path.exists(p):
            os.remove(p)

    payload, status = M._push_next_cert()
    eq("with nothing staged the push is refused", status, 409)
    eq("  with a code", payload.get("code"), "no_staged_cert")
    eq("and nothing was queued", len(commands(db)), 0)

    # A real certificate rather than any bytes: what is asserted below is the
    # fingerprint that reaches the System Log, and _cert_fingerprint answers
    # None for base64 that will not decode.
    try:
        from cryptography import x509
    except ImportError:
        skip("cryptography is not installed - nothing can be staged here")
        return
    fp = M._stage_new_cert()

    payload, status = M._push_next_cert(issued_by="Admin (Server GUI)")
    eq("the push is accepted", status, 200)
    eq("  one command per installation", payload.get("queued"), 2)
    eq("  and it names the certificate it was about",
       payload.get("fingerprint"), fp)
    rows = commands(db)
    eq("both rows are trust_cert", sorted(r["command"] for r in rows),
       ["trust_cert", "trust_cert"])
    eq("  for the two Clients", sorted(r["client_id"] for r in rows),
       ["c-abc", "c-xyz"])
    eq("  and the queue is what says nobody has answered yet",
       sorted(M._command_status(r) for r in rows), ["queued", "queued"])

    # The fingerprint is what this entry adds over client.command_issued: a
    # command name alone cannot say months later which certificate it was
    # about.
    pushed = [r for r in log_rows(db) if r["event"] == "cert.pushed"]
    eq("one cert.pushed per Client", len(pushed), 2)
    eq("  each naming the fingerprint",
       sorted(set(fp in r["detail"] for r in pushed)), [True])
    eq("  attributed to the console",
       sorted(set(r["actor"] for r in pushed)), ["Admin (Server GUI)"])

    payload, status = M._push_next_cert()
    eq("a second push while both are waiting queues none", status, 200)
    eq("  and says so", payload.get("queued"), 0)
    eq("  naming them as already waiting", payload.get("already_waiting"), 2)
    eq("and no row was stacked", len(commands(db)), 2)

    # Collected is what a check-in does, in the same transaction that hands
    # the command over - so this is the real path rather than an UPDATE here.
    r = checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    eq("the Client collects it", [c["command"] for c in
                                  r.get_json().get("commands")],
       ["trust_cert"])
    payload, status = M._push_next_cert()
    eq("a push after it was collected queues that one again",
       payload.get("queued"), 1)
    eq("  and still not the one still waiting",
       payload.get("already_waiting"), 1)

    for p, was in _had.items():
        if was is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            with io.open(p, "wb") as f:
                f.write(was)


def check_the_push_goes_through_the_one_writer():
    """Source: `_push_next_cert` writes no row of its own.

    An absence, so there is no request that demonstrates it. `_queue_command`
    is the one writer of the queue, the way `_save_asset` is the one writer of
    an asset - a push that INSERTed for itself would be a second door to the
    same table with its own idea of the duplicate guard, and the Admin would
    find out by reading the rows months later. **Neither takes a password
    since #174**, so it is also asserted that this one has not grown one back:
    a helper that checks a credential can only know about one of its two
    callers, and the one it knows about is whichever existed first.
    """
    head("the push goes through the one writer")
    tree = ast.parse(CERT_SRC)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}
    if "_push_next_cert" not in fns:
        bad("_push_next_cert() is missing")
        return
    body = ast.unparse(fns["_push_next_cert"])
    for needle in ("_queue_command", "_cert_fingerprint",
                   "SSL_CERT_NEXT_PATH", "_client_rows", "cert.pushed"):
        if needle in body:
            ok("the push uses %s" % needle)
        else:
            bad("the push does not use %s" % needle)
    for banned in ("INSERT", "get_db", "UPDATE", "_admin_password_ok",
                   "_remote_authorise", "_authorise"):
        if banned in body:
            bad("the push reaches for %s of its own" % banned)
        else:
            ok("and no %s of its own" % banned)


def check_who_has_not_collected_the_staged_certificate():
    """`_clients_behind_staged` reads the queue, not the Certificate column.

    This is the number an Admin decides a cutover on, and the whole of C3's
    argument turned around: a Client reports the fingerprint of the **first**
    certificate in its pinned file, and appending leaves the served one first,
    so a Client that has done exactly what it was told still reports the old
    certificate. A count off that column would say the fleet is behind on the
    morning every machine has caught up - the reading that would talk somebody
    out of a cutover that was safe, and into one that was not.

    So the states are driven one at a time: never pushed to, pushed and still
    waiting, collected, and collected-but-reporting-the-old-fingerprint, which
    is the normal state after a push and the one a column-derived count gets
    exactly wrong.
    """
    head("who has not collected the staged certificate")
    db = fresh_db()
    _admin()

    behind, total = M._clients_behind_staged()
    eq("with no Clients at all it is nought of nought", (behind, total),
       (0, 0))

    seen("c-abc", host="HOST-LT-01")
    seen("c-xyz", host="HOST-LT-02", app="Storekeeper")
    behind, total = M._clients_behind_staged()
    eq("a Client never pushed to is behind", (behind, total), (2, 2))

    M._queue_command("c-abc", "trust_cert")
    behind, _ = M._clients_behind_staged()
    eq("and one still waiting is still behind", behind, 2)

    checkin({"client_id": "c-abc", "hostname": "HOST-LT-01"})
    behind, total = M._clients_behind_staged()
    eq("one that collected it is not", (behind, total), (1, 2))

    # The state the whole group exists for: this Client has appended the
    # staged certificate and goes on reporting the served one, because that is
    # the first block in its file. Read off the column it is behind; read off
    # the queue it is not, and the queue is right.
    checkin({"client_id": "c-abc", "hostname": "HOST-LT-01",
             "cert_fingerprint": "AA:BB"})
    rows = {r["client_id"]: r for r in M._client_rows()}
    eq("it still reports the served certificate",
       rows["c-abc"]["cert_fingerprint"], "AA:BB")
    behind, _ = M._clients_behind_staged()
    eq("and is still not counted as behind", behind, 1)

    M._queue_command("c-xyz", "trust_cert")
    checkin({"client_id": "c-xyz", "hostname": "HOST-LT-02"})
    behind, total = M._clients_behind_staged()
    eq("a fleet that has all collected it is nought of two",
       (behind, total), (0, 2))


def check_the_cutover_replaces_the_live_pair():
    """`_cut_over_cert`: the four refusals, and what one write leaves behind.

    Every refusal is checked against the **files** rather than against the
    status alone, because the failure this function can have is not answering
    wrongly but moving something while it says no - and the thing it would
    move is the certificate every installation on this network verifies
    against (rule 1). A wrong admin password in particular has to be the
    cheapest possible answer: nothing copied aside, nothing replaced.

    The refusals are three different situations and are three different codes.
    `already_bound` is the least obvious and the one worth the most: a second
    cutover would put the **live** pair into the `cert_rollback` directory over the copy
    that is the way back from the first one, so the way back would be a copy
    of what is already being served, which is no way back at all.

    Then the write, and what is asserted is the aside directory rather than
    only the outcome: one generation, holding the pair that was live a moment
    ago and not the one that is live now.
    """
    head("the cutover replaces the live pair")
    db = fresh_db()
    _admin()
    try:
        from cryptography import x509  # noqa: F401
    except ImportError:
        skip("cryptography is not installed - nothing can be staged here")
        return

    _had = {}
    for p in (M.SSL_CERT_PATH, M.SSL_KEY_PATH,
              M.SSL_CERT_NEXT_PATH, M.SSL_KEY_NEXT_PATH):
        _had[p] = io.open(p, "rb").read() if os.path.exists(p) else None
        if os.path.exists(p):
            os.remove(p)
    if os.path.isdir(M.CERT_ROLLBACK_DIR):
        shutil.rmtree(M.CERT_ROLLBACK_DIR)

    try:
        payload, status = M._cut_over_cert(password="admin")
        eq("with nothing staged it is refused", status, 409)
        eq("  with a code", payload.get("code"), "no_staged_cert")

        fp_next = M._stage_new_cert()
        os.remove(M.SSL_KEY_NEXT_PATH)
        payload, status = M._cut_over_cert(password="admin")
        eq("a staged certificate with no key is refused", status, 409)
        eq("  with a code of its own", payload.get("code"), "no_staged_key")
        ok("  and they are different codes, being different things to fix")
        os.remove(M.SSL_CERT_NEXT_PATH)

        # The live pair, made the same way the staged one is - so that what is
        # asserted below is two real certificates with two real fingerprints
        # rather than two strings.
        fp_live = M._stage_new_cert()
        os.replace(M.SSL_CERT_NEXT_PATH, M.SSL_CERT_PATH)
        os.replace(M.SSL_KEY_NEXT_PATH, M.SSL_KEY_PATH)
        fp_next = M._stage_new_cert()

        was_cert = io.open(M.SSL_CERT_PATH, "rb").read()
        was_key = io.open(M.SSL_KEY_PATH, "rb").read()
        was_next = io.open(M.SSL_CERT_NEXT_PATH, "rb").read()

        payload, status = M._cut_over_cert(password="nope")
        eq("a wrong admin password is refused", status, 401)
        eq("  with a code", payload.get("code"), "bad_password")
        eq("  the served certificate is untouched",
           io.open(M.SSL_CERT_PATH, "rb").read(), was_cert)
        eq("  the staged one is still staged",
           io.open(M.SSL_CERT_NEXT_PATH, "rb").read(), was_next)
        eq("  and nothing was copied aside",
           os.path.isdir(M.CERT_ROLLBACK_DIR), False)
        eq("  and nothing was written down about it",
           [r for r in log_rows(db) if r["event"] == "cert.cutover"], [])

        seen("c-abc", host="HOST-LT-01")
        seen("c-xyz", host="HOST-LT-02", app="Storekeeper")
        # Put off rather than assumed off: three groups elsewhere in this
        # suite leave server_config.json saying ssl_enabled true, and which
        # of them shares a shard with this one moves whenever a group is
        # added anywhere above it (#280 added two and this read True).
        M._save_server_cfg(ssl_enabled=False)
        eq("ssl_enabled starts off",
           M._load_server_cfg().get("ssl_enabled", False), False)
        payload, status = M._cut_over_cert(password="admin",
                                           issued_by="Admin (Server GUI)")
        eq("the cutover is accepted", status, 200)
        # #266: off IIS this is the door ssl_enabled is turned on through -
        # otherwise a standalone server that was on plain HTTP stays there
        # after Generate and Cut Over, `_run_flask` never building a TLS
        # context without the flag.
        eq("  and it turns HTTPS on for a standalone server",
           M._load_server_cfg().get("ssl_enabled"), True)
        eq("  naming what was being served", payload.get("from"), fp_live)
        eq("  and what is now", payload.get("to"), fp_next)
        eq("  with the count it was decided on",
           (payload.get("behind"), payload.get("clients")), (2, 2))
        eq("the staged certificate is now the served one",
           M._cert_fingerprint(M.SSL_CERT_PATH), fp_next)
        eq("  and nothing is staged any more",
           os.path.exists(M.SSL_CERT_NEXT_PATH), False)
        eq("  nor is the staged key left behind",
           os.path.exists(M.SSL_KEY_NEXT_PATH), False)

        aside = sorted(os.listdir(M.CERT_ROLLBACK_DIR))
        eq("the pair that was live is beside the server", aside,
           ["ssl_cert.pem", "ssl_key.pem"])
        eq("  and it is the pair that was live, byte for byte",
           io.open(os.path.join(M.CERT_ROLLBACK_DIR, "ssl_cert.pem"),
                   "rb").read(), was_cert)
        eq("  the key with it",
           io.open(os.path.join(M.CERT_ROLLBACK_DIR, "ssl_key.pem"),
                   "rb").read(), was_key)

        cut = [r for r in log_rows(db) if r["event"] == "cert.cutover"]
        eq("one cert.cutover entry", len(cut), 1)
        eq("  at warn", cut[0]["level"], "warn")
        eq("  attributed to the console", cut[0]["actor"],
           "Admin (Server GUI)")
        eq("  naming the outgoing fingerprint", fp_live in cut[0]["detail"],
           True)
        eq("  and the incoming one", fp_next in cut[0]["detail"], True)
        eq("  and how many machines it was about to strand",
           "2 of 2" in cut[0]["detail"], True)

        # `data` (#246/071): the same four facts, structured, and the
        # phrase reads with the values templated in rather than the bare
        # "made the staged certificate the live one".
        log_data = json.loads(cut[0]["data"])
        eq("  and data carries the same four facts",
           log_data, {"from": fp_live, "to": fp_next, "behind": 2,
                      "total": 2})
        eq("  which the meaning column reads into the phrase",
           M._log_cell(cut[0], "meaning"),
           "made the staged certificate the live one - from %s to %s, 2 of "
           "2 installation(s) had not collected it" % (fp_live, fp_next))

        # A second run with the same pair staged again: the staged certificate
        # is a different one, so this is the ordinary second rotation and has
        # to keep exactly one generation - the pair that was live a moment
        # ago, which is the one that has just been replaced.
        fp_third = M._stage_new_cert()
        payload, status = M._cut_over_cert(password="admin")
        eq("a second cutover is accepted", status, 200)
        eq("  from the certificate the first one installed",
           payload.get("from"), fp_next)
        eq("  and the aside directory still holds one generation",
           sorted(os.listdir(M.CERT_ROLLBACK_DIR)),
           ["ssl_cert.pem", "ssl_key.pem"])
        eq("  which is the pair that was live a moment ago",
           M._cert_fingerprint(os.path.join(M.CERT_ROLLBACK_DIR,
                                            "ssl_cert.pem")), fp_next)
        eq("  and the served one is the third",
           M._cert_fingerprint(M.SSL_CERT_PATH), fp_third)

        # What the payload says about the host in front, which the window
        # reads to decide whether to spawn the elevated rebind at all. The
        # pool is read back out of the record rather than compared against the
        # spelling the code uses: `pool` was what it asked iis.json for, and
        # that key does not exist - install-iis.ps1 writes `app_pool` and
        # nothing writes the other - so this field was "" on every install
        # since it was added, and a check written against the spelling would
        # have agreed with the bug.
        #
        # `M.server_cert` and not this package's own handle: `_iis_host` is a
        # module global of server_cert.py, put there by bind(), and that is
        # the copy `_cut_over_cert` reads - the same reason stage.py keeps IM
        # for server_iis.py.
        CM = M.server_cert
        record = {"site": "AssetManager", "app_pool": "AssetManagerPool"}
        fp_fourth = M._stage_new_cert()
        # #266: TLS ends at the site under IIS, so this flag is not this
        # process's to turn on there. False here so a cutover that touched it
        # anyway would show up rather than agreeing with the earlier True.
        M._save_server_cfg(ssl_enabled=False)
        _was_iis = CM._iis_host
        CM._iis_host = lambda: dict(record)
        try:
            payload, status = M._cut_over_cert(password="admin")
        finally:
            CM._iis_host = _was_iis
        eq("a cutover under IIS is accepted", status, 200)
        eq("  and says the binding is somebody else's to move",
           payload.get("iis"), True)
        eq("  leaving ssl_enabled to IIS rather than turning it on itself",
           M._load_server_cfg().get("ssl_enabled"), False)
        eq("  naming the site iis.json records",
           payload.get("site"), record["site"])
        eq("  and the app pool it records",
           payload.get("pool"), record["app_pool"])
        eq("  onto the certificate that was staged",
           M._cert_fingerprint(M.SSL_CERT_PATH), fp_fourth)

        # Staging a copy of what is already served is the state `already_bound`
        # is for. Reached by staging and cutting over twice would be a rotation;
        # reached by copying the live certificate into the staged name is the
        # Admin who has lost track of which is which.
        shutil.copy2(M.SSL_CERT_PATH, M.SSL_CERT_NEXT_PATH)
        shutil.copy2(M.SSL_KEY_PATH, M.SSL_KEY_NEXT_PATH)
        before = io.open(os.path.join(M.CERT_ROLLBACK_DIR, "ssl_cert.pem"),
                         "rb").read()
        payload, status = M._cut_over_cert(password="admin")
        eq("cutting over to what is already served is refused", status, 409)
        eq("  with a code", payload.get("code"), "already_bound")
        eq("  and the way back from the last cutover is still there",
           io.open(os.path.join(M.CERT_ROLLBACK_DIR, "ssl_cert.pem"),
                   "rb").read(), before)
    finally:
        if os.path.isdir(M.CERT_ROLLBACK_DIR):
            shutil.rmtree(M.CERT_ROLLBACK_DIR)
        for p, was in _had.items():
            if was is None:
                if os.path.exists(p):
                    os.remove(p)
            else:
                with io.open(p, "wb") as f:
                    f.write(was)


def check_installing_a_certificate_under_iis_moves_the_binding():
    """Source: Install takes the cutover's elevated half, and Remove refuses.

    Install is the cutover one step earlier - the same two files replaced -
    and it was the one of the pair that restarted instead of binding. Under
    IIS `sc query` finds the service stopped, because it is disabled there
    (ADR-0001), so the fall-through `os.execv`'d the GUI process: a monitor
    window restarting while the site went on presenting the certificate it was
    bound to, under a popup naming the new one. Remove was worse and the other
    way round - it deleted the files a site serving https has no way to stop
    needing, which is the outage ADR-0020 exists to prevent reached through
    the one button that sounds like the way out of it.

    Source rather than behaviour, for `client_list`'s reason two groups up:
    these are Tk callbacks off a dialog, and what is asserted is the shape.
    Every assertion here is an **ordering** rather than a presence, because
    presence is what both of these already had: `do_remove` named `os.remove`
    before this ticket too, and what makes it a refusal is that the IIS
    question is asked in front of it.
    """
    head("install and remove under IIS")
    tree = ast.parse(GUI_SRC)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}
    for name in ("do_install", "do_remove", "_restart_server"):
        if name not in fns:
            bad("%s() is gone" % name)
            return

    def code(fn):
        """The function without its docstring, for `_clients_behind_staged`'s
        reason below: what is asserted here is an order, and a docstring
        saying which branch no longer reaches `os.execv` is a sentence about
        the rule rather than the code keeping it - and it is read first.
        """
        return "".join(ast.unparse(n) for n in fn.body
                       if not (isinstance(n, ast.Expr)
                               and isinstance(n.value, ast.Constant)
                               and isinstance(n.value.value, str)))

    install = code(fns["do_install"])
    for needle in ("_iis_host", "_bind_cert_command", "_elevate"):
        if needle in install:
            ok("install reaches %s" % needle)
        else:
            bad("install does not reach %s" % needle)
    if "_restart_server" not in install:
        bad("install no longer restarts off IIS either")
    else:
        eq("  and asks about IIS before it restarts anything",
           install.index("_iis_host") < install.index("_restart_server"), True)

    remove = code(fns["do_remove"])
    for needle in ("_iis_host", "install-iis.ps1"):
        if needle in remove:
            ok("remove reaches %s" % needle)
        else:
            bad("remove does not reach %s" % needle)
    for later in ("os.remove", "askyesno"):
        if later not in remove:
            bad("remove no longer reaches %s off IIS either" % later)
        else:
            eq("  and refuses under IIS before %s" % later,
               remove.index("_iis_host") < remove.index(later), True)

    restart = code(fns["_restart_server"])
    for needle in ("_iis_host", "_recycle_pool_command"):
        if needle in restart:
            ok("the restart reaches %s" % needle)
        else:
            bad("the restart does not reach %s" % needle)
    if "os.execv" not in restart:
        bad("the restart no longer execv's off IIS either")
    else:
        eq("  and never gets to os.execv under IIS",
           restart.index("_iis_host") < restart.index("os.execv"), True)

    # The command itself is server_iis.py's, beside the two elevated commands
    # already there, and it is None rather than a line naming an empty pool
    # where iis.json records none - the caller owes an Admin "recycle it
    # yourself" rather than something to paste that cannot work.
    itree = ast.parse(IIS_SRC)
    ifns = {n.name: n for n in ast.walk(itree)
            if isinstance(n, ast.FunctionDef)}
    if "_recycle_pool_command" not in ifns:
        bad("_recycle_pool_command() is missing from server_iis.py")
        return
    pool = code(ifns["_recycle_pool_command"])
    for needle in ("Restart-WebAppPool", "app_pool", "powershell"):
        if needle in pool:
            ok("the elevated command names %s" % needle)
        else:
            bad("the elevated command does not name %s" % needle)
    eq("  and is None where iis.json records no pool",
       "return None" in pool, True)

    # /health's ssl: the port under IIS, the flag and the files otherwise.
    # Both halves, since a key that answered one of them everywhere is how it
    # came to say false over a site serving TLS.
    hfn = [n for n in ast.walk(ast.parse(SRC))
           if isinstance(n, ast.FunctionDef) and n.name == "health"]
    if not hfn:
        bad("health() is gone")
        return
    body = code(hfn[0])
    eq("/health asks what is in front of the port under IIS",
       "_iis_tls_bound" in body, True)
    eq("  and the flag with the files where nothing is in front",
       "ssl_enabled" in body, True)

    # And the script the install spawns cycles the pool, so the rebind and a
    # process re-reading its files are one act rather than two.
    ps = io.open(os.path.join(R, "tools", "bind-cert.ps1"),
                 encoding="utf-8").read()
    if "Restart-WebAppPool" not in ps:
        bad("bind-cert.ps1 does not recycle the pool")
    else:
        eq("bind-cert.ps1 recycles the pool after it has rebound",
           ps.index("Set-SiteCertificate") < ps.index("Restart-WebAppPool"),
           True)
        eq("  and reads the name out of iis.json rather than asking for it",
           "app_pool" in ps, True)


def check_the_cutover_moves_no_binding_of_its_own():
    """Source: the cutover writes files, and the binding is somebody else's.

    An absence, so no request demonstrates it. Under IIS this process is the
    app pool identity and cannot bind anything, so a `_cut_over_cert` that
    reached for `IIS:` or spawned a rebind of its own would fail in a way that
    looks like the cutover failed - when the files really have been replaced,
    and telling an Admin otherwise is how a half cutover gets left half done.

    `_bind_cert_command` is asserted beside it because the point of that
    function is that there is **one** spelling of the elevated command: what
    is printed when the elevation is refused has to be what would have run, or
    somebody pastes a line that does nothing and reports that it did not work.
    """
    head("the cutover moves no binding of its own")
    # _bind_cert_command is server_iis.py's since #243 - CERT_SRC alone no
    # longer carries it, so this reads the two files' text together, the
    # way GUI_SRC and SRC join elsewhere in this package.
    tree = ast.parse(CERT_SRC + "\n" + IIS_SRC)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}
    for name in ("_cut_over_cert", "_clients_behind_staged",
                 "_bind_cert_command"):
        if name not in fns:
            bad("%s() is missing" % name)
            return

    body = ast.unparse(fns["_cut_over_cert"])
    for needle in ("_cert_fingerprint", "_admin_password_ok",
                   "_clients_behind_staged", "CERT_ROLLBACK_DIR",
                   "cert.cutover", "SSL_CERT_NEXT_PATH", "SSL_KEY_NEXT_PATH"):
        if needle in body:
            ok("the cutover uses %s" % needle)
        else:
            bad("the cutover does not use %s" % needle)
    for banned in ("IIS:", "Popen", "ShellExecute", "system(", "New-WebBinding",
                   "SslBindings"):
        if banned in body:
            bad("the cutover reaches for %s in process" % banned)
        else:
            ok("and no %s in process" % banned)

    # The count comes off the queue. Asserted as source as well as by
    # behaviour above, since what is claimed is that the column is not read at
    # all - a function that read both and preferred one would pass the
    # behaviour group on the day the two agree.
    # Read without its docstring, which says in prose that the column is not
    # what this counts - a scan over the whole function would be answered by
    # the sentence explaining the rule rather than by the code keeping it.
    _counted = fns["_clients_behind_staged"]
    counted = "".join(ast.unparse(n) for n in _counted.body
                      if not (isinstance(n, ast.Expr)
                              and isinstance(n.value, ast.Constant)
                              and isinstance(n.value.value, str)))
    for needle in ("_command_rows", "_command_status", "trust_cert",
                   "collected"):
        if needle in counted:
            ok("the count reads %s" % needle)
        else:
            bad("the count does not read %s" % needle)
    if "cert_fingerprint" in counted:
        bad("the count reads the Certificate column, which cannot see an "
            "append")
    else:
        ok("and never cert_fingerprint")

    cmd = ast.unparse(fns["_bind_cert_command"])
    for needle in ("bind-cert.ps1", "-InstallDir", "powershell"):
        if needle in cmd:
            ok("the elevated command names %s" % needle)
        else:
            bad("the elevated command does not name %s" % needle)
    callers = sorted(
        n.name for n in tree.body if isinstance(n, ast.FunctionDef)
        for sub in ast.walk(n)
        if isinstance(sub, ast.Name) and sub.id == "_bind_cert_command")
    # One caller, and it is the one that answers: the window is handed the
    # command in the payload rather than building its own, which is what makes
    # the line printed on a refused elevation the line that would have run.
    eq("and there is one caller of it", callers, ["_cut_over_cert"])


def check_the_live_certificate_is_watched_for_expiry():
    """The daily background check (#273): none, a warn, then an error.

    A certificate 40 days out is nobody's problem yet; one 20 days out is
    `CERT_WARN_DAYS` (30) inside the band and gets a `cert.expiry_warning`;
    one 3 days out is inside `CERT_ERROR_DAYS` (7) too and gets a
    `cert.expiry_critical` in place of the warning rather than beside it.
    It only warns - nothing here stages or cuts anything over.

    The live pair, made the same way `check_a_new_certificate_is_staged_and`
    `_nothing_is_bound` makes one: `_stage_new_cert` refuses to write over
    the live files directly (it is the one thing it never does), so a
    certificate is staged with the days this check wants and moved onto the
    live pair the way a real cutover would leave it.
    """
    head("the live certificate's expiry, watched daily")
    try:
        from cryptography import x509  # noqa: F401
    except ImportError:
        skip("cryptography is not installed - nothing can be minted here")
        return

    _had = {}
    for p in (M.SSL_CERT_PATH, M.SSL_KEY_PATH,
              M.SSL_CERT_NEXT_PATH, M.SSL_KEY_NEXT_PATH):
        _had[p] = io.open(p, "rb").read() if os.path.exists(p) else None

    def cert_days(days):
        M._stage_new_cert(days=days)
        os.replace(M.SSL_CERT_NEXT_PATH, M.SSL_CERT_PATH)
        os.replace(M.SSL_KEY_NEXT_PATH, M.SSL_KEY_PATH)

    try:
        db = fresh_db()
        cert_days(40)
        M._cert_expiry_check()
        rows = [r["event"] for r in log_rows(db) if r["event"].startswith("cert.expiry")]
        eq("40 days out writes nothing", rows, [])

        db = fresh_db()
        cert_days(20)
        M._cert_expiry_check()
        rows = [r for r in log_rows(db) if r["event"].startswith("cert.expiry")]
        eq("20 days out writes one warning", [r["event"] for r in rows],
           ["cert.expiry_warning"])
        eq("  at warn", rows[0]["level"], "warn")

        db = fresh_db()
        cert_days(3)
        M._cert_expiry_check()
        rows = [r for r in log_rows(db) if r["event"].startswith("cert.expiry")]
        eq("3 days out writes one critical entry instead of the warning",
           [r["event"] for r in rows], ["cert.expiry_critical"])
        eq("  at error", rows[0]["level"], "error")
    finally:
        for p, data in _had.items():
            if data is None:
                if os.path.exists(p):
                    os.remove(p)
            else:
                with io.open(p, "wb") as f:
                    f.write(data)

    # Wired into the daily job beside _log_retention_loop and _sync_loop,
    # the way system_log.py's own group holds _log_trim to _log_retention_loop.
    src = ast.unparse(ast.parse(SRC))
    eq("started from _start_background_jobs",
       "_cert_expiry_loop" in src, True)


def check_the_server_settings_panel_shows_the_expiry():
    """`Expires <date> (<n> days)`, beside the fingerprint (#273).

    Source rather than behaviour, `client_list`'s reason above: this is a Tk
    label built inside a dialog function, and what is asserted is that the
    panel reads the same thresholds the background job does rather than a
    second pair of numbers, and colours by them.
    """
    head("the Server Settings panel showing the certificate's expiry")
    tree = ast.parse(GUI_SRC)
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "server_settings"]
    if not fns:
        bad("server_settings() is missing from gui_settings.py")
        return
    body = ast.get_source_segment(GUI_SRC, fns[0])
    for needle in ("_cert_expiry", "CERT_WARN_DAYS", "CERT_ERROR_DAYS",
                  "Expires %s"):
        if needle in body:
            ok("the panel reads %s" % needle)
        else:
            bad("the panel does not read %s" % needle)
