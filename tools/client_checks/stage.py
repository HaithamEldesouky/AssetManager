r"""The staging tree every check group reads, and the fixtures they share.

Split out of tools/client-checks.py by #238, the way #221 split
tools/server-checks.py; what that file's own docstring said about staging is
said here, where the staging is.

**It stages copies of the app sources in a scratch directory and imports those,
never the ones in the repo.** Every path in these apps resolves next to the
source file, so importing the repo's copy would read - and, the first time an
app saves anything, write - the developer's own config.json beside the checkout.
Same reason server-checks.py stages server.py and dev-run.ps1 gives each app its
own directory.

**applaunch.py is staged too, and it is not a window.** It is what Windows
actually starts in source mode, and the one thing in this repo that has to work
when the install is broken - so its reporter is driven here rather than left to
the three apps' own groups, with tkinter taken away, which is the state that
made the whole of it mute in the field.

**No server.** `api` is replaced with a function that raises, which is the
offline path all three apps already handle: the engineer list falls back to
TEAM_MEMBERS, the heartbeat reports Offline, and nothing here needs an answer
that only a real server can give. Pointing this at asset-server would be worse
than useless - it would file a check-in from whatever machine ran the gate.

One tree, built once at import, for every group in the package: a second
staging tree per group file would be a second copy of every app imported, and
the groups hand each other no state to be confused by - each builds the app
and window it needs and tears it down.

The reporting half lives here too - ok(), bad(), skip(), head(), eq() and the
counters behind them - and so do the Tk helpers every window group measures
with, so that a group file holds check functions and the fixtures only it
reads, and the last line of a run counts every group's assertions in one place.
A helper in this file is one more than one group reads; a helper only one group
reads sits in that group's file.
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile
import time
import importlib.util as iu

import _offscreen

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

R = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
APPS = ("storekeeper_app.py", "notifier_app.py", "installer.py")
fails = []


# -- how much of a run is printed, and which slice of it runs ----------------
# Both flags exist for the same measurement: 69 groups, three minutes and 928 lines of [OK]. A wall of green
# is not read, and a serial run of it is not run either - which is how a gate
# stops being a gate and becomes a thing to skip.
#
#   -v / --verbose   print every passing line, the way this file always did
#   --shard i/n      run only every n-th group starting at the i-th, so
#                    tools/gate.py can run n copies of this at once
#   --group NAME     run one group module alone, for iterating on it
#   --list-groups    print the group names and exit
#   --check NAME     run one check_* group alone, one step smaller again
#   --list-checks    print the check group names and exit
#
# The slice is by position rather than by name so that adding a group needs no
# list kept anywhere. Groups do not hand each other state - each builds the
# app and window it needs and tears it down - so any slice of them is a valid run;
# what a shard cannot say is that the *whole* file is green, which is why
# gate.py aggregates the exit codes rather than trusting one of them.
#
# Quiet is the default rather than the flag because a skipped assertion is the
# failure mode this file has: the counts on the last line are what says a run
# asserted as much as the last one did, and a skip is counted there rather than
# swallowed - a group that quietly stopped measuring reads as a drop in the
# count instead of as a clean run.
ARGV = sys.argv[1:]
USAGE = r"""usage: py -3.12 tools\client-checks.py [-v] [--shard i/n] [--group NAME]
                                    [--check NAME]

  -v, --verbose  print every passing assertion rather than the last line only
  --shard i/n    run every n-th check starting at the i-th, for tools\gate.py
  --group NAME   run one group of tools/client_checks/ alone, for iterating
  --list-groups  print the group names and exit
  --check NAME   run one check_* group alone, for iterating on it
  --list-checks  print the check group names and exit
  -h, --help     print this and exit
"""
VERBOSE = False
SHARD = (1, 1)
GROUP = None
LIST_GROUPS = False
CHECK = None
LIST_CHECKS = False

# An argument this does not know is refused rather than skipped past, the same
# as server-checks.py and for the same two reasons: `--help` on a three-minute
# suite used to print nothing and run for three minutes, and a mistyped
# `--shrad 3/8` used to run the whole file while reading as a shard - silently,
# and green, since gate.py aggregates exit codes rather than counts.
#
# --group names one module of this package, the same unit server-checks.py's
# --group names, and it is the one flag here that needs the list of groups kept
# somewhere. That list already exists, in client-checks.py, which is where the
# name is checked: this file only carries what was asked for. --check is one
# step smaller - one check_* function - and was this file's only selector while
# it was a single module; its names come off the functions main() collects, so
# it needs no list at all.
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
    elif _a == "--list-checks":
        LIST_CHECKS = True
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
    elif _a == "--check":
        if not _args:
            raise SystemExit("--check wants a check group name - "
                             "--list-checks prints them")
        CHECK = _args.pop(0)
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


def eq(label, got, want):
    """ok/bad against an expected value, for a check that is not a measurement.

    The size groups above report what they measured, because the number is the
    finding. A branch has no number: what is worth printing is which of two
    windows opened, so the comparison is written once here rather than as an
    if in every assertion.
    """
    if got == want:
        ok("%s" % label)
    else:
        bad("%s: got %r, wanted %r" % (label, got, want))


def head(msg):
    if VERBOSE:
        print("\n=== %s ===" % msg)
        _group[0] = None          # already on the screen; bad() need not
    else:
        _group[0] = msg


# -- staging ------------------------------------------------------------------

STAGE = tempfile.mkdtemp(prefix="client-checks_")
# client_update.py comes along because both clients import it at module
# scope. It imports nothing of ours itself - `common` is imported inside
# fetch() - so staging it pulls nothing else in.
# applaunch.py is staged beside them but is deliberately not in APPS: it opens
# no window and has no form, so the size groups have nothing to say about it.
# notifier_pending.py is here for the first reason and not the second - the
# Notifier imports it at module scope, and it has a group of its own that opens
# no window either. notifier_remote.py is here for the first reason alone: the
# Notifier imports it at module scope too, and it is nine Remote Admin windows
# that the size groups below measure exactly as they did when the classes sat
# in notifier_app.py (#218). storekeeper_export.py is here for the same one
# (#219): the Storekeeper imports it at module scope, and it is the Export
# window the size groups measure as they did when it sat in that app's file.
# storekeeper_bulk.py is the same again (#236), for the Bulk submit window,
# and storekeeper_propose.py (#237), for the Propose and Import dialogs.
for _name in APPS + ("common.py", "ui_kit.py",
                     "client_update.py",
                     "applaunch.py", "notifier_pending.py",
                     "notifier_remote.py", "storekeeper_export.py",
                     "storekeeper_bulk.py", "storekeeper_propose.py"):
    shutil.copy2(os.path.join(R, _name), os.path.join(STAGE, _name))
# The Notifier reads current_user out of this at import-time module scope, and
# writing one here is also what keeps the apps off the developer's own copy.
with io.open(os.path.join(STAGE, "config.json"), "w", encoding="utf-8") as _f:
    json.dump({"server_url": "http://127.0.0.1:1",
               "current_user": "Brian Dawson",
               "poll_interval": 15,
               "setup_complete": True,
               "client_id": "client-checks"}, _f)
sys.path.insert(0, STAGE)


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


# The files a check reads as *text*, which is two more than the apps: the
# Notifier has been two files since #218 and the Storekeeper two since #219,
# and a sweep that walked only APPS would stop reading nine Remote Admin
# windows and the Export window without saying so - it would go on passing,
# about less and less. APPS itself is unchanged, because it is the list of
# things with an entry point and a window to build, and neither of those two
# has either.
SRC_FILES = APPS + ("notifier_remote.py", "storekeeper_export.py",
                    "storekeeper_bulk.py", "storekeeper_propose.py")
SRC = {}
for _name in SRC_FILES:
    SRC[_name] = io.open(os.path.join(R, _name),
                         encoding="utf-8", newline="").read()


def _load(name, modname):
    spec = iu.spec_from_file_location(modname, os.path.join(STAGE, name))
    mod = iu.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def _offline(*_a, **_k):
    raise OSError("client-checks: there is deliberately no server")


try:
    C = _load("common.py", "common")
    # Before notifier_app.py, so that app's own `import notifier_pending`
    # and `import notifier_remote` find these staged copies in sys.modules
    # rather than importing a second one off sys.path - a check that rebinds
    # something here has to be seen by the app reading it, and the Remote
    # Admin groups below rebind NR.SettingsWindow to watch the tray open it.
    NP = _load("notifier_pending.py", "notifier_pending")
    NR = _load("notifier_remote.py", "notifier_remote")
    # Before storekeeper_app.py, for the same reason and with the same
    # consequence: the export group below stubs SE.messagebox, and the app's
    # own `import storekeeper_export` has to find this staged copy rather
    # than a second one off sys.path.
    SE = _load("storekeeper_export.py", "storekeeper_export")
    # And the Bulk submit window (#236), whose two groups stub SB.messagebox
    # and SB.api.
    SB = _load("storekeeper_bulk.py", "storekeeper_bulk")
    # And the Propose and Import dialogs (#237).
    SP = _load("storekeeper_propose.py", "storekeeper_propose")
    SK = _load("storekeeper_app.py", "storekeeper_app")
    NT = _load("notifier_app.py", "notifier_app")
    IN = _load("installer.py", "installer")
    AL = _load("applaunch.py", "applaunch")
except ImportError as _ex:
    print("cannot import the client apps: %s" % _ex)
    print("run with the interpreter that has their dependencies, e.g."
          "  py -3.12 tools\\client-checks.py")
    sys.exit(2)

assert os.path.dirname(SK.CONFIG_PATH) == STAGE, "staging did not take"
assert os.path.dirname(NT.CONFIG_PATH) == STAGE, "staging did not take"

# Every door out to the network, closed. `api` is imported by name into each of
# the three apps, so each copy of the name has to be replaced.
C.api = _offline
# Five copies since #219: notifier_remote.py imports `api` by name too, and
# the door it opens is the console's rather than the tray's, and
# storekeeper_export.py imports it for the history the Export window reads.
NR.api = _offline
SE.api = _offline
for _m in (SK, NT, IN):
    _m.api = _offline
    _m.checkin = lambda *a, **k: {}
    _m.sync_server_cert = lambda *a, **k: None
NT.HAS_TRAY = False

# The background ticks, silenced at the class rather than on the instance: each
# is handed to after() inside __init__, which resolves the bound method there
# and then, so replacing the attribute afterwards is too late. They fetch from a
# server that is deliberately absent, so nothing on screen changes - what goes
# away is a worker thread reaching for Tk after this file has destroyed the
# root, which prints a traceback that reads like a failure and is not one.
SK.StorekeeperApp._check_server = lambda self: None
SK.StorekeeperApp._refresh_transactions = lambda self: None
SK.StorekeeperApp._tick_background = lambda self: None
SK.StorekeeperApp._check_update = lambda self: None
NT.NotifierApp._poll_loop = lambda self: None
NT.NotifierApp._check_update = lambda self: None


# -- Tk ------------------------------------------------------------------------

def tk_or_skip():
    """Tk, or None having already said why - the two ways it is unavailable.

    A machine with no desktop is not a broken client: these skip rather than
    fail so the file stays runnable over SSH, the same as server-checks.py.
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


def widgets(w, out=None):
    """Every widget under w, w included."""
    out = [] if out is None else out
    out.append(w)
    for c in w.winfo_children():
        widgets(c, out)
    return out


def controls(tk, win):
    """The clickable things in a window, bottom-most last.

    A tk.Button is one; a ui_kit.Pill is a rounded polygon on a canvas, so it
    is the other. Sorted by where they sit, because the question every group
    below asks is about whichever one is at the bottom - that is the one pack
    squeezes, and the one a form's submit button always is.
    """
    out = []
    for x in widgets(win):
        if x.winfo_class() == "Button" or getattr(x, "_ui_row", None):
            out.append(x)
        # A ui_kit.Pill is a rounded polygon on a canvas rather than a Button,
        # and it is not always inside a Row: the Notifier's popup footer is a
        # flat CARD2 frame carrying two of them (#180) and the Dashboard's
        # controls are packed the same way, so a walk that only knew about
        # rows reported those windows as having no button at all. The pill
        # hangs itself off its own canvas for exactly this - "anything
        # checking this window from outside it".
        elif getattr(x, "_pill", None) is not None:
            out.append(x)
        elif isinstance(x, tk.Canvas) and x.master is not None \
                and getattr(x.master, "_ui_row", None):
            out.append(x)
    return sorted(out, key=lambda x: (x.winfo_rooty(), x.winfo_rootx()))


def measure(tk, label, win):
    """Both axes of one window against what its children asked for.

    Each axis is judged on its own - a height shortfall used to hide a width
    one - and only where that axis is fixed. A resizable axis can be dragged
    open, so a shortfall there costs a drag rather than a control; it is
    reported and not failed, because passing it silently is how a window comes
    to be reported as holding a size it does not.
    """
    win.update_idletasks()
    win.update()
    grow_w, grow_h = win.resizable()
    w, h = win.winfo_width(), win.winfo_height()
    rw, rh = win.winfo_reqwidth(), win.winfo_reqheight()
    for axis, short, grow, cost in (
            ("shorter", rh - h, grow_h,
             "whatever is packed last is being squeezed"),
            ("narrower", rw - w, grow_w, "a label in it is being clipped")):
        if short <= 0:
            continue
        if grow:
            ok("%s is %dpx %s than its children ask for, but that axis is "
               "resizable - a drag, not a lost control" % (label, short, axis))
        else:
            bad("%s is %dpx %s than its children ask for (%dx%d of %dx%d) - %s"
                % (label, short, axis, w, h, rw, rh, cost))
    if rh <= h and rw <= w:
        ok("%s: %dx%d holds its children's %dx%d" % (label, w, h, rw, rh))


def measure_scrolled_body(tk, label, win):
    """The form inside a scrolling canvas, which the window cannot ask about.

    winfo_reqwidth() of a tk.Canvas is the width the canvas was configured
    with, not the width of the frame windowed into it with create_window. So a
    window whose whole body is a canvas reports the same request whatever form
    is in it - the installer's three component forms all measured 395x321,
    three different forms and one number, which is a measurement that cannot
    fail rather than one that passed. The frame is asked directly instead.

    Only the axis the canvas does not scroll is judged. A taller form scrolls
    into view, which is the reason the installer keeps a written height and
    does not call ui_kit.fit; a wider one has nowhere to go, and width is the
    axis resizable(False, True) pins.
    """
    grow_w, _grow_h = win.resizable()
    win.update_idletasks()
    for f in widgets(win):
        if f.winfo_class() != "Frame" or not isinstance(f.master, tk.Canvas):
            continue
        room, need = f.master.winfo_width(), f.winfo_reqwidth()
        if need <= room:
            ok("%s: its scrolling body gives %dpx to a form asking %dpx"
               % (label, room, need))
        elif grow_w:
            ok("%s: its scrolling body is %dpx narrower than the form asks "
               "for, but that axis is resizable - a drag, not a lost label"
               % (label, need - room))
        else:
            bad("%s: its scrolling body is %dpx narrower than the form asks "
                "for (%dpx of %dpx) - a label in it is clipped, and the only "
                "scrollbar there is vertical"
                % (label, need - room, room, need))


def scroll_reaches_its_form(tk, label, win):
    """The scroll region covers every row of the form inside it (#199).

    `measure_scrolled_body` above asks the other axis - whether the form is
    clipped sideways - and `measure` asks about the window. Neither can see a
    region whose `scrollregion` stops short of the body it holds, because the
    window is exactly as tall as it asked to be either way and what is out of
    reach is out of reach silently. Rows nobody can scroll to are the same
    loss as a window too short for its children, one layer further in.
    """
    win.update_idletasks()
    found = False
    for f in widgets(win):
        if f.winfo_class() != "Frame" or not isinstance(f.master, tk.Canvas):
            continue
        found = True
        needs = f.winfo_reqheight()
        got = str(f.master.cget("scrollregion")).split()
        reach = int(float(got[3])) if len(got) == 4 else 0
        if reach >= needs:
            ok("%s: %dpx of scroll for a form asking %dpx, so every row of it "
               "is reachable" % (label, reach, needs))
        else:
            bad("%s: the scroll region stops at %dpx and the form asks for "
                "%dpx, so what does not fit is unreachable rather than "
                "scrolled to" % (label, reach, needs))
    if not found:
        bad("%s has no scroll region at all - a form with no bound meets "
            "ui_kit.fit's clamp and loses the rest" % label)


def pinned(tk, win, items):
    """Of those controls, the ones outside any scrolling body (#199).

    `controls` sorts by where a widget sits, and once a window's form scrolls
    that is no longer the same question: the bottom-most control in a window
    holding 25 notification rules is the last card's own Remove button, two
    thousand pixels down a body the canvas is clipping, and asking whether
    *that* survives a 150px screen is asking whether a scroll region scrolls.
    What the group below is about is the footer - the control pinned outside
    the region, which is the whole reason the region has one.

    A window whose **every** control is inside the region is answered with all
    of them rather than with none: the installer is one window in a process of
    its own and scrolls its whole form, footer included, so filtering there
    would turn a measurement into "this window has no button at all".
    """
    bodies = [str(f) for f in widgets(win)
              if f.winfo_class() == "Frame" and isinstance(f.master, tk.Canvas)]
    out = [x for x in items
           if not any(str(x).startswith(b + ".") for b in bodies)]
    return out or items


def survives_a_short_screen(tk, label, win):
    """Force the window far shorter than any screen and read the button back.

    Sizing to the request makes a squeezed button rare, not impossible: a
    screen shorter than the dialog cannot be argued with, and ui_kit.fit clamps
    the height for exactly that case. The other half of the fix only shows
    here - the footer packed before the form, which puts the button first in
    the queue for the space rather than last.

    The clamp cannot be reached from a harness, so it is imposed.
    """
    bottom = pinned(tk, win, controls(tk, win))
    if not bottom:
        bad("%s has no button at all" % label)
        return
    btn = bottom[-1]
    width = win.winfo_width()
    worst = None
    for h in (260, 200, 150):
        win.geometry("%dx%d" % (width, h))
        win.update_idletasks()
        win.update()
        top = btn.winfo_rooty() - win.winfo_rooty()
        if not btn.winfo_ismapped():
            worst = "at %dpx tall its bottom control is not mapped" % h
        elif btn.winfo_height() < 20:
            worst = ("at %dpx tall its bottom control is %dpx, which is not a "
                     "button" % (h, btn.winfo_height()))
        elif top + btn.winfo_height() > win.winfo_height():
            worst = ("at %dpx tall its bottom control ends %dpx below the "
                     "bottom edge" % (h, top + btn.winfo_height()
                                      - win.winfo_height()))
    if worst:
        bad("%s: %s" % (label, worst))
    else:
        ok("%s: its bottom control survives being forced to 150px" % label)


def survives_its_own_floor(tk, label, win):
    """Hold it at the smallest a user can drag it to and read the control back.

    `measure` above judges an axis only where it is fixed, because a resizable
    one can be dragged open - and that is true and is only half of it: it can
    be dragged **shut** as well, and how far is a number the window itself
    wrote down. A `minsize` is therefore not a detail of a resizable window,
    it is the only floor there is, and one that sets none can be pulled down
    to nothing with `pack` giving the shortfall to whichever child went in
    last (#192). `tools/server-checks.py` holds the console's dialogs to
    exactly this; these three apps had no such check at all.

    **Both axes**, because the loss is not always vertical. A footer is packed
    along the width, so what a narrow window takes is its right-hand end - the
    Save this window is opened to press - while the height is untouched and a
    vertical-only probe reports it as fine.

    A window fixed on both axes has no floor to judge and is `measure`'s and
    `survives_a_short_screen`'s; it is skipped here rather than reported, the
    two groups above having already said everything about it.
    """
    grow_w, grow_h = win.resizable()
    # An `overrideredirect` window is drawn with no frame at all - no title
    # bar, no border, nothing a pointer can take hold of - so `resizable()`
    # answering True about it is the default nobody set rather than a size
    # anybody can change. The Notifier's popup is the one here, placed at a
    # fixed size in the bottom-right corner, and reporting it as floorless
    # would be asking for a `minsize` against a drag that cannot happen.
    if win.overrideredirect():
        return
    if not grow_w and not grow_h:
        return
    bottom = controls(tk, win)
    if not bottom:
        bad("%s has no button at all" % label)
        return
    btn = bottom[-1]
    win.update_idletasks()
    floor_w, floor_h = win.minsize()
    for axis, grow, floor in (("width", grow_w, floor_w),
                              ("height", grow_h, floor_h)):
        if grow and floor <= 1:
            bad("%s can be dragged smaller on its %s and sets no minsize, so "
                "there is no floor to judge and no size it cannot be pulled "
                "below - give it one" % (label, axis))
            return
    w = floor_w if grow_w else win.winfo_width()
    h = floor_h if grow_h else win.winfo_height()
    win.geometry("%dx%d" % (w, h))
    win.update_idletasks()
    win.update()
    at = "%s at its own %dx%d minimum" % (label, w, h)
    top = btn.winfo_rooty() - win.winfo_rooty()
    left = btn.winfo_rootx() - win.winfo_rootx()
    if not btn.winfo_ismapped():
        bad("%s: its bottom control is not mapped" % at)
    elif btn.winfo_height() < 20:
        bad("%s: its bottom control is %dpx tall, which is not a button"
            % (at, btn.winfo_height()))
    elif top + btn.winfo_height() > win.winfo_height():
        bad("%s: its bottom control ends %dpx below the bottom edge"
            % (at, top + btn.winfo_height() - win.winfo_height()))
    elif left + btn.winfo_width() > win.winfo_width():
        bad("%s: its bottom control ends %dpx past the right-hand edge"
            % (at, left + btn.winfo_width() - win.winfo_width()))
    else:
        ok("%s: its %dx%d minimum holds its bottom control, so no drag can "
           "squeeze it out" % (label, w, h))


def opened(tk, root, label, opener):
    """Open it and hand back the windows it opened, or an empty list."""
    before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
    try:
        opener()
    except Exception as ex:
        bad("%s raised %s: %s" % (label, type(ex).__name__, ex))
        return []
    root.update_idletasks()
    root.update()
    new = [w for w in widgets(root)
           if isinstance(w, tk.Toplevel) and str(w) not in before]
    if not new:
        bad("%s opened no window" % label)
    return new


def close(root, wins):
    for w in wins:
        try:
            w.grab_release()
        except Exception:
            pass
        try:
            w.destroy()
        except Exception:
            pass
    try:
        root.update_idletasks()
    except Exception:
        pass


def quiesce(root):
    """Cancel every pending after() before the root goes.

    These apps re-arm their own ticks, so one is always outstanding; a tick
    that fires against a destroyed root is a Tcl background error printed
    straight to stderr, in the middle of this file's output.
    """
    try:
        for tid in root.tk.splitlist(root.tk.call("after", "info")):
            try:
                root.after_cancel(tid)
            except Exception:
                pass
        root.destroy()
    except Exception:
        pass


def pump_until(root, ready, bound=60.0):
    """Turn the event loop until `ready()` answers true, bounded (#205).

    The two popup groups drive real `after` timers, and until #205 they waited
    for one by turning the loop until a wall clock had passed the moment it
    was due plus a small margin. The margin was deliberately small - the whole
    argument for a real timer is that reaching past it would pass against a
    popup whose timer was never armed - and a small margin is a margin a busy
    machine eats. Measured: at four shards on an idle box the client suite runs
    in 120s and both groups are green; with other work running, the same four
    shards took 572s and the return leg went with it, `update()` not
    dispatching the queue anything like as often when it is one of a dozen
    processes competing for the cores.

    So the wait is on the **event** rather than on the clock, which is #204's
    lesson one level up: turn the loop until the thing being asserted has
    happened, and bound it at a minute - long enough that no load reaches it,
    short enough that a timer which never fires is reported rather than hung
    on. Waiting this way is also *tighter* than the margin was, not looser:
    the caller stops the moment the state arrives, so a leg asserting what is
    true in the meantime reads it before the next timer moves it on.

    It does not weaken the "the timer is real" argument, which is carried by
    the legs either side of the wait - that no job is armed at all when the
    setting is off, that one is when it is on, and, where it is worth a line,
    that the elapsed time was not shorter than the timer. A lower bound is the
    load-safe direction: load can only make a wait longer.
    """
    end = time.time() + bound
    while True:
        root.update_idletasks()
        root.update()
        if ready():
            return True
        if time.time() >= end:
            return False
        time.sleep(0.005)


def show_next(app, root):
    """Offer the next Transaction, and hand back the popup that went up (#205).

    `_show_next_popup` builds the window inside the call, so the popup is on
    `app` the moment it returns - except when a gap from an earlier hide has
    not run out, which is the one case it defers: it arms a timer for the
    moment the gap ends and shows nothing until then. So the wait belongs
    **only** on that case, and reading first is not an optimisation.

    Turning the loop unconditionally is what #205's first attempt did, and it
    was worse than the clock it replaced: a popup with auto-hide on goes up,
    hides itself a second later, and `_current_popup` is back to `None` - so a
    loop turning until it is not `None` waits out its whole bound for a window
    that had already been and gone. Measured, it cost the group 60s and a red.

    But #205 also dropped the loop turn from the case it left alone. A popup
    handed back the moment `_show_next_popup` returns has never been through
    `update()`, so its children are unrealised - the Dismiss pill's canvas
    still reads its parent's 1x1 - and an `event_generate` click aimed at it
    lands on nothing (#212). So the non-deferred branch gets its own single
    turn, `update_idletasks()` plus `update()` rather than a `pump_until`,
    since the popup is already there and only needs laying out, not waiting
    for.
    """
    app._show_next_popup()
    if app._current_popup is None:
        pump_until(root, lambda: app._current_popup is not None)
    else:
        root.update_idletasks()
        root.update()
    return app._current_popup


def run(tk, root, plan):
    """Measure each window in the plan, and shrink the fixed ones."""
    for label, opener, shrink in plan:
        wins = opened(tk, root, label, opener)
        for w in wins:
            measure(tk, label, w)
            if shrink:
                survives_a_short_screen(tk, label, w)
            survives_its_own_floor(tk, label, w)
        close(root, wins)


# -- read as source, by more than one group --------------------------------

def _enclosing_functions(tree):
    """Every node in the tree, mapped to the function it is written inside."""
    where = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            where.setdefault(node, fn.name)
    return where