"""
Asset Manager — the server's certificate lifecycle.

The phases of a rotation (ADR-0020) and the readers around them: staging a
pair bound to nothing (C1), pushing it to every Client (C3), counting who has
not collected it, cutting over (C4), and exporting the public half (C5).

Lifted out of `server.py` by #206 unchanged. It sat in the middle of the
Server GUI block while being no part of it - it imports no tkinter and builds
no widget - and two routes reach into it from above (`GET /clients` and
`POST /clients/push_cert`). Lifting the GUI out around it would have made
those routes import the window; this comes out first, and alone.

Headless-safe: nothing here draws, so `server.py` imports it at module level.

**It owns no paths of its own.** `BASE_DIR` and the four certificate paths are
`server.py`'s, resolved there once against the install directory, and handed
over by `bind()` at import - a second derivation here is the install directory
being decided twice, which is the failure CODING_STANDARDS "Paths" stands in
front of. The helpers it calls come the same way, because `server.py` runs as
`__main__` under `applaunch`'s `runpy.run_path`: importing it back would
execute the whole server a second time rather than reach the one running.

Three signatures carried one of those paths as a default - `_cert_fingerprint`,
`_stage_new_cert`, `_export_public_cert`. A default is bound when the function
is defined, which here is before `bind()` has run, so each takes `None` and
resolves it to the same path in its first line. Every caller sees what it saw.
"""

import base64
import hashlib
import io
import os
import socket
import time

# The elevated command that moves the IIS binding (C4) - server_iis.py's
# since #243, moved out beside _iis_host and _iis_tls_bound rather than
# staying here: none of the three is about a certificate, and 069 and 070
# add two more elevated commands to that module rather than this one.
from server_iis import _bind_cert_command

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there and
# here as one thing.
BASE_DIR = None
SSL_CERT_PATH = None
SSL_KEY_PATH = None
SSL_CERT_NEXT_PATH = None
SSL_KEY_NEXT_PATH = None
CERT_ROLLBACK_DIR = None
_admin_password_ok = None
_client_rows = None
_command_rows = None
_command_status = None
_iis_host = None
_log_event = None
_queue_command = None
_save_server_cfg = None


def bind(*, base_dir, ssl_cert_path, ssl_key_path, ssl_cert_next_path,
         ssl_key_next_path, cert_rollback_dir, admin_password_ok, client_rows,
         command_rows, command_status, iis_host, log_event, queue_command,
         save_server_cfg):
    """Give this module the server's paths and helpers. Called once, at import.

    Keyword-only and exhaustive: every name the moved code reads out of
    `server.py` is on this list, so what the two modules share is one
    signature to read rather than a search of the file.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that imports
    a second, and it gives each staged copy a `server_cert` of its own.
    """
    global BASE_DIR, SSL_CERT_PATH, SSL_KEY_PATH, SSL_CERT_NEXT_PATH
    global SSL_KEY_NEXT_PATH, CERT_ROLLBACK_DIR
    global _admin_password_ok, _client_rows, _command_rows, _command_status
    global _iis_host, _log_event, _queue_command, _save_server_cfg
    BASE_DIR = base_dir
    SSL_CERT_PATH = ssl_cert_path
    SSL_KEY_PATH = ssl_key_path
    SSL_CERT_NEXT_PATH = ssl_cert_next_path
    SSL_KEY_NEXT_PATH = ssl_key_next_path
    CERT_ROLLBACK_DIR = cert_rollback_dir
    _admin_password_ok = admin_password_ok
    _client_rows = client_rows
    _command_rows = command_rows
    _command_status = command_status
    _iis_host = iis_host
    _log_event = log_event
    _queue_command = queue_command
    _save_server_cfg = save_server_cfg


def _cert_to_pem(cert_path, key_path=None, pfx_password=None):
    """Convert cert (and key) to PEM bytes. Returns (cert_pem, key_pem)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key, load_der_private_key)

    ext = os.path.splitext(cert_path)[1].lower()

    if ext in ('.pfx', '.p12'):
        with open(cert_path, 'rb') as f:
            data = f.read()
        # Try provided password, then empty-string fallback (Windows exports
        # sometimes require b"" rather than None even when no password is set)
        pwd = pfx_password.encode('utf-8') if pfx_password else None
        last_err = None
        result = None
        for attempt_pwd in ([pwd] if pwd is not None else [None, b""]):
            try:
                result = pkcs12.load_key_and_certificates(data, attempt_pwd)
                break
            except Exception as e:
                last_err = e
        if result is None:
            # Last-resort fallback via pyOpenSSL (handles older/legacy PFX formats)
            try:
                from OpenSSL import crypto as _ossl
                _pfx = _ossl.load_pkcs12(data, pwd if pwd is not None else b"")
                cert_pem = _ossl.dump_certificate(_ossl.FILETYPE_PEM, _pfx.get_certificate())
                key_pem  = _ossl.dump_privatekey(_ossl.FILETYPE_PEM, _pfx.get_privatekey())
                return cert_pem, key_pem
            except Exception as oe:
                pass
            raise ValueError(
                "Cannot open PFX file.\n"
                "• If it has a password, enter it in the PFX Password field.\n"
                f"• Technical detail: {last_err}"
            )
        priv_key, cert_obj, _ = result
        if cert_obj is None:
            raise ValueError("No certificate found in PFX file.")
        if priv_key is None:
            raise ValueError("No private key found in PFX file — "
                             "make sure the PFX includes the private key.")
        cert_pem = cert_obj.public_bytes(serialization.Encoding.PEM)
        key_pem  = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )
        return cert_pem, key_pem

    # .crt / .cer / .pem — certificate only; key file required
    with open(cert_path, 'rb') as f:
        cert_data = f.read()
    try:
        x509.load_pem_x509_certificate(cert_data)
        cert_pem = cert_data
    except Exception:
        try:
            cert_obj = x509.load_der_x509_certificate(cert_data)
            cert_pem = cert_obj.public_bytes(serialization.Encoding.PEM)
        except Exception:
            raise ValueError("Cannot parse certificate — unsupported format.")

    if not key_path or not os.path.exists(key_path):
        raise ValueError("Private key file is required for .crt / .cer / .pem certificates.")
    with open(key_path, 'rb') as f:
        key_data = f.read()
    try:
        load_pem_private_key(key_data, password=None)
        key_pem = key_data
    except Exception:
        try:
            key_obj = load_der_private_key(key_data, password=None)
            key_pem = key_obj.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            )
        except Exception:
            raise ValueError("Cannot parse key file — unsupported format.")
    return cert_pem, key_pem


def _cert_fingerprint(path=None):
    """The SHA-256 fingerprint of the certificate at `path`, or None.

    Colon-separated uppercase hex, which is what openssl prints and what an
    admin can read down a phone. Taken from the file GET /cert serves rather
    than from whatever certificate IIS has bound: the question it answers is
    whether the certificate a Client pinned is the one it would be handed, and
    those stop being the same file the moment a binding moves on.

    The digest is over the DER bytes - the base64 between the PEM markers -
    because that is what every other tool fingerprints; hashing the file's
    text would produce a number that looks right and matches nothing. The
    first certificate in the file is the one measured: a chain's leaf comes
    first, and the leaf is what a Client is comparing.

    base64 and hashlib are already imported, so this needs no certificate
    library and cannot fail for want of one.
    """
    if path is None:
        path = SSL_CERT_PATH
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            pem = f.read()
    except OSError:
        return None
    head, tail = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    start = pem.find(head)
    end   = pem.find(tail, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    # validate=True, over a body with its line breaks taken out: a decode
    # that quietly skips whatever it does not recognise would answer a
    # corrupt file with a fingerprint, and a wrong fingerprint is worse than
    # none - it is the one thing here nobody can check against anything else.
    try:
        der = base64.b64decode("".join(pem[start + len(head):end].split()),
                               validate=True)
    except Exception:
        return None
    if not der:
        return None
    hexed = hashlib.sha256(der).hexdigest().upper()
    return ":".join(hexed[i:i + 2] for i in range(0, len(hexed), 2))


CERT_WARN_DAYS = 30
CERT_ERROR_DAYS = 7


def _cert_expiry(path=None):
    """Days left until the live certificate's `not_valid_after`, or None (#273).

    Reads `ssl_cert.pem` - the file `GET /cert` serves and every pinned
    Client is actually relying on - rather than the staged one at
    `SSL_CERT_NEXT_PATH`: that pair is bound to nothing yet (C1) and answers
    a different question. Returns `(days_left, not_valid_after)`, or
    `(None, None)` where there is no certificate to read, `cryptography` is
    not installed, or the file will not parse - `_cert_expiry_check` below
    is a background job and must never raise for want of one.
    """
    if path is None:
        path = SSL_CERT_PATH
    import datetime as _dt
    try:
        from cryptography import x509
    except ImportError:
        return None, None
    try:
        with open(path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        try:
            expires = cert.not_valid_after_utc
        except AttributeError:
            expires = cert.not_valid_after.replace(tzinfo=_dt.timezone.utc)
        now = _dt.datetime.now(_dt.timezone.utc)
        return (expires - now).days, expires
    except Exception:
        return None, None


def _cert_expiry_check():
    """Read the live certificate's expiry and warn as it approaches (#273).

    Called once a day, from `_cert_expiry_loop` below, itself started from
    `_start_background_jobs` beside `_log_retention_loop` and `_sync_loop`.
    **It only warns.** Staging and cutting over a certificate stay a thing
    an Admin does on purpose (ADR-0020) - moving the IIS binding needs the
    elevated script, and a job that rotated it unattended is half of a
    rotation with nobody watching the other half.

    From `CERT_WARN_DAYS` out this writes one `cert.expiry_warning`; from
    `CERT_ERROR_DAYS` out, one `cert.expiry_critical` instead of it - never
    both for the same day, since a certificate seven days out is not also
    thirty days out. Each call writes at most one row, and this is called
    once a day, which is what makes it 'one warn a day' rather than a
    dedup kept here beside it.
    """
    days_left, expires = _cert_expiry()
    if days_left is None:
        return
    detail = "%d day(s) left - expires %s" % (days_left,
                                               expires.date().isoformat())
    if days_left <= CERT_ERROR_DAYS:
        _log_event("cert.expiry_critical", detail, level="error")
    elif days_left <= CERT_WARN_DAYS:
        _log_event("cert.expiry_warning", detail, level="warn")


def _cert_expiry_loop():
    """Background job: check the live certificate's expiry daily (#273)."""
    while True:
        try:
            _cert_expiry_check()
        except Exception:
            pass
        time.sleep(86400)  # re-check daily


CERT_NEXT_DAYS = 365


def _cert_names():
    """The names a certificate minted on this machine must answer to.

    This machine's own identity rather than one deployment's literals, which
    is the bug `install-iis.ps1 -SelfSigned` already fixed: a certificate
    minted for `asset-server` on a machine that is not it asserts a SAN no
    client can match, urllib3 asserts the SAN regardless of `check_hostname`,
    and a client that pinned the file then fails closed with no way back.

    The address is read off the interface carrying the default route rather
    than out of `gethostbyname`, which answers 127.0.0.1 on a machine whose
    hosts file says so. The UDP socket binds nothing, sends nothing and needs
    nothing at the other end - it is asked which local address would be used,
    not to reach anything. Where it cannot answer, **no address is written at
    all**: an absent IPAddress SAN costs a client configured by address, where
    a wrong one costs every client there is.
    """
    names = []
    for n in (socket.gethostname(), socket.getfqdn(), "localhost"):
        if n and n not in names:
            names.append(n)
    addr = ""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))
            addr = probe.getsockname()[0]
        finally:
            probe.close()
    except Exception:
        addr = ""
    if addr and addr not in names:
        names.append(addr)
    return names


def _stage_new_cert(cert_path=None, key_path=None,
                    names=None, days=CERT_NEXT_DAYS):
    """Write a new self-signed pair beside the server, bound to nothing (C1).

    Phase one of a rotation (ADR-0020). **Nothing is bound and nothing is
    served**: the running server keeps presenting the certificate it has, and
    every client keeps working. Clients pin by file and fail closed against
    anything else (rule 1), so a rotation that begins by binding strands the
    whole fleet at once - the hourly `GET /cert` refresh included, that going
    over the connection the outgoing certificate verified - and ends with
    somebody walking to every laptop.

    Three details on the certificate itself matter and each fails silently if
    omitted, which is why they are written here the way `_devtools.py cert`
    writes them for a dev run: an **IPAddress** SAN, because a client may
    connect by address and urllib3 asserts the SAN even with `check_hostname`
    off; a **DNSName** SAN for every name this server answers to; and
    **CA:TRUE**, because OpenSSL 3 refuses a non-CA certificate as a trust
    anchor and a self-signed certificate is its own issuer.

    Takes paths and touches no Tk, so every refusal below is reachable by a
    gate - the split `_export_public_cert` and `_take_backup` are written in.
    **The live pair is never written by this**, asserted rather than assumed:
    the two names are one character apart from the two that strand a fleet.

    `cryptography` is guarded like every other optional dependency here: with
    none, this refuses naming what to do instead rather than the server
    failing to start over a button nobody has pressed.
    """
    if cert_path is None:
        cert_path = SSL_CERT_NEXT_PATH
    if key_path is None:
        key_path = SSL_KEY_NEXT_PATH
    import datetime as _dt
    import ipaddress
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        raise RuntimeError(
            "cryptography is not installed on this server, so a certificate "
            "cannot be generated here. Run tools\\install-iis.ps1 "
            "-SelfSigned on this machine, or install a certificate from a "
            "file below.")

    for staged, live in ((cert_path, SSL_CERT_PATH), (key_path, SSL_KEY_PATH)):
        if os.path.abspath(staged) == os.path.abspath(live):
            raise ValueError(
                "a generated certificate is never written over the live one: "
                "%s is what the listener is bound to and what every client "
                "has pinned." % live)

    names = [n for n in (names or _cert_names()) if n]
    if not names:
        raise ValueError("a certificate needs at least one name.")
    sans = []
    for n in names:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            sans.append(x509.DNSName(n))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(days=1))
            .not_valid_after(now + _dt.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                           critical=True)
            .sign(key, hashes.SHA256()))

    # Both bodies built before either is written: a pair half on disk is a
    # staged certificate with no key to bind it with, and the run that noticed
    # would be the cutover.
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption())
    with io.open(cert_path, "wb") as f:
        f.write(cert_pem)
    with io.open(key_path, "wb") as f:
        f.write(key_pem)
    return _cert_fingerprint(cert_path)


def _push_next_cert(issued_by="Admin (Server GUI)"):
    """Queue `trust_cert` for every Client. Returns (payload, status). C3.

    Phase two of a rotation, from the console's side. The staged certificate
    (C1) is on disk and bound to nothing; this asks every installation that has
    ever checked in to fetch it and add it to the file it pins, so that the
    cutover (C4) is a restart here rather than a visit to every laptop.

    Refused with no staged certificate at all - there would be nothing for the
    Clients to fetch, and a queue of commands that each answer "nothing staged"
    is a fleet of collected rows that mean nothing happened.

    **It queues for every Client rather than for the ones that are behind**,
    and that is a deliberate departure from how this reads at first. A Client
    reports the fingerprint of the **first** certificate in its pinned file
    (C2), and appending leaves the served certificate first, so a Client that
    has done exactly what it was told still reports the old value - the column
    beside this cannot see the append at all, and a count derived from it would
    read as a fleet status and be the opposite of one. What says who has
    answered is the **queue**: each row is `queued` until that machine checks
    in and `collected` afterwards, which is the fact this feature exists to
    surface. `_queue_command`'s duplicate guard then does the rest, refusing a
    second command while the first is still waiting and allowing a re-push once
    it has been collected - which is what a second rotation needs, and is safe
    because appending is idempotent on the Client.

    Every row goes through `_queue_command`, the one writer of the queue, so a
    push and a hand-queued command cannot mean different things by the same
    row. **The credential is the caller's** since #174, as it is there and for
    its reason: this is reachable from the console and from
    `POST /clients/push_cert`, and a password checked in here could only know
    about the first of the two. What it takes is the actor, which every row it
    queues and every `cert.pushed` it writes is then attributed to.
    """
    fp = _cert_fingerprint(SSL_CERT_NEXT_PATH)
    if not fp:
        return {"error": "No certificate is staged on this server",
                "code": "no_staged_cert"}, 409
    queued, waiting, failed = [], [], []
    for r in _client_rows():
        cid = r["client_id"]
        payload, status = _queue_command(cid, "trust_cert",
                                         issued_by=issued_by)
        if status == 201:
            queued.append(cid)
            # The fingerprint is what this entry adds over the
            # `client.command_issued` beside it: a push is read months later
            # against which certificate it was about, and a command name alone
            # cannot answer that.
            _log_event("cert.pushed", "%s  ->  %s" % (fp, cid),
                       actor=issued_by, level="warn")
        elif payload.get("code") == "already_queued":
            waiting.append(cid)
        else:
            failed.append(cid)
    return {"status": "pushed", "fingerprint": fp, "queued": len(queued),
            "already_waiting": len(waiting), "failed": len(failed),
            "clients": len(queued) + len(waiting) + len(failed)}, 200


def _clients_behind_staged():
    """How many installations have not yet been handed the staged certificate.

    Read off the **command queue** and never off `clients.cert_fingerprint`,
    for C3's reason turned around: a Client that has done exactly what it was
    told still reports the served certificate, because appending leaves that
    one first, so the Certificate column cannot see the append and a count from
    it would say the whole fleet is behind on the morning every machine has
    caught up. The queue is a fact this server observed - it handed the command
    over, in the same transaction as the check-in that took it - rather than
    one a client asserted.

    A Client with **no** `trust_cert` row at all counts as behind, which is the
    half that matters: it was never pushed to, or it was registered after the
    push, and it is the machine that fails closed on the restart. So does one
    whose row is still `queued` or has expired. Only `collected` is not behind.

    Returns (behind, total). Both, because the sentence an Admin is shown is a
    proportion: 0 of 12 and 0 of 0 are different situations, and the second is
    a server nobody has installed a client against yet.
    """
    rows = _client_rows()
    behind = 0
    for r in rows:
        cmds = [c for c in _command_rows(r["client_id"])
                if c["command"] == "trust_cert"
                and _command_status(c) == "collected"]
        if not cmds:
            behind += 1
    return behind, len(rows)


def _cut_over_cert(password=None, issued_by="Admin", authorised_as=None):
    """Make the staged certificate the one being served. Returns (payload,
    status). C4, ADR-0020, phase three.

    The whole of the danger in this system is in these few lines, and it is
    worth saying which part: **this is the moment a client that never trusted
    the staged certificate stops being able to reach this server at all**,
    including the hourly `GET /cert` refresh that would have repaired it (rule
    1). There is no server-side remedy for such a machine - somebody deletes
    its `ssl_cert.pem` and confirms the new fingerprint at the keyboard
    (ADR-0010) - which is exactly why the count above is put in front of the
    Admin before this runs rather than reported afterwards.

    It refuses where nothing is staged, and refuses where the staged
    certificate is **already** the one being served: the second is a cutover
    that has already happened, and doing it again would move a live pair into
    `cert_rollback\\` over the copy that is the way back from the first one.

    The live pair is copied aside **before** either file is replaced, and the
    directory is emptied first so exactly one generation is kept - which is a
    private key per generation, and the reason this is not `restore_aside\\`'s
    keep-everything shape. The certificate is replaced **before** the key: for
    the instant between the two writes the pair on disk disagrees, and a
    certificate without its key is a server that will not bind on the next
    start, where a key without its certificate is one that binds the *old*
    certificate under the new key's name. The first says so immediately.

    The System Log entry is written **before** anything moves, not after: what
    follows is a restart, and a restart is where an entry written afterwards
    goes missing. It names both fingerprints and the count, because months
    later the question asked of it is which certificate this was and how many
    machines it was known to be about to strand.

    Nothing here touches the binding. Under IIS this process is the app pool
    identity and is not an administrator, so moving the binding is a spawn the
    window makes (`_bind_cert_command`), and under the service or a standalone
    install it is a restart. Either way the files are what this changes, and
    the answer says plainly that the binding has not moved yet - a half
    cutover reported as a whole one is worse than a refusal.

    Off IIS, this is also the door `ssl_enabled` is turned on through (#266):
    TLS ends at the site under IIS (`_run_flask` never builds a context
    there), but a standalone server or the Windows Service reads that flag
    itself, and a server Generate and Cut Over ran against while it was still
    on plain HTTP would otherwise go on serving HTTP after both - the files
    on disk are the staged pair, HTTPS is never offered. `_save_server_cfg`
    is what Install turns the same flag on through, so a server that has
    never had a certificate before and one that already had one staged reach
    it the same way.

    `authorised_as` is the console saying its door already asked (096): Server
    Settings is gated on the admin password, so Cut Over asks nothing again.
    Set, the password is not checked and the value is the actor.
    """
    import shutil
    fp_next = _cert_fingerprint(SSL_CERT_NEXT_PATH)
    if not fp_next:
        return {"error": "No certificate is staged on this server",
                "code": "no_staged_cert"}, 409
    if not os.path.exists(SSL_KEY_NEXT_PATH):
        return {"error": "The staged certificate has no private key beside "
                         "it. Generate the pair again.",
                "code": "no_staged_key"}, 409
    fp_live = _cert_fingerprint(SSL_CERT_PATH)
    if fp_live and fp_live == fp_next:
        return {"error": "The staged certificate is already the one being "
                         "served. There is nothing to cut over to.",
                "code": "already_bound"}, 409
    if authorised_as is not None:
        issued_by = authorised_as
    elif not _admin_password_ok(password):
        return {"error": "Wrong admin password", "code": "bad_password"}, 401

    behind, total = _clients_behind_staged()
    _log_event("cert.cutover",
               "%s  ->  %s  ·  %d of %d installation(s) had not collected it"
               % (fp_live or "(none)", fp_next, behind, total),
               actor=issued_by, level="warn",
               data={"from": fp_live or "(none)", "to": fp_next,
                     "behind": behind, "total": total})
    try:
        if os.path.isdir(CERT_ROLLBACK_DIR):
            shutil.rmtree(CERT_ROLLBACK_DIR)
        os.makedirs(CERT_ROLLBACK_DIR)
        for p in (SSL_CERT_PATH, SSL_KEY_PATH):
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(CERT_ROLLBACK_DIR,
                                             os.path.basename(p)))
        os.replace(SSL_CERT_NEXT_PATH, SSL_CERT_PATH)
        os.replace(SSL_KEY_NEXT_PATH, SSL_KEY_PATH)
    except OSError as ex:
        _log_event("cert.cutover_failed", "%s: %s" % (fp_next, ex),
                   actor=issued_by, level="error")
        return {"error": "The certificate could not be replaced: %s" % ex,
                "code": "cutover_failed"}, 500

    iis = _iis_host()
    if iis is None:
        _save_server_cfg(ssl_enabled=True, _actor=issued_by)
    return {"status": "cut over", "from": fp_live or "", "to": fp_next,
            "behind": behind, "clients": total,
            "aside": CERT_ROLLBACK_DIR,
            "site": (iis or {}).get("site") or "",
            # `app_pool`, which is what install-iis.ps1 writes and the
            # only name that key has ever had - `pool` read nothing and this
            # field has been "" on every install since it was added.
            "pool": (iis or {}).get("app_pool") or "",
            "iis": bool(iis),
            "command": _bind_cert_command()}, 200


def _export_public_cert(dest, source=None):
    """Write the **public half** of the server's certificate to `dest` (C5).

    `ssl_cert.pem` and `ssl_key.pem` sit beside each other in the install
    directory with names one character apart, and the moment somebody reaches
    for one of them is the moment a client cannot connect and they are in a
    hurry. That is the whole risk in this feature, and it is answered twice
    rather than once.

    **Refused** where the source holds a `PRIVATE KEY` block at all - the same
    refusal `package.ps1` and `bundle-client.ps1` already carry over anything
    they stage, for the same reason: anyone holding that key impersonates this
    server to every client that pinned the certificate, and a client fails
    closed against nothing else (rule 1), so it would not even be noticed.
    And **only the certificate blocks are written**, rather than the file's
    bytes, so a source carrying anything else at all - a key whose header is
    spelled some other way, a comment, a second unrelated PEM body - leaves
    that material behind rather than travelling in a file called
    `ssl_cert.pem` on somebody's laptop.

    Answers the fingerprint of what it wrote, in `_cert_fingerprint`'s own
    form, so the export and the client's first-contact prompt (ADR-0010) are
    compared without a second tool. Measured from the **written** file rather
    than from the source, since what the admin is going to read down a phone
    is what actually landed.

    Raises `ValueError` with the reason for every refusal, which is what the
    window shows: "failed" is the one answer nobody can act on here, a missing
    certificate and a file holding a key needing entirely different things
    done about them.
    """
    if source is None:
        source = SSL_CERT_PATH
    try:
        with open(source, encoding="utf-8", errors="replace") as f:
            pem = f.read()
    except OSError as ex:
        raise ValueError("The certificate could not be read: %s" % ex)
    if "PRIVATE KEY" in pem.upper():
        raise ValueError(
            "That file holds a private key and was not exported. Only the "
            "public certificate may be carried to a client - anybody holding "
            "the key can impersonate this server to every client that pinned "
            "it.")
    head, tail = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    blocks = []
    at = pem.find(head)
    while at >= 0:
        end = pem.find(tail, at + 1)
        if end < 0:
            break
        blocks.append(pem[at:end + len(tail)])
        at = pem.find(head, end + 1)
    if not blocks:
        raise ValueError("There is no certificate in that file to export.")
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(blocks) + "\n")
    fp = _cert_fingerprint(dest)
    if not fp:
        raise ValueError("What was written could not be read back as a "
                         "certificate. Nothing was exported.")
    return fp
