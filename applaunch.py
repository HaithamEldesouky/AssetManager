"""
Asset Manager - startup shim for running the apps from source.

What Windows executes in source mode is a signed pythonw.exe (or python.exe)
with one of the run_*.py launchers as its argument, instead of an unsigned
PyInstaller exe. See docs/it-asr-and-signing-request.md for why: the exes have
no reputation by construction, an ASR rule blocks one of them today and another
audits all of them.

The launchers are three lines each; everything that can go wrong before the app
starts is here, in one place, for one reason: under pythonw.exe there is no
console and no window, so an ImportError is completely invisible. The app simply
does not appear, and an engineer has nothing to report. So every failure this
shim can foresee ends in a message box and a line in launch.err.log next to the
app.

Layout it expects, all in one directory:

    run_notifier.pyw        what the shortcut points at
    applaunch.py            this file
    notifier_app.py         the app, unchanged
    common.py               the shared wire layer
    lib\\                    vendored dependencies (tools/vendor.ps1)
    lib\\PYVER               "3.12" - the Python that lib was built for
    config.json, ssl_cert.pem, ...

Dependencies are vendored rather than pip-installed per machine: the laptops
have no pip and may have no route to PyPI, and vendoring is what makes the
package hash cover the dependencies too.

lib\\PYVER exists because the vendored wheels are not portable across Python
minor versions - pillow and charset_normalizer carry cp312 compiled extensions.
Loading them under 3.11 fails deep inside an import with a message no engineer
can act on, so the check happens here and says which Python to install.
"""

import os
import runpy
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib")
LOG = os.path.join(HERE, "launch.err.log")

MIN_PYTHON = (3, 10)


def _log(message):
    """Append to launch.err.log. Never raises - it is the diagnostic path."""
    try:
        import datetime
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (stamp, message))
    except Exception:
        pass


def _report(title, message):
    """Put the failure on screen. Answers True where a box was actually drawn.

    Two reporters, and which one goes first is the whole of this function.
    MessageBoxW is user32, which is mapped into every process on this platform
    and needs nothing installed; tkinter is a Python package plus a Tcl/Tk
    runtime that the python.org installer ships only while Include_tcltk is
    on. Three of the four apps here are Tk-only, so a machine without it is a
    machine where every failure this shim exists to report is exactly what
    happens - and the box that says so needed the very thing that was missing.
    That is not a hypothetical: a server whose interpreter had no Tk died in
    run_gui, and the whole of the diagnosis available to the operator was a
    double-click that did nothing, because this function was mute for the same
    reason the app was.

    tkinter is kept as the fallback rather than deleted: it is what answers
    where there is no user32 to call at all, and a second reporter costs four
    lines in the one place that must not fail quietly.
    """
    caption = "Asset Manager - %s" % title
    body = "%s\n\nDetails were written to:\n%s" % (message, LOG)
    try:
        import ctypes
        # MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST - the shortcut was
        # double-clicked, so the box belongs in front of whatever has focus.
        ctypes.windll.user32.MessageBoxW(None, body, caption,
                                         0x10 | 0x10000 | 0x40000)
        return True
    except Exception:
        pass
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(caption, body)
        root.destroy()
        return True
    except Exception:
        pass
    return False


def _die(title, message):
    """Report a startup failure the user can actually see, then exit."""
    _log("%s: %s" % (title, message.replace("\n", " ")))
    if not _report(title, message):
        _log("no message box could be drawn - %s is the whole of the report"
             % LOG)
    sys.exit(1)


def _expected_python():
    """The Python version lib was vendored for, or None if unstamped."""
    stamp = os.path.join(LIB, "PYVER")
    if not os.path.exists(stamp):
        return None
    try:
        with open(stamp, encoding="ascii") as fh:
            return fh.read().strip()
    except Exception:
        return None


def _add_pywin32(lib):
    """Make pywin32 importable out of a vendored lib\\. #188.

    `pip install --target` lays pywin32's extension modules out in `lib\\win32`
    and `lib\\win32\\lib` rather than at the root of `lib\\`, which is why an
    ordinary install drops a `pywin32.pth` naming those directories - and a
    `--target` install writes that file too, where nothing reads it: a `.pth` is
    processed by `site` for a *site* directory, and `lib\\` is one entry on
    `sys.path` and nothing more. So `import win32crypt` failed on every source
    install, and source mode is the only mode (rule 14).

    What that cost is not an app that fails to start - both readers guard the
    import - but two capabilities quietly absent everywhere: `HAS_DPAPI` was
    false, so every stored secret was refused with the reason named, which is
    ADR-0013's designed answer for a machine that genuinely has no DPAPI and was
    being given on machines that have it; and `HAS_WIN32SVC` with it, so the
    Windows Service verbs were missing on a machine carrying pywin32.

    The **DLL directory is the other half and is load-bearing on its own**: the
    extensions link against `pywintypes3xx.dll` in `lib\\pywin32_system32`, so
    with the two directories on the path and not this, `win32crypt` is found and
    then dies on `DLL load failed while importing win32crypt`, which is the same
    failure one layer further down and reads as a corrupt install. That is what
    `pywin32.pth`'s own `import pywin32_bootstrap` does, and it is done here
    rather than by importing that module because this is three lines and the
    import is a dependency on a helper whose whole job is to be reached from a
    file nothing reads.

    Every part is conditional, since the client role's `lib\\` carries no
    pywin32 at all (`requirements-client.txt` does not pin it) and a directory
    that is not there is a stat on every import for ever. `os.add_dll_directory`
    is Windows-only and 3.8+, and this shim runs on nothing else, but it is
    guarded anyway for the reason every other step here is: a failure in the
    startup path is invisible under `pythonw.exe`, and pywin32 is not what the
    app is being started for.
    """
    for sub in ("win32", os.path.join("win32", "lib")):
        path = os.path.join(lib, sub)
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(1, path)
    dlls = os.path.join(lib, "pywin32_system32")
    if os.path.isdir(dlls):
        try:
            os.add_dll_directory(dlls)
        except Exception as exc:
            _log("pywin32_system32 could not be added to the DLL search "
                 "path: %s" % exc)


def bootstrap(app_filename):
    """Put lib on sys.path and run app_filename as __main__."""
    running = "%d.%d" % sys.version_info[:2]

    if sys.version_info[:2] < MIN_PYTHON:
        _die("Python is too old",
             "This app needs Python %d.%d or newer.\nThis one is %s (%s)."
             % (MIN_PYTHON[0], MIN_PYTHON[1], running, sys.executable))

    if not os.path.isdir(LIB):
        _die("Installation is incomplete",
             "The lib folder is missing from:\n%s\n\n"
             "Re-run the installer - the app cannot start without its "
             "bundled dependencies." % HERE)

    expected = _expected_python()
    if expected and expected != running:
        _die("Wrong Python version",
             "This installation was built for Python %s, but it is running "
             "under Python %s.\n\n%s\n\nInstall Python %s and launch the app "
             "again, or ask IT to reinstall it for %s."
             % (expected, running, sys.executable, expected, running))

    app = os.path.join(HERE, app_filename)
    if not os.path.exists(app):
        _die("Installation is incomplete",
             "%s is missing from:\n%s\n\nRe-run the installer."
             % (app_filename, HERE))

    # lib first so a vendored requests wins over anything the machine happens to
    # have; HERE so the app's own `import common` resolves. HERE is already
    # sys.path[0] when a launcher is run directly, but not when this module is
    # reached some other way, and the cost of being sure is one line.
    sys.path.insert(0, LIB)
    _add_pywin32(LIB)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    try:
        runpy.run_path(app, run_name="__main__")
    except SystemExit:
        raise
    except BaseException:
        # The app got far enough to start and then failed. Still invisible under
        # pythonw, so the traceback goes to the log and the user gets told where.
        trace = traceback.format_exc()
        _log("unhandled exception from %s:\n%s" % (app_filename, trace))
        # The last line of a traceback is the exception itself, which is the one
        # thing worth putting in front of somebody who is not going to open the
        # log: "ModuleNotFoundError: No module named 'tkinter'" is actionable
        # where "it failed to run" sends them to ask for the file.
        lines = [ln.strip() for ln in trace.strip().splitlines() if ln.strip()]
        detail = lines[-1] if lines else "No detail was available."
        _die("The app stopped unexpectedly",
             "%s failed to run.\n\n%s\n\nThe full error was written to the "
             "log file." % (app_filename, detail))
