r"""A release applied in place: client_update.py's two phases, the handover
to the next start, and the update_now Command.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import importlib.util as iu

from client_checks.stage import (C, NT, R, SK, SRC, _load, _offline, bad, eq,
                                 head, ok, tk_or_skip)


def check_the_applier_keeps_one_rollback_generation():
    """update_rollback\\ holds the build being replaced, and nothing older.

    CLAUDE.md says one generation is kept, and it was not: `rollback` is named
    after the version being replaced, so the rmtree that was there cleared a
    directory that had never existed, and each update left a whole vendored
    lib\\ beside the last - for ever, on every engineer's laptop, with nothing
    ever reading any of them but the newest.

    Nothing static sees that. The count is a property of what three successive
    runs leave behind, so three are driven here, against a real install
    directory and a real zip. Only the three things that leave this machine or
    take a minute are stubbed - waiting on the app's process, relaunching it
    and the health check; the rollback bookkeeping this is about is the real
    function throughout.

    The two halves either side of the count are what make it a measurement
    rather than a restatement. The generation that *is* kept has to hold the
    build that was just replaced - clearing before saving rather than after is
    the whole of the fix, and clearing the wrong one would pass a count of one
    while throwing away the only copy that can be restored. And a failed start
    still has to roll back, which is the property the deletion is placed to
    protect: it happens before a byte of the install has moved, so what it
    removes is copies of files that are live at that moment.
    """
    head("the applier keeps one rollback generation")
    import zipfile

    dest = tempfile.mkdtemp(prefix="client-checks_install_")
    # One directory per package, because apply_update removes the directory it
    # was handed the zip in - that is where update_now downloaded it to, and
    # the applier is what cleans it up.
    pkgs = []
    # Staged into the install directory, because the applier resolves
    # update_rollback\\ next to its own source file the way a real one does.
    shutil.copy2(os.path.join(R, "client_update.py"),
                 os.path.join(dest, "client_update.py"))
    spec = iu.spec_from_file_location("client_update_under_test",
                                      os.path.join(dest, "client_update.py"))
    CU = iu.module_from_spec(spec)
    spec.loader.exec_module(CU)

    pyver = "%d.%d" % sys.version_info[:2]

    def package(version):
        """A zip of one source file and a two-file lib\\, like a real one."""
        pkgs.append(tempfile.mkdtemp(prefix="client-checks_pkg_"))
        path = os.path.join(pkgs[-1], "NotifierApp-%s.zip" % version)
        files = {"notifier_app.py": "APP_VERSION = %r" % version,
                 "lib/charset_normalizer/__init__.py": "# %s" % version,
                 "lib/PYVER": pyver}
        with zipfile.ZipFile(path, "w") as zf:
            for name, body in files.items():
                zf.writestr(name, body + "\n")
            zf.writestr("manifest.json", json.dumps(
                {"app": "notifier", "version": version,
                 "python_version": pyver,
                 "launcher": "run_notifier.pyw",
                 "files": {n: "" for n in files}}))
        return path

    def installed(*parts):
        try:
            return io.open(os.path.join(dest, *parts), encoding="utf-8").read()
        except OSError:
            return None

    def kept():
        try:
            return sorted(os.listdir(CU.ROLLBACK_DIR))
        except OSError:
            return []

    try:
        # The install as it stands before the first update.
        os.makedirs(os.path.join(dest, "lib", "charset_normalizer"))
        io.open(os.path.join(dest, "notifier_app.py"), "w",
                encoding="utf-8").write("APP_VERSION = '1.5.0'\n")
        io.open(os.path.join(dest, "lib", "PYVER"), "w",
                encoding="utf-8").write(pyver)
        io.open(os.path.join(dest, "lib", "charset_normalizer", "__init__.py"),
                "w", encoding="utf-8").write("# 1.5.0\n")

        CU._wait_for_exit = lambda *a, **k: True
        CU._relaunch = lambda *a, **k: type(
            "P", (), {"poll": lambda s: None, "terminate": lambda s: None})()
        CU._started_cleanly = lambda *a, **k: True

        for frm, to in (("1.5.0", "1.6.0"), ("1.6.0", "1.7.0"),
                        ("1.7.0", "1.8.0")):
            rc = CU.apply_update(package(to), dest, os.getpid(), frm)
            eq("%s -> %s applied" % (frm, to), rc, 0)
            eq("  and update_rollback\\ holds the one build it replaced",
               kept(), [frm])

        # The kept generation is the one that can actually be restored: the
        # lib\\ of the build that was live a moment ago, not an older one.
        eq("the generation kept is the build that was replaced",
           installed("update_rollback", "1.7.0", "lib",
                     "charset_normalizer", "__init__.py"),
           "# 1.7.0\n")
        eq("  and the install is at the version that was applied",
           installed("notifier_app.py"), "APP_VERSION = '1.8.0'\n")

        # And the property the deletion is placed early to protect. It runs
        # before a byte of the install has moved, so a start that never comes
        # up still has everything it needs to go back.
        CU._started_cleanly = lambda *a, **k: False
        rc = CU.apply_update(package("1.9.0"), dest, os.getpid(), "1.8.0")
        eq("an update that does not come up is not reported as applied",
           rc != 0, True)
        eq("  and the app is rolled back to the build it was on",
           installed("notifier_app.py"), "APP_VERSION = '1.8.0'\n")
        eq("  with its own lib\\ back",
           installed("lib", "charset_normalizer", "__init__.py"), "# 1.8.0\n")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        for _pkg in pkgs:
            shutil.rmtree(_pkg, ignore_errors=True)


def check_the_applier_removes_only_its_own_staging_folder():
    """#277: the cleanup at the end of apply_update knows whose folder it is.

    `--apply` is a command-line entry point, so the zip it is handed is not
    always fetch()'s own `am-update-*` folder under the system temp
    directory - a zip in an engineer's working folder is a call away. The old
    code did `shutil.rmtree(os.path.dirname(zip_path))` unconditionally, which
    took that folder's other files with it, silently, because of
    `ignore_errors=True`. That happened for real on 2026-09-23.

    Two zips, two folders: one built the way fetch() builds its own staging
    folder (prefixed and directly under `tempfile.gettempdir()`), one an
    ordinary folder with a file of its own beside the zip. Only the first is
    removed whole; the second keeps its folder and the other file, and only
    the zip goes.
    """
    head("the applier removes only its own staging folder")
    import zipfile

    dest = tempfile.mkdtemp(prefix="client-checks_install_")
    spec = iu.spec_from_file_location("client_update_under_test_staging",
                                      os.path.join(R, "client_update.py"))
    CU = iu.module_from_spec(spec)
    spec.loader.exec_module(CU)

    pyver = "%d.%d" % sys.version_info[:2]

    def package(folder, version):
        path = os.path.join(folder, "NotifierApp-%s.zip" % version)
        files = {"notifier_app.py": "APP_VERSION = %r" % version,
                 "lib/PYVER": pyver}
        with zipfile.ZipFile(path, "w") as zf:
            for name, body in files.items():
                zf.writestr(name, body + "\n")
            zf.writestr("manifest.json", json.dumps(
                {"app": "notifier", "version": version,
                 "python_version": pyver,
                 "launcher": "run_notifier.pyw",
                 "files": {n: "" for n in files}}))
        return path

    CU._wait_for_exit = lambda *a, **k: True
    CU._relaunch = lambda *a, **k: type(
        "P", (), {"poll": lambda s: None, "terminate": lambda s: None})()
    CU._started_cleanly = lambda *a, **k: True

    own_staging = None
    ordinary = None
    try:
        os.makedirs(os.path.join(dest, "lib"))
        io.open(os.path.join(dest, "notifier_app.py"), "w",
                encoding="utf-8").write("APP_VERSION = '1.0.0'\n")
        io.open(os.path.join(dest, "lib", "PYVER"), "w",
                encoding="utf-8").write(pyver)

        # A fetch()-style staging folder: the same prefix, directly under the
        # system temp directory - apply_update() must take the whole of it.
        own_staging = tempfile.mkdtemp(prefix=CU._STAGING_PREFIX)
        zip_in_staging = package(own_staging, "1.1.0")
        rc = CU.apply_update(zip_in_staging, dest, os.getpid(), "1.0.0")
        eq("applying from its own staging folder succeeds", rc, 0)
        eq("  and the staging folder is gone",
           os.path.isdir(own_staging), False)
        own_staging = None

        # An ordinary folder - the case #277 was filed over: a zip pointed at
        # from the command line, sitting beside a file that is not the
        # applier's to touch.
        ordinary = tempfile.mkdtemp(prefix="client-checks_working_")
        keepsake = os.path.join(ordinary, "notes.txt")
        io.open(keepsake, "w", encoding="utf-8").write("do not delete me\n")
        zip_in_ordinary = package(ordinary, "1.2.0")
        rc = CU.apply_update(zip_in_ordinary, dest, os.getpid(), "1.1.0")
        eq("applying from an ordinary folder succeeds", rc, 0)
        eq("  and that folder is left alone", os.path.isdir(ordinary), True)
        eq("  with its other file untouched", os.path.isfile(keepsake), True)
        eq("  and only the zip is gone", os.path.exists(zip_in_ordinary), False)
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        if own_staging:
            shutil.rmtree(own_staging, ignore_errors=True)
        if ordinary:
            shutil.rmtree(ordinary, ignore_errors=True)


def check_the_applier_says_what_became_of_the_update():
    """Phase two writes down the outcome, because it cannot log one.

    #148. The whole update path emitted a single System Log entry - written
    when the package was *staged*, before the app was stopped - so nothing
    anywhere recorded whether an update had actually worked. The applier cannot
    fix that by logging: it is a separate process that imports nothing of ours
    on purpose (it is overwriting `common.py` while it runs) and by the time it
    has an outcome there is no app left holding a queue. What it can do is
    leave `update_result.json`, and the next start turns that into the entry.

    Driven rather than read, because what is claimed is the content of a file
    after three different runs, and each of them is several hundred lines of
    moving files apart. The three stubs are the three things that leave the
    machine or take a minute - the wait on the app's process, the relaunch and
    the health check - exactly as the rollback-generation group stubs them.

    All three outcomes, because the one that is easy to get right is the one
    that worked: a rollback reported as an update, or an update that was never
    applied reported as nothing at all, is an Admin reading a green System Log
    over a fleet that is stuck on an old build.
    """
    head("the applier says what became of the update")
    import hashlib, zipfile

    dest = tempfile.mkdtemp(prefix="client-checks_result_")
    pkgs = []
    shutil.copy2(os.path.join(R, "client_update.py"),
                 os.path.join(dest, "client_update.py"))
    spec = iu.spec_from_file_location("client_update_result_under_test",
                                      os.path.join(dest, "client_update.py"))
    CU = iu.module_from_spec(spec)
    spec.loader.exec_module(CU)

    pyver = "%d.%d" % sys.version_info[:2]

    def package(version):
        pkgs.append(tempfile.mkdtemp(prefix="client-checks_rpkg_"))
        path = os.path.join(pkgs[-1], "NotifierApp-%s.zip" % version)
        files = {"notifier_app.py": "APP_VERSION = %r" % version,
                 "lib/PYVER": pyver}
        with zipfile.ZipFile(path, "w") as zf:
            for name, body in files.items():
                zf.writestr(name, body + "\n")
            zf.writestr("manifest.json", json.dumps(
                {"app": "notifier", "version": version,
                 "python_version": pyver,
                 "launcher": "run_notifier.pyw",
                 "files": {n: "" for n in files}}))
        return path

    def result():
        """What the applier left behind, with the file cleared afterwards."""
        try:
            got = json.loads(io.open(CU.UPDATE_RESULT,
                                     encoding="utf-8").read())
        except Exception:
            return {}
        os.remove(CU.UPDATE_RESULT)
        return got

    def digest_of(path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            h.update(fh.read())
        return h.hexdigest()

    try:
        os.makedirs(os.path.join(dest, "lib"))
        io.open(os.path.join(dest, "notifier_app.py"), "w",
                encoding="utf-8").write("APP_VERSION = '2.0.0'\n")
        io.open(os.path.join(dest, "lib", "PYVER"), "w",
                encoding="utf-8").write(pyver)

        CU._relaunch = lambda *a, **k: type(
            "P", (), {"poll": lambda s: None, "terminate": lambda s: None})()

        # The update that worked.
        CU._wait_for_exit = lambda *a, **k: True
        CU._started_cleanly = lambda *a, **k: True
        zip_path = package("2.1.0")
        want = digest_of(zip_path)
        CU.apply_update(zip_path, dest, os.getpid(), "2.0.0")
        got = result()
        eq("an update that worked is written down as applied",
           got.get("outcome"), "applied")
        eq("  carrying both versions",
           [got.get("from_version"), got.get("to_version")], ["2.0.0", "2.1.0"])
        eq("  and the digest of the package that was installed",
           got.get("sha256"), want)

        # The update that did not come up.
        CU._started_cleanly = lambda *a, **k: False
        zip_path = package("2.2.0")
        CU.apply_update(zip_path, dest, os.getpid(), "2.1.0")
        got = result()
        eq("one that did not start is written down as rolled back",
           got.get("outcome"), "rolled_back")
        eq("  naming the version that was put back and the one that failed",
           [got.get("from_version"), got.get("to_version")], ["2.1.0", "2.2.0"])
        if got.get("detail"):
            ok("  and saying why, which is the whole of what an Admin can act "
               "on: %s" % got["detail"])
        else:
            bad("a rollback was recorded with no reason beside it")

        # And the one where nothing was touched at all, which must not read as
        # a rollback: there was nothing to roll back and the old build is still
        # running, so what the Admin needs to know is that the update never
        # happened rather than that it was undone.
        CU._wait_for_exit = lambda *a, **k: False
        CU.apply_update(package("2.3.0"), dest, os.getpid(), "2.1.0")
        got = result()
        eq("an app that never stopped is written down as failed",
           got.get("outcome"), "failed")
        eq("  and the install is left on the build it was on",
           io.open(os.path.join(dest, "notifier_app.py"),
                   encoding="utf-8").read(), "APP_VERSION = '2.1.0'\n")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        for _pkg in pkgs:
            shutil.rmtree(_pkg, ignore_errors=True)


def check_the_next_start_ships_what_the_applier_wrote():
    """The other side of the handover, and the deletion that ends it.

    #148. `common.report_update_result` is what turns the applier's file into a
    System Log entry, and it is `common.py`'s rather than each app's for rule
    10's reason - the file, the three event names and the wording are one fact
    both clients state.

    Both halves of the log are read back, as they are for every other entry
    these apps write: the shipping queue is the copy the Admin reads and
    `client.log` is what this machine can still say about itself.

    The **deletion** is the half worth driving. An outcome reported twice is an
    Admin reading two updates where one happened, and an outcome deleted before
    it was reported is one nothing anywhere says. So it is asserted both ways:
    the file goes once the entry is queued, and it survives a `log_event` that
    could not take it.
    """
    head("the next start ships what the applier wrote")

    def wrote(res):
        """Report `res` (a dict, or None for no file) and read both halves."""
        try:
            os.remove(C.UPDATE_RESULT_PATH)
        except OSError:
            pass
        if res is not None:
            io.open(C.UPDATE_RESULT_PATH, "w",
                    encoding="utf-8").write(json.dumps(res))
        with C._log_lock:
            del C._log_queue[:]
        io.open(C.LOG_PATH, "w", encoding="utf-8").close()
        event = C.report_update_result()
        with C._log_lock:
            shipped = [e for e in C._log_queue if e["event"].startswith("update.")]
        written = [l for l in io.open(C.LOG_PATH, encoding="utf-8")
                   if "update." in l]
        return event, shipped, written, os.path.exists(C.UPDATE_RESULT_PATH)

    real_log_event = C.log_event
    try:
        event, shipped, written, left = wrote(
            {"outcome": "applied", "from_version": "2.0.0",
             "to_version": "2.1.0", "sha256": "a" * 64,
             "detail": "the replaced files are in update_rollback\\2.0.0"})
        eq("an applied update is shipped as update.applied", event,
           "update.applied")
        eq("  and is in this machine's own client.log too", len(written), 1)
        detail = shipped[0]["detail"] if shipped else ""
        eq("  carrying both versions and the digest",
           [s for s in ("2.0.0", "2.1.0", "a" * 16) if s not in detail], [])
        eq("  and the file is gone, so it is not reported a second time",
           left, False)

        event, shipped, _w, left = wrote(
            {"outcome": "rolled_back", "from_version": "2.1.0",
             "to_version": "2.2.0"})
        eq("a rollback is shipped as update.rolled_back", event,
           "update.rolled_back")
        eq("  at error, since a fleet stuck on an old build is not an "
           "ordinary entry",
           shipped[0]["level"] if shipped else "", "error")

        event, shipped, _w, left = wrote(
            {"outcome": "failed", "from_version": "2.1.0"})
        eq("an update that never happened is shipped as update.failed", event,
           "update.failed")
        eq("  naming the version it was on and saying nothing it does not know",
           shipped[0]["detail"] if shipped else "", "2.1.0 -> ?")

        # The ordinary start, which is every start but the one after an update.
        event, shipped, _w, left = wrote(None)
        eq("an ordinary start ships nothing at all", [event, shipped], ["", []])

        # A file this build does not understand is still a file to be rid of:
        # left behind, it would be read again on every start for ever.
        event, shipped, _w, left = wrote({"outcome": "something-else"})
        eq("an outcome this build does not know is not an event",
           [event, shipped], ["", []])
        eq("  and is cleared rather than read again on every start for ever",
           left, False)

        # And the half that keeps the deletion honest. log_event never raises,
        # so the only way a caller can tell a queued entry from one that went
        # nowhere is the answer it gives - which is what this file is deleted
        # on, and nothing else here has a reason to read it.
        C.log_event = lambda *a, **k: False
        event, _s, _w, left = wrote(
            {"outcome": "applied", "from_version": "2.2.0",
             "to_version": "2.3.0"})
        eq("an entry the log could not take is not reported as shipped",
           event, "")
        eq("  and the file stays, so the outcome is not lost to it", left,
           True)
    finally:
        C.log_event = real_log_event
        try:
            os.remove(C.UPDATE_RESULT_PATH)
        except OSError:
            pass


def check_an_update_manifest_cannot_write_outside_the_install():
    """Phase one refuses a manifest entry that would land outside the install.

    `_extract` joins each name onto `dest`, and os.path.join with an absolute
    second argument discards the first while a `..` walks up. The cost is not a
    new way in - the zip is checked against the digest the server published, and
    a package that could be chosen freely already carries .py files the app runs
    - it is the **rollback**: `_save_for_rollback` walks the same list, so a name
    pointing outside `dest` saves nothing or saves the wrong file, and the
    restore cannot put back what was then overwritten. A failed update stays
    failed, with files where nobody will look and only update.log to say so.

    Asserted in phase one, because that is the whole of the split: a refusal
    there is a message box the app goes on running from, and by phase two the
    old files are already gone.

    client_update.py is staged beside the apps but nothing loaded it until this,
    so it had no gate at all.
    """
    head("an update manifest cannot write outside the install")
    CU = _load("client_update.py", "client_update")
    running = "%d.%d" % sys.version_info[:2]

    def manifest(names, launcher="run_notifier.pyw"):
        return {"app": "notifier", "version": "9.9.9",
                "python_version": running, "launcher": launcher,
                "files": dict.fromkeys(names, "")}

    def refusal(m):
        try:
            CU._check_manifest(m, "notifier", "9.9.9")
            return ""
        except CU.UpdateRefused as ex:
            return str(ex)

    eq("an ordinary payload is still accepted",
       refusal(manifest(["notifier_app.py", "lib/requests/__init__.py"])), "")
    eq("and one that walks up and back stays inside",
       refusal(manifest(["lib/../notifier_app.py"])), "")

    for name in ("../evil.py", r"..\evil.py", "lib/../../evil.py",
                 "/etc/passwd", "C:/Windows/System32/x.py",
                 r"\\server\share\x.py", "", "   ", "."):
        if refusal(manifest([name])):
            ok("refused: %r" % name)
        else:
            bad("accepted a name that escapes the install: %r" % name)

    if refusal(manifest(["notifier_app.py"], launcher="../run.pyw")):
        ok("and a launcher outside the install is refused too")
    else:
        bad("a launcher outside the install was accepted")

    eq("the refusal says the app is untouched",
       "untouched" in refusal(manifest(["../evil.py"])), True)


def check_an_update_with_nothing_to_apply_is_not_a_launch_nag():
    """A version the server cannot serve is answered once, when asked.

    `GET /version` answers with the running server's own APP_VERSION whatever
    else it holds, so a server that has been updated ahead of the bundles
    beside it tells every older client it is behind and offers it nothing -
    the "contact your admin" branch, which is the honest answer to an older
    server and a dead end on a launch check: a dialog nobody in front of it
    can act on, shown again on every launch for as long as the bundles are
    missing, with an `update.offered` beside it recording an offer that was
    not one.

    So the launch check says nothing and writes nothing there, and the manual
    check - a question somebody asked - is answered. Both apps, because both
    state the same two paths.

    Driven rather than read: what is asserted is which of two callers reaches
    the dialog, and the guard is one `and` that reads equally plausibly the
    wrong way round. `_prompt_update` touches no widget of its own on these
    paths, so it is called against a bare object with `messagebox` and
    `log_event` recorded - the real window would need a server, a tray and a
    Tk loop to say the same thing.

    The half that keeps it honest is the offer that **is** real: a launch
    check against a server holding this app's package still prompts, or the
    guard would be a client that has stopped offering updates at all.
    """
    head("an update with nothing to apply is not a launch nag")

    class Bare(object):
        """Enough of an app for the two paths that touch no widget."""
        def _forced_update(self, *a, **k):
            raise AssertionError("forced update reached")

        def _apply_source_update(self, *a, **k):
            raise AssertionError("in-place update reached")

    for mod, cls, label in ((NT, NT.NotifierApp, "Notifier"),
                            (SK, SK.StorekeeperApp, "Storekeeper")):
        shown, logged = [], []

        class Box(object):
            def showinfo(self, *a, **k):
                shown.append(("info", a))

            def askyesno(self, *a, **k):
                shown.append(("ask", a))
                return False

        had_box, had_log = mod.messagebox, mod.log_event
        mod.messagebox = Box()
        mod.log_event = lambda ev, detail="", **k: logged.append(ev)
        try:
            app = Bare()

            cls._prompt_update(app, "9.9.9", "", False)
            eq("%s: a launch check with nothing to apply shows nothing"
               % label, shown, [])
            eq("  and writes no update.offered", logged, [])

            cls._prompt_update(app, "9.9.9", "", False, manual=True)
            eq("  the manual check is answered",
               [k for k, _ in shown], ["info"])
            eq("  and is recorded as the offer it is",
               logged, ["update.offered"])

            shown[:] = []
            logged[:] = []
            cls._prompt_update(app, "9.9.9", "", True)
            eq("  a launch check the server holds a package for still asks",
               [k for k, _ in shown], ["ask"])
            eq("  and is recorded",
               logged[:1], ["update.offered"])
        finally:
            mod.messagebox, mod.log_event = had_box, had_log


def check_a_pushed_update_applies_only_where_there_is_one_to_apply():
    """The `update_now` Command, obeyed by both clients (#177).

    What an Admin pressing Update Selected is promising is that this machine
    ends up on the published release with nobody at it asked, and the three
    answers that promise rests on are all on this side of the wire: a Client
    already on the published version does **nothing** rather than reinstalling
    what it is running; a Client the server holds no package for stops rather
    than opening a browser at the installer, which is what the click path does
    and is exactly what an unattended push must not do; and only a Client that
    is behind applies anything. `_queue_command` refuses the middle one at
    issue time, but a week may pass before the machine collects the command,
    so the client has to answer it again for itself.

    Driven through each app's own handler rather than through a stub of it,
    since what is asserted is which of the three the handler picks. The
    download is the one thing stubbed: `_apply_source_update` puts megabytes
    on a worker against a server this file deliberately does not have.

    Two more things are asserted around them. An answer that applies nothing
    leaves `update_state.json` exactly as it found it - that file is the
    **engineer's** postpone count against a version they were asked about, and
    nobody was asked here. And a push arriving while an update is already
    running starts no second applier, two of them waiting on one process id
    being two extractions over one directory.
    """
    head("a pushed update applies only where there is one to apply")
    tk = tk_or_skip()
    if tk is None:
        return

    state = {"version": "9.9.9", "count": 3}
    with io.open(C.UPDATE_STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh)

    def postpone_state():
        with io.open(C.UPDATE_STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)

    class _Stub(object):
        """Stands in for `client_update`, and records what it was asked."""

        class UpdateRefused(Exception):
            pass

        def __init__(self):
            self.calls = []

        def update_now(self, *a, **k):
            self.calls.append(a)

    # -- the Notifier ----------------------------------------------------
    app = NT.NotifierApp()
    app._poll_once = lambda: None
    real_check, real_log = NT.check_for_update, NT.log_event
    real_cu = NT.client_update
    applied, entries = [], []
    try:
        app._apply_source_update = lambda v: applied.append(v)
        NT.log_event = (lambda ev, detail="", level="info", **kw:
                        entries.append((ev, detail, level)))
        handlers = app._commands()
        eq("the Notifier has a handler for the command",
           "update_now" in handlers, True)

        NT.check_for_update = lambda url: None
        handlers["update_now"]()
        eq("a Client already on the published version applies nothing",
           applied, [])
        eq("  and says so", entries[-1][0], "command.obeyed")
        eq("  at info, an ordinary answer rather than a failure",
           entries[-1][2], "info")
        eq("  naming the version it is on",
           NT.APP_VERSION in entries[-1][1], True)

        NT.check_for_update = lambda url: ("9.9.9", "http://x/y", False)
        handlers["update_now"]()
        eq("a server with no package for this app applies nothing",
           applied, [])
        eq("  and says so at warn", entries[-1][2], "warn")
        eq("  naming the version it cannot apply",
           "9.9.9" in entries[-1][1], True)

        eq("neither answer touched the engineer's postpone count",
           postpone_state(), state)

        NT.check_for_update = lambda url: ("9.9.9", "http://x/y", True)
        handlers["update_now"]()
        eq("a Client that is behind applies the published release",
           applied, ["9.9.9"])
        eq("  and says so at warn", entries[-1][2], "warn")
        eq("every one of them is one entry under one name",
           [e[0] for e in entries], ["command.obeyed"] * 3)

        # The guard is `_apply_source_update`'s own, so the real one is called
        # here with the flag already set - a stub of it would be asserting this
        # file's own lambda.
        stub = _Stub()
        NT.client_update = stub
        app._updating = True
        NT.NotifierApp._apply_source_update(app, "9.9.9")
        eq("a push during an update starts no second applier", stub.calls, [])
    finally:
        NT.check_for_update, NT.log_event = real_check, real_log
        NT.client_update = real_cu
        try:
            app.root.destroy()
        except Exception:
            pass

    # -- the Storekeeper -------------------------------------------------
    # This app has no module-level check_for_update at all - the /version read
    # is its own, inline on the tick - so `api` is what stands in for the
    # server here, the same transport every other group in this file stubs.
    root = tk.Tk()
    root.withdraw()
    sk = SK.StorekeeperApp(root)
    real_api, real_log = SK.api, SK.log_event
    real_cu = SK.client_update
    applied, entries = [], []

    class _Answer(object):
        def __init__(self, payload):
            self.ok, self._payload = True, payload

        def json(self):
            return self._payload

    def version(latest, packaged):
        pkg = {SK.UPDATE_APP_KEY: {"path": "x.zip"}} if packaged else {}
        return lambda *a, **k: _Answer({"latest": latest,
                                        "client_packages": pkg})

    try:
        sk._apply_source_update = lambda v: applied.append(v)
        SK.log_event = (lambda ev, detail="", level="info", **kw:
                        entries.append((ev, detail, level)))

        SK.api = version(SK.APP_VERSION, True)
        sk._update_now()
        eq("the Storekeeper already on the published version applies nothing",
           applied, [])
        eq("  and says so at info", entries[-1][2], "info")

        SK.api = version("9.9.9", False)
        sk._update_now()
        eq("with no package for this app it applies nothing", applied, [])
        eq("  and says so at warn", entries[-1][2], "warn")

        SK.api = _offline
        sk._update_now()
        eq("a server that cannot be reached applies nothing", applied, [])

        eq("and none of the three touched the postpone count",
           postpone_state(), state)

        SK.api = version("9.9.9", True)
        sk._update_now()
        eq("behind the published version it applies it", applied, ["9.9.9"])
        eq("  at warn", entries[-1][2], "warn")
        eq("every one of them is attributed",
           all(e[0] == "command.obeyed" for e in entries), True)

        stub = _Stub()
        SK.client_update = stub
        sk._updating = True
        SK.StorekeeperApp._apply_source_update(sk, "9.9.9")
        eq("a push during an update starts no second applier here either",
           stub.calls, [])
    finally:
        SK.api, SK.log_event = real_api, real_log
        SK.client_update = real_cu
        try:
            root.destroy()
        except Exception:
            pass
    os.remove(C.UPDATE_STATE_PATH)

    # The Storekeeper's handler map is built inline in the 15s tick, which
    # needs a server to reach, so that the command is wired to that handler at
    # all is read off the source rather than driven.
    if '"update_now": lambda: self._update_now()' in SRC["storekeeper_app.py"]:
        ok("the Storekeeper's obey() hands update_now to that handler")
    else:
        bad("the Storekeeper's obey() does not hand update_now to a handler")
