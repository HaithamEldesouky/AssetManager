"""
Asset Manager -- is there an IIS in front of this process, and what has it bound.

Five functions answered one question from two files under two names, and #243
brings them together: `_iis_host`, `_port_serves_tls` and `_iis_tls_bound` sat
in `server.py`, and `_bind_cert_command` in `server_cert.py` beside a
certificate lifecycle it is no part of - it moves the IIS binding, not a
`.pem` pair. `_remote_tls_ok`, `server.py`'s own "is this request encrypted"
answer, asks `_iis_tls_bound` and moves with it for the same reason
`server_cert.py`'s own module docstring gives: one concern, one entry point,
the rest of the file not reaching into it.

Two tickets in the same queue built on this: 069 added the second
elevated command, `_bind_port_command`, and 070 the third, `_recycle_pool_command`.
Neither is about certificates, so `server_cert.py` was the wrong home,
and `server.py` is what #224-#229 have been emptying - this is that shape
again.

**It owns no paths of its own.** `BASE_DIR`, `PORT` and `IIS_STATE_PATH` are
`server.py`'s, resolved there once against the install directory and the
server's own config, and handed over by `bind()` at import - a second
derivation here is the install directory being decided twice, which is the
failure CODING_STANDARDS "Paths" stands in front of. `IIS_STATE_PATH` stays an
`os.path.join(BASE_DIR, ...)` one-liner in `server.py` rather than moving
whole, for `server_archive.py`'s reason (see its row in
`docs/reference/architecture.md`): computed here instead it would drop out of
`tools/cascade-audit.py`'s `BESIDE_MODULES` scan, which reads module-level
joins in `server.py` to check a name written beside the app is tracked or
ignored.

Headless-safe: nothing here draws, so `server.py` imports it at module level.
It is not routeless the way `server_archive.py` and `server_lookup.py` are -
`_remote_tls_ok` reads Flask's `request` directly, because that is the one
name the moved code was already written against and a second spelling of "is
this request secure" is exactly what rule 10 is about. No `@app.route`,
`@door` or `jsonify` all the same: nothing here is a route, and no route moved
with it.
"""

import json
import os
import socket
import ssl
import threading
import time

from flask import request

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there and
# here as one thing.
BASE_DIR = None
PORT = None
IIS_STATE_PATH = None


def bind(*, base_dir, port, iis_state_path):
    """Give this module the server's paths, at import. See the module
    docstring for why none of these is derived here.
    """
    global BASE_DIR, PORT, IIS_STATE_PATH
    BASE_DIR = base_dir
    PORT = port
    IIS_STATE_PATH = iis_state_path


def _iis_host():
    """What IIS recorded about this install, or None if IIS does not host it.

    The presence of iis.json is the whole signal, and it is the same one
    tools\\update.ps1 reads to decide which of the two hosts to stop. Asking
    IIS itself would need the WebAdministration module and an elevated
    console, and this process is neither; a second signal would be a second
    answer to a question that already has one.

    Missing, unreadable, not JSON, or JSON that is not an object all mean the
    same thing and mean it quietly: not IIS. A server that has never met
    install-iis.ps1 has to behave exactly as it did before this existed, and
    a file somebody corrupted is not a reason to refuse to draw a window.

    Decoded utf-8-sig, and it stays that way. install-iis.ps1 writes this
    file without a BOM now, but until 054 it wrote it with
    Set-Content -Encoding UTF8, which under Windows PowerShell 5.1 means
    UTF-8 *with* a BOM - the trap tools/cascade-audit.py reads package
    manifests around for the same reason. Fixing the writer rewrites nothing
    already on disk: every machine installed before that keeps its BOM until
    somebody re-runs the installer. A plain open() decodes that BOM as cp1252
    and raises, and this function would then answer "not IIS" on every one of
    those machines, which is the one wrong answer it can give. utf-8-sig
    reads a file without a BOM correctly too, so it is right on both sides of
    that change.
    """
    try:
        with open(IIS_STATE_PATH, encoding="utf-8-sig") as f:
            state = json.load(f)
    except Exception:
        return None
    return state if isinstance(state, dict) else None


def _is_iis_served():
    """Is this process currently being served by IIS via HttpPlatformHandler?

    IIS's HttpPlatformHandler launches this process (with the 'serve' entry
    point) and assigns it a port via the %HTTP_PLATFORM_PORT% environment
    variable. That variable is set whether or not iis.json exists - it is
    HttpPlatformHandler's doing, not install-iis.ps1's - so this is True on
    every IIS-fronted process, the 069 bind-port.ps1 flow included.

    Returns True if currently being served by IIS, False otherwise.
    """
    return os.environ.get("HTTP_PLATFORM_PORT") is not None


def _iis_served_undetected():
    """Is IIS serving this process without install-iis.ps1 having run?

    True only when HttpPlatformHandler launched this process (`_is_iis_served`)
    and iis.json is missing (`_iis_host` is None) - IIS set up by hand, so
    nothing recorded which site or app pool owns the binding. That is the one
    case where a port change must be refused: the 069 bind-port.ps1 flow
    (iis.json present) binds a new site beside the old one, hands the new port
    to clients through /health's next_port, and removes the old site once
    they have moved - a port change there is exactly how a rebind is meant to
    happen, and must behave as it did before `_is_iis_served` existed.
    """
    return _is_iis_served() and _iis_host() is None


# What a TLS probe of this machine's own port last answered, and when it was
# taken. Read and written under the lock beside it: _iis_tls_bound is asked on
# every remote request, and Flask serves those on threads of their own.
_TLS_PROBE = [None, 0.0]
_TLS_PROBE_LOCK = threading.Lock()
_TLS_PROBE_TTL = 60.0


def _port_serves_tls():
    """Does the port this install is served on answer a TLS handshake?

    The machine's own answer to the question iis.json only keeps a record of,
    and the reason it is asked at all is that the record has one writer:
    `cert_thumbprint` is written by tools\\install-iis.ps1 and by nothing else,
    so a certificate bound in IIS Manager, bound after that script ran, or
    bound to a site it never ran against leaves the key empty while the site
    in front of this process is serving https.

    It is a handshake and nothing more - a connection is opened, TLS is
    negotiated, the socket is closed. No request is sent, no credential
    crosses it, nothing is read back, and what the certificate says is never
    examined, which is why the context verifies nothing: the question is
    whether this port speaks TLS at all, and a certificate this process would
    refuse to verify is still a certificate being presented over a connection
    somebody encrypted. That is not rule 1 turned off - rule 1 is a *client*
    deciding whether to trust a server, and this is a server asking what its
    own port is doing, which is the distinction Invoke-PinnedRequest in
    tools\\_deploy.ps1 is written around.

    Cached for `_TLS_PROBE_TTL`, because `_remote_tls_ok` asks this on every
    remote request and a handshake per request is a handshake per request. A
    minute is short enough that a binding made while the console is open is
    picked up without a restart, and long enough to cost nothing.

    Loopback, and 127.0.0.1 rather than this machine's name, for the reason
    the liveness probe already connects there: what is being asked about is
    the listener on this box and not the route to it.
    """
    now = time.monotonic()
    with _TLS_PROBE_LOCK:
        answer, taken = _TLS_PROBE
        if answer is not None and now - taken < _TLS_PROBE_TTL:
            return answer
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection(("127.0.0.1", PORT), 1.5) as raw:
            with ctx.wrap_socket(raw, server_hostname="localhost"):
                answer = True
    except Exception:
        answer = False
    with _TLS_PROBE_LOCK:
        _TLS_PROBE[0] = answer
        _TLS_PROBE[1] = time.monotonic()
    return answer


def _iis_tls_bound():
    """Is IIS terminating TLS in front of this process?

    `iis.json` is the record `install-iis.ps1` left of what it bound and
    `cert_thumbprint` is the certificate it bound to the site's port, which is
    the cheap half of the answer: a thumbprint there is that script having put
    a certificate on the site's port itself.

    An empty one is not the other half, and that is what #185 is. The key has
    exactly one writer, so a certificate bound in IIS Manager, bound after
    that script ran, or bound to a site it never ran against leaves it empty
    over a site serving https - and four surfaces then said the opposite of
    what the operator could see, out of one wrong record: the banner read HTTP
    over an HTTPS site, the tray beside it said the same, the liveness probe
    asked a TLS listener for `/stats` over plain `http://` and captioned a
    healthy server NOT RESPONDING, and `_remote_tls_ok` refused every Remote
    Admin knock `insecure`, which is what made the notification rules and the
    Engineers and Connected Clients panels look broken. So where the record
    says nothing the machine is asked instead, through `_port_serves_tls`:
    the port either answers a handshake or it does not, whoever bound it.

    The record is still asked first, and not only because it is cheaper - a
    thumbprint is what this install did, where a handshake is what the box is
    doing, and the first of those cannot be wrong about the second.

    Two callers and one answer, which is the whole of why it is a function
    rather than two lines in each. `_remote_tls_ok` asks it because a
    capability password is never accepted over plain `http://`, and `run_gui`
    asks it because under IIS this process binds no listener at all:
    `ssl_enabled` in `server_config.json` is written by the Server GUI's own
    SSL Certificate install and by nothing else, so an install whose
    certificate was bound by `install-iis.ps1` reads false there while the
    site serves TLS. That is #176's half of this, and the paragraph above is
    why it was not the whole of it: both callers were then asking one
    function that was reading one key nearly nothing writes.

    Neither pem file is consulted here, and that is the point rather than an
    omission: under IIS the private key is in `LocalMachine\\My`, and where
    the certificate came from `-PfxPath` or `-CertThumbprint` there is no
    `ssl_key.pem` beside the server at all - that script writes the public
    half on every path and the key on the `-SelfSigned` path alone. Asking
    for a file that correctly is not there is what the GUI was doing.
    """
    iis = _iis_host()
    if iis is None:
        return False
    if (iis.get("cert_thumbprint") or "").strip():
        return True
    return _port_serves_tls()


def _bind_cert_command(install_dir=None):
    """The elevated command that moves the IIS binding, as a list. C4.

    Built here rather than in the window so that what an Admin is shown when
    the elevation is refused is the same string that would have been run -
    two spellings of one command is exactly how somebody ends up pasting a
    line that does nothing and reporting that the cutover did not work.

    `tools\\bind-cert.ps1` (P3) is the elevated half by design: it imports the
    install directory's own pair and rebinds the site to it, and writes no
    `iis.json` of its own. `install-iis.ps1` would do it too and would also
    recreate the site, rewrite `web.config`, re-grant ACLs and ask questions -
    side effects nobody asked for when the job is to swap a certificate.
    """
    root = install_dir or BASE_DIR
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", os.path.join(root, "tools", "bind-cert.ps1"),
            "-InstallDir", root]


def _bind_port_command(port, install_dir=None):
    """The elevated command that moves the IIS binding to `port`, as a list.

    Beside `_bind_cert_command` and for exactly its reason: what an Admin is
    shown when the elevation is refused has to be the same string that would
    have been run, or somebody pastes a line that does nothing and reports
    that the port did not move.

    `tools\\bind-port.ps1` (ADR-0021) is the elevated half. Under IIS the port
    is the site binding, and this process is the app pool identity: it cannot
    touch a binding, a firewall rule or an app pool, so the console saves the
    number and spawns something that can. `install-iis.ps1` would move the
    port too and would also recreate the site and the app pool, rewrite
    `web.config`, re-grant ACLs and ask questions on an interactive run - and
    it takes the old binding away in the same breath, where the whole point
    of the move is the window in which both ports answer and every online
    client records the new one as `next_port`.

    `-Grace` is left off rather than passed: the script's own default is the
    number of client ticks this fleet is worth waiting for, and a copy of it
    here would be a second answer to a question that already has one.
    """
    root = install_dir or BASE_DIR
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", os.path.join(root, "tools", "bind-port.ps1"),
            "-InstallDir", root, "-Port", str(port)]


def _recycle_pool_command(pool=None):
    """The elevated command that recycles this install's app pool, as a list.

    Under IIS this process **is** the app pool, so the one restart it can ask
    for is the one thing it cannot perform: `Restart-WebAppPool` needs an
    administrator and this identity is not one. Beside `_bind_cert_command` and
    `_bind_port_command` for their reason - what an Admin is shown when the
    elevation is refused has to be the string that would have run, or somebody
    pastes a line that does nothing and reports that nothing restarted.

    It is what the console restarts with under IIS instead of `os.execv`, which
    restarts the **GUI process** and leaves the site serving out of a pool that
    has read nothing since it started - a monitor window blinking while every
    answer stays stale. `tools\\bind-port.ps1` already ends on this same call
    for the same reason, and `tools\\update.ps1` cycles the pool itself.

    A `-Command` rather than a `-File`: there is no script here to spawn, the
    act being one cmdlet against a name. The name is `app_pool` out of
    `iis.json`, which `install-iis.ps1` wrote and nothing else writes, and a
    single quote in it is doubled the way PowerShell escapes one.

    **None where nothing is recorded**, which is not the same as a command that
    would fail: an install whose `iis.json` predates the key, or was written by
    hand, has no pool name anywhere for this to guess at, and the caller owes
    the Admin "recycle it yourself" rather than a line that names an empty
    pool. `bind-port.ps1` says exactly that in its own step 5.
    """
    name = pool if pool is not None else (_iis_host() or {}).get("app_pool")
    name = str(name or "").strip()
    if not name:
        return None
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", "Restart-WebAppPool -Name '%s'" % name.replace("'", "''")]


def _remote_tls_ok():
    """Is this request arriving over a connection somebody encrypted? R1.

    A capability password is never accepted over plain `http://`, which is the
    ticket's own non-negotiable and the sharpest thing about the remote channel:
    the credential is replayed on every call, so one plaintext request hands it
    to anybody on the network for good.

    Two ways for that to be true and this server can see both of them:

    * `request.is_secure` - this process bound the listener itself and is
      serving TLS from `ssl_cert.pem`.
    * IIS in front of it. Under HttpPlatformHandler (ADR-0001) TLS ends at the
      site and the hop into this process is loopback HTTP, so `is_secure` is
      False for every genuinely encrypted request - answering off it alone
      would refuse the whole supported deployment. `iis.json` is the record
      `install-iis.ps1` left of what it bound, `cert_thumbprint` being the
      certificate it bound to the site's port, and it is the same file
      `_iis_host` already answers the banner's question out of.

    An `iis.json` with no thumbprint in it is not a refusal on its own since
    #185: that key has one writer, so a certificate bound any other way leaves
    it empty over a site that is serving https, and the port is asked for a
    handshake before this door is shut. That half is `_iis_tls_bound`, which
    the Server GUI's
    banner and liveness probe ask as well - one question with two answers in
    one file is what rule 10 is about, and the copy that was wrong there is
    the one an operator reads.
    """
    try:
        if request.is_secure:
            return True
    except Exception:
        pass
    return _iis_tls_bound()
