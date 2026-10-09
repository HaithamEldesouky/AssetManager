r"""The installer: its window, the source install it writes, and the
questions it asks.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile

from client_checks.stage import (C, IN, SRC, STAGE, _enclosing_functions, bad,
                                 eq, head, measure, measure_scrolled_body,
                                 quiesce, tk_or_skip, widgets)


def check_the_installer_shows_which_component_is_selected():
    """Which component is being installed is visible, and it is one fact (161).

    The selection is the one piece of state this window carries, and since
    080 it is a 2px `TEXT` bar on the leading edge of the chosen row rather
    than a tinted face: the three rows are one `INPUT_BG` plate, which is the
    recess this material gives a thing to be chosen, and the face no longer
    moves at all. So what is asserted is a measurement rather than a
    restatement of the code - each mark's colour is read back off the widget
    and **the three are compared with each other**, which is what caught a
    selection with no visible effect at all.

    **The equal faces are asserted too, not assumed.** A selection that
    stopped painting leaves three identical marks, and three identical faces
    would be the same evidence read the other way round - so the check says
    the faces are all one colour deliberately, and that exactly one mark is
    not that colour. It also reads the mark's width back off the screen: a
    2px bar packed with no `fill` is a bar 1px wide and mapped, which is a
    selection nobody sees and which every colour assertion here would pass.

    Beside it the two things the window is drawn out of: the form stays flat
    with its fields in INPUT_BG, every one of them being a password, a URL, a
    directory or an engineer picker; and the scrolling body stays a `tk.Frame`
    - `measure_scrolled_body` above reads the form's requested width back off
    it, and a canvas there would turn three real measurements into a check
    that reports nothing.

    And the progress window, one of the four windows in this product that must
    refuse its own X: no Escape binding, and a `WM_DELETE_WINDOW` that leaves
    it open - driven rather than read, a binding inherited from somewhere else
    being exactly what a source read would not see.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("the installer shows which component is selected")
    tk = tk_or_skip()
    if tk is None:
        return

    root = tk.Tk()
    root.geometry("560x700+0+0")
    app = IN.InstallerApp(root)
    root.update_idletasks()
    root.update()
    pal = IN.THEME.palette()

    placed = [w for w in root.winfo_children()
              if w.winfo_class() == "Canvas" and w.winfo_manager() == "place"]
    eq("no backdrop canvas is placed under the window", placed, [])

    import ui_kit

    cards = app.card_frames
    marks = app.card_marks
    eq("all three component cards are plain frames",
       sorted(set(f.winfo_class() for f in cards.values())), ["Frame"])

    for chosen in ("server", "storekeeper", "notifier"):
        app.v_component.set(chosen)
        app._on_component_change()
        root.update_idletasks()
        root.update()
        faces = [str(f.cget("bg")) for f in cards.values()]
        eq("  %s selected: the three cards are one plate, the face saying "
           "nothing (%s)" % (chosen, tuple(faces)),
           sorted(set(faces)), [pal["INPUT_BG"]])
        mine = str(marks[chosen].cget("bg"))
        others = [str(m.cget("bg")) for k, m in marks.items() if k != chosen]
        eq("    and its mark is the one colour the other two are not "
           "(%s against %s)" % (mine, tuple(others)),
           (mine, mine in others), (pal["TEXT"], False))
        eq("    and the mark is the 2px the kit sizes it at, on the screen",
           marks[chosen].winfo_width(), ui_kit.MARK_W)
        kids = [str(app.card_titles[chosen].cget("fg")),
                str(app.card_descs[chosen].cget("fg"))]
        eq("    and the words on it moved with the mark",
           kids, [pal["TEXT"], pal["SUBTEXT"]])

    entry = None
    for w in widgets(app.dynamic):
        try:
            if w.winfo_class() == "Entry":
                entry = w
                break
        except Exception:
            pass
    if entry is None:
        bad("the installer's form has no field on it - this group has stopped "
            "measuring what it names")
    else:
        eq("the form's fields keep INPUT_BG",
           str(entry.cget("bg")), pal["INPUT_BG"])
        eq("  and what they stand on is a frame",
           app.dynamic.winfo_class(), "Frame")

    pw = IN._ProgressWindow(root, "Installing Python 3.12")
    root.update_idletasks()
    root.update()
    eq("the progress window takes no Escape binding, being one of the four "
       "that must refuse its own X", pw.win.bind("<Escape>"), "")
    pw.win.tk.call("event", "generate", pw.win._w, "<Escape>")
    root.update()
    root.tk.call(pw.win.protocol("WM_DELETE_WINDOW"))
    root.update()
    eq("  and its own X leaves it open", bool(pw.win.winfo_exists()), True)
    pw.close()
    root.update()
    quiesce(root)


def check_the_installer_window_fits():
    """The installer's one window, in each of the three shapes it takes.

    Its width is the fixed axis - resizable(False, True) - and its body is a
    scrolling canvas, so nothing in it is unreachable at any height: the
    Install button scrolls into view rather than being squeezed out of
    existence, which is why it keeps a written size and does not call
    ui_kit.fit. The component radio buttons rebuild the form under it, so all
    three are measured: server asks for two password fields, Storekeeper for
    one, Notifier for an engineer picker.

    Measured twice, and the second one is the one that can fail. The window's
    own request is a canvas's configured width, which is the same number for
    all three forms - so measure_scrolled_body asks the frame inside the canvas
    instead. Without it this group reported a pass on a figure that cannot see
    the form it is a pass about.
    """
    head("the installer's window fits its form")
    tk = tk_or_skip()
    if tk is None:
        return
    root = tk.Tk()
    app = IN.InstallerApp(root)
    for component in ("notifier", "storekeeper", "server"):
        app.v_component.set(component)
        app._on_component_change()
        label = "Setup, %s selected" % component
        measure(tk, label, root)
        measure_scrolled_body(tk, label, root)
    quiesce(root)


def check_the_server_install_can_register_its_service():
    """The Windows Service is registered by running the launcher, not the target.

    The same defect as the shortcut's, one call further down and quieter: the
    registration ran `[dst, "install"]`, and in source mode - the only mode
    there is (rule 14) - dst is pythonw.exe, so what ran was an interpreter
    with no script. That exits 0 with nothing registered, `net start` then
    fails against a service that does not exist, and the remedy printed
    underneath was the same command written out by hand, so following it did
    the same nothing.

    Driven rather than read, because what is claimed is the content of an argv
    and of the sentence beside it: `_service_command` takes strings and needs
    no payload, no window and no Service. The printed line has to be the argv
    that ran - a remedy that is not the command that failed is worse than no
    remedy - and the exe-mode branch is the negative half, where the target
    really is the whole command and a launcher must not appear in it.
    """
    head("the server install registers the service it says it does")

    launcher = r"C:\Program Files\AssetManager\Server\run_server.py"
    python = r"C:\Python312\pythonw.exe"

    argv, printed = IN._service_command(python, '"%s"' % launcher, "install")
    eq("source mode runs the interpreter, the launcher and the verb",
       argv, [python, launcher, "install"])
    eq("  and the launcher is unquoted in the argv, since no shell sees it",
       '"' in argv[1], False)
    eq("  while the line an operator is told to paste is quoted",
       printed, '"%s" "%s" install' % (python, launcher))

    exe = r"C:\Program Files\AssetManager\Server\AssetServer.exe"
    argv, printed = IN._service_command(exe, "", "install")
    eq("exe mode runs the exe and the verb alone", argv, [exe, "install"])
    eq("  and prints exactly that", printed, '"%s" install' % exe)

    # And the install actually asks it, rather than keeping a second spelling
    # of the command beside the one that runs.
    seg = ""
    for fn in ast.walk(ast.parse(SRC["installer.py"])):
        if isinstance(fn, ast.FunctionDef) and fn.name == "_install_server":
            seg = ast.get_source_segment(SRC["installer.py"], fn) or ""
    eq("the server install builds its command there",
       '_service_command(dst, args, "install")' in seg, True)
    eq("  and keeps no hand-written copy of it",
       ('[dst, "install"]' in seg, '"{dst}" install' in seg), (False, False))


def check_the_server_install_can_open_its_console():
    """A server install ends with a shortcut that opens the Server GUI.

    That window is the console: Server Administration, Mail Settings, Backup /
    Restore, the Lookup Sheet, Asset Proposals and Connected Clients are
    reached from nowhere else. Under IIS it is the only way in there is, the
    process that serves being an app pool worker in session 0 with no window
    and no tray - so an install that cannot open it is an install with no
    console at all.

    `_deploy_component` answers with a target **and** an argument, because in
    source mode - the only mode (rule 14) - the target is pythonw.exe and the
    launcher is the argument. Both client installs passed all three; this one
    passed the target alone, so the shortcut it wrote started an interpreter
    with no script and exited without drawing anything. Nothing said so: the
    .lnk is written, cscript reports success, and the failure is a
    double-click that does nothing.

    A source check, because `_install_server` needs a payload, a Windows
    Service and a window, and because what is claimed is that no call site
    drops the argument rather than that one of them does.
    """
    head("the server install's shortcut opens the console")
    tree = ast.parse(SRC["installer.py"])

    inner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for n in ast.walk(fn):
                inner[n] = fn

    calls = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_create_shortcut"):
            fn = inner.get(n)
            named = {k.arg for k in n.keywords}
            calls.append((fn.name if fn else "(module)",
                          len(n.args) >= 3 or "arguments" in named))

    eq("every install writes one", sorted(name for name, _ok in calls),
       ["_install_notifier", "_install_server", "_install_storekeeper"])
    eq("  and none of them drops the launcher the payload named",
       sorted(name for name, ok in calls if not ok), [])

    # And the operator is told which of the two happened, the way both client
    # installs are: a shortcut is a convenience and its absence is not an
    # install failure, but a server with no console and no command printed is
    # somebody with nowhere to go.
    seg = ""
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "_install_server":
            seg = ast.get_source_segment(SRC["installer.py"], fn) or ""
    eq("  and the popup says how to open it either way",
       "_console_note(made" in seg, True)


def check_the_installer_never_names_itself_as_the_python():
    """What a source install's shortcut points at is a Python, on every payload.

    _gui_python answered with the interpreter it was running under whenever
    lib\\PYVER did not say otherwise, the frozen guard sitting in the second
    half of that condition only - and under AssetManager_Setup.exe the
    interpreter it is running under is the installer. So an unstamped lib\\
    produced a Desktop shortcut reading

        AssetManager_Setup.exe "C:\\...\\run_notifier.pyw"

    which reopens Setup on every click, and _launch_note printed that same
    command where no shortcut could be written. The install reported success
    either way, and applaunch was never reached to say anything about it -
    a turn worse than the wrong-Python shortcut this function reads PYVER to
    prevent, which at least ends in applaunch's error box.

    Driven with an `expected` of None rather than with a version, because that
    is the payload the defect is about and it is a state every other reader
    here tolerates: _payload_mode asks only that lib\\ is a directory,
    applaunch's own check is skipped where there is nothing to compare
    against, and _ensure_python reads a missing stamp as PYTHON_SERIES.

    `sys` is replaced on the installer module rather than on the interpreter:
    frozen is a fact about the process, and setting it for real would answer
    for _ssl_cert_source, _payload_root and _bundled_path at the same time.
    The Python it is handed is a path that does not exist, so what comes back
    is the answer rather than whatever sits beside a real install.
    """
    head("the installer never names itself as the Python")
    NOWHERE = r"C:\nonexistent-client-checks\python.exe"

    class _Frozen(object):
        frozen = True
        executable = r"C:\Program Files\AssetManager\AssetManager_Setup.exe"
        version_info = sys.version_info

    class _Source(object):
        # No `frozen` attribute at all, which is what a real source run has.
        executable = NOWHERE
        version_info = sys.version_info

    asked = []

    def _probe(series=None):
        asked.append(series)
        return NOWHERE

    real_sys, real_installed = IN.sys, IN._python_installed
    try:
        IN.sys, IN._python_installed = _Frozen(), _probe
        got = IN._gui_python(None)
        eq("a frozen installer with an unstamped lib asks the machine",
           asked, [IN.PYTHON_SERIES])
        eq("  and answers with that Python, never with itself", got, NOWHERE)

        IN._python_installed = lambda *_a, **_k: None
        eq("  and with none on the machine it answers None, so the install is "
           "refused rather than shortcut to Setup",
           IN._gui_python(None), None)

        # The branch the fix must not disturb: an installer run from source
        # under a matching interpreter is still that interpreter.
        IN.sys = _Source()
        eq("a source-run installer still answers with what it runs under",
           IN._gui_python(None), NOWHERE)
    finally:
        IN.sys, IN._python_installed = real_sys, real_installed

    # And the refusal that is now reachable with no stamp has to name a
    # version: it printed `expected`, which is None on exactly this payload,
    # and "install Python None" is a refusal nobody can act on.
    tmp = tempfile.mkdtemp(prefix="client-checks-payload_")
    real = (IN._payload_root, IN._payload_mode, IN._lib_pyver, IN._gui_python)
    try:
        IN._payload_root = lambda: tmp
        IN._payload_mode = lambda _key: "source"
        IN._lib_pyver = lambda _root: None
        IN._gui_python = lambda expected=None: None
        said = ""
        try:
            IN._deploy_component("notifier", os.path.join(tmp, "install"))
        except IN.PythonMismatch as ex:
            said = str(ex)
        # The whole sentence, not the version anywhere in it: the line below
        # it names the interpreter this gate is running under, which on a
        # machine carrying the pinned series is that same number.
        eq("the refusal says what the package was built for",
           said.startswith("This package was built for Python %s."
                           % IN.PYTHON_SERIES), True)
        eq("  and never None", "None" in said, False)
    finally:
        (IN._payload_root, IN._payload_mode, IN._lib_pyver,
         IN._gui_python) = real
        shutil.rmtree(tmp, ignore_errors=True)


class _Rc(object):
    """What _run_hidden answers with, as much of it as the installer reads."""

    def __init__(self, returncode):
        self.returncode = returncode


def check_the_python_step_reports_its_failure_and_clears_its_download():
    """What the Python install step leaves behind, on screen and on disk.

    `_ensure_python` runs a worker and drives a `_ProgressWindow` render loop
    on the Tk thread for as long as the Windows installer takes, which is up to
    half an hour. Its worker's own failures are already caught into `state` and
    reported; the render loop around it is what was outside the enclosing
    `try` in both client installs, so a `TclError` out of it escaped to Tk's
    own handler - a console that is not there under a windowed exe - leaving an
    installer that had stopped, an empty error label, and nothing anywhere
    saying why. That the call sits inside the reporting `try` is asserted as
    **source**: reaching it needs a server, a payload and a machine with no
    Python on it, and what is claimed is where the call is written.

    The other half is driven, because it is about what is on disk afterwards.
    The download goes into a `mkdtemp` nothing removed, so every install that
    found no local copy left 25 MB of `python-3.12.10-amd64.exe` in `%TEMP%`
    under a name nothing will look for again - sharpest on the refusal below,
    a file that failed the signature check being the last thing to leave
    sitting there named as Python's own installer. A copy supplied beside the
    installer is asserted to be **kept**: that one is the admin's, not ours,
    and a cleanup that took it would delete the thing an offline machine was
    shipped. The third leg is the run that works, so the group cannot pass by
    finding a step that deletes everything and installs nothing.
    """
    head("installing Python: the failure, and the file it downloaded")
    tk = tk_or_skip()
    if tk is None:
        return

    root = tk.Tk()
    root.withdraw()
    app = type("_Caller", (), {"root": root})()

    warned = []
    ran = []

    class _Box(object):
        @staticmethod
        def showwarning(title, text):
            warned.append((title, text))

        @staticmethod
        def showinfo(*_a, **_k):
            pass

        @staticmethod
        def showerror(*_a, **_k):
            pass

    real = (IN._lib_pyver, IN._python_installed, IN._python_setup_source,
            IN._download, IN._signed_by_psf, IN._run_hidden, IN.messagebox)
    fetched = []

    def _fetch(_url, dest, _cb):
        fetched.append(dest)
        with io.open(dest, "wb") as fh:
            fh.write(b"not really the Python installer")

    try:
        IN._lib_pyver = lambda _root: None
        IN._download = _fetch
        IN.messagebox = _Box
        IN._run_hidden = lambda cmd, timeout=None: ran.append(cmd[0]) or _Rc(0)

        # 1. Downloaded, and refused by the signature check.
        IN._python_installed = lambda series=None: None
        IN._python_setup_source = lambda: None
        IN._signed_by_psf = lambda _p: False
        IN.InstallerApp._ensure_python(app)
        eq("a download that is refused is not left on the machine",
           [os.path.exists(os.path.dirname(p)) for p in fetched], [False])
        eq("  and the refusal reaches the operator",
           bool(warned) and "not signed by" in warned[-1][1], True)

        # 2. A copy supplied beside the installer: the admin's file, not ours.
        kept_dir = tempfile.mkdtemp(prefix="client-checks-supplied-")
        kept = os.path.join(kept_dir, IN.PYTHON_SETUP)
        with io.open(kept, "wb") as fh:
            fh.write(b"shipped next to AssetManager_Setup.exe")
        IN._python_setup_source = lambda: kept
        del fetched[:]
        IN.InstallerApp._ensure_python(app)
        eq("a copy shipped beside the installer is left where it was",
           os.path.exists(kept), True)
        eq("  and nothing was downloaded to stand in for it", fetched, [])
        shutil.rmtree(kept_dir, ignore_errors=True)

        # 3. The run that works: installed off the file it fetched, and the
        #    file still goes. Nothing is warned about, so the two legs above
        #    are measuring a step that can also succeed.
        state = {"there": False}
        IN._python_installed = (
            lambda series=None: "C:/Python312/python.exe" if state["there"]
            else None)
        IN._python_setup_source = lambda: None
        IN._signed_by_psf = lambda _p: True

        def _install(cmd, timeout=None):
            ran.append(cmd[0])
            state["there"] = True
            return _Rc(0)

        IN._run_hidden = _install
        del fetched[:], warned[:], ran[:]
        IN.InstallerApp._ensure_python(app)
        eq("the installer that ran is the one that was downloaded",
           ran, fetched)
        eq("  and it is not left behind either",
           [os.path.exists(os.path.dirname(p)) for p in fetched], [False])
        eq("  and nothing is warned about", warned, [])
    finally:
        (IN._lib_pyver, IN._python_installed, IN._python_setup_source,
         IN._download, IN._signed_by_psf, IN._run_hidden,
         IN.messagebox) = real
        quiesce(root)

    # Where the call is written. Not "inside some try" but inside the one that
    # also runs _deploy_component - that is the try whose except reports a
    # failure to the operator, and being inside any other would say nothing.
    tree = ast.parse(SRC["installer.py"])
    where = _enclosing_functions(tree)
    tries = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            ids = set()
            for stmt in node.body:
                for inner in ast.walk(stmt):
                    ids.add(id(inner))
            deploys = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_deploy_component"
                for n in ast.walk(node) if id(n) in ids)
            tries.append((ids, deploys))

    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_ensure_python"]
    eq("both client installs ask for the interpreter",
       sorted(where.get(n) for n in calls),
       ["_install_notifier", "_install_storekeeper"])
    eq("  and each asks inside the try that reports what went wrong",
       sorted(where.get(n) for n in calls
              if any(deploys for ids, deploys in tries if id(n) in ids)),
       ["_install_notifier", "_install_storekeeper"])


def check_a_refused_fingerprint_is_asked_again_on_the_next_install():
    """One prompt per process is the clients' rule; the installer asks per click.

    `bootstrap_cert` asks once whatever the answer, because the two windowed
    clients reach the server on a fifteen-second tick and a refusal that could
    be re-asked there would be a dialog every fifteen seconds until somebody
    accepted it without reading. The installer is not that: it asks when a
    person clicks Install, and the prompt opens with Cancel as its default
    button, so a stray keypress refuses it.

    What that cost is the message the operator is then shown. Every later click
    fails closed with no certificate on disk and lands in
    `_report_unreachable` - "Cannot reach server at the URL above. Make sure
    the server is running" - while the server is up, the URL is right and the
    password is right, and the one line offering a way out says to accept the
    certificate when offered, which cannot happen again in that process. That
    function exists so a check which could not be made is not reported as a
    wrong password; this is the same wrongness one door along.

    Both halves are asserted, because the fix is a narrowing and not a
    loosening: the client rule has to still hold with nobody re-arming it, or
    this group would be passing a `common.py` that prompts on every tick. The
    call into it is a **source** check - `_install` is a Tk callback needing a
    server, a payload and an install directory, none of which this file has.
    """
    head("a refused fingerprint, and the next click on Install")
    import base64

    der = b"the certificate this server would offer, as a digest sees it"
    pem = ("-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n"
           % base64.b64encode(der).decode()).encode()

    asked = []

    def _refuse(fp, origin):
        asked.append(("refuse", fp, origin))
        return False

    def _accept(fp, origin):
        asked.append(("accept", fp, origin))
        return True

    had = None
    if os.path.exists(C.SSL_CERT_PATH):
        with io.open(C.SSL_CERT_PATH, "rb") as f:
            had = f.read()
        os.remove(C.SSL_CERT_PATH)
    was_confirm, was_asked = C._cert_confirm, C._cert_asked
    was_fetch = C._fetch_offered_cert
    try:
        C._fetch_offered_cert = lambda _origin, **_k: pem
        C.set_cert_confirm(_refuse)
        C._cert_asked = False

        C.bootstrap_cert("https://server:8081/auth/verify")
        eq("a first attempt offers the fingerprint", len(asked), 1)
        eq("  and a refusal pins nothing", os.path.exists(C.SSL_CERT_PATH),
           False)

        # The rule as the clients need it, asserted before the way out of it:
        # nothing re-arms on its own.
        C.bootstrap_cert("https://server:8081/auth/verify")
        eq("a second attempt in the same process asks nothing", len(asked), 1)

        # What an install attempt does. The question comes back, so the
        # operator who dismissed the dialog is not told the server is down.
        C.reset_cert_prompt()
        C.set_cert_confirm(_accept)
        C.bootstrap_cert("https://server:8081/auth/verify")
        eq("an install attempt asks again", len(asked), 2)
        eq("  and accepting pins what was offered",
           os.path.exists(C.SSL_CERT_PATH)
           and io.open(C.SSL_CERT_PATH, "rb").read(), pem)
        eq("  having shown the fingerprint of that certificate, and its origin",
           (asked[1][1], asked[1][2]),
           (C.cert_fingerprint(pem), "https://server:8081"))

        # It re-arms the question and not the trust: a certificate already on
        # disk is a different condition, and re-offering one would be asking
        # an operator to re-accept what this install is already pinning.
        C.reset_cert_prompt()
        C.bootstrap_cert("https://server:8081/auth/verify")
        eq("a certificate already held is still not re-offered", len(asked), 2)
    finally:
        C._fetch_offered_cert = was_fetch
        C._cert_confirm, C._cert_asked = was_confirm, was_asked
        if os.path.exists(C.SSL_CERT_PATH):
            os.remove(C.SSL_CERT_PATH)
        if had is not None:
            with io.open(C.SSL_CERT_PATH, "wb") as f:
                f.write(had)

    # The caller. An install attempt is the one thing allowed to re-arm it, so
    # what is asserted is that the installer asks once and asks in `_install`
    # - a second call elsewhere would be some other path quietly deciding it
    # may re-prompt, which is the rule this keeps in one place.
    tree = ast.parse(SRC["installer.py"])
    where = _enclosing_functions(tree)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "reset_cert_prompt"]
    eq("the installer re-arms the prompt exactly once", len(calls), 1)
    eq("  and it is _install that does it",
       sorted({where.get(n) for n in calls}), ["_install"])


def check_the_installer_asks_one_question_about_the_certificate():
    """Two fallbacks that could not answer, and the one reader that disagreed.

    `_report_unreachable` is the sentence somebody installing is shown when the
    live password check got no answer at all - it exists so that a check which
    could not be made is not reported as a wrong password. The one line on it
    offering a way out is about the certificate, and it decided whether to
    offer it by asking `os.path.exists(_SSL_CERT_PATH)` while all three install
    paths asked `_ssl_cert_source()`. One question, two spellings, agreeing
    only because nothing has bundled a certificate into the exe since 061 -
    which is the sort of agreement that ends the moment either side moves. So
    the hint is driven through `_ssl_cert_source` rather than through a file on
    disk: an assertion that put a certificate next to the installer would pass
    just as happily against the wrong question.

    The other half is the `getattr(self, ...)` defaults the three install
    functions read their fields through. Each stood in for an attribute that is
    never missing - `_on_component_change` builds that card's variables at
    startup and again on every radio, before Install can be clicked - and the
    Notifier's stood in badly: the default was a class rather than an instance,
    so `.get()` was an unbound function called with no arguments and raised
    `TypeError` inside a lambda where it reads as answering with the first
    engineer. Asserted as **source**, because what is claimed is an absence:
    every one of them was unreachable, so no driven leg can show one going or
    stop a differently-shaped one arriving.
    """
    head("the certificate the installer looks for, and where it looks")

    class _Label(object):
        """As much of the error label as _report_unreachable writes to."""

        def __init__(self):
            self.text = ""

        def config(self, text="", **_kw):
            self.text = text

    app = type("_Caller", (), {})()
    app.err_lbl = _Label()

    # _SSL_CERT_PATH is a real path beside the staged installer and the group
    # above writes and removes a certificate there. What is measured here is
    # which question this function asks, so whatever is on disk is put out of
    # the way and given back afterwards.
    had = None
    if os.path.exists(IN._SSL_CERT_PATH):
        with io.open(IN._SSL_CERT_PATH, "rb") as f:
            had = f.read()
        os.remove(IN._SSL_CERT_PATH)
    was = IN._ssl_cert_source
    try:
        IN._ssl_cert_source = lambda: None
        IN.InstallerApp._report_unreachable(app, "https://server:8081",
                                            "Notifier")
        eq("a server that did not answer is not reported as a wrong password",
           "Cannot reach server" in app.err_lbl.text, True)
        eq("  and with no certificate to install, the way out is offered",
           "ssl_cert.pem next to the installer" in app.err_lbl.text, True)

        IN._ssl_cert_source = lambda: os.path.join(STAGE, "shipped",
                                                   "ssl_cert.pem")
        IN.InstallerApp._report_unreachable(app, "https://server:8081",
                                            "Notifier")
        eq("a certificate this installer already has is not asked for",
           "ssl_cert.pem" in app.err_lbl.text, False)
        eq("  and the server is still what it says could not be reached",
           "Cannot reach server" in app.err_lbl.text, True)

        IN._ssl_cert_source = lambda: None
        IN.InstallerApp._report_unreachable(app, "http://server:8081",
                                            "Storekeeper")
        eq("over plain HTTP no certificate is mentioned at all",
           "ssl_cert.pem" in app.err_lbl.text, False)
    finally:
        IN._ssl_cert_source = was
        if had is not None:
            with io.open(IN._SSL_CERT_PATH, "wb") as f:
                f.write(had)

    # No install reads a field through a stand-in for the widget that holds it.
    # An attribute that really is absent is then an AttributeError naming it,
    # rather than a wrong engineer or a TypeError from inside a lambda.
    tree = ast.parse(SRC["installer.py"])
    where = _enclosing_functions(tree)
    stand_ins = sorted(
        "%s:%d" % (where.get(n) or "?", n.lineno) for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "getattr" and len(n.args) == 3
        and isinstance(n.args[0], ast.Name) and n.args[0].id == "self")
    eq("no field is read through a default standing in for its widget",
       stand_ins, [])


def check_a_server_reinstall_keeps_what_it_was_not_asked_about():
    """admin_config.json holds a third key, and a fresh dict dropped it.

    `_install_server` asks for two things and writes three - `password_hash`,
    `first_run`, and, by omission, the absence of every capability password the
    Admin had set. A reinstall therefore cleared `capability_hashes` with
    nothing said at the time and nothing left in the file to say one was ever
    there: the Capability Passwords window afterwards reports four actions with
    no delegation on them, which reads exactly like an Admin who never set one.

    The answer is written out twenty lines below on the file beside it -
    `server_config.json` is read-modify-written for the same reason, and a copy
    it cannot read is left alone and said so in the popup - so the assertions
    here are that both doors in one function now answer the one question the
    one way.

    Driven rather than read, because what is claimed is what is in a file after
    a write, and the write is reachable without a payload to copy: it is
    `_write_admin_cfg`, which takes paths and touches no Tk - the split
    `_export_public_cert` makes on the server side.
    """
    head("what a server reinstall keeps in admin_config.json")

    def _staged(contents):
        """An install directory holding that admin_config.json, or none."""
        d = tempfile.mkdtemp(prefix="client-checks-admincfg_")
        if contents is not None:
            with io.open(os.path.join(d, "admin_config.json"), "w",
                         encoding="utf-8") as f:
                f.write(contents)
        return d

    digest = lambda pw: IN.hashlib.sha256(pw.encode()).hexdigest()

    # A reinstall over a server somebody has delegated two actions on.
    before = {"password_hash": digest("old"), "first_run": False,
              "capability_hashes": {"ssl_cert": "pbkdf2_sha256$1$a$b",
                                    "host_port": "pbkdf2_sha256$1$c$d"}}
    d = _staged(json.dumps(before, indent=2))
    note = IN._write_admin_cfg(d, "new-admin-password")
    with io.open(os.path.join(d, "admin_config.json"), encoding="utf-8") as f:
        after = json.load(f)
    eq("a reinstall keeps the capability passwords it did not ask about",
       after.get("capability_hashes"), before["capability_hashes"])
    eq("  and the password it did ask about is the one that moved",
       after.get("password_hash"), digest("new-admin-password"))
    eq("  and first_run stays False", after.get("first_run"), False)
    eq("  so nothing is put in front of the operator", note, "")

    # A file that cannot be read is worth more than this install's two keys.
    broken = "{ not json at all"
    d = _staged(broken)
    note = IN._write_admin_cfg(d, "new-admin-password")
    with io.open(os.path.join(d, "admin_config.json"), encoding="utf-8") as f:
        eq("an admin_config.json that cannot be read is left exactly as it was",
           f.read(), broken)
    eq("  and the operator is told the admin password was not applied",
       "Admin password not applied" in note, True)

    # A JSON array is readable and is not this file, which is the shape the
    # port write refuses too - a list would take the two keys silently.
    d = _staged("[]")
    note = IN._write_admin_cfg(d, "new-admin-password")
    with io.open(os.path.join(d, "admin_config.json"), encoding="utf-8") as f:
        eq("a file that is not an object is left alone as well", f.read(), "[]")
    eq("  and is reported the same way",
       "Admin password not applied" in note, True)

    # A fresh install writes what it always wrote, so the group cannot pass by
    # finding a function that refuses everything.
    d = _staged(None)
    note = IN._write_admin_cfg(d, "first-password")
    with io.open(os.path.join(d, "admin_config.json"), encoding="utf-8") as f:
        fresh = json.load(f)
    eq("a fresh install writes the two keys it was asked for",
       sorted(fresh), ["first_run", "password_hash"])
    eq("  as the pre-ADR-0008 bare SHA-256 the server upgrades on first use",
       fresh.get("password_hash"), digest("first-password"))
    eq("  with nothing said about it", note, "")

    # The one writer, and the popup that reads what it answered. Source,
    # because _install_server needs a payload, a service and a Tk window.
    tree = ast.parse(SRC["installer.py"])
    where = _enclosing_functions(tree)
    names = sorted(set(
        where.get(n) or "?" for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and n.value == "admin_config.json"))
    eq("one function in the installer names admin_config.json at all",
       names, ["_write_admin_cfg"])
    eq("  and the install calls it",
       "_write_admin_cfg(dest_dir, pw)" in SRC["installer.py"], True)
    eq("  and puts what it answered in front of the operator",
       "{admin_note}" in SRC["installer.py"], True)


def check_the_installer_holds_a_password_to_the_constant():
    """The first admin password this system has is held to PASSWORD_MIN.

    `server-checks.py` makes this assertion about `server.py`'s six doors, and
    the seventh is here: `_install_server` **sets** the admin password, where
    every one of those six changes one that exists. That makes it the worst
    place for the bound to be a literal - it is the credential every capability
    password is measured against, so raising `PASSWORD_MIN` in `server.py`
    alone would leave the door at the bottom of the system the loosest one in
    it. #90 was this same drift in the Server GUI's Change Admin Password,
    pointing the other way.

    What is asserted here is the half that is about this file alone: that the
    refusal and the sentence the operator reads are the **same** copy of the
    number, so a raise moves both. That the copy equals `server.py`'s is
    `cascade-audit.py`'s row and is deliberately not restated here - two gates
    holding one fact is a second place for it to be answered differently, which
    is the shape this ticket exists to remove rather than to add.

    A source check, because what is claimed is an absence and because
    `_install_server` needs a payload, a Windows Service and a window.
    """
    head("the password bound the installer refuses on")

    src = SRC["installer.py"]
    tree = ast.parse(src)

    # Innermost enclosing function, for the reason server-checks.py gives
    # about the same assertion: `_enclosing_functions` lets the outer function
    # win, and a check written inside a nested callback would then be reported
    # against whatever it sits in.
    inner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for n in ast.walk(fn):
                inner[n] = fn

    literal, named = [], set()
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Compare) and len(n.ops) == 1
                and isinstance(n.ops[0], (ast.Lt, ast.LtE))):
            continue
        left = n.left
        if not (isinstance(left, ast.Call) and isinstance(left.func, ast.Name)
                and left.func.id == "len"):
            continue
        fn = inner.get(n)
        right = n.comparators[0]
        if isinstance(right, ast.Name) and right.id.endswith("_MIN"):
            named.add(fn.name if fn else "(module)")
        elif isinstance(right, ast.Constant) and isinstance(right.value, int):
            # Only where the code around it is about a password: a length
            # bound on a chunk or a column is not this check's business, which
            # is the scoping server-checks.py uses on the same shape.
            seg = ast.get_source_segment(src, fn) or "" if fn else ""
            if "assword" in seg or "assword" in (fn.name if fn else ""):
                literal.append("%s (line %d): %s"
                               % (fn.name if fn else "(module)", n.lineno,
                                  ast.unparse(n)))
    eq("no door in the installer compares a password against a number",
       sorted(literal), [])
    eq("  the one that does reads a named bound", sorted(named),
       ["_install_server"])

    # And nothing tells the operator a number the check no longer holds.
    said = sorted(
        "line %d %r" % (n.lineno, n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and "char" in n.value.lower()
        and any("%s %s" % (w, d) in n.value.lower()
                for w in ("min", "at least") for d in "0123456789"))
    eq("no window states the bound as a digit", said, [])

    # The positive half, without which those pass by finding nothing: the
    # constant is there, it is a module-level one, and the refusal reads it. A
    # raise then moves the check and the sentence together.
    const = [n.value.value for n in tree.body
             if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name)
             and n.targets[0].id == "PASSWORD_MIN"
             and isinstance(n.value, ast.Constant)]
    eq("the installer states the bound once, as a module-level constant",
       len(const), 1)
    readers = sorted(set(
        inner[n].name for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id == "PASSWORD_MIN" and n in inner))
    eq("  and the door that sets the first admin password reads it",
       readers, ["_install_server"])
    eq("  twice, the refusal and the sentence under it",
       sum(1 for n in ast.walk(tree)
           if isinstance(n, ast.Name) and n.id == "PASSWORD_MIN"
           and inner.get(n) is not None
           and inner[n].name == "_install_server"), 2)


def check_the_python_install_asks_for_tk():
    """Include_tcltk is stated, not inherited.

    Three of the four apps here are a Tk window and nothing else, so an
    interpreter installed without Tcl/Tk is an install that reports success and
    can never open anything. The python.org installer defaults that option on -
    but a default is remembered from the last install on that machine and is a
    tickbox anybody can clear, which is not the same as a guarantee, and the
    cost of finding out is an app with no window and, until the group above, no
    message either.

    The other four flags are asserted beside it because what is being checked
    is the argument list the installer actually runs: a rewrite that adds this
    one and drops InstallAllUsers is a laptop that loses its interpreter with
    the first profile to be deleted.
    """
    head("the Python step asks for Tcl/Tk")
    eq("the interpreter is installed with Tk",
       "Include_tcltk=1" in IN.PYTHON_ARGS, True)
    eq("  and never without it",
       "Include_tcltk=0" in IN.PYTHON_ARGS, False)
    eq("  the rest of the install is unchanged by it",
       [a for a in IN.PYTHON_ARGS if not a.startswith("Include_tcltk")],
       ["/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_launcher=1",
        "Include_test=0"])

    # And the list is what is run, rather than a constant beside a command that
    # spells its own flags out - source, since reaching the call needs a machine
    # with no Python on it.
    ran = [n for n in ast.walk(ast.parse(SRC["installer.py"]))
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "_run_hidden" and n.args
           and "PYTHON_ARGS" in ast.dump(n.args[0])]
    eq("  and it is what the install actually runs", len(ran), 1)
