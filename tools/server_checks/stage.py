r"""The staging tree every check group reads, and the fixtures they share.

Split out of tools/server-checks.py by #221; what that file's own docstring
says about staging is said here, where the staging is.

It **stages a copy of server.py in a scratch directory and imports that**, never
the one in the repo. Every path in server.py resolves next to the source file, so
importing the repo's copy would read the developer's own server_config.json and
*write* their admin_config.json at import time - `ADMIN_CFG = load_admin_cfg()`
runs at module level. Staging is the same reason dev-run.ps1 gives each app its
own directory.

The API is driven through Flask's own test client rather than over a socket. No
port to pick, no server to start or fail to stop, and it works on a machine where
8081 is already served by the real thing.

One tree, built once at import, for every group in the package: a second staging
tree per group file would multiply the setup cost tools/gate.py measures, and the
groups hand each other no state to be confused by - each builds the database it
needs and tears it down.

The reporting half lives here too - ok(), bad(), skip(), head(), eq() and the
counters behind them - so that a group file holds check functions and nothing
else, and the last line of a run counts every group's assertions in one place.
A fixture below this banner is one that more than one group file reads; a fixture
only one group reads sits in that group's file.
"""
r"""Behaviour checks for server.py. Reports failures and exits non-zero.

    py -3.12 tools\server-checks.py

The companion to cascade-audit.py: that one checks whether the repo contradicts
itself, this one checks whether the server does what it is supposed to. Same
idiom on purpose - plain Python, standard library only, no test framework and no
new dependency, so it can gate a release next to the audit without adding
anything to requirements-server.txt (which feeds a vendored lib\ pinned to one
Python minor version - see rule 13).

It **stages a copy of server.py in a scratch directory and imports that**, never
the one in the repo. Every path in server.py resolves next to the source file, so
importing the repo's copy would read the developer's own server_config.json and
*write* their admin_config.json at import time - `ADMIN_CFG = load_admin_cfg()`
runs at module level. Staging is the same reason dev-run.ps1 gives each app its
own directory.

The API is driven through Flask's own test client rather than over a socket. No
port to pick, no server to start or fail to stop, and it works on a machine where
8081 is already served by the real thing.

One group is not about server.py at all: common.verify_password, the client side
of /auth/verify. It sits here because the endpoint's contract and the client's
reading of it are one fact checked in two directions, and because the only leg
that cannot be reached from a live server is the fallback for a server that
predates the endpoint - there is no such server to point at, so the transport is
stubbed. A gate script of its own for one function would be a third thing to run
and remember. common.py is staged and imported the same way server.py is.

Adding a check: put it in a function named check_*, take no arguments, and use
ok()/bad(). They are found and run in definition order.
"""
import ast
import base64
import hashlib
import inspect
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import types
from datetime import datetime, timedelta

import _offscreen

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

R = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
fails = []


# -- how much of a run is printed, and which slice of it runs ----------------
# Both flags exist for the same measurement: 236 groups, six minutes and 2626 lines of [OK]. A wall of green
# is not read, and a serial run of it is not run either - which is how a gate
# stops being a gate and becomes a thing to skip.
#
#   -v / --verbose   print every passing line, the way this file always did
#   --shard i/n      run only every n-th group starting at the i-th, so
#                    tools/gate.py can run n copies of this at once
#   --group NAME     run one group module alone, for iterating on it
#   --list-groups    print the group names and exit
#
# The slice is by position rather than by name so that adding a group needs no
# list kept anywhere. Groups do not hand each other state - each builds the
# database it needs and tears it down - so any slice of them is a valid run;
# what a shard cannot say is that the *whole* file is green, which is why
# gate.py aggregates the exit codes rather than trusting one of them.
#
# Quiet is the default rather than the flag because a skipped assertion is the
# failure mode this file has: the counts on the last line are what says a run
# asserted as much as the last one did, and a skip is counted there rather than
# swallowed - a group that quietly stopped measuring reads as a drop in the
# count instead of as a clean run.
ARGV = sys.argv[1:]               # before the staging block below reassigns it
USAGE = r"""usage: py -3.12 tools\server-checks.py [-v] [--shard i/n] [--group NAME]

  -v, --verbose  print every passing assertion rather than the last line only
  --shard i/n    run every n-th check starting at the i-th, for tools\gate.py
  --group NAME   run one group of tools/server_checks/ alone, for iterating
  --list-groups  print the group names and exit
  -h, --help     print this and exit
"""
VERBOSE = False
SHARD = (1, 1)
GROUP = None
LIST_GROUPS = False

# An argument this does not know is refused rather than skipped past. The scan
# this replaced only ever looked for the flags it wanted, so everything else
# fell through to a full serial run: `--help` on a six-minute suite printed
# nothing and ran for six minutes, and a mistyped `--shrad 3/8` ran the whole
# file while reading as a shard. Both are silent, and the second is the one
# that matters - gate.py aggregates exit codes, so eight whole runs claiming to
# be eight shards come back green.
#
# --group is by name where --shard is by position, and it is the one thing here
# that needs the list of groups kept somewhere. That list already exists, in
# server-checks.py, which is where the name is checked: this file only carries
# what was asked for, so the name and the order stay in one place.
_args = []
for _a in ARGV:                   # --flag=value and --flag value are one case
    _args.extend(_a.split("=", 1) if _a.startswith("--") and "=" in _a
                 else [_a])
while _args:
    _a = _args.pop(0)
    if _a in ("-v", "--verbose"):
        VERBOSE = True
    elif _a == "--list-groups":
        LIST_GROUPS = True
    elif _a in ("-h", "--help"):
        print(USAGE)
        raise SystemExit(0)
    elif _a == "--shard":
        if not _args:
            raise SystemExit("--shard wants i/n, e.g. --shard 3/8")
        _spec = _args.pop(0)
        try:
            _one, _of = (int(x) for x in _spec.split("/", 1))
        except ValueError:
            raise SystemExit("--shard wants i/n, e.g. --shard 3/8")
        if not 1 <= _one <= _of:
            raise SystemExit("--shard %s is not a slice of anything" % _spec)
        SHARD = (_one, _of)
    elif _a == "--group":
        if not _args:
            raise SystemExit("--group wants a group name - --list-groups "
                             "prints them")
        GROUP = _args.pop(0)
    else:
        raise SystemExit("unknown argument %s\n\n%s" % (_a, USAGE))

_group = [None]                   # named by head(), printed by the first bad()
_passed = [0]
_skipped = [0]


def ok(msg):
    _passed[0] += 1
    if VERBOSE:
        print("  [OK]   %s" % msg)


def bad(msg):
    if _group[0] is not None:
        print("\n=== %s ===" % _group[0])
        _group[0] = None          # one heading per group, however many fail
    print("  [FAIL] %s" % msg)
    fails.append(msg)


def skip(msg):
    _skipped[0] += 1
    if VERBOSE:
        print("  [skip] %s" % msg)


def head(msg):
    if VERBOSE:
        print("\n=== %s ===" % msg)
        _group[0] = None          # already on the screen; bad() need not
    else:
        _group[0] = msg


def eq(label, got, want):
    if got == want:
        ok("%s: %r" % (label, got))
    else:
        bad("%s: got %r, wanted %r" % (label, got, want))


# ── staging ──────────────────────────────────────────────────────────────────

STAGE = tempfile.mkdtemp(prefix="server-checks_")
#: The server's own modules, in the order server.py imports them and the
#: nine windows #235 split out of server_gui.py after. One tuple rather than
#: two lists: both staging sites below copy exactly this, and the second also
#: takes every one of them out of sys.modules so a staged server binds its own.
SERVER_SRC = ("server.py", "server_gui.py", "server_cert.py",
              "register_assets.py", "register_transactions.py",
              "register_engineers.py", "server_mail.py",
              "server_sync.py", "server_clients.py",
              "server_log.py", "server_archive.py",
              "server_lookup.py", "server_iis.py",
              "gui_assets.py", "gui_backup.py", "gui_clients.py",
              "gui_log.py", "gui_mail.py", "gui_proposals.py",
              "gui_records.py", "gui_settings.py", "gui_users.py")

for _name in SERVER_SRC + ("ui_kit.py",):
    shutil.copy2(os.path.join(R, _name), os.path.join(STAGE, _name))
# server.py imports ui_kit, and this file is run as tools\server-checks.py, so
# sys.path[0] is tools\ and the repo root is not on it at all. Staging the kit
# and putting STAGE first means the module under test imports the copy beside
# it, the same way it will beside AssetServer.exe.
sys.path.insert(0, STAGE)
sys.argv = ["server.py"]          # no CLI verb: import must not run a command


# The screen every window is judged against (095). `ui_kit.fit` clamps a
# window's height to the screen less 80px, and `pack` gives the shortfall to
# whatever it served last, so on a 1366x768 laptop a form asking more than
# 688px is a form whose tail cannot be reached by any drag or scroll. The
# staged `fit` is wrapped once, here, and every call is judged on the spot
# rather than in a group at the end, so `--group NAME` run alone still judges
# every window that group opens. A window over the line passes only if it
# scrolls: a direct child `tk.Canvas` holding a windowed `tk.Frame`, the one
# shape `ui_kit.ScrollRegion` builds. FIT_SEEN is what the `screen` group reads
# to prove the recorder is still measuring.
SCREEN_ROOM = 768 - 80
FIT_SEEN = {}                     # window title -> tallest height it asked
_FIT_FAILED = set()

import ui_kit as _ui_kit          # noqa: E402

_fit_unwrapped = _ui_kit.fit


def _scrolls(win):
    import tkinter as tk
    for c in win.winfo_children():
        if not isinstance(c, tk.Canvas):
            continue
        for item in c.find_all():
            if c.type(item) != "window":
                continue
            try:
                body = c.nametowidget(c.itemcget(item, "window"))
            except Exception:
                continue
            if isinstance(body, tk.Frame):
                return True
    return False


def _recording_fit(win, width):
    out = _fit_unwrapped(win, width)
    title = win.title()
    h = win.winfo_reqheight()
    FIT_SEEN[title] = max(h, FIT_SEEN.get(title, 0))
    if h > SCREEN_ROOM and title not in _FIT_FAILED and not _scrolls(win):
        _FIT_FAILED.add(title)    # once per window, however often it refits
        bad("%s asks for %dpx of height, more than the %dpx a 768px screen "
            "leaves it, and does not scroll" % (title, h, SCREEN_ROOM))
    return out


_ui_kit.fit = _recording_fit


import importlib.util as _iu      # noqa: E402

_spec = _iu.spec_from_file_location("srv_under_test",
                                    os.path.join(STAGE, "server.py"))
M = _iu.module_from_spec(_spec)
# Registered before exec, the way a plain `import` would: server.py hands
# server_gui its own module through `sys.modules[__name__]` (#207), which is
# only populated by the import machinery itself - runpy.run_path does this
# for a real launch, so exec_module has to do it here too, or the bind call
# is a KeyError instead of a live GUI.
sys.modules[_spec.name] = M
try:
    _spec.loader.exec_module(M)
except ImportError as ex:
    print("cannot import server.py: %s" % ex)
    print("run with the interpreter that has the server's dependencies, e.g."
          "  py -3.12 tools\\server-checks.py")
    sys.exit(2)

assert os.path.dirname(M.SERVER_CFG_PATH) == STAGE, "staging did not take"

# server_gui.py's own module, live - not the copy `from server_gui import
# INPUT_BG, DANGER, SUCCESS` left in M. That import ran once, at M's own
# load, and copied whatever the three names held then; `THEME.set()`
# afterwards rewrites server_gui's globals (#207's bind() reaches back the
# other way, from server_gui into server.py, so this is the one direction
# a plain `from import` cannot follow), and M's copies go stale. Reading
# them off GM instead asks the module THEME actually paints.
GM = sys.modules["server_gui"]

# server_iis.py's own module, live, for GM's reason turned the other way:
# `_iis_tls_bound` and `_remote_tls_ok` read `_iis_host` and
# `_port_serves_tls` as globals inside that module now (#243), not through
# `server.py`'s namespace, so a check steering what either of them sees
# has to patch IM rather than M - patching M._iis_host only moves what
# `server_gui.py` reads as `S._iis_host()` directly.
IM = sys.modules["server_iis"]

# An unreadable sheet, written before the first init_db of this run. Since 024
# the Lookup Sheet lives in the database and init_db seeds an empty one from
# asset_lookup.xlsx - the embedded workbook holds 3462 assets, which would be
# read and inserted into every database this file makes, and would then refuse
# the made-up asset numbers these checks are written with (rule 6). The group
# that proves the seeding works stages a real workbook of its own.
with io.open(M.LOOKUP_PATH, "wb") as _f:
    _f.write(b"")

# common.py too, for the one client-side group. It is staged for the same reason
# server.py is - every path in it resolves next to the source file - though it is
# the gentler case: nothing it does at import reads or writes anything.
shutil.copy2(os.path.join(R, "common.py"), os.path.join(STAGE, "common.py"))
_cspec = _iu.spec_from_file_location("common_under_test",
                                     os.path.join(STAGE, "common.py"))
C = _iu.module_from_spec(_cspec)
_cspec.loader.exec_module(C)
assert os.path.dirname(C.SSL_CERT_PATH) == STAGE, "common staging did not take"
SRC = io.open(os.path.join(R, "server.py"), encoding="utf-8", newline="").read()
# The certificate lifecycle is its own module since #206, and the Server GUI
# since #207 - so a check that reads a cert function's source, or a console
# window's, reads CERT_SRC or GUI_SRC instead of SRC. The three are kept
# apart rather than concatenated: several checks here assert that a spelling
# is *absent* from the file they name, and a joined text would answer for
# all three.
CERT_SRC = io.open(os.path.join(R, "server_cert.py"), encoding="utf-8",
                   newline="").read()
# The console is ten files since #235 (060): `server_gui.py` is the shell it
# left behind, and the twelve windows sit in the nine `gui_*.py` modules beside
# it. GUI_SRC is all ten joined, because what every check reading it asks is
# about a *window* rather than about one file's own text - whether Mail
# Settings checks the admin password, which functions name the staged pair,
# what reads the fingerprint. The note above still holds for the texts it was
# written about: SRC, CERT_SRC and IIS_SRC each answer for one file, and the
# checks asserting a spelling is absent from one of those read them alone.
GUI_FILES = ("server_gui.py",) + tuple(_n for _n in SERVER_SRC
                                       if _n.startswith("gui_"))
GUI_SRC = "\n".join(io.open(os.path.join(R, _n), encoding="utf-8",
                            newline="").read() for _n in GUI_FILES)


def console_door(label):
    """What the console's `SECTIONS` entry `label` is gated on (096).

    `"admin"` is `_admin_again` on every open, `True` is `_console_unlock`
    once a sitting, `False` is no door; None where no entry has that label.
    Read off the tuple itself - `(label, subtitle, gated, command)` - so a
    check asks the question the console answers rather than grepping for a
    spelling of it.
    """
    tree = ast.parse(io.open(os.path.join(R, "server_gui.py"),
                             encoding="utf-8").read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Tuple) and len(node.elts) == 4
                and isinstance(node.elts[0], ast.Constant)
                and node.elts[0].value == label
                and isinstance(node.elts[2], ast.Constant)):
            return node.elts[2].value
    return None


# And server_iis.py since #243, kept apart for the same reason: what is
# there in server.py after the move is a single _iis_host() call, and
# more than one check below asks whether that stayed the only call and
# the only read of IIS_STATE_PATH left in this file.
IIS_SRC = io.open(os.path.join(R, "server_iis.py"), encoding="utf-8",
                  newline="").read()
# And the Assets register since #215, kept apart for the same reason.
REG_SRC = io.open(os.path.join(R, "register_assets.py"), encoding="utf-8",
                  newline="").read()
# The Transactions register since #216, the same again. This one is read by
# more checks than REG_SRC is: the four functions it holds are where the
# lookup-sheet rule, the cancel credential and the notes caps are enforced,
# and every check that reads one of those out of the source now reads it here.
TXN_SRC = io.open(os.path.join(R, "register_transactions.py"),
                  encoding="utf-8", newline="").read()
# The two joined, for a check that is asking about the console and the API
# together rather than about one file's own text - "does anything call this",
# "how many functions read that column" - where which of the two files answers
# is not the question. A check asking whether a spelling is *absent* from one
# named file keeps using SRC or GUI_SRC alone, per the note above.
SRC_ALL = SRC + "\n" + GUI_SRC
# server.py, server_gui.py and server_iis.py, for a check whose subject
# spans a call server_gui.py makes into a function server_iis.py now
# holds - _iis_tls_bound calling _iis_host and _port_serves_tls, and
# run_gui asking _iis_tls_bound, being one relationship the checks below
# read out of one tree rather than three.
SRC_ALL_IIS = SRC_ALL + "\n" + IIS_SRC
# And the three, for the checks whose subject is one of the four functions
# #216 moved into the Transactions register. The rule each of them enforces did
# not move - the notes cap, the cancel credential, the newest-per-asset query,
# the Pending-only rule - so a check that reads only the API and the console
# now reports `_create_transaction is gone` rather than reading it where it
# lives. A third name rather than a wider SRC_ALL, for the reason REG_SRC is
# kept apart: the checks that ask whether a spelling is *absent* from one named
# file still need a text that answers for that file alone, and there are two
# below whose whole subject is that the register's own `def` line is not what
# they found.
SRC_TXN_ALL = SRC_ALL + "\n" + TXN_SRC
# The Engineers register since #217, kept apart for REG_SRC's reason and joined
# for SRC_TXN_ALL's: the six functions it holds are where an Engineer is added,
# renamed and removed, and the checks below that ask who writes
# `team_members`, or what a rename moves with it, are asking about the API, the
# console and the register together.
ENG_SRC = io.open(os.path.join(R, "register_engineers.py"), encoding="utf-8",
                  newline="").read()
SRC_ENG_ALL = SRC_ALL + "\n" + ENG_SRC
# And the mail module since #224, kept apart and joined for the same two
# reasons: every mail and notification-rule helper below lives there now, so
# the checks that ask which functions reach the stored secret, who writes the
# settings, or what calls `_notify_of` are asking about the API, the console
# and this module together. `_secret_set` and `_secret_get` stayed in
# `server.py`, so the DPAPI half of those checks still reads the file it
# always did.
MAIL_SRC = io.open(os.path.join(R, "server_mail.py"), encoding="utf-8",
                   newline="").read()
SRC_MAIL_ALL = SRC_ALL + "\n" + MAIL_SRC
# And the external asset system since #225, kept apart and joined for the
# same two reasons: every `_sync_*` helper below lives there now except
# `_sync_admin_cfg`, which shares the prefix and nothing else and stayed, so
# the two checks that ask which functions reach the credential's file and
# what the reconcile writes through are asking about the API, the console
# and this module together. The window that drives all of it is still
# `server_gui.py`'s, so `GUI_SRC` is as much of the answer as it ever was.
SYNC_SRC = io.open(os.path.join(R, "server_sync.py"), encoding="utf-8",
                   newline="").read()
SRC_SYNC_ALL = SRC_ALL + "\n" + SYNC_SRC
# And the registry of installations since #226, kept apart and joined for
# the same two reasons: the check-in, the queue, the registry read and the
# stale sweep live there now, while the five `/clients*` routes and the
# Connected Clients window that drive them did not move, so the two groups
# that ask what the registry exposes and what the command controls do are
# asking about the routes, the console and this module together.
CLIENTS_SRC = io.open(os.path.join(R, "server_clients.py"),
                      encoding="utf-8", newline="").read()
SRC_CLIENTS_ALL = SRC_ALL + "\n" + CLIENTS_SRC
# And the System Log since #227, kept apart and joined for the same two
# reasons: the writer, the readers, the clear and the two retention bounds
# live there now, while `POST /clients/log` and the System Log window that
# drive them did not move, so a group that asks what the retention does is
# asking about the route, the console and this module together. The mail
# hook is the one that needs both this and `MAIL_SRC`: `_notify_of` is
# `server_mail.py`'s and its one caller is `_log_event`, which is here.
LOG_SRC = io.open(os.path.join(R, "server_log.py"),
                  encoding="utf-8", newline="").read()
SRC_LOG_ALL = SRC_ALL + "\n" + LOG_SRC
SRC_MAIL_LOG_ALL = SRC_MAIL_ALL + "\n" + LOG_SRC
# And backup, restore, the migrations and the archive since #228, kept
# apart and joined for the same two reasons: the backup, the restore,
# the migration engine and the archive live there now, while the window
# that drives all of it, `POST /records/import` and the `migrate` verb
# did not move, so the groups that ask what a backup carries, which
# helpers open no window and which functions insert a Transaction are
# asking about the routes, the console and this module together. The
# last of those needs `TXN_SRC` as well: `_create_transaction` is
# `register_transactions.py`'s and `_import_records_xlsx` is here, and
# the point of the check is that those two are the only pair.
BACKUP_SRC = io.open(os.path.join(R, "server_archive.py"),
                     encoding="utf-8", newline="").read()
SRC_BACKUP_ALL = SRC_ALL + "\n" + BACKUP_SRC
SRC_TXN_BACKUP_ALL = SRC_TXN_ALL + "\n" + BACKUP_SRC
# And the asset lookup's write path and the proposals since #229, kept
# apart and joined for the same two reasons: the mapping, the verdicts,
# the proposals and the three readers live there now, while the nine
# routes and the two windows that drive them did not move, so the
# groups that ask which function holds a rule and which one writes are
# asking about the routes, the console and this module together.
# `_owners_of` needs it too - `INSERT INTO asset_proposals` and the
# decision's `UPDATE` moved with `_propose_asset` and
# `_decide_proposal`, and the whole point of that check is that no
# second function holds either string.
LOOKUP_SRC = io.open(os.path.join(R, "server_lookup.py"),
                     encoding="utf-8", newline="").read()
SRC_LOOKUP_ALL = SRC_ALL + "\n" + LOOKUP_SRC
SRC_OWNERS_ALL = SRC_TXN_BACKUP_ALL + "\n" + LOOKUP_SRC


def _resolves_to(node, name):
    """True where `node` names `name`, as a bare Name or as `S.<name>`.

    server_gui.py reaches every name that stays in server.py through the
    bind() seam (#207), so a read of one of them is an Attribute on `S`
    there rather than a bare Name - `_tray_icon[...]` in server.py is
    `S._tray_icon[...]` in server_gui.py, same dict, same read. A check
    built around `.id` alone sees the second spelling as something else
    entirely, so this is the one place that reads either.
    """
    if isinstance(node, ast.Name) and node.id == name:
        return True
    return (isinstance(node, ast.Attribute) and node.attr == name
            and isinstance(node.value, ast.Name) and node.value.id == "S")


def _call_name(func):
    """The name a Call node's `func` reads as, Name or S.<name> alike."""
    if isinstance(func, ast.Name):
        return func.id
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id == "S"):
        return func.attr
    return ""


_stage_seq = [0]


def stage_name(prefix, suffix=""):
    """A name inside STAGE no earlier call has handed out.

    Counted, rather than taken from the number of entries in STAGE, which is
    what every helper here did and which is not a unique-name generator at
    all: it assumes the directory only ever grows and that each name it hands
    out leaves exactly one entry behind. Neither holds. Eight groups here
    remove a file - a certificate, a stored secret - and the moment a removal
    drops the count back onto a name that already exists the scheme latches,
    because the colliding call creates no new entry either: the count never
    moves again and every later call reuses that one file.

    What that costs is the whole point of fresh_db. init_db is idempotent, so
    a reused path keeps every row already in it and the database handed back
    is not fresh. One run handed check_173.db to five groups in a row: the
    certificate group wrote junk.pem and ssl_cert.pem (170 -> 173, so
    check_173.db was created) and a later one removed ssl_cert.pem (back to
    173, where check_173.db already sat) - so a System Log group expecting a
    handful of its own entries was handed dozens from every domain that had
    run before it. It reads as a flake because which files exist when depends
    on which groups skipped - no display, no pillow, no openpyxl - so the run
    that latches and the run that does not are the same suite on two
    machines.

    A counter in a list rather than itertools, for the idiom the module under
    test uses for exactly this.
    """
    _stage_seq[0] += 1
    return os.path.join(STAGE, "%s%d%s" % (prefix, _stage_seq[0], suffix))


def fresh_db():
    """An empty, initialised database, pointed at by the module under test."""
    path = stage_name("check_", ".db")
    M.DB_PATH = path
    M.init_db()
    return path


def write_server_cfg(d):
    with io.open(M.SERVER_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f)


def read_server_cfg():
    with io.open(M.SERVER_CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_admin_cfg(text):
    with io.open(M.ADMIN_CFG_PATH, "w", encoding="utf-8") as f:
        f.write(text)


_stored_forms = {}


def stored_form(password):
    """The salted stored form of `password`, as an install would hold it.

    Memoised for two reasons: hashing is deliberately slow now (see ADR-0008),
    and a check that writes a hash into a config and then reads the file back
    wants the same string both times. That two *installs* given the same
    password store different values is asserted where it belongs, in the
    password group, not worked around here.
    """
    if password not in _stored_forms:
        _stored_forms[password] = M.hash_password(password)
    return _stored_forms[password]


def legacy(password):
    """The stored form every install written before ADR-0008 holds.

    A bare unsalted SHA-256 hex digest, built here rather than asked of
    server.py: the point of the legacy branch is to read a value this build
    would never write, so a helper in server.py that wrote one would be a way
    back to the format the ticket removed.
    """
    return hashlib.sha256(password.encode()).hexdigest()


def add_txn(db, **kw):
    row = {"asset_type": "Laptop", "serial_number": "", "asset_number": "",
           "asset_model": "", "team_member": "Brian Dawson",
           "direction": "Out Store", "timestamp": datetime.now().isoformat(),
           "confirmed": 0, "rejected": 0, "confirmed_at": "",
           "rejection_reason": "", "notes": "", "storekeeper": "Storekeeper User"}
    row.update(kw)
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO transactions (%s) VALUES (%s)"
        % (", ".join(row), ", ".join("?" * len(row))), tuple(row.values()))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def txn(db, tid):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    conn.close()
    return dict(r)

# ── fixtures more than one group reads ───────────────────────────────────────



def _member_hash(db, name):
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT password_hash FROM team_members WHERE name=?",
                       (name,)).fetchone()
    conn.close()
    return row[0]


def _log_rows(db, event=None):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        if event:
            rows = conn.execute("SELECT * FROM system_log WHERE event=?"
                                " ORDER BY id", (event,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM system_log ORDER BY id"
                                ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _add_client(db, client_id, member):
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO clients(client_id, hostname, os_user, app,"
                 " version, member, address, first_seen, last_seen)"
                 " VALUES (?, 'LAPTOP-1', 'user', 'Notifier', '2.3.0', ?,"
                 " '192.0.2.7', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                 (client_id, member))
    conn.commit()
    conn.close()


def tk_or_skip():
    """Tk, or None having already said why - the two ways it is unavailable.

    Every group below that measures a real widget needs both answers, and a
    machine with no desktop is not a failing server: these skip rather than
    fail so the rest of this file stays runnable over SSH.
    """
    try:
        import tkinter as tk
    except Exception as ex:
        skip("tkinter unavailable (%s)" % ex)
        return None
    try:
        tk.Tk().destroy()
    except Exception as ex:
        skip("no display for Tk (%s)" % ex)
        return None
    return tk


def gui_root(tk, tray=False):
    """Open the real Server GUI and hand back its root window.

    `tray` is off for every group but the one that reads the tooltip: a
    tray icon is a thread and an image, and a window that needs neither
    should not be made to carry them.

    run_gui() ends in mainloop, which never returns, so mainloop is stubbed for
    the length of the call and put back afterwards. The window has to be the
    real one: a size only Tk knows is the whole subject of these groups, and a
    form rebuilt inside the harness would be measuring the harness.
    """
    M.HAS_TRAY = bool(tray)
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    # The console door is already answered. Every group that opens a window
    # here is opening one an Admin has walked through - _console_unlock holds
    # its answer per process for exactly that reason (ADR-0015) - and a modal
    # password prompt with nobody to answer it would hang the gate rather than
    # fail it. What the door itself does is asserted as source, in the group
    # that holds each of the four windows to calling it.
    M._CONSOLE_UNLOCKED[0] = True
    # Database Location and Backup / Restore ask again on every open
    # (`_admin_again`, 090) whatever the flag above says - answered here for
    # the same reason; that the two rows name it is asserted as source.
    GM._admin_again = lambda parent, what: True
    real = tk.Tk.mainloop
    tk.Tk.mainloop = lambda self: None
    try:
        M.run_gui()
    finally:
        tk.Tk.mainloop = real
    root = tk._default_root
    root.update_idletasks()
    root.update()
    return root


def widgets(w, out=None):
    """Every widget under w, w included."""
    out = [] if out is None else out
    out.append(w)
    for c in w.winfo_children():
        widgets(c, out)
    return out


# ── the System Log ───────────────────────────────────────────────────────────

def log_rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM system_log ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── cancellation ─────────────────────────────────────────────────────────────

def _blank_lookup():
    """Empty the Lookup Sheet, so POST /transactions skips rule 6.

    An empty Lookup Sheet is a documented skip - nothing to check against is
    not the same as an unknown asset - and it is what lets these checks use
    made-up asset numbers instead of hunting real ones out of the embedded
    workbook.
    Since 024 that is the `assets` table rather than the workbook; the
    unreadable sheet staged at the top of this file is what stops init_db
    filling each new database from the embedded one in the first place.
    """
    conn = sqlite3.connect(M.DB_PATH)
    conn.execute("DELETE FROM assets")
    conn.commit()
    conn.close()


def moved_db(name):
    """An initialised database in its own directory under the scratch tree."""
    d = os.path.join(STAGE, name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "assets.db")
    keep = M.DB_PATH
    M.DB_PATH = path
    M.init_db()
    M.DB_PATH = keep
    return path


def stage_import(name, cfg):
    """Import a fresh copy of server.py with a given server_config.json.

    DB_PATH is derived from _SERVER_CFG at import time, which is the whole
    point of the movable database, so setting M.DB_PATH on the already-imported
    module would test something the server never does. Importing for real also
    catches the import-order hazard head on: the assignment has to sit below
    _SERVER_CFG and below the validator, and getting that wrong is a NameError
    at import rather than a subtle wrong answer later.

    Returns (module, directory). The directory is inside STAGE, so it goes with
    everything else when the run finishes.
    """
    d = os.path.join(STAGE, name)
    os.makedirs(d, exist_ok=True)
    for _f in SERVER_SRC:
        shutil.copy2(os.path.join(R, _f), os.path.join(d, _f))
    with io.open(os.path.join(d, "server_config.json"), "w",
                 encoding="utf-8") as f:
        json.dump(cfg, f)
    spec = _iu.spec_from_file_location("srv_" + name,
                                       os.path.join(d, "server.py"))
    mod = _iu.module_from_spec(spec)
    # See the same registration above M's own load - server.py's bind() call
    # reaches for sys.modules[__name__].
    sys.modules[spec.name] = mod
    # Its own server_cert, server_gui, the three registers and the mail,
    # sync, clients and log modules too, or the copies
    # imported here would be the ones M is bound to: server_gui holds the
    # server.py it was last bound to (see its bind()), server_cert the paths
    # and helpers of whichever server.py imported it last, and the two
    # registers the get_db of the same (see their own bind()s), so a second
    # import over the top of any of them would leave M's console, certificate
    # functions and both sets of writers reading this staged directory. One
    # server per process is what a real install has; this file is the only
    # thing anywhere that imports two.
    # Held by name rather than in twenty-one _kept_* locals: the nine window
    # modules #235 added are the same problem as the twelve above them - each
    # one holds the server_gui it was imported under, so a copy left in
    # sys.modules would leave this staged console drawing against the other
    # server.
    _kept = {}
    for _m in SERVER_SRC:
        _m = _m[:-3]
        if _m == "server":
            continue
        _kept[_m] = sys.modules.pop(_m, None)
    sys.path.insert(0, d)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(d)
        for _m, _was in _kept.items():
            sys.modules.pop(_m, None)
            if _was is not None:
                sys.modules[_m] = _was
    return mod, d


# ── the Admin can add a Transaction after the fact ──────────────────

def _stub_lookup(rows):
    """Put known assets in the Lookup Sheet.

    _blank_lookup above is for checks that need rule 6 to skip; this is the
    other half, for the ones that need it populated and correcting what it
    is handed. The tuples keep the sheet's own order - asset number,
    serial number, type, model - since that is the order every caller here was
    already written in, and it is still the order of the interchange format.
    Written through `_save_asset`, the one writer, rather than into the table
    directly: a helper with its own INSERT would be a second door in the one
    file that checks there is only one.
    """
    _blank_lookup()
    for r in rows:
        M._save_asset(r[0], r[1], r[2], r[3] if len(r) > 3 else "")


def _owners_of(needle):
    """Every function whose own body holds `needle`, innermost only.

    A plain get_source_segment scan would report run_gui for anything in any of
    its dialogs, which is most of the GUI.

    Over the register too since #216: `INSERT INTO transactions` and the
    cancel's UPDATE moved out with their functions, and the one thing every
    caller of this asks is whether a *second* function holds the same string.
    Nothing in `register_transactions.py` carries the asset-proposal or
    `_save_asset` needles the other callers pass, so the wider text changes no
    answer but that one.

    And over `server_archive.py` too since #228, for the same reason one
    ticket later: `_import_records_xlsx` is the second writer of a
    Transaction row and it moved there with the export it is the
    counterpart of. It carries neither of the other two needles either.
    """
    found = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, n):
            self.stack.append(n.name)
            self.generic_visit(n)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Constant(self, n):
            if isinstance(n.value, str) and needle in n.value and self.stack:
                found.append(self.stack[-1])

    V().visit(ast.parse(SRC_OWNERS_ALL))
    return set(found)


# ── the Admin can correct a Pending Transaction ─────────────────────

def _admin():
    """Set the module's admin password to "admin"."""
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}


def clients(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM clients ORDER BY last_seen DESC")]
    conn.close()
    return rows


def checkin(body, address="192.0.2.42"):
    return M.app.test_client().post("/clients/checkin", json=body,
                                    environ_base={"REMOTE_ADDR": address})


def commands(db, client_id=None):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM client_commands"
    args = ()
    if client_id is not None:
        sql += " WHERE client_id=?"
        args = (client_id,)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]
    conn.close()
    return rows


def seen(cid, host="HOST-LT-01", app="Notifier"):
    """A Client that has checked in, which is the only kind that can be sent
    a command."""
    return checkin({"client_id": cid, "hostname": host, "app": app,
                    "version": "2.3.0", "member": "Brian Dawson"})


# ── capability passwords ─────────────────────────────────────────────────────

def _caps(**caps):
    """Admin password "admin", plus a password of its own per capability."""
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False,
                   "capability_hashes": {c: stored_form(p)
                                         for c, p in caps.items()}}


def _code(fn):
    """A function's source without its docstring.

    Several checks below assert that a function does *not* mention something,
    and a docstring explaining why it does not would fail them - which is how
    the Capability Passwords dialog came to look as though it called
    _authorise.
    """
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and \
            isinstance(body[0].value, ast.Constant) and \
            isinstance(body[0].value.value, str):
        body = body[1:]
    return chr(10).join(ast.unparse(n) for n in body)


# ── the server holds writes (G3, ADR-0018) ─────────────────────────────────────────────


def _clear_log(db):
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM system_log")
    conn.commit()
    conn.close()


def _no_maintenance():
    """Leave nothing behind between these checks."""
    try:
        os.remove(M.MAINTENANCE_PATH)
    except OSError:
        pass
    M._HELD_SEEN.clear()
