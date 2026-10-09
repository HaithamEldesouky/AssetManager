r"""Behaviour checks for server.py. Reports failures and exits non-zero.

    py -3.12 tools\server-checks.py
    py -3.12 tools\server-checks.py --group console   one group, while
                                                      iterating on it

The companion to cascade-audit.py: that one checks whether the repo contradicts
itself, this one checks whether the server does what it is supposed to. Same
idiom on purpose - plain Python, standard library only, no test framework and no
new dependency, so it can gate a release next to the audit without adding
anything to requirements-server.txt (which feeds a vendored lib\ pinned to one
Python minor version - see rule 13).

The checks themselves live in tools/server_checks/, one module per group of
them, and the staging tree they all read is server_checks/stage.py - see its
docstring for what staging is for. This file is the front door gate.py names:
it imports the group modules in the fixed order below, collects their check_*
functions, and runs the slice --shard asks for. 18,758 lines in one file was
what #221 split; nothing about how a run behaves moved with it.

One group is not about server.py at all: common.verify_password, the client side
of /auth/verify. It sits here because the endpoint's contract and the client's
reading of it are one fact checked in two directions, and because the only leg
that cannot be reached from a live server is the fallback for a server that
predates the endpoint - there is no such server to point at, so the transport is
stubbed. common.py is staged and imported the same way server.py is.

Adding a check: put it in a function named check_*, take no arguments, and use
ok()/bad() from server_checks.stage. Put it in the group module its subject
belongs to; a subject none of them covers gets a module of its own and a line
in GROUPS below, which is the one list a new group needs. They are found and
run in the order the groups are named here, and within a group in definition
order.
"""
import importlib
import shutil
import sys

import _offscreen

from server_checks import stage

# The order the groups run in, and the only place it is written down. main()
# sorts within a module by source line the way the one file did, so a check
# added to a module runs where it sits; a module added here runs after the one
# above it. --group runs one of these alone and is the one thing that needs
# this list by name; --shard slices the collected list by position, so any slice is a
# valid run and the union of n shards is the whole file, whatever this order
# is - what it buys is that two runs of the same tree run the same groups.
GROUPS = (
    "settings",
    "passwords",
    "own_password",
    "engineers",
    "admin_config",
    "console",
    "auto_accept",
    "system_log",
    "mail",
    "sync",
    "api",
    "cancellation",
    "doors",
    "db_path",
    "transactions",
    "lookup",
    "corrections",
    "clients",
    "capabilities",
    "storekeeper",
    "tls",
    "holds",
    "archive",
    "certificates",
    "windows",
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
        # run nothing and report a green file of zero assertions.
        if stage.GROUP not in GROUPS:
            shutil.rmtree(stage.STAGE, ignore_errors=True)
            raise SystemExit("no check group named %s - --list-groups "
                             "prints the %d there are"
                             % (stage.GROUP, len(GROUPS)))
        names = (stage.GROUP,)
    _offscreen.enable_if_asked()
    checks = []
    for name in names:
        mod = importlib.import_module("server_checks.%s" % name)
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
