"""
Asset Manager - updating a client installation from a source zip.

What this replaces is a browser download and an engineer running an installer.
Since 061 the clients ship as .py files under a signed pythonw.exe (rule 12),
so the thing an update has to move is a zip of sources, the launchers and the
vendored lib\\ - and `tools/bundle-client.ps1` already builds exactly that zip,
`<App>-<version>.zip`, with a manifest carrying `app`, `version`,
`python_version`, `launcher` and a SHA-256 per file. Nothing an update
transfers is an executable of ours, which is what keeps this path out of
Defender ASR's way (docs/it-asr-and-signing-request.md).

TWO PHASES, AND THE SPLIT IS THE POINT

  fetch/update_now   runs INSIDE the app being updated. It asks the server what
                     is published, downloads the zip over `common.py`'s pinned
                     session and verifies it whole - and only then is anything
                     stopped. A download found to be short after the app is
                     already down leaves a Notifier that is not running, which
                     is an engineer who stops being asked to confirm anything
                     while the store carries on recording movements.

  --apply            runs as a SEPARATE pythonw.exe, spawned by the app just
                     before it quits. It waits for that process to go, saves
                     every file it is about to overwrite, extracts, starts the
                     app again and checks it stayed up.

The applier imports nothing but the standard library, and `common.py` is
imported inside `fetch` rather than at the top of this file for that reason:
the applier is overwriting `common.py` and `ui_kit.py` while it runs, and code
that has not been imported yet is exactly the code that must not be needed
then. This file overwrites itself too, which is safe for the same reason
`tools/update.ps1` may replace itself on the server: CPython reads and compiles
a script whole before executing a line of it, and closes the file.

WHY THE WINDOW IS SOMEBODY ELSE'S

There is no Tk in here. Which dialog an app shows, and what it says while it
waits, is the app's decision - the same split `common.py` makes for the
certificate prompt, where the transport layer has no business opening a window.
What this module offers is one call that either returns having staged an
update, or raises UpdateRefused carrying a sentence fit to show a person.

WHAT IS DELIBERATELY NOT TOUCHED

The zip is a payload, not a directory image. `config.json`, `ssl_cert.pem`,
`client.log`, `seen_rejections.json`, `pending_buffer.json` and
`update_state.json` are this installation's rather than the build's, and only
the entries named in the zip's own manifest are ever written. A
`pending_buffer.json` lost in an update is a submission that never reaches the
store.
"""

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))

UPDATE_LOG   = os.path.join(HERE, "update.log")
ROLLBACK_DIR = os.path.join(HERE, "update_rollback")
LAUNCH_ERR   = os.path.join(HERE, "launch.err.log")

# What phase two leaves behind for the app that starts next, and the whole of
# why this file can be said to have reported anything. The System Log is written
# by the server and shipped by a client; this process is neither - it imports
# nothing of ours (it is overwriting `common.py` while it runs) and by the time
# it has an outcome there is no app left holding a log queue. So the outcome is
# written down here and `common.report_update_result` turns it into the entry.
# Nothing else reads it, and it is in no manifest, so `_extract` cannot touch
# it: it joins `config.json` and `update_state.json` on the list of files an
# update leaves exactly as it found them.
UPDATE_RESULT = os.path.join(HERE, "update_result.json")

# How long the applier waits for the app it is replacing to exit. Python holds
# no handle on a .py file, but lib\\ carries loaded .pyd extensions and Windows
# will not let those be replaced under a running process - so this wait is what
# makes the extraction possible rather than a courtesy. An app still there at
# the end of it is left alone: nothing is overwritten and nothing is restarted,
# because it never stopped.
EXIT_WAIT_SECONDS = 60

# How long the restarted app has to not fail. applaunch.py reports a startup
# failure by appending to launch.err.log and then opening a message box, so the
# process is still alive while somebody reads it - which is why staying alive is
# not on its own the health check.
HEALTH_SECONDS = 12

# Under pythonw.exe there is no console and no window, so an applier that dies
# is completely silent. This is its launch.err.log: a handful of lines per
# update, and an update is a thing that happens a few times a year.
_LOG_PREFIX = "[client_update]"

# The prefix fetch() stamps on its own staging folder (tempfile.mkdtemp below)
# and the only prefix apply_update() will remove a whole folder for - one
# constant so the two cannot drift apart.
_STAGING_PREFIX = "am-update-"


class UpdateRefused(Exception):
    """The update will not be applied, and nothing has been stopped yet.

    Every message this carries is shown to whoever is at the machine, so each
    one says what was wrong and what would fix it.
    """


def log(message):
    """Append a line to update.log. Never raises - it is the diagnostic path."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(UPDATE_LOG, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s %s\n" % (stamp, _LOG_PREFIX, message))
    except Exception:
        pass


# ─── Phase one: ask, download, verify ─────────────────────────────────────────

def _running_python():
    return "%d.%d" % sys.version_info[:2]


def fetch(app_key, server_url, current_version):
    """Download and verify the published zip for `app_key`. Returns its path.

    Nothing outside a scratch directory is written and nothing is stopped, so
    every refusal here costs an engineer a message box and no more.
    """
    import common      # see the module docstring: not a top-level import

    server_url = (server_url or "").rstrip("/")

    # ADR-0010's first-contact confirmation is answered by a person reading a
    # fingerprint down a phone. An update has nobody to ask - it is offered
    # while the app is already running and the answer decides what code this
    # machine executes next - so with no certificate on disk this refuses and
    # says where the question belongs, rather than letting common.api open the
    # prompt on its behalf.
    if server_url.startswith("https") and not os.path.exists(common.SSL_CERT_PATH):
        raise UpdateRefused(
            "This installation has not yet trusted the server's certificate, "
            "so an update cannot be downloaded.\n\n"
            "Start the app and accept the server's fingerprint when it asks, "
            "then check for updates again.")

    try:
        r = common.api("get", "%s/version" % server_url, timeout=10)
    except Exception:
        raise UpdateRefused("The server could not be reached to check for updates.")
    if not r.ok:
        raise UpdateRefused("The server answered %d when asked what version is "
                            "published." % r.status_code)

    data   = r.json()
    latest = str(data.get("latest", ""))
    entry  = (data.get("client_packages") or {}).get(app_key) or {}
    if not entry.get("path"):
        raise UpdateRefused(
            "This server has no downloadable package for this app.\n\n"
            "It may be running a build from before in-app updates, or the "
            "release was not copied into the dist folder beside it. Ask your "
            "admin to update this PC.")

    expected_sha  = str(entry.get("sha256", "")).lower()
    expected_size = entry.get("size")
    if not expected_sha:
        raise UpdateRefused("The server did not state a checksum for the update, "
                            "so it cannot be verified. Ask your admin.")

    staging = tempfile.mkdtemp(prefix=_STAGING_PREFIX)
    zip_path = os.path.join(staging, entry.get("filename") or "update.zip")
    log("downloading %s for %s (have %s, latest %s)"
        % (os.path.basename(zip_path), app_key, current_version, latest))

    try:
        r = common.api("get", "%s%s" % (server_url, entry["path"]),
                       timeout=120, stream=True)
        if not r.ok:
            raise UpdateRefused("The server answered %d for the update download."
                                % r.status_code)
        h = hashlib.sha256()
        written = 0
        with open(zip_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                fh.write(chunk)
                h.update(chunk)
                written += len(chunk)
    except UpdateRefused:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateRefused("The update could not be downloaded. The connection "
                            "to the server was lost.")

    # Verified whole before anything is stopped. A truncated download is the
    # ordinary failure here - a laptop carried out of range mid-transfer - and
    # it has to be caught while the app is still running.
    try:
        if expected_size is not None and written != int(expected_size):
            raise UpdateRefused(
                "The update did not download completely (%d of %s bytes). "
                "Try again." % (written, expected_size))
        if h.hexdigest() != expected_sha:
            raise UpdateRefused(
                "The downloaded update does not match the checksum the server "
                "stated, so it will not be installed. Try again, and tell your "
                "admin if it keeps happening.")
        manifest = read_manifest(zip_path)
        _check_manifest(manifest, app_key, latest)
    except UpdateRefused:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    log("verified %s (%d bytes, python %s)"
        % (os.path.basename(zip_path), written, manifest.get("python_version")))
    return zip_path


def read_manifest(zip_path):
    """The manifest inside a client zip, or a refusal naming what was wrong."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception:
        raise UpdateRefused("The downloaded file is not a readable Asset Manager "
                            "package. Try again, and tell your admin if it keeps "
                            "happening.")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise UpdateRefused("The downloaded package has no file list in it and "
                            "will not be installed.")
    return manifest


def _escapes_install(name):
    """True when a manifest entry could be written outside the install directory.

    `_extract` joins each of these onto `dest`, and os.path.join with an
    absolute second argument throws the first away, while a `..` walks up. What
    that costs is not a new way in - the zip is already checked against the
    digest the server published, and a package that could be chosen freely
    carries .py files the app then runs - it is the **rollback**.
    `_save_for_rollback` walks this same list to decide what to put aside, so a
    name pointing outside `dest` is either not there (nothing is saved) or is
    some other file on the machine (the wrong thing is saved). Either way the
    restore cannot put back what `_extract` then overwrote, and a failed update
    stays failed with files somewhere nobody will look.

    Checked in phase one with the size, the digest and the rest, because that is
    the whole point of the split: every refusal happens while the app is still
    running.

    Both separators are treated as separators whichever platform this runs on -
    the packages are built on Windows and the applier runs there, so a `\\` in a
    name is a separator in practice however posixpath reads it.
    """
    if not isinstance(name, str) or not name.strip():
        return True
    slashed = name.replace("\\", "/")
    # A drive letter ("C:/x") is absolute on Windows and just a filename on
    # posix, so it is refused by hand rather than left to os.path.isabs.
    if os.path.isabs(name) or os.path.isabs(slashed) or ":" in slashed.split("/")[0]:
        return True
    depth = 0
    for part in slashed.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return depth == 0        # nothing but separators and dots is not a file


def _check_manifest(manifest, app_key, latest):
    """Refuse a package this machine could download and then not start.

    Rule 13: the vendored lib\\ carries cp3xx compiled extensions and runs under
    one Python minor version and no other. applaunch.py refuses a mismatch at
    startup - which, for an update, is after the old files are gone and the app
    is already down. So the same question is asked here, against the interpreter
    this very process is running under, which is by definition the one the
    restarted app will use.
    """
    if manifest.get("app") and manifest["app"] != app_key:
        raise UpdateRefused("The server offered a package for the %s app, not "
                            "this one. Tell your admin."
                            % manifest.get("app"))
    if latest and manifest.get("version") and manifest["version"] != latest:
        raise UpdateRefused("The package is version %s but the server publishes "
                            "%s. Tell your admin."
                            % (manifest["version"], latest))
    wanted  = manifest.get("python_version")
    running = _running_python()
    if wanted and wanted != running:
        raise UpdateRefused(
            "This update was built for Python %s and this PC runs the app under "
            "Python %s.\n\nIt has not been installed, and the app is untouched. "
            "Install Python %s and check for updates again, or ask IT."
            % (wanted, running, wanted))
    if not manifest.get("launcher"):
        raise UpdateRefused("The package does not say how the app is started "
                            "and will not be installed.")
    outside = sorted(n for n in manifest["files"] if _escapes_install(n))
    if _escapes_install(manifest["launcher"]):
        outside.append(str(manifest["launcher"]))
    if outside:
        raise UpdateRefused(
            "The package lists a file that would be written outside the app's "
            "own folder, so it will not be installed:\n\n%s\n\nThe app is "
            "untouched. Tell your admin."
            % "\n".join("    " + n for n in outside[:5]))


def spawn_apply(zip_path, from_version):
    """Start the applier and return. The caller then has to quit.

    Detached, because the process that spawns it is about to exit and the
    applier's whole job begins after that.
    """
    args = [sys.executable, os.path.join(HERE, os.path.basename(__file__)),
            "--apply", zip_path,
            "--dest", HERE,
            "--wait-pid", str(os.getpid()),
            "--from-version", str(from_version)]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log("spawning applier for %s" % os.path.basename(zip_path))
    subprocess.Popen(args, cwd=HERE, close_fds=True, creationflags=flags)


def update_now(app_key, server_url, current_version):
    """Fetch, verify, and hand over to the applier. The caller then quits.

    The one call an app makes. It returns only once an update is staged and
    verified and the applier is waiting for this process to go; every other
    outcome is an UpdateRefused carrying a sentence to show.
    """
    zip_path = fetch(app_key, server_url, current_version)
    spawn_apply(zip_path, current_version)


# ─── Phase two: wait, save, extract, restart ─────────────────────────────────

def _wait_for_exit(pid, seconds=EXIT_WAIT_SECONDS):
    """True once the process has gone. Windows handles, not os.kill.

    os.kill on Windows terminates for every signal including 0, so the usual
    "send nothing and see if it raises" probe would kill the app it is asking
    about. OpenProcess with SYNCHRONIZE and WaitForSingleObject ask the
    question the kernel is actually holding the answer to, and cost nothing
    while waiting.
    """
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return True                      # already gone, or never ours to see
    try:
        return k32.WaitForSingleObject(handle, int(seconds * 1000)) == WAIT_OBJECT_0
    finally:
        k32.CloseHandle(handle)


def _stamp(path):
    """(mtime, size) of a file, or None. What a health check compares."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _save_for_rollback(dest, names, rollback):
    """Copy every file the extraction will overwrite into rollback.

    lib\\ moves wholesale rather than file by file: it is replaced wholesale
    below for the reason installer.py replaces it wholesale, and several hundred
    copies is a great deal of disk churn for a directory that has to go back as
    one thing anyway.
    """
    os.makedirs(rollback, exist_ok=True)
    lib_src = os.path.join(dest, "lib")
    if os.path.isdir(lib_src):
        lib_dst = os.path.join(rollback, "lib")
        shutil.rmtree(lib_dst, ignore_errors=True)
        shutil.move(lib_src, lib_dst)
    for name in names:
        if name.startswith("lib/"):
            continue
        src = os.path.join(dest, name.replace("/", os.sep))
        if not os.path.exists(src):
            continue
        dst = os.path.join(rollback, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def _clear_old_generations():
    """Leave update_rollback\\ holding nothing, so this update writes the only one.

    `rollback` is named after the version being replaced, which is different on
    every update, so clearing that one subdirectory cleared nothing that was
    already there: each update added a generation beside the last and
    update_rollback\\ grew a whole vendored lib\\ per update, for ever, on every
    engineer's laptop. Nothing ever read the old ones - apply_update restores
    from update_rollback\\<from_version>\\ and from nowhere else, and that is
    always the version currently installed, so every generation but the newest
    describes a build that is not on this machine.

    Called **before** _save_for_rollback, which is before a byte of the install
    has moved. That is the only moment at which there is nothing to lose: what
    is set aside next is copies of files that are live in the install right
    now. Doing it at the end of a successful update instead would put the
    deletion inside the window the bullet in CLAUDE.md warns about, where
    deleting this directory during an update is how a failed one stays failed.

    Everything goes, the incoming generation's own name included: a previous
    run of this same version may have left one there, and it describes the
    build being replaced no better than the rest of them do.
    """
    try:
        leaves = os.listdir(ROLLBACK_DIR)
    except OSError:
        return                            # nothing there yet, which is fine
    for leaf in leaves:
        path = os.path.join(ROLLBACK_DIR, leaf)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError as exc:
                log("could not remove %s: %s" % (leaf, exc))


def _restore(dest, rollback):
    """Put back what _save_for_rollback set aside. Best effort, and logged."""
    lib_saved = os.path.join(rollback, "lib")
    if os.path.isdir(lib_saved):
        lib_dst = os.path.join(dest, "lib")
        shutil.rmtree(lib_dst, ignore_errors=True)
        try:
            shutil.copytree(lib_saved, lib_dst)
        except Exception as exc:
            log("could not restore lib: %s" % exc)
    for root, _dirs, files in os.walk(rollback):
        for leaf in files:
            src = os.path.join(root, leaf)
            rel = os.path.relpath(src, rollback)
            if rel.split(os.sep)[0] == "lib":
                continue
            try:
                shutil.copy2(src, os.path.join(dest, rel))
            except Exception as exc:
                log("could not restore %s: %s" % (rel, exc))


def _extract(zip_path, dest, names):
    """Write exactly the manifest's entries over dest, and nothing else.

    lib\\ is emptied first rather than merged into: a module left behind by an
    older pin would still be found on applaunch's sys.path entry and shadow the
    new one, which is the sort of thing that only shows up on an engineer's
    laptop. Its old copy is already in rollback by the time this runs.
    """
    shutil.rmtree(os.path.join(dest, "lib"), ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in names:
            target = os.path.join(dest, name.replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def _relaunch(dest, launcher):
    """Start the app again under this same interpreter."""
    args = [sys.executable, os.path.join(dest, launcher)]
    log("starting %s" % launcher)
    return subprocess.Popen(args, cwd=dest, close_fds=True,
                            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def _started_cleanly(proc, err_before):
    """Did the restarted app get past applaunch.py?

    Two signals, because neither answers on its own. A process that has exited
    inside HEALTH_SECONDS plainly failed; but applaunch.py's refusals end in a
    message box, so a failed start is a process that is very much alive with an
    error on screen. What it also does is append to launch.err.log, so a file
    that has changed since the moment of launch is the direct evidence - and it
    is the evidence for exactly the failure an update can cause, a lib\\ built
    for a Python this PC does not have.
    """
    deadline = time.time() + HEALTH_SECONDS
    while time.time() < deadline:
        if proc.poll() is not None:
            log("the app exited inside the %ds health check" % HEALTH_SECONDS)
            return False
        if _stamp(LAUNCH_ERR) != err_before:
            log("the app wrote to launch.err.log after starting")
            return False
        time.sleep(0.5)
    return True


def _digest(zip_path):
    """SHA-256 of the package, which is the number the server published.

    Taken here rather than carried over from phase one: this process was started
    with a path and an argument list and nothing else. It is what ties the
    System Log entry to one published package - a version number cannot, two
    packages having carried one often enough - and it is the same value
    `fetch` checked the download against before anything was stopped.
    """
    try:
        h = hashlib.sha256()
        with open(zip_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _write_result(outcome, from_version, to_version="", digest="", detail=""):
    """Leave the outcome where the app that starts next will find it.

    Written **before the app is started**, on every path where the outcome is
    already known by then - nothing was changed, the extraction failed, the new
    build did not come up - so the app this run relaunches is the one that
    reports it. The one exception is the update that **worked**, whose outcome
    is not known until the restarted app has been watched for
    HEALTH_SECONDS: that entry is written afterwards and is therefore shipped
    by the start after next. Later rather than lost, and the least urgent of
    the four to be told about.

    It is never overwritten before it has been shipped, and that holds by
    construction rather than by a guard: an update is offered by an app that is
    running, and `common.report_update_result` reads and deletes this file at
    the start of every run, so there is no update to be had without a start
    having already cleared whatever the last one left.

    Never raises, for `log`'s reason: this is the diagnostic path, and an update
    that worked must not come to be reported as one that failed because a file
    could not be written.
    """
    try:
        with open(UPDATE_RESULT, "w", encoding="utf-8") as fh:
            json.dump({"outcome":      outcome,
                       "from_version": str(from_version or ""),
                       "to_version":   str(to_version or ""),
                       "sha256":       digest,
                       "detail":       detail,
                       "at":           time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
    except Exception as exc:
        log("could not write update_result.json: %s" % exc)


def _remove_staging(zip_path):
    """Clean up after the zip `--apply` was handed.

    The parent folder is removed whole only when it is unmistakably fetch()'s
    own staging directory: named with `_STAGING_PREFIX` and sitting directly
    under the system temp directory. `--apply` is a command-line entry point,
    so a zip pointed at from anywhere else - an engineer's working folder,
    say - must not have its parent folder taken with it; only the zip goes.
    """
    parent = os.path.dirname(zip_path)
    temp_dir = os.path.realpath(tempfile.gettempdir())
    real_parent = os.path.realpath(parent)
    is_own_staging = (
        os.path.basename(real_parent).lower().startswith(_STAGING_PREFIX.lower())
        and os.path.dirname(real_parent).lower() == temp_dir.lower()
    )
    if is_own_staging:
        shutil.rmtree(parent, ignore_errors=True)
    else:
        try:
            os.remove(zip_path)
        except OSError:
            pass


def apply_update(zip_path, dest, wait_pid, from_version):
    """Wait for the app to go, replace its files, start it again.

    Returns an exit code. Every path through here ends with the app running:
    the new one where the update took, the old one where it did not.
    """
    manifest = read_manifest(zip_path)
    names    = [n for n in manifest["files"] if not n.endswith("/")]
    launcher = manifest["launcher"]
    to_version = str(manifest.get("version") or "")
    digest     = _digest(zip_path)
    log("applying %s -> %s (%d file(s))"
        % (from_version, to_version, len(names)))

    if not _wait_for_exit(wait_pid):
        # It never stopped, so nothing here may touch its files - and there is
        # nothing to restart either.
        log("the app was still running after %ds; nothing was changed"
            % EXIT_WAIT_SECONDS)
        _write_result("failed", from_version, to_version, digest,
                      "the app was still running after %ds; nothing was changed"
                      % EXIT_WAIT_SECONDS)
        return 1

    rollback = os.path.join(ROLLBACK_DIR, str(from_version))
    _clear_old_generations()

    err_before = _stamp(LAUNCH_ERR)
    try:
        _save_for_rollback(dest, names, rollback)
        _extract(zip_path, dest, names)
    except Exception as exc:
        log("extraction failed: %s" % exc)
        _restore(dest, rollback)
        _write_result("rolled_back", from_version, to_version, digest,
                      "extraction failed: %s" % exc)
        _relaunch(dest, launcher)
        return 1

    proc = _relaunch(dest, launcher)
    if not _started_cleanly(proc, err_before):
        log("rolling back to %s" % from_version)
        try:
            proc.terminate()
        except Exception:
            pass
        _restore(dest, rollback)
        _write_result("rolled_back", from_version, to_version, digest,
                      "the app did not start inside the %ds health check; the "
                      "previous version was restored" % HEALTH_SECONDS)
        _relaunch(dest, launcher)
        return 1

    log("updated to %s; the replaced files are in %s" % (to_version, rollback))
    _write_result("applied", from_version, to_version, digest,
                  "the replaced files are in update_rollback\\%s"
                  % str(from_version))
    _remove_staging(zip_path)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", required=True, metavar="ZIP",
                    help="the verified package to install")
    ap.add_argument("--dest", required=True,
                    help="the installation directory to write over")
    ap.add_argument("--wait-pid", required=True, type=int,
                    help="the app process to wait for before touching anything")
    ap.add_argument("--from-version", required=True,
                    help="the version being replaced; names the rollback folder")
    args = ap.parse_args(argv)
    try:
        return apply_update(args.apply, args.dest, args.wait_pid, args.from_version)
    except Exception as exc:
        # The outcome of last resort. Whatever went wrong here, the one thing
        # that must not follow it is an update nothing anywhere says happened:
        # `apply_update` reports every path it knows about, and this reports the
        # paths it does not.
        log("applier failed: %r" % (exc,))
        _write_result("failed", args.from_version, "", "",
                      "the applier failed: %r" % (exc,))
        return 1


if __name__ == "__main__":
    sys.exit(main())
