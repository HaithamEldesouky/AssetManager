"""
Asset Manager — code shared by the three client apps.

Imported by storekeeper_app.py, notifier_app.py and installer.py. The server
deliberately does not import it: it shares no transport code with the clients,
and pulling a client module into the service would tie the two release paths
together for nothing.

What lives here is the wire layer - how a client trusts the server, how it finds
the server after a port change, how it checks a password with it, how it asks
the register what an asset is or which types it holds, and how it tracks a
pending update, and how it records and ships what it did. Each of
these existed as a byte-identical copy in two or three apps, and the copies were
kept in sync by hand; a TLS change had to be made three times and be right three
times. The password check is the newest of them: it lived in the Notifier alone
until the installer needed the same answer, and it is two doors rather than one,
because which passwords open a thing is part of what a caller is asking. Both
doors need the server, so the sentence a client shows when neither could be
asked - and the rule behind it, that the Server URL alone may be changed then -
is here as well, in one wording for the two windows that show it. The
System Log is here for the same reason and with the same split: the rolling
local file and the shipping loop are transport and live here once, while *what*
is worth logging is each app's own decision, the way a command's handler is.

Four more joined them by #211, the last of the copies rule 10 was written
against: `load_config`/`save_config`, the config.json-read-over-defaults both
apps kept under two names over the same four lines - the path and the defaults
were the only thing that ever differed, so those are what moved here as
arguments, the way `server_cert.py` takes its paths from `server.py` rather
than resolving its own; `_has_client_package`, the client_packages check
against `GET /version`'s answer, keyed the same way by the app's own
UPDATE_APP_KEY; and `_mark`, the header bar's rounded "A" badge - the one
widget this file draws, and the one place here that imports `tkinter`
(deferred inside the function, the way `ui_kit.py`'s own uses are), because
what it returns is a `Canvas` the caller already owns rather than a window of
this module's own. `_tag_status` looked like a fifth of these and stayed
where it was: the Notifier's filters by client and the Storekeeper's does not,
so what they compute has genuinely diverged rather than merely being spelled
twice.

Paths (SSL_CERT_PATH, UPDATE_STATE_PATH) resolve next to the running exe when
frozen and next to this file otherwise - the same rule every app uses, so a
staged dev copy and an installed exe behave alike. The installer overrides
SSL_CERT_PATH at import time, because it may read the certificate bundled inside
itself. PyInstaller follows the import on its own, so the build needs no change;
tools/dev-run.ps1 copies this file into each staged app directory.
"""

import base64
import getpass
import hashlib
import http.client
import json
import os
import socket
import ssl
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter

# The one drawing primitive _mark borrows - see its docstring for why this
# file imports tkinter at all.
import ui_kit

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Read through the module (common.SSL_CERT_PATH) rather than imported by value,
# so the installer's override at import time is seen by api() below.
SSL_CERT_PATH = os.path.join(BASE_DIR, "ssl_cert.pem")

# Fallback engineer list. The server is the source of truth - every client
# loads GET /members at startup - and this is only what a client shows when
# the server cannot be reached, which is also the moment nobody can add an
# engineer anyway. It lived in three files that had to be edited together.
# server.py keeps its own seed list: it seeds the table from it on first run,
# and it does not import this module.
TEAM_MEMBERS = [
    "Alice Carter",
    "Brian Dawson",
    "Carol Evans",
    "David Foster",
]

# ─── Transport ────────────────────────────────────────────────────────────────


class _SelfSignedAdapter(HTTPAdapter):
    """Trust one specific self-signed certificate, and nothing else."""

    def __init__(self, cert_path, **kw):
        self._cert_path = cert_path
        super().__init__(**kw)

    def _make_ctx(self):
        if not os.path.exists(self._cert_path):
            # Fail closed. This branch used to fall back to the system
            # certificate store with check_hostname off, which accepts any
            # publicly-trusted certificate for any hostname - anyone on this
            # network holding one certificate could impersonate the server.
            # Refusing is the only safe answer: the server's certificate is
            # self-signed, so nothing in the system store can vouch for it, and
            # the installer is the channel that re-supplies the file.
            raise requests.exceptions.SSLError(
                "no ssl_cert.pem next to this app, so the server's certificate "
                "cannot be verified. Accept the fingerprint when this app offers "
                "it, or re-run AssetManager_Setup.exe to reinstall the file.")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # The certificate is pinned by file, so the hostname it was issued for
        # does not matter - clients reach the same server as asset-server, by
        # IP, and by 127.0.0.1 in dev.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(self._cert_path)
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = self._make_ctx()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs['ssl_context'] = self._make_ctx()
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def api(method, url, **kw):
    """requests.<method>(url), trusting the pinned certificate for https."""
    kw.setdefault("timeout", 7)
    if url.startswith("https"):
        if not os.path.exists(SSL_CERT_PATH):
            # First contact with nothing to trust yet: offer the certificate
            # for confirmation rather than dead-ending. Nothing is written
            # unless whoever is at the machine accepts the fingerprint, and
            # the adapter below still fails closed when they do not.
            bootstrap_cert(url)
        try:
            s = requests.Session()
            s.mount("https://", _SelfSignedAdapter(SSL_CERT_PATH))
            return getattr(s, method)(url, **kw)
        except requests.exceptions.SSLError as _e:
            if "WRONG_VERSION_NUMBER" in str(_e) or "wrong version number" in str(_e).lower():
                # The server is serving plain HTTP on this port - follow it.
                # Only reachable when a certificate is present; without one the
                # adapter refuses before any connection is made.
                return getattr(requests, method)(url.replace("https://", "http://", 1), **kw)
            raise
    return getattr(requests, method)(url, **kw)


# ─── The server holding writes ────────────────────────────────────────────────

# What the server answers a write with while a backup or a restore is running
# (ADR-0018): a 503 carrying this code. Both clients read it and neither
# carries its own spelling of it (rule 10) - a client that tested for the wrong
# string would treat a hold as an ordinary server error, and what that costs is
# different in each of them: a Transaction re-POSTed row by row on the Tk
# thread here, and an engineer's Confirm thrown away there.
MAINTENANCE_CODE = "maintenance"


def held_for_maintenance(r):
    """Is this answer the server saying it is not taking writes just now?

    A 503 **and** the code, rather than either alone. Not the status on its
    own, because an ordinary 5xx is about the one row and the Storekeeper's
    flush is right to carry on past it; and not the code on its own, because
    what makes this readable by a client built before it existed is that the
    status is already the one such a client keeps its row for.

    Answers False for anything it cannot read, which is the same direction
    every other reader here takes: an answer this does not recognise is handled
    as whatever its status already means, never as a hold that nothing will
    lift.
    """
    if r is None or getattr(r, "status_code", None) != 503:
        return False
    try:
        return (r.json() or {}).get("code") == MAINTENANCE_CODE
    except Exception:
        return False


def maintenance_notice(r):
    """The server's own words for why it is holding, or a sentence of ours.

    Shown rather than computed, the way every other refusal these clients
    report is: only the server knows what it is busy with, and "the server is
    busy" with no idea what it is busy with is the answer nobody can act on.
    """
    try:
        said = (r.json() or {}).get("error")
    except Exception:
        said = None
    return said or ("The server is busy with maintenance and is not taking "
                    "writes just now.")


# ─── Bootstrapping the pinned certificate ─────────────────────────────────────

# The callback an app registers to ask its user, and the lock and flag that
# keep one process to a single attempt. Without a callback nothing here runs
# and a client with no certificate fails closed exactly as it did before, which
# is what the installer's own path relies on when it already holds the file.
_cert_confirm = None
_cert_lock    = threading.Lock()
_cert_asked   = False


def set_cert_confirm(fn):
    """Register how this app asks its user to accept a fingerprint.

    `fn(fingerprint, server_url)` returns True to pin, anything else to refuse.
    It lives in the app rather than here because a tray app, a window and an
    installer ask in three different idioms, while the decision - what is
    fetched, what is measured, what is written - is one answer and belongs in
    one place (rule 10). An app that registers nothing keeps the old behaviour.
    """
    global _cert_confirm
    _cert_confirm = fn


def reset_cert_prompt():
    """Let the next bootstrap ask again, for a caller that asks on purpose.

    `bootstrap_cert` asks once per process whatever the answer, and that rule
    is about a client that ticks: the Notifier and the Storekeeper reach the
    server every fifteen seconds, so a refusal that could be re-asked there
    would be a dialog every fifteen seconds until somebody accepted it without
    reading - which is the one way a fingerprint prompt stops meaning anything.
    Restarting the app is what asks those two again.

    The installer is the caller that is not that. It reaches the server when
    somebody clicks Install, once per click, and the prompt it opens has Cancel
    as its default button, so a stray keypress refuses it. Every later click
    then fails closed with no file on disk and is reported as a server that
    cannot be reached - which is what that message must never say while the
    server is up, the URL is right and the password is right, and the one line
    offering a way out names an offer that can no longer come. So an install
    attempt re-arms the question, and the re-arming is named here rather than
    reached into from there: which callers may ask twice is part of the
    decision this file owns (rule 10), and a private poked from another module
    is a rule with nowhere to be written down.

    It re-arms the **question** and nothing else. A certificate already on disk
    is still not re-offered, that being `bootstrap_cert`'s other condition and
    a different fact - this says nobody has been asked yet, not that nothing is
    trusted.
    """
    global _cert_asked
    with _cert_lock:
        _cert_asked = False


def confirm_on_tk_thread(root, ask, timeout=300):
    """Run `ask()` on the Tk thread from wherever this was called, and wait.

    Both windowed clients reach the server from worker threads - the poll loop,
    the background tick - and a Tk call from one of those raises rather than
    drawing anything. So the question is marshalled with after() and the worker
    waits for the answer. Shared for the reason everything else here is: two
    copies of this is two chances to get the failure branch wrong.

    Refuses rather than pins when there is nothing to ask on: after() raises
    when mainloop is not running yet, and a timeout means nobody answered. A
    certificate must not be pinned by a client nobody was looking at.
    """
    if threading.current_thread() is threading.main_thread():
        return bool(ask())
    answer = {}
    done   = threading.Event()

    def run():
        try:
            answer["value"] = ask()
        finally:
            done.set()

    try:
        root.after(0, run)
    except Exception:
        return False
    if not done.wait(timeout):
        return False
    return bool(answer.get("value"))


def cert_fingerprint(pem):
    """The SHA-256 fingerprint of the first certificate in `pem`, or None.

    Colon-separated uppercase hex, which is what openssl prints and what the
    Server GUI's SSL Certificate dialog shows - the two are compared by a human
    reading one against the other, so they have to be the same shape.

    The digest is over the DER bytes, the base64 between the PEM markers,
    because that is what every other tool fingerprints; hashing the text would
    give a number that looks right and matches nothing. The first certificate
    is the one measured: a chain's leaf comes first, and the leaf is what is
    being compared.

    server.py computes the same value from a file and this takes bytes, because
    what is being measured here has not been written anywhere yet and must not
    be until it is accepted. The server does not import this module and never
    will (rule 10 says so in as many words), so the two are separate on purpose
    rather than by omission.
    """
    if isinstance(pem, bytes):
        pem = pem.decode("utf-8", "replace")
    head, tail = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    start = pem.find(head)
    end   = pem.find(tail, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    # validate=True: a decode that quietly skips whatever it does not
    # recognise would answer corrupt bytes with a fingerprint, and a wrong
    # fingerprint is the one thing here nobody can check against anything else.
    try:
        der = base64.b64decode("".join(pem[start + len(head):end].split()),
                               validate=True)
    except Exception:
        return None
    if not der:
        return None
    hexed = hashlib.sha256(der).hexdigest().upper()
    return ":".join(hexed[i:i + 2] for i in range(0, len(hexed), 2))


def cert_prompt_text(fingerprint, server_url):
    """The title and body every app shows when it asks. Returns (title, body).

    One copy of the wording rather than three, because what the person is told
    is the whole of the protection here: the fingerprint means nothing to
    somebody who has not been told where to check it, and an app that asked
    more casually than the others would be the one that got waved through.

    Laid out in groups of eight pairs, the same shape the Server GUI's SSL
    Certificate dialog shows, so the two can be read against each other a line
    at a time.
    """
    pairs = fingerprint.split(":")
    lines = ["  ".join(pairs[i:i + 8]) for i in range(0, len(pairs), 8)]
    return ("Trust this server?",
            "This is the first connection to\n"
            "    %s\n"
            "and there is no certificate on this machine to check it against.\n\n"
            "SHA-256 fingerprint of the certificate it offered:\n\n"
            "%s\n\n"
            "Check that against the Server GUI's SSL Certificate dialog, on the\n"
            "server itself, before accepting. Accepting pins this certificate:\n"
            "this app will refuse to talk to anything else afterwards.\n\n"
            "Cancel writes nothing and changes nothing."
            % (server_url, "\n".join("    " + ln for ln in lines)))


def _fetch_offered_cert(origin, timeout=6):
    """GET /cert over a connection that verifies nothing, and hand back the bytes.

    A self-signed server cannot be verified before its certificate is in hand,
    so this one connection is unverified and is the only one in this file that
    is. It is http.client rather than the session api() uses, deliberately:
    that session's adapter is the pinned one, and relaxing it - or handing
    requests a verify=False - would put an unverified path within reach of
    every other call here. What crosses this one is a GET of a public file: no
    credential, no check-in, no transaction. What comes back is not trusted
    either - it is measured and shown to a human to accept.

    The body is capped, because nothing has vouched for what is at the other
    end and a certificate is a couple of kilobytes. Returns None for anything
    that is not a 200.
    """
    parts = urlsplit(origin)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(parts.hostname, parts.port,
                                       timeout=timeout, context=ctx)
    try:
        conn.request("GET", "/cert")
        r = conn.getresponse()
        if r.status != 200:
            return None
        return r.read(65536)
    finally:
        conn.close()


def bootstrap_cert(url):
    """Offer the server's certificate for confirmation, and pin it if accepted.

    Trust on first use, with the first use answered by a person: the
    fingerprint of what came back is shown, and the file is written only if it
    is accepted. A silent fetch-and-pin was rejected for this - whoever
    answered for the server during that window would be pinned permanently, and
    the next Settings unlock would hand them the admin password. See ADR-0010.

    Only GET /cert crosses the unverified connection. Every other request in
    this file goes through the pinned adapter and still fails closed with no
    file on disk, and sync_server_cert() is untouched: it refreshes over a
    connection the current pin has already verified, which is a different
    question from this one.

    One attempt per process, whatever the outcome. The clients tick every 15
    seconds, so a refusal that could be re-asked would be a dialog every 15
    seconds until it was accepted, which is how a person is trained to accept
    it without reading. Restarting the app asks again - and so does
    reset_cert_prompt(), for the one caller that asks on purpose rather than on
    a tick.

    Never raises: the caller is on its way to a request that will fail closed
    on its own if this does not produce a file, and that failure is the honest
    one to report.
    """
    global _cert_asked
    if _cert_confirm is None:
        return
    with _cert_lock:
        if _cert_asked or os.path.exists(SSL_CERT_PATH):
            return
        _cert_asked = True
    try:
        parts  = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        body = _fetch_offered_cert(origin)
        if not body or b"BEGIN CERTIFICATE" not in body:
            return
        if b"PRIVATE KEY" in body:
            # A server serving its own key is not a server to pin. Nothing
            # legitimate answers /cert with one, so this is either a
            # misconfiguration nobody should paper over or something pretending
            # to be the server.
            return
        fp = cert_fingerprint(body)
        if not fp:
            return
        if not _cert_confirm(fp, origin):
            return
        with open(SSL_CERT_PATH, "wb") as f:
            f.write(body)
    except Exception:
        return


# ─── Verifying a password ─────────────────────────────────────────────────────


def verify_password(server_url, name, password):
    """Verify one password against the server, on an engineer's behalf.

    Returns /auth/verify's own answer - {valid, admin, profile, permissions} -
    so a caller can tell an accepted password from a refused one, and can tell
    the admin password from an engineer's own. `admin` is reported separately
    rather than folded into the permission list because an admin is not limited
    by the engineer's profile.

    A server that predates /auth/verify answers 404, and the fallback then goes
    through verify_admin_password: mid-rollout the admin password is the only
    one such a server knows, and a client that updated first must not lock the
    admin out. It goes through that function rather than asking /admin/verify
    here, so the admin door has one call site and not two. A 401 is deliberately
    not a fallback - that is a wrong password, not an old server, and retrying
    it as an admin password would turn one refusal into two and report the wrong
    reason for the second.

    Raises whatever api() raises when the server cannot be reached: "the check
    could not be made" is a different answer from "wrong password", and only the
    caller knows how to say so on its own screen.
    """
    refused = {"valid": False, "admin": False,
               "profile": "default", "permissions": []}

    r = api("post", "%s/auth/verify" % server_url,
            json={"name": name, "password": password})

    if r.status_code == 404:
        # Through the other door rather than asking /admin/verify here. Asking
        # it here was this function's own two-line copy of that door, inside
        # the module that exists to stop those two lines being copied.
        if verify_admin_password(server_url, password):
            # An old server has no profile to report, and it does not matter:
            # the only password it accepted is the admin password, which no
            # profile limits.
            return {"valid": True, "admin": True,
                    "profile": "default", "permissions": []}
        return refused

    if r.ok and r.json().get("valid"):
        return r.json()
    return refused


def verify_admin_password(server_url, password):
    """True when this is the admin password. Nothing else opens what it opens.

    The other door in this section, for the callers that must not accept an
    engineer's own password: standing up a Storekeeper, pointing a Notifier at a
    server, opening the Storekeeper's Server Settings. verify_password accepts
    an own password by design, so routing these through it would hand an
    engineer three things that are not theirs.

    Two doors rather than one function with a flag, because a flag would put
    "may an own password open this?" at every call site, and that is the one
    decision here that must not be gettable wrong.

    What refuses an own password is /admin/verify itself - it is checked against
    the admin hash and nothing else - so this function's job is to knock on that
    door and not the other one. A capability password is refused there too: it
    is a console credential and reaches no endpoint at all (ADR-0006).

    No fallback of its own. /admin/verify has existed for as long as the
    endpoint set has, unlike /auth/verify, so there is no older server to
    accommodate - and inventing one on the chance would be a second copy of a
    fallback, which is what this section exists to avoid. It is also the one
    place that asks the endpoint: verify_password's own fallback comes through
    here rather than asking it a second time.

    Raises whatever api() raises when the server cannot be reached, the same
    contract verify_password has: "the check could not be made" is a different
    answer from "wrong password", and all three callers say so differently on
    their own screens.
    """
    r = api("post", "%s/admin/verify" % server_url, json={"password": password})
    return bool(r.ok and r.json().get("valid"))


def offline_url_notice(server_url):
    """What a client puts on its settings window when nobody could be asked.

    Both doors above need the server, and the Server URL is the setting whose
    wrongness is why the server cannot be reached - so the one field that can
    fix it sits behind a check that needs it already fixed. Where the check
    could not be *made*, each client opens its settings window with that field
    alone editable and says this on it. A refusal never comes here: a wrong
    password is an answer, and only an unanswered one opens anything.

    The sentence lives here for the reason `cert_prompt_text` does (rule 10) -
    the Notifier and the Storekeeper both show it, and what an engineer is told
    about a password nobody checked must not exist in two wordings. Drawing it
    is still the app's: this module opens no window. Three short lines with the
    URL on its own, so a label can take them as they are - a paragraph in a
    window whose width drags is a `wraplength` that stops being the answer the
    moment somebody widens it.
    """
    url = (server_url or "").strip()
    if len(url) > 60:
        url = url[:57] + "..."
    lines = ["⚠  No password could be checked - the server did not answer."]
    if url:
        lines.append(url)
    lines.append("The Server URL is the only setting that can be changed here.")
    return "\n".join(lines)


# ─── Port-change cascade ──────────────────────────────────────────────────────


def _swap_port(url, port):
    """Return url with its port replaced."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, "%s:%s" % (parts.hostname, port),
                       parts.path, parts.query, parts.fragment))


def resolve_server_url(cfg, save):
    """Return (base_url, health_json) for a server that answers, following an
    admin's port change.

    The Server GUI needs a restart to apply a new port, so while the old
    listener is still up /health reports the pending one as next_port. The
    client records that, and once the old port goes dead it tries next_port and
    then the port it was on before that. Persisting the working URL is what lets
    a client that was offline during the change still find the server later.

    Returns (None, None) when no candidate answers - callers keep their existing
    url and try again on the next tick.
    """
    base = (cfg.get("server_url") or "").rstrip("/")
    candidates = [base]
    for key in ("next_port", "last_known_port"):
        port = cfg.get(key)
        if port:
            candidate = _swap_port(base, port)
            if candidate not in candidates:
                candidates.append(candidate)

    for url in candidates:
        try:
            r = api("get", "%s/health" % url, timeout=5)
        except Exception:
            continue
        if not r.ok:
            continue
        try:
            health = r.json()
        except ValueError:
            health = {}

        changed = False
        if url != base:
            cfg["last_known_port"] = urlsplit(base).port
            cfg["server_url"] = url
            changed = True
        if health.get("next_port") != cfg.get("next_port"):
            cfg["next_port"] = health.get("next_port")
            changed = True
        if changed:
            try:
                save(cfg)
            except Exception:
                pass          # a read-only config is not worth losing the poll over
        return url, health
    return None, None


_last_cert_sync = 0.0


def sync_server_cert(server_url, min_interval=3600):
    """Refresh the local copy of the server's public certificate.

    This runs over a connection the certificate already on disk has verified, so
    a renewed certificate lands before the old one expires and no reinstall is
    needed. If the server is switched to a certificate the current one cannot
    verify, the client cannot reach it at all and needs the installer again -
    unavoidable without a real CA.

    Rate-limited because the clients tick every 15 seconds and a certificate
    changes maybe once a year.
    """
    global _last_cert_sync
    if not server_url.startswith("https"):
        return
    now = time.time()
    if now - _last_cert_sync < min_interval:
        return
    _last_cert_sync = now
    try:
        r = api("get", "%s/cert" % server_url, timeout=6)
        if not r.ok or b"BEGIN CERTIFICATE" not in r.content:
            return
        if os.path.exists(SSL_CERT_PATH):
            with open(SSL_CERT_PATH, "rb") as f:
                if f.read() == r.content:
                    return
        with open(SSL_CERT_PATH, "wb") as f:
            f.write(r.content)
    except Exception:
        pass          # keep the certificate we have; retried on the next interval


def own_cert_fingerprint():
    """The fingerprint of the certificate this installation trusts, or "".

    Read off `ssl_cert.pem` beside this app - the file the pinned session
    loads as its trust anchor and fails closed without (rule 1) - so what it
    answers is the one thing that decides whether this client can still reach
    the server after the certificate is replaced.

    "" for a client that holds none, and for one whose file cannot be read or
    parsed: the check-in is a statement about this installation and "I have no
    usable certificate" is the honest one to make there. It never raises, being
    called from the tick that also asks about Transactions.
    """
    try:
        with open(SSL_CERT_PATH, "rb") as f:
            return cert_fingerprint(f.read()) or ""
    except Exception:
        return ""


def own_address(server_url):
    """The address this machine would reach `server_url` from, or "".

    The server records the peer it saw, and behind a NAT or VPN gateway that
    is the gateway, the same for every Client behind it - so this is the
    Client's own side, sent beside it and never in place of it. A UDP socket
    `connect()`ed to the server picks the interface the OS would route
    through, which is the one that matters on a laptop holding VPN, Wi-Fi and
    Ethernet at once; connecting a datagram socket sends nothing.

    "" for every failure, a host that does not resolve included, for
    `own_cert_fingerprint`'s reason: it is called from the check-in tick and
    must not raise into it.
    """
    try:
        parts = urlsplit(server_url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((parts.hostname, port))
            return s.getsockname()[0] or ""
        finally:
            s.close()
    except Exception:
        return ""


_CERT_HEAD = "-----BEGIN CERTIFICATE-----"
_CERT_TAIL = "-----END CERTIFICATE-----"


def _cert_blocks(pem):
    """Every PEM certificate block in `pem`, in order, as text.

    Found with `find` rather than a regular expression for `cert_fingerprint`'s
    reason and one more: this module imports no `re`, and a splitter that had to
    be written twice - once here and once for the digest above - is exactly the
    second spelling of a certificate decision rule 10 exists to prevent. What it
    returns is the blocks alone, so anything else in the file is left behind the
    way `_export_public_cert` leaves it behind on the server: a key that ended up
    beside a certificate must not be copied forward by a routine that was only
    ever asked about certificates.
    """
    if isinstance(pem, bytes):
        pem = pem.decode("utf-8", "replace")
    out, at = [], 0
    while True:
        start = pem.find(_CERT_HEAD, at)
        if start < 0:
            return out
        end = pem.find(_CERT_TAIL, start + 1)
        if end < 0:
            return out
        at = end + len(_CERT_TAIL)
        out.append(pem[start:at])


def trust_next_cert(server_url):
    """Append the server's staged certificate to the pinned file. C3, ADR-0020.

    Phase two of a rotation. The server has generated a certificate and bound
    nothing to it (C1); this is every client learning to accept it **while the
    old one is still what is being served**, so that when the binding does move
    there is nobody at any machine to confirm anything. `load_verify_locations`
    reads a file holding several certificates as a bundle, so a client that has
    run this verifies against either one, and the cutover is then a restart on
    the server rather than a visit to four laptops.

    It is reached by the `trust_cert` Client command, which carries **no PEM**:
    `client_commands` has no payload column, and a command is handed over
    exactly once, so a hand-over lost to a crash would strand that machine with
    the server believing it had been told. A signal is re-issuable. The fetch
    is this client's own, over the connection its current certificate already
    verifies - `api()` and the pinned adapter like every other request, so this
    is **not** the ADR-0010 bootstrap and nothing here runs unverified.

    Returns the fingerprint it appended, or "" for every other answer. Every
    other answer leaves `ssl_cert.pem` exactly as it was, which is the whole of
    the safety here: that file is this installation's only trust anchor and a
    client with a damaged one cannot reach the server to be told anything
    again. So a 404 - the ordinary state, nothing staged - an unreadable body, a
    body carrying no certificate and one whose base64 will not decode are all
    the same answer, and the write goes to a temporary file beside the real one
    and is moved over it, `os.replace` being atomic on Windows as well: a
    truncated write here is a client that has locked itself out.

    **Appending is idempotent.** A client that already holds the staged
    certificate - the command reissued, or two pushes crossing - writes nothing
    and answers "", so a caller cannot tell a second run from a no-op and does
    not log one as a change.
    """
    if not server_url.startswith("https"):
        return ""
    try:
        r = api("get", "%s/cert/next" % server_url, timeout=8)
        if not r.ok:
            return ""
        incoming = _cert_blocks(r.content)
        if not incoming:
            return ""
        # The digest of what arrived, before anything is written: an answer
        # whose base64 does not decode has no fingerprint, and a certificate
        # nothing can name is one nothing could be compared against either.
        fp = cert_fingerprint(incoming[0])
        if not fp:
            return ""
        with open(SSL_CERT_PATH, "rb") as f:
            held = f.read()
        blocks = _cert_blocks(held)
        if not blocks:
            # The pinned file is not a certificate bundle at all. Appending to
            # it would produce one this client cannot explain, and rewriting it
            # is ADR-0010's job and answered by a person.
            return ""
        if any(cert_fingerprint(b) == fp for b in blocks):
            return ""
        body = ("\n".join(blocks + incoming) + "\n").encode("ascii")
        tmp = SSL_CERT_PATH + ".new"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, SSL_CERT_PATH)
        return fp
    except Exception:
        return ""          # the certificate we have is untouched; reissuable


# ─── Client identity, check-in and commands ──────────────────────────────────

# Matches _CHECKIN_MAX in server.py, which caps every field it stores. Truncated
# here as well so an over-long hostname is a shortened row rather than a check-in
# the server refused - the client cannot fix the hostname, and the row is worth
# more than the last few characters of it.
CHECKIN_MAX = 120

# One identity per run, even when the configuration cannot be written back. A
# read-only config.json - a locked-down laptop, a folder the engineer has no
# write access to - would otherwise mint a fresh identifier on every tick, and
# the Connected Clients list exists to answer how many installations there are
# and when each was last heard from. One machine filling it with a row every
# fifteen seconds would destroy the only question it answers.
_CLIENT_ID = None


def _persist(cfg, save):
    """Write the configuration back, and never raise into the caller's tick.

    An unwritable config.json leaves the identity lasting only as long as the
    process, which is still worth having: the alternative is a client that never
    checks in at all, so this is not the place to give up.
    """
    if not save:
        return
    try:
        save(cfg)
    except Exception:
        pass


def client_id(cfg, save=None):
    """This installation's identifier, generated once and kept in `cfg`.

    Generated by the Client rather than handed out by the server, which has
    nothing to key a handout on: the identifier is what tells two installations
    apart, so asking for one would need one already. A uuid4 rather than the
    hostname, because a hostname is not unique - a Notifier and the Storekeeper
    on one machine are two installations - and it moves, which is the whole
    reason the `clients` table is not keyed on it. Unguessable matters a little
    too: POST /clients/checkin is unauthenticated (ADR-0005), so identifiers
    anybody could enumerate would let a caller on the network overwrite another
    installation's row.
    """
    global _CLIENT_ID
    if _CLIENT_ID:
        return _CLIENT_ID
    kept = str(cfg.get("client_id") or "").strip()[:CHECKIN_MAX]
    if kept:
        _CLIENT_ID = kept
        return _CLIENT_ID
    _CLIENT_ID = uuid.uuid4().hex
    cfg["client_id"] = _CLIENT_ID
    _persist(cfg, save)
    return _CLIENT_ID


def forget_client_id(cfg, save=None):
    """Throw this installation's identifier away - the `reset_identity` command.

    The server keeps the old row: it is the record that an installation existed
    and when it was last heard from, and the next check-in arrives as a new one
    because from the registry's point of view it is a new installation. The
    cache is cleared as well as the file, and that half is the load-bearing one -
    without it the running process would carry on checking in under the identity
    the Admin had just reset, and would obey only on its next launch.
    """
    global _CLIENT_ID
    _CLIENT_ID = None
    cfg.pop("client_id", None)
    _persist(cfg, save)


def _adopt_member(cfg, save, member_key, answer):
    """Take the Engineer's id, and their current name, off a check-in answer.

    An Engineer's name can be corrected at the console, and this
    installation's copy of it is then a name that resolves to nobody:
    `GET /pending/<name>` answers with an empty queue, which is
    indistinguishable from having nothing to confirm, and the engineer stops
    being asked to confirm anything - the one failure the Notifier exists to
    prevent. The **id** is what a rename does not move, so it is kept the
    moment the server names one, and the name beside it is replaced by whatever
    the server says that id is called now.

    `member_key` is the config key this app keeps its Engineer under - the
    Notifier's `current_user`. The Storekeeper passes none, being configured as
    no Engineer at all. Which key that is, is the app's fact; reading the
    answer is this file's, for rule 10's reason - a second client doing its own
    reading of the same two fields is how the two come to disagree.

    A server too old to answer with either says nothing, which leaves both
    exactly as they were: the same reading the Storekeeper's name gets off
    `GET /health`, and for the same reason - absent is nothing said, not a
    value cleared.
    """
    changed = False
    mid = str(answer.get("member_id") or "").strip()
    if mid and str(cfg.get("member_id") or "") != mid:
        cfg["member_id"] = mid
        changed = True
    if member_key:
        name = str(answer.get("member") or "").strip()
        if name and str(cfg.get(member_key) or "") != name:
            cfg[member_key] = name
            changed = True
    if changed:
        _persist(cfg, save)


def checkin(server_url, cfg, save, app, version, member="", member_key=""):
    """Say this installation exists; return the commands queued for it.

    Returns [] for every failure, an unreachable server included. This rides on
    the tick that already refreshes what the user is looking at, so it must not
    raise into it - and a server that cannot be reached is the ordinary state of
    a laptop away from the office, not something to report.

    Everything sent is a fact about this installation, and the server overwrites
    every field rather than merging, so `member` is sent even when it is empty:
    the Storekeeper has no configured Engineer, and a Notifier re-pointed at a
    different one must stop being listed under the old one.

    `member_id` is sent beside the name once the server has told this
    installation what it is, and is what lets the Engineer be found again after
    their name has been corrected - see `_adopt_member`, which is what learns
    it. An installation that has never been told one sends nothing, and a
    server too old to answer with one never tells it: both are the behaviour
    this had before.

    `cert_fingerprint` is the certificate this installation currently trusts,
    and it is sent on every check-in rather than when it changes: the server
    overwrites every field, so a value sent once and then left out would read
    as current for ever, and this is the field an Admin is about to decide a
    certificate replacement on. A client holding none sends "", which is the
    answer that says it would not be stranded because it has nothing pinned.

    `reported_address` is sent every time for the same reason: a DHCP lease or
    a VPN reconnect moves it, and a value left out would read as current.
    """
    if not server_url:
        return []
    try:
        r = api("post", "%s/clients/checkin" % server_url,
                json={"client_id": client_id(cfg, save),
                      "hostname": socket.gethostname()[:CHECKIN_MAX],
                      "os_user": getpass.getuser()[:CHECKIN_MAX],
                      "app": app,
                      "version": version,
                      "member": (member or "")[:CHECKIN_MAX],
                      "member_id": str(cfg.get("member_id") or "")[:CHECKIN_MAX],
                      "cert_fingerprint":
                          own_cert_fingerprint()[:CHECKIN_MAX],
                      "reported_address":
                          own_address(server_url)[:CHECKIN_MAX]},
                timeout=6)
        if not r.ok:
            return []
        answer = r.json() or {}
        _adopt_member(cfg, save, member_key, answer)
        return answer.get("commands") or []
    except Exception:
        return []


# The order commands are obeyed in, lowest first, with anything unlisted in the
# middle. A command that ends the process has to run last: the server marks
# everything it hands over collected in one commit, so a logoff obeyed before a
# reset_identity that arrived alongside it would take the process down with the
# reset unapplied - and the Admin would be looking at a `collected` row for
# something that never happened, unable to reissue it because the queue's
# duplicate guard counts a collected command as done. `trust_cert` is in front
# of the logoff for that same reason and behind the reset for a different one:
# a reset throws the identifier away, and a certificate appended after it is
# still appended, where one appended before a logoff is the difference between
# a machine that survives the cutover and one somebody has to walk to.
#
# `update_now` (#177) is the second command that ends the process and the only
# one that brings the app back, so it sits in front of the logoff for the reason
# `trust_cert` does and behind both of the others for theirs: an identifier
# thrown away and a certificate appended are still thrown away and still
# appended after a restart, where neither survives being skipped by one. The
# pair it would actually race - a logoff arriving in the same batch - cannot
# arrive at all, `_queue_command` refusing the two against one Client precisely
# because no ordering here can settle them: the update handler returns as soon
# as its worker is started, so whatever runs next runs alongside a download.
_COMMAND_ORDER = {"reset_identity": 0, "trust_cert": 1, "update_now": 8,
                  "logoff": 9}


def obey(commands, handlers):
    """Run each queued command through this app's handler for it.

    Returns the names that actually ran, which is what a caller can assert on.

    A command this build has never heard of is skipped rather than raised on: a
    server upgraded ahead of a client will hand one back, and the rest of the
    response still has to be obeyed. It is not retried, because the server
    already marked it collected - which is the honest outcome, since this client
    genuinely cannot do it. A handler that throws is contained for the same
    reason: the next command, and the tick this rides on, are not its to take
    down.
    """
    ran = []
    for c in sorted(commands or [],
                    key=lambda c: _COMMAND_ORDER.get((c or {}).get("command"),
                                                     5)):
        fn = handlers.get((c or {}).get("command"))
        if not fn:
            continue
        try:
            fn()
        except Exception:
            continue
        ran.append(c.get("command"))
    return ran




# ─── The System Log, from a Client's side ─────────────────────────────────────

# A Client does both: it writes every action to a rolling file of its own and it
# ships the same entries to the server. Both, deliberately - the server's copy
# is the one the Admin reads and the only place all three components sit on one
# timeline, and the local file is what an engineer's laptop can still say about
# itself when the server cannot be reached, which is the reason applaunch.py
# already writes launch.err.log. Neither is trusted to match the other: the
# server stamps its own clock and the source address it saw, and the local file
# is this machine's own record.
#
# Here rather than in each app, for the reason everything else in this module is
# here (rule 10): three copies of a shipping loop is three places a change has to
# be made and be right. What each app decides to log stays in the app - that is
# what a command's handler is to `obey`, and an action is not a transport.

LOG_PATH = os.path.join(BASE_DIR, "client.log")
LOG_PATH_PREV = LOG_PATH + ".1"

# The bound on the local file. One generation kept, so this machine spends at
# most twice this on the log however long it runs - a laptop is not where an
# unbounded file should be discovered.
LOG_MAX_BYTES = 256 * 1024

# Matches _LOG_FIELD_MAX / _LOG_DETAIL_MAX / _LOG_BATCH_MAX in server.py, which
# caps every one of these on arrival because that endpoint is unauthenticated.
# Truncated here as well for the reason CHECKIN_MAX is: a shortened line is
# worth more than an entry the server trimmed differently from the local file.
LOG_FIELD_MAX  = 120
LOG_DETAIL_MAX = 400
LOG_BATCH      = 50

# What may wait in memory for a server that is not answering. The local file
# already holds everything within its own bound, so the oldest queued entry is
# what gives way - a queue that grew without limit would be this module's
# contribution to the outage it is trying to describe.
LOG_QUEUE_MAX = 200

_log_lock  = threading.Lock()
_log_queue = []


def _log_data_json(data):
    """`data` as the bytes the server will store, or None where it cannot be.

    The server's own rule, kept identical here (`server_log._log_event`):
    `sort_keys` so two entries carrying the same facts are the same bytes,
    and dropped whole to None rather than cut where it does not fit, because
    a truncated JSON document is not a smaller JSON document - it is not JSON
    at all. Held on this side as well as that one for the reason every other
    cap in this module is held twice: an entry the server trimmed differently
    from the local file is two records of one action that disagree, and the
    local file is what a laptop can still say about itself.

    The entry is never refused for its `data`; only the `data` is.
    """
    if data is None:
        return None
    try:
        encoded = json.dumps(data, sort_keys=True)
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > LOG_DETAIL_MAX:
        return None
    return encoded


def log_event(event, detail="", level="info", actor="", data=None):
    """Record one action: to this machine's file, and to the shipping queue.

    Never raises. Every caller is an app in the middle of doing something else -
    submitting a Transaction, answering a popup, starting up - and a log line is
    never worth what it was called from. An unwritable directory, a full disk
    and a locked file all end here silently, which is the same promise
    `_log_event` makes on the server.

    `data` is a dict of the facts behind the line, beside the free-text
    `detail` rather than instead of it, and reaches the server's own `data`
    column as a sixth key of the shipped entry (#247/072). Additive in both
    directions and with no flag deciding it: a server from before #071 reads
    named keys and ignores one it does not know, and a client from before
    this ticket sends none and the column is NULL. In this machine's own file
    it is one trailing field on the same line, so `client.log` stays one line
    per entry however much structure an entry carries.

    Answers whether the entry was taken, the way `_log_event` does, and for the
    one caller that has something to do with the answer: `report_update_result`
    below is shipping a fact that exists nowhere else and deletes the file it
    read it out of, so it has to be able to tell a queued entry from one that
    went nowhere. Every other caller ignores it, as it should - an action is
    not undone because the line about it could not be written.
    """
    try:
        entry = {"ts":     time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "event":  str(event or "")[:LOG_FIELD_MAX],
                 "detail": str(detail or "")[:LOG_DETAIL_MAX],
                 "level":  str(level or "info"),
                 "actor":  str(actor or "")[:LOG_FIELD_MAX]}
        # Serialised once: the text goes on the local line, and the dict
        # itself is what ships - the server serialises its own copy, so a
        # payload that carried the text would arrive as a JSON string
        # holding a document rather than as the document. A `data` this
        # could not serialise or could not fit ships as None, so the two
        # copies of the entry agree about it being absent.
        data_json = _log_data_json(data)
        entry["data"] = data if data_json is not None else None
        line = "%s  %-5s  %s  %s%s%s" % (entry["ts"], entry["level"].upper(),
                                         entry["event"],
                                         entry["detail"],
                                         "  [%s]" % entry["actor"]
                                         if entry["actor"] else "",
                                         "  %s" % data_json
                                         if data_json is not None else "")
        with _log_lock:
            _log_queue.append(entry)
            del _log_queue[:max(0, len(_log_queue) - LOG_QUEUE_MAX)]
            _roll_log()
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return True
    except Exception:
        return False


def _roll_log():
    """Start a new file once the current one is full, keeping one generation.

    Called with `_log_lock` held. `os.replace` rather than a remove and a
    rename: on Windows the remove is a second moment in which the previous
    generation is gone and the current one is not yet in its place.
    """
    try:
        if os.path.getsize(LOG_PATH) < LOG_MAX_BYTES:
            return
    except OSError:
        return          # no file yet, which is the ordinary first call
    try:
        os.replace(LOG_PATH, LOG_PATH_PREV)
    except OSError:
        pass


def ship_log(server_url, cfg, save, component, timeout=6):
    """Hand what is queued to the server. Returns the number it accepted.

    Rides the tick that already checks in, and returns 0 for every failure the
    way `checkin` returns []: a server that cannot be reached is the ordinary
    state of a laptop away from the office, not something to report - and the
    local file has the entries either way.

    A batch the server *answered* is dropped whichever answer it gave. A refusal
    retried is the same refusal, and the alternative is a client that ships the
    same rejected batch on every tick for ever and never gets to the entries
    behind it. Only an unanswered batch is kept, which is exactly the case that
    comes back on its own.
    """
    if not server_url:
        return 0
    with _log_lock:
        batch = _log_queue[:LOG_BATCH]
    if not batch:
        return 0
    try:
        r = api("post", "%s/clients/log" % server_url,
                json={"client_id": client_id(cfg, save),
                      "component": component,
                      "entries": batch},
                timeout=timeout)
    except Exception:
        return 0
    with _log_lock:
        del _log_queue[:len(batch)]
    if not r.ok:
        return 0
    try:
        return int(r.json().get("accepted") or 0)
    except Exception:
        return 0


# ─── Asset lookup ─────────────────────────────────────────────────────────────

# Fallback asset types. The server is the source of truth (rule 2) - every
# client loads GET /asset_types at startup - and this is only what a client
# shows when it has never learnt the register's own answer: not merely
# unreachable, since the on-disk cache below is what an unreachable server
# leaves standing instead. It lived in storekeeper_app.py alone as
# ASSET_TYPES; a second client asking the same question is why it moved here
# (rule 10).
ASSET_TYPES = ["Laptop", "Desktop", "Mobile", "Tablet", "Screen", "UPS", "Server",
               "Cisco Phone", "Printer", "Scanner", "Switch"]

ASSET_CACHE_PATH = os.path.join(BASE_DIR, "asset_cache.json")


def _load_asset_cache():
    try:
        if os.path.exists(ASSET_CACHE_PATH):
            with open(ASSET_CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_asset_cache(d):
    try:
        with open(ASSET_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def cached_asset_types():
    """The asset types this installation last actually saw, with no network
    call - what a window open before the first fetch has answered should
    show, and what a server that has never answered leaves an app showing for
    good. Falls back to ASSET_TYPES only when nothing has ever been cached; a
    caller wanting a live answer calls fetch_asset_types() instead.
    """
    cached = _load_asset_cache().get("asset_types")
    return list(cached) if cached else list(ASSET_TYPES)


def fetch_asset_types(server_url, timeout=5):
    """GET /asset_types, refreshing the on-disk cache on success.

    A convenience only - rule 6 is enforced on the server regardless of what
    this returns, so a stale answer here never lets an unregistered asset
    through, it only changes what a Type dropdown offers. A fetch that
    succeeds replaces the cache and is returned; one that fails - the server
    unreachable, or answering with no types in it - leaves the cache exactly
    as it was and returns cached_asset_types() instead, the shape
    sync_server_cert uses: a two-day-old list is more useful than falling all
    the way back to ASSET_TYPES.
    """
    try:
        r = api("get", "%s/asset_types" % server_url, timeout=timeout)
        if r.ok:
            types = r.json().get("asset_types")
            if types:
                # Read-modify-write, for the reason `_save_server_cfg` is one:
                # the models below live in this same file, and writing a fresh
                # dict here would drop every one of them on the next type
                # fetch - which is the tick this app already runs.
                cache = _load_asset_cache()
                cache["asset_types"] = list(types)
                cache["fetched_at"] = time.time()
                _save_asset_cache(cache)
                return list(types)
    except Exception:
        pass
    return cached_asset_types()


def _model_key(for_type):
    """The cache key one Asset Type's models are kept under.

    Folded to lower case for 027's reason and the register's own: a sheet
    holding `Laptop` answers `LAPTOP` too, so two spellings of one type must
    not become two cache entries that disagree. The empty key is every model
    this register holds, which is what an unnarrowed fetch answers with.
    """
    return (for_type or "").strip().lower()


def cached_asset_models(for_type=""):
    """The models this installation last actually saw for one Asset Type.

    No network call, so it is what a window open before any fetch has been
    answered shows, and what an app offers for good against a server that
    cannot be reached. **There is no baked-in fallback here, unlike
    `cached_asset_types`**: an Asset Model is offered rather than enforced -
    the field is editable and a model nobody has bought before has to be
    typeable - so nothing is lost by offering an empty list, while a made-up
    one would put models in front of a storekeeper that this register has
    never held.
    """
    cache = _load_asset_cache().get("asset_models")
    if not isinstance(cache, dict):
        return []
    got = cache.get(_model_key(for_type))
    return list(got) if isinstance(got, list) else []


def fetch_asset_models(server_url, for_type="", timeout=4):
    """GET /asset_models[?type=...], refreshing the on-disk cache on success.

    The client half of G2, and the same shape `fetch_asset_types` has: a fetch
    that succeeds replaces this type's entry and is returned, one that fails
    leaves the cache exactly as it was and answers out of it, so a client
    shows the last real answer rather than nothing the moment the server is
    unreachable.

    **An empty list is an answer and is cached as one**, unlike the types
    fetch above, which treats an empty answer as a failure: a register with no
    model recorded against a type yet is an ordinary state - it is what the
    Server GUI's own combobox shows - where a register with no *types* at all
    is a server that has not answered properly.

    The timeout is 4s rather than 5, the one `lookup_asset` uses, because this
    is called on the Tk thread from a window somebody is typing into.
    """
    try:
        r = api("get", "%s/asset_models" % server_url,
                params={"type": for_type} if for_type else None,
                timeout=timeout)
        if r.ok:
            models = r.json().get("asset_models")
            if isinstance(models, list):
                cache = _load_asset_cache()
                known = cache.get("asset_models")
                if not isinstance(known, dict):
                    known = {}
                known[_model_key(for_type)] = list(models)
                cache["asset_models"] = known
                cache["models_fetched_at"] = time.time()
                _save_asset_cache(cache)
                return list(models)
    except Exception:
        pass
    return cached_asset_models(for_type)


def lookup_asset(server_url, q, timeout=4):
    """GET /lookup?q=<value> - the identifier a storekeeper just typed or
    scanned, checked against the register right now.

    A single query, never the cached list above: rule 6 is enforced on the
    server and this is what asks it, so the answer has to be live. Raises
    like any other api() call rather than swallowing one - Submit queues a
    Transaction on a timeout, the debounced auto-fill goes quiet, and Bulk
    Scan marks the row not found, each staying the caller's own decision.
    """
    return api("get", "%s/lookup" % server_url, params={"q": q}, timeout=timeout)


def origin_suffix(t):
    """` (auto)` for a decided Transaction that was auto-approved, and "" for
    desktop, NULL and a row from a server that predates 106 and sends no
    `origin` at all."""
    o = t.get('origin')
    return " (%s)" % o if o in ("auto",) else ""


# ─── Update state ─────────────────────────────────────────────────────────────

MAX_LATER = 5                       # postpones allowed before the update is forced
UPDATE_STATE_PATH = os.path.join(BASE_DIR, "update_state.json")


def _ver_tuple(s):
    try:
        return tuple(int(x) for x in str(s).strip().split("."))
    except Exception:
        return (0,)


def _load_update_state():
    try:
        if os.path.exists(UPDATE_STATE_PATH):
            with open(UPDATE_STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_update_state(d):
    try:
        with open(UPDATE_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


# ─── The previous update's outcome ────────────────────────────────────────────

# `client_update.py`'s phase two is a separate process that imports nothing of
# ours on purpose - it is overwriting `common.py` and `ui_kit.py` while it runs
# - so it cannot call `log_event`, and there is no app left holding a queue to
# put an entry in either. What it can do is leave a file. This is the other side
# of that handover: the app that starts next reads it, writes the System Log
# entry that could not be written at the time, and deletes it.
#
# Here rather than in each client for the reason everything else in this module
# is (rule 10): the file, the three event names and the wording are one fact,
# and two copies of it is two spellings of what an update did.
#
# **The honest gap**, written down rather than papered over: an update that
# rolls back *and still fails to start the app* ships nothing, ever. There is no
# app to read the file and no channel that does not go through one. The only
# evidence is `update.log` on that machine and that installation going red in
# the Server GUI's Connected Clients, which is what somebody has to act on.

UPDATE_RESULT_PATH = os.path.join(BASE_DIR, "update_result.json")

# What the applier may say, and what each is worth in the System Log. An
# outcome this build does not know is not an event - a file naming one is
# cleared rather than reported, since left behind it would be read again on
# every start for ever.
UPDATE_RESULT_EVENTS = {
    "applied":     ("update.applied",     "info"),
    "failed":      ("update.failed",      "error"),
    "rolled_back": ("update.rolled_back", "error"),
}


def _clear_update_result():
    """Take the handover file away. Never raises - it is already best effort."""
    try:
        os.remove(UPDATE_RESULT_PATH)
    except OSError:
        pass


def report_update_result(actor=""):
    """Ship what the applier wrote down about the update that brought us here.

    Called once at startup by each client, beside `app.started`. Answers the
    event name it wrote, or "" where there was nothing to say - which is the
    ordinary case, an update being a handful of times a year.

    The entry carries **both versions and the digest of the package**, so a row
    in the System Log says which build replaced which and which published
    package it was: a version number alone cannot tell two packages carrying it
    apart, and the digest is the number `GET /version` published and the
    updater checked the download against.

    The file is deleted only once the entry has actually been **queued** - that
    is what `log_event`'s answer is for - so an outcome is not lost to a log
    write that failed and is not reported twice either.

    Never raises, for `log_event`'s reason: nothing on the startup path of a
    client is worth a Transaction not being confirmed.
    """
    try:
        with open(UPDATE_RESULT_PATH, encoding="utf-8") as f:
            res = json.load(f)
        if not isinstance(res, dict):
            raise ValueError("not an object")
    except Exception:
        # No file is the ordinary state; one that cannot be read at all is a
        # half-written handover, and there is nothing in it to report.
        if os.path.exists(UPDATE_RESULT_PATH):
            _clear_update_result()
        return ""

    event, level = UPDATE_RESULT_EVENTS.get(str(res.get("outcome", "")),
                                            ("", ""))
    if not event:
        _clear_update_result()
        return ""

    detail = "%s -> %s" % (res.get("from_version") or "?",
                           res.get("to_version") or "?")
    if res.get("detail"):
        detail += "  ·  %s" % res["detail"]
    if res.get("sha256"):
        detail += "  ·  sha256 %s" % str(res["sha256"])[:16]
    if log_event(event, detail, level=level, actor=actor):
        _clear_update_result()
        return event
    return ""


# ─── Client-local config file ──────────────────────────────────────

def load_config(path, defaults):
    """The file at `path` read over `defaults`, leaving `defaults` where it is.

    The copy is taken first and the file goes into the copy. Updating
    `defaults` itself and copying afterwards reads the same way and is not: it
    writes the file's values into the dict the caller keeps as its record of
    what a default is, so the first read of a stale config.json destroys that
    record for the rest of the run - and for the Storekeeper's own
    `storekeeper_name`, the one default that is also a fallback read back
    later, that is how a name of spaces once ended a run attributing every
    System Log entry to " (Storekeeper)". Both clients carried this function
    under two names over the same four lines; the path and the defaults were
    the only thing that ever differed between them, so those are what moved
    here as arguments rather than a flag - the way `server_cert.py` takes its
    paths from `server.py` rather than resolving its own.
    """
    cfg = dict(defaults)
    if os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    return cfg


def save_config(path, cfg):
    """Write `cfg` to `path` as indented JSON - the other half of `load_config`."""
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)


# ─── The client package check ──────────────────────────────────────

def _has_client_package(version_payload, app_key):
    """True when `GET /version`'s answer holds a source zip for `app_key`.

    client_packages is additive, so a server built before it says nothing and
    a client goes on offering the installer through the browser exactly as it
    did. Identical in both clients before this, keyed only by which app's own
    UPDATE_APP_KEY the caller already knows - that is the one thing that ever
    differed, so it is the one thing passed in rather than copied.
    """
    entry = (version_payload.get("client_packages") or {}).get(app_key)
    return bool(entry and entry.get("path"))


# ─── The rounded "A" badge ──────────────────────────────────────

def _mark(parent, bg, accent, size=30, radius=9, pt=13):
    """The rounded "A" badge shared by the Notifier's and the Storekeeper's
    header bars. Canvas items are not widgets, so it draws itself again on a
    theme change rather than being reached by the walk.

    `bg` and `accent` come in as values, the way `Pill`'s constructor already
    takes its own, rather than this file reaching into the caller's globals
    for `BG`/`ACCENT`; a switch remaps the stored values through
    `ui_kit.remap`, the same way `Pill._retint` does. This is the one place in
    this file that imports tkinter, and it does so inside the function rather
    than at module top - a client's transport layer has no business needing a
    display to import, any more than it has business opening a window - so the
    import is deferred the way `ui_kit.py`'s own tkinter uses are.
    """
    import tkinter as tk
    cv = tk.Canvas(parent, width=size, height=size, bg=bg,
                   highlightthickness=0)

    def draw():
        cv.delete("all")
        cv.configure(bg=bg)
        ui_kit.round_rect(cv, 1, 1, size - 1, size - 1, radius, fill=accent,
                          outline="")
        cv.create_text(size / 2.0, size / 2.0 + 1, text="A", fill="white",
                       font=ui_kit.font("emph", size=pt))

    def _retint(rev, new):
        nonlocal bg, accent
        bg = ui_kit.remap(bg, rev, new)
        accent = ui_kit.remap(accent, rev, new)
        draw()

    draw()
    cv._retint_hook = _retint
    return cv
