r"""applaunch.py, what Windows starts in source mode: its reporter with
tkinter taken away, and the vendored pywin32 it has to find.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import os
import shutil
import sys
import tempfile

from client_checks.stage import (AL, R, bad, eq, head, ok)


def _applaunch_reporters(user32=None, tk=None):
    """Run applaunch with exactly the reporters named, and put them back.

    Both are resolved inside the function that draws the box - `import ctypes`,
    `import tkinter` - so what decides which one answers is sys.modules at the
    moment of the failure, which is the same thing that decides it on a machine
    with half a Python install on it. None means the module is not there at all:
    None in sys.modules is what an interpreter without tkinter behaves like
    from the importer's point of view, and it is what this is about.
    """
    names = ("ctypes", "tkinter", "tkinter.messagebox")
    saved = dict((n, sys.modules.get(n)) for n in names)

    def restore():
        for n in names:
            if saved[n] is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = saved[n]

    sys.modules["ctypes"] = user32
    sys.modules["tkinter"] = tk
    sys.modules.pop("tkinter.messagebox", None)
    return restore


class _User32(object):
    """ctypes, as far as applaunch reaches into it. Counts what was drawn."""

    def __init__(self, working=True):
        self.working = working
        self.boxes = []
        outer = self

        class _U(object):
            @staticmethod
            def MessageBoxW(owner, body, caption, flags):
                if not outer.working:
                    raise OSError("user32 is not there")
                outer.boxes.append((caption, body, flags))
                return 1

        self.windll = type("_WinDLL", (), {"user32": _U})()


class _Tkinter(object):
    """tkinter, as far as applaunch reaches into it. Counts what was drawn."""

    def __init__(self):
        self.boxes = []
        outer = self

        class _Root(object):
            def withdraw(self):
                pass

            def destroy(self):
                pass

        class _MB(object):
            @staticmethod
            def showerror(caption, body):
                outer.boxes.append((caption, body))

        self.Tk = _Root
        self.messagebox = _MB


def check_a_startup_failure_is_reported_without_tkinter():
    """The one path that has to work when the install is broken.

    applaunch is what Windows starts in source mode, under pythonw.exe, where
    there is no console at all - so every failure it can foresee ends in a
    message box, and that box is the whole of what an engineer has to report.
    It was drawn with tkinter, which is not part of the interpreter: the
    python.org installer ships Tcl/Tk only while Include_tcltk is on, and three
    of the four apps here are nothing but a Tk window. So on a machine without
    it the app could not start **and** the box that says so could not be drawn,
    which is exactly what happened - a server install whose only symptom was a
    double-click that did nothing, diagnosed in the end by reading
    launch.err.log over somebody's shoulder.

    Driven rather than read, because what is claimed is which reporter answers
    under which conditions, and a source read cannot see an import resolved at
    call time. The negative half is the machine with neither: it must still log,
    must still exit 1, and must not raise on the way - a diagnostic path that
    throws inside itself leaves less behind than one that does nothing.
    """
    head("a startup failure is reported on a machine with no Tk")
    log = AL.LOG
    before = os.path.getsize(log) if os.path.exists(log) else 0

    def tail():
        if not os.path.exists(log):
            return ""
        with io.open(log, encoding="utf-8", newline="") as fh:
            fh.seek(before)
            return fh.read()

    # 1. No tkinter, which is the state this is about.
    box = _User32()
    restore = _applaunch_reporters(user32=box, tk=None)
    try:
        code = "no SystemExit"
        try:
            AL._die("Wrong Python version", "Install Python 3.12.")
        except SystemExit as ex:
            code = ex.code
    finally:
        restore()
    eq("a box is drawn with no tkinter on the machine", len(box.boxes), 1)
    if box.boxes:
        caption, body, _flags = box.boxes[0]
        eq("  captioned with the failure", caption,
           "Asset Manager - Wrong Python version")
        eq("  carrying the message and the log to send back",
           ("Install Python 3.12." in body, log in body), (True, True))
    eq("  and the launcher still exits non-zero", code, 1)
    eq("  with the same line in the log", "Install Python 3.12." in tail(),
       True)

    # 2. No user32 either - the half that keeps the first honest, since a
    #    reporter that answered in every state would prove nothing about order.
    before = os.path.getsize(log) if os.path.exists(log) else 0
    dead = _User32(working=False)
    restore = _applaunch_reporters(user32=dead, tk=None)
    try:
        code = "no SystemExit"
        raised = ""
        try:
            AL._die("Installation is incomplete", "lib is missing.")
        except SystemExit as ex:
            code = ex.code
        except BaseException as ex:
            raised = type(ex).__name__
    finally:
        restore()
    eq("with neither reporter nothing is drawn", len(dead.boxes), 0)
    eq("  and nothing is raised out of the diagnostic path", raised, "")
    eq("  the launcher still exits non-zero", code, 1)
    wrote = tail()
    eq("  the failure is in the log regardless", "lib is missing." in wrote,
       True)
    eq("  which says it is the whole of the report",
       "no message box could be drawn" in wrote, True)

    # 3. tkinter alone still answers: it is kept as the fallback rather than
    #    deleted, for the machine where there is no user32 to call.
    tk = _Tkinter()
    restore = _applaunch_reporters(user32=_User32(working=False), tk=tk)
    try:
        try:
            AL._die("Python is too old", "This app needs Python 3.10.")
        except SystemExit:
            pass
    finally:
        restore()
    eq("tkinter draws it where there is no user32", len(tk.boxes), 1)

    # 4. And it is the second reporter, not the first: with both available the
    #    one that needs nothing installed is the one that answers.
    box, tk = _User32(), _Tkinter()
    restore = _applaunch_reporters(user32=box, tk=tk)
    try:
        try:
            AL._die("Python is too old", "This app needs Python 3.10.")
        except SystemExit:
            pass
    finally:
        restore()
    eq("with both there, user32 is what answers",
       (len(box.boxes), len(tk.boxes)), (1, 0))


def check_the_box_names_the_error_that_stopped_the_app():
    """An app that started and then died says what killed it.

    The other failures here are the shim's own and are worded by it. This one
    is the app's, and it said "failed to run - the full error was written to the
    log file", which is true and is not something an engineer can act on: what
    they need on screen is the last line of the traceback, because
    "ModuleNotFoundError: No module named 'tkinter'" names the thing to fix
    where "it failed to run" sends somebody to go and find a file.

    Driven end to end through bootstrap against a real directory - a stamped
    lib directory, an app that raises - since what is asserted is that the detail
    survives from the exception into the box, and the two are several frames
    apart.
    """
    head("the box names the error the app died on")
    home = tempfile.mkdtemp(prefix="applaunch-boot_")
    os.mkdir(os.path.join(home, "lib"))
    with io.open(os.path.join(home, "lib", "PYVER"), "w",
                 encoding="ascii") as fh:
        fh.write("%d.%d" % sys.version_info[:2])
    with io.open(os.path.join(home, "bad_app.py"), "w", encoding="utf-8") as fh:
        fh.write("raise ModuleNotFoundError(\"No module named 'tkinter'\")\n")

    was = (AL.HERE, AL.LIB, AL.LOG)
    AL.HERE = home
    AL.LIB = os.path.join(home, "lib")
    AL.LOG = os.path.join(home, "launch.err.log")
    box = _User32()
    restore = _applaunch_reporters(user32=box, tk=None)
    try:
        code = "no SystemExit"
        try:
            AL.bootstrap("bad_app.py")
        except SystemExit as ex:
            code = ex.code
    finally:
        restore()
        log = AL.LOG
        AL.HERE, AL.LIB, AL.LOG = was

    eq("the app's failure reaches the screen", len(box.boxes), 1)
    if box.boxes:
        body = box.boxes[0][1]
        eq("  naming the exception that stopped it",
           "ModuleNotFoundError: No module named 'tkinter'" in body, True)
        eq("  and the app it came from", "bad_app.py" in body, True)
    eq("  the launcher exits non-zero", code, 1)
    with io.open(log, encoding="utf-8", newline="") as fh:
        wrote = fh.read()
    eq("  and the whole traceback is still in the log, not just its last line",
       ("Traceback" in wrote, "bad_app.py" in wrote), (True, True))
    shutil.rmtree(home, ignore_errors=True)


def check_pywin32_is_importable_out_of_a_vendored_lib():
    """`pip install --target` does not lay pywin32 out where sys.path looks. #188.

    An ordinary pywin32 install drops a `pywin32.pth` naming `win32`,
    `win32\\lib` and `pythonwin`, because its extension modules sit in those
    subdirectories rather than at the root of the directory pip wrote into. A
    `--target` install writes that file too, where nothing reads it: a `.pth` is
    processed by `site` for a *site* directory, and a vendored `lib\\` is one
    entry on `sys.path` and nothing more. So `import win32crypt` failed on every
    source install, and source mode is the only mode (rule 14).

    What that cost is not an app that fails to start - both readers guard the
    import - but two capabilities quietly absent: `HAS_DPAPI` was false, so every
    stored secret was refused with the reason named, which is ADR-0013's answer
    for a machine that genuinely has no DPAPI and was being given on machines
    that have it; and `HAS_WIN32SVC` with it.

    The **DLL directory is asserted beside the two path entries because it is
    load-bearing on its own**: the extensions link against `pywintypes3xx.dll` in
    `lib\\pywin32_system32`, so with the directories on the path and not this,
    `win32crypt` is found and then dies on `DLL load failed while importing
    win32crypt` - the same failure one layer down, reading as a corrupt install.
    Measured that way on a real `--target` tree before this was written.

    And the other half is that a `lib\\` carrying none of it is left alone and
    raises nothing: the client role does not pin pywin32 at all, so every
    Notifier and every Storekeeper takes this path, and a directory that is not
    there must not become a stat on every import for ever.
    """
    head("pywin32 out of a vendored lib")
    home = tempfile.mkdtemp(prefix="applaunch-pywin32_")
    lib = os.path.join(home, "lib")
    for sub in ("win32", os.path.join("win32", "lib"), "pywin32_system32"):
        os.makedirs(os.path.join(lib, sub))

    def drive(target):
        """Run the shim over one directory, putting sys.path back afterwards."""
        asked = []
        before = list(sys.path)
        was_add = getattr(os, "add_dll_directory", None)
        os.add_dll_directory = lambda p: asked.append(p)
        try:
            AL._add_pywin32(target)
            return before, list(sys.path), asked
        finally:
            sys.path[:] = before
            if was_add is None:
                del os.add_dll_directory
            else:
                os.add_dll_directory = was_add

    before, after, asked = drive(lib)
    ext = os.path.join(lib, "win32")
    pure = os.path.join(lib, "win32", "lib")
    eq("the extension modules land on sys.path", ext in after, True)
    eq("  and the pure-Python half beside them", pure in after, True)
    eq("  the DLL directory is on the search path, which is the half that fails "
       "one layer further down",
       asked, [os.path.join(lib, "pywin32_system32")])
    eq("  and nothing else on the path moved",
       [p for p in after if p not in (ext, pure)], before)

    bare = os.path.join(home, "bare")
    os.makedirs(bare)
    before, after, asked = drive(bare)
    eq("a lib carrying no pywin32 adds nothing", after, before)
    eq("  and asks for no DLL directory", asked, [])

    # A machine whose os cannot add one at all is the guard's own case: this
    # runs under pythonw.exe, where a raise in the startup path is invisible.
    before = list(sys.path)
    was_add = getattr(os, "add_dll_directory", None)

    def _refuse(_p):
        raise OSError("no DLL directory on this machine")

    os.add_dll_directory = _refuse
    try:
        AL._add_pywin32(lib)
        ok("a DLL directory that cannot be added is not a startup failure")
    except Exception as ex:
        bad("adding the DLL directory raised %s: %s" % (type(ex).__name__, ex))
    finally:
        sys.path[:] = before
        if was_add is None:
            del os.add_dll_directory
        else:
            os.add_dll_directory = was_add

    shutil.rmtree(home, ignore_errors=True)

    # And bootstrap is what calls it: the group above drives bootstrap against a
    # lib with no pywin32 in it, so the call site itself is read off the source.
    al = io.open(os.path.join(R, "applaunch.py"),
                 encoding="utf-8", newline="").read()
    tree = ast.parse(al)
    boot = [n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "bootstrap"]
    called = [n for f in boot for n in ast.walk(f)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_add_pywin32"]
    eq("bootstrap asks for it, once", len(called), 1)
