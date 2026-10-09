"""Helpers for tools/dev-run.ps1 and tools/package.ps1 that need Python.

Kept out of the .ps1 because PowerShell has no X.509 generation, no xlsx reader
and no way to draw a .ico, while the dev machine already has cryptography,
openpyxl and pillow. Its two callers both run it under the developer's own
interpreter - package.ps1 calls `python` for `icon`, dev-run.ps1 calls `cert`
and `lookup` with the interpreter it resolved from PATH or was handed as
-PythonExe - and never against a vendored
lib\\, so what it needs is what that interpreter already has.
cryptography is in neither requirements file: it is wanted here and nowhere
else, and nothing ships it.

    python _devtools.py cert   <cert_path> <key_path> [name ...]
    python _devtools.py lookup <xlsx_path> [count]
    python _devtools.py icon   <ico_path>
"""
import sys


def make_cert(cert_path, key_path, names=None):
    """Write a self-signed certificate the clients can actually verify.

    Three details matter, each of which fails silently if omitted:

      * an IPAddress SAN, because a client may connect by address and urllib3
        asserts the SAN even though the adapter turns check_hostname off;
      * a DNSName SAN for every name the server answers to, so either spelling
        of the URL works;
      * CA:TRUE, because OpenSSL 3 refuses to use a non-CA certificate as a
        trust anchor, and a self-signed cert is its own issuer.

    names are the hostnames and addresses the certificate must carry: each one
    that parses as an IP address becomes an IPAddress SAN and every other a
    DNSName, and the first is the common name. Defaults to what dev-run.ps1
    needs, localhost and 127.0.0.1, and dev-run.ps1 is the only caller left:
    it stopped being a hardcoded pair when package.ps1 grew a self-signed
    switch of its own that minted for the real server's names, and 061 took
    that switch back out because a build machine was minting a key for a
    server it could not bind it on. install-iis.ps1 -SelfSigned mints on the
    server now, where the key never leaves, and does not come through here.
    """
    import datetime as dt
    import ipaddress
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    names = [n for n in (names or []) if n] or ["localhost", "127.0.0.1"]
    sans = []
    for n in names:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            sans.append(x509.DNSName(n))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                           critical=True)
            .sign(key, hashes.SHA256()))

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    print("wrote %s and %s" % (cert_path, key_path))


def show_lookup(xlsx_path, count):
    """Print a few rows of the lookup sheet.

    Without this the first thing anyone tries in the Storekeeper is blocked by
    "Asset Not in Lookup", because a submission is only accepted for an asset
    the sheet already knows.
    """
    import openpyxl
    ws = openpyxl.load_workbook(xlsx_path, read_only=True).active
    rows = list(ws.iter_rows(min_row=2, max_row=1 + count, values_only=True))
    for r in rows:
        cells = ["" if c is None else str(c) for c in r[:3]]
        while len(cells) < 3:
            cells.append("")
        print("    %-16s %-20s %s" % (cells[0], cells[1], cells[2]))
    if not rows:
        print("    (the lookup sheet is empty)")


def make_icon(ico_path):
    """Write the .ico PyInstaller stamps on AssetManager_Setup.exe.

    One exe, not the four this said before 061: PyInstaller compiles the
    installer and nothing else, the other three apps shipping as the .py files
    a signed pythonw.exe reads (rule 12).

    The writing is ui_kit.write_ico's, not this file's: the installer writes
    one too, for a source-mode Desktop shortcut, and which sizes go in is the
    decision worth having in one place. Derived at build time rather than
    committed beside the sources - a committed .ico would be a second copy of
    an artwork the windows and the trays already draw, and it is the file that
    would go stale, because nothing reads it back to notice.
    """
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import ui_kit

    if not ui_kit.write_ico(ico_path):
        raise SystemExit("pillow is not installed - the icon cannot be drawn.")
    print("wrote %s (%s)"
          % (ico_path, ", ".join(str(s) for s in ui_kit.ICO_SIZES)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "cert":
        make_cert(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif cmd == "lookup":
        show_lookup(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 5)
    elif cmd == "icon":
        make_icon(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)
