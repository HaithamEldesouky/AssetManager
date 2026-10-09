r"""What a Client sends and trusts through common.py: the structured data it
ships, and the certificate it reports and stages.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import io
import os

from client_checks.stage import (C, eq, head)


def check_the_client_ships_structured_data():
    """`data` (#247/072): the same document on the wire and in the local file.

    Both halves are read back, as they are for every other entry these apps
    write - the shipping queue is the copy the Admin ends up reading and
    `client.log` is what this machine can still say about itself - because a
    client that queues the facts and writes a line without them is two
    records of one action that disagree, which is the whole reason the caps
    in `common.py` are the server's caps rather than looser ones.

    The **dict** is what is queued rather than the text of it. The server
    serialises its own copy in `_log_event`, so an entry carrying the text
    would arrive as a JSON string holding a document instead of as the
    document, and the column would be unreadable to `event_phrase` while
    looking perfectly full.
    """
    head("the client ships structured data with an entry (#247/072)")

    def wrote(**kw):
        """One `log_event`, with both halves of the log emptied first."""
        with C._log_lock:
            del C._log_queue[:]
        io.open(C.LOG_PATH, "w", encoding="utf-8").close()
        taken = C.log_event("cert.installed", "was none  ->  now ab", **kw)
        with C._log_lock:
            queued = list(C._log_queue)
        lines = [l for l in io.open(C.LOG_PATH, encoding="utf-8")
                 if l.strip()]
        return taken, queued, lines

    taken, queued, lines = wrote(data={"now": "ab", "was": "none"})
    eq("an entry carrying data is taken", taken, True)
    eq("  and ships the dict itself, not the text of it",
       [e["data"] for e in queued], [{"now": "ab", "was": "none"}])
    eq("  and is still one line in this machine's own client.log",
       len(lines), 1)
    eq("  with the same document on the end of it, keys sorted",
       lines[0].rstrip("\n").endswith('{"now": "ab", "was": "none"}'), True)

    taken, queued, lines = wrote()
    eq("an entry with no data is taken exactly as before", taken, True)
    eq("  and ships data as None rather than the writer's own default",
       [e["data"] for e in queued], [None])
    eq("  and its line ends where it always did",
       lines[0].rstrip("\n").endswith("was none  ->  now ab"), True)

    big = {"note": "n" * (C.LOG_DETAIL_MAX + 200)}
    taken, queued, lines = wrote(data=big)
    eq("an over-long document still writes the entry", taken, True)
    eq("  with data dropped whole rather than cut in half",
       [e["data"] for e in queued], [None])
    eq("  and one line, not a line and a fragment", len(lines), 1)
    eq("  and the detail untouched by data's own cap",
       [e["detail"] for e in queued], ["was none  ->  now ab"])

    taken, queued, _l = wrote(data={"x": object()})
    eq("a value json cannot serialise still writes the entry", taken, True)
    eq("  with data None rather than the entry refused",
       [e["data"] for e in queued], [None])

    # A newline inside a value is the one way a trailing field could cost the
    # file its one-line-per-entry shape; json escapes it, and that is asserted
    # rather than assumed.
    _t, _q, lines = wrote(data={"note": "one\ntwo"})
    eq("a newline inside a value does not become a second line", len(lines), 1)

    try:
        io.open(C.LOG_PATH, "w", encoding="utf-8").close()
        with C._log_lock:
            del C._log_queue[:]
    except OSError:
        pass


def check_a_checkin_reports_the_certificate_this_install_trusts():
    """What a Client says it holds, and what it says when it holds nothing.

    The Server GUI's Connected Clients answers "who would break if I replaced
    the certificate today" off this one field, so it has to be the fingerprint
    of the file this installation actually pins - `ssl_cert.pem` beside the app,
    which is what the pinned session loads and what it fails closed without
    (rule 1) - and it has to be **the same number** the Server GUI's Server
    Settings window and `Get-CertFingerprint` show for that certificate. That
    is the digest over the DER bytes between the PEM markers; hashing the
    file's text gives a number that looks equally plausible and matches none of
    the three, and nobody comparing two of them would find out here.

    Driven rather than read, with the transport replaced by something that
    keeps the body: what is asserted is what left this machine.
    """
    head("the certificate a check-in reports")
    import base64, hashlib
    real_api = C.api
    sent = {}

    class _Answer(object):
        ok = True

        def json(self):
            return {"status": "ok", "client_id": "c-1"}

    def _keep(_method, _url, json=None, **_k):
        sent.clear()
        sent.update(json or {})
        return _Answer()

    der = b"these bytes are the certificate, as far as a digest is concerned"
    want = hashlib.sha256(der).hexdigest().upper()
    want = ":".join(want[i:i + 2] for i in range(0, len(want), 2))
    pem = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n"
           % base64.b64encode(der).decode())
    had = None
    if os.path.exists(C.SSL_CERT_PATH):
        with io.open(C.SSL_CERT_PATH, "rb") as f:
            had = f.read()
    try:
        C.api = _keep
        cfg = {"client_id": "c-1"}

        with io.open(C.SSL_CERT_PATH, "w", encoding="utf-8") as f:
            f.write(pem)
        C.checkin("https://server", cfg, lambda _c: None, "Notifier", "2.4.0",
                  member="Brian Dawson", member_key="current_user")
        eq("the check-in carries the certificate this install trusts",
           sent.get("cert_fingerprint"), want)
        eq("  which is the digest over the DER bytes, not over the PEM text",
           sent.get("cert_fingerprint") ==
           hashlib.sha256(pem.encode()).hexdigest().upper(), False)
        eq("  and it is what server.py would compute for the same file",
           C.cert_fingerprint(pem), want)
        # The identifier is whatever `client_id` resolved for this run -
        # this file stages a config of its own - so what is asserted is that
        # one went out beside the fingerprint rather than which one.
        eq("  beside everything the check-in already said",
           (bool(sent.get("client_id")), sent.get("app"),
            sent.get("member")),
           (True, "Notifier", "Brian Dawson"))

        # A client with no certificate is not stranded by a replacement - it
        # has nothing pinned - so "" is the true answer rather than an
        # omission, which on this endpoint would read as a field cleared and
        # mean the same thing anyway.
        os.remove(C.SSL_CERT_PATH)
        C.checkin("https://server", cfg, lambda _c: None, "Storekeeper",
                  "2.4.0")
        eq("a Client holding no certificate says so",
           sent.get("cert_fingerprint"), "")
        eq("  and it is still the key, not a missing one",
           "cert_fingerprint" in sent, True)

        # A file that is there and is not a certificate is the same answer: a
        # check-in rides the tick that asks about Transactions, and an engineer
        # who stops being asked to confirm anything is what this must never
        # cost.
        with io.open(C.SSL_CERT_PATH, "w", encoding="utf-8") as f:
            f.write("this is not a certificate")
        eq("an unreadable certificate answers '' rather than raising",
           C.own_cert_fingerprint(), "")
        C.checkin("https://server", cfg, lambda _c: None, "Notifier", "2.4.0")
        eq("  and the check-in still goes out",
           sent.get("cert_fingerprint"), "")
    finally:
        C.api = real_api
        if had is None:
            if os.path.exists(C.SSL_CERT_PATH):
                os.remove(C.SSL_CERT_PATH)
        else:
            with io.open(C.SSL_CERT_PATH, "wb") as f:
                f.write(had)


def check_a_checkin_reports_the_address_this_machine_has():
    """The Client's own side of the address (#281), and what it says on failure.

    Behind NAT the server sees the gateway, so the Client names the interface
    it would route to the server through. Against a loopback server that is
    the loopback address - a dotted IPv4, not a hostname or a blank - and a
    host that does not resolve is "" rather than a raise into the tick.
    """
    head("the address a check-in reports")
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    url = "https://127.0.0.1:%d" % srv.getsockname()[1]
    real_api = C.api
    sent = {}

    class _Answer(object):
        ok = True

        def json(self):
            return {"status": "ok", "client_id": "c-1"}

    def _keep(_method, _url, json=None, **_k):
        sent.clear()
        sent.update(json or {})
        return _Answer()

    try:
        got = C.own_address(url)
        try:
            socket.inet_aton(got)
            dotted = got.count(".") == 3
        except (OSError, TypeError):
            dotted = False
        eq("against a loopback server it is a dotted IPv4",
           (dotted, got), (True, "127.0.0.1"))
        eq("a host that does not resolve answers ''",
           C.own_address("https://no-such-host.invalid:8081"), "")
        eq("  and so does a URL with no host in it",
           C.own_address("not a url"), "")
        C.api = _keep
        C.checkin(url, {"client_id": "c-1"}, lambda _c: None, "Notifier",
                  "2.4.0")
        eq("the check-in carries it as reported_address",
           sent.get("reported_address"), "127.0.0.1")
        C.checkin("https://no-such-host.invalid:8081", {"client_id": "c-1"},
                  lambda _c: None, "Notifier", "2.4.0")
        eq("  and sends the key as '' when it has none",
           ("reported_address" in sent, sent.get("reported_address")),
           (True, ""))
    finally:
        C.api = real_api
        srv.close()


def check_the_staged_certificate_is_appended_and_never_replaces():
    """`common.trust_next_cert`, and the four answers that write nothing.

    This is the one function in these three apps that writes the file every
    request is verified against, so what is asserted is mostly an **absence**:
    a 404, a body that is not a certificate, base64 that will not decode and a
    pinned file that is not a bundle all have to leave `ssl_cert.pem` byte for
    byte as it was. A client with a damaged one cannot reach the server to be
    told anything ever again (rule 1), so there is no failure here that can be
    recovered from at the console - it is a walk to the machine.

    The append itself is asserted both ways round: the served certificate is
    still **first** afterwards, which is what keeps C2's Certificate column
    reporting the certificate this install is actually being served, and the
    staged one is there beside it, which is what `load_verify_locations` reads
    as a second anchor. And it is **idempotent** - a second run answers "" and
    writes nothing - because the command that reaches it is re-issuable by
    design, a push being a signal and not a payload (ADR-0020).

    Driven with the transport stubbed, for this file's usual reason: pointing
    it at a real server would file a check-in from whatever machine ran the
    gate, and the 404 leg has no server to be answered by anyway.
    """
    head("the staged certificate is appended, never substituted")
    import base64
    real_api = C.api

    def _pem(body):
        return ("-----BEGIN CERTIFICATE-----\n%s\n"
                "-----END CERTIFICATE-----\n"
                % base64.b64encode(body).decode())

    live = _pem(b"the certificate this install is being served")
    staged = _pem(b"the certificate bound to nothing at all")
    want = C.cert_fingerprint(staged)

    class _Answer(object):
        def __init__(self, ok, content=b""):
            self.ok = ok
            self.content = content

    served = {"body": staged.encode(), "ok": True}
    asked = []

    def _serve(_method, url, **_k):
        asked.append(url)
        return _Answer(served["ok"], served["body"])

    had = None
    if os.path.exists(C.SSL_CERT_PATH):
        with io.open(C.SSL_CERT_PATH, "rb") as f:
            had = f.read()
    try:
        C.api = _serve

        with io.open(C.SSL_CERT_PATH, "w", encoding="utf-8") as f:
            f.write(live)
        got = C.trust_next_cert("https://server")
        eq("the append answers with the fingerprint it added", got, want)
        eq("  fetched from the staged route", asked and asked[-1],
           "https://server/cert/next")
        held = io.open(C.SSL_CERT_PATH, encoding="utf-8").read()
        blocks = C._cert_blocks(held)
        eq("the pinned file now holds both", len(blocks), 2)
        eq("  and the one being served is still first",
           C.cert_fingerprint(blocks[0]), C.cert_fingerprint(live))
        eq("  with the staged one beside it",
           C.cert_fingerprint(blocks[1]), want)

        after = io.open(C.SSL_CERT_PATH, "rb").read()
        eq("a second run appends nothing and says nothing",
           C.trust_next_cert("https://server"), "")
        eq("  leaving the file exactly as it was",
           io.open(C.SSL_CERT_PATH, "rb").read(), after)

        # The four answers that are not an append. Each is checked against the
        # bytes rather than against the return value alone: "" is what a
        # refusal and a certificate already held both say, and only one of
        # those two would be a defect if it had written.
        for label, setup in (
                ("nothing is staged", lambda: served.update(ok=False,
                                                            body=b"")),
                ("the body is not a certificate",
                 lambda: served.update(ok=True, body=b"404 Not Found")),
                ("the base64 will not decode",
                 lambda: served.update(
                     ok=True,
                     body=(b"-----BEGIN CERTIFICATE-----\n!!!!\n"
                           b"-----END CERTIFICATE-----\n"))),
        ):
            setup()
            eq("with %s nothing is appended" % label,
               C.trust_next_cert("https://server"), "")
            eq("  and ssl_cert.pem is untouched",
               io.open(C.SSL_CERT_PATH, "rb").read(), after)

        # A pinned file that is not a bundle is the sharpest of the four: the
        # incoming certificate is perfectly good, and writing it would leave
        # this installation pinning something nobody confirmed (ADR-0010).
        served.update(ok=True, body=staged.encode())
        with io.open(C.SSL_CERT_PATH, "w", encoding="utf-8") as f:
            f.write("this is not a certificate")
        eq("a pinned file that is not a bundle is left alone",
           C.trust_next_cert("https://server"), "")
        eq("  exactly as it was",
           io.open(C.SSL_CERT_PATH, encoding="utf-8").read(),
           "this is not a certificate")

        # And nothing is fetched at all over a connection this function has no
        # way to verify: `http://` is not a smaller version of this, it is the
        # ADR-0010 bootstrap without the person.
        before = len(asked)
        eq("a plain http server is not asked at all",
           C.trust_next_cert("http://server"), "")
        eq("  no request was made", len(asked), before)
    finally:
        C.api = real_api
        if had is None:
            if os.path.exists(C.SSL_CERT_PATH):
                os.remove(C.SSL_CERT_PATH)
        else:
            with io.open(C.SSL_CERT_PATH, "wb") as f:
                f.write(had)
