r"""Mail, and which events are mailed.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import os
import sqlite3
import threading
import time

from server_checks.stage import console_door
from server_checks.stage import (M, SRC_MAIL_ALL, SRC_MAIL_LOG_ALL,
                                 _blank_lookup, _caps, _stub_lookup, bad, eq,
                                 fresh_db, head, ok, read_server_cfg,
                                 write_server_cfg)



class _StubSMTP(object):
    """Stands in for smtplib.SMTP. Raises, times out or succeeds to order.

    A stub rather than a real server on a port, for the reason this whole file
    drives Flask's test client rather than a socket: there is nothing to pick,
    nothing to fail to stop, and the three answers that matter - a host that is
    not there, one that never replies, one that takes the mail - are three
    values of a class attribute rather than three machines.
    """

    mode = "ok"
    sent = []
    logins = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        if _StubSMTP.mode == "refuse":
            raise OSError("[Errno 10061] the mail server refused the connection")
        if _StubSMTP.mode == "slow":
            raise TimeoutError("timed out")
        if _StubSMTP.mode == "nohost":
            # What a name that does not resolve raises, errno and all. It is
            # the one failure whose own words name nothing: no host, no port,
            # and no sign that the relay was never reached at all.
            raise M.socket.gaierror(11001, "getaddrinfo failed")

    def starttls(self):
        self.tls = True

    def ehlo(self):
        pass

    def login(self, user, password):
        _StubSMTP.logins.append((user, password))
        if _StubSMTP.mode == "badpw":
            raise Exception("(535, b'5.7.8 Authentication credentials invalid')")

    def send_message(self, msg):
        _StubSMTP.sent.append({"to": msg["To"], "from": msg["From"],
                               "subject": msg["Subject"],
                               "body": msg.get_content()})

    def quit(self):
        pass


def check_a_send_can_never_break_what_triggered_it():
    """_send_mail carries _log_event's contract: it never raises (030).

    The failure this guards against is the one the whole system exists to
    prevent. A mail server that is down, full or slow sits behind an event that
    happened - a Transaction recorded, a proposal waiting - and if a send can
    raise out of that path, the movement is refused because a notification
    could not be delivered. So the three answers a mail server can give are
    driven here against a stub, and beside each of them a Transaction is
    recorded, confirmed and rejected exactly as it is with no mail at all.
    """
    head("a failed send never breaks what triggered it (030)")
    db = fresh_db()
    _blank_lookup()
    real, M.smtplib.SMTP = M.smtplib.SMTP, _StubSMTP
    _StubSMTP.sent, _StubSMTP.logins, _StubSMTP.mode = [], [], "ok"
    try:
        write_server_cfg({"host": "0.0.0.0", "port": 8081})
        eq("with nothing configured, a send is refused in words and starts"
           " nothing", (M._smtp_send_now("a@b.c", "s", "b"),
                        M._send_mail("a@b.c", "s", "b")),
           ("No mail server is configured.", False))

        M._save_server_cfg(smtp_host="relay.local", smtp_port=25,
                           smtp_from="assets@example.com", smtp_starttls=False,
                           smtp_username="svc-assets")
        eq("a send that works says nothing, which is the empty string",
           M._smtp_send_now("admin@example.com", "Subject", "Body"), "")
        eq("  and the message carries what it was given",
           [(m["to"], m["from"], m["subject"]) for m in _StubSMTP.sent],
           [("admin@example.com", "assets@example.com", "Subject")])

        for mode, want in (("refuse", "refused the connection"),
                           ("slow", "timed out"),
                           ("badpw", "Authentication credentials invalid"),
                           ("nohost", '"relay.local" could not be found')):
            _StubSMTP.mode = mode
            got = M._smtp_send_now("admin@example.com", "S", "B")
            # The mail server's own words. "Failed" is the one answer nobody
            # can act on: a wrong password, a refused sender and a host that is
            # not there each need a different thing done about them.
            eq("a %s answers with what the mail server said" % mode,
               want in got, True)
            eq("  and raises nothing", isinstance(got, str), True)

            eq("  a worker is started and nothing comes back out of it",
               M._send_mail("admin@example.com", "S", "B"), True)
            eq("  and the answer names the relay it is about", "relay.local"
               in got, True)
            payload, status = M._create_transaction(
                {"asset_number": "A-%s" % mode, "team_member": "Brian Dawson",
                 "direction": "Out Store"})
            eq("  and a Transaction is still recorded while mail is %s" % mode,
               (status, payload.get("status")), (201, "created"))
            tid = payload.get("id")
            c = M.app.test_client()
            eq("  still confirmed", c.post("/confirm/%d" % tid).status_code, 200)
            payload2, _st = M._create_transaction(
                {"asset_number": "B-%s" % mode, "team_member": "Brian Dawson",
                 "direction": "Out Store"})
            eq("  still rejected",
               c.post("/reject/%d" % payload2["id"],
                      json={"reason": "not mine"}).status_code, 200)

        # The worker's own answer is a log line, which is the only place
        # anybody will look for it. Given time to land: it is a thread, and the
        # whole point of it is that the caller did not wait.
        #
        # Waited on the **thread** rather than on a clock, which is the whole
        # of what #204 is about one level up: this polled the table for two
        # and a half seconds, which was enough until this file started running
        # eight shards at once, and then reported a mail subsystem that had
        # written nothing when what it had was no CPU. More patience only
        # moves where that happens. So the worker is waited for by counting
        # threads down to what was running before the send, and the table is
        # read after it has gone - a bound on the wait rather than a guess at
        # how long the work takes, and the same answer however loaded the
        # machine is.
        #
        # The short poll under it stays: `_log_event` commits on the worker's
        # own connection, and a thread that has ended is not a write this
        # connection has necessarily seen yet.
        _StubSMTP.mode = "refuse"
        _threads = threading.active_count()
        M._send_mail("admin@example.com", "A subject", "A body")
        _gone = time.time() + 120
        while threading.active_count() > _threads and time.time() < _gone:
            time.sleep(0.02)
        if threading.active_count() > _threads:
            bad("the mail worker was still running after 120s - it is not "
                "slow, it is stuck, and nothing below measures that")
        conn = sqlite3.connect(M.DB_PATH)
        rows = []
        for _ in range(200):
            rows = conn.execute(
                "SELECT level, detail FROM system_log WHERE"
                " event='mail.send_failed' AND detail LIKE '%A subject%'"
            ).fetchall()
            if rows:
                break
            time.sleep(0.05)
        conn.close()
        eq("a failed send is one System Log entry at warn",
           (len(rows), rows and rows[0][0]), (1, "warn"))
        eq("  naming the recipient, the subject and what the server said",
           bool(rows) and all(x in rows[0][1] for x in
                              ("admin@example.com", "A subject",
                               "refused the connection")), True)
        eq("  and never the body of the mail",
           bool(rows) and "A body" in rows[0][1], False)
    finally:
        M.smtplib.SMTP = real
        _StubSMTP.mode = "ok"
    fresh_db()
    del db


def check_a_name_that_does_not_resolve_says_which_name():
    """"getaddrinfo failed" is the one mail failure that names nothing.

    The other three answers a relay gives carry their own subject - a refused
    connection, a timeout inside the conversation, a rejected credential are
    all the relay talking. A name that does not resolve is not: the relay was
    never reached, and what comes back is "[Errno 11001] getaddrinfo failed"
    with no host in it, no port, and nothing to say that a name lookup rather
    than the mail is what went wrong. So it reads as the mail server refusing
    the mail, which is exactly the "failed" answer nobody can act on that
    _smtp_send_now exists not to give.

    What is asserted is that the name is in the sentence and the system's own
    words are still behind it - the errno is what somebody searches for, and
    the name is what they compare against what they typed.
    """
    head("a mail server name that does not resolve is named (030)")
    real, M.smtplib.SMTP = M.smtplib.SMTP, _StubSMTP
    _StubSMTP.mode = "nohost"
    try:
        write_server_cfg({"host": "0.0.0.0", "port": 8081})
        M._save_server_cfg(smtp_host="relay.invalid", smtp_port=587,
                           smtp_from="assets@example.com", smtp_starttls=True,
                           smtp_username="")
        got = M._smtp_send_now("admin@example.com", "S", "B")
        eq("the name that could not be resolved is in the answer",
           '"relay.invalid"' in got, True)
        eq("  and the system's own words are still behind it",
           ("11001" in got, "getaddrinfo failed" in got), (True, True))

        # And the other failures now say which relay they are about, which is
        # the half a single-mode assertion would let drift back.
        _StubSMTP.mode = "slow"
        got = M._smtp_send_now("admin@example.com", "S", "B")
        eq("a failure inside the conversation names the relay and the port",
           ("relay.invalid:587" in got, "timed out" in got), (True, True))
    finally:
        M.smtplib.SMTP = real
        _StubSMTP.mode = "ok"


def check_the_mail_password_is_never_written_where_it_can_be_read():
    """The one replayable secret this system holds, and where it is not (030).

    ADR-0013: every other stored password is a one-way salted hash (ADR-0008)
    and this one has to be replayed at every send, so it is stored recoverably
    - which makes *where* it is not stored the thing worth asserting. Not in
    server_config.json, which three writers outside the server
    read-modify-write; not in the System Log, which has never held a password
    in any form; and not in the test mail, which is a message an Admin sends to
    themselves and might forward to anybody.
    """
    head("the mail password is never written where it can be read (030)")
    fresh_db()
    _blank_lookup()
    real, M.smtplib.SMTP = M.smtplib.SMTP, _StubSMTP
    _StubSMTP.sent, _StubSMTP.logins, _StubSMTP.mode = [], [], "ok"
    secret = "correct-horse-battery-staple"
    try:
        write_server_cfg({"host": "0.0.0.0", "port": 8081})
        M._save_server_cfg(smtp_host="relay.local", smtp_port=587,
                           smtp_from="assets@example.com", smtp_starttls=True,
                           smtp_username="svc-assets")
        eq("the settings round-trip through server_config.json",
           M._smtp_cfg(), {"host": "relay.local", "port": 587,
                           "from": "assets@example.com", "starttls": True,
                           "username": "svc-assets"})

        refusal = M._smtp_secret_set(secret)
        if not M.HAS_DPAPI:
            # A source install without pywin32 refuses, naming why, and never
            # falls back to plaintext (ADR-0013). Asserted rather than skipped:
            # the refusal is the behaviour.
            eq("with no DPAPI the password is refused, naming why",
               ("DPAPI" in refusal and "plaintext" in refusal), True)
            eq("  and nothing is written", M._smtp_secret_stored(), False)
        else:
            eq("with DPAPI the password is stored and reads back",
               (refusal, M._smtp_secret_stored(), M._smtp_secret_get()),
               ("", True, secret))
            eq("  in a file of its own, not in server_config.json",
               os.path.basename(M.SMTP_SECRET_PATH), "smtp_secret.dat")
            raw = io.open(M.SMTP_SECRET_PATH, "rb").read()
            eq("  encrypted rather than written down", secret.encode() in raw,
               False)

        cfg_text = io.open(M.SERVER_CFG_PATH, encoding="utf-8").read()
        eq("the password is not in server_config.json, in any form",
           secret in cfg_text, False)
        eq("  and neither is a key that would say where it is",
           [k for k in read_server_cfg() if "password" in k.lower()
            or "secret" in k.lower()], [])

        M._smtp_send_now("admin@example.com", "Asset Manager test mail",
                         "This is a test message from the Asset Server.")
        eq("the test mail does not carry the password",
           [m for m in _StubSMTP.sent if secret in str(m)], [])
        if M.HAS_DPAPI:
            eq("  it is replayed to the mail server and nowhere else",
               _StubSMTP.logins[-1:], [("svc-assets", secret)])

        conn = sqlite3.connect(M.DB_PATH)
        rows = conn.execute("SELECT detail, actor, event FROM"
                            " system_log").fetchall()
        conn.close()
        eq("and no System Log row anywhere holds it",
           [r for r in rows if secret in str(r)], [])

        eq("clearing it takes the file with it",
           (M._smtp_secret_set(""), M._smtp_secret_stored(),
            M._smtp_secret_get()), ("", False, ""))
    finally:
        M.smtplib.SMTP = real
        _StubSMTP.mode = "ok"
        try:
            os.remove(M.SMTP_SECRET_PATH)
        except OSError:
            pass
    del real

    # Source checks. The dialog is a Tk callback no request reaches, and what
    # matters about it is an absence: that no _log_event call in the mail code
    # is handed the password, and that the secret has one writer.
    tree = ast.parse(SRC_MAIL_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns.setdefault(node.name, node)

    def src_of(name):
        return "" if name not in fns else (
            ast.get_source_segment(SRC_MAIL_ALL, fns[name]) or "")

    for name in ("_smtp_secret_set", "_smtp_secret_get", "_smtp_send_now",
                 "_send_mail", "_send_mail_worker", "_smtp_cfg",
                 "mail_settings"):
        if name in fns:
            ok("%s is there" % name)
        else:
            bad("%s is missing" % name)
    # The DPAPI calls moved into `_secret_set`/`_secret_get` when 032 brought
    # the second replayable secret (ADR-0014). What is asserted is unchanged -
    # that this password reaches CryptProtectData and is never written down -
    # but the pair is now shared, so it is asserted in two hops rather than
    # one. A second hand-copied CryptProtectData is what the shared pair exists
    # to prevent, and this is the check that would have noticed it.
    if "CryptProtectData" in src_of("_secret_set"):
        ok("the password is encrypted with DPAPI rather than written down")
    else:
        bad("_secret_set does not reach CryptProtectData")
    if "_secret_set(" in src_of("_smtp_secret_set"):
        ok("  and the mail password goes through that one pair")
    else:
        bad("_smtp_secret_set does not go through _secret_set")
    writers = [n for n in fns
               if "CryptProtectData" in src_of(n) or "CryptUnprotectData"
               in src_of(n)]
    eq("nothing else in this file calls DPAPI directly",
       sorted(writers), ["_secret_get", "_secret_set"])
    touches = []

    class _V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, n):
            self.stack.append(n.name)
            self.generic_visit(n)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Name(self, n):
            if n.id == "SMTP_SECRET_PATH" and self.stack:
                touches.append(self.stack[-1])

    _V().visit(tree)
    # `bind` is where the path arrives, not a reader of the file: #224
    # moved these three into `server_mail.py` and `SMTP_SECRET_PATH` is
    # one of the eight names `server.py` hands over, so the assignment
    # inside that signature is a mention and not a touch. Subtracted by
    # name rather than widened into the wanted set, which would stop this
    # answering the question it asks.
    eq("three helpers reach the secret's file and nothing else does",
       set(touches) - {"bind"}, {"_smtp_secret_set", "_smtp_secret_get",
                                 "_smtp_secret_stored"})
    for name in ("_smtp_send_now", "_send_mail", "_send_mail_worker",
                 "mail_settings"):
        if "_save_server_cfg(smtp_password" in src_of(name) or (
                "smtp_password" in src_of(name)):
            bad("%s puts the password in server_config.json" % name)
    ok("no mail function writes the password into server_config.json")
    if "_smtp_secret_get(" in src_of("mail_settings"):
        bad("the dialog reads the stored password back")
    else:
        ok("the dialog never reads the stored password back - it is told only"
           " whether one is there")
    eq("every change here takes the admin password, at the entry's door "
       "on every open and not again in the window (096)",
       ("_admin_password_ok(" in src_of("mail_settings"),
        console_door("Mail Settings")), (False, "admin"))
    if "_authorise(" in src_of("mail_settings"):
        bad("mail_settings is delegable to a capability password")
    else:
        ok("and it is not a fifth capability (ADR-0006)")
    # The console itself since 077, Server Administration having been the
    # door until it was deleted: Mail Settings is an entry on the System
    # section, gated on the entry rather than on a menu in front of it.
    seg = src_of("run_gui")
    if "mail_settings(" in seg:
        ok("the console's System section is the door to it")
    else:
        bad("nothing reaches mail_settings()")


def check_the_mail_settings_are_reachable_over_the_delegated_channel():
    """Mail Settings and Notification Rules from somewhere else (#172).

    The console's two windows put on the network behind the **Server
    Settings** capability password, and what has to hold across that move is
    the property ADR-0013 is about: the SMTP password is the one replayable
    secret this server holds, so a channel that can *set* it must still be one
    that cannot *read* it. Four places it could leak to and does not - the
    answer to the GET, `server_config.json`, a System Log row, and a plain
    `http://` request, which is refused before the password is examined.

    Beside that, the three things the wire adds:

      - **An absent `smtp_password` keeps what is stored**, `""` clears it -
        `_save_member`'s convention, and the only one a form that is never
        shown the password can use.
      - **A rule written through the endpoint takes effect with no restart**,
        because `_notify_rules` reads the file on every entry. That is the
        whole reason this is worth having remotely: an Admin who has to reach
        the console to stop a flood will not reach it in the situation that
        made them want to.
      - **The recipients survive the round trip.** The GET answers `to` as a
        list, so a caller that fetched the rules and sent them back would have
        written `"['a@b']"` into the column if the writer took the line as
        typed and nothing else.

    The password legs follow `HAS_DPAPI` rather than being skipped without it:
    the machine that cannot encrypt one has to **refuse** it naming the reason,
    which is ADR-0013's rule and the half a skip would stop asserting.
    """
    head("the mail settings are reachable over the delegated channel (#172)")
    fresh_db()
    _blank_lookup()
    _caps(server_settings="setpw", manage_records="mrpw")
    real, M.smtplib.SMTP = M.smtplib.SMTP, _StubSMTP
    _StubSMTP.sent, _StubSMTP.logins, _StubSMTP.mode = [], [], "ok"
    secret = "relay-hunter2-hunter2"
    stored = bool(M.HAS_DPAPI)
    c = M.app.test_client()
    HTTPS = "https://localhost"
    try:
        write_server_cfg({"host": "0.0.0.0", "port": 8081})
        M._smtp_secret_set("")

        r = c.post("/admin/mail", base_url=HTTPS,
                   json={"password": "setpw", "host": "relay.local",
                         "port": 587, "from": "assets@example.com",
                         "username": "svc-assets", "starttls": True})
        eq("the capability password saves the settings", r.status_code, 200)
        eq("  and they land in server_config.json", M._smtp_cfg(),
           {"host": "relay.local", "port": 587, "from": "assets@example.com",
            "starttls": True, "username": "svc-assets"})

        r = c.post("/admin/mail", base_url=HTTPS,
                   json={"password": "setpw", "host": "relay.local",
                         "port": 587, "from": "assets@example.com",
                         "username": "svc-assets", "starttls": True,
                         "smtp_password": secret})
        if stored:
            eq("a password sent with them is stored",
               (r.status_code, M._smtp_secret_stored()), (200, True))
        else:
            eq("a machine with no DPAPI refuses the password rather than "
               "writing one in the clear (ADR-0013)",
               (r.status_code, r.get_json().get("code")),
               (400, "no_secret_store"))
            eq("  and says so in words", bool(r.get_json().get("error")), True)

        r = c.get("/admin/mail", base_url=HTTPS, json={"password": "setpw"})
        got = r.get_json()
        eq("the GET answers the settings", (got["host"], got["port"],
                                            got["from"], got["username"],
                                            got["starttls"]),
           ("relay.local", 587, "assets@example.com", "svc-assets", True))
        eq("  and whether a password is stored rather than the password",
           (got["password_stored"], secret in json.dumps(got)),
           (stored, False))
        eq("  with can_store beside it, so a form can say why a field is "
           "refused", got["can_store"], stored)

        cfg_text = io.open(M.SERVER_CFG_PATH, encoding="utf-8").read()
        eq("the secret is not in server_config.json, in any form",
           secret in cfg_text, False)

        # Absent keeps, "" clears - and the settings beside it still move, so
        # an ordinary correction to the host cannot wipe the credential.
        r = c.post("/admin/mail", base_url=HTTPS,
                   json={"password": "setpw", "host": "relay2.local",
                         "port": 25, "from": "assets@example.com",
                         "username": "svc-assets", "starttls": False})
        eq("a save with no smtp_password keeps what is stored",
           (r.status_code, M._smtp_secret_stored()), (200, stored))
        eq("  while everything beside it moves",
           (M._smtp_cfg()["host"], M._smtp_cfg()["starttls"]),
           ("relay2.local", False))

        r = c.post("/admin/mail", base_url=HTTPS,
                   json={"password": "setpw", "host": "relay2.local",
                         "port": 25, "from": "assets@example.com",
                         "smtp_password": ""})
        eq("an empty one clears it", M._smtp_secret_stored(), False)

        r = c.post("/admin/mail", base_url=HTTPS,
                   json={"password": "setpw", "host": "relay2.local",
                         "port": 99999, "from": "assets@example.com"})
        eq("a port outside the range is refused by the one writer",
           (r.status_code, r.get_json().get("code")), (400, "bad_port"))

        # The test send: the relay's own words, and a refusal that is the
        # relay's failure rather than this server's.
        _StubSMTP.mode = "ok"
        r = c.post("/admin/mail/test", base_url=HTTPS,
                   json={"password": "setpw", "to": "admin@example.com"})
        eq("a test send that works answers ok",
           (r.status_code, r.get_json().get("status")), (200, "ok"))
        r = c.post("/admin/mail/test", base_url=HTTPS,
                   json={"password": "setpw", "to": ""})
        eq("  with no recipient it is refused",
           (r.status_code, r.get_json().get("code")), (400, "no_recipient"))
        _StubSMTP.mode = "refuse"
        r = c.post("/admin/mail/test", base_url=HTTPS,
                   json={"password": "setpw", "to": "admin@example.com"})
        eq("a refused send is 200 carrying the relay's words - the request "
           "did what it was asked",
           (r.status_code, r.get_json().get("status")), (200, "failed"))
        eq("  and says something rather than 'failed'",
           bool(r.get_json().get("error")), True)
        _StubSMTP.mode = "ok"

        # -- the rules ----------------------------------------------------
        r = c.post("/admin/notify_rules", base_url=HTTPS,
                   json={"password": "setpw",
                         "rules": [{"event": "update.failed",
                                    "to": "it@example.com, team@example.com",
                                    "level": "error"},
                                   {"event": "", "to": "", "level": "info"}]})
        eq("the rules are written, the blank row dropped rather than refused",
           (r.status_code, r.get_json().get("rules")), (200, 1))
        eq("  and take effect with no restart, being read from the file on "
           "every entry",
           [(x["event"], x["to"], x["level"]) for x in M._notify_rules()],
           [("update.failed", ["it@example.com", "team@example.com"], "error")])

        # The round trip: what the GET answers, sent straight back.
        got = c.get("/admin/notify_rules", base_url=HTTPS,
                    json={"password": "setpw"}).get_json()
        eq("the GET states the two bounds",
           (got["min_secs"], got["hourly_max"]),
           (M._NOTIFY_MIN_SECS, M._NOTIFY_HOURLY_MAX))
        r = c.post("/admin/notify_rules", base_url=HTTPS,
                   json={"password": "setpw", "rules": got["rules"]})
        eq("and a list of recipients sent back is still a list of recipients",
           [x["to"] for x in M._notify_rules()],
           [["it@example.com", "team@example.com"]])

        r = c.post("/admin/notify_rules", base_url=HTTPS,
                   json={"password": "setpw",
                         "rules": [{"event": "update.failed", "to": "",
                                    "level": "info"}]})
        eq("a rule with an event and no recipient is refused, naming it",
           (r.status_code, r.get_json().get("code")), (400, "bad_rule"))
        r = c.post("/admin/notify_rules", base_url=HTTPS,
                   json={"password": "setpw",
                         "rules": [{"event": "update.failed",
                                    "to": "it@example.com",
                                    "level": "shouting"}]})
        eq("  and a level that is not one is refused too",
           (r.status_code, r.get_json().get("code")), (400, "bad_level"))
        eq("  with neither of them written", len(M._notify_rules()), 1)

        # The transport gate, which is R1's rather than this ticket's: refused
        # before the password is examined, and nothing written.
        before = M._smtp_cfg()
        r = c.post("/admin/mail", base_url="http://localhost",
                   json={"password": "setpw", "host": "evil.local",
                         "port": 25, "from": "assets@example.com"})
        eq("a capability password over plain http is refused insecure",
           (r.status_code, r.get_json().get("code")), (403, "insecure"))
        eq("  and nothing was written", M._smtp_cfg(), before)
        r = c.get("/admin/mail", base_url="http://localhost",
                  json={"password": "setpw"})
        eq("  the read is refused the same way", r.status_code, 403)

        # The admin password still opens all of it - a delegation that could
        # lock the Admin out is not a delegation.
        r = c.get("/admin/mail", base_url=HTTPS, json={"password": "admin"})
        eq("the admin password still opens the settings", r.status_code, 200)

        conn = sqlite3.connect(M.DB_PATH)
        rows = conn.execute("SELECT event, actor, detail FROM"
                            " system_log").fetchall()
        conn.close()
        eq("no System Log row holds the secret",
           [r for r in rows if secret in str(r)], [])
        eq("  and the delegated uses are on the record",
           len([r for r in rows if r[0] == "remote.action"]) > 0, True)
    finally:
        M.smtplib.SMTP = real
        _StubSMTP.mode = "ok"
        M._smtp_secret_set("")
    del real

    # Source checks: the console and the wire go through the same three
    # writers, which is what stops one of them growing a rule the other does
    # not have. Each console door is a Tk callback no request reaches.
    tree = ast.parse(SRC_MAIL_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns.setdefault(node.name, node)

    def src_of(name):
        return "" if name not in fns else (
            ast.get_source_segment(SRC_MAIL_ALL, fns[name]) or "")

    for name in ("_save_mail_settings", "_send_test_mail",
                 "_save_notify_rules", "_mail_door", "mail_settings",
                 "notification_rules", "get_mail_settings",
                 "set_mail_settings", "send_mail_test", "get_notify_rules",
                 "set_notify_rules"):
        if name in fns:
            ok("%s is there" % name)
        else:
            bad("%s is missing" % name)
    for writer, doors in (("_save_mail_settings",
                           ("mail_settings", "set_mail_settings")),
                          ("_send_test_mail",
                           ("mail_settings", "send_mail_test")),
                          ("_save_notify_rules",
                           ("notification_rules", "set_notify_rules"))):
        for door in doors:
            if writer + "(" in src_of(door):
                ok("%s goes through %s" % (door, writer))
            else:
                bad("%s does not go through %s" % (door, writer))
    for door in ("set_mail_settings", "set_notify_rules"):
        if "_save_server_cfg(" in src_of(door):
            bad("%s writes server_config.json behind the one writer" % door)
        else:
            ok("%s writes nothing behind the one writer" % door)
    if "_smtp_secret_get(" in src_of("get_mail_settings"):
        bad("GET /admin/mail reads the stored password back (ADR-0013)")
    else:
        ok("GET /admin/mail never reads the stored password back")
    for door in ("get_mail_settings", "set_mail_settings", "send_mail_test",
                 "get_notify_rules", "set_notify_rules"):
        if "_mail_door(" in src_of(door):
            ok("%s asks the one door" % door)
        else:
            bad("%s does not go through _mail_door" % door)
    if "_remote_authorise(" in src_of("_mail_door"):
        ok("and that door is strict on both credentials - these routes are "
           "new, so there is no install sending the admin password over "
           "plain http for it to break")
    else:
        bad("_mail_door does not go through _remote_authorise")


def _notify_reset():
    """Forget the two bounds' state between legs. Not a production door.

    They are per-process counters, which is what the whole point of them
    requires - a bound that reset on every log write is not a bound - so a
    check that wants a clean one says so here rather than each leg reaching
    into the dict.
    """
    M._notify_state.update({"hour": -1, "sent": 0, "last": {}, "held": {}})


def check_only_a_rule_decides_what_is_mailed():
    """A rule mails an event and the absence of one does not (031).

    The hook is a single call inside `_log_event`, after the row is written,
    and nowhere else. A call per interesting event would mean an event somebody
    forgot to wire mails nothing and *looks* configured - where a rule pointed
    at an event nobody emits mails nothing and is visible as exactly that.

    `_send_mail` is replaced with a recorder for these legs. What is being
    asserted is which rules matched, and the worker behind a real send is the
    subject of the group above.

    The recorder is hung on `M.server_mail` rather than on `M` since #224.
    `_notify_of` moved into that module and reads `_send_mail` out of its
    own globals, so a name replaced on the server module alone would be
    the copy `server.py` imported back and nothing would be intercepted -
    a real send attempt reported as a rule that did not match.
    """
    head("only a rule decides what is mailed (031)")
    fresh_db()
    _blank_lookup()
    posted = []
    real = M.server_mail._send_mail
    M.server_mail._send_mail = lambda to, subject, body: (posted.append(
        (tuple(to), subject, body)) or True)
    try:
        write_server_cfg({"host": "0.0.0.0", "port": 8081})
        _notify_reset()
        eq("with no rules at all, nothing is mailed and the row is still"
           " written", (M._log_event("transaction.created", "one"), posted),
           (True, []))

        M._save_server_cfg(notify_rules=[
            {"event": "transaction.created", "to": "store@example.com",
             "level": "info"},
            {"event": "auth.refused", "to": "sec@example.com, boss@example.com",
             "level": "warn"},
            # Two shapes a hand-edited file can hold. Ignored rather than
            # raised on: a rule that cannot be read must not be able to break a
            # log write, whose promise is above this one.
            {"event": "no-recipient", "to": "", "level": "info"},
            "not a rule at all"])
        eq("a rule with no recipient and a line that is not a rule are both"
           " dropped rather than raised on",
           [r["event"] for r in M._notify_rules()],
           ["transaction.created", "auth.refused"])

        _notify_reset()
        posted[:] = []
        M._log_event("transaction.created", "two", actor="Storekeeper User")
        eq("a subscribed event reaches the mailbox the rule names",
           [(p[0], p[1]) for p in posted],
           [(("store@example.com",), "[Asset Manager] transaction.created")])
        eq("  carrying what the row holds rather than a second telling of it",
           all(x in posted[0][2] for x in ("transaction.created",
                                           "Storekeeper User", "two")), True)

        posted[:] = []
        M._log_event("lookup.saved", "nobody subscribed to this")
        eq("an event nobody subscribed to mails nothing", posted, [])

        _notify_reset()
        posted[:] = []
        M._log_event("auth.refused", "an ordinary one", level="info")
        eq("an entry below the rule's level is left alone", posted, [])
        M._log_event("auth.refused", "the real one", level="warn")
        eq("  and one at it goes to every recipient the rule names",
           [p[0] for p in posted], [("sec@example.com", "boss@example.com")])

        # The loop this excludes: _send_mail's worker logs its own failure, and
        # a rule on that name would mail about the mail that could not be sent.
        M._save_server_cfg(notify_rules=[{"event": "mail.send_failed",
                                          "to": "b@example.com",
                                          "level": "info"}])
        _notify_reset()
        posted[:] = []
        M._log_event("mail.send_failed", "to x · y · refused", level="warn")
        eq("a rule on a mail.* event is never acted on, so a failed send"
           " cannot mail about itself", posted, [])

        # Read from the file on every entry, not from the import-time snapshot:
        # an Admin who has to restart the server to stop a flood will not reach
        # for the switch in the situation that made them want it.
        M._save_server_cfg(notify_rules=[{"event": "server.config_changed",
                                          "to": "boss@example.com",
                                          "level": "warn"}])
        _notify_reset()
        posted[:] = []
        M._log_event("server.config_changed", "port=9000", level="warn")
        eq("a rule written to the file takes effect with no restart",
           [p[0] for p in posted], [("boss@example.com",)])

        # The mail hook renders through event_sentence since #071 - one
        # renderer, three readers - so a converted event's mail carries the
        # same templated values the window's meaning column and the export
        # would show, not only the raw "Event: ..." name.
        _notify_reset()
        posted[:] = []
        M._save_server_cfg(host="192.0.2.5")
        eq("a converted event's mail carries its templated meaning",
           "saved a server setting - changed host" in posted[0][2], True)
    finally:
        M.server_mail._send_mail = real
    fresh_db()

    # Source check: the hook is one call, inside the one writer. Both
    # sources, since #227: `_notify_of` is `server_mail.py`'s and the one
    # call to it is in `_log_event`, which is `server_log.py`'s.
    tree = ast.parse(SRC_MAIL_LOG_ALL)
    calls = []

    class _V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, n):
            self.stack.append(n.name)
            self.generic_visit(n)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, n):
            if isinstance(n.func, ast.Name) and n.func.id == "_notify_of":
                calls.append(self.stack[-1] if self.stack else "<module>")
            self.generic_visit(n)

    _V().visit(tree)
    eq("one place decides a notification, and it is the one log writer",
       calls, ["_log_event"])


def check_the_notification_bounds_hold_and_say_so():
    """Two bounds, and nothing dropped in silence (031).

    Two for the reason the System Log's retention has two: `POST /clients/log`
    is unauthenticated (ADR-0002, ADR-0005), so anybody on the internal network
    writes entries as fast as they like and a rule on a client-shipped event is
    a mail amplifier pointed at the department. Either bound alone is walked
    around - one event a hundred times defeats the ceiling alone, a hundred
    events once each defeats the per-event limit alone - and what a stuck
    client actually does is the first of those.

    What was held back rides the next mail that event does send, because a
    reader told nothing cannot tell a quiet hour from a bound holding all of it
    back.
    """
    head("the notification bounds hold, and say what they held (031)")
    fresh_db()
    _blank_lookup()
    posted = []
    real = M.server_mail._send_mail
    M.server_mail._send_mail = lambda to, subject, body: (
        posted.append(body) or True)
    try:
        write_server_cfg({"host": "0.0.0.0", "port": 8081})
        M._save_server_cfg(notify_rules=[{"event": "transaction.created",
                                          "to": "store@example.com",
                                          "level": "info"}])
        _notify_reset()
        for i in range(6):
            M._log_event("transaction.created", "burst %d" % i)
        eq("a burst of six is one mail, not six",
           (len(posted), M._notify_state["held"].get("transaction.created")),
           (1, 5))
        eq("  and the first of them said nothing about a bound, there being"
           " nothing held yet",
           "not mailed" in posted[0], False)

        # The cooldown expiring, without waiting a minute for it.
        M._notify_state["last"]["transaction.created"] = 0
        posted[:] = []
        M._log_event("transaction.created", "after the burst")
        eq("the next one that does send counts what was held",
           (len(posted), "5 further transaction.created entries" in posted[0]),
           (1, True))
        eq("  and points at the log, which has all of them",
           "System Log has all of them" in posted[0], True)
        eq("  the count is not carried twice",
           M._notify_state["held"].get("transaction.created"), None)

        # The ceiling: one event each, so the per-event limit cannot be what
        # stops it.
        M._save_server_cfg(notify_rules=[
            {"event": "e%d" % i, "to": "store@example.com", "level": "info"}
            for i in range(M._NOTIFY_HOURLY_MAX + 20)])
        _notify_reset()
        posted[:] = []
        for i in range(M._NOTIFY_HOURLY_MAX + 20):
            M._log_event("e%d" % i, "one each")
        eq("a hundred different events in an hour stop at the ceiling",
           len(posted), M._NOTIFY_HOURLY_MAX)
        eq("  and the rest are held rather than forgotten",
           sum(M._notify_state["held"].values()), 20)
        eq("  which the next hour lets through, counting what it held",
           M._notify_gate("e%d" % M._NOTIFY_HOURLY_MAX,
                          now=(M._notify_state["hour"] + 1) * 3600.0),
           (True, 1))
    finally:
        M.server_mail._send_mail = real
    _notify_reset()
    fresh_db()


def check_a_notification_can_never_break_the_entry_behind_it():
    """_log_event's promise is above the mail's, and stays above it (031).

    The hook sits after the row is written and inside a `try` of its own rather
    than the one that wraps the write. The difference is the return value: a
    notification that raised inside the outer `try` would make this function
    answer False about a row it really wrote, and `POST /clients/log` reads
    that answer.
    """
    head("a notification can never break the entry behind it (031)")
    db = fresh_db()
    _blank_lookup()
    _stub_lookup([("1001", "S-1", "Laptop", "T14")])
    real = M.server_mail._send_mail

    def explodes(to, subject, body):
        raise RuntimeError("the mail layer fell over")

    # On the mail module, for the reason the first of these groups gives.
    M.server_mail._send_mail = explodes
    try:
        M._save_server_cfg(notify_rules=[
            {"event": "transaction.created", "to": "store@example.com",
             "level": "info"},
            {"event": "log.smoke", "to": "store@example.com", "level": "info"}])
        _notify_reset()
        eq("a notification that raises does not make the writer lie about the"
           " row", M._log_event("log.smoke", "written"), True)
        conn = sqlite3.connect(M.DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM system_log WHERE"
                         " event='log.smoke'").fetchone()[0]
        conn.close()
        eq("  and the row really is there", n, 1)

        _notify_reset()
        payload, status = M._create_transaction(
            {"asset_number": "1001", "team_member": "Brian Dawson",
             "direction": "Out Store"})
        eq("a Transaction is recorded while the mail layer is broken",
           (status, payload.get("status")), (201, "created"))
        c = M.app.test_client()
        eq("  still confirmed",
           c.post("/confirm/%d" % payload["id"]).status_code, 200)
        _notify_reset()
        p2, _st = M._create_transaction(
            {"asset_number": "1001", "team_member": "Brian Dawson",
             "direction": "In Store"})
        eq("  still rejected",
           c.post("/reject/%d" % p2["id"],
                  json={"reason": "not mine"}).status_code, 200)
    finally:
        M.server_mail._send_mail = real
    _notify_reset()
    fresh_db()
    _blank_lookup()
    del db
