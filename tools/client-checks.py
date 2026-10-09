r"""Window checks for the three client apps. Reports failures and exits non-zero.

    py -3.12 tools\client-checks.py
    py -3.12 tools\client-checks.py --group popup     one group, while
                                                      iterating on it
    py -3.12 tools\client-checks.py --check check_the_storekeeper_windows_fit
                                    one check_* group alone, smaller again

The third gate, beside cascade-audit.py (does the repo contradict itself?) and
server-checks.py (does the server do what it is supposed to?). This one asks
whether the Storekeeper's, the Notifier's and the installer's windows are big
enough for the forms inside them - and, for the one place it matters, *which*
window opens: the Notifier's decision to demand a Temporary Own Password be
replaced is a Tk callback, so nothing static reaches it and no endpoint answers
for it. Same idiom as the other two on purpose: plain
Python, standard library only, no test framework and no new dependency, so it
can gate a release without adding anything to requirements-server.txt - which
feeds a vendored lib\ pinned to one Python minor version, rule 13.

The checks themselves live in tools/client_checks/, one module per group of
them, and the staging tree they all read is client_checks/stage.py - see its
docstring for what staging is for, why applaunch.py is staged beside the apps,
and why there is no server. This file is the front door gate.py names: it
imports the group modules in the fixed order below, collects their check_*
functions, and runs the slice --shard asks for. 8,980 lines in one file was
what #238 split, the way #221 split server-checks.py; nothing about how a run
behaves moved with it.

Its own suite rather than more groups in server-checks.py. That harness is
server-shaped from its first line - it stages server.py, drives Flask's test
client, and every helper in it takes a database - while nothing here touches a
database or an endpoint at all: three Tk apps are opened and read back off the
screen. The one thing the two share is `ui_kit.fit`, which server-checks.py
already measures the Server GUI's six callers against.

That means ok(), bad(), head(), widgets() and the per-axis loop in measure()
are a second copy of what server-checks.py holds, and knowingly - each suite
keeps its own in its own stage.py. Rule 10's argument does not reach them: it
is about code that ships, where one fix has to be right in three places at
once, and these two suites ship to nobody - they are gates, run from a
checkout. A third module under tools\ for four reporting helpers would be a
file to import before either gate could run, and the two have already drifted
apart where it matters (this one has no database, no test client and no
Flask). If they ever share more than the reporting, that is the moment to
extract, not before.

**One group opens nothing at all.** `notifier_pending.py` is the Notifier's
Pending decisions with no tkinter in it (#208), and the group that drives it
calls no `tk_or_skip()` and builds no app - it runs on a machine with no
desktop. That is the whole point of the module: while the same logic sat inside
Tk callbacks, the only way to assert any of it was to open a real window and
measure it, which is the reading this suite is worst at. If that group ever
needs a root window, the seam is in the wrong place.

**The windows are measured inside the real app.** An app configures its ttk
styles and fonts at startup and those are what its forms are drawn with: the
same dialog under a bare tk.Tk() asks for 24px less than an admin sees, which is
how a wrong figure reached issue #25 and three docstrings. So each group builds
the app the way its entry point does and opens the dialogs off it. The three
apps each want their own Tk, so the groups run one app at a time and destroy it.

Adding a check: put it in a function named check_*, take no arguments, and use
ok()/bad() from client_checks.stage. Put it in the group module its subject
belongs to; a subject none of them covers gets a module of its own and a line
in GROUPS below, which is the one list a new group needs. They are found and
run in the order the groups are named here, and within a group in definition
order.
"""
import importlib
import shutil
import sys

import _offscreen

from client_checks import stage

# The order the groups run in, and the only place it is written down. main()
# sorts within a module by source line the way the one file did, so a check
# added to a module runs where it sits; a module added here runs after the one
# above it. --group runs one of these alone and is the one thing that needs
# this list by name; --shard slices the collected list by position, so any
# slice is a valid run and the union of n shards is the whole suite, whatever
# this order is - what it buys is that two runs of the same tree run the same
# groups.
GROUPS = (
    "storekeeper",
    "offline",
    "notifier",
    "remote_admin",
    "popup",
    "install",
    "icon",
    "update",
    "wire",
    "masked",
    "sizing",
    "launcher",
    "single_window",
    "screen",
)


def main():
    if stage.LIST_GROUPS:
        print("\n".join(GROUPS))
        shutil.rmtree(stage.STAGE, ignore_errors=True)
        return 0
    names = GROUPS
    if stage.GROUP:
        # Checked here rather than in stage.py: GROUPS is the one list of
        # them, and a name it does not hold is a typo that would otherwise
        # run nothing and report a green suite of zero assertions.
        if stage.GROUP not in GROUPS:
            shutil.rmtree(stage.STAGE, ignore_errors=True)
            raise SystemExit("no check group named %s - --list-groups "
                             "prints the %d there are"
                             % (stage.GROUP, len(GROUPS)))
        names = (stage.GROUP,)
    checks = []
    for name in names:
        mod = importlib.import_module("client_checks.%s" % name)
        # co_filename rather than everything named check_ in the module: a
        # group that imports a fixture out of another one would otherwise run
        # that group's checks a second time, and a doubled group reads as a
        # rise in the assertion count rather than as a fault.
        found = [(fn.__code__.co_firstlineno, fn)
                 for key, fn in vars(mod).items()
                 if key.startswith("check_") and callable(fn)
                 and getattr(fn, "__code__", None)
                 and fn.__code__.co_filename == mod.__file__]
        checks.extend(fn for _line, fn in sorted(found, key=lambda p: p[0]))
    if stage.LIST_CHECKS:
        print("\n".join(fn.__name__ for fn in checks))
        shutil.rmtree(stage.STAGE, ignore_errors=True)
        return 0
    if stage.CHECK:
        # The names come off the functions rather than a list kept beside
        # them, so there is nothing to fall out of step. A name none of
        # them carries is a typo, and running it would otherwise assert
        # nothing and report a green suite of no assertions.
        wanted = [fn for fn in checks if fn.__name__ == stage.CHECK]
        if not wanted:
            shutil.rmtree(stage.STAGE, ignore_errors=True)
            raise SystemExit("no check group named %s - --list-checks "
                             "prints the %d there are"
                             % (stage.CHECK, len(checks)))
        checks = wanted
    _offscreen.enable_if_asked()
    i, n = stage.SHARD
    mine = checks[i - 1::n]
    for fn in mine:
        try:
            fn()
        except Exception as ex:
            stage.head(fn.__name__)
            stage.bad("raised %s: %s" % (type(ex).__name__, ex))

    print("\n" + "=" * 66)
    # A partial run says so on the line that is read, for the reason the
    # shard suffix already existed: green over one group is not green.
    slice_ = "" if n == 1 else " of shard %d/%d" % (i, n)
    if stage.GROUP:
        slice_ += " of --group %s" % stage.GROUP
    if stage.CHECK:
        slice_ += " of --check %s" % stage.CHECK
    if stage.fails:
        print("%d FAILURE(S)%s" % (len(stage.fails), slice_))
        for f in stage.fails:
            print("  FAIL: %s" % f)
    else:
        print("all checks passed (%d check group(s)%s, %d assertion(s), "
              "%d skipped)" % (len(mine), slice_, stage._passed[0],
                                stage._skipped[0]))
    shutil.rmtree(stage.STAGE, ignore_errors=True)
    return 1 if stage.fails else 0


if __name__ == "__main__":
    sys.exit(main())
