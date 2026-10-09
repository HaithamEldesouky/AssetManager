r"""
Asset Manager — Unified Installer
User picks which component to install; installer writes config.json
and copies the right payload to a chosen directory.
Since 061 every payload it ships is source: the .py files plus a vendored
lib\, run by a signed pythonw.exe. The exe payload below is still read,
for a release built before that, but nothing produces one any more.
Each install verifies live against the server, asking for the credential
that fits it: a Notifier takes the engineer's own password or the admin
password, a Storekeeper takes the admin password. See docs/adr/0007.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os, sys, json, shutil, hashlib

# Wire layer shared with the two client apps - see common.py.
import common
from common import api, TEAM_MEMBERS, verify_password, verify_admin_password
import ui_kit

# ─── Bundled exe names - nothing builds these since 061 ────────────────────
BUNDLED_EXES = {
    "server":      "AssetServer.exe",
    "storekeeper": "StorekeeperApp.exe",
    "notifier":    "NotifierApp.exe",
}

# ─── Source-mode payload ──────────────────────────────────────────────────────
# The same installer, shipping .py instead of .exe. What Windows then executes
# is a signed pythonw.exe with a launcher as its argument, which is the point:
# our exes are unsigned and have no reputation by construction, and an ASR rule
# already blocks one of them. See docs/it-asr-and-signing-request.md.
#
# Which mode this is running in is decided by what is actually next to the
# installer (_payload_mode), not by a flag, so one code path cannot be told to
# install files that were never shipped.
#
# Storekeeper and Notifier only. A source-mode server is installed by
# tools/install-iis.ps1 and tools/update.ps1, not from here: the Windows Service
# verbs need pywin32's pythonservice.exe, which is an unsigned executable that
# tools/vendor.ps1 deliberately strips out of lib\. IIS is the supported host
# either way - see ADR-0001.
# client_update.py is in both lists rather than in neither: it is what applies
# the next release in place, and an install that did not carry it would have to
# be updated by running this installer again - which is the thing it exists to
# stop. It imports nothing of ours at module level, so it survives being the
# file that is overwriting common.py and ui_kit.py around it.
# Three modules are in one list rather than both: the Notifier's Pending
# decisions (#208) and its Remote Admin surface (#218), and the Storekeeper's
# export (#219). Neither app has the other's concern - no pending queue and no
# console on one side, no store to export on the other - so each is that app's
# own module rather than shared code rule 10 would put in common.py.
# bundle-client.ps1 stages them the same way - that app's Extra, not the shared
# $Payload - and cascade-audit.py holds the two lists equal per app.
SOURCE_FILES = {
    "storekeeper": ["run_storekeeper.pyw", "applaunch.py", "storekeeper_app.py", "common.py", "ui_kit.py",
                    "client_update.py", "storekeeper_export.py",
                    "storekeeper_bulk.py", "storekeeper_propose.py"],
    "notifier":    ["run_notifier.pyw",    "applaunch.py", "notifier_app.py",    "common.py", "ui_kit.py",
                    "client_update.py", "notifier_pending.py",
                    "notifier_remote.py"],
}
SOURCE_LAUNCHER = {
    "storekeeper": "run_storekeeper.pyw",
    "notifier":    "run_notifier.pyw",
}

# Grey hint text in the empty Server URL field, never a value: the installer
# prefills nothing, so a person types the address rather than accepting one.
SERVER_URL_HINT = "https://example.com:9000"
DEFAULT_PORT = 8081          # what a fresh server_config.json listens on
# server.py's PASSWORD_MIN, written down a second time because this file does
# not import the server and must not: the server is not on the machine being
# installed from, and rule 10 keeps the two release paths apart - the port
# check in _install_server says exactly this about _validate_port three lines
# below its own. So it is a cascade rather than a call, and cascade-audit.py
# holds the two numbers equal.
#
# Which way it drifts is the point. Every other door holding this bound
# changes a password that already exists; this one sets the first admin
# password an install ever has, and that is the credential every capability
# password is measured against - raise the constant in server.py alone and the
# loosest door in the system is the one at the bottom of it. #90 was this same
# drift pointing the other way, in the Server GUI's Change Admin Password.
PASSWORD_MIN = 4
APP_VERSION = "2.10.1"


# ─── Colours ──────────────────────────────────────────────────────────────────
# The names below are bound into this module by the Theme, out of ui_kit's
# own table, which is where the product's colours are written down (rule 10).
# This file used to state the fourteen as literals - the values every app
# carried before ui_kit existed - so the installer was the one window in this
# product still on the old palette.
#
# There is no theme *setting* here and deliberately none: this is one window,
# run once, on a machine that may not have Python on it yet, with nowhere to
# remember a choice and nobody to make one. What the Theme is for is the table
# and the live palette bound out of it.
THEME = ui_kit.Theme(globals())

# ─── Helpers ──────────────────────────────────────────────────────────────────

if getattr(sys, 'frozen', False):
    _INSTALLER_DIR = os.path.dirname(sys.executable)
else:
    _INSTALLER_DIR = os.path.dirname(os.path.abspath(__file__))

_SSL_CERT_PATH = os.path.join(_INSTALLER_DIR, "ssl_cert.pem")
_SSL_KEY_PATH  = os.path.join(_INSTALLER_DIR, "ssl_key.pem")

def _ssl_cert_source():
    """Path to the public certificate to install beside a client, or None.

    One source, and it is a copy sitting next to AssetManager_Setup.exe - how an
    admin supplies a certificate, or a renewed one, without a rebuild.

    There was a second, the copy baked in at build time, and it is gone because
    nothing writes it any more: 061 stopped package.ps1 staging a certificate
    into the exe at all, and packaging refuses one that turns up. A fallback
    with no source is worse than no fallback, because it makes this one
    question look like two - _report_unreachable asked
    os.path.exists(_SSL_CERT_PATH) where every other caller asked this, and the
    two agreed only by accident of nothing being bundled.

    The history is what the branch was for and is worth keeping: before it
    existed the bundled copy was extracted to _MEIPASS and never read, so every
    client install needed the file placed next to the installer by hand. What
    answers that now is ADR-0010 - a client given no certificate offers the
    server's fingerprint on first contact and pins it if a person accepts -
    rather than a second place to look.

    ssl_key.pem deliberately has no equivalent: the private key is read only
    from next to the installer, on the server, by the admin running the server
    install. It is never bundled.
    """
    if os.path.exists(_SSL_CERT_PATH):
        return _SSL_CERT_PATH
    return None

# api() verifies against whichever copy _ssl_cert_source() finds. Without this
# the installer only ever looked next to itself, so the certificate bundled at
# build time was extracted and never used - and with the client apps now
# refusing HTTPS when no certificate is present, that would have blocked every
# notifier install that did not ship a loose ssl_cert.pem.
common.SSL_CERT_PATH = _ssl_cert_source() or _SSL_CERT_PATH

# ─── The Python the client apps run on ────────────────────────────────────────
# 3.12 is not negotiable: in source mode what Windows executes is a signed
# pythonw.exe with a launcher as its argument, and the vendored lib\ carries
# cp312 compiled extensions, so applaunch.py refuses any other minor (rule 13).
#
# 3.12.10 is pinned because it is the last 3.12 with a Windows installer - the
# series went security-only afterwards and those releases are source-only - so
# this is a fact about the series rather than a number that goes stale on every
# patch. A newer one dropped next to AssetManager_Setup.exe is still preferred
# over it, the way a renewed ssl_cert.pem is.
PYTHON_SERIES = "3.12"
PYTHON_PINNED = "3.12.10"
PYTHON_SETUP  = "python-%s-amd64.exe" % PYTHON_PINNED
PYTHON_URL    = "https://www.python.org/ftp/python/%s/%s" % (PYTHON_PINNED, PYTHON_SETUP)
PYTHON_SIGNER = "Python Software Foundation"
# All users, because this installer is already --uac-admin and a laptop signed
# into by a second engineer must not lose the interpreter with the profile.
# Include_tcltk is stated rather than left to the installer's default, which is
# 1 today and is a default rather than a guarantee: it is remembered from the
# last install on that machine and is a tickbox anybody can clear. Three of the
# four apps here are nothing but a Tk window, so an interpreter without it
# installs cleanly, reports success, and can never open anything - which is how
# a server came to be installed with no console on it at all.
PYTHON_ARGS   = ["/quiet", "InstallAllUsers=1", "PrependPath=1",
                 "Include_launcher=1", "Include_tcltk=1", "Include_test=0"]

_PHASE_TEXT = {
    "download": "Downloading Python %s..." % PYTHON_PINNED,
    "verify":   "Checking the installer's signature...",
    "install":  "Installing Python %s - this takes a minute..." % PYTHON_PINNED,
}


def _run_hidden(cmd, timeout=None):
    """subprocess.run with no console window flashing over the installer."""
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _python_installed(series=PYTHON_SERIES):
    """Path to an installed CPython <series> on this machine, or None.

    Two questions rather than one, because they fail apart: the py launcher
    answers for any install that shipped it, and the registry answers for one
    installed without it. Neither is sys.executable - under
    AssetManager_Setup.exe that is the frozen installer, which is not a Python
    anything else can be run with.
    """
    try:
        r = _run_hidden(["py", "-%s" % series, "-c",
                         "import sys; print(sys.executable)"], timeout=30)
        if r.returncode == 0 and (r.stdout or "").strip():
            return r.stdout.strip()
    except Exception:
        pass
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = r"Software\Python\PythonCore\%s\InstallPath" % series
                with winreg.OpenKey(hive, key) as k:
                    path = winreg.QueryValueEx(k, "ExecutablePath")[0]
                if path and os.path.exists(path):
                    return path
            except OSError:
                continue
    except Exception:
        pass
    return None


def _python_setup_source():
    """The Python installer to run, or None when one has to be downloaded.

    Next to AssetManager_Setup.exe first, then the copy embedded at build time:
    an admin ships a newer patch by dropping it beside the installer rather than
    by rebuilding. Nothing embeds one today - package.ps1 refuses to stage any
    .exe at all (rule 12) - so in practice this is the loose file or the
    download.
    Matched on the series rather than on PYTHON_SETUP so that a newer one is
    actually found, and the newest file wins when there is more than one, since
    "3.12.9" sorts after "3.12.10" as text.
    """
    import glob
    loose = glob.glob(os.path.join(_INSTALLER_DIR,
                                   "python-%s.*-amd64.exe" % PYTHON_SERIES))
    if loose:
        return max(loose, key=os.path.getmtime)
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, PYTHON_SETUP)
        if os.path.exists(bundled):
            return bundled
    return None


def _signed_by_psf(path):
    """True when path carries a valid Authenticode signature from the PSF.

    Checked instead of a pinned SHA-256 because this file arrives three ways -
    embedded at build time, dropped next to the installer by an admin, or
    downloaded here - and a hash pinned to one patch release refuses the other
    two the moment python.org publishes a new one. The signature is the same
    thing rule 12 rests on: what Windows ends up executing is PSF-signed.
    """
    quoted = "'" + path.replace("'", "''") + "'"
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath %s; "
          "Write-Output $s.Status; "
          "Write-Output $s.SignerCertificate.Subject" % quoted)
    try:
        r = _run_hidden(["powershell", "-NoProfile", "-NonInteractive",
                         "-Command", ps], timeout=120)
    except Exception:
        return False
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    return (r.returncode == 0 and bool(lines) and lines[0] == "Valid"
            and PYTHON_SIGNER.lower() in " ".join(lines[1:]).lower())


def _download(url, dest, progress):
    """Fetch url to dest, reporting (done, total) as it goes.

    Plain urllib against the system trust store - python.org is publicly
    trusted, unlike our own server, so nothing here touches common.py's pinned
    session and nothing here ever relaxes verification.
    """
    import urllib.request
    req = urllib.request.Request(url,
                                 headers={"User-Agent": "AssetManager-Installer"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done  = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                progress(done, total)


class _ProgressWindow:
    """A bar and one line of text, for the one job here that takes minutes.

    No Cancel button: what it covers is a Windows installer already running
    under /quiet, and there is nothing here that could take a half-applied one
    back. No geometry either - the window is left to size itself to what is
    packed into it, which is the answer ui_kit.fit computes for the windows that
    do write one down.

    Every widget here is touched from the Tk thread only: the worker writes to a
    dict and render() reads it, because tkinter from a second thread is a crash
    that happens on somebody else's laptop.
    """

    def __init__(self, parent, title):
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        # No Escape binding here: this is one of the four windows in this
        # product that must refuse its own X, and a key that closed it would
        # be the same refusal walked round.
        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=title, bg=BG, fg=TEXT,
                 font=font("display")).pack(anchor="w", padx=28,
                                            pady=(22, 0))
        self.lbl = tk.Label(body, text="", bg=BG, fg=SUBTEXT, width=46,
                            anchor="w", font=font("body"))
        self.lbl.pack(anchor="w", padx=28, pady=(6, 12))
        self.bar = ttk.Progressbar(body, mode="indeterminate", length=380)
        self.bar.pack(fill="x", padx=28, pady=(0, 22))
        self.bar.start(12)
        self._mode = "indeterminate"

        self.win.update_idletasks()
        self.win.grab_set()

    def _set_mode(self, mode):
        if mode == self._mode:
            return
        if self._mode == "indeterminate":
            self.bar.stop()
        self.bar.config(mode=mode)
        if mode == "indeterminate":
            # Back off the download's scale first. An indeterminate bar
            # bounces value within maximum, so leaving 26,964,224 there
            # moves the block one part in 26 million per tick - a bar that
            # looks frozen for exactly the phases that take longest.
            self.bar.config(maximum=100, value=0)
            self.bar.start(12)
        self._mode = mode

    def render(self, state):
        phase, done, total = state["phase"], state["done"], state["total"]
        if phase == "download" and total:
            self._set_mode("determinate")
            self.bar.config(maximum=total, value=done)
            self.lbl.config(text="Downloading Python %s  -  %d%%"
                                 % (PYTHON_PINNED, done * 100 // total))
        else:
            self._set_mode("indeterminate")
            self.lbl.config(text=_PHASE_TEXT.get(phase, ""))
        self.win.update()

    def close(self):
        try:
            self.bar.stop()
            self.win.grab_release()
            self.win.destroy()
        except Exception:
            pass


def fetch_members(server_url):
    """Engineer names from the server's /members, so newly-added engineers are
    selectable without rebuilding. Falls back to the baked-in list if unreachable."""
    try:
        r = api("get", f"{server_url.rstrip('/')}/members", timeout=5)
        if r.ok:
            names = [m["name"] for m in r.json() if m.get("name")]
            if names:
                return names
    except Exception:
        pass
    return list(TEAM_MEMBERS)

def _bundled_path(name):
    """Return path to a bundled exe.
    When running as AssetManager_Setup.exe (frozen), PyInstaller extracts
    bundled files to sys._MEIPASS. When running as script, look next to installer.py.
    """
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, BUNDLED_EXES[name])


def _payload_root():
    """Directory holding whatever this installer is shipping."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _payload_mode(key):
    """Return "exe", "source", or None when neither payload is present.

    Decided by looking, not by a flag. A source bundle has no exes in it and an
    exe installer has no lib directory, so the check cannot pick a path whose
    files were never shipped.
    """
    root = _payload_root()
    if os.path.exists(os.path.join(root, BUNDLED_EXES[key])):
        return "exe"
    if key in SOURCE_FILES:
        have = all(os.path.exists(os.path.join(root, f)) for f in SOURCE_FILES[key])
        if have and os.path.isdir(os.path.join(root, "lib")):
            return "source"
    return None


class PythonMismatch(Exception):
    """No Python on this PC matches the one lib\\ was vendored for."""


def _lib_pyver(root):
    """The Python minor version lib\\ carries, or None when it is unstamped.

    Written by tools/vendor.ps1 and read here for the same reason applaunch.py
    reads it at startup (rule 13): pillow and charset_normalizer carry compiled
    cp3xx extensions, so the vendored lib\\ runs under one minor version and no
    other.
    """
    stamp = os.path.join(root, "lib", "PYVER")
    try:
        with open(stamp, encoding="ascii") as fh:
            return fh.read().strip() or None
    except Exception:
        return None


def _gui_python(expected=None):
    """pythonw.exe to install the app to run under, or None when none matches.

    Not simply the interpreter running this installer. What the shortcut names
    has to match lib\\PYVER, and the interpreter that opened the installer is
    whichever one the .pyw association points at - on a machine with two
    Pythons that is the newest, not the right one. It is not a Python at all
    when the installer is the frozen AssetManager_Setup.exe.

    So: the running interpreter when it already matches, else whatever
    _python_installed asks the machine - one probe for that question rather
    than a second copy of it here. None when neither answers, and the caller
    refuses the install - a shortcut naming the wrong Python installs cleanly
    and then opens applaunch's error box the first time an engineer clicks it,
    which is the failure this reads PYVER to prevent. _ensure_python has run by
    then, so "not installed" has already had its one chance to be fixed.

    A frozen installer never answers with sys.executable, whatever it was
    asked. An unstamped lib\\ - deleted, hand-assembled, or left half-written
    by an interrupted pip run, which is the case Get-VendoredPyVer refuses at
    the other end - used to take the first branch, and sys.executable under
    AssetManager_Setup.exe is the installer itself: the Desktop shortcut then
    named Setup and reopened it on every click, with applaunch never reached to
    say anything about it. Every other reader here tolerates a missing stamp -
    _payload_mode asks only that lib\\ is a directory, applaunch's check is
    skipped where there is nothing to compare against, and _ensure_python reads
    it as PYTHON_SERIES - so this asks the machine for that same pinned series
    rather than inventing a fourth answer. It is on the machine by then or the
    install is refused, which is what this function is for.

    pythonw rather than python because these are GUI apps and the console window
    would sit behind them forever; python.exe is better than nothing where no
    pythonw sits beside it.
    """
    def gui(exe):
        cand = os.path.join(os.path.dirname(exe),
                            os.path.basename(exe).replace("python.exe", "pythonw.exe"))
        return cand if os.path.exists(cand) else exe

    running = "%d.%d" % sys.version_info[:2]
    if not getattr(sys, "frozen", False) and (not expected or expected == running):
        return gui(sys.executable)

    found = _python_installed(expected or PYTHON_SERIES)
    return gui(found) if found else None


def _deploy_component(key, dest_dir):
    """Copy the payload for key into dest_dir. Returns (target, args, workdir, icon).

    target/args are what a shortcut should point at: the exe itself in exe mode,
    or pythonw.exe plus the launcher in source mode.

    icon is the path to a .ico for the shortcut, or None when it does not need
    one. In exe mode it does not: a shortcut takes its icon from the exe it
    points at, and that exe is stamped with this same artwork by package.ps1.
    In source mode it points at pythonw.exe instead, so without a file of its
    own the engineer's Desktop carries a Python feather for an app that is not
    Python's - which is the one place rule 12's no-exe-of-ours is visible to
    the person using it.
    """
    os.makedirs(dest_dir, exist_ok=True)
    root = _payload_root()
    mode = _payload_mode(key)

    if mode == "exe":
        dst = os.path.join(dest_dir, BUNDLED_EXES[key])
        shutil.copy2(_bundled_path(key), dst)
        return dst, "", dest_dir, None

    # Resolved before a single file is copied: a refusal here has to leave
    # nothing behind, and what it refuses is an install that would succeed and
    # then never start.
    expected = _lib_pyver(root)
    python = _gui_python(expected)
    if python is None:
        # PYTHON_SERIES where the stamp is gone, which is the version
        # _gui_python and _ensure_python both asked the machine for. A refusal
        # naming "Python None" is one nobody can act on.
        expected = expected or PYTHON_SERIES
        raise PythonMismatch(
            "This package was built for Python %s.\n\n"
            "The installer is running under Python %d.%d, and no Python %s was "
            "found on this PC - the py launcher was asked for -%s.\n\n"
            "Install Python %s and run the installer again, or ask IT for a "
            "package built for the Python this PC has."
            % (expected, sys.version_info[0], sys.version_info[1],
               expected, expected, expected))

    for name in SOURCE_FILES[key]:
        shutil.copy2(os.path.join(root, name), os.path.join(dest_dir, name))

    # lib\ is replaced wholesale rather than merged: a leftover module from an
    # older pin would be found by applaunch's sys.path entry and shadow the new
    # one, which is the sort of thing that only shows up in production.
    lib_dst = os.path.join(dest_dir, "lib")
    if os.path.isdir(lib_dst):
        shutil.rmtree(lib_dst, ignore_errors=True)
    shutil.copytree(os.path.join(root, "lib"), lib_dst)

    # Written rather than copied, so there is no icon file to ship, to hash in
    # a manifest or to keep in step with the one the app draws. Never fatal: an
    # install with a plain shortcut is an install, and this runs after every
    # file that matters is already on disk.
    icon = os.path.join(dest_dir, "app.ico")
    try:
        if not ui_kit.write_ico(icon):
            icon = None
    except Exception:
        icon = None

    launcher = os.path.join(dest_dir, SOURCE_LAUNCHER[key])
    return python, '"%s"' % launcher, dest_dir, icon


def _existing_port(dest_dir):
    """The port the install at dest_dir already serves on, or None.

    Looked up rather than assumed, the way _payload_mode looks at what sits
    beside it: a reinstall whose Port field said 8081 would quietly move a
    server that had been serving on another one, which is the same silent
    wrongness this field exists to remove. Read with a plain open(), the way
    every other reader of this file in the repo reads it; anything unreadable
    is no answer rather than a wrong one.
    """
    try:
        with open(os.path.join(dest_dir, "server_config.json")) as f:
            port = json.load(f).get("port")
    except Exception:
        return None
    return str(port) if isinstance(port, int) and 1 <= port <= 65535 else None


def _write_admin_cfg(dest_dir, password):
    """Put the admin password into admin_config.json, keeping what is there.

    A read-modify-write on a reinstall, for the reason server_config.json
    beside it is one. This file holds a third key - capability_hashes - and a
    fresh dict drops every capability password the Admin has set, with nothing
    said at the time and nothing left in the file to say one was ever there:
    the Capability Passwords window afterwards reports four actions with no
    delegation on them, which is indistinguishable from an Admin who never set
    one. The two keys the operator was actually asked about are the two that
    move.

    The hash is the pre-ADR-0008 bare SHA-256, deliberately: the salted pair
    lives in server.py, which does not import common.py (rule 10), and copying
    a security primitive across that line is what rule 10 exists to prevent.
    The server accepts this format and rewrites it salted on the first use of
    the password it stands for - see ADR-0008.

    A file that cannot be read is left byte for byte alone and the caller is
    handed a line to put in front of the operator, the same answer the port
    write gives: what is already in that file is worth more than this install's
    two keys, and an admin password that was not applied has to be said rather
    than discovered at the console.

    Takes paths and touches no Tk, so the decision is reachable without a
    payload to copy first - the split _export_public_cert makes on the server
    side. Returns "" where it wrote, else the line for the popup.
    """
    path = os.path.join(dest_dir, "admin_config.json")
    admin_cfg = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                admin_cfg = json.load(f)
            if not isinstance(admin_cfg, dict):
                raise ValueError("not a JSON object")
        except Exception as cfg_err:
            return (
                f"\n\n⚠️  Admin password not applied: admin_config.json "
                f"could not be read ({cfg_err}).\n"
                "    Nothing in it was replaced - the server still takes the "
                "password it already had."
            )
    admin_cfg["password_hash"] = hashlib.sha256(password.encode()).hexdigest()
    admin_cfg["first_run"] = False
    with open(path, "w") as f:
        json.dump(admin_cfg, f, indent=2)
    return ""

# ─── Main Installer Window ────────────────────────────────────────────────────

class InstallerApp:
    def __init__(self, root):
        self.root = root
        root.title("Asset Manager — Setup")
        # The first window anybody sees of this product, and the one that is
        # looked at while it copies files - so it is the one that most wants
        # the icon rather than Tk's feather.
        ui_kit.set_window_icon(root)
        # Before anything is built, so the engineer combobox's dropdown is born
        # in this palette rather than in Tk's white default.
        THEME.register(root)
        root.geometry("560x700")
        root.minsize(560, 600)
        root.configure(bg=BG)
        root.resizable(False, True)

        # An install is the first thing that ever talks to the server from this
        # machine, so it is usually where a missing certificate is met first.
        common.set_cert_confirm(self._confirm_cert)

        self._build_ui()

    def _confirm_cert(self, fingerprint, server_url):
        """Ask the person installing to accept the server's certificate.

        The certificate is no longer required beside the installer: where one
        is shipped nothing is asked, and where none is, this offers the
        server's own and pins it on acceptance - written next to the installer,
        so _ssl_cert_source() then copies it into the install like any other.

        Every install runs on the Tk thread, so this asks directly; it still
        goes through common.confirm_on_tk_thread, which is what decides that.
        Cancel is the default button, and cancelling leaves the install to fail
        the way it did before, with no certificate to verify against.
        """
        title, body = common.cert_prompt_text(fingerprint, server_url)
        return common.confirm_on_tk_thread(
            self.root,
            lambda: messagebox.askokcancel(title, body, icon="warning",
                                           default="cancel"))

    def _build_ui(self):
        # Fixed header (not scrollable), and a flat shell with a groove
        # under it rather than a band of the accent (#181). This window has
        # exactly one action on it, and 56px of ACCENT above the form was the
        # loudest thing on screen while the control that actually installs
        # something sat at the bottom in the same colour. What is left is the
        # title in the shell's own face, in sentence case, with no emoji: this
        # is a title bar rather than a badge.
        hdr = tk.Frame(self.root, bg=CARD2, height=68)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        _hb = tk.Frame(hdr, bg=CARD2)
        _hb.pack(side="left", padx=24, pady=15)
        tk.Label(_hb, text="Asset Manager", bg=CARD2, fg=TEXT,
                 font=font("display", size=15)).pack(anchor="w")
        tk.Label(_hb, text="Setup", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w")
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x")

        # Scrollable body
        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(self.root, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # The scrolling body stays a tk.Frame: what it is windowed into asks
        # about its requested width rather than its own, and tools/client-
        # checks.py reads that form back off it.
        body = tk.Frame(canvas, bg=BG)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        pad = tk.Frame(body, bg=BG)
        pad.pack(fill="both", expand=True)

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(body_window, width=e.width)
        body.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # All content goes into `pad` from here - the ground, rather than the
        # frame around it.
        tk.Label(pad, text="What this computer is",
                 bg=BG, fg=TEXT,
                 font=font("heading")).pack(pady=(16, 1), padx=24, anchor="w")
        tk.Label(pad,
                 text="Choose which component to install on this computer.",
                 bg=BG, fg=SUBTEXT,
                 font=font("body")).pack(pady=(0, 10), padx=24, anchor="w")

        # ── Component selector ─────────────────────────────────────────────────
        # Nothing is selected until a card is clicked, and nothing below the
        # cards is shown until then either: every field is read off the card
        # that was picked, so there is no form to show before one is.
        self.v_component = tk.StringVar(value="")

        # No emoji on the three labels (#181): the cards are the one place
        # this window carries state, and a glyph per card is decoration
        # competing with the mark that says which of them is selected.
        cards = [
            ("server",      "Asset Server",
             "Installs the Asset Server on this computer.\nHosts the database and the REST API."),
            ("storekeeper", "Storekeeper App",
             "Install on Storekeeper User's computer.\nUsed to log asset transactions."),
            ("notifier",    "Notifier",
             "Install on each engineer's laptop.\nShows confirmation popups for asset movements."),
        ]

        # **The three cards are one plate divided by grooves** (#181), rather
        # than three tiles floating with a gap between them: packed flush, and
        # a 1px rule where two of them meet. The padding sits on the children
        # rather than on the card, which is where it went when a card was a
        # canvas and is left there - moving it back would re-measure every
        # form on this window for nothing.
        #
        # **Since 080 the plate is `INPUT_BG` and the selection is a mark on
        # it** (`prototypes/NOTES-3.md`). The rows were a tinted face - `CARD`
        # against `CARD2` - which is what `ui_glass.Surface.reface` existed
        # to carry under the frost and is what #249 took away with it; this
        # is the caller that replaced. Three rows in three different faces
        # also say the wrong thing about what a row is: a thing to choose is
        # a recess, the way a field somebody types into is, and all three are
        # equally a recess until one is picked. What says which is picked is
        # a 2px `TEXT` bar on the leading edge - `ui_kit.MARK_W`, the same
        # mark a selected `ListPane` row carries and the same one a selected
        # `SectionBar` cell carries, so this window's one piece of state
        # reads as the product's selection rather than as its own device.
        #
        # The accent border went with the face. Two marks on one row is the
        # ambiguity `SectionBar`'s docstring names one widget over, and the
        # weight of the card's own words (#181) is already the second thing
        # saying the same fact.
        self.card_frames = {}
        self.card_titles = {}
        self.card_descs = {}
        self.card_marks = {}
        for idx, (key, title, desc) in enumerate(cards):
            if idx:
                tk.Frame(pad, bg=LINE, height=1).pack(fill="x", padx=24)
            f = tk.Frame(pad, bg=INPUT_BG, cursor="hand2",
                         highlightthickness=0)
            f.pack(fill="x", padx=24)
            # Packed first and on the leading edge, where the rows are
            # stacked and that edge is a column of its own - `SectionBar`
            # puts its mark on the bottom instead for the reason it gives,
            # which is a strip of abutting cells having no visible leading
            # edge. These rows have one.
            mark = tk.Frame(f, bg=INPUT_BG, width=ui_kit.MARK_W)
            mark.pack(side="left", fill="y")
            words = tk.Frame(f, bg=INPUT_BG)
            words.pack(side="left", fill="both", expand=True)
            rb = tk.Radiobutton(words, text=title, variable=self.v_component,
                                value=key,
                                bg=INPUT_BG, fg=SUBTEXT, selectcolor=INPUT_BG,
                                activebackground=INPUT_BG,
                                activeforeground=TEXT,
                                font=font("title"),
                                # Tk draws a radio whose variable equals its
                                # tristate value half-set, and that value
                                # defaults to "" - which v_component is until
                                # a card is picked.
                                tristatevalue="-",
                                command=self._on_component_change)
            rb.pack(anchor="w", padx=12, pady=(9, 0))
            dsc = tk.Label(words, text=desc, bg=INPUT_BG, fg=FAINT,
                           font=font("body"), justify="left")
            dsc.pack(anchor="w", padx=(38, 14), pady=(0, 9))
            # Click anywhere on card to select. The words frame is bound as
            # well as the card: it fills the row, so a click that lands
            # between the title and the description lands on it rather than
            # on the card behind it.
            for w in (f, words):
                w.bind("<Button-1>", lambda e, k=key: (
                    self.v_component.set(k), self._on_component_change()))
            self.card_frames[key] = f
            self.card_titles[key] = rb
            self.card_descs[key] = dsc
            self.card_marks[key] = mark

        # ── Dynamic section (changes per component) ────────────────────────────
        # Everything from here to the Install button sits in one frame that
        # _on_component_change packs on the first pick; the footer stays in
        # `pad` so it is there before one.
        self.footer = tk.Label(pad,
                               text="For IT department internal use only.",
                               bg=BG, fg=FAINT, font=font("micro"))
        self.footer.pack(side="bottom", pady=(6, 14))
        self.form = tk.Frame(pad, bg=BG)
        pad = self.form
        tk.Frame(pad, bg=LINE, height=1).pack(fill="x", padx=24, pady=(16, 0))
        tk.Label(pad, text="What it needs to know", bg=BG, fg=TEXT,
                 font=font("heading")).pack(pady=(14, 6), padx=24, anchor="w")
        self.dynamic = tk.Frame(pad, bg=BG)
        self.dynamic.pack(fill="x", padx=24)

        # ── Install dir picker ─────────────────────────────────────────────────
        dir_row = tk.Frame(pad, bg=BG)
        dir_row.pack(fill="x", padx=24, pady=(10, 0))
        tk.Label(dir_row, text="Install directory",
                 bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w")
        pick_row = tk.Frame(dir_row, bg=BG)
        pick_row.pack(fill="x", pady=4)
        # Empty until a card is picked; each card's branch below fills in
        # where that component goes, since the path is what an upgrade finds.
        self.v_dir = tk.StringVar(value="")
        dir_e = tk.Entry(pick_row, textvariable=self.v_dir,
                         bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("body"), insertbackground=TEXT)
        dir_e.pack(side="left", fill="x", expand=True, ipady=7)
        tk.Button(pick_row, text="Browse",
                  bg=CARD2, fg=TEXT, font=font("body"),
                  relief="flat", cursor="hand2", padx=12, pady=6,
                  command=self._pick_dir,
                  activebackground=INPUT_BG).pack(side="left", padx=(6, 0))

        # Status / error label
        self.err_lbl = tk.Label(pad, text="", bg=BG, fg=DANGER,
                                font=font("body"))
        self.err_lbl.pack(pady=(6, 0))

        # **The one inverted block on the window** (#181): light on the
        # shell, radius 0, and no arrow on the label - the button says what
        # happens when it is pressed and a glyph beside it adds nothing. It is
        # the only thing here drawn out of the shell rather than into it, which
        # is what makes it the write action now that the header is not a band
        # of the same accent. A `Pill` is a canvas whose bg is BG, so it is
        # registered by the `follow` below and handed the colour of the point
        # it stands at like every other opaque widget here.
        tk.Frame(pad, bg=LINE, height=1).pack(fill="x", padx=24, pady=(14, 0))
        self.btn_install = ui_kit.Pill(pad, "Install", BG, TEXT, MONO, fg=BG,
                                       w=430, h=48, radius=0, size=12,
                                       command=self._install)
        self.btn_install.pack(fill="x", padx=24, pady=(14, 4))

        self._on_component_change()

    def _highlight_card(self, selected_key):
        """The selected card is a 2px `TEXT` bar and its words (080).

        **The face says nothing here and that is the change.** It was `CARD`
        against `CARD2` - eight points a channel, a selection somebody had to
        look for, which is why it needed an accent border and the weight of
        the words beside it to be legible at all. All three rows are
        `INPUT_BG` now, the recess this material gives a thing to be chosen,
        and the mark on the leading edge is the whole of what moves.

        Two things are still written, not one: the mark, and **since #181 the
        text on the card**. The selected title is the shell's brightest text
        and its description is ordinary prose, while the two it is not are a
        step quieter each. That second one is kept rather than dropped
        because a 2px bar is 2px - it says *which*, and the words say *this
        one* at the distance somebody reads the row from.

        The faces are deliberately equal, so `tools/client-checks.py`
        measures the marks and asserts that equality rather than asserting a
        difference: a selection that stopped painting would otherwise pass by
        leaving all three the same.
        """
        for key, frame in self.card_frames.items():
            chosen = key == selected_key
            self.card_marks[key].config(bg=TEXT if chosen else INPUT_BG)
            self.card_titles[key].config(fg=TEXT if chosen else SUBTEXT)
            self.card_descs[key].config(fg=SUBTEXT if chosen else FAINT)

    def _on_component_change(self):
        for w in self.dynamic.winfo_children():
            w.destroy()
        key = self.v_component.get()
        self._highlight_card(key)
        if not key:
            return
        if not self.form.winfo_ismapped():
            self.form.pack(fill="x", before=self.footer)

        if key == "server":
            tk.Label(self.dynamic,
                     text="This computer will host the database and the REST API.",
                     bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w")
            tk.Label(self.dynamic, text="Set the admin password",
                     bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(10, 2))
            if not hasattr(self, 'v_admin_pw'):
                self.v_admin_pw  = tk.StringVar()
                self.v_admin_pw2 = tk.StringVar()
            e_pw = tk.Entry(self.dynamic, textvariable=self.v_admin_pw,
                            show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                            font=font("value"), insertbackground=TEXT)
            e_pw.pack(fill="x", ipady=8)
            ui_kit.reveal(e_pw)
            tk.Label(self.dynamic, text="Confirm the admin password",
                     bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(8, 2))
            e_pw2 = tk.Entry(self.dynamic, textvariable=self.v_admin_pw2,
                             show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                             font=font("value"), insertbackground=TEXT)
            e_pw2.pack(fill="x", ipady=8)
            ui_kit.reveal(e_pw2)
            # Update suggested dir
            self.v_dir.set(os.path.join(
                os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                "AssetManager", "Server"))
            # The port follows the install directory: it shows what the install
            # being pointed at already serves on, and is left empty, the
            # default as grey hint, where there is no install there yet.
            # _pick_dir re-reads it for the same reason.
            tk.Label(self.dynamic, text="Server port",
                     bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(8, 2))
            self.v_port = tk.StringVar(
                value=_existing_port(self.v_dir.get()) or "")
            e_port = tk.Entry(self.dynamic, textvariable=self.v_port,
                              bg=INPUT_BG, fg=TEXT, relief="flat",
                              font=font("value"), insertbackground=TEXT)
            e_port.pack(fill="x", ipady=8)
            self._hint(e_port, self.v_port, str(DEFAULT_PORT))
            tk.Label(self.dynamic,
                     text="Used by the Windows Service and the standalone server.\n"
                          "Under IIS the site binding decides.",
                     bg=BG, fg=SUBTEXT, font=font("micro"),
                     justify="left").pack(anchor="w", pady=(3, 0))

        elif key == "storekeeper":
            self._build_url_field(self.dynamic)
            # The admin password, and only that. This is the app that records
            # every movement in the store, and standing one up used to need
            # nothing but a Server URL. It is a control over who installs one
            # and points it at the store's server, not a network boundary:
            # POST /transactions is deliberately unauthenticated (ADR-0002), so
            # this stops nobody from doing what a Storekeeper does.
            tk.Label(self.dynamic,
                     text="Admin password, verified against the server",
                     bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(10, 2))
            self.v_sk_pw = tk.StringVar()
            e_sk = tk.Entry(self.dynamic, textvariable=self.v_sk_pw,
                            show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                            font=font("label"), insertbackground=TEXT,
                            highlightthickness=1,
                            highlightbackground=DANGER,
                            highlightcolor="#ef9a9a")
            e_sk.pack(fill="x", ipady=8)
            ui_kit.reveal(e_sk)
            tk.Label(self.dynamic,
                     text="Only an admin installs the Storekeeper.",
                     bg=BG, fg=WARNING, font=font("micro")).pack(anchor="w", pady=(3, 0))
            self.v_dir.set(os.path.join(
                os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                "AssetManager", "Storekeeper"))

        elif key == "notifier":
            self._build_url_field(self.dynamic)
            tk.Label(self.dynamic, text="Assign this computer to",
                     bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(8, 2))
            member_row = tk.Frame(self.dynamic, bg=BG)
            member_row.pack(fill="x")
            # Blank until someone picks: a first name preselected assigned
            # laptops to whoever sorts first, and nothing refused it. The list
            # is fetched when there is a URL to ask, and on Reload or on
            # leaving the URL field after that.
            url = self.v_url.get().strip()
            self.v_member = ttk.Combobox(
                member_row, state="readonly", font=font("value"),
                values=fetch_members(url) if url else list(TEAM_MEMBERS))
            self.v_member.pack(side="left", fill="x", expand=True, ipady=4)
            def _reload_members(_e=None):
                url = self.v_url.get().strip()
                if not url:
                    return
                vals = fetch_members(url)
                self.v_member["values"] = vals
                if self.v_member.get() not in vals:
                    self.v_member.set("")
            self.url_entry.bind("<FocusOut>", _reload_members)
            tk.Button(member_row, text="Reload", bg=CARD2, fg=TEXT,
                      relief="flat", cursor="hand2", font=font("body"),
                      padx=10, command=_reload_members).pack(side="left",
                                                             padx=(6, 0))
            tk.Label(self.dynamic,
                     text="Reload asks the server for the latest engineer list.",
                     bg=BG, fg=SUBTEXT, font=font("micro")).pack(anchor="w", pady=(2, 0))

            # The engineer's own password, or the admin password. It used to be
            # the admin password alone, which meant an engineer could not install
            # their own Notifier without being handed the password that also
            # opens Clear All Records. The caption names both rather than asking
            # the server which one this engineer has: the server refuses an own
            # password that was never set, so the offer costs nothing and the
            # installer needs no second opinion to word a label.
            tk.Label(self.dynamic,
                     text="Password: this engineer's own, or the admin password",
                     bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(10, 2))
            self.v_notifier_pw = tk.StringVar()
            e_nt = tk.Entry(self.dynamic, textvariable=self.v_notifier_pw,
                            show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                            font=font("label"), insertbackground=TEXT,
                            highlightthickness=1,
                            highlightbackground=DANGER,
                            highlightcolor="#ef9a9a")
            e_nt.pack(fill="x", ipady=8)
            ui_kit.reveal(e_nt)
            tk.Label(self.dynamic,
                     text="Checked against the server. Installation is blocked without it.",
                     bg=BG, fg=WARNING, font=font("micro")).pack(anchor="w", pady=(3, 0))

            self.v_dir.set(os.path.join(
                os.environ.get("APPDATA", os.path.expanduser("~")),
                "AssetManager", "Notifier"))

    def _build_url_field(self, parent):
        tk.Label(parent, text="Server URL",
                 bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(0, 2))
        if not hasattr(self, 'v_url'):
            self.v_url = tk.StringVar(value="")
        url_e = tk.Entry(parent, textvariable=self.v_url,
                         bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
        url_e.pack(fill="x", ipady=7)
        self.url_entry = url_e
        self._hint(url_e, self.v_url, SERVER_URL_HINT)

    def _hint(self, entry, var, text):
        """Grey `text` over `entry` while `var` is empty.

        A label laid over the field rather than text in it, so the variable
        never holds the hint and nothing that reads it has to know one exists.
        """
        hint = tk.Label(entry, text=text, bg=INPUT_BG, fg=FAINT,
                        font=entry.cget("font"), cursor="xterm")
        hint.bind("<Button-1>", lambda e: entry.focus_set())
        def _show(*_):
            if var.get():
                hint.place_forget()
            else:
                hint.place(x=1, rely=0.5, anchor="w")
        _show()
        # The variable can outlive the field (v_url does, across a card
        # switch), so the trace goes with the field rather than piling up.
        trace = var.trace_add("write", _show)
        entry.bind("<Destroy>",
                   lambda e: var.trace_remove("write", trace), add="+")

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Choose Install Directory")
        if d:
            self.v_dir.set(d)
            # The Port field is the port of the directory it is pointed at, so
            # a directory chosen after the panel was built re-reads it.
            if self.v_component.get() == "server" and hasattr(self, "v_port"):
                self.v_port.set(_existing_port(d) or "")

    # ── Install logic ──────────────────────────────────────────────────────────

    def _install(self):
        self.err_lbl.config(text="", fg=DANGER)
        # A click is a person asking, on purpose, once - not a tick - so a
        # fingerprint prompt refused on an earlier click is offered again
        # rather than leaving this process to report a reachable server as
        # unreachable for as long as it stays open. common.py owns why it is
        # one per process everywhere else, and names this the one caller that
        # may re-arm it.
        common.reset_cert_prompt()
        key      = self.v_component.get()
        dest_dir = self.v_dir.get().strip()

        if not dest_dir:
            self.err_lbl.config(text="Choose an install directory.")
            return

        mode = _payload_mode(key)
        if mode is None:
            if key == "server" and _payload_mode("notifier") == "source":
                # A source bundle on purpose carries no server: see SOURCE_FILES.
                self.err_lbl.config(
                    text="This is a source install bundle, which does not include the\n"
                         "server. Install the server with tools\\install-iis.ps1.")
            else:
                self.err_lbl.config(
                    text=f"Payload not found for {key}: expected {BUNDLED_EXES[key]}\n"
                         "or the .py files plus lib. Re-download the installer.")
            return

        if key == "notifier":
            self._install_notifier(dest_dir)
        elif key == "server":
            self._install_server(dest_dir)
        elif key == "storekeeper":
            self._install_storekeeper(dest_dir)


    def _report_unreachable(self, server_url, component):
        """Say the check could not be made - not that the password was wrong.

        Both the Notifier and the Storekeeper verify live before writing
        anything, and a server that cannot be reached is a different failure
        from a refusal: reporting it as a wrong password sends whoever is
        installing off to hunt for a password that was never the problem.
        """
        # _ssl_cert_source(), not _SSL_CERT_PATH. "Is there a certificate to
        # install" is one question and the three install paths all ask it that
        # way; asking it here by path meant this line and those three could
        # disagree, and they agreed only because nothing has bundled a
        # certificate since 061. This sentence is the one thing an operator is
        # offered as a way out, so it is the worst line here to be right by
        # accident.
        hint = ("\n(For HTTPS: accept the certificate when offered, or copy"
                "\nssl_cert.pem next to the installer.)"
                if server_url.startswith("https")
                and _ssl_cert_source() is None else "")
        self.err_lbl.config(
            text="\u26a0  Cannot reach server at the URL above.\n"
                 f"Make sure the server is running before installing the "
                 f"{component}." + hint,
            fg=DANGER)

    def _ensure_python(self):
        """Put CPython PYTHON_SERIES on this machine if it is not there already.

        Silent throughout - the Windows installer runs under /quiet, so the only
        thing on screen is the bar. Three sources in order: an installer next to
        AssetManager_Setup.exe, the copy embedded at build time, and only then a
        download from python.org, so a laptop with no route out still installs
        from what was shipped to it.

        It is deliberately **not** a gate. In exe mode the client carries its own
        interpreter and runs whether this succeeded or not, so a machine that
        cannot reach python.org is told what is missing rather than refused an
        install that would have worked.

        In source mode it is load-bearing rather than a convenience: what the
        shortcut must name is a Python matching lib\\PYVER, which is not
        necessarily the one that opened this installer, and _deploy_component
        refuses the install outright when none is on the machine. Running here
        first is what gives that refusal something to find.

        The worker only writes to `state`; every widget is touched from this
        thread, because tkinter from a second thread is a crash on somebody
        else's laptop.
        """
        wanted = _lib_pyver(_payload_root()) or PYTHON_SERIES
        if wanted != PYTHON_SERIES:
            # A lib\ vendored for some other minor. Only 3.12 is pinned
            # here, so installing it would not answer the question -
            # _deploy_component refuses and names the version instead.
            return
        if _python_installed(wanted):
            return
        import threading, time

        state = {"phase": "verify", "done": 0, "total": 0, "error": None}
        win   = _ProgressWindow(self.root, "Installing Python %s" % PYTHON_SERIES)

        def work():
            tmpdir = None
            try:
                setup = _python_setup_source()
                if setup is None:
                    import tempfile
                    state["phase"] = "download"
                    tmpdir = tempfile.mkdtemp(prefix="am-python-")
                    setup  = os.path.join(tmpdir, PYTHON_SETUP)
                    _download(PYTHON_URL, setup,
                              lambda d, t: state.update(done=d, total=t))
                state["phase"] = "verify"
                if not _signed_by_psf(setup):
                    state["error"] = ("%s is not signed by the %s."
                                      % (os.path.basename(setup), PYTHON_SIGNER))
                    return
                state["phase"] = "install"
                rc = _run_hidden([setup] + PYTHON_ARGS, timeout=1800).returncode
                # 3010 is "installed, wants a reboot" - the interpreter is there.
                if rc not in (0, 3010):
                    state["error"] = "The Python installer exited with code %d." % rc
            except Exception as ex:
                state["error"] = str(ex)
            finally:
                # Only what this function fetched. A copy sitting beside
                # AssetManager_Setup.exe, or embedded at build time, is the
                # admin's or the build's and is not ours to remove - the one
                # downloaded here is 25 MB under a name nothing will look for
                # again, left on every install that had no local copy.
                # Sharpest on the refusal above: a file that failed the
                # signature check is the last thing to leave sitting on disk
                # named as Python's own installer. ignore_errors, because
                # failing to delete a temporary copy of something that can be
                # fetched again must never be what fails an install - the same
                # reason this whole step warns rather than gates.
                if tmpdir:
                    shutil.rmtree(tmpdir, ignore_errors=True)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        while worker.is_alive():
            win.render(state)
            time.sleep(0.03)
        win.close()

        if state["error"] is None and _python_installed() is None:
            state["error"] = "Python %s is still not on this machine." % PYTHON_SERIES
        if state["error"]:
            messagebox.showwarning(
                "Python %s was not installed" % PYTHON_SERIES,
                "%s\n\nThe app is being installed anyway. If it does not start, "
                "install Python %s by hand - or ask IT to - and launch it again."
                % (state["error"], PYTHON_SERIES))

    def _install_notifier(self, dest_dir):
        # Read off the card. _on_component_change builds all three before this
        # can be clicked - it runs once at startup and again on every radio -
        # so the getattr defaults that stood here were standing in for
        # attributes that are never missing. The engineer's was also wrong: the
        # default was a class rather than an instance, so .get() was an unbound
        # function called with no arguments and would have raised TypeError
        # inside a lambda rather than answering with the first engineer it is
        # written to answer with. An attribute genuinely absent is now an
        # AttributeError naming it, which is a better answer than either.
        member     = self.v_member.get()
        server_url = self.v_url.get().strip().rstrip("/")
        pw         = self.v_notifier_pw.get().strip()

        if not server_url:
            self.err_lbl.config(text="\u274c  Enter the server URL.", fg=DANGER)
            return
        if not member:
            self.err_lbl.config(text="\u274c  Select the engineer for this PC.", fg=DANGER)
            return
        if not pw:
            self.err_lbl.config(
                text="\u274c  Enter this engineer's own password, or the admin password.",
                fg=DANGER)
            return

        # The engineer's own password opens their own install; the admin
        # password opens any. It used to be the admin password alone, which
        # meant an engineer could not install their own Notifier without being
        # handed the password that also opens Clear All Records.
        #
        # Checked against *this* engineer, not against whoever answered:
        # accepting any own password for any name would let one engineer install
        # a Notifier configured as another and then confirm or reject that
        # person's Transactions. The shared verifier in common.py is what asks,
        # so the fallback for a server that predates /auth/verify lives in one
        # place rather than being copied in here.
        # A Temporary Own Password installs a Notifier, and deliberately so:
        # the replacement is the Notifier's to demand and there is no Notifier
        # running yet, while refusing the install would refuse the Engineer the
        # one thing the password was handed to them for. So must_change_password
        # is read here and acted on nowhere - the engineer is asked the first
        # time they authenticate into Settings on the client this is installing.
        # See ADR-0009.
        self.err_lbl.config(text="Verifying password...", fg=SUBTEXT)
        self.root.update()
        try:
            if not verify_password(server_url, member, pw).get("valid"):
                self.err_lbl.config(
                    text="\u274c  Wrong password. Installation blocked.", fg=DANGER)
                return
        except Exception:
            self._report_unreachable(server_url, "Notifier")
            return

        try:
            # The client apps run on CPython 3.12 (rule 13). Asked for after
            # the password check so a wrong password is not answered with a
            # several-minute Python install, and before the payload is copied
            # so the interpreter is there by the time the shortcut exists.
            # Inside the try, because what runs here is a render loop on the
            # Tk thread for as long as the Python installer takes: a TclError
            # out of it escapes to Tk's own handler, which under a windowed
            # exe writes to a console that is not there, so the install stops
            # with an empty error label and nothing anywhere saying why. What
            # keeps this step from being a gate is its own warn-and-carry-on
            # reporting, not its position relative to this try.
            self._ensure_python()

            target, args, workdir, icon = _deploy_component("notifier", dest_dir)
            _cert_src = _ssl_cert_source()
            if _cert_src:
                shutil.copy2(_cert_src, os.path.join(dest_dir, "ssl_cert.pem"))
            cfg = {
                "server_url":     server_url,
                "current_user":   member,
                "poll_interval":  15,
                "setup_complete": True,
            }
            with open(os.path.join(dest_dir, "config.json"), "w") as f:
                json.dump(cfg, f, indent=2)

            made = _create_shortcut(target, f"Asset Notifier \u2014 {member.split()[0]}",
                                    args, workdir, icon)

            messagebox.showinfo(
                "Installation Complete \u2714",
                f"\u2705  Notifier installed successfully for  {member}\n\n"
                f"Location: {dest_dir}\n\n"
                + _launch_note(made, target, args)
            )
            self.root.destroy()
        except PythonMismatch as e:
            # Its own branch rather than the line below: this message is
            # several sentences and names a version to install, while
            # err_lbl is a single label with no wraplength.
            self.err_lbl.config(text="❌  Wrong Python version.", fg=DANGER)
            messagebox.showerror("Asset Manager — Wrong Python version", str(e))
        except Exception as e:
            self.err_lbl.config(text=f"Install failed: {e}", fg=DANGER)

    def _install_server(self, dest_dir):
        # Off the card, for the reason _install_notifier gives.
        pw  = self.v_admin_pw.get()
        pw2 = self.v_admin_pw2.get()
        if not pw:
            self.err_lbl.config(text="✗  Enter an admin password.", fg=DANGER)
            return
        # The bound and the sentence under it both read the constant, so a
        # raise moves what the operator is told as well as what is refused.
        if len(pw) < PASSWORD_MIN:
            self.err_lbl.config(
                text="✗  Password must be at least %d characters." % PASSWORD_MIN,
                fg=DANGER)
            return
        if pw != pw2:
            self.err_lbl.config(text="✗  Passwords do not match.", fg=DANGER)
            return
        # 1-65535, and deliberately no refusal of 443: that block was removed
        # everywhere in #48 because the port is no longer blocked on this
        # network, and a copy of it here would be a rule with no original.
        # Inline rather than server.py's _validate_port - this file does not
        # import the server and is not going to start.
        port_s = self.v_port.get().strip()
        if not port_s.isdigit() or not (1 <= int(port_s) <= 65535):
            self.err_lbl.config(text="✗  Port must be a whole number from 1 to 65535.",
                                fg=DANGER)
            return
        port = int(port_s)
        try:
            import subprocess
            dst, args, workdir, icon = _deploy_component("server", dest_dir)
            cert_copied = False
            key_copied  = False
            _cert_src = _ssl_cert_source()
            if _cert_src:
                shutil.copy2(_cert_src, os.path.join(dest_dir, "ssl_cert.pem"))
                cert_copied = True
            if os.path.exists(_SSL_KEY_PATH):
                shutil.copy2(_SSL_KEY_PATH, os.path.join(dest_dir, "ssl_key.pem"))
                key_copied = True

            # The password the operator was asked for, into the file that
            # also holds every capability password they were not asked about.
            # _write_admin_cfg keeps the rest of it and says so when it cannot
            # be read - the same two answers the port write below gives, since
            # two doors in one function must not answer one question two ways.
            admin_note = _write_admin_cfg(dest_dir, pw)

            # Preserve or create server_config.json
            srv_cfg_path = os.path.join(dest_dir, "server_config.json")
            port_note = ""
            if os.path.exists(srv_cfg_path):
                # Reinstall — change the one key the operator was asked for and
                # keep the rest. Read-modify-write, never a fresh dict: this
                # file also holds ssl_enabled, db_path, storekeeper_name and
                # theme, and replacing it turns HTTPS off on the next restart
                # with both cert files still on disk, where nothing looks wrong
                # until a client fails to verify. A file that cannot be read is
                # left alone for the same reason, and said so in the popup - the
                # port is worth less than what is already in there.
                try:
                    with open(srv_cfg_path) as f:
                        srv_cfg = json.load(f)
                    if not isinstance(srv_cfg, dict):
                        raise ValueError("not a JSON object")
                    srv_cfg["port"] = port
                    with open(srv_cfg_path, "w") as f:
                        json.dump(srv_cfg, f, indent=2)
                except Exception as cfg_err:
                    port_note = (
                        f"\n\n⚠️  Port left unchanged: server_config.json could not "
                        f"be read ({cfg_err}).\n"
                        f'    Nothing in it was replaced. Set "port": {port} by hand.'
                    )
            else:
                # Fresh install — enable SSL only when BOTH cert and key were bundled
                srv_cfg = {"host": "0.0.0.0", "port": port}
                if cert_copied and key_copied:
                    srv_cfg["ssl_enabled"] = True
                with open(srv_cfg_path, "w") as f:
                    json.dump(srv_cfg, f, indent=2)

            # Register the Windows Service then start it in background
            # (onefile EXE extraction takes time; we don't block the installer)
            svc_note = ""
            svc_argv, svc_cmd = _service_command(dst, args, "install")
            try:
                subprocess.run(svc_argv, check=True,
                               capture_output=True, timeout=60)
                # Fire-and-forget — service starts in background, no timeout risk
                subprocess.Popen(["net", "start", "AssetManagerServer"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                svc_note = "\n\n✅  Windows Service registered and starting in background."
            except subprocess.CalledProcessError as svc_err:
                svc_note = (
                    "\n\n⚠️  Service registration failed (run installer as Administrator).\n"
                    f"    Error: {svc_err.stderr.decode(errors='replace').strip() or svc_err}\n\n"
                    "    To register manually (as Administrator):\n"
                    f"    {svc_cmd}\n"
                    '    net start AssetManagerServer'
                )
            except Exception as svc_err:
                svc_note = (
                    f"\n\n⚠️  Service registration failed: {svc_err}\n\n"
                    "    To register manually (as Administrator):\n"
                    f"    {svc_cmd}\n"
                    '    net start AssetManagerServer'
                )

            # The arguments and the working directory, not the target
            # alone: in source mode - which is the only mode there is
            # (rule 14) - dst is pythonw.exe and the launcher is its argument,
            # so a shortcut handed the target by itself starts an interpreter
            # with no script and exits without ever drawing a window. Both
            # client installs pass all three and this one did not, which left
            # every server install with no working way to open the Server GUI.
            # Under IIS that window is the **whole** console: Server
            # Administration, Mail Settings, Backup / Restore, the Lookup
            # Sheet and Connected Clients are reached from nowhere else, and
            # the process that is actually serving is a session-0 app pool
            # worker with no window and no tray to reach them from.
            made = _create_shortcut(dst, "Asset Manager — Asset Server",
                                    args, workdir, icon)
            messagebox.showinfo(
                "Installation Complete ✔",
                f"✅  Asset Server installed successfully!\n\n"
                f"Location: {dst}\n"
                f"{svc_note}{admin_note}{port_note}"
                f"{_console_note(made, dst, args)}\n\n"
                f"IMPORTANT: Open port {port} in Windows Firewall:\n"
                "netsh advfirewall firewall add rule name=\"Asset Manager\" "
                f"dir=in action=allow protocol=TCP localport={port}"
            )
            self.root.destroy()
        except Exception as e:
            self.err_lbl.config(text=f"Install failed: {e}", fg=DANGER)

    def _install_storekeeper(self, dest_dir):
        # Off the card, for the reason _install_notifier gives.
        server_url = self.v_url.get().strip().rstrip("/")
        pw = self.v_sk_pw.get().strip()

        if not server_url:
            self.err_lbl.config(text="\u274c  Enter the server URL.", fg=DANGER)
            return
        if not pw:
            self.err_lbl.config(text="\u274c  Enter the admin password.", fg=DANGER)
            return

        # The admin-only door in common.py, not the shared verifier: that one
        # also accepts an engineer's own password, and an engineer is not who
        # installs this.
        self.err_lbl.config(text="Verifying admin password...", fg=SUBTEXT)
        self.root.update()
        try:
            if not verify_admin_password(server_url, pw):
                self.err_lbl.config(
                    text="\u274c  Wrong admin password. Installation blocked.", fg=DANGER)
                return
        except Exception:
            self._report_unreachable(server_url, "Storekeeper")
            return

        try:
            # The client apps run on CPython 3.12 (rule 13). Asked for after
            # the password check so a wrong password is not answered with a
            # several-minute Python install, and before the payload is copied
            # so the interpreter is there by the time the shortcut exists.
            # Inside the try, because what runs here is a render loop on the
            # Tk thread for as long as the Python installer takes: a TclError
            # out of it escapes to Tk's own handler, which under a windowed
            # exe writes to a console that is not there, so the install stops
            # with an empty error label and nothing anywhere saying why. What
            # keeps this step from being a gate is its own warn-and-carry-on
            # reporting, not its position relative to this try.
            self._ensure_python()

            target, args, workdir, icon = _deploy_component("storekeeper", dest_dir)
            _cert_src = _ssl_cert_source()
            if _cert_src:
                shutil.copy2(_cert_src, os.path.join(dest_dir, "ssl_cert.pem"))
            cfg = {"server_url": server_url}
            with open(os.path.join(dest_dir, "config.json"), "w") as f:
                json.dump(cfg, f, indent=2)
            made = _create_shortcut(target, "Asset Manager — Storekeeper", args,
                                    workdir, icon)
            messagebox.showinfo(
                "Installation Complete ✔",
                f"✅  Storekeeper App installed successfully!\n\n"
                f"Location: {dest_dir}\n\n"
                + _launch_note(made, target, args)
            )
            self.root.destroy()
        except PythonMismatch as e:
            # Its own branch rather than the line below: this message is
            # several sentences and names a version to install, while
            # err_lbl is a single label with no wraplength.
            self.err_lbl.config(text="❌  Wrong Python version.", fg=DANGER)
            messagebox.showerror("Asset Manager — Wrong Python version", str(e))
        except Exception as e:
            self.err_lbl.config(text=f"Install failed: {e}", fg=DANGER)


# ─── Shortcut helper (Windows VBScript) ──────────────────────────────────────

def _vbs_quote(value):
    """Escape a value for a VBScript double-quoted string literal.

    A double quote inside one is written twice. Nothing else needs escaping - a
    backslash is an ordinary character in VBScript, which is why a Windows path
    goes in as it stands.
    """
    return str(value).replace('"', '""')


def _launch_note(made, target_path, arguments):
    """The line a finished client install ends on: how to start the app.

    A shortcut is a convenience and its absence is not an install failure, so
    the window says which of the two happened rather than printing the same
    sentence either way - it said one had been created for as long as source
    mode had never once managed to create one.

    Where there is none, what is offered is the command itself rather than a
    file to double-click: in source mode the thing to run is pythonw.exe with a
    launcher as its argument, and the .pyw association that would make the
    launcher openable on its own is per-user and not guaranteed.
    """
    if made:
        return ("A Desktop shortcut has been created.\n"
                "Launch the app from that shortcut - it does not start on its own.")
    cmd = ('"%s" %s' % (target_path, arguments)).strip()
    return ("⚠️  No Desktop shortcut could be created.\n"
            "Start the app with:\n\n"
            "    " + cmd)


def _shortcut_vbs(target_path, name, arguments, cwd, icon_path=None):
    """The VBScript that writes one Desktop shortcut, as a string.

    Built here rather than inline in _create_shortcut so that what it says can
    be read without running cscript, which would put a real shortcut on the
    Desktop of whatever machine is asking. That matters for this script in
    particular: it is one string, a single unescaped value closes it early and
    fails the whole file to compile, and a failure to compile is silent from
    where the installer stands - which is how source mode went from release to
    release never once creating a shortcut. tools/client-checks.py reads it.

    IconLocation is written only when there is an icon to point at, with the
    `,0` index WSH expects. Exe mode passes none: a shortcut to an exe already
    shows that exe's icon, and a file beside it would be a second copy of the
    artwork with nothing keeping the two in step.
    """
    lines = [
        'Set WshShell = WScript.CreateObject("WScript.Shell")',
        'sLnk = WshShell.SpecialFolders("Desktop") & "\\%s.lnk"' % _vbs_quote(name),
        'Set oShortcut = WshShell.CreateShortcut(sLnk)',
        'oShortcut.TargetPath = "%s"' % _vbs_quote(target_path),
        'oShortcut.Arguments = "%s"' % _vbs_quote(arguments),
        'oShortcut.WorkingDirectory = "%s"' % _vbs_quote(cwd),
    ]
    if icon_path:
        lines.append('oShortcut.IconLocation = "%s,0"' % _vbs_quote(icon_path))
    lines += [
        'oShortcut.Save',
        'Set fso = WScript.CreateObject("Scripting.FileSystemObject")',
        'If fso.FileExists(sLnk) Then WScript.Echo "SHORTCUT-OK"',
    ]
    return "\n".join(lines) + "\n"


def _service_command(target_path, arguments, verb):
    """The argv and the printed line for one of the server's service verbs.

    The Windows Service is registered by running the server with a verb after
    it, and in source mode - which is the only mode there is (rule 14) - "the
    server" is two things: pythonw.exe and the launcher it is handed.
    _deploy_component answers with both for exactly that reason, and this call
    passed the target alone, so what ran was an interpreter with no script: it
    exits 0, registers nothing, and `net start` then fails against a service
    that was never created. The advice printed when it did fail was the same
    command written out by hand, so following it did the same nothing.

    One helper because the argv and the sentence are the same command, and a
    remedy that is not what was actually run is worse than no remedy at all.
    `arguments` is the quoted launcher _deploy_component built, or "" in exe
    mode, so it is unquoted for the argv and quoted again for the line.
    """
    argv = [target_path]
    inner = (arguments or "").strip()
    if inner:
        argv.append(inner[1:-1]
                    if inner.startswith('"') and inner.endswith('"')
                    else inner)
    argv.append(verb)
    return argv, " ".join(['"%s"' % a for a in argv[:-1]] + [verb])


def _console_note(made, target_path, arguments):
    """The line a finished server install ends on: how to open the console.

    Not _launch_note's, which says the app does not start on its own - the
    opposite of what a server does, since the Service and IIS both start it
    with nobody there. What this shortcut opens is the Server GUI, and that
    window is the console: Server Administration, Mail Settings, Backup /
    Restore, the Lookup Sheet and Connected Clients are reached from nowhere
    else. Under IIS it is the only way in at all, the serving process being an
    app pool worker in session 0 with no window and no tray, so an install
    that ends without one is an install with no console.
    """
    if made:
        return ("\n\n\U0001f5a5  A Desktop shortcut opens the Server GUI - the "
                "console for\n"
                "    Server Administration, Mail Settings and Backup / Restore.\n"
                "    The server itself is started by the Service or by IIS; the "
                "window watches it.")
    cmd = ('"%s" %s' % (target_path, arguments)).strip()
    return ("\n\n\u26a0\ufe0f  No Desktop shortcut could be created. Open the "
            "Server GUI - the console\n"
            "    for Server Administration, Mail Settings and Backup / Restore "
            "- with:\n\n"
            "    " + cmd)


def _create_shortcut(target_path, name, arguments="", workdir=None,
                     icon_path=None):
    """Create a Desktop shortcut using a temporary VBScript (Windows only).

    arguments and workdir exist for source mode, where target_path is
    pythonw.exe and the app is its argument. The working directory then has to
    be the install directory rather than the interpreter's, because every app
    resolves config.json and ssl_cert.pem relative to itself. icon_path is
    there for the same mode and the same reason: the shortcut points at
    pythonw.exe, so the icon it would otherwise show is Python's.

    The script itself is _shortcut_vbs's, so that it can be read by a check
    without running cscript.

    Every value goes through _vbs_quote on the way in. A source-mode argument is
    a quoted path, and pasting one into the script raw closed the VBScript
    string early and failed the whole file to compile — so source mode never got
    a shortcut at all, on any install, while the window went on saying one had
    been created. Exe mode passes no arguments, which is why it never showed.

    The Desktop comes from WSH rather than from %USERPROFILE%: on a domain
    machine that folder is redirected to OneDrive or to a home share often
    enough that writing to the literal path is writing somewhere that is not
    there.

    Returns True only when the script reports the .lnk on disk afterwards, and
    it reports that as a fixed ASCII token rather than by echoing the path back:
    cscript writes its output in the console codepage, which turns the em dash
    in both client shortcut names into a hyphen, and a path compared after that
    round trip names a file that does not exist. A failure here is still not
    fatal, but it is no longer silent: the caller says which of the two happened
    rather than claiming a shortcut nothing has seen.
    """
    try:
        import tempfile, subprocess
        cwd = workdir or os.path.dirname(target_path)
        vbs = _shortcut_vbs(target_path, name, arguments, cwd, icon_path)
        # utf-16 rather than the locale encoding: WSH reads a script with a BOM
        # as Unicode, and both client shortcut names carry an em dash that an
        # ANSI codepage is not guaranteed to be able to write.
        tmp = tempfile.NamedTemporaryFile(suffix=".vbs", delete=False, mode='w',
                                          encoding='utf-16')
        tmp.write(vbs)
        tmp.close()
        res = subprocess.run(["cscript", "//Nologo", tmp.name],
                             capture_output=True, timeout=10)
        os.unlink(tmp.name)
        if res.returncode != 0:
            return False
        return "SHORTCUT-OK" in res.stdout.decode(errors="replace")
    except Exception:
        return False  # Non-fatal — the caller reports it instead of assuming it worked


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()
